"""
S2.A — CandidateMiner V3.3 (pair selection multi-signal).

Évolue de candidate_miner_c4.py (cosine seul) vers un score composite 5 signaux :

    score = 0.3·s_cos + 0.25·s_entity + 0.15·s_facet + 0.2·s_cluster + 0.1·s_graph

Avantage (cf. plan §S2.A) : 4 signaux sur 5 sont déjà calculés en post-import
(CanonicalEntity 2 320, ClaimCluster 9 622, Facet 68 — audit Phase A).
On ajoute juste le scoring composite.

Sources de paires candidates :
1. **Réutilisation C4** : 4 997 paires déjà :C4_SCANNED (cosine déjà calculé)
2. **Multi-signal new** : claims partageant 2+ entities OU même cluster cross-doc
   (élargit le recall sans nécessiter Qdrant)

Marker run incrémental : `:C12_SCANNED` (séparé de :C4_SCANNED pour tracer
indépendamment les runs S2/S3 V3.3).

Le runtime V3.3 ignore les paires legacy=true (S0).
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Optional

from neo4j import Driver

from knowbase.relations.v33_types import MultiSignalScore

logger = logging.getLogger(__name__)


# ============================================================================
# CandidatePair V3.3 (avec breakdown multi-signal)
# ============================================================================

@dataclass
class CandidatePairV33:
    """Paire candidate enrichie pour le 12-class classifier."""

    claim_a_id: str
    claim_a_text: str
    claim_a_doc_id: str
    claim_b_id: str
    claim_b_text: str
    claim_b_doc_id: str

    score_breakdown: MultiSignalScore
    """Détail des 5 signaux (audit + tuning)."""

    composite_score: float
    """Score composite pondéré."""

    source: str = "multi_signal"
    """Source de découverte: c4_cached | multi_signal_new"""

    shared_canonical_entities: list[str] = field(default_factory=list)
    """IDs des CanonicalEntity partagées (audit)."""

    shared_facets: list[str] = field(default_factory=list)
    shared_clusters: list[str] = field(default_factory=list)


# ============================================================================
# Miner core
# ============================================================================

class CandidateMinerV33:
    """
    Pair selection multi-signal V3.3.

    Stratégie :
    1. Récupérer les paires C4_SCANNED existantes (cosine déjà calculé)
    2. Mine de nouvelles paires via cluster/entity co-membership
    3. Calculer score composite pour toutes les paires (5 signaux)
    4. Filtrer par threshold (start 0.55)
    5. Marquer :C12_SCANNED pour idempotence
    """

    def __init__(self, neo4j_driver: Driver, tenant_id: str = "default"):
        self.driver = neo4j_driver
        self.tenant_id = tenant_id

    def mine_candidates(
        self,
        composite_threshold: float = 0.55,
        max_pairs: int = 10000,
        include_c4_cached: bool = True,
        include_new_pairs: bool = True,
    ) -> list[CandidatePairV33]:
        """
        Mine des paires candidates pour le 12-class classifier.

        Args:
            composite_threshold: Score composite minimum (défaut 0.55)
            max_pairs: Limite totale (auto-cap)
            include_c4_cached: Inclure les paires C4 existantes
            include_new_pairs: Mine des paires neuves via cluster/entity

        Returns:
            Liste de CandidatePairV33 triées par score décroissant
        """
        t_start = time.time()

        # 1. Recover C4 cached pairs avec leur cosine déjà calculé
        c4_pairs: list[tuple] = []
        if include_c4_cached:
            c4_pairs = self._fetch_c4_cached_pairs()
            logger.info(f"[V33:MINER] {len(c4_pairs):,} C4 cached pairs récupérées")

        # 2. Mine new pairs via cluster + entity co-membership
        new_pairs: list[tuple] = []
        if include_new_pairs:
            new_pairs = self._mine_via_cluster_entity()
            logger.info(f"[V33:MINER] {len(new_pairs):,} nouvelles paires multi-signal")

        # 3. Dedup + score
        all_pairs_dict: dict[tuple[str, str], CandidatePairV33] = {}
        for pair_data in c4_pairs:
            key = tuple(sorted([pair_data["a_id"], pair_data["b_id"]]))
            if key not in all_pairs_dict:
                pair = self._build_candidate_pair(pair_data, source="c4_cached")
                if pair.composite_score >= composite_threshold:
                    all_pairs_dict[key] = pair

        for pair_data in new_pairs:
            key = tuple(sorted([pair_data["a_id"], pair_data["b_id"]]))
            if key not in all_pairs_dict:
                pair = self._build_candidate_pair(pair_data, source="multi_signal_new")
                if pair.composite_score >= composite_threshold:
                    all_pairs_dict[key] = pair

        # 4. Sort + cap
        candidates = sorted(
            all_pairs_dict.values(),
            key=lambda p: p.composite_score,
            reverse=True,
        )
        if len(candidates) > max_pairs:
            candidates = candidates[:max_pairs]
            logger.info(f"[V33:MINER] Capped à {max_pairs:,}")

        elapsed = time.time() - t_start
        logger.info(
            f"[V33:MINER] {len(candidates):,} paires candidates "
            f"(threshold={composite_threshold}, elapsed={elapsed:.1f}s)"
        )

        return candidates

    # ------------------------------------------------------------------------
    # Helpers — fetch C4 cached pairs
    # ------------------------------------------------------------------------

    def _fetch_c4_cached_pairs(self) -> list[dict]:
        """Récupère les paires :C4_SCANNED avec leur similarity_score cached."""
        # Note : audit Phase A confirme C4_SCANNED = 4 997 relations (pas labels)
        query = """
        MATCH (a:Claim {tenant_id: $tid})-[r:C4_SCANNED]-(b:Claim)
        WHERE a.claim_id < b.claim_id
          AND coalesce(r.legacy, false) = false
        RETURN
          a.claim_id AS a_id, a.text AS a_text, a.doc_id AS a_doc,
          b.claim_id AS b_id, b.text AS b_text, b.doc_id AS b_doc,
          coalesce(r.similarity_score, r.score, 0.0) AS s_cos
        """
        with self.driver.session() as s:
            return s.run(query, tid=self.tenant_id).data()

    def _mine_via_cluster_entity(self) -> list[dict]:
        """
        Mine de NOUVELLES paires (non encore vues par C4) :
        - Claims partageant ≥2 CanonicalEntity (cross-doc)
        - OU Claims dans le même cluster (cross-doc)
        """
        # Pairs sharing 2+ canonical entities
        query_entity_share = """
        MATCH (a:Claim {tenant_id: $tid})-[:ABOUT]->(e:Entity)-[:SAME_CANON_AS]->(ce:CanonicalEntity)
        MATCH (b:Claim {tenant_id: $tid})-[:ABOUT]->(e2:Entity)-[:SAME_CANON_AS]->(ce)
        WHERE a.claim_id < b.claim_id
          AND a.doc_id <> b.doc_id
        WITH a, b, count(DISTINCT ce) AS shared_ce_count
        WHERE shared_ce_count >= 2
        RETURN
          a.claim_id AS a_id, a.text AS a_text, a.doc_id AS a_doc,
          b.claim_id AS b_id, b.text AS b_text, b.doc_id AS b_doc,
          shared_ce_count
        LIMIT 20000
        """

        # Pairs in same cluster (cross-doc)
        query_cluster_share = """
        MATCH (a:Claim {tenant_id: $tid})-[:IN_CLUSTER]->(cl:ClaimCluster)<-[:IN_CLUSTER]-(b:Claim {tenant_id: $tid})
        WHERE a.claim_id < b.claim_id
          AND a.doc_id <> b.doc_id
        RETURN
          a.claim_id AS a_id, a.text AS a_text, a.doc_id AS a_doc,
          b.claim_id AS b_id, b.text AS b_text, b.doc_id AS b_doc,
          cl.cluster_id AS cluster_id
        LIMIT 20000
        """

        results: dict[tuple[str, str], dict] = {}
        with self.driver.session() as s:
            for r in s.run(query_entity_share, tid=self.tenant_id):
                key = tuple(sorted([r["a_id"], r["b_id"]]))
                results[key] = dict(r)
            for r in s.run(query_cluster_share, tid=self.tenant_id):
                key = tuple(sorted([r["a_id"], r["b_id"]]))
                if key not in results:
                    results[key] = dict(r)

        return list(results.values())

    # ------------------------------------------------------------------------
    # Helpers — score breakdown
    # ------------------------------------------------------------------------

    def _build_candidate_pair(self, raw: dict, source: str) -> CandidatePairV33:
        """Calcule le score composite multi-signal pour une paire."""
        # Cosine
        s_cos = raw.get("s_cos", 0.0) or 0.0

        # Récupération des signaux complémentaires en 1 query Cypher
        signals = self._compute_other_signals(raw["a_id"], raw["b_id"])

        score = MultiSignalScore(
            s_cos=min(1.0, max(0.0, s_cos)),
            s_entity=signals["s_entity"],
            s_facet=signals["s_facet"],
            s_cluster=signals["s_cluster"],
            s_graph=signals["s_graph"],
        )

        return CandidatePairV33(
            claim_a_id=raw["a_id"],
            claim_a_text=raw["a_text"],
            claim_a_doc_id=raw["a_doc"],
            claim_b_id=raw["b_id"],
            claim_b_text=raw["b_text"],
            claim_b_doc_id=raw["b_doc"],
            score_breakdown=score,
            composite_score=score.composite,
            source=source,
            shared_canonical_entities=signals.get("shared_ce_ids", []),
            shared_facets=signals.get("shared_facet_ids", []),
            shared_clusters=signals.get("shared_cluster_ids", []),
        )

    def _compute_other_signals(self, a_id: str, b_id: str) -> dict:
        """
        Calcule s_entity, s_facet, s_cluster, s_graph en 1 query Cypher.

        - s_entity : min(1, count(shared_canonical_entities) / 2)
        - s_facet : 1 si même facet, 0 sinon
        - s_cluster : 1 si même cluster, 0 sinon
        - s_graph : approximation 1 - graph_distance / 4 via ABOUT path
        """
        query = """
        MATCH (a:Claim {claim_id: $aid, tenant_id: $tid})
        MATCH (b:Claim {claim_id: $bid, tenant_id: $tid})

        // s_entity : shared CanonicalEntity via ABOUT > SAME_CANON_AS
        OPTIONAL MATCH
          (a)-[:ABOUT]->(:Entity)-[:SAME_CANON_AS]->(ce:CanonicalEntity)<-[:SAME_CANON_AS]-(:Entity)<-[:ABOUT]-(b)
        WITH a, b, collect(DISTINCT ce.canonical_entity_id) AS shared_ce_ids

        // s_facet : shared Facet
        OPTIONAL MATCH (a)-[:BELONGS_TO_FACET]->(f:Facet)<-[:BELONGS_TO_FACET]-(b)
        WITH a, b, shared_ce_ids, collect(DISTINCT f.facet_id) AS shared_facet_ids

        // s_cluster : shared ClaimCluster
        OPTIONAL MATCH (a)-[:IN_CLUSTER]->(cl:ClaimCluster)<-[:IN_CLUSTER]-(b)
        WITH a, b, shared_ce_ids, shared_facet_ids, collect(DISTINCT cl.cluster_id) AS shared_cluster_ids

        RETURN
          shared_ce_ids,
          shared_facet_ids,
          shared_cluster_ids
        """
        with self.driver.session() as s:
            row = s.run(query, aid=a_id, bid=b_id, tid=self.tenant_id).single()
            if not row:
                return {
                    "s_entity": 0.0, "s_facet": 0.0, "s_cluster": 0.0, "s_graph": 0.0,
                    "shared_ce_ids": [], "shared_facet_ids": [], "shared_cluster_ids": [],
                }
            ce_ids = row["shared_ce_ids"] or []
            facet_ids = row["shared_facet_ids"] or []
            cluster_ids = row["shared_cluster_ids"] or []

            # graph distance approximée :
            # - ≥2 entities partagées → distance ~1 (très proche) → s_graph ~0.75
            # - 1 entity OU même facet OU même cluster → distance ~2 → s_graph ~0.5
            # - sinon → distance ≥4 → s_graph 0
            if len(ce_ids) >= 2:
                s_graph = 0.75
            elif len(ce_ids) == 1 or facet_ids or cluster_ids:
                s_graph = 0.5
            else:
                s_graph = 0.0

            return {
                "s_entity": min(1.0, len(ce_ids) / 2.0),
                "s_facet": 1.0 if facet_ids else 0.0,
                "s_cluster": 1.0 if cluster_ids else 0.0,
                "s_graph": s_graph,
                "shared_ce_ids": ce_ids,
                "shared_facet_ids": facet_ids,
                "shared_cluster_ids": cluster_ids,
            }

    # ------------------------------------------------------------------------
    # Marker C12_SCANNED (idempotence runs S2/S3)
    # ------------------------------------------------------------------------

    def mark_pairs_scanned(self, pairs: list[CandidatePairV33]) -> int:
        """Ajoute la relation `:C12_SCANNED` sur les paires (idempotence)."""
        if not pairs:
            return 0
        with self.driver.session() as s:
            result = s.run(
                """
                UNWIND $pairs AS p
                MATCH (a:Claim {claim_id: p.a_id, tenant_id: $tid})
                MATCH (b:Claim {claim_id: p.b_id, tenant_id: $tid})
                MERGE (a)-[r:C12_SCANNED]-(b)
                ON CREATE SET r.created_at = timestamp(), r.composite_score = p.score
                ON MATCH SET r.composite_score = p.score, r.last_seen = timestamp()
                RETURN count(r) AS n
                """,
                tid=self.tenant_id,
                pairs=[
                    {"a_id": p.claim_a_id, "b_id": p.claim_b_id, "score": p.composite_score}
                    for p in pairs
                ],
            ).single()
            return result["n"] if result else 0


__all__ = ["CandidateMinerV33", "CandidatePairV33"]
