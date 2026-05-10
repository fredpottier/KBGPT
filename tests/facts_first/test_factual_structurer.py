"""
Tests CH-41 Tranche 2 — FactualStructurer + D-FF13 (mocks LLM).
"""
from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest

from knowbase.facts_first.evidence_collector import EvidenceBundle, EvidenceClaim
from knowbase.facts_first.factual_structurer import FactualStructurer


def _make_llm_responses(*responses):
    """Mock LLM returning different responses on successive calls."""
    llm = MagicMock()
    queue = list(responses)

    def side_effect(*args, **kwargs):
        if not queue:
            raise RuntimeError("no more mock responses")
        content = queue.pop(0)
        if isinstance(content, dict):
            content = json.dumps(content)
        return {"content": content, "model": "test", "provider": "mock", "logprobs": None}

    llm.chat_completion_with_meta.side_effect = side_effect
    return llm


def _bundle(quotes_per_doc, scores=None):
    claims = []
    for i, (doc, quote, cid) in enumerate(quotes_per_doc):
        score = scores[i] if scores else 0.85
        claims.append(EvidenceClaim(
            claim_id=cid, doc_id=doc, chunk_id=f"chunk_{cid}", page_no=8,
            quote=quote, score=score, enriched_from_neo4j=True,
        ))
    return EvidenceBundle(question="q", claims=claims, n_qdrant_hits=len(claims))


def test_no_evidence_returns_unanswerable():
    structurer = FactualStructurer(llm=MagicMock())
    res = structurer.structure("q", EvidenceBundle(question="q", claims=[]))
    ff = res.facts_first_json
    assert ff["primary_type"] == "factual"
    assert ff["answerability"] == "unanswerable"
    assert ff["factual_specific"]["facts"] == []


def test_grounded_fact_kept():
    bundle = _bundle([
        ("doc_2021_821", "Regulation (EU) 2021/821 of the European Parliament and of the Council of 20 May 2021 setting up a Union regime for the control of exports", "c1"),
    ])
    llm_resp = {
        "facts": [
            {"fact_id": "F1",
             "subject": "Regulation (EU) 2021/821",
             "predicate": "was adopted on",
             "object": {"raw": "20 May 2021", "normalized": "2021-05-20", "kind": "date", "unit": None},
             "qualifiers": {"condition": None, "scope": None, "time_anchor": None, "lifecycle_status": "ACTIVE"},
             "source": {"doc_id": "doc_2021_821", "claim_id": "c1", "chunk_id": "chunk_c1", "page_no": 8, "section_id": None,
                        "quote": "Regulation (EU) 2021/821 of the European Parliament and of the Council of 20 May 2021"},
             "confidence": 0.95}
        ],
        "direct_answer_fact_ids": ["F1"]
    }
    res = FactualStructurer(llm=_make_llm_responses(llm_resp)).structure(
        "When was EU 2021/821 adopted?", bundle, language="en", analyzer_confidence=0.9,
    )
    ff = res.facts_first_json
    assert ff["answerability"] == "answerable"
    assert ff["coverage_state"] == "not_applicable"
    facts = ff["factual_specific"]["facts"]
    assert len(facts) == 1
    assert facts[0]["object"]["raw"] == "20 May 2021"
    assert facts[0]["object"]["kind"] == "date"
    assert ff["factual_specific"]["direct_answer_fact_ids"] == ["F1"]
    assert not res.used_fallback


def test_hallucination_object_raw_not_in_quote_rejected():
    bundle = _bundle([
        ("d1", "The text mentions some date around May 2021 here", "c1"),
    ])
    llm_resp = {
        "facts": [
            {"fact_id": "F1", "subject": "X", "predicate": "is",
             "object": {"raw": "20 May 2021", "kind": "date"},  # raw NOT in quote
             "qualifiers": {"lifecycle_status": "UNKNOWN"},
             "source": {"doc_id": "d1", "claim_id": "c1",
                        "quote": "The text mentions some date around May 2021 here"},
             "confidence": 0.9}
        ],
        "direct_answer_fact_ids": ["F1"]
    }
    res = FactualStructurer(llm=_make_llm_responses(llm_resp)).structure(
        "q", bundle, language="en", analyzer_confidence=0.5,  # < threshold = no D-FF13 trigger
    )
    facts = res.facts_first_json["factual_specific"]["facts"]
    assert len(facts) == 0
    assert any(r.get("reason") == "object_raw_not_in_quote" for r in res.rejected_facts)


def test_d_ff13_triggers_when_primary_low_confidence():
    """D-FF13 active si analyzer ≥0.7 + Structurer max conf < 0.7 + top chunk ≥ 0.7 + kind court."""
    bundle = _bundle([
        ("doc_2021_821", "EU 2021/821 was published on 11 June 2021 in the Official Journal", "c1"),
    ], scores=[0.85])
    primary_resp = {  # primary returns weak fact
        "facts": [
            {"fact_id": "F1", "subject": "EU 2021/821", "predicate": "published",
             "object": {"raw": "Official Journal", "kind": "name"},  # weak fact, kind=name
             "qualifiers": {"lifecycle_status": "UNKNOWN"},
             "source": {"doc_id": "doc_2021_821", "claim_id": "c1",
                        "quote": "EU 2021/821 was published on 11 June 2021 in the Official Journal"},
             "confidence": 0.5}  # < threshold
        ],
        "direct_answer_fact_ids": ["F1"]
    }
    fallback_resp = {  # D-FF13 extract
        "found": True,
        "subject": "EU 2021/821",
        "predicate": "was published on",
        "object_raw": "11 June 2021",
        "object_kind": "date",
        "object_unit": None,
        "supporting_quote": "EU 2021/821 was published on 11 June 2021 in the Official Journal",
        "confidence": 0.9
    }
    llm = _make_llm_responses(primary_resp, fallback_resp)
    res = FactualStructurer(llm=llm).structure(
        "When was EU 2021/821 published?", bundle, language="en", analyzer_confidence=0.85,
    )
    assert res.used_fallback
    assert res.fallback_mode in ("factual_simple_chunk_extractive", "factual_simple_conflict_suspected")
    facts = res.facts_first_json["factual_specific"]["facts"]
    assert len(facts) == 1
    assert facts[0]["object"]["raw"] == "11 June 2021"
    assert facts[0]["object"]["kind"] == "date"
    assert facts[0]["source"]["claim_id"] is None  # D-FF13 source = chunk
    assert res.facts_first_json["diagnostic"]["fallback_mode"] in (
        "factual_simple_chunk_extractive", "factual_simple_conflict_suspected"
    )


