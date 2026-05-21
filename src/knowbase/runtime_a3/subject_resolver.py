"""Subject Resolver runtime — résout user_input → subject_canonical du KG.

Cf doc/ongoing/POST_A38_FINDINGS_2026-05-21.md (cause racine A3.8) et EKX Q1.

Pipeline 5 étapes EKX-aligned (cf échange EKX 21/05/2026) :
    1. Normalisation via normalize_canonical_key (lowercase, strip ponctuation,
       collapse spaces, unicode NFKC).
    2. Exact match sur :Entity.normalized_name (=normalized).
    3. Full-text search sur :Entity.name (index Neo4j 'entity_name_search').
    4. Embedding fallback via Qdrant (collection knowbase_chunks_v2) si étapes
       2-3 ne retournent rien de fort.
    5. Re-ranking grapho-sensitif : pour chaque candidat top-K, suivre
       :Entity-[:ABOUT]-:Claim et vérifier predicate cohérent. Boost candidats
       avec predicate matchant.

Output : `ResolverResult` avec `resolved` (subject_canonical à utiliser dans
Cypher kg_claims) + `confidence` + candidats alternatifs pour transparence.

Si confidence < MIN_CONFIDENCE, retourne `resolved=None` (abstention).

Charte stricte : domain-agnostic. Aucun token SAP/médical/légal hardcodé.
Heuristiques universelles (normalisation lexicale + FTS + embeddings + graphe).

Toggle env var : `V6_SUBJECT_RESOLVER_ENABLED` (default "1"). Si "0", l'orchestrator
peut bypasser le resolver pour rollback safe.
"""

from __future__ import annotations

import logging
import time
from typing import Any, Callable, Dict, List, Optional

from knowbase.runtime_a3.schemas import (
    ResolverCandidate,
    ResolverResult,
    SubjectResolverError,
)
from knowbase.utils.normalize import normalize_canonical_key

logger = logging.getLogger("knowbase.runtime_a3.subject_resolver")


# Constants
MIN_CONFIDENCE = 0.5
EXACT_CONFIDENCE = 1.0
FTS_SCORE_THRESHOLD = 2.0  # score brut Neo4j FTS — en dessous, fallback embedding
TOP_K_CANDIDATES = 10
TOP_K_RETURNED = 5  # nombre de candidats exposés dans ResolverResult.candidates
DEFAULT_QDRANT_COLLECTION = "knowbase_chunks_v2"

# Pénalité pour candidats sans claim associé (pas de :ABOUT trouvé)
NO_CLAIM_PENALTY = 0.3
# Boost pour candidats dont le predicate matche
PREDICATE_BOOST = 1.2


