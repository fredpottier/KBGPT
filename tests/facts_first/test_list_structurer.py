"""
Tests CH-41.3 — ListStructurer (mocks LLM).
"""
from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest

from knowbase.facts_first.evidence_collector import EvidenceBundle, EvidenceClaim
from knowbase.facts_first.list_structurer import ListStructurer


def _make_llm(content):
    if isinstance(content, dict):
        content = json.dumps(content)
    llm = MagicMock()
    llm.chat_completion_with_meta.return_value = {
        "content": content, "logprobs": None,
        "model": "Qwen2.5-72B", "provider": "deepinfra",
    }
    return llm


def _bundle_with_claims(quotes_per_doc):
    """quotes_per_doc = list of (doc_id, quote, claim_id) tuples."""
    claims = []
    for doc, quote, cid in quotes_per_doc:
        claims.append(EvidenceClaim(
            claim_id=cid, doc_id=doc, chunk_id=None, page_no=None,
            quote=quote, score=0.85, enriched_from_neo4j=True,
        ))
    return EvidenceBundle(question="q", claims=claims, n_qdrant_hits=len(claims), n_neo4j_enriched=len(claims))


def test_no_evidence_returns_unanswerable():
    structurer = ListStructurer(llm=_make_llm({}))
    bundle = EvidenceBundle(question="q", claims=[])
    res = structurer.structure("q", bundle)
    ff = res.facts_first_json
    assert ff["answerability"] == "unanswerable"
    assert ff["coverage_state"] == "unknown"
    assert ff["list_specific"]["items"] == []
    assert ff["list_specific"]["enumeration_quality"]["deduped_count"] == 0


def test_grounded_items_kept_hallucinations_rejected():
    """Le LLM peut renvoyer un item halluciné dont la quote n'est pas dans le pool — il doit être rejeté."""
    bundle = _bundle_with_claims([
        ("doc_2021_821", "Individual export authorisation is granted to one specific exporter for one end-user", "c1"),
        ("doc_2021_821", "Global export authorisation grants an authorisation to one specific exporter for a type or category of dual-use items", "c2"),
    ])
    llm_response = {
        "list_subject": "export authorisation types",
        "list_scope": {"scope_description": "EU 2021/821", "doc_id": "doc_2021_821", "section_id": None, "confidence": 0.9},
        "items": [
            # Valid — quote substring of pool
            {"item_id": "I1", "label": "Individual export authorisation",
             "normalized_label": "individual export authorisation", "item_type": "category",
             "source": {"doc_id": "doc_2021_821", "claim_id": "c1", "chunk_id": None, "page_no": None,
                        "section_id": None, "quote": "Individual export authorisation is granted to one specific exporter"},
             "confidence": 0.95},
            # Valid via overlap
            {"item_id": "I2", "label": "Global export authorisation",
             "normalized_label": "global export authorisation", "item_type": "category",
             "source": {"doc_id": "doc_2021_821", "claim_id": "c2", "chunk_id": None, "page_no": None,
                        "section_id": None, "quote": "Global export authorisation grants an authorisation to one specific exporter"},
             "confidence": 0.95},
            # Hallucination — quote not in pool
            {"item_id": "I3", "label": "Phantom authorisation",
             "normalized_label": "phantom", "item_type": "category",
             "source": {"doc_id": "doc_2021_821", "claim_id": "fake", "chunk_id": None, "page_no": None,
                        "section_id": None, "quote": "Phantom authorisation grants nothing to nobody never anywhere always"},
             "confidence": 0.7},
        ],
        "enumeration_quality": {
            "expected_exhaustive": True, "coverage_state": "partial",
            "evidence_count": 2, "deduped_count": 3, "deduplication_notes": None,
        },
    }
    res = ListStructurer(llm=_make_llm(llm_response)).structure(
        "List the authorisation types",
        bundle,
        language="en",
    )
    ff = res.facts_first_json
    assert ff["primary_type"] == "list"
    assert ff["answerability"] in ("answerable", "partial")
    items = ff["list_specific"]["items"]
    assert len(items) == 2  # phantom rejeté
    labels = {i["label"] for i in items}
    assert "Individual export authorisation" in labels
    assert "Global export authorisation" in labels
    assert "Phantom authorisation" not in labels
    assert any(r.get("reason") == "quote_not_grounded" for r in res.rejected_items)
    assert ff["list_specific"]["enumeration_quality"]["deduped_count"] == 2