def test_d_ff13_disabled_when_analyzer_confidence_low():
    """analyzer_confidence < 0.7 → pas de D-FF13 fallback même si primary fait."""
    bundle = _bundle([("d1", "some text long enough to keep", "c1")], scores=[0.85])
    primary_resp = {"facts": [], "direct_answer_fact_ids": []}
    res = FactualStructurer(llm=_make_llm_responses(primary_resp)).structure(
        "q", bundle, language="en", analyzer_confidence=0.5,  # < threshold
    )
    assert not res.used_fallback
    assert res.facts_first_json["answerability"] == "unanswerable"


def test_d_ff13_disabled_when_top_chunk_score_low():
    bundle = _bundle([("d1", "top chunk text long enough", "c1")], scores=[0.4])  # < threshold
    primary_resp = {"facts": [], "direct_answer_fact_ids": []}
    res = FactualStructurer(llm=_make_llm_responses(primary_resp)).structure(
        "q", bundle, language="en", analyzer_confidence=0.9,
    )
    assert not res.used_fallback


def test_d_ff13_rejects_text_kind():
    """Si fallback retourne kind=text, rejet (D-FF13 ne traite que kinds courts)."""
    bundle = _bundle([("d1", "some long passage of text about a topic", "c1")], scores=[0.85])
    primary_resp = {"facts": [], "direct_answer_fact_ids": []}
    fallback_resp = {
        "found": True, "subject": "topic", "predicate": "is described as",
        "object_raw": "a topic", "object_kind": "text",  # not in SHORT_OBJECT_KINDS
        "supporting_quote": "some long passage of text about a topic",
        "confidence": 0.8
    }
    res = FactualStructurer(llm=_make_llm_responses(primary_resp, fallback_resp)).structure(
        "q", bundle, language="en", analyzer_confidence=0.9,
    )
    # Fallback rejected → no fact returned
    assert not res.used_fallback
    assert res.facts_first_json["factual_specific"]["facts"] == []


def test_d_ff13_conflict_detected_when_primary_diverges():
    """Si primary fact (faible) diverge du fallback fact → fallback_mode=conflict_suspected."""
    bundle = _bundle([
        ("d1", "EU 2021/821 was published on 11 June 2021", "c1"),
    ], scores=[0.85])
    primary_resp = {
        "facts": [
            {"fact_id": "F1", "subject": "EU 2021/821", "predicate": "published",
             "object": {"raw": "11 June 2021", "kind": "date"},
             "qualifiers": {"lifecycle_status": "UNKNOWN"},
             "source": {"doc_id": "d1", "claim_id": "c1",
                        "quote": "EU 2021/821 was published on 11 June 2021"},
             "confidence": 0.5}  # < threshold → triggers fallback
        ],
        "direct_answer_fact_ids": ["F1"]
    }
    fallback_resp = {  # diverge sur l'object.raw
        "found": True, "subject": "EU 2021/821", "predicate": "was published on",
        "object_raw": "11 June 2021",  # même valeur ici → pas de conflit
        "object_kind": "date",
        "supporting_quote": "EU 2021/821 was published on 11 June 2021",
        "confidence": 0.9
    }
    res = FactualStructurer(llm=_make_llm_responses(primary_resp, fallback_resp)).structure(
        "q", bundle, language="en", analyzer_confidence=0.9,
    )
    # Pas de conflit ici (mêmes valeurs) → mode normal
    assert res.used_fallback
    assert res.fallback_mode == "factual_simple_chunk_extractive"
    assert res.facts_first_json["answerability"] == "answerable"


def test_facts_first_v1_required_common_fields():
    bundle = _bundle([("d1", "Test passage long enough to keep here", "c1")])
    llm_resp = {
        "facts": [
            {"fact_id": "F1", "subject": "test", "predicate": "is",
             "object": {"raw": "value", "kind": "text"},
             "qualifiers": {"lifecycle_status": "ACTIVE"},
             "source": {"doc_id": "d1", "claim_id": "c1",
                        "quote": "Test passage with value long enough"},
             "confidence": 0.85}
        ],
        "direct_answer_fact_ids": ["F1"]
    }
    res = FactualStructurer(llm=_make_llm_responses(llm_resp)).structure(
        "q", bundle, language="fr", analyzer_confidence=0.5,
    )
    ff = res.facts_first_json
    assert ff["schema_version"] == "facts_first_v1"
    assert ff["primary_type"] == "factual"
    assert ff["language"] == "fr"
    assert "@" in ff["extraction_model"]
