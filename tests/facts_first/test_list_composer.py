"""
Tests CH-41.3 — ListComposer (mocks LLM).
"""
from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest

from knowbase.facts_first.list_composer import ListComposer


def _make_llm(content):
    if isinstance(content, dict):
        content = json.dumps(content)
    llm = MagicMock()
    llm.chat_completion_with_meta.return_value = {
        "content": content, "logprobs": None,
        "model": "Qwen2.5-72B", "provider": "deepinfra",
    }
    return llm


def _ff_with_items(items, language="en", subject="export authorisation types"):
    return {
        "schema_version": "facts_first_v1",
        "primary_type": "list",
        "answerability": "answerable",
        "coverage_state": "complete",
        "language": language,
        "extracted_at": "2026-05-06T00:00:00Z",
        "extraction_model": "test@mock",
        "list_specific": {
            "list_subject": subject,
            "list_scope": None,
            "items": items,
            "enumeration_quality": {
                "expected_exhaustive": True, "coverage_state": "complete",
                "evidence_count": len(items), "deduped_count": len(items),
                "deduplication_notes": None,
            },
        },
    }


def test_empty_items_deterministic_abstention_fr():
    ff = _ff_with_items([], language="fr")
    res = ListComposer(llm=MagicMock()).compose(ff)
    assert "n'a pas été trouvée" in res.answer_text
    assert res.model == "deterministic"
    assert res.sentence_support[0]["support_ids"] == []


def test_empty_items_deterministic_abstention_en():
    ff = _ff_with_items([], language="en")
    res = ListComposer(llm=MagicMock()).compose(ff)
    assert "not found" in res.answer_text.lower()
    assert res.sentence_support[0]["support_ids"] == []


def test_compose_with_items_calls_llm_and_returns_prose():
    items = [
        {"item_id": "I1", "label": "Individual export authorisation", "item_type": "category",
         "source": {"doc_id": "d1", "claim_id": "c1", "quote": "x" * 20}, "confidence": 0.95},
        {"item_id": "I2", "label": "Global export authorisation", "item_type": "category",
         "source": {"doc_id": "d1", "claim_id": "c2", "quote": "y" * 20}, "confidence": 0.95},
    ]
    ff = _ff_with_items(items, language="en")
    llm_response = {
        "answer_text": "The following export authorisation types were identified:\n- Individual export authorisation\n- Global export authorisation",
        "sentence_support": [
            {"sentence_index": 0, "text": "The following export authorisation types were identified:",
             "support_ids": ["I1", "I2"]},
            {"sentence_index": 1, "text": "Individual export authorisation", "support_ids": ["I1"]},
            {"sentence_index": 2, "text": "Global export authorisation", "support_ids": ["I2"]},
        ],
    }
    res = ListComposer(llm=_make_llm(llm_response)).compose(ff)
    assert "Individual export authorisation" in res.answer_text
    assert "Global export authorisation" in res.answer_text
    assert len(res.sentence_support) == 3
    cited = set(sid for s in res.sentence_support for sid in s["support_ids"])
    assert cited == {"I1", "I2"}


def test_llm_failure_falls_back_to_deterministic():
    items = [
        {"item_id": "I1", "label": "Alpha", "item_type": "value",
         "source": {"doc_id": "d1", "claim_id": "c1", "quote": "x" * 20}, "confidence": 0.9},
        {"item_id": "I2", "label": "Beta", "item_type": "value",
         "source": {"doc_id": "d1", "claim_id": "c2", "quote": "y" * 20}, "confidence": 0.9},
    ]
    ff = _ff_with_items(items, language="fr")
    llm = MagicMock()
    llm.chat_completion_with_meta.side_effect = RuntimeError("down")
    res = ListComposer(llm=llm).compose(ff)
    assert res.model == "deterministic"
    assert "Alpha" in res.answer_text
    assert "Beta" in res.answer_text
    # support_ids référencent les bons items
    cited = set(sid for s in res.sentence_support for sid in s["support_ids"])
    assert "I1" in cited and "I2" in cited


def test_llm_invalid_json_falls_back():
    items = [{"item_id": "I1", "label": "X", "item_type": "value",
              "source": {"doc_id": "d1", "claim_id": "c1", "quote": "x" * 20}, "confidence": 0.9}]
    ff = _ff_with_items(items)
    res = ListComposer(llm=_make_llm("totally not json")).compose(ff)
    assert res.model == "deterministic"
    assert res.parse_error is not None
