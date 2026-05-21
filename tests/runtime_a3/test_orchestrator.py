"""Tests unitaires de l'orchestrateur runtime_a3.

Cf ADR_PARSE_EVALUATE_RUNTIME §2.1-§2.5 + §2.9.

Stratégie :
    - Mock chacun des 5 modules (Parser, Executor, Evaluator, Synthesizer)
    - Vérifier le séquencement Parse → Plan → Execute → Evaluate → Synthesize
    - Vérifier la boucle re-plan (AMBIGUOUS + hint != none + iter < 2)
    - Vérifier chacun des 6 hints (broaden_subject, add_qdrant_fallback,
      decompose_comparison, check_lifecycle, narrow_time_filter,
      drop_overspecific_filters)
    - Vérifier hard caps (max_iterations, wall-clock)
"""

from __future__ import annotations

import time
from unittest.mock import MagicMock

import pytest

from knowbase.runtime_a3.orchestrator import (
    IterationTrace,
    Orchestrator,
    OrchestratorResult,
    _augment_plan_for_hint,
    _broaden_subject,
    _modify_sub_goals_for_hint,
    apply_re_plan_hint,
    run_question,
)
from knowbase.runtime_a3.schemas import (
    CitedClaim,
    ClaimSummary,
    EvaluateOutput,
    ExecuteOutput,
    ParseInput,
    ParseOutput,
    PlanOutput,
    SubGoal,
    SynthesizeOutput,
    ToolCall,
    ToolResult,
)


# ============================================================================
# Helpers
# ============================================================================


def _po(
    sub_goals=None,
    raw_question="test question",
    parse_confidence=0.9,
) -> ParseOutput:
    return ParseOutput(
        sub_goals=sub_goals or [],
        entities=[],
        language="en",
        raw_question=raw_question,
        parse_confidence=parse_confidence,
        parse_warnings=[],
        schema_version="a3.0",
    )


def _eo_eval(verdict="CORRECT", hint="none", covered=None, uncovered=None) -> EvaluateOutput:
    return EvaluateOutput(
        verdict=verdict,
        covered_sub_goals=covered or [],
        uncovered_sub_goals=uncovered or [],
        re_plan_hint=hint,
        confidence=0.9,
        reasoning="test",
        schema_version="a3.0",
    )


def _eo_exec(results=None) -> ExecuteOutput:
    return ExecuteOutput(
        results=results or [],
        total_duration_s=0.05,
        schema_version="a3.0",
    )


def _tr(sub_goal_idx=0, n_claims=0, coverage="empty") -> ToolResult:
    return ToolResult(
        sub_goal_idx=sub_goal_idx,
        tool="kg_claims",
        claims=[ClaimSummary(claim_id=f"c_{i}") for i in range(n_claims)],
        coverage_signal=coverage,
        duration_s=0.01,
    )


def _so(answer="ok", mode="REASONED") -> SynthesizeOutput:
    return SynthesizeOutput(
        answer_text=answer,
        cited_claims=[],
        uncovered_sub_goals_warning=None,
        conflict_pending_warning=None,
        mode=mode,
        synthesize_warnings=[],
        citation_coverage_rate=1.0,
        schema_version="a3.0",
    )


def _make_parser_mock(parse_output):
    p = MagicMock()
    p.parse.return_value = parse_output
    return p


def _make_executor_mock_constant(execute_output_factory):
    """Crée un Executor mock dont .execute() retourne toujours une copie de l'output.

    `execute_output_factory` est un callable qui retourne un ExecuteOutput
    (appelé à chaque execute). Permet de varier sub_goal_idx selon le call.
    """
    ex = MagicMock()
    if callable(execute_output_factory):
        ex.execute.side_effect = lambda *args, **kwargs: execute_output_factory()
    else:
        ex.execute.return_value = execute_output_factory
    return ex


def _make_evaluator_mock_sequence(evaluate_outputs):
    """Mock evaluator qui retourne successivement chaque EvaluateOutput de la liste."""
    ev = MagicMock()
    ev.evaluate.side_effect = list(evaluate_outputs)
    return ev


