"""Tests unitaires du module Evaluate — runtime_a3.

Cf ADR_PARSE_EVALUATE_RUNTIME §2.4 + §3.2 + §3.2.1.

Stratégie :
    - Mock LLM via injection custom (`Evaluator(llm_client=...)`)
    - Tests dédiés au fallback déterministe (sans LLM) — règles ADR §3.2
    - Pydantic validation Literals (verdict + re_plan_hint)
    - Sanity check indices invalides
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest

from knowbase.runtime_a3.evaluate import (
    Evaluator,
    _build_system_prompt,
    _choose_re_plan_hint,
    _coverage_for_sub_goal,
    _fallback_deterministic,
    _load_examples,
    _sanitize_indices,
    _serialize_input,
    evaluate,
)
from knowbase.runtime_a3.schemas import (
    ClaimSummary,
    EvaluateInput,
    EvaluateOutput,
    ExecuteOutput,
    ParseOutput,
    PlanOutput,
    SubGoal,
    ToolCall,
    ToolResult,
)


# ============================================================================
# Helpers
# ============================================================================


def _make_parse_output(
    sub_goals=None,
    parse_confidence: float = 0.9,
    raw_question: str = "test",
    parse_warnings=None,
) -> ParseOutput:
    return ParseOutput(
        sub_goals=sub_goals or [],
        entities=[],
        language="en",
        raw_question=raw_question,
        parse_confidence=parse_confidence,
        parse_warnings=parse_warnings or [],
        schema_version="a3.0",
    )


def _make_plan_output(tool_calls=None, unmappable=None) -> PlanOutput:
    return PlanOutput(
        tool_calls=tool_calls or [],
        unmappable_sub_goals=unmappable or [],
        plan_warnings=[],
        schema_version="a3.0",
    )


def _make_execute_output(results=None, duration: float = 0.0) -> ExecuteOutput:
    return ExecuteOutput(
        results=results or [],
        total_duration_s=duration,
        schema_version="a3.0",
    )


def _tool_result(
    sub_goal_idx: int = 0,
    tool: str = "kg_claims",
    n_claims: int = 0,
    coverage: str = "empty",
    error=None,
) -> ToolResult:
    claims = [ClaimSummary(claim_id=f"c_{i}") for i in range(n_claims)]
    return ToolResult(
        sub_goal_idx=sub_goal_idx,
        tool=tool,
        claims=claims,
        coverage_signal=coverage,
        duration_s=0.01,
        error=error,
    )


def _make_evaluate_input(
    sub_goals=None,
    results=None,
    iteration: int = 0,
    parse_confidence: float = 0.9,
    parse_warnings=None,
) -> EvaluateInput:
    return EvaluateInput(
        parse_output=_make_parse_output(
            sub_goals=sub_goals,
            parse_confidence=parse_confidence,
            parse_warnings=parse_warnings,
        ),
        plan_output=_make_plan_output(),
        execute_output=_make_execute_output(results=results),
        iteration=iteration,
    )


def _valid_llm_response(
    verdict: str = "CORRECT",
    covered=None,
    uncovered=None,
    re_plan_hint: str = "none",
    confidence: float = 0.9,
    reasoning: str = "Three concordant claims directly answer the question.",
) -> str:
    return json.dumps({
        "verdict": verdict,
        "covered_sub_goals": covered if covered is not None else [0],
        "uncovered_sub_goals": uncovered if uncovered is not None else [],
        "re_plan_hint": re_plan_hint,
        "confidence": confidence,
        "reasoning": reasoning,
        "schema_version": "a3.0",
    })


# ============================================================================
# Few-shot examples
# ============================================================================


class TestFewShotExamples:
    def test_examples_load(self):
        examples = _load_examples()
        assert len(examples) >= 5

    def test_examples_validate_against_schema(self):
        examples = _load_examples()
        for i, ex in enumerate(examples):
            try:
                EvaluateOutput.model_validate(ex["expected"])
            except Exception as e:
                pytest.fail(f"Example {i} failed validation: {e}")

    def test_examples_domain_agnostic(self):
        examples = _load_examples()
        text = json.dumps(examples, ensure_ascii=False).lower()
        forbidden = ["sap", "s4hana", "s/4hana", "rise ", "fiori", "hana ",
                     "aerospace", "ehs", "etops",
                     "icd-10", "icd10", "rcp", "fda ",
                     "gdpr", "eu 2021"]
        for token in forbidden:
            assert token not in text, f"Token '{token}' found in evaluate_examples.json"


# ============================================================================
# System prompt
# ============================================================================


class TestSystemPrompt:
    def test_prompt_contains_schema(self):
        prompt = _build_system_prompt()
        assert "CORRECT" in prompt
        assert "AMBIGUOUS" in prompt
        assert "INCORRECT" in prompt
        assert "INSUFFICIENT_EVIDENCE" in prompt
        assert "broaden_subject" in prompt
        assert "add_qdrant_fallback" in prompt
        assert "EXAMPLES" in prompt

    def test_prompt_cached(self):
        p1 = _build_system_prompt()
        p2 = _build_system_prompt()
        assert p1 is p2


# ============================================================================
# Serialization
# ============================================================================


class TestSerializeInput:
    def test_minimal_input(self):
        inp = _make_evaluate_input(
            sub_goals=[SubGoal(kind="fact_lookup", subject_canonical="X")],
            results=[_tool_result(n_claims=3, coverage="full")],
        )
        user = _serialize_input(inp)
        assert "sub_goals" in user
        assert "iteration" in user
        assert "results_per_sub_goal" in user
        # n_claims présent dans la sérialisation
        assert "n_claims" in user


# ============================================================================
# Fallback déterministe — règles ADR §3.2
# ============================================================================


class TestFallbackEmptySubGoals:
    def test_no_sub_goals_returns_insufficient(self):
        inp = _make_evaluate_input(sub_goals=[])
        out = _fallback_deterministic(inp)
        assert out.verdict == "INSUFFICIENT_EVIDENCE"
        assert out.re_plan_hint == "none"


class TestFallbackLowParseConfidence:
    def test_parse_confidence_below_threshold_insufficient(self):
        inp = _make_evaluate_input(
            sub_goals=[SubGoal(kind="fact_lookup", subject_canonical="X")],
            parse_confidence=0.2,
            parse_warnings=["out_of_scope_for_corpus"],
        )
        out = _fallback_deterministic(inp)
        assert out.verdict == "INSUFFICIENT_EVIDENCE"
        assert out.re_plan_hint == "none"


class TestFallbackAllFull:
    def test_all_full_correct(self):
        inp = _make_evaluate_input(
            sub_goals=[
                SubGoal(kind="fact_lookup", subject_canonical="X"),
                SubGoal(kind="fact_lookup", subject_canonical="Y"),
            ],
            results=[
                _tool_result(sub_goal_idx=0, n_claims=5, coverage="full"),
                _tool_result(sub_goal_idx=1, n_claims=4, coverage="full"),
            ],
        )
        out = _fallback_deterministic(inp)
        assert out.verdict == "CORRECT"
        assert out.covered_sub_goals == [0, 1]
        assert out.uncovered_sub_goals == []
        assert out.re_plan_hint == "none"


class TestFallbackAllEmpty:
    def test_all_empty_iter0_ambiguous_with_qdrant_hint(self):
        inp = _make_evaluate_input(
            sub_goals=[SubGoal(kind="fact_lookup", subject_canonical="X")],
            results=[_tool_result(coverage="empty")],
            iteration=0,
        )
        out = _fallback_deterministic(inp)
        assert out.verdict == "AMBIGUOUS"
        assert out.re_plan_hint == "add_qdrant_fallback"

    def test_all_empty_iter1_insufficient(self):
        inp = _make_evaluate_input(
            sub_goals=[SubGoal(kind="fact_lookup", subject_canonical="X")],
            results=[_tool_result(coverage="empty")],
            iteration=1,
        )
        out = _fallback_deterministic(inp)
        assert out.verdict == "INSUFFICIENT_EVIDENCE"
        assert out.re_plan_hint == "none"


class TestFallbackPartialCoverage:
    def test_partial_iter0_ambiguous(self):
        inp = _make_evaluate_input(
            sub_goals=[
                SubGoal(kind="fact_lookup", subject_canonical="X"),
                SubGoal(kind="fact_lookup", subject_canonical="Y"),
            ],
            results=[
                _tool_result(sub_goal_idx=0, n_claims=3, coverage="full"),
                _tool_result(sub_goal_idx=1, n_claims=1, coverage="partial"),
            ],
            iteration=0,
        )
        out = _fallback_deterministic(inp)
        assert out.verdict == "AMBIGUOUS"
        # 0 covered, 1 uncovered (partial counted as uncovered for re-plan)
        assert 0 in out.covered_sub_goals
        assert 1 in out.uncovered_sub_goals

    def test_partial_iter1_correct_with_warning(self):
        """Hard cap iter≥1 → CORRECT (warning only)."""
        inp = _make_evaluate_input(
            sub_goals=[
                SubGoal(kind="fact_lookup", subject_canonical="X"),
                SubGoal(kind="fact_lookup", subject_canonical="Y"),
            ],
            results=[
                _tool_result(sub_goal_idx=0, n_claims=3, coverage="full"),
                _tool_result(sub_goal_idx=1, n_claims=1, coverage="partial"),
            ],
            iteration=1,
        )
        out = _fallback_deterministic(inp)
        assert out.verdict == "CORRECT"
        assert out.re_plan_hint == "none"
        assert 0 in out.covered_sub_goals
        # uncovered/partial should be in uncovered_sub_goals
        assert 1 in out.uncovered_sub_goals


class TestFallbackAllErrors:
    def test_all_errors_insufficient(self):
        inp = _make_evaluate_input(
            sub_goals=[SubGoal(kind="fact_lookup", subject_canonical="X")],
            results=[
                _tool_result(error="Connection lost"),
                _tool_result(error="Timeout"),
            ],
        )
        out = _fallback_deterministic(inp)
        assert out.verdict == "INSUFFICIENT_EVIDENCE"
        assert out.re_plan_hint == "none"


# ============================================================================
# Re-plan hint chooser
# ============================================================================


class TestRePlanHintChooser:
    def test_comparison_subgoal_returns_decompose(self):
        inp = _make_evaluate_input(
            sub_goals=[
                SubGoal(kind="comparison", subject_canonical="A"),
                SubGoal(kind="comparison", subject_canonical="B"),
            ],
            results=[_tool_result(sub_goal_idx=0), _tool_result(sub_goal_idx=1)],
        )
        hint = _choose_re_plan_hint(inp, empties=[0, 1], partials=[])
        assert hint == "decompose_comparison"

    def test_lifecycle_subgoal_returns_narrow_time(self):
        inp = _make_evaluate_input(
            sub_goals=[SubGoal(kind="lifecycle_trace", subject_canonical="X")],
            results=[_tool_result()],
        )
        hint = _choose_re_plan_hint(inp, empties=[0], partials=[])
        assert hint == "narrow_time_filter"

    def test_default_qdrant_fallback(self):
        inp = _make_evaluate_input(
            sub_goals=[SubGoal(kind="fact_lookup", subject_canonical="X")],
            results=[_tool_result()],
        )
        hint = _choose_re_plan_hint(inp, empties=[0], partials=[])
        assert hint == "add_qdrant_fallback"


# ============================================================================
# Coverage aggregator
# ============================================================================


class TestCoverageAggregator:
    def test_max_full_wins(self):
        exec_out = _make_execute_output(results=[
            _tool_result(sub_goal_idx=0, coverage="partial"),
            _tool_result(sub_goal_idx=0, coverage="full"),
            _tool_result(sub_goal_idx=0, coverage="empty"),
        ])
        assert _coverage_for_sub_goal(0, exec_out) == "full"

    def test_partial_wins_over_empty(self):
        exec_out = _make_execute_output(results=[
            _tool_result(sub_goal_idx=0, coverage="empty"),
            _tool_result(sub_goal_idx=0, coverage="partial"),
        ])
        assert _coverage_for_sub_goal(0, exec_out) == "partial"

    def test_no_results_empty(self):
        exec_out = _make_execute_output(results=[])
        assert _coverage_for_sub_goal(0, exec_out) == "empty"


# ============================================================================
# Sanitization
# ============================================================================


class TestSanitizeIndices:
    def test_invalid_indices_filtered(self):
        parsed = {
            "covered_sub_goals": [0, 1, 99, -1, "foo"],
            "uncovered_sub_goals": [2, 3, 5],
        }
        sanitized = _sanitize_indices(parsed, n_sub_goals=3)
        assert sanitized["covered_sub_goals"] == [0, 1]
        assert sanitized["uncovered_sub_goals"] == [2]

    def test_non_list_becomes_empty(self):
        parsed = {"covered_sub_goals": "not a list", "uncovered_sub_goals": None}
        sanitized = _sanitize_indices(parsed, n_sub_goals=3)
        assert sanitized["covered_sub_goals"] == []
        assert sanitized["uncovered_sub_goals"] == []


# ============================================================================
# Evaluator — LLM happy path
# ============================================================================


class TestEvaluatorLLMHappyPath:
    def test_llm_response_parsed(self):
        llm = MagicMock()
        llm.complete.return_value = _valid_llm_response(
            verdict="CORRECT",
            covered=[0],
            confidence=0.95,
        )
        ev = Evaluator(llm_client=llm)
        out = ev.evaluate(_make_evaluate_input(
            sub_goals=[SubGoal(kind="fact_lookup", subject_canonical="X")],
            results=[_tool_result(n_claims=3, coverage="full")],
        ))
        assert out.verdict == "CORRECT"
        assert out.confidence == 0.95
        assert llm.complete.call_count == 1

    def test_markdown_fences_stripped(self):
        llm = MagicMock()
        llm.complete.return_value = "```json\n" + _valid_llm_response() + "\n```"
        ev = Evaluator(llm_client=llm)
        out = ev.evaluate(_make_evaluate_input(
            sub_goals=[SubGoal(kind="fact_lookup", subject_canonical="X")],
            results=[_tool_result(n_claims=3, coverage="full")],
        ))
        assert out.verdict == "CORRECT"


# ============================================================================
# Evaluator — retry + fallback
# ============================================================================


class TestEvaluatorRetry:
    def test_retry_on_invalid_json_then_success(self):
        llm = MagicMock()
        llm.complete.side_effect = ["not json {{{", _valid_llm_response()]
        ev = Evaluator(llm_client=llm)
        out = ev.evaluate(_make_evaluate_input(
            sub_goals=[SubGoal(kind="fact_lookup", subject_canonical="X")],
            results=[_tool_result(n_claims=3, coverage="full")],
        ))
        assert out.verdict == "CORRECT"
        assert llm.complete.call_count == 2

    def test_fallback_after_two_failures(self):
        llm = MagicMock()
        llm.complete.side_effect = ["bogus1", "bogus2"]
        ev = Evaluator(llm_client=llm)
        out = ev.evaluate(_make_evaluate_input(
            sub_goals=[SubGoal(kind="fact_lookup", subject_canonical="X")],
            results=[_tool_result(n_claims=3, coverage="full")],
        ))
        # Fallback: tous full → CORRECT
        assert out.verdict == "CORRECT"
        assert "[fallback]" in out.reasoning

    def test_fallback_on_pydantic_validation_failures(self):
        # JSON valide mais verdict invalide (pas un Literal)
        bad = json.dumps({"verdict": "BOGUS_VERDICT", "confidence": 0.5,
                          "covered_sub_goals": [], "uncovered_sub_goals": [],
                          "re_plan_hint": "none", "reasoning": "x"})
        llm = MagicMock()
        llm.complete.side_effect = [bad, bad]
        ev = Evaluator(llm_client=llm)
        out = ev.evaluate(_make_evaluate_input(
            sub_goals=[SubGoal(kind="fact_lookup", subject_canonical="X")],
            results=[_tool_result(coverage="empty")],
        ))
        # Fallback déterministe → AMBIGUOUS (1 sub_goal empty, iteration=0)
        assert out.verdict == "AMBIGUOUS"
        assert "[fallback]" in out.reasoning

    def test_fallback_marks_reasoning(self):
        llm = MagicMock()
        llm.complete.side_effect = ["x", "y"]
        ev = Evaluator(llm_client=llm)
        out = ev.evaluate(_make_evaluate_input(
            sub_goals=[SubGoal(kind="fact_lookup", subject_canonical="X")],
            results=[_tool_result(coverage="empty")],
        ))
        assert out.reasoning.startswith("[fallback]")

    def test_llm_exception_falls_back(self):
        llm = MagicMock()
        llm.complete.side_effect = Exception("Network error")
        ev = Evaluator(llm_client=llm)
        out = ev.evaluate(_make_evaluate_input(
            sub_goals=[SubGoal(kind="fact_lookup", subject_canonical="X")],
            results=[_tool_result(n_claims=5, coverage="full")],
        ))
        # Fallback → CORRECT (all full)
        assert out.verdict == "CORRECT"
        assert "[fallback]" in out.reasoning


# ============================================================================
# Evaluator — court-circuit no sub_goals
# ============================================================================


class TestEvaluatorShortCircuit:
    def test_no_sub_goals_skip_llm(self):
        llm = MagicMock()  # ne devrait JAMAIS être appelé
        ev = Evaluator(llm_client=llm)
        out = ev.evaluate(_make_evaluate_input(sub_goals=[]))
        assert out.verdict == "INSUFFICIENT_EVIDENCE"
        llm.complete.assert_not_called()


# ============================================================================
# LLM sanitization — indices invalides → corrigés
# ============================================================================


class TestEvaluatorSanitization:
    def test_invalid_indices_filtered_pre_validation(self):
        """LLM renvoie idx invalides — ils sont filtrés avant Pydantic."""
        llm = MagicMock()
        llm.complete.return_value = _valid_llm_response(
            covered=[0, 99],   # 99 invalid
            uncovered=[1, -5],  # -5 invalid
        )
        ev = Evaluator(llm_client=llm)
        out = ev.evaluate(_make_evaluate_input(
            sub_goals=[
                SubGoal(kind="fact_lookup", subject_canonical="X"),
                SubGoal(kind="fact_lookup", subject_canonical="Y"),
            ],
            results=[_tool_result(sub_goal_idx=0, n_claims=3, coverage="full")],
        ))
        assert out.covered_sub_goals == [0]
        assert out.uncovered_sub_goals == [1]


# ============================================================================
# Top-level API
# ============================================================================


class TestTopLevelAPI:
    def test_evaluate_function_works(self):
        llm = MagicMock()
        llm.complete.return_value = _valid_llm_response()
        po = _make_parse_output(sub_goals=[
            SubGoal(kind="fact_lookup", subject_canonical="X")
        ])
        plo = _make_plan_output()
        eo = _make_execute_output(results=[_tool_result(n_claims=3, coverage="full")])
        out = evaluate(po, plo, eo, iteration=0, evaluator=Evaluator(llm_client=llm))
        assert isinstance(out, EvaluateOutput)
        assert out.verdict == "CORRECT"


# ============================================================================
# Schema validation
# ============================================================================


class TestSchemaValidation:
    def test_verdict_literal_strict(self):
        with pytest.raises(Exception):
            EvaluateOutput(
                verdict="BOGUS",  # type: ignore
                covered_sub_goals=[],
                uncovered_sub_goals=[],
                re_plan_hint="none",
                confidence=0.5,
                reasoning="x",
            )

    def test_re_plan_hint_literal_strict(self):
        with pytest.raises(Exception):
            EvaluateOutput(
                verdict="AMBIGUOUS",
                covered_sub_goals=[],
                uncovered_sub_goals=[],
                re_plan_hint="custom_hint",  # type: ignore
                confidence=0.5,
                reasoning="x",
            )

    def test_confidence_bounds(self):
        with pytest.raises(Exception):
            EvaluateOutput(
                verdict="CORRECT",
                covered_sub_goals=[],
                uncovered_sub_goals=[],
                re_plan_hint="none",
                confidence=1.5,
                reasoning="x",
            )

    def test_iteration_bounds(self):
        with pytest.raises(Exception):
            EvaluateInput(
                parse_output=_make_parse_output(),
                plan_output=_make_plan_output(),
                execute_output=_make_execute_output(),
                iteration=5,  # > 2
            )


# ============================================================================
# Domain-agnostic charter
# ============================================================================


class TestDomainAgnostic:
    def test_evaluate_module_no_corpus_tokens(self):
        from pathlib import Path
        import inspect
        from knowbase.runtime_a3 import evaluate as evaluate_module

        src = Path(inspect.getfile(evaluate_module)).read_text(encoding="utf-8").lower()
        forbidden = ["sap ", "s4hana", "s/4hana", "rise ", "fiori", "hana ",
                     "aerospace", "ehs ", "etops",
                     "icd-10", "icd10", "fda ",
                     "gdpr", "eu 2021"]
        for token in forbidden:
            assert token not in src, f"Token '{token}' found in evaluate.py"
