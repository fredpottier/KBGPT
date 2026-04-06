# src/knowbase/perspectives/persister.py
"""
Persistance Neo4j pour les Perspectives.

Utilise les patterns MERGE + UNWIND batch du claim_persister existant.
Ne cree pas son propre client — recoit le driver Neo4j en parametre.
"""

from __future__ import annotations

import logging
from typing import Dict, List

from .models import Perspective

logger = logging.getLogger(__name__)


def persist_perspectives(
    driver,
    tenant_id: str,
    subject_id: str,
    perspectives: List[Perspective],
    claim_assignments: Dict[str, List[str]],
) -> Dict[str, int]:
    """
    Persiste les Perspectives et leurs relations dans Neo4j.

    Args:
        driver: Neo4j driver
        tenant_id: Tenant ID
        subject_id: Subject ID parent
        perspectives: Liste de Perspectives a persister
        claim_assignments: Dict perspective_id -> [claim_ids]

    Returns:
        Stats de persistance {perspectives_created, claims_linked, facets_linked}
    """
    stats = {"perspectives_created": 0, "claims_linked": 0, "facets_linked": 0}

    if not perspectives:
        return stats

    with driver.session() as session:
        # 1. MERGE des noeuds Perspective (batch)
        batch = []
        for p in perspectives:
            props = p.to_neo4j_properties()
            batch.append(props)

        session.run("""
            UNWIND $batch AS item
            MERGE (p:Perspective {perspective_id: item.perspective_id})
            SET p += item
        """, batch=batch)
        stats["perspectives_created"] = len(batch)

        # 2. Relation HAS_PERSPECTIVE : SubjectAnchor -> Perspective
        #    On tente d'abord SubjectAnchor, puis ComparableSubject
        for p in perspectives:
            session.run("""
                OPTIONAL MATCH (sa:SubjectAnchor {subject_id: $sid})
                OPTIONAL MATCH (cs:ComparableSubject {subject_id: $sid})
                WITH coalesce(sa, cs) AS subject
                WHERE subject IS NOT NULL
                MATCH (p:Perspective {perspective_id: $pid})
                MERGE (subject)-[:HAS_PERSPECTIVE]->(p)
            """, sid=subject_id, pid=p.perspective_id)

        # 3. Relation INCLUDES_CLAIM : Perspective -> Claim (batch par perspective)
        for p in perspectives:
            claim_ids = claim_assignments.get(p.perspective_id, [])
            if not claim_ids:
                continue

            # Batch de 500 max
            for i in range(0, len(claim_ids), 500):
                chunk = claim_ids[i:i + 500]
                session.run("""
                    UNWIND $claim_ids AS cid
                    MATCH (p:Perspective {perspective_id: $pid})
                    MATCH (c:Claim {claim_id: cid})
                    MERGE (p)-[:INCLUDES_CLAIM]->(c)
                """, pid=p.perspective_id, claim_ids=chunk)
                stats["claims_linked"] += len(chunk)

        # 4. Relation SPANS_FACET : Perspective -> Facet
        for p in perspectives:
            if not p.source_facet_ids:
                continue
            session.run("""
                UNWIND $fids AS fid
                MATCH (p:Perspective {perspective_id: $pid})
                MATCH (f:Facet {facet_id: fid})
                MERGE (p)-[:SPANS_FACET]->(f)
            """, pid=p.perspective_id, fids=p.source_facet_ids)
            stats["facets_linked"] += len(p.source_facet_ids)

    logger.info(
        f"[PERSPECTIVE:PERSIST] subject={subject_id}: "
        f"{stats['perspectives_created']} perspectives, "
        f"{stats['claims_linked']} claim links, "
        f"{stats['facets_linked']} facet links"
    )
    return stats


def delete_perspectives_for_subject(driver, tenant_id: str, subject_id: str) -> int:
    """Supprime toutes les Perspectives d'un sujet (pour rebuild)."""
    with driver.session() as session:
        result = session.run("""
            MATCH (p:Perspective {tenant_id: $tid, subject_id: $sid})
            DETACH DELETE p
            RETURN count(p) AS deleted
        """, tid=tenant_id, sid=subject_id)
        deleted = result.single()["deleted"]

    logger.info(f"[PERSPECTIVE:DELETE] subject={subject_id}: {deleted} perspectives supprimees")
    return deleted
