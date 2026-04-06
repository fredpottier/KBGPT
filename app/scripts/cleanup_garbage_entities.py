#!/usr/bin/env python3
"""
Pass C3 — Garbage Collection et Entity Status.

Marque les entites selon leur qualite :
- VALID : >= 2 claims, ou liees a un CanonicalEntity
- UNCERTAIN : 1 claim, orpheline
- NOISY : 0 claims, orpheline — candidate a l'archivage

Les entites NOISY ne sont PAS supprimees (invariant: pas de destruction irreversible).
Elles sont marquees avec entity_status='NOISY' pour filtrage.

Usage :
    python scripts/cleanup_garbage_entities.py --dry-run --tenant default
    python scripts/cleanup_garbage_entities.py --execute --tenant default
"""

from __future__ import annotations

import argparse
import logging
import os

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)


def run(tenant_id: str, dry_run: bool = True):
    from neo4j import GraphDatabase

    neo4j_uri = os.getenv("NEO4J_URI", "bolt://localhost:7687")
    neo4j_user = os.getenv("NEO4J_USER", "neo4j")
    neo4j_pass = os.getenv("NEO4J_PASSWORD", "graphiti_neo4j_pass")

    driver = GraphDatabase.driver(neo4j_uri, auth=(neo4j_user, neo4j_pass))

    with driver.session() as session:
        # 1. Compter avant
        stats_before = session.run("""
            MATCH (e:Entity {tenant_id: $tid})
            OPTIONAL MATCH (e)<-[:ABOUT]-(c:Claim)
            OPTIONAL MATCH (e)-[:SAME_CANON_AS]->(ce:CanonicalEntity)
            WITH e, count(c) AS claims, ce IS NOT NULL AS has_canon
            RETURN
              count(e) AS total,
              count(CASE WHEN claims = 0 AND NOT has_canon THEN 1 END) AS noisy,
              count(CASE WHEN claims = 1 AND NOT has_canon THEN 1 END) AS uncertain,
              count(CASE WHEN claims >= 2 OR has_canon THEN 1 END) AS valid
        """, tid=tenant_id).single()

        logger.info(f"[C3] Etat avant:")
        logger.info(f"  Total: {stats_before['total']}")
        logger.info(f"  VALID (>=2 claims ou canonical): {stats_before['valid']}")
        logger.info(f"  UNCERTAIN (1 claim, orpheline): {stats_before['uncertain']}")
        logger.info(f"  NOISY (0 claims, orpheline): {stats_before['noisy']}")

        if dry_run:
            logger.info(f"\n[C3] DRY-RUN: {stats_before['noisy']} entites seraient marquees NOISY, "
                        f"{stats_before['uncertain']} marquees UNCERTAIN, "
                        f"{stats_before['valid']} marquees VALID")
            logger.info("  Relancer avec --execute pour appliquer.")
        else:
            # 2. Marquer NOISY : 0 claims, pas de canonical
            noisy_result = session.run("""
                MATCH (e:Entity {tenant_id: $tid})
                WHERE NOT (e)<-[:ABOUT]-(:Claim) AND NOT (e)-[:SAME_CANON_AS]->(:CanonicalEntity)
                SET e.entity_status = 'NOISY', e.status_updated_at = datetime()
                RETURN count(e) AS cnt
            """, tid=tenant_id).single()

            # 3. Marquer UNCERTAIN : 1 claim, pas de canonical
            uncertain_result = session.run("""
                MATCH (e:Entity {tenant_id: $tid})
                WHERE NOT (e)-[:SAME_CANON_AS]->(:CanonicalEntity)
                WITH e
                MATCH (e)<-[:ABOUT]-(c:Claim)
                WITH e, count(c) AS claims
                WHERE claims = 1
                SET e.entity_status = 'UNCERTAIN', e.status_updated_at = datetime()
                RETURN count(e) AS cnt
            """, tid=tenant_id).single()

            # 4. Marquer VALID : tout le reste
            valid_result = session.run("""
                MATCH (e:Entity {tenant_id: $tid})
                WHERE e.entity_status IS NULL
                SET e.entity_status = 'VALID', e.status_updated_at = datetime()
                RETURN count(e) AS cnt
            """, tid=tenant_id).single()

            logger.info(f"\n[C3] EXECUTED:")
            logger.info(f"  NOISY: {noisy_result['cnt']} entites marquees")
            logger.info(f"  UNCERTAIN: {uncertain_result['cnt']} entites marquees")
            logger.info(f"  VALID: {valid_result['cnt']} entites marquees")

            # 5. Stats finales
            final = session.run("""
                MATCH (e:Entity {tenant_id: $tid})
                RETURN e.entity_status AS status, count(e) AS cnt
                ORDER BY cnt DESC
            """, tid=tenant_id)
            logger.info(f"\n[C3] Distribution finale:")
            for r in final:
                logger.info(f"  {r['status'] or 'NULL':12s}: {r['cnt']}")

    driver.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="C3 — Garbage Collection")
    parser.add_argument("--tenant", default="default")
    parser.add_argument("--dry-run", action="store_true", default=True)
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()

    if args.execute:
        args.dry_run = False

    run(tenant_id=args.tenant, dry_run=args.dry_run)
