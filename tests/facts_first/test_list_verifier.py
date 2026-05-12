"""
Tests CH-41.3 — Channel 1 List Verifier (déterministe, no LLM).
"""
from __future__ import annotations

import pytest

from knowbase.facts_first.list_verifier import (
    Channel1ListVerifier,
    SEVERITY_ERROR,
    SEVERITY_WARNING,
)


def _good_ff(items=None):
    items = items if items is not None else [
        {"item_id": "I1", "label": "Item Alpha",
         "normalized_label": "alpha", "item_type": "category",
         "source": {"doc_id": "d1", "claim_id": "c1", "chunk_id": None, "page_no": None,
                    "section_id": None, "quote": "Item Alpha is the first one"},
         "confidence": 0.9},
        {"item_id": "I2", "label": "Item Beta",
         "normalized_label": "beta", "item_type": "category",
         "source": {"doc_id": "d1", "claim_id": "c2", "chunk_id": None, "page_no": None,
                    "section_id": None, "quote": "Item Beta follows Alpha"},
         "confidence": 0.85},
    ]
    return {
        "schema_version": "facts_first_v1",
        "primary_type": "list",
        "answerability": "answerable",
        "coverage_state": "complete",
        "language": "en",
        "extracted_at": "2026-05-06T00:00:00Z",
        "extraction_model": "test@mock",
        "list_specific": {
            "list_subject": "items",
            "list_scope": None,
            "items": items,
            "enumeration_quality": {
                "expected_exhaustive": True, "coverage_state": "complete",
                "evidence_count": len(items), "deduped_count": len(items),
                "deduplication_notes": None,
            },
        },
    }


def _good_composer(item_ids):
    return {
        "answer_text": "intro: " + ", ".join(item_ids),
        "sentence_support": [
            {"sentence_index": 0, "text": "intro", "support_ids": list(item_ids)},
        ],
    }


def test_valid_facts_first_passes():
    ff = _good_ff()
    report = Channel1ListVerifier().verify("question", ff)
    assert report.passed is True
    assert report.severity in ("info", "warning")  # peut avoir des warnings sur identifier


def test_missing_common_field_errors():
    ff = _good_ff()
    del ff["coverage_state"]
    report = Channel1ListVerifier().verify("q", ff)
    assert report.passed is False
    assert any(i.code == "schema.common.missing_field" for i in report.issues)


def test_bad_schema_version_errors():
    ff = _good_ff()
    ff["schema_version"] = "facts_first_v2"
    report = Channel1ListVerifier().verify("q", ff)
    assert report.passed is False
    assert any(i.code == "schema.common.bad_version" for i in report.issues)


def test_duplicate_item_id_errors():
    items = [
        {"item_id": "I1", "label": "Alpha", "normalized_label": "alpha", "item_type": "value",
         "source": {"doc_id": "d1", "claim_id": "c1", "chunk_id": None, "page_no": None,
                    "section_id": None, "quote": "Alpha is here for sure"},
         "confidence": 0.9},
        {"item_id": "I1", "label": "Beta", "normalized_label": "beta", "item_type": "value",  # dup id
         "source": {"doc_id": "d1", "claim_id": "c2", "chunk_id": None, "page_no": None,
                    "section_id": None, "quote": "Beta follows for sure"},
         "confidence": 0.9},
    ]
    ff = _good_ff(items=items)
    report = Channel1ListVerifier().verify("q", ff)
    assert report.passed is False
    assert any(i.code == "item.duplicate_id" for i in report.issues)


def test_quote_too_short_errors():
    items = [
        {"item_id": "I1", "label": "Alpha", "normalized_label": "alpha", "item_type": "value",
         "source": {"doc_id": "d1", "claim_id": "c1", "chunk_id": None, "page_no": None,
                    "section_id": None, "quote": "abc"},  # 3 chars < 10
         "confidence": 0.9},
    ]
    ff = _good_ff(items=items)
    report = Channel1ListVerifier().verify("q", ff)
    assert report.passed is False
    assert any(i.code == "item.source.quote_too_short" for i in report.issues)


def test_missing_doc_id_errors():
    items = [
        {"item_id": "I1", "label": "Alpha", "normalized_label": "alpha", "item_type": "value",
         "source": {"doc_id": "", "claim_id": "c1", "chunk_id": None, "page_no": None,
                    "section_id": None, "quote": "Alpha is here for sure"},
         "confidence": 0.9},
    ]
    ff = _good_ff(items=items)
    report = Channel1ListVerifier().verify("q", ff)
    assert report.passed is False
    assert any(i.code == "item.source.missing_doc_id" for i in report.issues)


def test_complete_but_empty_errors():
    ff = _good_ff(items=[])
    ff["coverage_state"] = "complete"
    ff["list_specific"]["enumeration_quality"]["coverage_state"] = "complete"
    ff["answerability"] = "answerable"
    report = Channel1ListVerifier().verify("q", ff)
    assert report.passed is False
    codes = {i.code for i in report.issues}
    assert "coverage.complete_but_empty" in codes or "answerability.answerable_but_empty" in codes


def test_composer_unknown_support_id_errors():
    ff = _good_ff()
    composer = {
        "answer_text": "text",
        "sentence_support": [
            {"sentence_index": 0, "text": "intro", "support_ids": ["I1", "I99"]},  # I99 inexistant
        ],
    }
    report = Channel1ListVerifier().verify("q", ff, composer_output=composer)
    assert any(i.code == "composer.support_ids.unknown" for i in report.issues)
    assert report.passed is False


def test_composer_uncited_items_warning_only():
    """Items non cités → warning, pas error."""
    ff = _good_ff()
    composer = {
        "answer_text": "text",
        "sentence_support": [
            {"sentence_index": 0, "text": "intro", "support_ids": ["I1"]},  # I2 non cité
        ],
    }
    report = Channel1ListVerifier().verify("q", ff, composer_output=composer)
    codes = {i.code: i.severity for i in report.issues}
    if "composer.items.uncited" in codes:
        assert codes["composer.items.uncited"] == "warning"


def test_identifier_in_question_signals_warning_if_missing_in_response():
    """Question avec EU 2021/821 mais aucun item ne le mentionne → warning."""
    ff = _good_ff()
    # items dont les labels et quotes ne contiennent PAS "2021/821"
    report = Channel1ListVerifier().verify("List items in EU 2021/821", ff)
    assert any(i.code == "identifier.missing_in_response" and i.severity == "warning" for i in report.issues)
    assert report.passed is True  # warnings ne bloquent pas


def test_identifier_in_question_satisfied_when_present_in_quote():
    items = [
        {"item_id": "I1", "label": "Alpha", "normalized_label": "alpha", "item_type": "value",
         "source": {"doc_id": "d1", "claim_id": "c1", "chunk_id": None, "page_no": None,
                    "section_id": None, "quote": "EU 2021/821 Article 8 introduces Alpha"},
         "confidence": 0.9},
    ]
    ff = _good_ff(items=items)
    ff["coverage_state"] = "partial"
    ff["list_specific"]["enumeration_quality"]["coverage_state"] = "partial"
    ff["list_specific"]["enumeration_quality"]["deduped_count"] = 1
    report = Channel1ListVerifier().verify("List items in EU 2021/821", ff)
    assert not any(i.code == "identifier.missing_in_response" for i in report.issues)


def test_deduped_count_mismatch_warning():
    ff = _good_ff()
    ff["list_specific"]["enumeration_quality"]["deduped_count"] = 99  # incohérent
    report = Channel1ListVerifier().verify("q", ff)
    assert any(i.code == "coverage.deduped_count_mismatch" for i in report.issues)
