"""Tests LoopSignatureTracker (CH-52.5.1 / S4.1)."""
from __future__ import annotations

import pytest

from knowbase.runtime_v5.agent.loop_signature import (
    LoopSignature,
    LoopSignatureTracker,
    _jaccard,
    _normalize_args,
    _tokenize,
)


# ─── Helpers ─────────────────────────────────────────────────────────────────


class TestHelpers:
    def test_normalize_args_dict_canonical(self):
        a = _normalize_args({"b": 1, "a": 2})
        b = _normalize_args({"a": 2, "b": 1})
        assert a == b  # ordre indépendant

    def test_normalize_args_str(self):
        assert _normalize_args("foo") == "foo"

    def test_normalize_args_none(self):
        assert _normalize_args(None) == ""

    def test_tokenize_basic(self):
        assert _tokenize("Hello World!") == {"hello", "world"}

    def test_tokenize_punct_stripped(self):
        assert _tokenize("3.2.1: setup, Sequence") == {"3", "2", "1", "setup", "sequence"}

    def test_tokenize_empty(self):
        assert _tokenize("") == set()
        assert _tokenize(None) == set()

    def test_jaccard_identical(self):
        assert _jaccard({"a", "b"}, {"a", "b"}) == 1.0

    def test_jaccard_disjoint(self):
        assert _jaccard({"a"}, {"b"}) == 0.0

    def test_jaccard_overlap(self):
        assert _jaccard({"a", "b", "c"}, {"b", "c", "d"}) == 2 / 4

    def test_jaccard_both_empty(self):
        assert _jaccard(set(), set()) == 1.0


# ─── LoopSignature ───────────────────────────────────────────────────────────


class TestLoopSignature:
    def test_signature_hash_stable(self):
        s1 = LoopSignature(tool="read", normalized_args='{"a":1}', evidence_gain=0.5,
                           novelty_score=0.7, iter_idx=0)
        s2 = LoopSignature(tool="read", normalized_args='{"a":1}', evidence_gain=0.9,
                           novelty_score=0.2, iter_idx=5)
        # Hash dépend uniquement tool+args, pas des métriques
        assert s1.signature_hash() == s2.signature_hash()

    def test_signature_hash_differs_with_args(self):
        s1 = LoopSignature(tool="read", normalized_args='{"a":1}', evidence_gain=0.5,
                           novelty_score=0.7, iter_idx=0)
        s2 = LoopSignature(tool="read", normalized_args='{"a":2}', evidence_gain=0.5,
                           novelty_score=0.7, iter_idx=0)
        assert s1.signature_hash() != s2.signature_hash()


# ─── LoopSignatureTracker — record + signatures ──────────────────────────────


class TestRecording:
    def test_record_single_iter(self):
        t = LoopSignatureTracker()
        sig = t.record("outline", {"doc_id": "X"}, "section1 text", 0, 0)
        assert sig.tool == "outline"
        assert sig.evidence_gain == 1.0  # first observation
        assert sig.novelty_score == 1.0  # rien dans history
        assert len(t.history) == 1

    def test_evidence_gain_zero_when_no_new_text(self):
        t = LoopSignatureTracker()
        sig = t.record("outline", {}, "", prior_evidence_chars=500, iter_idx=0)
        assert sig.evidence_gain == 0.0

    def test_evidence_gain_decreasing_with_prior(self):
        t = LoopSignatureTracker()
        s1 = t.record("read", {"id": "A"}, "x" * 1000, prior_evidence_chars=0, iter_idx=0)
        s2 = t.record("read", {"id": "B"}, "y" * 500, prior_evidence_chars=1000, iter_idx=1)
        assert s2.evidence_gain < s1.evidence_gain


# ─── Stop conditions ─────────────────────────────────────────────────────────


class TestStopOnDuplicateCalls:
    def test_no_stop_on_first_call(self):
        t = LoopSignatureTracker(duplicate_signatures_threshold=3)
        t.record("read", {"id": "A"}, "section A text", 0, 0)
        ok, _ = t.should_stop_for_duplicate_calls()
        assert ok is False

    def test_stop_after_threshold_duplicate(self):
        t = LoopSignatureTracker(duplicate_signatures_threshold=3)
        for i in range(3):
            t.record("read", {"id": "A"}, f"text iter {i}", i * 100, i)
        ok, reason = t.should_stop_for_duplicate_calls()
        assert ok is True
        assert "duplicate_signature" in reason
        assert "3x" in reason

    def test_no_stop_when_args_differ(self):
        t = LoopSignatureTracker(duplicate_signatures_threshold=3)
        for i in range(5):
            t.record("read", {"id": f"sec_{i}"}, f"text {i}", i * 100, i)
        ok, _ = t.should_stop_for_duplicate_calls()
        assert ok is False  # args différents = signatures différentes