def _make_synth_mock(synth_output):
    s = MagicMock()
    s.synthesize.return_value = synth_output
    return s


# ============================================================================
# _broaden_subject heuristic
# ============================================================================


class TestBroadenSubject:
    def test_strip_parenthesis(self):
        assert _broaden_subject("Product X (v2024)") == "Product X"

    def test_strip_comma(self):
        assert _broaden_subject("Product X, Edition Pro") == "Product X"

    def test_drop_last_token(self):
        assert _broaden_subject("Product X v2024") == "Product X"
        assert _broaden_subject("Product X") == "Product"

    def test_single_token_unchanged(self):
        assert _broaden_subject("Alpha") == "Alpha"

    def test_combined_strip_only_one_level(self):
        """Si qualifier présent, strip suffit (un seul niveau d'élargissement)."""
        assert _broaden_subject("Product X v2024 (Edition Pro), Premium") == "Product X v2024"


# ============================================================================
# _modify_sub_goals_for_hint
# ============================================================================


class TestModifySubGoals:
    def test_broaden_subject_affected_only(self):
        po = _po(sub_goals=[
            SubGoal(kind="fact_lookup", subject_canonical="Product X v2024"),
            SubGoal(kind="fact_lookup", subject_canonical="Product Y v2024"),
        ])
        new = _modify_sub_goals_for_hint("broaden_subject", po, affected_indices=[0])
        assert new.sub_goals[0].subject_canonical == "Product X"
        assert new.sub_goals[1].subject_canonical == "Product Y v2024"  # inchangé

    def test_narrow_time_filter(self):
        po = _po(sub_goals=[
            SubGoal(kind="lifecycle_trace", subject_canonical="X", time_filter="evolution"),
        ])
        new = _modify_sub_goals_for_hint("narrow_time_filter", po, affected_indices=[0])
        assert new.sub_goals[0].time_filter == "current"

    def test_drop_overspecific_filters(self):
        po = _po(sub_goals=[
            SubGoal(kind="fact_lookup", subject_canonical="X",
                    predicate_hint="some_pred", object_hint="some_obj"),
        ])
        new = _modify_sub_goals_for_hint("drop_overspecific_filters", po, affected_indices=[0])
        assert new.sub_goals[0].predicate_hint is None
        assert new.sub_goals[0].object_hint is None

    def test_decompose_comparison(self):
        po = _po(sub_goals=[
            SubGoal(kind="comparison", subject_canonical="A"),
        ])
        new = _modify_sub_goals_for_hint("decompose_comparison", po, affected_indices=[0])
        assert new.sub_goals[0].kind == "fact_lookup"

    def test_none_returns_same(self):
        po = _po(sub_goals=[SubGoal(kind="fact_lookup", subject_canonical="X")])
        new = _modify_sub_goals_for_hint("none", po, affected_indices=[0])
        assert new is po  # short-circuit return


# ============================================================================
# _augment_plan_for_hint
# ============================================================================


