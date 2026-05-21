"""Tests unitaires SubjectResolver (A3.9).

Couvre les 5 étapes du pipeline EKX-aligned :
    1. Normalisation
    2. Exact match :Entity.normalized_name
    3. FTS sur :Entity.name (index 'entity_name_search')
    4. Embedding fallback (Qdrant → chunk → :ABOUT → :Entity)
    5. Re-ranking grapho-sensitif via :ABOUT

Stratégie : mocks complets (Neo4j + Qdrant + embedder injectés via constructor).
Aucun appel réel à l'infrastructure dans ces tests.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional
from unittest.mock import MagicMock

import pytest

from knowbase.runtime_a3.schemas import (
    ResolverCandidate,
    ResolverResult,
)
from knowbase.runtime_a3.subject_resolver import (
    EXACT_CONFIDENCE,
    FTS_SCORE_THRESHOLD,
    MIN_CONFIDENCE,
    NO_CLAIM_PENALTY,
    PREDICATE_BOOST,
    SubjectResolver,
    resolve_subject,
)


# ============================================================================
# Helpers
# ============================================================================


def _make_neo4j_mock(query_results: Optional[List[Any]] = None):
    """Construit un Neo4jClient mock.

    `query_results` : liste ordonnée de résultats pour chaque appel
    `execute_query(...)`. Si callable, on l'appelle avec les kwargs.
    Si liste, on les retourne dans l'ordre.
    """
    mock = MagicMock()
    if query_results is None:
        mock.execute_query.return_value = []
        return mock

    # Compteur d'appels
    state = {"i": 0}

    def _exec(*args, **kwargs):
        i = state["i"]
        state["i"] += 1
        if i >= len(query_results):
            return []
        result = query_results[i]
        if callable(result):
            return result(*args, **kwargs)
        return result

    mock.execute_query.side_effect = _exec
    return mock


def _make_resolver(neo4j_mock=None, qdrant_search=None, embedder=None) -> SubjectResolver:
    return SubjectResolver(
        neo4j_client=neo4j_mock,
        qdrant_search=qdrant_search,
        embedder=embedder,
    )


# ============================================================================
# TestEdgeCases
# ============================================================================


class TestEdgeCases:
    def test_empty_input_returns_abstain(self):
        r = _make_resolver(neo4j_mock=_make_neo4j_mock())
        result = r.resolve("", tenant_id="default")
        assert result.resolved is None
        assert result.method == "empty_input"
        assert result.abstain_reason == "empty user_subject"
        assert result.confidence == 0.0
        assert result.duration_s >= 0.0

    def test_whitespace_only_input_returns_abstain(self):
        r = _make_resolver(neo4j_mock=_make_neo4j_mock())
        result = r.resolve("   \t\n  ", tenant_id="default")
        assert result.resolved is None
        assert result.method == "empty_input"

    def test_no_candidates_returns_no_match(self):
        # Aucun match exact, FTS vide, embedding vide
        neo = _make_neo4j_mock([
            [],  # exact
            [],  # FTS
        ])
        # Pas de qdrant_search → embedding step skipped
        r = _make_resolver(
            neo4j_mock=neo,
            qdrant_search=lambda **kw: [],
            embedder=lambda txt: [0.0] * 384,
        )
        result = r.resolve("nonexistent thing", tenant_id="default")
        assert result.resolved is None
        assert result.method in ("no_candidates", "low_confidence")


# ============================================================================
# TestExactMatch (Step 2)
# ============================================================================


class TestExactMatch:
    def test_exact_match_returns_resolved(self):
        # Step 2 : exact_match retourne 1 row → enrich retourne sc + n
        neo = _make_neo4j_mock([
            [{"name": "SAP Solution Manager", "eid": "ent_solman", "mc": 12}],  # exact
            [{"sc": "SAP Solution Manager", "n": 12}],  # enrich
        ])
        r = _make_resolver(neo4j_mock=neo)
        result = r.resolve("Solution Manager", tenant_id="default")
        assert result.resolved == "SAP Solution Manager"
        assert result.confidence == EXACT_CONFIDENCE
        assert result.method == "exact_normalized"
        assert len(result.candidates) == 1
        assert result.candidates[0].source == "exact_normalized"
        assert result.candidates[0].n_supporting_claims == 12

    def test_exact_match_predicate_hint_passed(self):
        captured: Dict[str, Any] = {}

        def _exec(*args, **kwargs):
            captured["last_kwargs"] = kwargs
            # Premier appel = exact match
            if "norm" in kwargs:
                return [{"name": "Entity X", "eid": "ent_x", "mc": 1}]
            # Second = enrich (avec pred)
            return [{"sc": "Entity X", "n": 5}]

        neo = MagicMock()
        neo.execute_query.side_effect = _exec
        r = _make_resolver(neo4j_mock=neo)
        result = r.resolve("Entity X", tenant_id="default", predicate_hint="HAS_VERSION")
        assert result.resolved == "Entity X"
        # predicate doit avoir été inclus dans le second appel
        assert captured["last_kwargs"].get("pred") == "HAS_VERSION"

    def test_exact_match_but_enrich_empty_falls_through(self):
        # exact OK mais aucun claim → on ne return pas, on tombe au FTS
        neo = _make_neo4j_mock([
            [{"name": "Lone Entity", "eid": "ent_lone", "mc": 0}],  # exact
            [],  # enrich (no claim)
            [],  # FTS
        ])
        r = _make_resolver(
            neo4j_mock=neo,
            qdrant_search=lambda **kw: [],
            embedder=lambda t: [0.0] * 384,
        )
        result = r.resolve("Lone Entity", tenant_id="default")
        # Sans claim et sans FTS hit, on retourne no_candidates ou low_confidence
        assert result.resolved is None

    def test_exact_match_query_exception_returns_none(self):
        neo = MagicMock()
        neo.execute_query.side_effect = Exception("Neo4j down")
        r = _make_resolver(
            neo4j_mock=neo,
            qdrant_search=lambda **kw: [],
            embedder=lambda t: [0.0] * 384,
        )
        result = r.resolve("anything", tenant_id="default")
        # Erreur → exact_match retourne None → poursuit FTS (qui re-échoue) → no_candidates
        assert result.resolved is None


# ============================================================================
# TestFTS (Step 3)
# ============================================================================


class TestFTS:
    def test_fts_high_score_skips_embedding(self):
        # FTS retourne un hit fort → embedding bypassé
        neo = _make_neo4j_mock([
            [],  # exact (miss)
            # FTS : raw_score > FTS_SCORE_THRESHOLD
            [{"eid": "ent_solman", "name": "SAP Solution Manager", "raw_score": 5.5}],
            # enrich pour le rerank
            [{"sc": "SAP Solution Manager", "n": 8}],
        ])
        r = _make_resolver(
            neo4j_mock=neo,
            qdrant_search=lambda **kw: [],  # ne devrait pas être appelé
            embedder=lambda t: [0.0] * 384,  # idem
        )
        result = r.resolve("Solution Mngr", tenant_id="default")
        assert result.resolved == "SAP Solution Manager"
        # method peut être "fts" ou "fts+rerank"
        assert result.method.startswith("fts")
        assert result.candidates[0].source == "fts"

    def test_fts_low_score_triggers_embedding(self):
        qdrant_called = {"n": 0}

        def _qd(**kw):
            qdrant_called["n"] += 1
            return []  # pas de hit non plus

        neo = _make_neo4j_mock([
            [],  # exact
            # FTS : raw_score < threshold
            [{"eid": "ent_weak", "name": "Weak Match", "raw_score": 0.5}],
            # Pas d'enrich car embedding va aussi retourner [] → rerank fait des appels
            [],  # enrich pour Weak Match
        ])
        r = _make_resolver(
            neo4j_mock=neo,
            qdrant_search=_qd,
            embedder=lambda t: [0.0] * 384,
        )
        r.resolve("vague query", tenant_id="default")
        # Embedding step doit avoir été appelé (FTS top brut < threshold)
        assert qdrant_called["n"] >= 1

    def test_fts_query_exception_returns_empty(self):
        neo = MagicMock()
        calls = {"n": 0}

        def _exec(*args, **kwargs):
            calls["n"] += 1
            if calls["n"] == 1:
                return []  # exact miss
            raise Exception("FTS index missing")

        neo.execute_query.side_effect = _exec
        r = _make_resolver(
            neo4j_mock=neo,
            qdrant_search=lambda **kw: [],
            embedder=lambda t: [0.0] * 384,
        )
        result = r.resolve("x", tenant_id="default")
        # Gracieux : pas d'exception, abstention
        assert result.resolved is None

    def test_fts_score_normalization(self):
        # 2 résultats : raw_score 4.0 et 2.0 → normalisé 1.0 et 0.5
        neo = _make_neo4j_mock([
            [],  # exact
            [
                {"eid": "e1", "name": "Top Hit", "raw_score": 4.0},
                {"eid": "e2", "name": "Second", "raw_score": 2.0},
            ],
            # enrich top
            [{"sc": "Top Hit", "n": 5}],
            # enrich second
            [{"sc": "Second", "n": 3}],
        ])
        r = _make_resolver(
            neo4j_mock=neo,
            qdrant_search=lambda **kw: [],
            embedder=lambda t: [0.0] * 384,
        )
        result = r.resolve("Hit", tenant_id="default")
        # Top doit avoir score 1.0 (boost predicate s'il s'applique pas)
        assert result.resolved == "Top Hit"
        assert len(result.candidates) >= 1


# ============================================================================
# TestEmbedding (Step 4)
# ============================================================================


class TestEmbedding:
    def test_embedding_finds_entity_via_chunks(self):
        # FTS miss faible → embedding kicks in → trouve Entity via :ABOUT
        neo = _make_neo4j_mock([
            [],  # exact
            [],  # FTS empty
            # embedding-to-entity bridge
            [{"eid": "ent_via_emb", "name": "Found via Embedding", "n_claims": 3}],
            # enrich pour rerank
            [{"sc": "Found via Embedding", "n": 3}],
        ])
        # Qdrant retourne 1 chunk
        qd_results = [{"id": "chunk_xyz", "score": 0.85, "payload": {"section_id": "chunk_xyz"}}]
        r = _make_resolver(
            neo4j_mock=neo,
            qdrant_search=lambda **kw: qd_results,
            embedder=lambda t: [0.1] * 384,
        )
        result = r.resolve("fuzzy concept", tenant_id="default")
        assert result.resolved == "Found via Embedding"

    def test_embedding_empty_hits_yields_no_candidate(self):
        neo = _make_neo4j_mock([
            [],  # exact
            [],  # FTS
            # embedding-to-entity bridge not called car qdrant vide
        ])
        r = _make_resolver(
            neo4j_mock=neo,
            qdrant_search=lambda **kw: [],
            embedder=lambda t: [0.1] * 384,
        )
        result = r.resolve("nope", tenant_id="default")
        assert result.resolved is None

    def test_embedding_qdrant_exception_handled(self):
        def _qd(**kw):
            raise Exception("Qdrant timeout")

        neo = _make_neo4j_mock([
            [],  # exact
            [],  # FTS
        ])
        r = _make_resolver(
            neo4j_mock=neo,
            qdrant_search=_qd,
            embedder=lambda t: [0.1] * 384,
        )
        result = r.resolve("anything", tenant_id="default")
        # Erreur silenced → no_candidates
        assert result.resolved is None


# ============================================================================
# TestMergeCandidates
# ============================================================================


class TestMergeCandidates:
    def test_merge_dedupes_by_entity_id_keep_max(self):
        c1 = ResolverCandidate(
            entity_id="e1", entity_name="X", score=0.6, source="fts",
        )
        c2 = ResolverCandidate(
            entity_id="e1", entity_name="X", score=0.4, source="embedding",
        )
        merged = SubjectResolver._merge_candidates([c1], [c2])
        assert len(merged) == 1
        assert merged[0].score == 0.6
        assert merged[0].source == "fts"

    def test_merge_keeps_distinct_entities(self):
        c1 = ResolverCandidate(entity_id="e1", entity_name="A", score=0.7, source="fts")
        c2 = ResolverCandidate(entity_id="e2", entity_name="B", score=0.5, source="embedding")
        merged = SubjectResolver._merge_candidates([c1], [c2])
        assert len(merged) == 2
        # Tri DESC
        assert merged[0].score >= merged[1].score

    def test_merge_empty_lists(self):
        assert SubjectResolver._merge_candidates([], []) == []


# ============================================================================
# TestRerankWithPredicate
# ============================================================================


class TestRerankWithPredicate:
    def test_rerank_predicate_match_boosts_score(self):
        # enrich retourne predicate_match=True → boost ×PREDICATE_BOOST
        neo = _make_neo4j_mock([
            # enrich
            [{"sc": "Subject Canonical", "n": 4}],
        ])
        r = _make_resolver(neo4j_mock=neo)
        cand = ResolverCandidate(
            entity_id="e1", entity_name="X", score=0.7, source="fts",
        )
        ranked = r._rerank_with_predicate([cand], tenant_id="t", predicate_hint="HAS_VERSION")
        assert len(ranked) == 1
        # 0.7 * 1.2 = 0.84
        assert ranked[0].score == pytest.approx(0.84, abs=0.01)
        assert ranked[0].predicate_match is True

    def test_rerank_no_claim_penalty(self):
        # enrich retourne None (pas de claim trouvé même sans pred filter)
        neo = _make_neo4j_mock([
            [],  # enrich (with pred) → empty
            [],  # enrich retry (no pred) → empty
        ])
        r = _make_resolver(neo4j_mock=neo)
        cand = ResolverCandidate(
            entity_id="e_orphan", entity_name="Orphan", score=0.8, source="fts",
        )
        ranked = r._rerank_with_predicate([cand], tenant_id="t", predicate_hint="HAS_VERSION")
        # 0.8 * 0.3 = 0.24
        assert ranked[0].score == pytest.approx(0.24, abs=0.01)
        assert ranked[0].predicate_match is False

    def test_rerank_predicate_retry_without_filter(self):
        # enrich avec pred = empty → retry sans pred = trouve
        neo = _make_neo4j_mock([
            [],  # enrich with pred
            [{"sc": "Sub Cano", "n": 3}],  # enrich no pred
        ])
        r = _make_resolver(neo4j_mock=neo)
        cand = ResolverCandidate(
            entity_id="e1", entity_name="X", score=0.7, source="fts",
        )
        ranked = r._rerank_with_predicate([cand], tenant_id="t", predicate_hint="MISSING_PRED")
        assert ranked[0].subject_canonical == "Sub Cano"
        assert ranked[0].predicate_match is False  # found but not matching pred

    def test_rerank_candidate_without_entity_id_passes_through(self):
        # Sans entity_id, rerank ne tente pas d'enrichir → garde tel quel
        r = _make_resolver(neo4j_mock=_make_neo4j_mock())
        cand = ResolverCandidate(
            entity_id=None, entity_name="NoId", score=0.5, source="fts",
        )
        ranked = r._rerank_with_predicate([cand], tenant_id="t", predicate_hint=None)
        assert len(ranked) == 1
        assert ranked[0].score == 0.5

    def test_rerank_empty_list(self):
        r = _make_resolver(neo4j_mock=_make_neo4j_mock())
        assert r._rerank_with_predicate([], tenant_id="t", predicate_hint=None) == []

    def test_rerank_sorts_by_score_desc(self):
        # 2 candidats : c1 score 0.6, c2 score 0.4
        # enrich c1 : predicate match (boost) → 0.72
        # enrich c2 : pas de claim → penalty (0.4 * 0.3 = 0.12)
        neo = _make_neo4j_mock([
            [{"sc": "C1", "n": 5}],  # enrich c1
            [],  # enrich c2 with pred
            [],  # enrich c2 retry no pred
        ])
        r = _make_resolver(neo4j_mock=neo)
        c1 = ResolverCandidate(entity_id="e1", entity_name="A", score=0.6, source="fts")
        c2 = ResolverCandidate(entity_id="e2", entity_name="B", score=0.4, source="fts")
        ranked = r._rerank_with_predicate([c1, c2], tenant_id="t", predicate_hint="P")
        assert ranked[0].entity_id == "e1"
        assert ranked[1].entity_id == "e2"


# ============================================================================
# TestEnrich
# ============================================================================


class TestEnrich:
    def test_enrich_returns_subject_canonical_and_n_claims(self):
        neo = _make_neo4j_mock([
            [{"sc": "Resolved Subject", "n": 7}],
        ])
        r = _make_resolver(neo4j_mock=neo)
        cand = ResolverCandidate(
            entity_id="e1", entity_name="Entity", score=0.7, source="fts",
        )
        enriched = r._enrich_with_subject_canonical(cand, "t", None)
        assert enriched is not None
        assert enriched.subject_canonical == "Resolved Subject"
        assert enriched.n_supporting_claims == 7

    def test_enrich_with_predicate_filter_marks_match_true(self):
        neo = _make_neo4j_mock([
            [{"sc": "X", "n": 4}],
        ])
        r = _make_resolver(neo4j_mock=neo)
        cand = ResolverCandidate(entity_id="e1", entity_name="E", score=0.7, source="fts")
        enriched = r._enrich_with_subject_canonical(cand, "t", "P_VERSION")
        assert enriched.predicate_match is True

    def test_enrich_no_claim_with_predicate_retries_without(self):
        # 1er appel (with pred) → vide, 2e (no pred) → trouve
        neo = _make_neo4j_mock([
            [],  # avec pred
            [{"sc": "Fallback Sub", "n": 2}],  # sans pred
        ])
        r = _make_resolver(neo4j_mock=neo)
        cand = ResolverCandidate(entity_id="e1", entity_name="E", score=0.7, source="fts")
        enriched = r._enrich_with_subject_canonical(cand, "t", "MISSING")
        assert enriched is not None
        assert enriched.subject_canonical == "Fallback Sub"
        # predicate_match=False car retry réussi mais predicate ne matche pas
        assert enriched.predicate_match is False

    def test_enrich_completely_empty_returns_none(self):
        neo = _make_neo4j_mock([
            [],  # avec pred
            [],  # sans pred
        ])
        r = _make_resolver(neo4j_mock=neo)
        cand = ResolverCandidate(entity_id="e_orph", entity_name="Orph", score=0.5, source="fts")
        enriched = r._enrich_with_subject_canonical(cand, "t", "P")
        assert enriched is None

    def test_enrich_query_exception_returns_none(self):
        neo = MagicMock()
        neo.execute_query.side_effect = Exception("DB error")
        r = _make_resolver(neo4j_mock=neo)
        cand = ResolverCandidate(entity_id="e1", entity_name="E", score=0.5, source="fts")
        enriched = r._enrich_with_subject_canonical(cand, "t", None)
        assert enriched is None


# ============================================================================
# TestResolveEndToEnd (scénarios complets)
# ============================================================================


class TestResolveEndToEnd:
    def test_resolve_low_confidence_returns_abstain_reason(self):
        # FTS retourne 1 hit faible (score normalisé faible), pas de claim → penalty
        neo = _make_neo4j_mock([
            [],  # exact
            # FTS : raw_score juste sous threshold → embedding triggered
            [{"eid": "e1", "name": "Faint", "raw_score": 1.0}],
            # embedding empty
            # rerank enrich c1 : empty x2 → score *0.3 → 1.0*0.3=0.3 < 0.5
            [],  # enrich with pred (None → never called this path)
        ])
        r = _make_resolver(
            neo4j_mock=neo,
            qdrant_search=lambda **kw: [],
            embedder=lambda t: [0.0] * 384,
        )
        result = r.resolve("Faint hit", tenant_id="default")
        # Score final 0.3 < 0.5 → low_confidence
        assert result.resolved is None
        assert result.method == "low_confidence"
        assert "0.30" in result.abstain_reason or "OR" in result.abstain_reason
        # candidats exposés pour debug
        assert len(result.candidates) >= 1

    def test_resolve_method_propagated_with_rerank(self):
        # exact miss, FTS top fort + predicate match → method "fts+rerank"
        neo = _make_neo4j_mock([
            [],  # exact
            [{"eid": "e1", "name": "Match", "raw_score": 5.0}],
            [{"sc": "Match Canonical", "n": 6}],  # enrich (predicate matched)
        ])
        r = _make_resolver(
            neo4j_mock=neo,
            qdrant_search=lambda **kw: [],
            embedder=lambda t: [0.0] * 384,
        )
        result = r.resolve("match", tenant_id="default", predicate_hint="P")
        assert result.method == "fts+rerank"

    def test_resolve_duration_recorded(self):
        neo = _make_neo4j_mock([[]])
        r = _make_resolver(
            neo4j_mock=neo,
            qdrant_search=lambda **kw: [],
            embedder=lambda t: [0.0] * 384,
        )
        result = r.resolve("anything", tenant_id="default")
        assert result.duration_s >= 0.0
        assert result.duration_s < 5.0  # mock = très rapide

    def test_resolve_tenant_id_propagated(self):
        captured: Dict[str, Any] = {}

        def _exec(*args, **kwargs):
            captured.setdefault("tids", []).append(kwargs.get("tid"))
            return []

        neo = MagicMock()
        neo.execute_query.side_effect = _exec
        r = _make_resolver(
            neo4j_mock=neo,
            qdrant_search=lambda **kw: [],
            embedder=lambda t: [0.0] * 384,
        )
        r.resolve("x", tenant_id="custom_tenant")
        # tid devrait être passé sur exact + FTS au minimum
        assert "custom_tenant" in captured.get("tids", [])

    def test_resolve_schema_version_set(self):
        neo = _make_neo4j_mock([[]])
        r = _make_resolver(
            neo4j_mock=neo,
            qdrant_search=lambda **kw: [],
            embedder=lambda t: [0.0] * 384,
        )
        result = r.resolve("any", tenant_id="t")
        assert result.schema_version == "a3.0"


# ============================================================================
# TestTopLevelAPI
# ============================================================================


class TestTopLevelAPI:
    def test_resolve_subject_uses_default_resolver(self):
        # Inject un resolver mockable
        injected = _make_resolver(neo4j_mock=_make_neo4j_mock([
            [{"name": "X", "eid": "e1", "mc": 1}],
            [{"sc": "X Canonical", "n": 1}],
        ]))
        result = resolve_subject("X", tenant_id="t", resolver=injected)
        assert isinstance(result, ResolverResult)
        assert result.resolved == "X Canonical"


# ============================================================================
# TestConstants
# ============================================================================


class TestConstants:
    def test_constants_are_sensible(self):
        assert 0.0 < MIN_CONFIDENCE <= 1.0
        assert EXACT_CONFIDENCE == 1.0
        assert FTS_SCORE_THRESHOLD > 0
        assert 0.0 < NO_CLAIM_PENALTY < 1.0
        assert PREDICATE_BOOST > 1.0
