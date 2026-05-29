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


def test_procedural_modality_preserved():
    # Phase B : la modalité `procedural` (étape exécutable) doit être conservée
    payload = {"claims": [{
        "subject": "the SI-Check", "predicate": "run before", "objects": ["the conversion"],
        "modality": "procedural", "polarity": "affirmative",
        "self_contained_text": "Run the SI-Check before the conversion.",
        "source_unit_ids": ["u1"],
    }]}
    res = DecompositionStage(_llm(payload)).decompose([("u1", "Run the SI-Check before the conversion.")])
    assert res.claims[0].modality == "procedural"


def test_qualifiers_parsed_and_filtered():
    # Phase B : qualifiers structurés extraits ; entrées non-dict filtrées
    payload = {"claims": [{
        "subject": "the feature", "predicate": "is available in", "objects": ["Private Cloud"],
        "modality": "assertive", "polarity": "affirmative",
        "self_contained_text": "For Private Cloud, the feature is available since release 2023.",
        "source_unit_ids": ["u1"],
        "qualifiers": [
            {"qualifier_type": "version", "value": "Private Cloud edition", "confidence": 0.9},
            {"qualifier_type": "temporal", "value": "since release 2023"},
            "not-a-dict",
        ],
    }]}
    res = DecompositionStage(_llm(payload)).decompose([("u1", "x")])
    quals = res.claims[0].qualifiers
    assert len(quals) == 2
    assert quals[0]["qualifier_type"] == "version"
    assert quals[1]["value"] == "since release 2023"


def test_qualifiers_default_empty():
    payload = {"claims": [{
        "subject": "X", "predicate": "is", "objects": ["a"], "modality": "assertive",
        "polarity": "affirmative", "self_contained_text": "X is a.", "source_unit_ids": ["u1"],
    }]}
    res = DecompositionStage(_llm(payload)).decompose([("u1", "x")])
    assert res.claims[0].qualifiers == []


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


# --- P3.7 : merge déterministe anti-fragmentation énumération ---

def test_fragmented_enumeration_merged_to_one_claim():
    # Simule le 14B violant la règle : 3 claims mono-objet, même unit/subject/predicate.
    payload = {"claims": [
        {"subject": "Assigning catalog X", "predicate": "assigns", "objects": ["catalog CUSTOMER_DSP"],
         "modality": "assertive", "polarity": "affirmative",
         "self_contained_text": "Assigning catalog X assigns catalog CUSTOMER_DSP.", "source_unit_ids": ["u1"]},
        {"subject": "Assigning catalog X", "predicate": "assigns", "objects": ["catalog PRODUCT_DSP"],
         "modality": "assertive", "polarity": "affirmative",
         "self_contained_text": "Assigning catalog X assigns catalog PRODUCT_DSP.", "source_unit_ids": ["u1"]},
        {"subject": "Assigning catalog X", "predicate": "assigns", "objects": ["catalog SUPPLIER_DSP"],
         "modality": "assertive", "polarity": "affirmative",
         "self_contained_text": "Assigning catalog X assigns catalog SUPPLIER_DSP.", "source_unit_ids": ["u1"]},
    ]}
    res = DecompositionStage(_llm(payload)).decompose([("u1", "x")])
    assert res.n_claims == 1, "les 3 fratries d'énumération doivent fusionner en 1 claim"
    c = res.claims[0]
    assert len(c.objects) == 3
    assert all(o in c.self_contained_text for o in
               ["catalog CUSTOMER_DSP", "catalog PRODUCT_DSP", "catalog SUPPLIER_DSP"])


def test_different_predicates_not_merged():
    # Même subject/unit mais prédicats DIFFÉRENTS → ne PAS fusionner.
    payload = {"claims": [
        {"subject": "The engine", "predicate": "weighs", "objects": ["500 kg"],
         "modality": "assertive", "polarity": "affirmative",
         "self_contained_text": "The engine weighs 500 kg.", "source_unit_ids": ["u1"]},
        {"subject": "The engine", "predicate": "runs on", "objects": ["kerosene"],
         "modality": "assertive", "polarity": "affirmative",
         "self_contained_text": "The engine runs on kerosene.", "source_unit_ids": ["u1"]},
    ]}
    res = DecompositionStage(_llm(payload)).decompose([("u1", "x")])
    assert res.n_claims == 2, "prédicats différents → claims séparés"


def test_different_units_not_merged():
    # Même subject/predicate mais unités SOURCES différentes → ne PAS fusionner.
    payload = {"claims": [
        {"subject": "Module A", "predicate": "supports", "objects": ["feature X"],
         "modality": "assertive", "polarity": "affirmative",
         "self_contained_text": "Module A supports feature X.", "source_unit_ids": ["u1"]},
        {"subject": "Module A", "predicate": "supports", "objects": ["feature Y"],
         "modality": "assertive", "polarity": "affirmative",
         "self_contained_text": "Module A supports feature Y.", "source_unit_ids": ["u2"]},
    ]}
    res = DecompositionStage(_llm(payload)).decompose([("u1", "x"), ("u2", "y")])
    assert res.n_claims == 2, "unités sources différentes → pas de fusion"