def test_dedup_by_normalized_label():
    bundle = _bundle_with_claims([
        ("d1", "One specific exporter for type alpha listed in Annex II", "c1"),
    ])
    llm_response = {
        "list_subject": "items",
        "list_scope": None,
        "items": [
            {"item_id": "I1", "label": "Type Alpha",
             "normalized_label": "alpha", "item_type": "category",
             "source": {"doc_id": "d1", "claim_id": "c1", "chunk_id": None, "page_no": None,
                        "section_id": None, "quote": "One specific exporter for type alpha"},
             "confidence": 0.9},
            {"item_id": "I2", "label": "ALPHA",
             "normalized_label": "alpha", "item_type": "category",  # même normalized → dup
             "source": {"doc_id": "d1", "claim_id": "c1", "chunk_id": None, "page_no": None,
                        "section_id": None, "quote": "One specific exporter for type alpha"},
             "confidence": 0.85},
        ],
        "enumeration_quality": {
            "expected_exhaustive": False, "coverage_state": "partial",
            "evidence_count": 1, "deduped_count": 1, "deduplication_notes": "merged duplicates",
        },
    }
    res = ListStructurer(llm=_make_llm(llm_response)).structure("q", bundle)
    items = res.facts_first_json["list_specific"]["items"]
    assert len(items) == 1
    assert any(r.get("reason") == "duplicate" for r in res.rejected_items)


def test_quote_too_short_rejected():
    bundle = _bundle_with_claims([("d1", "Long enough passage to keep this item", "c1")])
    llm_response = {
        "list_subject": "x", "list_scope": None,
        "items": [
            {"item_id": "I1", "label": "X", "normalized_label": "x", "item_type": "value",
             "source": {"doc_id": "d1", "claim_id": "c1", "chunk_id": None, "page_no": None,
                        "section_id": None, "quote": "short"},  # < 10 chars
             "confidence": 0.9}
        ],
        "enumeration_quality": {"expected_exhaustive": False, "coverage_state": "partial",
                                 "evidence_count": 1, "deduped_count": 1, "deduplication_notes": None},
    }
    res = ListStructurer(llm=_make_llm(llm_response)).structure("q", bundle)
    assert res.facts_first_json["list_specific"]["items"] == []
    assert any(r.get("reason") == "quote_too_short" for r in res.rejected_items)


def test_llm_json_parse_error_returns_empty_with_parse_error():
    bundle = _bundle_with_claims([("d1", "Long enough passage to keep", "c1")])
    res = ListStructurer(llm=_make_llm("not a json")).structure("q", bundle)
    assert res.parse_error and "json_parse" in res.parse_error
    assert res.facts_first_json["answerability"] == "unanswerable"


def test_llm_exception_returns_empty():
    bundle = _bundle_with_claims([("d1", "Long enough passage to keep", "c1")])
    llm = MagicMock()
    llm.chat_completion_with_meta.side_effect = RuntimeError("api down")
    res = ListStructurer(llm=llm).structure("q", bundle)
    assert res.facts_first_json["answerability"] == "unanswerable"
    assert "api down" in (res.parse_error or "")


def test_facts_first_v1_required_common_fields_present():
    bundle = _bundle_with_claims([("d1", "Long enough passage with item alpha to keep", "c1")])
    llm_response = {
        "list_subject": "items", "list_scope": None,
        "items": [
            {"item_id": "I1", "label": "alpha", "normalized_label": "alpha", "item_type": "value",
             "source": {"doc_id": "d1", "claim_id": "c1", "chunk_id": None, "page_no": None,
                        "section_id": None, "quote": "Long enough passage with item alpha"},
             "confidence": 0.9}
        ],
        "enumeration_quality": {"expected_exhaustive": False, "coverage_state": "partial",
                                "evidence_count": 1, "deduped_count": 1, "deduplication_notes": None},
    }
    res = ListStructurer(llm=_make_llm(llm_response)).structure("q", bundle, language="fr")
    ff = res.facts_first_json
    assert ff["schema_version"] == "facts_first_v1"
    assert ff["primary_type"] == "list"
    assert ff["language"] == "fr"
    assert "extracted_at" in ff
    assert "extraction_model" in ff
    # extraction_model format = <model>@<provider>
    assert "@" in ff["extraction_model"]
