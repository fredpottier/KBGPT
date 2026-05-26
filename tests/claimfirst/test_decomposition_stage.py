"""
Tests P1.4b-3 — DecompositionStage (Stage B). LLM mocké (pas de burst/réseau).

Teste : énumération→1 claim-liste, multi-prédicats→N claims, négation/modalité préservées,
coercition robuste (objects string→list, modality invalide→assertive, subject vide ignoré),
filtrage source_unit_ids, défaillance→vide+flag, disabled no-op.
"""

import json

import pytest

from knowbase.claimfirst.extractors.decomposition_stage import (
    DecompositionStage,
    ClaimCandidate,
)


def _llm(payload):
    return lambda system, user: json.dumps(payload)


def test_enumeration_one_claim_with_objects_list():
    payload = {"claims": [{
        "subject": "Master Data Governance", "predicate": "is available for",
        "objects": ["Custom Objects", "Financials", "Material"],
        "modality": "assertive", "polarity": "affirmative",
        "self_contained_text": "Master Data Governance is available for Custom Objects, Financials, and Material.",
        "source_unit_ids": ["u1"],
    }]}
    res = DecompositionStage(_llm(payload)).decompose([("u1", "MDG available for ...")])
    assert res.n_claims == 1
    c = res.claims[0]
    assert c.is_enumeration and len(c.objects) == 3
    assert c.source_unit_ids == ["u1"]


def test_multi_predicate_separate_claims():
    payload = {"claims": [
        {"subject": "The engine", "predicate": "weighs", "objects": ["500 kg"],
         "modality": "assertive", "polarity": "affirmative", "self_contained_text": "The engine weighs 500 kg."},
        {"subject": "The engine", "predicate": "runs on", "objects": ["kerosene"],
         "modality": "assertive", "polarity": "affirmative", "self_contained_text": "The engine runs on kerosene."},
    ]}
    res = DecompositionStage(_llm(payload)).decompose([("u1", "...")])
    assert res.n_claims == 2
    assert all(not c.is_enumeration for c in res.claims)


def test_negation_and_modality_preserved():
    payload = {"claims": [{
        "subject": "The experimental API", "predicate": "must be used in", "objects": ["production"],
        "modality": "prescriptive", "polarity": "negative",
        "self_contained_text": "The experimental API must not be used in production.",
        "source_unit_ids": ["u1"],
    }]}
    res = DecompositionStage(_llm(payload)).decompose([("u1", "It must not be used in production.")])
    c = res.claims[0]
    assert c.polarity == "negative"
    assert c.modality == "prescriptive"


def test_coercion_objects_string_and_invalid_modality():
    payload = {"claims": [{
        "subject": "X", "predicate": "is", "objects": "single",     # string -> list
        "modality": "weird", "polarity": "nope",                    # invalides -> défauts
        "self_contained_text": "X is single.",
    }]}
    res = DecompositionStage(_llm(payload)).decompose([("u1", "x")])
    c = res.claims[0]
    assert c.objects == ["single"]
    assert c.modality == "assertive"
    assert c.polarity == "affirmative"


def test_missing_subject_skipped():
    payload = {"claims": [
        {"subject": "", "predicate": "is", "objects": ["a"], "modality": "assertive",
         "polarity": "affirmative", "self_contained_text": "x"},
        {"subject": "Y", "predicate": "is", "objects": ["b"], "modality": "assertive",
         "polarity": "affirmative", "self_contained_text": "Y is b."},
    ]}
    res = DecompositionStage(_llm(payload)).decompose([("u1", "x")])
    assert res.n_claims == 1 and res.claims[0].subject == "Y"


def test_source_unit_ids_filtered_to_valid():
    payload = {"claims": [{
        "subject": "X", "predicate": "is", "objects": ["a"], "modality": "assertive",
        "polarity": "affirmative", "self_contained_text": "X is a.",
        "source_unit_ids": ["u1", "ghost99"],   # ghost99 inexistant -> filtré
    }]}
    res = DecompositionStage(_llm(payload)).decompose([("u1", "x")])
    assert res.claims[0].source_unit_ids == ["u1"]


def test_parse_failure_returns_empty_flagged():
    res = DecompositionStage(lambda s, u: "garbage not json").decompose([("u1", "x")])
    assert res.judge_failed is True and res.n_claims == 0


def test_llm_exception_flagged():
    def boom(s, u):
        raise RuntimeError("down")
    res = DecompositionStage(boom).decompose([("u1", "x")])
    assert res.judge_failed is True and res.n_claims == 0


def test_disabled_noop():
    def must_not_call(s, u):
        raise AssertionError("should not call")
    res = DecompositionStage(must_not_call, enabled=False).decompose([("u1", "x")])
    assert res.n_claims == 0


def test_self_contained_text_fallback():
    payload = {"claims": [{
        "subject": "X", "predicate": "supports", "objects": ["A", "B"],
        "modality": "assertive", "polarity": "affirmative",  # self_contained_text manquant
    }]}
    res = DecompositionStage(_llm(payload)).decompose([("u1", "x")])
    assert "X" in res.claims[0].self_contained_text