class TestAugmentPlan:
    def test_add_qdrant_fallback_appends_toolcall(self):
        po = _po(sub_goals=[SubGoal(kind="fact_lookup", subject_canonical="X")])
        plan_out = PlanOutput(tool_calls=[
            ToolCall(sub_goal_idx=0, tool="kg_claims", params={}, timeout_s=8.0),
        ])
        pi = ParseInput(question="test", tenant_id="default")
        new_plan = _augment_plan_for_hint("add_qdrant_fallback", plan_out, po, pi, [0])
        assert len(new_plan.tool_calls) == 2
        assert new_plan.tool_calls[-1].tool == "qdrant_sections"
        assert new_plan.tool_calls[-1].sub_goal_idx == 0

    def test_add_qdrant_fallback_idempotent(self):
        """Si qdrant_sections déjà présent pour cet idx, ne pas dupliquer."""
        po = _po(sub_goals=[SubGoal(kind="fact_lookup", subject_canonical="X")])
        plan_out = PlanOutput(tool_calls=[
            ToolCall(sub_goal_idx=0, tool="kg_claims", params={}, timeout_s=8.0),
            ToolCall(sub_goal_idx=0, tool="qdrant_sections", params={}, timeout_s=6.0),
        ])
        pi = ParseInput(question="test", tenant_id="default")
        new_plan = _augment_plan_for_hint("add_qdrant_fallback", plan_out, po, pi, [0])
        assert len(new_plan.tool_calls) == 2  # pas de duplication

    def test_check_lifecycle_appends_toolcall(self):
        po = _po(sub_goals=[SubGoal(kind="fact_lookup", subject_canonical="X")])
        plan_out = PlanOutput(tool_calls=[
            ToolCall(sub_goal_idx=0, tool="kg_claims", params={}, timeout_s=8.0),
        ])
        pi = ParseInput(question="test", tenant_id="default")
        new_plan = _augment_plan_for_hint("check_lifecycle", plan_out, po, pi, [0])
        assert len(new_plan.tool_calls) == 2
        assert new_plan.tool_calls[-1].tool == "lifecycle_query"

    def test_check_lifecycle_skips_no_subject(self):
        po = _po(sub_goals=[SubGoal(kind="fact_lookup", subject_canonical=None)])
        plan_out = PlanOutput(tool_calls=[])
        pi = ParseInput(question="test", tenant_id="default")
        new_plan = _augment_plan_for_hint("check_lifecycle", plan_out, po, pi, [0])
        assert len(new_plan.tool_calls) == 0  # subject None → pas de lifecycle

    def test_non_augmenting_hint_returns_same_plan(self):
        plan_out = PlanOutput(tool_calls=[])
        pi = ParseInput(question="test", tenant_id="default")
        po = _po()
        # broaden_subject n'ajoute pas de ToolCall (modifie le sub_goal)
        new_plan = _augment_plan_for_hint("broaden_subject", plan_out, po, pi, [0])
        assert new_plan is plan_out  # pas d'extra_calls → return original


# ============================================================================
# apply_re_plan_hint end-to-end
# ============================================================================


class TestApplyRePlanHint:
    def test_apply_broaden_subject_replans(self):
        po = _po(sub_goals=[
            SubGoal(kind="fact_lookup", subject_canonical="Product X v2024"),
        ])
        plan_out = PlanOutput(tool_calls=[
            ToolCall(sub_goal_idx=0, tool="kg_claims",
                     params={"subject": "Product X v2024"}, timeout_s=8.0),
        ])
        eo = _eo_eval(verdict="AMBIGUOUS", hint="broaden_subject", uncovered=[0])
        pi = ParseInput(question="test", tenant_id="default")
        new_parse, new_plan = apply_re_plan_hint("broaden_subject", po, plan_out, eo, pi)
        # ParseOutput modifié
        assert new_parse.sub_goals[0].subject_canonical == "Product X"
        # Plan re-généré avec nouveau subject
        assert any(
            tc.params.get("subject") == "Product X"
            for tc in new_plan.tool_calls
        )

    def test_apply_none_short_circuit(self):
        po = _po(sub_goals=[SubGoal(kind="fact_lookup", subject_canonical="X")])
        plan_out = PlanOutput(tool_calls=[])
        eo = _eo_eval(verdict="AMBIGUOUS", hint="none")
        pi = ParseInput(question="test", tenant_id="default")
        new_parse, new_plan = apply_re_plan_hint("none", po, plan_out, eo, pi)
        assert new_parse is po
        assert new_plan is plan_out


# ============================================================================
# Orchestrator — happy path (CORRECT iter 0)
# ============================================================================


class TestOrchestratorHappyPath:
    def test_single_iteration_correct(self):
        po = _po(sub_goals=[SubGoal(kind="fact_lookup", subject_canonical="X")])
        parser = _make_parser_mock(po)
        executor = _make_executor_mock_constant(_eo_exec(results=[_tr(n_claims=3, coverage="full")]))
        evaluator = _make_evaluator_mock_sequence([
            _eo_eval(verdict="CORRECT", covered=[0]),
        ])
        synth = _make_synth_mock(_so(answer="Got it"))

        orch = Orchestrator(parser=parser, executor=executor,
                            evaluator=evaluator, synthesizer=synth)
        result = orch.run("test question")

        assert len(result.iterations) == 1
        assert result.iterations[0].evaluate_output.verdict == "CORRECT"
        assert result.terminated_reason == "verdict_correct"
        assert result.synthesize_output.answer_text == "Got it"
        # Une seule évaluation appelée
        assert evaluator.evaluate.call_count == 1


