"""
C4 RelationPersister — Persistance des relations adjudiquees dans Neo4j.

Stage 3 du pipeline C4 Relations Evidence-First.

Chaque relation est persistee comme arete typee (CONTRADICTS, QUALIFIES, REFINES)
entre deux Claim nodes, avec les proprietes evidence obligatoires (INV-PROOF-01).

Usage :
    from knowbase.relations.relation_persister_c4 import RelationPersisterC4
    persister = RelationPersisterC4(neo4j_driver)
    stats = persister.persist_batch(adjudication_results)
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Any

from knowbase.relations.nli_adjudicator import AdjudicationResult

logger = logging.getLogger(__name__)


@dataclass
class PersistenceStats:
    """Statistiques de persistance."""
    total: int = 0
    created: int = 0
    updated: int = 0
    skipped: int = 0
    errors: int = 0


def _make_merge_cypher(rel_type: str) -> str:
    """Genere le Cypher MERGE pour un type de relation."""
    return f"""
        MATCH (c1:Claim {{claim_id: $c1id, tenant_id: $tid}})
        MATCH (c2:Claim {{claim_id: $c2id, tenant_id: $tid}})
        MERGE (c1)-[r:{rel_type}]->(c2)
        ON CREATE SET
            r.confidence = $conf,
            r.method = $method,
            r.evidence_a = $ev_a,
            r.evidence_b = $ev_b,
            r.reasoning = $reasoning,
            r.doc_a_title = $doc_a,
            r.doc_b_title = $doc_b,
            r.pivot_entity = $pivot,
            r.created_at = datetime()
        ON MATCH SET
            r.confidence = CASE WHEN $conf > r.confidence THEN $conf ELSE r.confidence END,
            r.method = CASE WHEN $conf > r.confidence THEN $method ELSE r.method END,
            r.evidence_a = CASE WHEN $conf > r.confidence THEN $ev_a ELSE r.evidence_a END,
            r.evidence_b = CASE WHEN $conf > r.confidence THEN $ev_b ELSE r.evidence_b END,
            r.reasoning = CASE WHEN $conf > r.confidence THEN $reasoning ELSE r.reasoning END,
            r.pivot_entity = CASE WHEN $pivot IS NOT NULL THEN $pivot ELSE r.pivot_entity END,
            r.updated_at = datetime()
        RETURN type(r) AS rel_type
    """


# Cypher par type de relation — MERGE pour upsert
CYPHER_BY_TYPE = {
    "CONTRADICTS": _make_merge_cypher("CONTRADICTS"),
    "QUALIFIES": _make_merge_cypher("QUALIFIES"),
    "REFINES": _make_merge_cypher("REFINES"),
    "COMPLEMENTS": _make_merge_cypher("COMPLEMENTS"),
    "EVOLVES_TO": _make_merge_cypher("EVOLVES_TO"),
    "SPECIALIZES": _make_merge_cypher("SPECIALIZES"),
}


class RelationPersisterC4:
    """Persiste les relations adjudiquees dans Neo4j avec preuves verbatim."""

    def __init__(self, neo4j_driver, tenant_id: str = "default"):
        self.driver = neo4j_driver
        self.tenant_id = tenant_id

    def persist_batch(
        self,
        results: list,
        on_progress: callable = None,
    ) -> PersistenceStats:
        """Persiste un batch de relations adjudiquees (C4 ou C6).

        Args:
            results: Liste de AdjudicationResult ou PivotAdjudicationResult
            on_progress: Callback(done, total) pour progression

        Returns:
            PersistenceStats avec compteurs
        """
        start = time.time()
        stats = PersistenceStats(total=len(results))

        with self.driver.session() as session:
            for i, result in enumerate(results):
                if on_progress and (i + 1) % 10 == 0:
                    on_progress(i + 1, len(results))

                cypher = CYPHER_BY_TYPE.get(result.relation)
                if not cypher:
                    stats.skipped += 1
                    continue

                try:
                    record = session.run(
                        cypher,
                        c1id=result.claim_a_id,
                        c2id=result.claim_b_id,
                        tid=self.tenant_id,
                        conf=result.confidence,
                        method=result.detection_method,
                        ev_a=result.evidence_a,
                        ev_b=result.evidence_b,
                        reasoning=result.reasoning,
                        doc_a=result.doc_a_title,
                        doc_b=result.doc_b_title,
                        pivot=getattr(result, 'pivot_entity', ''),
                    ).single()

                    stats.created += 1

                except Exception as e:
                    stats.errors += 1
                    logger.debug(f"[C4:PERSIST] Failed for {result.claim_a_id}: {e}")

        duration = time.time() - start
        logger.info(
            f"[C4:PERSIST] Persisted {stats.created} new + {stats.updated} updated "
            f"({stats.errors} errors, {stats.skipped} skipped) in {duration:.1f}s"
        )

        return stats

    def get_relation_counts(self) -> dict[str, int]:
        """Retourne le nombre de relations par type."""
        query = """
        MATCH (a:Claim {tenant_id: $tid})-[r:CONTRADICTS|QUALIFIES|REFINES|COMPLEMENTS|EVOLVES_TO|SPECIALIZES]->(b:Claim)
        RETURN type(r) AS rel_type, count(r) AS cnt
        """
        with self.driver.session() as session:
            result = session.run(query, tid=self.tenant_id)
            counts = {r["rel_type"]: r["cnt"] for r in result}

        counts["total"] = sum(counts.values())
        return counts

    def get_c4_relations(self) -> list[dict[str, Any]]:
        """Retourne les relations creees par C4 (method=embedding_nli)."""
        query = """
        MATCH (a:Claim {tenant_id: $tid})-[r:CONTRADICTS|QUALIFIES|REFINES]->(b:Claim)
        WHERE r.method = 'embedding_nli'
        RETURN a.claim_id AS a_id, a.text AS a_text,
               type(r) AS rel_type, r.confidence AS conf,
               r.evidence_a AS ev_a, r.evidence_b AS ev_b,
               r.reasoning AS reasoning,
               b.claim_id AS b_id, b.text AS b_text,
               r.doc_a_title AS doc_a, r.doc_b_title AS doc_b
        ORDER BY r.confidence DESC
        """
        with self.driver.session() as session:
            result = session.run(query, tid=self.tenant_id)
            return [dict(r) for r in result]
