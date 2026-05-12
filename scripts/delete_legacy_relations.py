#!/usr/bin/env python3
"""
S3.F.4 — Cleanup physique des 12 503 edges legacy V0.

Précondition (cf. plan §S3.F) :
- Golden set annoté avec précision CONFLICT ≥ 80%
- Validation user explicite via --confirm

Action :
1. Compte les edges CONTRADICTS|REFINES|QUALIFIES avec legacy=true
2. Vérifie qu'un dump JSONL existe dans data/forensics/legacy_relations_*.jsonl
3. Si --confirm : DELETE physique des edges
4. Vérifie post-suppression

Réversibilité : impossible après suppression. Le dump JSONL est l'unique
source de vérité pour reconstruction si nécessaire.

Usage :
    docker exec knowbase-app python /tmp/delete_legacy_relations.py            # dry-run
    docker exec knowbase-app python /tmp/delete_legacy_relations.py --confirm  # apply
"""
from __future__ import annotations

import argparse
import logging
import os
import sys
from datetime import datetime
from pathlib import Path

from neo4j import GraphDatabase

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

NEO4J_URI = os.getenv("NEO4J_URI", "bolt://neo4j:7687")
NEO4J_USER = os.getenv("NEO4J_USER", "neo4j")
NEO4J_PASSWORD = os.getenv("NEO4J_PASSWORD", "graphiti_neo4j_pass")

FORENSICS_DIR = Path("/data/forensics") if Path("/data").exists() else Path("data/forensics")


def main() -> int:
    parser = argparse.ArgumentParser(description="Cleanup physique edges legacy V0")
    parser.add_argument("--confirm", action="store_true", help="Apply DELETE (default: dry-run)")
    parser.add_argument("--skip-dump-check", action="store_true", help="Bypass legacy dump check (dangereux)")
    args = parser.parse_args()

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")

    logger.info("=" * 70)
    logger.info("S3.F.4 — Cleanup edges legacy V0 (CONTRADICTS|REFINES|QUALIFIES)")
    logger.info("=" * 70)
    logger.info(f"Mode : {'APPLY' if args.confirm else 'DRY-RUN'}")

    # 1. Vérifier qu'un dump JSONL existe (sauf bypass explicite)
    if not args.skip_dump_check:
        dumps = sorted(FORENSICS_DIR.glob("legacy_relations_*.jsonl"))
        if not dumps:
            logger.error(f"❌ Aucun dump legacy trouvé dans {FORENSICS_DIR}")
            logger.error(f"   Lance d'abord : scripts/dump_and_mark_legacy_relations.py")
            return 1
        latest_dump = dumps[-1]
        size_mb = latest_dump.stat().st_size / 1024 / 1024
        logger.info(f"✓ Dump trouvé : {latest_dump.name} ({size_mb:.1f} MB)")

    driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))

    try:
        with driver.session() as s:
            # 2. Counts pré-suppression
            logger.info("\n--- Counts pré-suppression ---")
            for rel_type in ("CONTRADICTS", "REFINES", "QUALIFIES"):
                row = s.run(f"""
                    MATCH ()-[r:{rel_type}]->()
                    RETURN
                        sum(CASE WHEN coalesce(r.legacy, false) = true THEN 1 ELSE 0 END) AS legacy,
                        count(r) AS total
                """).single()
                logger.info(f"  {rel_type:13s} : {row['legacy']:>6,} legacy / {row['total']:>6,} total")

            # 3. Suppression physique si --confirm
            if not args.confirm:
                logger.info("\n[DRY-RUN] Aucune suppression. Re-run avec --confirm pour appliquer.")
                return 0

            logger.info("\n--- DELETE legacy edges ---")
            deleted_total = 0
            for rel_type in ("CONTRADICTS", "REFINES", "QUALIFIES"):
                row = s.run(f"""
                    MATCH ()-[r:{rel_type}]->()
                    WHERE coalesce(r.legacy, false) = true
                    WITH r LIMIT 50000
                    DELETE r
                    RETURN count(r) AS deleted
                """).single()
                deleted = row["deleted"]
                deleted_total += deleted
                logger.info(f"  {rel_type}: {deleted:,} deleted")

            # 4. Vérification post-suppression
            logger.info("\n--- Vérification post-suppression ---")
            for rel_type in ("CONTRADICTS", "REFINES", "QUALIFIES"):
                row = s.run(f"""
                    MATCH ()-[r:{rel_type}]->()
                    RETURN
                        sum(CASE WHEN coalesce(r.legacy, false) = true THEN 1 ELSE 0 END) AS legacy_remaining,
                        count(r) AS total_remaining
                """).single()
                logger.info(f"  {rel_type:13s} : {row['legacy_remaining']:>6,} legacy / {row['total_remaining']:>6,} total")

            logger.info(f"\n✅ Cleanup completed : {deleted_total:,} edges deleted at {ts}")
            logger.info(f"   Dump preserved (réversibilité): {latest_dump if not args.skip_dump_check else 'N/A'}")
            return 0

    finally:
        driver.close()


if __name__ == "__main__":
    sys.exit(main())
