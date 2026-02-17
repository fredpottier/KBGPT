#!/usr/bin/env python3
"""
Correction rétroactive du resolution_status des DocumentContexts.

Les DocumentContexts ont resolution_status="unresolved" et resolution_confidence=0.0
alors qu'un ComparableSubject existe (via ABOUT_COMPARABLE). Ce script :
1. Met à jour dc.resolution_status et dc.resolution_confidence depuis cs.confidence
2. Recalcule cs.doc_count et cs.source_doc_ids depuis les relations ABOUT_COMPARABLE

Usage (dans le conteneur Docker) :
    python scripts/fix_resolution_status.py --dry-run --tenant default
    python scripts/fix_resolution_status.py --execute --tenant default
"""

from __future__ import annotations

import argparse
import logging
import os
import sys

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)


def get_neo4j_driver():
    """Crée une connexion Neo4j."""
    from neo4j import GraphDatabase

    neo4j_uri = os.getenv("NEO4J_URI", "bolt://neo4j:7687")
    neo4j_user = os.getenv("NEO4J_USER", "neo4j")
    neo4j_password = os.getenv("NEO4J_PASSWORD", "graphiti_neo4j_pass")
    return GraphDatabase.driver(neo4j_uri, auth=(neo4j_user, neo4j_password))


def main():
    parser = argparse.ArgumentParser(
        description="Correction rétroactive du resolution_status des DocumentContexts"
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
            # 1. Trouver les paires DocumentContext ↔ ComparableSubject
            logger.info(f"[OSMOSE] Chargement des paires DC ↔ CS (tenant={args.tenant})...")
            result = session.run(
                """
                MATCH (dc:DocumentContext {tenant_id: $tid})-[:ABOUT_COMPARABLE]->(cs:ComparableSubject)
                RETURN dc.doc_id AS doc_id,
                       dc.resolution_status AS current_status,
                       dc.resolution_confidence AS current_confidence,
                       cs.subject_id AS subject_id,
                       cs.canonical_name AS canonical_name,
                       cs.confidence AS cs_confidence
                """,
                tid=args.tenant,
            )
            pairs = [dict(r) for r in result]
            logger.info(f"  → {len(pairs)} paires DC ↔ CS trouvées")

            if not pairs:
                logger.info("Aucune paire à corriger.")
                return

            # Afficher l'état actuel
            for p in pairs:
                logger.info(
                    f"  {p['doc_id']}: status={p['current_status']}, "
                    f"confidence={p['current_confidence']}, "
                    f"CS='{p['canonical_name']}' (conf={p['cs_confidence']})"
                )

            # 2. Corriger les DocumentContexts
            dc_fixed = 0
            for p in pairs:
                cs_conf = p["cs_confidence"] or 0.0
                new_status = "resolved" if cs_conf >= 0.85 else "low_confidence"
                new_confidence = max(p["current_confidence"] or 0.0, cs_conf)

                if p["current_status"] == new_status and (p["current_confidence"] or 0.0) == new_confidence:
                    logger.info(f"  {p['doc_id']}: déjà correct, skip")
                    continue

                logger.info(
                    f"  {p['doc_id']}: {p['current_status']} → {new_status}, "
                    f"confidence {p['current_confidence']} → {new_confidence:.2f}"
                )

                if not args.dry_run:
                    session.run(
                        """
                        MATCH (dc:DocumentContext {doc_id: $doc_id, tenant_id: $tid})
                        SET dc.resolution_status = $status,
                            dc.resolution_confidence = $confidence
                        """,
                        doc_id=p["doc_id"],
                        tid=args.tenant,
                        status=new_status,
                        confidence=new_confidence,
                    )
                dc_fixed += 1

            # 3. Recalculer doc_count et source_doc_ids sur les ComparableSubjects
            logger.info("\n[OSMOSE] Recalcul doc_count sur les ComparableSubjects...")
            cs_result = session.run(
                """
                MATCH (cs:ComparableSubject {tenant_id: $tid})
                OPTIONAL MATCH (dc:DocumentContext)-[:ABOUT_COMPARABLE]->(cs)
                WITH cs, collect(DISTINCT dc.doc_id) AS doc_ids
                RETURN cs.subject_id AS subject_id,
                       cs.canonical_name AS canonical_name,
                       cs.doc_count AS current_doc_count,
                       cs.source_doc_ids AS current_source_doc_ids,
                       doc_ids AS actual_doc_ids,
                       size(doc_ids) AS actual_count
                """,
                tid=args.tenant,
            )
            cs_rows = [dict(r) for r in cs_result]

            cs_fixed = 0
            for cs in cs_rows:
                actual_ids = [d for d in cs["actual_doc_ids"] if d is not None]
                actual_count = len(actual_ids)
                current_count = cs["current_doc_count"] or 0

                if current_count == actual_count:
                    logger.info(
                        f"  CS '{cs['canonical_name']}': doc_count={current_count} OK"
                    )
                    continue

                logger.info(
                    f"  CS '{cs['canonical_name']}': doc_count {current_count} → {actual_count}, "
                    f"docs={actual_ids}"
                )

                if not args.dry_run:
                    session.run(
                        """
                        MATCH (cs:ComparableSubject {subject_id: $sid, tenant_id: $tid})
                        SET cs.doc_count = $count,
                            cs.source_doc_ids = $doc_ids
                        """,
                        sid=cs["subject_id"],
                        tid=args.tenant,
                        count=actual_count,
                        doc_ids=actual_ids,
                    )
                cs_fixed += 1

            # Résumé
            logger.info(f"\n{'='*60}")
            logger.info("RÉSUMÉ FIX RESOLUTION STATUS")
            logger.info(f"{'='*60}")
            logger.info(f"DocumentContexts corrigés : {dc_fixed}")
            logger.info(f"ComparableSubjects corrigés : {cs_fixed}")

            if args.dry_run:
                logger.info("\n[DRY-RUN] Aucune modification effectuée.")
                logger.info("    Utilisez --execute pour appliquer.")

    finally:
        driver.close()


if __name__ == "__main__":
    main()