# ============================================================================
# Orchestrator — re-plan loop
# ============================================================================


class TestOrchestratorReplanLoop:
    def test_ambiguous_iter0_then_correct_iter1(self):
        po = _po(sub_goals=[SubGoal(kind="fact_lookup", subject_canonical="Product X v2024")])
        parser = _make_parser_mock(po)
        executor = _make_executor_mock_constant(_eo_exec(results=[_tr(n_claims=0, coverage="empty")]))
        evaluator = _make_evaluator_mock_sequence([
            _eo_eval(verdict="AMBIGUOUS", hint="broaden_subject", uncovered=[0]),
            _eo_eval(verdict="CORRECT", covered=[0]),
        ])
        synth = _make_synth_mock(_so())
        orch = Orchestrator(parser=parser, executor=executor,
                            evaluator=evaluator, synthesizer=synth)
        result = orch.run("test")
        assert len(result.iterations) == 2
        assert result.iterations[0].evaluate_output.verdict == "AMBIGUOUS"
        assert result.iterations[1].evaluate_output.verdict == "CORRECT"
        assert result.terminated_reason == "verdict_correct"
        # iter 1 a vu re_plan_hint_applied = broaden_subject
        assert result.iterations[1].re_plan_hint_applied == "broaden_subject"

    def test_ambiguous_with_none_hint_terminates(self):
        po = _po(sub_goals=[SubGoal(kind="fact_lookup", subject_canonical="X")])
        parser = _make_parser_mock(po)
        executor = _make_executor_mock_constant(_eo_exec(results=[_tr()]))
        evaluator = _make_evaluator_mock_sequence([
            _eo_eval(verdict="AMBIGUOUS", hint="none", uncovered=[0]),
        ])
        synth = _make_synth_mock(_so())
        orch = Orchestrator(parser=parser, executor=executor,
                            evaluator=evaluator, synthesizer=synth)
        result = orch.run("test")
        assert len(result.iterations) == 1
        assert result.terminated_reason == "ambiguous_no_useful_hint"

    def test_ambiguous_at_max_iter_terminates(self):
        po = _po(sub_goals=[SubGoal(kind="fact_lookup", subject_canonical="X")])
        parser = _make_parser_mock(po)
        executor = _make_executor_mock_constant(_eo_exec(results=[_tr()]))
        # 2 itérations AMBIGUOUS → hard cap
        evaluator = _make_evaluator_mock_sequence([
            _eo_eval(verdict="AMBIGUOUS", hint="add_qdrant_fallback", uncovered=[0]),
            _eo_eval(verdict="AMBIGUOUS", hint="add_qdrant_fallback", uncovered=[0]),
        ])
        synth = _make_synth_mock(_so())
        orch = Orchestrator(parser=parser, executor=executor,
                            evaluator=evaluator, synthesizer=synth)
        result = orch.run("test")
        assert len(result.iterations) == 2
        assert result.terminated_reason == "ambiguous_at_hard_cap"

    def test_insufficient_terminates_immediately(self):
        po = _po(sub_goals=[SubGoal(kind="fact_lookup", subject_canonical="X")])
        parser = _make_parser_mock(po)
        executor = _make_executor_mock_constant(_eo_exec(results=[_tr()]))
        evaluator = _make_evaluator_mock_sequence([
            _eo_eval(verdict="INSUFFICIENT_EVIDENCE", uncovered=[0]),
        ])
        synth = _make_synth_mock(_so(mode="ABSTENTION"))
        orch = Orchestrator(parser=parser, executor=executor,
                            evaluator=evaluator, synthesizer=synth)
        result = orch.run("test")
        assert len(result.iterations) == 1
        assert result.terminated_reason == "verdict_insufficient_evidence"


# ============================================================================
# Orchestrator — wall-clock guard
# ============================================================================


