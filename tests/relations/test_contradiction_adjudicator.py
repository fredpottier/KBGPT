"""Tests adjudicateur de contradictions (#446) — parsing, pré-passe, fail-safe."""

import json

from knowbase.relations.contradiction_adjudicator import (
    ContradictionAdjudicator, _parse_verdict, _build_user_prompt,
)


def _pair(text_a, text_b, passage_a="ctx A", passage_b="ctx B"):
    return {
        "a_id": "ca", "b_id": "cb",
        "text_a": text_a, "text_b": text_b,
        "passage_a": passage_a, "passage_b": passage_b,
        "doc_a": "DOC_A", "doc_b": "DOC_B", "page_a": 1, "page_b": 2,
    }


def test_parse_verdict_valid():
    raw = '{"verdict": "different_scope", "reason": "different test cases"}'
    out = _parse_verdict(raw)
    assert out == {"verdict": "DIFFERENT_SCOPE", "reason": "different test cases"}


def test_parse_verdict_rejects_unknown():
    assert _parse_verdict('{"verdict": "MAYBE", "reason": "?"}') is None
    assert _parse_verdict("pas de json") is None


def test_prompt_contains_passages_and_docs():
    p = _pair("A says X", "B says Y", passage_a="LONG CONTEXT A", passage_b="LONG CONTEXT B")
    prompt = _build_user_prompt(p)
    # le juge DOIT recevoir les passages sources et l'identité des documents
    assert "LONG CONTEXT A" in prompt and "LONG CONTEXT B" in prompt
    assert "DOC_A" in prompt and "DOC_B" in prompt
    assert "page 1" in prompt and "page 2" in prompt


def test_deterministic_equivalence_pre_pass():
    # 680 kg ≈ 1500 lb → EQUIVALENT sans appel LLM
    called = []
    adj = ContradictionAdjudicator(llm_call=lambda s, u: called.append(1) or "{}")
    rec = adj.adjudicate_pair(_pair(
        "the load must not exceed 1,500 lbs (6.67 kN)",
        "the load must not exceed 680 kg (1500 lb)",
    ))
    assert rec.verdict == "EQUIVALENT"
    assert rec.method == "deterministic_equivalence"
    assert not called


def test_llm_verdict_flow():
    adj = ContradictionAdjudicator(
        llm_call=lambda s, u: json.dumps(
            {"verdict": "COMPLEMENTARY", "reason": "rule plus exception in both docs"}),
        model_label="fake",
    )
    rec = adj.adjudicate_pair(_pair("must be solid strike", "applies regardless of strike"))
    assert rec.verdict == "COMPLEMENTARY"
    assert rec.method == "llm"


def test_failsafe_unclear_on_garbage():
    adj = ContradictionAdjudicator(llm_call=lambda s, u: "garbage not json")
    rec = adj.adjudicate_pair(_pair("a", "b"))
    assert rec.verdict == "UNCLEAR"
    assert rec.method == "error_fallback"
