"""
Tests CH-41 Tranche 2 — FactualComposer (mocks LLM).
"""
from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest

from knowbase.facts_first.factual_composer import FactualComposer


def _llm(content):
    if isinstance(content, dict):
        content = json.dumps(content)
    llm = MagicMock()
    llm.chat_completion_with_meta.return_value = {
        "content": content, "model": "test", "provider": "mock", "logprobs": None,
    }
    return llm


def _ff_with_facts(facts, language="en", direct_ids=None, fallback_mode=None):
    return {
        "schema_version": "facts_first_v1",
        "primary_type": "factual",
        "answerability": "answerable" if facts else "unanswerable",
        "coverage_state": "not_applicable",
        "language": language,
        "extracted_at": "2026-05-06T00:00:00Z",
        "extraction_model": "test@mock",
        "factual_specific": {
            "facts": facts,
            "direct_answer_fact_ids": direct_ids or ([f["fact_id"] for f in facts[:1]] if facts else []),
        },
        "diagnostic": {"fallback_mode": fallback_mode},
    }


def test_empty_facts_deterministic_fr():
    ff = _ff_with_facts([], language="fr")
    res = FactualComposer(llm=MagicMock()).compose(ff)
    assert "n'a pas été trouvée" in res.answer_text
    assert res.model == "deterministic"


def test_empty_facts_deterministic_en():
    ff = _ff_with_facts([], language="en")
    res = FactualComposer(llm=MagicMock()).compose(ff)
    assert "not found" in res.answer_text.lower()


def test_compose_single_fact():
    fact = {
        "fact_id": "F1", "subject": "EU 2021/821",
        "predicate": "was adopted on",
        "object": {"raw": "20 May 2021", "kind": "date", "unit": None},
        "qualifiers": {"lifecycle_status": "ACTIVE"},
        "source": {"doc_id": "d1", "claim_id": "c1", "quote": "x" * 30},
        "confidence": 0.95,
    }
    ff = _ff_with_facts([fact], language="en")
    llm_resp = {
        "answer_text": "Regulation (EU) 2021/821 was adopted on 20 May 2021.",
        "sentence_support": [
            {"sentence_index": 0, "text": "Regulation (EU) 2021/821 was adopted on 20 May 2021.", "support_ids": ["F1"]}
        ]
    }
    res = FactualComposer(llm=_llm(llm_resp)).compose(ff)
    assert "20 May 2021" in res.answer_text
    assert len(res.sentence_support) == 1
    assert "F1" in res.sentence_support[0]["support_ids"]


def test_llm_failure_falls_back_deterministic():
    fact = {
        "fact_id": "F1", "subject": "X", "predicate": "is",
        "object": {"raw": "value", "kind": "text", "unit": None},
        "qualifiers": {"lifecycle_status": "ACTIVE"},
        "source": {"doc_id": "d1", "claim_id": "c1", "quote": "x" * 30},
        "confidence": 0.9,
    }
    ff = _ff_with_facts([fact])
    llm = MagicMock()
    llm.chat_completion_with_meta.side_effect = RuntimeError("down")
    res = FactualComposer(llm=llm).compose(ff)
    assert res.model == "deterministic"
    assert "value" in res.answer_text


def test_llm_invalid_json_falls_back():
    fact = {
        "fact_id": "F1", "subject": "X", "predicate": "is",
        "object": {"raw": "value", "kind": "text", "unit": None},
        "qualifiers": {"lifecycle_status": "ACTIVE"},
        "source": {"doc_id": "d1", "claim_id": "c1", "quote": "x" * 30},
        "confidence": 0.9,
    }
    ff = _ff_with_facts([fact])
    res = FactualComposer(llm=_llm("not valid json {")).compose(ff)
    assert res.model == "deterministic"


def test_unit_appended_in_deterministic_fallback():
    fact = {
        "fact_id": "F1", "subject": "the impact energy", "predicate": "is",
        "object": {"raw": "21", "kind": "number", "unit": "J"},
        "qualifiers": {"lifecycle_status": "ACTIVE"},
        "source": {"doc_id": "d1", "claim_id": "c1", "quote": "x" * 30},
        "confidence": 0.95,
    }
    ff = _ff_with_facts([fact])
    llm = MagicMock()
    llm.chat_completion_with_meta.side_effect = RuntimeError("down")
    res = FactualComposer(llm=llm).compose(ff)
    assert "21 J" in res.answer_text
