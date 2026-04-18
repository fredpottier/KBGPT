"""
C4 CandidateMiner — Mining de paires candidates pour detection de relations.

Stage 1 du pipeline C4 Relations Evidence-First.

Strategie :
1. Embedding similarity via Neo4j vector index (claims cross-doc)
2. Filtrage : cross-doc only, cosine > seuil, max paires par claim
3. Deduplication contre relations existantes

Usage :
    from knowbase.relations.candidate_miner_c4 import CandidateMinerC4
    miner = CandidateMinerC4(neo4j_driver)
    pairs = miner.mine_candidates(tenant_id="default")
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class CandidatePair:
    """Paire candidate pour adjudication NLI."""
    claim_a_id: str
    claim_a_text: str
    claim_a_doc_id: str
    claim_a_doc_title: str
    claim_b_id: str
    claim_b_text: str
    claim_b_doc_id: str
    claim_b_doc_title: str
    similarity_score: float
    source: str  # "embedding" | "entity_shared"


class CandidateMinerC4:
    """Mine les paires de claims candidates pour la detection de relations cross-doc."""

    def __init__(self, neo4j_driver, tenant_id: str = "default"):
        self.driver = neo4j_driver
        self.tenant_id = tenant_id

    def mine_candidates(
        self,
        *,
        cosine_threshold: float = 0.85,
        max_neighbors: int = 5,
        max_total_pairs: int = 0,
        exclude_existing: bool = True,
    ) -> list[CandidatePair]:
        """Mine les paires candidates via embedding similarity cross-doc.

        Pour chaque claim, trouve les k plus proches voisins cross-doc
        via le vector index Neo4j. Filtre par seuil cosine.

        Args:
            cosine_threshold: Seuil minimum de similarite cosine
            max_neighbors: Nombre max de voisins par claim
            max_total_pairs: Limite totale de paires
            exclude_existing: Exclure les paires qui ont deja une relation

        Returns:
            Liste de CandidatePair
        """
        start = time.time()

        # 1. Charger les doc titles pour enrichir les paires
        doc_titles = self._load_doc_titles()

        # 2. Miner via vector search
        pairs = self._mine_by_embedding(
            cosine_threshold=cosine_threshold,
            max_neighbors=max_neighbors,
            doc_titles=doc_titles,
        )

        logger.info(f"[C4:MINER] Mined {len(pairs)} raw candidate pairs in {time.time()-start:.1f}s")

        # 3. Deduplication (a, b) == (b, a)
        seen = set()
        deduped = []
        for p in pairs:
            key = tuple(sorted([p.claim_a_id, p.claim_b_id]))
            if key not in seen:
                seen.add(key)
                deduped.append(p)

        logger.info(f"[C4:MINER] After dedup: {len(deduped)} unique pairs")

        # 4. Exclure les paires avec relations existantes
        if exclude_existing and deduped:
            existing = self._get_existing_relation_pairs()
            before = len(deduped)
            deduped = [p for p in deduped if tuple(sorted([p.claim_a_id, p.claim_b_id])) not in existing]
            logger.info(f"[C4:MINER] Excluded {before - len(deduped)} pairs with existing relations")

        # 5. Limiter — budget auto si non specifie (sample_size * 2.5)
        budget = max_total_pairs if max_total_pairs > 0 else int(min(len(claims), 2000) * 2.5)
        if len(deduped) > budget:
            deduped.sort(key=lambda p: p.similarity_score, reverse=True)
            deduped = deduped[:budget]
            logger.info(f"[C4:MINER] Limited to {budget} pairs (auto={'yes' if max_total_pairs == 0 else 'no'})")

        logger.info(
            f"[C4:MINER] Final: {len(deduped)} candidate pairs, "
            f"{len(set(p.claim_a_doc_id for p in deduped) | set(p.claim_b_doc_id for p in deduped))} docs involved"
        )

        return deduped

    def _load_doc_titles(self) -> dict[str, str]:
        """Charge les titres de documents depuis DocumentContext."""
        query = """
        MATCH (dc:DocumentContext {tenant_id: $tid})
        RETURN dc.doc_id AS doc_id, dc.title AS title
        """
        with self.driver.session() as session:
            result = session.run(query, tid=self.tenant_id)
            return {r["doc_id"]: r["title"] or r["doc_id"] for r in result}

    def _mine_by_embedding(
        self,
        cosine_threshold: float,
        max_neighbors: int,
        doc_titles: dict[str, str],
    ) -> list[CandidatePair]:
        """Mine les paires via Neo4j vector index sur claim embeddings.

        Pour chaque claim, trouve les k plus proches voisins CROSS-DOC.
        """
        # Charger toutes les claims avec leur doc_id
        query_claims = """
        MATCH (c:Claim {tenant_id: $tid})
        WHERE c.embedding IS NOT NULL AND c.text IS NOT NULL AND size(c.text) > 30
        RETURN c.claim_id AS claim_id, c.text AS text, c.doc_id AS doc_id
        """

        # Vector search pour chaque claim — batché par doc pour efficacité
        query_neighbors = """
        MATCH (source:Claim {claim_id: $claim_id, tenant_id: $tid})
        CALL db.index.vector.queryNodes('claim_embedding', $k, source.embedding)
        YIELD node AS neighbor, score
        WHERE neighbor.tenant_id = $tid
          AND neighbor.doc_id <> source.doc_id
          AND score >= $threshold
          AND neighbor.text IS NOT NULL
          AND size(neighbor.text) > 30
        RETURN neighbor.claim_id AS neighbor_id,
               neighbor.text AS neighbor_text,
               neighbor.doc_id AS neighbor_doc_id,
               score
        LIMIT $k
        """

        pairs = []
        claims_processed = 0

        with self.driver.session() as session:
            # Charger les claims
            claims = list(session.run(query_claims, tid=self.tenant_id))
            logger.info(f"[C4:MINER] Loaded {len(claims)} claims with embeddings")

            # Pour chaque claim, chercher les voisins cross-doc
            # Optimisation : on sample les claims pour ne pas exploser (max 2000)
            sample_size = min(len(claims), 2000)
            if sample_size < len(claims):
                import random
                random.seed(42)
                claims = random.sample(claims, sample_size)
                logger.info(f"[C4:MINER] Sampled {sample_size} claims for mining")

            for i, claim in enumerate(claims):
                if i % 200 == 0 and i > 0:
                    logger.info(f"[C4:MINER] Processing claim {i}/{len(claims)}...")

                try:
                    neighbors = list(session.run(
                        query_neighbors,
                        claim_id=claim["claim_id"],
                        tid=self.tenant_id,
                        k=max_neighbors + 5,  # Over-fetch to account for same-doc filtering
                        threshold=cosine_threshold,
                    ))

                    for n in neighbors[:max_neighbors]:
                        pairs.append(CandidatePair(
                            claim_a_id=claim["claim_id"],
                            claim_a_text=claim["text"],
                            claim_a_doc_id=claim["doc_id"],
                            claim_a_doc_title=doc_titles.get(claim["doc_id"], claim["doc_id"]),
                            claim_b_id=n["neighbor_id"],
                            claim_b_text=n["neighbor_text"],
                            claim_b_doc_id=n["neighbor_doc_id"],
                            claim_b_doc_title=doc_titles.get(n["neighbor_doc_id"], n["neighbor_doc_id"]),
                            similarity_score=n["score"],
                            source="embedding",
                        ))

                    claims_processed += 1

                except Exception as e:
                    if "no such index" in str(e).lower():
                        logger.error(f"[C4:MINER] Vector index 'claim_embedding' not found!")
                        break
                    logger.debug(f"[C4:MINER] Vector search failed for {claim['claim_id']}: {e}")

        logger.info(f"[C4:MINER] Processed {claims_processed} claims, found {len(pairs)} raw pairs")
        return pairs

    def _get_existing_relation_pairs(self) -> set[tuple[str, str]]:
        """Retourne les paires claim deja scannees ou ayant une relation.

        Inclut :
        - Les relations reelles (CONTRADICTS/QUALIFIES/REFINES) — deja persistees
        - Le marker :C4_SCANNED — paires adjudiquees y compris celles resolues en NONE
          (permet les runs C4 incrementaux sans re-adjudication)
        """
        query = """
        MATCH (a:Claim {tenant_id: $tid})-[r:CONTRADICTS|QUALIFIES|REFINES|C4_SCANNED]-(b:Claim)
        WHERE a.claim_id < b.claim_id
        RETURN a.claim_id AS a_id, b.claim_id AS b_id
        """
        with self.driver.session() as session:
            result = session.run(query, tid=self.tenant_id)
            pairs = set()
            for r in result:
                pairs.add(tuple(sorted([r["a_id"], r["b_id"]])))
            return pairs

    def get_mining_stats(self) -> dict[str, Any]:
        """Retourne des statistiques sur le potentiel de mining."""
        with self.driver.session() as session:
            stats = session.run("""
                MATCH (c:Claim {tenant_id: $tid})
                WHERE c.embedding IS NOT NULL
                RETURN count(c) AS total_claims,
                       count(DISTINCT c.doc_id) AS total_docs
            """, tid=self.tenant_id).single()

            relations = session.run("""
                MATCH (a:Claim {tenant_id: $tid})-[r:CONTRADICTS|QUALIFIES|REFINES]->(b:Claim)
                RETURN type(r) AS rel_type, count(r) AS cnt
            """, tid=self.tenant_id)

            rel_counts = {r["rel_type"]: r["cnt"] for r in relations}

            return {
                "total_claims": stats["total_claims"],
                "total_docs": stats["total_docs"],
                "existing_relations": rel_counts,
                "total_existing": sum(rel_counts.values()),
            }