class SubjectResolver:
    """Résout un user_input (subject_canonical du Parse LLM) vers le subject_canonical
    exact du KG (utilisable directement dans Cypher kg_claims).

    Injection de dépendances pour testabilité :
        - `neo4j_client` : objet exposant `.execute_query(query, **params) -> List[Dict]`
        - `qdrant_search` : callable signature `(collection, query_vector, tenant_id, limit, score_threshold)`
        - `embedder` : callable signature `(query_text) -> List[float]`
    """

    def __init__(
        self,
        neo4j_client: Any = None,
        qdrant_search: Optional[Callable] = None,
        embedder: Optional[Callable] = None,
        qdrant_collection: str = DEFAULT_QDRANT_COLLECTION,
        min_confidence: float = MIN_CONFIDENCE,
    ):
        self._neo4j = neo4j_client
        self._qdrant_search = qdrant_search
        self._embedder = embedder
        self._qdrant_collection = qdrant_collection
        self._min_confidence = min_confidence

    # ------------------------------------------------------------------
    # Lazy default clients (only when not injected)
    # ------------------------------------------------------------------

    def _get_neo4j(self):
        if self._neo4j is None:
            from knowbase.common.clients.neo4j_client import get_neo4j_client
            self._neo4j = get_neo4j_client()
        return self._neo4j

    def _get_qdrant_search(self):
        if self._qdrant_search is None:
            from knowbase.common.clients.qdrant_client import search_with_tenant_filter
            self._qdrant_search = search_with_tenant_filter
        return self._qdrant_search

    def _get_embedder(self):
        if self._embedder is None:
            from knowbase.common.clients.embeddings import EmbeddingModelManager
            mgr = EmbeddingModelManager()
            self._embedder = lambda text: mgr.encode([text])[0].tolist()
        return self._embedder

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def resolve(
        self,
        user_subject: str,
        tenant_id: str = "default",
        predicate_hint: Optional[str] = None,
    ) -> ResolverResult:
        """Pipeline 5 étapes pour résoudre user_subject → subject_canonical KG."""
        t0 = time.perf_counter()

        if not user_subject or not user_subject.strip():
            return ResolverResult(
                method="empty_input",
                abstain_reason="empty user_subject",
                duration_s=time.perf_counter() - t0,
            )

        # 1. Normalisation
        normalized = normalize_canonical_key(user_subject)

        # 2. Exact match sur :Entity.normalized_name
        exact_cand = self._exact_match_entity(normalized, tenant_id)
        if exact_cand is not None:
            # Enrichir avec subject_canonical via :ABOUT
            enriched = self._enrich_with_subject_canonical(
                exact_cand, tenant_id, predicate_hint,
            )
            if enriched is not None and enriched.subject_canonical:
                return ResolverResult(
                    resolved=enriched.subject_canonical,
                    confidence=enriched.score,
                    method="exact_normalized",
                    candidates=[enriched],
                    duration_s=time.perf_counter() - t0,
                )

        # 3. FTS sur :Entity.name (index 'entity_name_search')
        fts_candidates = self._fts_entity_search(user_subject, tenant_id, top_k=TOP_K_CANDIDATES)

        # 4. Embedding fallback si pas de FTS hit fort
        top_fts_raw = max((c.score for c in fts_candidates), default=0.0)
        # FTS scores are unbounded; we use raw score before normalization
        if not fts_candidates or self._fts_raw_top_score(fts_candidates) < FTS_SCORE_THRESHOLD:
            embedding_candidates = self._embedding_search(
                user_subject, tenant_id, top_k=TOP_K_CANDIDATES,
            )
            all_candidates = self._merge_candidates(fts_candidates, embedding_candidates)
        else:
            all_candidates = fts_candidates

        # 5. Re-ranking grapho-sensitif
        ranked = self._rerank_with_predicate(
            all_candidates, tenant_id, predicate_hint,
        )

        # 6. Décision finale
        duration = time.perf_counter() - t0
        if not ranked:
            return ResolverResult(
                method="no_candidates",
                abstain_reason="no candidates after search",
                duration_s=duration,
            )

        top = ranked[0]
        if top.score < self._min_confidence or top.subject_canonical is None:
            return ResolverResult(
                method="low_confidence",
                abstain_reason=(
                    f"top candidate score {top.score:.2f} < {self._min_confidence} "
                    f"OR no subject_canonical resolved"
                ),
                candidates=ranked[:TOP_K_RETURNED],
                duration_s=duration,
            )

        method = top.source
        if top.predicate_match is True:
            method = f"{top.source}+rerank"

        return ResolverResult(
            resolved=top.subject_canonical,
            confidence=top.score,
            method=method,
            candidates=ranked[:TOP_K_RETURNED],
            duration_s=duration,
        )

    # ------------------------------------------------------------------
    # Step 2 — Exact match Entity.normalized_name
    # ------------------------------------------------------------------

    def _exact_match_entity(
        self, normalized: str, tenant_id: str,
    ) -> Optional[ResolverCandidate]:
        if not normalized:
            return None
        try:
            rows = self._get_neo4j().execute_query(
                """
                MATCH (e:Entity {tenant_id: $tid, normalized_name: $norm})
                RETURN e.name AS name, e.entity_id AS eid,
                       coalesce(e.mention_count, 0) AS mc
                ORDER BY mc DESC
                LIMIT 1
                """,
                tid=tenant_id,
                norm=normalized,
            )
        except Exception:
            logger.exception("subject_resolver: exact_match query failed")
            return None
        if not rows:
            return None
        r = rows[0]
        return ResolverCandidate(
            entity_id=r.get("eid"),
            entity_name=r["name"],
            score=EXACT_CONFIDENCE,
            source="exact_normalized",
        )

    # ------------------------------------------------------------------
    # Step 3 — Full-text search
    # ------------------------------------------------------------------

    def _fts_entity_search(
        self, user_subject: str, tenant_id: str, top_k: int,
    ) -> List[ResolverCandidate]:
        try:
            # Note: paramètre Cypher renommé `search_query` pour éviter conflit
            # avec l'argument Python `query` de Neo4jClient.execute_query()
            rows = self._get_neo4j().execute_query(
                """
                CALL db.index.fulltext.queryNodes('entity_name_search', $search_query)
                YIELD node, score
                WHERE node.tenant_id = $tid
                RETURN node.entity_id AS eid, node.name AS name, score AS raw_score
                ORDER BY raw_score DESC
                LIMIT $k
                """,
                search_query=user_subject,
                tid=tenant_id,
                k=top_k,
            )
        except Exception:
            logger.exception("subject_resolver: FTS query failed (index 'entity_name_search' missing?)")
            return []
        if not rows:
            return []
        # Normalise les scores FTS par le max → [0,1]
        max_raw = max(r["raw_score"] for r in rows) or 1.0
        # On garde aussi le score brut pour le seuil FTS_SCORE_THRESHOLD
        candidates = []
        for r in rows:
            raw = r["raw_score"]
            # Score normalisé pour comparaison cross-méthode
            normalized_score = raw / max_raw
            cand = ResolverCandidate(
                entity_id=r.get("eid"),
                entity_name=r["name"],
                score=normalized_score,
                source="fts",
            )
            # On stocke le score brut dans un attribut additionnel pour le seuil
            cand.__dict__["_raw_score"] = raw
            candidates.append(cand)
        return candidates

    @staticmethod
    def _fts_raw_top_score(candidates: List[ResolverCandidate]) -> float:
        """Retourne le score FTS brut du top candidat (pour comparaison au seuil)."""
        if not candidates:
            return 0.0
        return float(candidates[0].__dict__.get("_raw_score", 0.0))

    # ------------------------------------------------------------------
    # Step 4 — Embedding fallback
    # ------------------------------------------------------------------

    def _embedding_search(
        self, user_subject: str, tenant_id: str, top_k: int,
    ) -> List[ResolverCandidate]:
        """Cherche via Qdrant les chunks sémantiquement proches, puis remonte aux
        Entities mentionnées dans ces chunks.

        Note : Qdrant indexe les chunks de section, pas les entities directement.
        On utilise donc une heuristique en 2 temps :
            (a) Top chunks vectoriels
            (b) Pour chaque chunk, query Neo4j pour les Entities qui ont des claims
                EXTRACTED_FROM ce chunk
        """
        try:
            vector = self._get_embedder()(user_subject)
            hits = self._get_qdrant_search()(
                collection_name=self._qdrant_collection,
                query_vector=vector,
                tenant_id=tenant_id,
                limit=top_k * 2,  # plus de chunks pour avoir plus d'entities
                score_threshold=0.4,
            )
        except Exception:
            logger.exception("subject_resolver: embedding search failed")
            return []

        if not hits:
            return []

        # Récupérer les entities mentionnées dans les claims des chunks top
        chunk_ids = [h.get("payload", {}).get("section_id") or str(h.get("id", ""))
                     for h in hits if h.get("score", 0) >= 0.4]
        chunk_ids = [c for c in chunk_ids if c]
        if not chunk_ids:
            return []

        # Pour chaque chunk, trouver les entities mentionnées dans ses claims
        # Note: le schéma OSMOSIS lie Claim → Entity via :ABOUT, et Claim a un
        # passage_id (chunk source). Donc on fait Chunk → Claim (par passage_id)
        # → Entity (via :ABOUT)
        try:
            rows = self._get_neo4j().execute_query(
                """
                MATCH (cl:Claim {tenant_id: $tid})
                WHERE cl.passage_id IN $chunks
                MATCH (cl)-[:ABOUT]-(e:Entity {tenant_id: $tid})
                WITH e, count(cl) AS n_claims
                ORDER BY n_claims DESC
                LIMIT $k
                RETURN e.entity_id AS eid, e.name AS name, n_claims
                """,
                tid=tenant_id,
                chunks=chunk_ids,
                k=top_k,
            )
        except Exception:
            logger.exception("subject_resolver: embedding-to-entity bridge failed")
            return []

        candidates = []
        max_n = max((r["n_claims"] for r in rows), default=1)
        for r in rows:
            # Score basé sur fréquence d'occurrence dans top chunks
            score = min(1.0, (r["n_claims"] / max_n) * 0.7)  # cap embedding à 0.7
            candidates.append(ResolverCandidate(
                entity_id=r.get("eid"),
                entity_name=r["name"],
                score=score,
                source="embedding",
            ))
        return candidates

    # ------------------------------------------------------------------
    # Merge candidates from different sources
    # ------------------------------------------------------------------

    @staticmethod
    def _merge_candidates(
        primary: List[ResolverCandidate],
        secondary: List[ResolverCandidate],
    ) -> List[ResolverCandidate]:
        """Merge candidates de 2 sources, déduplique par entity_id en gardant le max score."""
        merged: Dict[str, ResolverCandidate] = {}
        for c in primary + secondary:
            key = c.entity_id or c.entity_name
            if key in merged:
                # Garder le candidate avec le meilleur score
                if c.score > merged[key].score:
                    merged[key] = c
            else:
                merged[key] = c
        return sorted(merged.values(), key=lambda x: x.score, reverse=True)

    # ------------------------------------------------------------------
    # Step 5 — Re-ranking grapho-sensitif via :ABOUT
    # ------------------------------------------------------------------

    def _enrich_with_subject_canonical(
        self,
        candidate: ResolverCandidate,
        tenant_id: str,
        predicate_hint: Optional[str],
    ) -> Optional[ResolverCandidate]:
        """Pour une Entity, trouver le subject_canonical le plus fréquent dans
        les claims qui la mentionnent (via :ABOUT).

        Si `predicate_hint` est donné, filtre les claims sur ce predicate.
        """
        params: Dict[str, Any] = {"tid": tenant_id, "eid": candidate.entity_id}
        cypher_parts = [
            "MATCH (e:Entity {tenant_id: $tid, entity_id: $eid})-[:ABOUT]-(cl:Claim)",
            "WHERE cl.subject_canonical IS NOT NULL",
        ]
        if predicate_hint:
            cypher_parts.append("AND cl.predicate = $pred")
            params["pred"] = predicate_hint
        # Priorité : subject_canonical qui matche le nom de l'Entity, sinon
        # le plus fréquent. CASE pour scorer le match :
        #   exact match (case-insensitive) → 2
        #   partial match → 1
        #   sinon → 0
        # Ordre final : match_score DESC, count DESC
        cypher_parts.extend([
            "WITH e, cl.subject_canonical AS sc, count(cl) AS n",
            "WITH e, sc, n, CASE",
            "  WHEN toLower(sc) = toLower(e.name) THEN 2",
            "  WHEN toLower(sc) CONTAINS toLower(e.name)",
            "    OR toLower(e.name) CONTAINS toLower(sc) THEN 1",
            "  ELSE 0",
            "END AS match_score",
            "ORDER BY match_score DESC, n DESC",
            "LIMIT 1",
            "RETURN sc, n",
        ])
        cypher = "\n".join(cypher_parts)

        try:
            rows = self._get_neo4j().execute_query(cypher, **params)
        except Exception:
            logger.exception("subject_resolver: enrich query failed")
            return None

        if not rows:
            # Pas de subject_canonical trouvé via :ABOUT
            # Si predicate_hint était filtré, retry sans filtre
            if predicate_hint:
                logger.debug(
                    "subject_resolver: no claim with predicate=%s, retry without filter",
                    predicate_hint,
                )
                enriched_no_pred = self._enrich_with_subject_canonical(
                    candidate, tenant_id, predicate_hint=None,
                )
                if enriched_no_pred is not None:
                    # Marquer predicate_match=False (cohérent fail)
                    return enriched_no_pred.model_copy(update={"predicate_match": False})
            return None

        r = rows[0]
        return candidate.model_copy(update={
            "subject_canonical": r["sc"],
            "n_supporting_claims": r["n"],
            "predicate_match": True if predicate_hint else None,
        })

    def _rerank_with_predicate(
        self,
        candidates: List[ResolverCandidate],
        tenant_id: str,
        predicate_hint: Optional[str],
    ) -> List[ResolverCandidate]:
        """Re-rank les candidats en fonction de leur cohérence avec le predicate.

        - Pour chaque candidat, enrichir avec subject_canonical via :ABOUT
        - Si predicate matché (claim avec ce predicate trouvé) → boost ×PREDICATE_BOOST
        - Si pas de claim trouvé → pénalité ×NO_CLAIM_PENALTY
        """
        if not candidates:
            return []

        ranked: List[ResolverCandidate] = []
        for cand in candidates:
            if cand.entity_id is None:
                # Sans entity_id, on ne peut pas faire le rerank graphe
                ranked.append(cand)
                continue
            enriched = self._enrich_with_subject_canonical(
                cand, tenant_id, predicate_hint,
            )
            if enriched is None:
                # Pas de claim associé → pénalité
                penalized = cand.model_copy(update={
                    "score": cand.score * NO_CLAIM_PENALTY,
                    "predicate_match": False,
                })
                ranked.append(penalized)
            else:
                # Si predicate matché, boost ; sinon, garder le score
                if enriched.predicate_match is True:
                    boosted = enriched.model_copy(update={
                        "score": min(1.0, enriched.score * PREDICATE_BOOST),
                    })
                    ranked.append(boosted)
                else:
                    ranked.append(enriched)

        ranked.sort(key=lambda c: c.score, reverse=True)
        return ranked


# ============================================================================
# Top-level API
# ============================================================================


def resolve_subject(
    user_subject: str,
    tenant_id: str = "default",
    predicate_hint: Optional[str] = None,
    resolver: Optional[SubjectResolver] = None,
) -> ResolverResult:
    """API top-level."""
    r = resolver or SubjectResolver()
    return r.resolve(user_subject, tenant_id, predicate_hint)
