#!/usr/bin/env python3
"""
Backfill rétroactif quality_status = "PASS" sur les claims existantes.

Marque PASS sur les claims qui ont :
- quality_status IS NULL (jamais évaluées ou passées sans marquage)
- quality_scores_json contenant un verif_score >= 0.88

Usage (dans le conteneur Docker) :
    python scripts/backfill_quality_status.py --dry-run --tenant default
    python scripts/backfill_quality_status.py --execute --tenant default
"""

from __future__ import annotations

import argparse
import logging
import os

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)

VERIF_THRESHOLD = 0.88


def get_neo4j_driver():
    """Crée une connexion Neo4j."""
    from neo4j import GraphDatabase

    neo4j_uri = os.getenv("NEO4J_URI", "bolt://neo4j:7687")
    neo4j_user = os.getenv("NEO4J_USER", "neo4j")
    neo4j_password = os.getenv("NEO4J_PASSWORD", "graphiti_neo4j_pass")
    return GraphDatabase.driver(neo4j_uri, auth=(neo4j_user, neo4j_password))


def main():
    parser = argparse.ArgumentParser(
        description="Backfill quality_status = PASS sur claims existantes"
    )
    parser.add_argument("--dry-run", action="store_true", default=True,
                        help="Afficher sans modifier (défaut)")
    parser.add_argument("--execute", action="store_true",
                        help="Exécuter les modifications")
    parser.add_argument("--tenant", default="default",
                        help="Tenant ID (default: 'default')")
    args = parser.parse_args()

    if args.execute:
        args.dry_run = False

    driver = get_neo4j_driver()

    try:
        with driver.session() as session:
            # 1. Compter les claims éligibles
            count_result = session.run(
                """
                MATCH (c:Claim {tenant_id: $tenant_id})
                WHERE c.quality_status IS NULL
                  AND c.quality_scores_json IS NOT NULL
                RETURN count(c) AS total_null,
                       count(CASE
                           WHEN apoc.convert.fromJsonMap(c.quality_scores_json).verif_score >= $threshold
                           THEN 1
                       END) AS eligible
                """,
                tenant_id=args.tenant,
                threshold=VERIF_THRESHOLD,
            )
            record = count_result.single()
            total_null = record["total_null"]
            eligible = record["eligible"]

            # Compter les claims déjà marquées
            already_result = session.run(
                """
                MATCH (c:Claim {tenant_id: $tenant_id})
                WHERE c.quality_status IS NOT NULL
                RETURN count(c) AS already_marked
                """,
                tenant_id=args.tenant,
            )
            already_marked = already_result.single()["already_marked"]

            # Compter les claims sans quality_scores_json
            no_scores_result = session.run(
                """
                MATCH (c:Claim {tenant_id: $tenant_id})
                WHERE c.quality_status IS NULL
                  AND c.quality_scores_json IS NULL
                RETURN count(c) AS no_scores
                """,
                tenant_id=args.tenant,
            )
            no_scores = no_scores_result.single()["no_scores"]

            logger.info(f"\n{'='*60}")
            logger.info("BACKFILL QUALITY STATUS — RÉSUMÉ")
            logger.info(f"{'='*60}")
            logger.info(f"Claims déjà marquées       : {already_marked}")
            logger.info(f"Claims NULL + scores JSON   : {total_null}")
            logger.info(f"  → éligibles (verif≥{VERIF_THRESHOLD}) : {eligible}")
            logger.info(f"Claims NULL + pas de scores : {no_scores}")

            if args.dry_run:
                logger.info(f"\n[DRY-RUN] {eligible} claims seraient marquées PASS.")
                logger.info("    Utilisez --execute pour appliquer.")
                return

            if eligible == 0:
                logger.info("\nAucune claim éligible. Rien à faire.")
                return

            # 2. Appliquer le backfill
            logger.info(f"\n[OSMOSE] Marquage PASS sur {eligible} claims...")
            update_result = session.run(
                """
                MATCH (c:Claim {tenant_id: $tenant_id})
                WHERE c.quality_status IS NULL
                  AND c.quality_scores_json IS NOT NULL
                  AND apoc.convert.fromJsonMap(c.quality_scores_json).verif_score >= $threshold
                SET c.quality_status = "PASS"
                RETURN count(c) AS updated
                """,
                tenant_id=args.tenant,
                threshold=VERIF_THRESHOLD,
            )
            updated = update_result.single()["updated"]
            logger.info(f"  → {updated} claims marquées PASS")

            # 3. Vérification finale
            final_result = session.run(
                """
                MATCH (c:Claim {tenant_id: $tenant_id})
                RETURN c.quality_status AS status, count(c) AS cnt
                ORDER BY status
                """,
                tenant_id=args.tenant,
            )
            logger.info("\nDistribution quality_status après backfill :")
            for r in final_result:
                logger.info(f"  {r['status'] or 'NULL'}: {r['cnt']}")

            logger.info("\n[OSMOSE] Backfill terminé.")

    finally:
        driver.close()


if __name__ == "__main__":
    main()