class TestWallClockGuard:
    def test_wall_clock_zero_terminates(self):
        """Si max_wall_clock_s=0, on n'exécute aucune itération."""
        po = _po(sub_goals=[SubGoal(kind="fact_lookup", subject_canonical="X")])
        parser = _make_parser_mock(po)
        executor = MagicMock()
        evaluator = MagicMock()
        synth = MagicMock()

        # On simule un parse qui prend du temps avant la première itération
        original_parse = parser.parse
        def slow_parse(*args, **kwargs):
            time.sleep(0.05)
            return po
        parser.parse.side_effect = slow_parse

        orch = Orchestrator(
            parser=parser, executor=executor, evaluator=evaluator,
            synthesizer=synth, max_wall_clock_s=0.01,
        )
        result = orch.run("test")
        # Aucune itération exécutée (wall-clock dépassé après le parse)
        assert len(result.iterations) == 0
        assert result.terminated_reason == "wall_clock_timeout"
        # Synthesize emergency abstention
        assert result.synthesize_output.mode == "ABSTENTION"
        assert "emergency_abstention" in result.synthesize_output.synthesize_warnings[0]


# ============================================================================
# Each hint integration (re-plan applied → effect visible)
# ============================================================================


class TestEachHintIntegration:
    """Vérifie que chaque hint produit l'effet attendu sur ParseOutput/PlanOutput."""

    def _setup_orchestrator_with_hint(self, hint, sub_goal):
        """Crée un orchestrator qui à iter=0 dit AMBIGUOUS+hint, iter=1 dit CORRECT.
        Retourne (orch, result) pour les assertions.
        """
        po = _po(sub_goals=[sub_goal])
        parser = _make_parser_mock(po)
        # On capture le ParseOutput utilisé à chaque execute()
        # via une factory closure
        execute_call_count = [0]

        def execute_factory(*args, **kwargs):
            execute_call_count[0] += 1
            return _eo_exec(results=[_tr(n_claims=3, coverage="full")])

        executor = MagicMock()
        executor.execute.side_effect = execute_factory

        evaluator = _make_evaluator_mock_sequence([
            _eo_eval(verdict="AMBIGUOUS", hint=hint, uncovered=[0]),
            _eo_eval(verdict="CORRECT", covered=[0]),
        ])
        synth = _make_synth_mock(_so())
        orch = Orchestrator(parser=parser, executor=executor,
                            evaluator=evaluator, synthesizer=synth)
        result = orch.run("test question")
        return orch, result, executor

    def test_broaden_subject_modifies_subject(self):
        sg = SubGoal(kind="fact_lookup", subject_canonical="Product X v2024")
        _, result, _ = self._setup_orchestrator_with_hint("broaden_subject", sg)
        # iter 1 utilise un sub_goal modifié
        new_sg = result.iterations[1].parse_output.sub_goals[0]
        assert new_sg.subject_canonical == "Product X"

    def test_narrow_time_filter_modifies_filter(self):
        sg = SubGoal(kind="lifecycle_trace", subject_canonical="X", time_filter="evolution")
        _, result, _ = self._setup_orchestrator_with_hint("narrow_time_filter", sg)
        new_sg = result.iterations[1].parse_output.sub_goals[0]
        assert new_sg.time_filter == "current"

    def test_drop_overspecific_filters_clears_hints(self):
        sg = SubGoal(kind="fact_lookup", subject_canonical="X",
                     predicate_hint="some_pred", object_hint="some_obj")
        _, result, _ = self._setup_orchestrator_with_hint("drop_overspecific_filters", sg)
        new_sg = result.iterations[1].parse_output.sub_goals[0]
        assert new_sg.predicate_hint is None
        assert new_sg.object_hint is None

    def test_decompose_comparison_changes_kind(self):
        sg = SubGoal(kind="comparison", subject_canonical="A")
        _, result, _ = self._setup_orchestrator_with_hint("decompose_comparison", sg)
        new_sg = result.iterations[1].parse_output.sub_goals[0]
        assert new_sg.kind == "fact_lookup"

    def test_add_qdrant_fallback_adds_toolcall(self):
        sg = SubGoal(kind="fact_lookup", subject_canonical="X")
        _, result, _ = self._setup_orchestrator_with_hint("add_qdrant_fallback", sg)
        # iter 1 plan a un ToolCall qdrant_sections
        tool_names = [tc.tool for tc in result.iterations[1].plan_output.tool_calls]
        assert "qdrant_sections" in tool_names

    def test_check_lifecycle_adds_toolcall(self):
        sg = SubGoal(kind="fact_lookup", subject_canonical="X")
        _, result, _ = self._setup_orchestrator_with_hint("check_lifecycle", sg)
        tool_names = [tc.tool for tc in result.iterations[1].plan_output.tool_calls]
        assert "lifecycle_query" in tool_names


