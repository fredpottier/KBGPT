"""Tests unitaires PredicateResolver (A3.9-bis).

Stratégie : mocks complets (Neo4j + embedder injectés).
Aucun appel réel à l'infrastructure dans ces tests.
"""

from __future__ import annotations

from typing import List
from unittest.mock import MagicMock

import pytest

from knowbase.runtime_a3.predicate_resolver import (
    EXACT_CONFIDENCE,
    MIN_CONFIDENCE,
    PredicateResolver,
    _cosine_topk,
    resolve_predicate,
)
from knowbase.runtime_a3.schemas import PredicateResolverResult


# ============================================================================
# Helpers
# ============================================================================


def _make_neo4j(predicates: List[str]):
    mock = MagicMock()
    mock.execute_query.return_value = [
        {"predicate": p} for p in predicates
    ]
    return mock


def _make_embedder(mapping: dict) -> callable:
    """Embedder mock : mapping {text_lower → vector}. Sinon vecteur zéro."""
    def _embed(texts: List[str]) -> List[List[float]]:
        out = []
        for t in texts:
            key = t.lower().strip()
            out.append(mapping.get(key, [0.0] * 4))
        return out
    return _embed


def _make_resolver(predicates: List[str], embed_mapping: dict):
    return PredicateResolver(
        neo4j_client=_make_neo4j(predicates),
        embedder=_make_embedder(embed_mapping),
    )


# ============================================================================
# TestPassthrough
# ============================================================================


class TestPassthrough:
    def test_none_returns_passthrough(self):
        r = _make_resolver([], {})
        out = r.resolve(None, tenant_id="t")
        assert out.resolved is None
        assert out.method == "passthrough"

    def test_empty_string_returns_passthrough(self):
        r = _make_resolver([], {})
        out = r.resolve("", tenant_id="t")
        assert out.method == "passthrough"

    def test_whitespace_only_returns_passthrough(self):
        r = _make_resolver([], {})
        out = r.resolve("   \t\n  ", tenant_id="t")
        assert out.method == "passthrough"


# ============================================================================
# TestExactKG
# ============================================================================


class TestExactKG:
    def test_upper_snake_present_in_kg_returns_exact(self):
        r = _make_resolver(["PROCESSES", "USES"], {})
        out = r.resolve("PROCESSES", tenant_id="t")
        assert out.resolved == "PROCESSES"
        assert out.method == "exact_kg"
        assert out.confidence == EXACT_CONFIDENCE
        assert len(out.candidates) == 1
        assert out.candidates[0].source == "exact_kg"

    def test_upper_snake_with_underscores(self):
        r = _make_resolver(["HAS_VERSION", "INTEGRATED_IN"], {})
        out = r.resolve("HAS_VERSION", tenant_id="t")
        assert out.resolved == "HAS_VERSION"
        assert out.method == "exact_kg"

    def test_upper_snake_absent_from_kg_falls_through(self):
        # UPPER_SNAKE mais pas dans KG → tombe en embedding step (avec
        # mapping vide, donc score = 0 → low_confidence)
        r = _make_resolver(["USES"], {"unknown": [1, 0, 0, 0]})
        out = r.resolve("UNKNOWN", tenant_id="t")
        assert out.method != "exact_kg"


# ============================================================================
# TestEmbedding
# ============================================================================


