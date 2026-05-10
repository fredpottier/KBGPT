"""
Tests CH-41 Tranche 2 — Channel 1 Factual Verifier (déterministe).
"""
from __future__ import annotations

import pytest

from knowbase.facts_first.factual_verifier import Channel1FactualVerifier


def _good_ff(facts=None, direct_ids=None):
    if facts is None:
        facts = [{
            "fact_id": "F1", "subject": "EU 2021/821",
            "predicate": "was adopted on",
            "object": {"raw": "20 May 2021", "normalized": "2021-05-20", "kind": "date", "unit": None},
            "qualifiers": {"condition": None, "scope": None, "time_anchor": None, "lifecycle_status": "ACTIVE"},
            "source": {"doc_id": "d1", "claim_id": "c1", "chunk_id": None, "page_no": 8, "section_id": None,
                       "quote": "Regulation (EU) 2021/821 was adopted on 20 May 2021"},
            "confidence": 0.95,
        }]
    return {
        "schema_version": "facts_first_v1",
        "primary_type": "factual",
        "answerability": "answerable",
        "coverage_state": "not_applicable",
        "language": "en",
        "extracted_at": "2026-05-06T00:00:00Z",
        "extraction_model": "test@mock",
        "factual_specific": {
            "facts": facts,
            "direct_answer_fact_ids": direct_ids if direct_ids is not None else [f["fact_id"] for f in facts[:1]],
        },
    }


def test_valid_facts_first_passes():
    ff = _good_ff()
    report = Channel1FactualVerifier().verify("when was EU 2021/821 adopted", ff)
    assert report.passed is True


def test_missing_common_field_errors():
    ff = _good_ff()
    del ff["coverage_state"]
    report = Channel1FactualVerifier().verify("q", ff)
    assert report.passed is False


def test_bad_primary_type_errors():
    ff = _good_ff()
    ff["primary_type"] = "list"
    report = Channel1FactualVerifier().verify("q", ff)
    assert report.passed is False


def test_quote_too_short_errors():
    facts = [{
        "fact_id": "F1", "subject": "X", "predicate": "is",
        "object": {"raw": "value", "kind": "text"},
        "qualifiers": {"lifecycle_status": "UNKNOWN"},
        "source": {"doc_id": "d1", "claim_id": "c1", "quote": "abc"},  # < 10
        "confidence": 0.9,
    }]
    ff = _good_ff(facts=facts)
    report = Channel1FactualVerifier().verify("q", ff)
    assert report.passed is False


def test_missing_doc_id_errors():
    facts = [{
        "fact_id": "F1", "subject": "X", "predicate": "is",
        "object": {"raw": "value", "kind": "text"},
        "qualifiers": {"lifecycle_status": "UNKNOWN"},
        "source": {"doc_id": "", "claim_id": "c1", "quote": "long enough quote here"},
        "confidence": 0.9,
    }]
    ff = _good_ff(facts=facts)
    report = Channel1FactualVerifier().verify("q", ff)
    assert report.passed is False


def test_duplicate_fact_id_errors():
    facts = [
        {"fact_id": "F1", "subject": "X", "predicate": "is",
         "object": {"raw": "v1", "kind": "text"},
         "qualifiers": {"lifecycle_status": "UNKNOWN"},
         "source": {"doc_id": "d1", "claim_id": "c1", "quote": "long enough quote here for v1"},
         "confidence": 0.9},
        {"fact_id": "F1", "subject": "Y", "predicate": "is",  # dup
         "object": {"raw": "v2", "kind": "text"},
         "qualifiers": {"lifecycle_status": "UNKNOWN"},
         "source": {"doc_id": "d1", "claim_id": "c2", "quote": "long enough quote here for v2"},
         "confidence": 0.9},
    ]
    ff = _good_ff(facts=facts)
    report = Channel1FactualVerifier().verify("q", ff)
    assert report.passed is False


def test_direct_answer_unknown_id_errors():
    ff = _good_ff(direct_ids=["F99"])  # F99 inexistant
    report = Channel1FactualVerifier().verify("q", ff)
    assert report.passed is False


def test_answerable_but_empty_errors():
    ff = _good_ff(facts=[])
    ff["answerability"] = "answerable"
    report = Channel1FactualVerifier().verify("q", ff)
    assert report.passed is False


def test_object_raw_not_in_quote_warning_not_error():
    """Si object.raw n'apparaît pas dans la quote → warning mais pas error."""
    facts = [{
        "fact_id": "F1", "subject": "X", "predicate": "is",
        "object": {"raw": "value_not_in_quote", "kind": "text"},
        "qualifiers": {"lifecycle_status": "UNKNOWN"},
        "source": {"doc_id": "d1", "claim_id": "c1", "quote": "totally different content here long enough"},
        "confidence": 0.9,
    }]
    ff = _good_ff(facts=facts)
    report = Channel1FactualVerifier().verify("q", ff)
    # object.raw mismatch est warning (pas error)
    codes = {i.code: i.severity for i in report.issues}
    if "factual.fact.object.raw_not_in_quote" in codes:
        assert codes["factual.fact.object.raw_not_in_quote"] == "warning"


def test_composer_unknown_support_id_errors():
    ff = _good_ff()
    composer = {
        "answer_text": "EU 2021/821 was adopted on 20 May 2021.",
        "sentence_support": [
            {"sentence_index": 0, "text": "...", "support_ids": ["F1", "F99"]}  # F99 inexistant
        ]
    }
    report = Channel1FactualVerifier().verify("q", ff, composer_output=composer)
    assert report.passed is False


def test_identifier_in_question_satisfied_when_in_quote():
    ff = _good_ff()
    report = Channel1FactualVerifier().verify("when was EU 2021/821 adopted", ff)
    # quote contient "2021/821" → pas d'issue identifier
    assert not any(i.code == "identifier.missing_in_response" for i in report.issues)


def test_lifecycle_status_domain_pack_extension_info_only():
    facts = [{
        "fact_id": "F1", "subject": "X", "predicate": "is",
        "object": {"raw": "value", "kind": "text"},
        "qualifiers": {"lifecycle_status": "DRAFT"},  # Domain Pack extension
        "source": {"doc_id": "d1", "claim_id": "c1", "quote": "long enough quote here for value"},
        "confidence": 0.9,
    }]
    ff = _good_ff(facts=facts)
    report = Channel1FactualVerifier().verify("q", ff)
    # DRAFT n'est pas dans les 3 valeurs core → info-level, pas error
    assert report.passed is True