# ============================================================================
# Orchestrator — synthesize integration
# ============================================================================


class TestSynthesizeIntegration:
    def test_synthesize_called_with_final_outputs(self):
        po = _po(sub_goals=[SubGoal(kind="fact_lookup", subject_canonical="X")])
        parser = _make_parser_mock(po)
        executor = _make_executor_mock_constant(
            _eo_exec(results=[_tr(n_claims=3, coverage="full")])
        )
        evaluator = _make_evaluator_mock_sequence([
            _eo_eval(verdict="CORRECT", covered=[0]),
        ])
        synth = _make_synth_mock(_so(answer="Final answer"))
        orch = Orchestrator(parser=parser, executor=executor,
                            evaluator=evaluator, synthesizer=synth)
        result = orch.run("test")
        # Synth.synthesize appelé une fois
        assert synth.synthesize.call_count == 1
        # answer_text de SynthesizeOutput injectée dans le result
        assert result.synthesize_output.answer_text == "Final answer"


# ============================================================================
# Top-level API
# ============================================================================


class TestTopLevelAPI:
    def test_run_question_works(self):
        po = _po(sub_goals=[SubGoal(kind="fact_lookup", subject_canonical="X")])
        parser = _make_parser_mock(po)
        executor = _make_executor_mock_constant(
            _eo_exec(results=[_tr(n_claims=3, coverage="full")])
        )
        evaluator = _make_evaluator_mock_sequence([
            _eo_eval(verdict="CORRECT", covered=[0]),
        ])
        synth = _make_synth_mock(_so())
        orch = Orchestrator(parser=parser, executor=executor,
                            evaluator=evaluator, synthesizer=synth)
        result = run_question("test", orchestrator=orch)
        assert isinstance(result, OrchestratorResult)


# ============================================================================
# OrchestratorResult serialization
# ============================================================================


class TestResultSerialization:
    def test_to_dict_structure(self):
        po = _po(sub_goals=[SubGoal(kind="fact_lookup", subject_canonical="X")])
        parser = _make_parser_mock(po)
        executor = _make_executor_mock_constant(
            _eo_exec(results=[_tr(n_claims=3, coverage="full")])
        )
        evaluator = _make_evaluator_mock_sequence([
            _eo_eval(verdict="CORRECT", covered=[0]),
        ])
        synth = _make_synth_mock(_so())
        orch = Orchestrator(parser=parser, executor=executor,
                            evaluator=evaluator, synthesizer=synth)
        result = orch.run("test")
        d = result.to_dict()
        assert "answer" in d
        assert "iterations" in d
        assert d["n_iterations"] == 1
        assert d["total_duration_s"] >= 0
        assert d["terminated_reason"] == "verdict_correct"


# ============================================================================
# Domain-agnostic charter
# ============================================================================


class TestDomainAgnostic:
    def test_orchestrator_module_no_corpus_tokens(self):
        from pathlib import Path
        import inspect
        from knowbase.runtime_a3 import orchestrator as orch_module

        src = Path(inspect.getfile(orch_module)).read_text(encoding="utf-8").lower()
        forbidden = ["sap ", "s4hana", "s/4hana", "rise ", "fiori", "hana ",
                     "aerospace", "ehs ", "etops",
                     "icd-10", "icd10", "fda ",
                     "gdpr", "eu 2021"]
        for token in forbidden:
            assert token not in src, f"Token '{token}' in orchestrator.py"
