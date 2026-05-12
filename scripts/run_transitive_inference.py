#!/usr/bin/env python3
"""
S4.A — Run TransitiveInferenceEngine pour matérialiser les relations dérivées.

Pattern :
1. Stats avant
2. Run materialization (depth 2 puis 3, idempotent MERGE)
3. Stats après
4. Output rapport

Usage :
    docker exec knowbase-app python /tmp/run_transitive_inference.py            # apply
    docker exec knowbase-app python /tmp/run_transitive_inference.py --dry-run  # preview
    docker exec knowbase-app python /tmp/run_transitive_inference.py --max-hops 2
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
from datetime import datetime
from pathlib import Path

from neo4j import GraphDatabase

sys.path.insert(0, "/app/src")

from knowbase.relations.transitive_inference import TransitiveInferenceEngine, MAX_HOPS  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

NEO4J_URI = os.getenv("NEO4J_URI", "bolt://neo4j:7687")
NEO4J_USER = os.getenv("NEO4J_USER", "neo4j")
NEO4J_PASSWORD = os.getenv("NEO4J_PASSWORD", "graphiti_neo4j_pass")
TENANT_ID = os.getenv("TENANT_ID", "default")

OUTPUT_DIR = Path("/data/forensics") if Path("/data").exists() else Path("data/forensics")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


def main() -> int:
    parser = argparse.ArgumentParser(description="S4.A transitive inference")
    parser.add_argument("--dry-run", action="store_true", help="Compute but don't persist")
    parser.add_argument("--max-hops", type=int, default=MAX_HOPS, help=f"Max depth (default {MAX_HOPS})")
    args = parser.parse_args()

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    report_path = OUTPUT_DIR / f"run_transitive_inference_{ts}.md"

    logger.info("=" * 70)
    logger.info(f"S4.A — Transitive inference (max_hops={args.max_hops}, dry_run={args.dry_run})")
    logger.info("=" * 70)

    driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))
    engine = TransitiveInferenceEngine(driver, tenant_id=TENANT_ID)

    try:
        # Stats avant
        logger.info("\n--- Stats avant ---")
        before = engine.stats()
        logger.info(f"  Total derived (existant) : {before['total_derived']:,}")
        logger.info(f"  Distinct types : {before['distinct_types']}")
        logger.info(f"  Avg confidence : {before['avg_confidence']:.3f}")
        for r in before["by_type"]:
            logger.info(f"    {r['type']}: {r['count']}")

        # Run
        logger.info(f"\n--- Materialization (max_hops={args.max_hops}) ---")
        result = engine.materialize(max_hops=args.max_hops, dry_run=args.dry_run)
        logger.info(f"\n  Derived count : {result.derived_count:,}")
        logger.info(f"  Skipped low confidence : {result.skipped_low_confidence:,}")
        logger.info(f"  Skipped existing : {result.skipped_existing:,}")
        logger.info(f"  Elapsed : {result.elapsed_s:.1f}s")

        # Stats après (si pas dry-run)
        if not args.dry_run:
            logger.info("\n--- Stats après ---")
            after = engine.stats()
            logger.info(f"  Total derived : {after['total_derived']:,}")
            logger.info(f"  Distinct types : {after['distinct_types']}")
            logger.info(f"  Avg confidence : {after['avg_confidence']:.3f}")
            for r in after["by_type"]:
                logger.info(f"    {r['type']}: {r['count']}")

            # Markdown report
            md = [
                f"# S4.A — Transitive inference ({ts})",
                "",
                f"**Mode** : `APPLIED` · **Max hops** : `{args.max_hops}`",
                "",
                "## Synthèse",
                "",
                f"- Derived nouvellement créées : **{result.derived_count:,}**",
                f"- Skipped low confidence (< 0.50) : {result.skipped_low_confidence:,}",
                f"- Skipped existing : {result.skipped_existing:,}",
                f"- Elapsed : {result.elapsed_s:.1f}s",
                "",
                "## Distribution derived par type (après)",
                "",
                "| Type | Count |",
                "|---|---:|",
            ]
            for r in after["by_type"]:
                md.append(f"| {r['type']} | {r['count']} |")
            md.append("")
            md.append(f"**Total dérivées** : {after['total_derived']:,}")
            md.append(f"**Avg confidence** : {after['avg_confidence']:.3f}")
            report_path.write_text("\n".join(md), encoding="utf-8")
            logger.info(f"\n✅ Report : {report_path}")
        else:
            logger.info("\n[DRY-RUN] No persistence. Re-run without --dry-run to apply.")

        return 0

    finally:
        driver.close()


if __name__ == "__main__":
    sys.exit(main())