class TestEmbedding:
    def test_high_similarity_resolves(self):
        # 'transaction' (vec) ≈ PROCESSES (vec)
        r = _make_resolver(
            ["PROCESSES", "USES"],
            {
                "transaction": [1.0, 0.0, 0.0, 0.0],
                "processes": [1.0, 0.0, 0.0, 0.0],  # cosine = 1.0
                "uses": [0.0, 1.0, 0.0, 0.0],       # cosine = 0.0 with transaction
            },
        )
        out = r.resolve("transaction", tenant_id="t")
        assert out.resolved == "PROCESSES"
        assert out.method == "embedding"
        assert out.confidence >= MIN_CONFIDENCE

    def test_low_similarity_abstains(self):
        # 'foo' n'a aucune similarité avec les predicates
        r = _make_resolver(
            ["PROCESSES", "USES"],
            {
                "foo": [1.0, 0.0, 0.0, 0.0],
                "processes": [0.0, 1.0, 0.0, 0.0],  # cos=0
                "uses": [0.0, 0.0, 1.0, 0.0],       # cos=0
            },
        )
        out = r.resolve("foo", tenant_id="t")
        assert out.resolved is None
        assert out.method == "low_confidence"
        assert len(out.candidates) >= 1  # candidats exposés malgré abstain

    def test_candidates_sorted_desc(self):
        r = _make_resolver(
            ["A_PRED", "B_PRED", "C_PRED"],
            {
                "query": [1.0, 0.0, 0.0, 0.0],
                "a pred": [1.0, 0.0, 0.0, 0.0],  # cos=1.0
                "b pred": [0.7, 0.7, 0.0, 0.0],  # cos=0.7
                "c pred": [0.3, 0.0, 0.9, 0.0],  # cos<0.7
            },
        )
        out = r.resolve("query", tenant_id="t")
        scores = [c.score for c in out.candidates]
        assert scores == sorted(scores, reverse=True)

    def test_low_confidence_returns_top_candidates_for_debug(self):
        r = _make_resolver(
            ["X_ONE", "Y_TWO"],
            {
                "weak": [1.0, 0.0, 0.0, 0.0],
                "x one": [0.4, 0.0, 0.0, 1.0],   # cos faible
                "y two": [0.3, 1.0, 0.0, 0.0],   # cos faible
            },
        )
        out = r.resolve("weak", tenant_id="t")
        assert out.method == "low_confidence"
        assert len(out.candidates) >= 1


# ============================================================================
# TestKGPredicatesLoading
# ============================================================================


class TestKGPredicatesLoading:
    def test_empty_kg_returns_abstain(self):
        r = _make_resolver([], {})
        out = r.resolve("anything", tenant_id="t")
        assert out.resolved is None
        assert out.method == "no_kg_predicates"

    def test_cache_avoids_second_neo4j_call(self):
        neo = MagicMock()
        neo.execute_query.return_value = [{"predicate": "USES"}]
        embedder = MagicMock(return_value=[[1.0, 0.0]])
        r = PredicateResolver(neo4j_client=neo, embedder=embedder)
        r.resolve("uses", tenant_id="t")
        r.resolve("uses", tenant_id="t")
        # execute_query devrait avoir été appelé une seule fois pour load
        # NB: pour 'uses' exact_kg, le hint est lowercase donc UPPER_SNAKE_RE
        # ne match pas → fallback embedding → load déclenché.
        # 2nd appel : cache hit → no neo4j call
        assert neo.execute_query.call_count == 1

    def test_invalidate_cache_forces_reload(self):
        neo = MagicMock()
        neo.execute_query.return_value = [{"predicate": "USES"}]
        embedder = MagicMock(return_value=[[1.0, 0.0]])
        r = PredicateResolver(neo4j_client=neo, embedder=embedder)
        r.resolve("anything", tenant_id="t")
        r.invalidate_cache("t")
        r.resolve("anything", tenant_id="t")
        assert neo.execute_query.call_count == 2

    def test_invalidate_cache_all_tenants(self):
        neo = MagicMock()
        neo.execute_query.return_value = [{"predicate": "USES"}]
        embedder = MagicMock(return_value=[[1.0, 0.0]])
        r = PredicateResolver(neo4j_client=neo, embedder=embedder)
        r.resolve("anything", tenant_id="t1")
        r.resolve("anything", tenant_id="t2")
        # 2 loads
        assert neo.execute_query.call_count == 2
        r.invalidate_cache()  # all
        r.resolve("anything", tenant_id="t1")
        r.resolve("anything", tenant_id="t2")
        assert neo.execute_query.call_count == 4


# ============================================================================
# TestErrorHandling
# ============================================================================


