"""
C6 PivotMiner — Mining de paires candidates via entites partagees cross-doc.

Stage 1 du pipeline C6 Cross-doc Pivots.

Strategie :
1. Trouver les entites presentes dans 2+ documents (pivots)
2. Pour chaque pivot, collecter les claims cross-doc
3. Generer des paires (claim_doc_A, claim_doc_B) pour le meme pivot
4. Deduplication contre relations existantes (C4 + C6)

Usage :
    from knowbase.relations.pivot_miner_c6 import PivotMinerC6
    miner = PivotMinerC6(neo4j_driver)
    pairs = miner.mine_candidates(tenant_id="default")
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from itertools import combinations
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class PivotCandidatePair:
    """Paire candidate pour adjudication C6 (pivot-based)."""
    claim_a_id: str
    claim_a_text: str
    claim_a_doc_id: str
    claim_a_doc_title: str
    claim_b_id: str
    claim_b_text: str
    claim_b_doc_id: str
    claim_b_doc_title: str
    pivot_entity: str       # nom de l'entite pivot
    pivot_doc_count: int    # nombre de docs ou le pivot apparait
    source: str = "entity_pivot"


class PivotMinerC6:
    """Mine les paires candidates cross-doc via entites partagees."""

    def __init__(self, neo4j_driver, tenant_id: str = "default"):
        self.driver = neo4j_driver
        self.tenant_id = tenant_id

    def mine_candidates(
        self,
        *,
        min_pivot_docs: int = 2,
        max_pairs_per_pivot: int = 10,
        max_total_pairs: int = 0,
        exclude_existing: bool = True,
    ) -> list[PivotCandidatePair]:
        """Mine les paires candidates via pivots d'entites cross-doc.

        Strategie de couverture :
        - Phase 1 : 1 paire par pivot (couverture minimale garantie)
        - Phase 2 : paires supplementaires pour les pivots les plus connectes
        - Budget = max_total_pairs si > 0, sinon auto (nombre de pivots * 2)

        Args:
            min_pivot_docs: Nombre minimum de documents pour un pivot
            max_pairs_per_pivot: Max paires generees par pivot
            max_total_pairs: Limite totale (0 = auto: pivots * 2)
            exclude_existing: Exclure les paires avec une relation existante

        Returns:
            Liste de PivotCandidatePair
        """
        start = time.time()

        # 1. Charger les doc titles
        doc_titles = self._load_doc_titles()

        # 2. Trouver les pivots (entites multi-doc)
        pivots = self._find_pivots(min_pivot_docs)
        logger.info(f"[C6:MINER] Found {len(pivots)} entity pivots (>= {min_pivot_docs} docs)")

        # Budget auto : chaque pivot merite au moins 1 paire, plus un bonus
        # pour les pivots tres connectes
        budget = max_total_pairs if max_total_pairs > 0 else len(pivots) * 2
        logger.info(f"[C6:MINER] Budget: {budget} pairs (auto={'yes' if max_total_pairs == 0 else 'no'})")

        # 3. Phase 1 : 1 paire par pivot (couverture garantie)
        phase1_pairs = []
        for pivot in pivots:
            pivot_pairs = self._pairs_for_pivot(pivot, doc_titles, 1)
            phase1_pairs.extend(pivot_pairs)

        logger.info(f"[C6:MINER] Phase 1 (coverage): {len(phase1_pairs)} pairs ({len(pivots)} pivots)")

        # 4. Phase 2 : paires supplementaires pour les pivots les plus connectes
        remaining_budget = budget - len(phase1_pairs)
        phase2_pairs = []
        if remaining_budget > 0:
            # Pivots tries par doc_count DESC — les plus connectes d'abord
            sorted_pivots = sorted(pivots, key=lambda p: len(p["docs"]), reverse=True)
            for pivot in sorted_pivots:
                if remaining_budget <= 0:
                    break
                extra = self._pairs_for_pivot(pivot, doc_titles, max_pairs_per_pivot)
                # Exclure les paires deja dans phase1
                phase1_keys = {(p.claim_a_id, p.claim_b_id) for p in phase1_pairs}
                new_pairs = [p for p in extra if (p.claim_a_id, p.claim_b_id) not in phase1_keys]
                take = min(len(new_pairs), remaining_budget)
                phase2_pairs.extend(new_pairs[:take])
                remaining_budget -= take

            logger.info(f"[C6:MINER] Phase 2 (depth): {len(phase2_pairs)} extra pairs")

        pairs = phase1_pairs + phase2_pairs

        logger.info(f"[C6:MINER] Generated {len(pairs)} raw pairs from pivots in {time.time()-start:.1f}s")

        # 4. Deduplication (a, b) == (b, a)
        seen = set()
        deduped = []
        for p in pairs:
            key = tuple(sorted([p.claim_a_id, p.claim_b_id]))
            if key not in seen:
                seen.add(key)
                deduped.append(p)

        logger.info(f"[C6:MINER] After dedup: {len(deduped)} unique pairs")

        # 5. Exclure les paires avec relations existantes (C4 ou autres)
        if exclude_existing and deduped:
            existing = self._get_existing_relation_pairs()
            before = len(deduped)
            deduped = [p for p in deduped if tuple(sorted([p.claim_a_id, p.claim_b_id])) not in existing]
            logger.info(f"[C6:MINER] Excluded {before - len(deduped)} pairs with existing relations")

        # 6. Limiter — prioriser les pivots avec le plus de docs
        if len(deduped) > max_total_pairs:
            deduped.sort(key=lambda p: p.pivot_doc_count, reverse=True)
            deduped = deduped[:max_total_pairs]
            logger.info(f"[C6:MINER] Limited to {max_total_pairs} pairs")

        logger.info(
            f"[C6:MINER] Final: {len(deduped)} candidate pairs, "
            f"{len(set(p.pivot_entity for p in deduped))} pivots involved"
        )

        return deduped

    def _load_doc_titles(self) -> dict[str, str]:
        """Charge les titres de documents."""
        query = """
        MATCH (dc:DocumentContext {tenant_id: $tid})
        RETURN dc.doc_id AS doc_id, dc.title AS title
        """
        with self.driver.session() as session:
            result = session.run(query, tid=self.tenant_id)
            return {r["doc_id"]: r["title"] or r["doc_id"] for r in result}

    def _find_pivots(self, min_docs: int) -> list[dict]:
        """Trouve les entites presentes dans min_docs+ documents."""
        query = """
        MATCH (c:Claim {tenant_id: $tid})-[:ABOUT]->(e)
        WHERE (e.quality_status IS NULL OR e.quality_status = "VALID")
          AND c.text IS NOT NULL AND size(c.text) > 30
        WITH e, collect(DISTINCT c.doc_id) AS docs, count(c) AS claim_count
        WHERE size(docs) >= $min_docs
        RETURN e.name AS name, docs, claim_count
        ORDER BY size(docs) DESC, claim_count DESC
        LIMIT 500
        """
        with self.driver.session() as session:
            result = session.run(query, tid=self.tenant_id, min_docs=min_docs)
            return [{"name": r["name"], "docs": r["docs"], "claim_count": r["claim_count"]} for r in result]

    def _pairs_for_pivot(
        self,
        pivot: dict,
        doc_titles: dict[str, str],
        max_pairs: int,
    ) -> list[PivotCandidatePair]:
        """Genere des paires cross-doc pour un pivot donne."""
        query = """
        MATCH (c:Claim {tenant_id: $tid})-[:ABOUT]->(e {name: $entity_name})
        WHERE c.text IS NOT NULL AND size(c.text) > 30
        RETURN c.claim_id AS claim_id, c.text AS text, c.doc_id AS doc_id
        """
        with self.driver.session() as session:
            claims = list(session.run(query, tid=self.tenant_id, entity_name=pivot["name"]))

        # Grouper par document
        by_doc: dict[str, list] = {}
        for c in claims:
            by_doc.setdefault(c["doc_id"], []).append(c)

        # Generer les paires cross-doc (1 claim par doc, combinaisons de docs)
        pairs = []
        doc_ids = list(by_doc.keys())

        for doc_a, doc_b in combinations(doc_ids, 2):
            claims_a = by_doc[doc_a]
            claims_b = by_doc[doc_b]

            # Limiter : 1 paire par combinaison de docs pour ce pivot
            # Prendre le claim le plus long de chaque doc (plus informatif)
            best_a = max(claims_a, key=lambda c: len(c["text"]))
            best_b = max(claims_b, key=lambda c: len(c["text"]))

            pairs.append(PivotCandidatePair(
                claim_a_id=best_a["claim_id"],
                claim_a_text=best_a["text"],
                claim_a_doc_id=doc_a,
                claim_a_doc_title=doc_titles.get(doc_a, doc_a),
                claim_b_id=best_b["claim_id"],
                claim_b_text=best_b["text"],
                claim_b_doc_id=doc_b,
                claim_b_doc_title=doc_titles.get(doc_b, doc_b),
                pivot_entity=pivot["name"],
                pivot_doc_count=len(pivot["docs"]),
            ))

            if len(pairs) >= max_pairs:
                break

        return pairs

    def _get_existing_relation_pairs(self) -> set[tuple[str, str]]:
        """Retourne les paires qui ont deja une relation (C4 ou autre)."""
        query = """
        MATCH (a:Claim {tenant_id: $tid})-[r:CONTRADICTS|QUALIFIES|REFINES|COMPLEMENTS|EVOLVES_TO|SPECIALIZES]->(b:Claim)
        RETURN a.claim_id AS a_id, b.claim_id AS b_id
        """
        with self.driver.session() as session:
            result = session.run(query, tid=self.tenant_id)
            pairs = set()
            for r in result:
                pairs.add(tuple(sorted([r["a_id"], r["b_id"]])))
            return pairs

    def get_pivot_stats(self) -> dict[str, Any]:
        """Statistiques sur les pivots disponibles."""
        with self.driver.session() as session:
            stats = session.run("""
                MATCH (c:Claim {tenant_id: $tid})-[:ABOUT]->(e)
                WHERE e.quality_status IS NULL OR e.quality_status = "VALID"
                WITH e, collect(DISTINCT c.doc_id) AS docs
                WHERE size(docs) >= 2
                RETURN count(e) AS pivot_count,
                       avg(size(docs)) AS avg_docs,
                       max(size(docs)) AS max_docs
            """, tid=self.tenant_id).single()

            return {
                "pivot_count": stats["pivot_count"],
                "avg_docs_per_pivot": round(stats["avg_docs"], 1),
                "max_docs_per_pivot": stats["max_docs"],
            }
