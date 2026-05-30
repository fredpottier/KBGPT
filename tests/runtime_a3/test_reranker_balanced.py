"""Test rerank_balanced — garantit la représentation des 2 côtés d'une comparaison.

Le côté dominant (plus de claims, mieux scorés) ne doit PAS écraser l'autre.
Cf project_comparison_synthesis_audit.
"""
from __future__ import annotations

from knowbase.runtime_a3.reranker import ClaimReranker
from knowbase.runtime_a3.schemas import ClaimSummary


class _FakeCE:
    """Modèle CE factice : score élevé pour le côté 'private', faible sinon."""

    def predict(self, pairs, **_kwargs):
        return [1.0 if "private" in q_ct[1].lower() else 0.1 for q_ct in pairs]


def _mk(cid: str, subject: str) -> ClaimSummary:
    return ClaimSummary(claim_id=cid, subject_canonical=subject,
                        predicate="HAS_SCOPE", value="scope")


def _reranker() -> ClaimReranker:
    r = ClaimReranker(top_k=4)
    r._model = _FakeCE()  # bypass lazy load
    return r


def test_balanced_keeps_minority_side():
    # 8 claims côté Private (dominant), 1 côté Public (minoritaire)
    claims = [_mk(f"priv{i}", "Private Edition") for i in range(8)] + [_mk("pub1", "Public Edition")]
    groups = [0] * 8 + [1]
    kept, scores = _reranker().rerank_balanced(
        "différence de scope private vs public", claims, groups, top_k=4,
    )
    kept_subjects = {c.subject_canonical for c in kept}
    assert "Public Edition" in kept_subjects, "le côté minoritaire doit être représenté"
    assert "Private Edition" in kept_subjects


def test_balanced_single_group_falls_back():
    claims = [_mk(f"p{i}", "Private Edition") for i in range(5)]
    groups = [0] * 5
    kept, _ = _reranker().rerank_balanced("q", claims, groups, top_k=3)
    assert len(kept) == 3  # rerank global normal


def test_balanced_mismatched_groups_falls_back():
    claims = [_mk("a", "A"), _mk("b", "B")]
    kept, _ = _reranker().rerank_balanced("q", claims, [0], top_k=2)  # groups != claims
    assert len(kept) == 2


def test_balanced_empty():
    kept, scores = _reranker().rerank_balanced("q", [], [], top_k=4)
    assert kept == [] and scores == []