class TestErrorHandling:
    def test_neo4j_exception_returns_error(self):
        neo = MagicMock()
        neo.execute_query.side_effect = Exception("Neo4j down")
        embedder = MagicMock(return_value=[[1.0]])
        r = PredicateResolver(neo4j_client=neo, embedder=embedder)
        out = r.resolve("anything", tenant_id="t")
        assert out.resolved is None
        assert out.method == "error"

    def test_embedder_exception_returns_error(self):
        neo = _make_neo4j(["USES"])
        embedder = MagicMock()

        # 1er appel batch (load predicates) OK ; 2nd appel (encode user hint) fail
        calls = {"n": 0}

        def _embed(texts):
            calls["n"] += 1
            if calls["n"] == 1:
                return [[1.0, 0.0]]  # encode 1 predicate
            raise Exception("embedder down")

        embedder.side_effect = _embed
        r = PredicateResolver(neo4j_client=neo, embedder=embedder)
        out = r.resolve("transaction", tenant_id="t")
        assert out.resolved is None
        assert out.method == "error"


# ============================================================================
# TestCosineTopK (helper)
# ============================================================================


class TestCosineTopK:
    def test_basic_ranking(self):
        q = [1.0, 0.0]
        cs = [[1.0, 0.0], [0.0, 1.0], [0.7, 0.7]]
        labels = ["A", "B", "C"]
        out = _cosine_topk(q, cs, labels, k=3)
        assert out[0] == ("A", 1.0)
        assert out[1][0] == "C"
        assert out[2][0] == "B"

    def test_empty_inputs(self):
        assert _cosine_topk([], [], [], k=3) == []
        assert _cosine_topk([1.0, 0.0], [], [], k=3) == []

    def test_zero_norm_query_returns_empty(self):
        assert _cosine_topk([0.0, 0.0], [[1.0, 0.0]], ["A"], k=3) == []

    def test_zero_norm_candidate_skipped(self):
        out = _cosine_topk(
            [1.0, 0.0],
            [[1.0, 0.0], [0.0, 0.0]],
            ["A", "B"],
            k=3,
        )
        # B est zéro-norme, skip → seul A
        assert len(out) == 1
        assert out[0][0] == "A"

    def test_length_mismatch_raises(self):
        with pytest.raises(ValueError):
            _cosine_topk([1.0], [[1.0]], ["A", "B"], k=3)

    def test_topk_truncation(self):
        q = [1.0]
        cs = [[1.0], [0.9], [0.8], [0.7]]
        labels = ["A", "B", "C", "D"]
        out = _cosine_topk(q, cs, labels, k=2)
        assert len(out) == 2
        assert out[0][0] == "A"


# ============================================================================
# TestPredicateCanonicalization
# ============================================================================


class TestPredicateCanonicalization:
    def test_resolved_returns_kg_form_not_user_form(self):
        # User input lowercase → resolved = KG UPPER form
        r = _make_resolver(
            ["INTEGRATED_IN"],
            {
                "integration": [1.0, 0.0],
                "integrated in": [1.0, 0.0],  # cos=1.0
            },
        )
        out = r.resolve("integration", tenant_id="t")
        # Resolved doit être la forme KG, pas la forme readable
        assert out.resolved == "INTEGRATED_IN"


# ============================================================================
# TestTopLevelAPI
# ============================================================================


class TestTopLevelAPI:
    def test_resolve_predicate_uses_injected_resolver(self):
        injected = _make_resolver(["USES"], {})
        out = resolve_predicate("USES", tenant_id="t", resolver=injected)
        assert isinstance(out, PredicateResolverResult)
        assert out.resolved == "USES"


# ============================================================================
# TestConstants
# ============================================================================


class TestConstants:
    def test_thresholds_sensible(self):
        assert 0.0 < MIN_CONFIDENCE < 1.0
        assert EXACT_CONFIDENCE == 1.0
        # MIN_CONFIDENCE doit être suffisamment haut pour rejeter le bruit
        # observé sur 19 predicates KG (~0.83)
        assert MIN_CONFIDENCE >= 0.8
