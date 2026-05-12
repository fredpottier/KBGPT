"""
Tests CH-41.1 — QuestionAnalyzer (mocks LLM, pas d'appel réseau).
"""
from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest

from knowbase.facts_first.question_analyzer import (
    AnalyzerResult,
    QuestionAnalyzer,
    RoutingDecision,
)


def _make_llm(content: str | dict, model: str = "test-model", provider: str = "mock"):
    """Construit un mock RuntimeLLMClient qui retourne le content fourni."""
    if isinstance(content, dict):
        content = json.dumps(content)
    llm = MagicMock()
    llm.chat_completion_with_meta.return_value = {
        "content": content,
        "logprobs": None,
        "model": model,
        "provider": provider,
    }
    return llm


def test_routing_thresholds():
    """Vérifie les bornes de routing (D-FF11)."""
    llm = _make_llm({
        "primary_type": "list", "primary_confidence": 0.85,
        "secondary_type": None, "secondary_confidence": None,
        "language": "fr", "rationale": "list test"
    })
    a = QuestionAnalyzer(llm=llm)
    res = a.analyze("Quels sont les 4 types d'autorisations ?")
    assert res.primary_type == "list"
    assert res.primary_confidence == 0.85
    assert res.routing == RoutingDecision.SINGLE
    assert res.language == "fr"

    llm2 = _make_llm({
        "primary_type": "factual", "primary_confidence": 0.6,
        "secondary_type": "list", "secondary_confidence": 0.5,
        "language": "en", "rationale": "ambig"
    })
    res2 = QuestionAnalyzer(llm=llm2).analyze("How many types of X?")
    assert res2.routing == RoutingDecision.COMBINED
    assert res2.secondary_type == "list"

    llm3 = _make_llm({
        "primary_type": "causal", "primary_confidence": 0.3,
        "secondary_type": None, "secondary_confidence": None,
        "language": "fr", "rationale": "ambig"
    })
    res3 = QuestionAnalyzer(llm=llm3).analyze("?")
    assert res3.routing == RoutingDecision.EAV_FALLBACK


def test_invalid_primary_type_falls_back():
    """Un primary_type inconnu → unanswerable + EAV_FALLBACK + parse_error renseigné."""
    llm = _make_llm({
        "primary_type": "narrative",  # pas dans les 7 types légaux
        "primary_confidence": 0.9, "language": "en", "rationale": "x"
    })
    res = QuestionAnalyzer(llm=llm).analyze("Tell me a story")
    assert res.primary_type == "unanswerable"
    assert res.routing == RoutingDecision.EAV_FALLBACK
    assert res.parse_error and "unknown_primary_type" in res.parse_error


def test_secondary_same_as_primary_dropped():
    """secondary_type == primary_type → ignoré (normalisation)."""
    llm = _make_llm({
        "primary_type": "list", "primary_confidence": 0.85,
        "secondary_type": "list", "secondary_confidence": 0.4,
        "language": "fr", "rationale": "x"
    })
    res = QuestionAnalyzer(llm=llm).analyze("Quels X")
    assert res.primary_type == "list"
    assert res.secondary_type is None
    assert res.secondary_confidence is None


def test_json_parse_error_returns_eav_fallback():
    """JSON malformé → fallback EAV avec parse_error renseigné."""
    llm = _make_llm("not a json {{{")
    res = QuestionAnalyzer(llm=llm).analyze("question")
    assert res.primary_type == "unanswerable"
    assert res.routing == RoutingDecision.EAV_FALLBACK
    assert res.parse_error and "json_parse" in res.parse_error


def test_empty_question_returns_eav_fallback():
    """Question vide → EAV_FALLBACK sans appel LLM."""
    llm = MagicMock()
    res = QuestionAnalyzer(llm=llm).analyze("   ")
    assert res.routing == RoutingDecision.EAV_FALLBACK
    assert res.primary_confidence == 0.0
    llm.chat_completion_with_meta.assert_not_called()


def test_llm_exception_returns_eav_fallback():
    """Exception LLM → EAV_FALLBACK + parse_error renseigné."""
    llm = MagicMock()
    llm.chat_completion_with_meta.side_effect = RuntimeError("api down")
    res = QuestionAnalyzer(llm=llm).analyze("Quels X ?")
    assert res.routing == RoutingDecision.EAV_FALLBACK
    assert "api down" in (res.parse_error or "")


def test_confidence_clamped_0_1():
    """Confidence > 1.0 ou < 0.0 sont clampées."""
    llm = _make_llm({
        "primary_type": "list", "primary_confidence": 1.5,  # OOR
        "secondary_type": None, "secondary_confidence": None,
        "language": "fr", "rationale": "x"
    })
    res = QuestionAnalyzer(llm=llm).analyze("Quels X ?")
    assert 0.0 <= res.primary_confidence <= 1.0


def test_to_dict_routing_serialized_as_string():
    """to_dict() doit sérialiser routing comme str enum value."""
    llm = _make_llm({
        "primary_type": "list", "primary_confidence": 0.85,
        "secondary_type": None, "secondary_confidence": None,
        "language": "fr", "rationale": "x"
    })
    res = QuestionAnalyzer(llm=llm).analyze("Quels X ?")
    d = res.to_dict()
    assert d["routing"] == "single"
    assert isinstance(d["routing"], str)
