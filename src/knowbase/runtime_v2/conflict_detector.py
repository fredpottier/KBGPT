"""
Conflict Detector intra-anchor — V2-S4.

Wrapper sur les LOGICAL_RELATION {type: 'CONFLICT'} déjà persistées (Phase ingestion).
Conformément à VISION_RECENTREE §2 (USP réelle d'OSMOSIS) :
- Le KG porte le fait qu'il y a deux claims qui s'opposent (descriptif).
- Le runtime consulte ces faits + les LIFECYCLE_RELATION pour requalifier
  les contradictions résolues par succession (ex: doc_A SUPERSEDED par doc_B
  → CONFLICT entre claim_a et claim_b résolu par lifecycle, pas une vraie incohérence).

Aucune écriture KG.
"""
from __future__ import annotations

import logging
from typing import Optional

from neo4j import Driver

from knowbase.runtime_v2.models import ConflictReport

logger = logging.getLogger(__name__)


class ConflictDetector:
    """Détecte les vraies contradictions intra-anchor.

    Args:
        driver: Neo4j driver
        tenant_id: tenant courant
    """

    def __init__(self, driver: Driver, tenant_id: str = "default") -> None:
        self.driver = driver
        self.tenant_id = tenant_id

    def detect(
        self,
        doc_ids: list[str],
        confidence_threshold: float = 0.85,
    ) -> list[ConflictReport]:
        """Retourne les CONFLICT entre claims appartenant aux doc_ids fournis.

        Pour chaque CONFLICT, on vérifie si une LIFECYCLE_RELATION résout l'opposition
        (ex: doc_A → doc_B en SUPERSEDES/EVOLVES_FROM rend la contradiction acceptable
        comme évolution).

        Args:
            doc_ids: liste de docs autoritaires dans l'anchor
            confidence_threshold: seuil minimal CONFLICT.confidence pour reporter

        Returns:
            Liste ConflictReport. is_resolved_by_lifecycle=True signifie que la
            contradiction est explicable par une succession documentée — le frontend
            peut filtrer ces cas en mode normal et les afficher en mode Audit.
        """
        if len(doc_ids) < 2:
            return []  # Au moins 2 docs requis pour un conflict cross-doc

        cypher = """
        MATCH (a:Claim)-[r:LOGICAL_RELATION {type: 'CONFLICT'}]->(b:Claim)
        WHERE a.tenant_id = $tenant_id
          AND b.tenant_id = $tenant_id
          AND a.doc_id IN $doc_ids
          AND b.doc_id IN $doc_ids
          AND coalesce(r.legacy, false) = false
          AND coalesce(r.confidence, 0) >= $threshold
        OPTIONAL MATCH (dca:DocumentContext {doc_id: a.doc_id, tenant_id: $tenant_id})
                       -[lr:LIFECYCLE_RELATION]-(dcb:DocumentContext {doc_id: b.doc_id, tenant_id: $tenant_id})
        RETURN
          a.claim_id AS claim_a_id,
          a.doc_id AS doc_a_id,
          b.claim_id AS claim_b_id,
          b.doc_id AS doc_b_id,
          coalesce(r.confidence, 0) AS confidence,
          r.reasoning AS reasoning,
          lr.type AS lifecycle_type
        ORDER BY confidence DESC
        """
        with self.driver.session() as session:
            rows = session.run(
                cypher,
                tenant_id=self.tenant_id,
                doc_ids=doc_ids,
                threshold=confidence_threshold,
            ).data()

        reports: list[ConflictReport] = []
        for row in rows:
            lifecycle_type = row.get("lifecycle_type")
            is_resolved = lifecycle_type in {"SUPERSEDES", "EVOLVES_FROM"}
            reports.append(
                ConflictReport(
                    claim_a_id=row["claim_a_id"],
                    claim_b_id=row["claim_b_id"],
                    doc_a_id=row["doc_a_id"],
                    doc_b_id=row["doc_b_id"],
                    confidence=float(row["confidence"]),
                    reasoning=row.get("reasoning"),
                    is_resolved_by_lifecycle=is_resolved,
                    lifecycle_resolution_type=lifecycle_type,
                )
            )

        logger.info(
            "ConflictDetector: %d CONFLICT(s) intra-scope (resolved_by_lifecycle=%d)",
            len(reports),
            sum(1 for r in reports if r.is_resolved_by_lifecycle),
        )
        return reports
