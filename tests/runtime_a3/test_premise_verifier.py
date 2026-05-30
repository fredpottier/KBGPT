"""Tests PremiseVerifier — extraction + retrieval dédié + vérif 3-voies.

Mocks : llm_client (extract puis verify selon le system prompt), embedder, qdrant_search.
Cf ADR_PREMISE_VERIFIER.md.
"""
from __future__ import annotations

import json

from knowbase.runtime_a3.premise_verifier import PremiseVerifier, PremiseResult, _parse_json


class _MockLLM:
    """Retourne extract_json sur le prompt d'extraction, verify_json sinon."""

    def __init__(self, extract_json: dict, verify_json: dict, raise_on=None):
        self._extract = json.dumps(extract_json, ensure_ascii=False)
        self._verify = json.dumps(verify_json, ensure_ascii=False)
        self._raise_on = raise_on  # "extract" | "verify" | None

    def complete(self, system: str, user: str) -> str:
        is_extract = "extract the PRESUPPOSITIONS" in system
        if self._raise_on == "extract" and is_extract:
            raise RuntimeError("boom-extract")
        if self._raise_on == "verify" and not is_extract:
            raise RuntimeError("boom-verify")
        return self._extract if is_extract else self._verify


def _fake_embedder(_text):
    return [0.0] * 8


def _fake_search(**kwargs):
    # 2 passages d'evidence quelconques
    return [
        {"payload": {"text": "A new installation of SystemY needs to run on the HANA database."}},
        {"payload": {"text": "SystemY connects to external systems via standard connectors."}},
    ]


class _FakeNeo4j:
    """Retourne n claims contenant l'entité (0 par défaut = non attesté en KG)."""

    def __init__(self, n=0):
        self._n = n

    def execute_query(self, *_a, **_k):
        return [{"n": self._n}]


def _make(llm, search=_fake_search, neo4j=None) -> PremiseVerifier:
    return PremiseVerifier(
        llm_client=llm, embedder=_fake_embedder, qdrant_search=search,
        neo4j_client=neo4j or _FakeNeo4j(0),
    )


def test_false_contradicted():
    llm = _MockLLM(
        extract_json={"presuppositions": ["SystemY natively supports Oracle"]},
        verify_json={"status": "FALSE_CONTRADICTED", "reasoning": "requires HANA",
                     "correction": "SystemY requires HANA, not Oracle."},
    )
    r = _make(llm).verify("How does native Oracle support work in SystemY?")
    assert r.status == "FALSE_CONTRADICTED"
    assert r.is_false_premise is True
    assert "HANA" in r.correction
    assert r.presuppositions == ["SystemY natively supports Oracle"]


def test_false_unsupported_entity_absent_stays():
    # focal_entity absent du corpus (les fake chunks parlent de HANA/connectors) → reste UNSUPPORTED
    llm = _MockLLM(
        extract_json={"presuppositions": ["ProductX has a Quantum Cache module"],
                      "focal_entity": "Quantum Cache module"},
        verify_json={"status": "FALSE_UNSUPPORTED", "reasoning": "not found",
                     "correction": "No such module documented."},
    )
    r = _make(llm).verify("How to enable the Quantum Cache module in ProductX?")
    assert r.status == "FALSE_UNSUPPORTED"
    assert r.is_false_premise is True


def test_unsupported_downgraded_when_entity_attested():
    # L'entité apparaît pourtant dans le corpus → raté de retrieval → rétrograde en OK.
    def search_with_entity(**kwargs):
        return [{"payload": {"text": "The Labeling Workbench (transaction CBGLWB) filters print requests."}}]

    llm = _MockLLM(
        extract_json={"presuppositions": ["System has a Labeling Workbench"],
                      "focal_entity": "Labeling Workbench"},
        verify_json={"status": "FALSE_UNSUPPORTED", "reasoning": "only adjacent items",
                     "correction": "No such feature."},
    )
    r = _make(llm, search=search_with_entity).verify("Which transaction is used for the Labeling Workbench?")
    assert r.status == "OK"  # rétrogradé car l'entité est attestée
    assert r.is_false_premise is False


def test_contradicted_not_downgraded_even_if_entity_present():
    # CONTRADICTED n'est jamais rétrogradé par la confirmation lexicale.
    def search_with_entity(**kwargs):
        return [{"payload": {"text": "SystemY native Oracle is mentioned here verbatim."}}]

    llm = _MockLLM(
        extract_json={"presuppositions": ["SystemY natively supports Oracle"],
                      "focal_entity": "native Oracle"},
        verify_json={"status": "FALSE_CONTRADICTED", "reasoning": "requires HANA",
                     "correction": "Requires HANA."},
    )
    r = _make(llm, search=search_with_entity).verify("How does native Oracle work in SystemY?")
    assert r.status == "FALSE_CONTRADICTED"


def test_ok_not_flagged():
    llm = _MockLLM(
        extract_json={"presuppositions": ["France has a capital"]},
        verify_json={"status": "OK", "reasoning": "attested", "correction": ""},
    )
    r = _make(llm).verify("What is the capital of France?")
    assert r.status == "OK"
    assert r.is_false_premise is False


def test_no_presupposition_is_ok():
    llm = _MockLLM(extract_json={"presuppositions": []}, verify_json={"status": "OK"})
    r = _make(llm).verify("Hello?")
    assert r.status == "OK"
    assert r.presuppositions == []


def test_empty_question_is_ok():
    r = _make(_MockLLM({"presuppositions": []}, {"status": "OK"})).verify("   ")
    assert r.status == "OK"


def test_extract_failure_fail_open():
    llm = _MockLLM({"presuppositions": ["x"]}, {"status": "FALSE_CONTRADICTED"}, raise_on="extract")
    r = _make(llm).verify("anything")
    assert r.status == "OK"  # fail-open
    assert r.llm_failed is True


def test_verify_failure_fail_open():
    llm = _MockLLM({"presuppositions": ["x exists"]}, {"status": "FALSE_CONTRADICTED"}, raise_on="verify")
    r = _make(llm).verify("anything about x")
    assert r.status == "OK"  # fail-open
    assert r.llm_failed is True


def test_invalid_status_coerced_to_ok():
    llm = _MockLLM({"presuppositions": ["x exists"]}, {"status": "WEIRD", "reasoning": "?"})
    r = _make(llm).verify("anything")
    assert r.status == "OK"


def test_parse_json_with_markdown_fence():
    assert _parse_json('```json\n{"status": "OK"}\n```') == {"status": "OK"}


def test_parse_json_embedded_object():
    assert _parse_json('blah {"status": "OK"} trailing')["status"] == "OK"


def test_parse_json_garbage_returns_none():
    assert _parse_json("not json at all") is None
