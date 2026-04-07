# src/knowbase/perspectives/persister.py
"""
Persistance Neo4j pour les Perspectives V2 (theme-scoped).

Schema :
  (:Perspective) -[:INCLUDES_CLAIM]-> (:Claim)
  (:Perspective) -[:TOUCHES_SUBJECT]-> (:SubjectAnchor | :ComparableSubject)

Plus de relation HAS_PERSPECTIVE depuis un sujet (le sujet n'est plus
le parent), mais une relation TOUCHES_SUBJECT depuis la Perspective vers
les sujets touches (N:M, derive du contenu des claims).
"""

from __future__ import annotations

import logging
from typing import Dict, List

from .models import Perspective

logger = logging.getLogger(__name__)


def persist_perspectives(
    driver,
    tenant_id: str,
    perspectives: List[Perspective],
    claim_assignments: Dict[str, List[str]],
) -> Dict[str, int]:
    """
    Persiste les Perspectives theme-scoped dans Neo4j.

    Args:
        driver: Neo4j driver
        tenant_id: Tenant ID
        perspectives: Perspectives a persister
        claim_assignments: {perspective_id: [claim_ids]}
    """
    stats = {
        "perspectives_created": 0,
        "claims_linked": 0,
        "subjects_linked": 0,
    }

    if not perspectives:
        return stats

    with driver.session() as session:
        # 1. MERGE des nœuds Perspective (batch)
        batch = [p.to_neo4j_properties() for p in perspectives]
        session.run("""
            UNWIND $batch AS item
            MERGE (p:Perspective {perspective_id: item.perspective_id})
            SET p += item
        """, batch=batch)
        stats["perspectives_created"] = len(batch)

        # 2. INCLUDES_CLAIM : Perspective -> Claim (batch par perspective)
        for p in perspectives:
            claim_ids = claim_assignments.get(p.perspective_id, [])
            if not claim_ids:
                continue

            for i in range(0, len(claim_ids), 500):
                chunk = claim_ids[i:i + 500]
                session.run("""
                    UNWIND $claim_ids AS cid
                    MATCH (p:Perspective {perspective_id: $pid})
                    MATCH (c:Claim {claim_id: cid})
                    MERGE (p)-[:INCLUDES_CLAIM]->(c)
                """, pid=p.perspective_id, claim_ids=chunk)
                stats["claims_linked"] += len(chunk)

        # 3. TOUCHES_SUBJECT : Perspective -> SubjectAnchor / ComparableSubject
        for p in perspectives:
            if not p.linked_subject_ids:
                continue
            session.run("""
                UNWIND $sids AS sid
                MATCH (p:Perspective {perspective_id: $pid})
                OPTIONAL MATCH (sa:SubjectAnchor {subject_id: sid})
                OPTIONAL MATCH (cs:ComparableSubject {subject_id: sid})
                WITH p, coalesce(sa, cs) AS subj
                WHERE subj IS NOT NULL
                MERGE (p)-[:TOUCHES_SUBJECT]->(subj)
            """, pid=p.perspective_id, sids=p.linked_subject_ids)
            stats["subjects_linked"] += len(p.linked_subject_ids)

    logger.info(
        f"[PERSPECTIVE:PERSIST] {stats['perspectives_created']} perspectives, "
        f"{stats['claims_linked']} claim links, "
        f"{stats['subjects_linked']} subject links"
    )
    return stats


def delete_all_perspectives(driver, tenant_id: str) -> int:
    """Supprime toutes les Perspectives d'un tenant (pour rebuild complet)."""
    with driver.session() as session:
        result = session.run("""
            MATCH (p:Perspective {tenant_id: $tid})
            DETACH DELETE p
            RETURN count(p) AS deleted
        """, tid=tenant_id)
        deleted = result.single()["deleted"]

    logger.info(f"[PERSPECTIVE:DELETE] {deleted} perspectives deleted for tenant={tenant_id}")
    return deleted
