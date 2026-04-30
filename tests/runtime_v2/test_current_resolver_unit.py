"""Tests unitaires CurrentResolver — heuristiques runtime + politique graduée."""
from __future__ import annotations

from datetime import date

import pytest

from knowbase.current.current_resolver import CurrentResolver, _digit_run_tokens, _parse_iso_date
from knowbase.current.models import (
    ConfidenceWeights,
    CurrentCandidate,
    CurrentResolverDecision,
)


def test_digit_run_tokens_extraction():
    assert _digit_run_tokens("CS-25 Amendment 28") == [25, 28]
    assert _digit_run_tokens("v3.2.1") == [3, 2, 1]
    assert _digit_run_tokens("1809") == [1809]
    assert _digit_run_tokens("2021/821") == [2021, 821]
    assert _digit_run_tokens("no version here") == []
    assert _digit_run_tokens("") == []
    assert _digit_run_tokens(None) == []


def test_parse_iso_date_formats():
    assert _parse_iso_date("2024-01-15") == date(2024, 1, 15)
    assert _parse_iso_date("2024-01") == date(2024, 1, 1)
    assert _parse_iso_date("2024") == date(2024, 1, 1)
    assert _parse_iso_date("invalid") is None
    assert _parse_iso_date(None) is None
    assert _parse_iso_date("") is None


def test_phase3_single_candidate_auto_pick(monkeypatch):
    """1 seul candidat → AUTO_PICK_SINGLE_CANDIDATE."""
    resolver = CurrentResolver.__new__(CurrentResolver)
    resolver.weights = ConfidenceWeights()
    candidate = CurrentCandidate(doc_id="d1", confidence=1.0)
    result = resolver._phase3_policy([candidate])
    assert result.decision == CurrentResolverDecision.AUTO_PICK_SINGLE_CANDIDATE
    assert result.top_candidate.doc_id == "d1"


def test_phase3_high_confidence_auto_pick():
    resolver = CurrentResolver.__new__(CurrentResolver)
    resolver.weights = ConfidenceWeights()
    cands = [
        CurrentCandidate(doc_id="d_top", confidence=0.92),
        CurrentCandidate(doc_id="d_alt", confidence=0.50),
    ]
    result = resolver._phase3_policy(cands)
    assert result.decision == CurrentResolverDecision.AUTO_PICK_HIGH_CONFIDENCE
    assert result.top_candidate.doc_id == "d_top"
    assert len(result.alternatives) == 1


def test_phase3_suggest_with_alternatives():
    resolver = CurrentResolver.__new__(CurrentResolver)
    resolver.weights = ConfidenceWeights()
    cands = [
        CurrentCandidate(doc_id="d_top", confidence=0.70),
        CurrentCandidate(doc_id="d_alt", confidence=0.65),
    ]
    result = resolver._phase3_policy(cands)
    assert result.decision == CurrentResolverDecision.SUGGEST_WITH_ALTERNATIVES
    assert result.top_candidate.doc_id == "d_top"
    assert len(result.alternatives) == 1


def test_phase3_escalate_ambiguous_low_confidence():
    resolver = CurrentResolver.__new__(CurrentResolver)
    resolver.weights = ConfidenceWeights()
    cands = [
        CurrentCandidate(doc_id="d_top", confidence=0.40),
        CurrentCandidate(doc_id="d_alt", confidence=0.38),
    ]
    result = resolver._phase3_policy(cands)
    assert result.decision == CurrentResolverDecision.ESCALATE_AMBIGUOUS


def test_phase3_not_found_empty():
    resolver = CurrentResolver.__new__(CurrentResolver)
    resolver.weights = ConfidenceWeights()
    result = resolver._phase3_policy([])
    assert result.decision == CurrentResolverDecision.NOT_FOUND


def test_phase2_recency_score_normalized():
    """Phase 2 ranking : recency normalisée entre 0 et 1."""
    resolver = CurrentResolver.__new__(CurrentResolver)
    resolver.weights = ConfidenceWeights()
    candidates = [
        {"doc_id": "old", "publication_date": "2020-01-01", "primary_subject": "X", "centrality_count": 5, "trust_score": 0.5},
        {"doc_id": "new", "publication_date": "2024-12-31", "primary_subject": "X v2", "centrality_count": 5, "trust_score": 0.5},
    ]
    ranked = resolver._phase2_rank(candidates)
    # new doit avoir recency = 1.0, old = 0.0
    new_cand = next(c for c in ranked if c.doc_id == "new")
    old_cand = next(c for c in ranked if c.doc_id == "old")
    assert new_cand.score_recency == 1.0
    assert old_cand.score_recency == 0.0


def test_confidence_weights_defaults():
    """Calibration P2.3 — recency renforcée."""
    w = ConfidenceWeights()
    assert w.recency == 0.60  # P2.3
    assert w.kg_centrality == 0.05
    assert w.auto_pick_threshold == 0.85
    assert w.suggest_threshold == 0.55
