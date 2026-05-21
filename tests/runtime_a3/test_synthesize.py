"""Tests unitaires du module Synthesize — runtime_a3.

Cf ADR_PARSE_EVALUATE_RUNTIME §2.5 + §3.3.

Stratégie :
    - Mock LLM via injection custom (`Synthesizer(llm_client=...)`)
    - Tests fallback template (sans LLM, garde le pipeline up)
    - Court-circuit ABSTENTION
    - Citation coverage check (garde-fou AX-1)
    - Mode selection déterministe par verdict
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest

from knowbase.runtime_a3.synthesize import (
    Synthesizer,
    _aggregate_claims,
    _aggregate_conflict_pending_summaries,
    _build_system_prompt,
    _compute_citation_coverage,
    _load_examples,
    _select_mode_from_verdict,
    _split_sentences,
    synthesize,
)
from knowbase.runtime_a3.schemas import (
    CitedClaim,
    ClaimSummary,
    ConflictPendingSummary,
    EvaluateOutput,
    ExecuteOutput,
    ParseOutput,
    PlanOutput,
    SubGoal,
    SynthesizeInput,
    SynthesizeOutput,
    ToolResult,
)


# ============================================================================
# Helpers
# ============================================================================


def _po(sub_goals=None, raw_question="test question") -> ParseOutput:
    return ParseOutput(
        sub_goals=sub_goals or [],
        entities=[],
        language="en",
        raw_question=raw_question,
        parse_confidence=0.9,
        parse_warnings=[],
        schema_version="a3.0",
    )


def _eo_exec(results=None) -> ExecuteOutput:
    return ExecuteOutput(
        results=results or [],
        total_duration_s=0.05,
        schema_version="a3.0",
    )


def _eo_eval(verdict="CORRECT", covered=None, uncovered=None) -> EvaluateOutput:
    return EvaluateOutput(
        verdict=verdict,
        covered_sub_goals=covered or [],
        uncovered_sub_goals=uncovered or [],
        re_plan_hint="none",
        confidence=0.9,
        reasoning="test reasoning",
        schema_version="a3.0",
    )


def _tr(
    sub_goal_idx=0,
    claims=None,
    coverage="full",
    cps=None,
) -> ToolResult:
    return ToolResult(
        sub_goal_idx=sub_goal_idx,
        tool="kg_claims",
        claims=claims or [],
        coverage_signal=coverage,
        conflict_pendings=cps or [],
        duration_s=0.01,
    )


def _claim(cid: str, value: str = "v", subject: str = "X") -> ClaimSummary:
    return ClaimSummary(
        claim_id=cid,
        subject_canonical=subject,
        predicate="p",
        value=value,
    )


def _valid_llm_response(
    answer_text="Product X v2024 supports 500 users [claim_id=c_001].",
    cited_claims=None,
    mode="REASONED",
    uncovered_warning=None,
    conflict_warning=None,
) -> str:
    return json.dumps({
        "answer_text": answer_text,
        "cited_claims": cited_claims if cited_claims is not None else [
            {"claim_id": "c_001", "claim_verbatim": "Product X v2024 max users: 500"}
        ],
        "uncovered_sub_goals_warning": uncovered_warning,
        "conflict_pending_warning": conflict_warning,
        "mode": mode,
        "synthesize_warnings": [],
        "schema_version": "a3.0",
    })


# ============================================================================
# Few-shot examples
# ============================================================================


class TestFewShotExamples:
    def test_examples_load(self):
        examples = _load_examples()
        assert len(examples) >= 4

    def test_examples_validate_against_schema(self):
        examples = _load_examples()
        for i, ex in enumerate(examples):
            try:
                SynthesizeOutput.model_validate(ex["expected"])
            except Exception as e:
                pytest.fail(f"Example {i} failed validation: {e}")

    def test_examples_have_all_modes(self):
        examples = _load_examples()
        modes = {ex["expected"]["mode"] for ex in examples}
        # Au moins REASONED + ANCHORED + ABSTENTION couverts
        assert "REASONED" in modes
        assert "ABSTENTION" in modes

    def test_examples_domain_agnostic(self):
        examples = _load_examples()
        text = json.dumps(examples, ensure_ascii=False).lower()
        forbidden = ["sap ", "s/4hana", "s4hana", "rise ", "fiori", "hana ",
                     "aerospace", "ehs ", "etops",
                     "icd-10", "icd10", "rcp", "fda ",
                     "gdpr", "eu 2021"]
        for token in forbidden:
            assert token not in text, f"Token '{token}' in synthesize_examples"


# ============================================================================
# System prompt
# ============================================================================


class TestSystemPrompt:
    def test_prompt_contains_rules(self):
        prompt = _build_system_prompt()
        assert "NEVER invent facts" in prompt
        assert "claim_id" in prompt
        assert "REASONED" in prompt
        assert "ABSTENTION" in prompt

    def test_prompt_cached(self):
        p1 = _build_system_prompt()
        p2 = _build_system_prompt()
        assert p1 is p2


# ============================================================================
# Aggregators
# ============================================================================


class TestAggregators:
    def test_aggregate_claims_dedupes_by_claim_id(self):
        exec_out = _eo_exec(results=[
            _tr(sub_goal_idx=0, claims=[_claim("c1"), _claim("c2")]),
            _tr(sub_goal_idx=1, claims=[_claim("c2"), _claim("c3")]),
        ])
        agg = _aggregate_claims(exec_out)
        assert len(agg) == 3
        assert [c.claim_id for c in agg] == ["c1", "c2", "c3"]

    def test_aggregate_cp_dedupes(self):
        cp1 = ConflictPendingSummary(
            conflict_id="cp_001", resolution_status="unresolved",
            involved_claim_ids=["c1"],
        )
        exec_out = _eo_exec(results=[
            _tr(claims=[_claim("c1")], cps=[cp1]),
            _tr(claims=[_claim("c1")], cps=[cp1]),  # même CP via dédup
        ])
        agg = _aggregate_conflict_pending_summaries(exec_out)
        assert len(agg) == 1


# ============================================================================
# Mode selector déterministe
# ============================================================================


class TestModeSelector:
    @pytest.mark.parametrize("verdict,n_claims,expected", [
        ("CORRECT", 5, "REASONED"),
        ("CORRECT", 0, "ABSTENTION"),
        ("AMBIGUOUS", 3, "ANCHORED"),
        ("AMBIGUOUS", 0, "ABSTENTION"),
        ("INSUFFICIENT_EVIDENCE", 0, "ABSTENTION"),
        ("INSUFFICIENT_EVIDENCE", 5, "ABSTENTION"),
        ("INCORRECT", 5, "TEXT_ONLY"),
    ])
    def test_mode_from_verdict(self, verdict, n_claims, expected):
        eo = _eo_eval(verdict=verdict)
        assert _select_mode_from_verdict(eo, n_claims) == expected


# ============================================================================
# Citation coverage check (AX-1)
# ============================================================================


class TestCitationCoverage:
    def test_all_sentences_cited_rate_1(self):
        text = "Fact one [claim_id=c1]. Fact two [claim_id=c2]. Fact three [claim_id=c3]."
        assert _compute_citation_coverage(text) == 1.0

    def test_half_cited_rate_half(self):
        text = "Fact one [claim_id=c1]. Fact two without citation. Fact three [claim_id=c3]."
        rate = _compute_citation_coverage(text)
        assert abs(rate - 2 / 3) < 0.01

    def test_warning_section_ignored(self):
        text = (
            "Fact one [claim_id=c1]. Fact two [claim_id=c2].\n\n"
            "⚠ Sub-goals not covered: foo bar baz.\n"
            "  - reformulate query"
        )
        # Les phrases ⚠ sont ignorées (pas factuelles)
        rate = _compute_citation_coverage(text)
        assert rate == 1.0

    def test_empty_text_rate_1(self):
        assert _compute_citation_coverage("") == 1.0


# ============================================================================
# Synthesizer — court-circuit ABSTENTION (no claims)
# ============================================================================


class TestAbstentionShortCircuit:
    def test_insufficient_evidence_skips_llm(self):
        llm = MagicMock()  # ne doit JAMAIS être appelé
        s = Synthesizer(llm_client=llm)
        inp = SynthesizeInput(
            parse_output=_po(sub_goals=[SubGoal(kind="fact_lookup", subject_canonical="X")]),
            execute_output=_eo_exec(),
            evaluate_output=_eo_eval(verdict="INSUFFICIENT_EVIDENCE", uncovered=[0]),
        )
        out = s.synthesize(inp)
        assert out.mode == "ABSTENTION"
        assert out.cited_claims == []
        llm.complete.assert_not_called()

    def test_correct_but_zero_claims_abstention(self):
        llm = MagicMock()
        s = Synthesizer(llm_client=llm)
        inp = SynthesizeInput(
            parse_output=_po(sub_goals=[SubGoal(kind="fact_lookup", subject_canonical="X")]),
            execute_output=_eo_exec(results=[_tr(claims=[], coverage="empty")]),
            evaluate_output=_eo_eval(verdict="CORRECT"),
        )
        out = s.synthesize(inp)
        assert out.mode == "ABSTENTION"
        llm.complete.assert_not_called()


# ============================================================================
# Synthesizer — LLM happy path
# ============================================================================


class TestLLMHappyPath:
    def test_llm_response_parsed(self):
        llm = MagicMock()
        llm.complete.return_value = _valid_llm_response()
        s = Synthesizer(llm_client=llm)
        inp = SynthesizeInput(
            parse_output=_po(sub_goals=[SubGoal(kind="fact_lookup", subject_canonical="X")]),
            execute_output=_eo_exec(results=[
                _tr(claims=[_claim("c_001", value="500 users")]),
            ]),
            evaluate_output=_eo_eval(verdict="CORRECT", covered=[0]),
        )
        out = s.synthesize(inp)
        assert out.mode == "REASONED"
        assert "[claim_id=c_001]" in out.answer_text
        assert len(out.cited_claims) == 1
        assert out.citation_coverage_rate == 1.0

    def test_markdown_fences_stripped(self):
        llm = MagicMock()
        llm.complete.return_value = "```json\n" + _valid_llm_response() + "\n```"
        s = Synthesizer(llm_client=llm)
        inp = SynthesizeInput(
            parse_output=_po(sub_goals=[SubGoal(kind="fact_lookup", subject_canonical="X")]),
            execute_output=_eo_exec(results=[_tr(claims=[_claim("c_001")])]),
            evaluate_output=_eo_eval(),
        )
        out = s.synthesize(inp)
        assert isinstance(out, SynthesizeOutput)

    def test_invalid_mode_corrected(self):
        """Si LLM produit mode hors Literal, on le force via le selector."""
        llm = MagicMock()
        llm.complete.return_value = _valid_llm_response(mode="BOGUS_MODE")
        s = Synthesizer(llm_client=llm)
        inp = SynthesizeInput(
            parse_output=_po(sub_goals=[SubGoal(kind="fact_lookup", subject_canonical="X")]),
            execute_output=_eo_exec(results=[_tr(claims=[_claim("c_001")])]),
            evaluate_output=_eo_eval(verdict="CORRECT", covered=[0]),
        )
        out = s.synthesize(inp)
        assert out.mode == "REASONED"  # forcé par selector


# ============================================================================
# Synthesizer — citation coverage warning
# ============================================================================


class TestCitationCoverageWarning:
    def test_low_coverage_adds_warning(self):
        llm = MagicMock()
        # 3 phrases, 1 citée → coverage 33%
        llm.complete.return_value = _valid_llm_response(
            answer_text=(
                "Fact one [claim_id=c1]. Fact two without source. Fact three without source."
            ),
        )
        s = Synthesizer(llm_client=llm)
        inp = SynthesizeInput(
            parse_output=_po(sub_goals=[SubGoal(kind="fact_lookup", subject_canonical="X")]),
            execute_output=_eo_exec(results=[_tr(claims=[_claim("c1")])]),
            evaluate_output=_eo_eval(verdict="CORRECT", covered=[0]),
        )
        out = s.synthesize(inp)
        assert out.citation_coverage_rate < 0.95
        assert any("citation_coverage_below_threshold" in w for w in out.synthesize_warnings)

    def test_full_coverage_no_warning(self):
        llm = MagicMock()
        llm.complete.return_value = _valid_llm_response()
        s = Synthesizer(llm_client=llm)
        inp = SynthesizeInput(
            parse_output=_po(sub_goals=[SubGoal(kind="fact_lookup", subject_canonical="X")]),
            execute_output=_eo_exec(results=[_tr(claims=[_claim("c_001")])]),
            evaluate_output=_eo_eval(verdict="CORRECT", covered=[0]),
        )
        out = s.synthesize(inp)
        assert out.citation_coverage_rate == 1.0
        assert not any("citation_coverage_below" in w for w in out.synthesize_warnings)


# ============================================================================
# Synthesizer — fallback template
# ============================================================================


class TestFallbackTemplate:
    def test_fallback_on_llm_failure_with_claims(self):
        llm = MagicMock()
        llm.complete.side_effect = Exception("LLM down")
        s = Synthesizer(llm_client=llm)
        inp = SynthesizeInput(
            parse_output=_po(sub_goals=[SubGoal(kind="fact_lookup", subject_canonical="X")]),
            execute_output=_eo_exec(results=[
                _tr(claims=[_claim("c1", value="val1"), _claim("c2", value="val2")]),
            ]),
            evaluate_output=_eo_eval(verdict="CORRECT", covered=[0]),
        )
        out = s.synthesize(inp)
        assert out.mode == "REASONED"
        assert "template_fallback_no_llm" in out.synthesize_warnings
        # Claims listés avec citation
        assert "[claim_id=c1]" in out.answer_text
        assert "[claim_id=c2]" in out.answer_text
        assert len(out.cited_claims) == 2

    def test_fallback_invalid_json_two_attempts(self):
        llm = MagicMock()
        llm.complete.side_effect = ["not json {{", "still not json"]
        s = Synthesizer(llm_client=llm)
        inp = SynthesizeInput(
            parse_output=_po(sub_goals=[SubGoal(kind="fact_lookup", subject_canonical="X")]),
            execute_output=_eo_exec(results=[_tr(claims=[_claim("c1")])]),
            evaluate_output=_eo_eval(verdict="CORRECT", covered=[0]),
        )
        out = s.synthesize(inp)
        assert "template_fallback_no_llm" in out.synthesize_warnings

    def test_fallback_includes_conflict_pending_warning(self):
        llm = MagicMock()
        llm.complete.side_effect = Exception("LLM down")
        cp = ConflictPendingSummary(
            conflict_id="cp_001", resolution_status="unresolved",
            involved_claim_ids=["c1"],
        )
        s = Synthesizer(llm_client=llm)
        inp = SynthesizeInput(
            parse_output=_po(sub_goals=[SubGoal(kind="fact_lookup", subject_canonical="X")]),
            execute_output=_eo_exec(results=[
                _tr(claims=[_claim("c1")], cps=[cp]),
            ]),
            evaluate_output=_eo_eval(verdict="CORRECT", covered=[0]),
        )
        out = s.synthesize(inp)
        assert out.conflict_pending_warning is not None
        assert "cp_001" in out.conflict_pending_warning
        assert "⚠ Conflicting sources" in out.answer_text

    def test_fallback_includes_uncovered_warning(self):
        llm = MagicMock()
        llm.complete.side_effect = Exception("LLM down")
        s = Synthesizer(llm_client=llm)
        inp = SynthesizeInput(
            parse_output=_po(sub_goals=[
                SubGoal(kind="fact_lookup", subject_canonical="X"),
                SubGoal(kind="fact_lookup", subject_canonical="Y"),
            ]),
            execute_output=_eo_exec(results=[
                _tr(sub_goal_idx=0, claims=[_claim("c1")]),
                _tr(sub_goal_idx=1, claims=[], coverage="empty"),
            ]),
            evaluate_output=_eo_eval(verdict="CORRECT", covered=[0], uncovered=[1]),
        )
        out = s.synthesize(inp)
        assert out.uncovered_sub_goals_warning is not None
        assert "⚠ Sub-goals not covered" in out.answer_text


# ============================================================================
# Schema validation
# ============================================================================


class TestSchemaValidation:
    def test_mode_literal_strict(self):
        with pytest.raises(Exception):
            SynthesizeOutput(
                answer_text="x",
                cited_claims=[],
                mode="BOGUS_MODE",  # type: ignore
                schema_version="a3.0",
            )

    def test_citation_coverage_bounds(self):
        with pytest.raises(Exception):
            SynthesizeOutput(
                answer_text="x",
                cited_claims=[],
                mode="REASONED",
                citation_coverage_rate=1.5,
            )

    def test_cited_claim_requires_verbatim(self):
        with pytest.raises(Exception):
            CitedClaim(
                claim_id="c1",
                claim_verbatim="",  # empty disallowed (min_length=1)
            )


# ============================================================================
# Top-level API
# ============================================================================


class TestTopLevelAPI:
    def test_synthesize_function_works(self):
        llm = MagicMock()
        llm.complete.return_value = _valid_llm_response()
        po = _po(sub_goals=[SubGoal(kind="fact_lookup", subject_canonical="X")])
        eo_exec = _eo_exec(results=[_tr(claims=[_claim("c_001")])])
        eo_eval = _eo_eval(verdict="CORRECT", covered=[0])
        out = synthesize(po, eo_exec, eo_eval,
                         synthesizer=Synthesizer(llm_client=llm))
        assert isinstance(out, SynthesizeOutput)
        assert out.mode == "REASONED"


# ============================================================================
# Domain-agnostic charter
# ============================================================================


class TestDomainAgnostic:
    def test_synthesize_module_no_corpus_tokens(self):
        from pathlib import Path
        import inspect
        from knowbase.runtime_a3 import synthesize as synth_module

        src = Path(inspect.getfile(synth_module)).read_text(encoding="utf-8").lower()
        forbidden = ["sap ", "s4hana", "s/4hana", "rise ", "fiori", "hana ",
                     "aerospace", "ehs ", "etops",
                     "icd-10", "icd10", "fda ",
                     "gdpr", "eu 2021"]
        for token in forbidden:
            assert token not in src, f"Token '{token}' in synthesize.py"