class TestStopOnLowNovelty:
    def test_stop_when_repeated_same_content(self):
        """Si 3 iter consécutives retournent le même contenu → novelty très bas → stop."""
        t = LoopSignatureTracker(novelty_window=3, novelty_threshold=0.10)
        text = "the procedure follows the standard guideline"
        # 1st observation : novelty = 1.0 (rien à comparer)
        t.record("read", {"id": "A"}, text, 0, 0)
        # 2nd : on compare au précédent → similaire → novelty bas
        t.record("read", {"id": "B"}, text, 100, 1)
        t.record("read", {"id": "C"}, text, 200, 2)
        t.record("read", {"id": "D"}, text, 300, 3)
        ok, reason = t.should_stop_for_low_novelty()
        assert ok is True, f"expected stop, got reason={reason}, stats={t.stats()}"

    def test_no_stop_with_distinct_content(self):
        """Différents contenus à chaque iter → novelty élevé → pas stop."""
        t = LoopSignatureTracker(novelty_window=3, novelty_threshold=0.10)
        contents = [
            "alpha beta gamma",
            "delta epsilon zeta",
            "eta theta iota",
            "kappa lambda mu",
        ]
        for i, c in enumerate(contents):
            t.record("read", {"id": f"s{i}"}, c, i * 50, i)
        ok, _ = t.should_stop_for_low_novelty()
        assert ok is False

    def test_no_stop_below_window(self):
        t = LoopSignatureTracker(novelty_window=3)
        t.record("read", {"id": "A"}, "x", 0, 0)
        t.record("read", {"id": "B"}, "y", 50, 1)
        # window=3 not reached yet
        ok, _ = t.should_stop_for_low_novelty()
        assert ok is False


# ─── Combined should_stop ────────────────────────────────────────────────────


class TestShouldStop:
    def test_duplicate_takes_priority_over_novelty(self):
        """Si à la fois duplicate ET low novelty, on doit stop avec raison duplicate."""
        t = LoopSignatureTracker(
            duplicate_signatures_threshold=3, novelty_window=3, novelty_threshold=0.10
        )
        # 3 calls identiques
        for i in range(3):
            t.record("read", {"id": "A"}, "alpha beta gamma", i * 50, i)
        ok, reason = t.should_stop()
        assert ok is True
        assert "duplicate_signature" in reason

    def test_no_stop_when_healthy_loop(self):
        t = LoopSignatureTracker()
        contents = ["alpha beta", "gamma delta", "epsilon zeta", "eta theta"]
        for i, c in enumerate(contents):
            t.record("read", {"id": f"s{i}"}, c, i * 30, i)
        ok, _ = t.should_stop()
        assert ok is False


# ─── Anti-thrash A→B→A→B pattern ────────────────────────────────────────────


class TestAntiThrashPattern:
    """Cas pathologique POC : agent alterne entre 2 sections."""

    def test_a_b_a_b_pattern_caught_by_duplicate(self):
        t = LoopSignatureTracker(duplicate_signatures_threshold=3)
        # Pattern A→B→A→B→A
        for i, sid in enumerate(["A", "B", "A", "B", "A"]):
            t.record("read", {"id": sid}, f"content_of_{sid}", i * 50, i)
        # 'read({"id": "A"})' appelé 3 fois → duplicate triggers
        ok, _ = t.should_stop_for_duplicate_calls()
        assert ok is True


# ─── Stats ───────────────────────────────────────────────────────────────────


class TestStats:
    def test_stats_empty_tracker(self):
        s = LoopSignatureTracker().stats()
        assert s["n_iter"] == 0
        assert s["avg_novelty"] == 0.0

    def test_stats_basic(self):
        t = LoopSignatureTracker()
        t.record("outline", {"doc_id": "X"}, "alpha", 0, 0)
        t.record("read", {"id": "A"}, "beta gamma", 50, 1)
        s = t.stats()
        assert s["n_iter"] == 2
        assert s["n_unique_signatures"] == 2
        assert 0 < s["avg_novelty"] <= 1.0
        assert s["duplicate_max_count"] == 1
