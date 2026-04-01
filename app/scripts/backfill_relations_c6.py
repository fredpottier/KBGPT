#!/usr/bin/env python3
"""
C6 Cross-doc Pivots — Script de backfill complet.

Orchestre les 3 stages du pipeline C6 :
  Stage 1 : PivotMiner      → mining paires via entites partagees cross-doc
  Stage 2 : PivotAdjudicator → adjudication LLM (COMPLEMENTS/EVOLVES_TO/SPECIALIZES)
  Stage 3 : RelationPersister → persistance Neo4j avec preuves verbatim

Usage :
    python -m scripts.backfill_relations_c6 [--dry-run] [--max-pairs 3000]
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
from datetime import datetime

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from neo4j import GraphDatabase

from knowbase.relations.pivot_miner_c6 import PivotMinerC6
from knowbase.relations.pivot_adjudicator_c6 import PivotAdjudicatorC6
from knowbase.relations.relation_persister_c4 import RelationPersisterC4

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)


def get_neo4j_driver():
    uri = os.getenv("NEO4J_URI", "bolt://localhost:7687")
    user = os.getenv("NEO4J_USER", "neo4j")
    password = os.getenv("NEO4J_PASSWORD", "graphiti_neo4j_pass")
    return GraphDatabase.driver(uri, auth=(user, password))


def run_pipeline(
    *,
    tenant_id: str = "default",
    min_pivot_docs: int = 2,
    max_pairs: int = 3000,
    max_workers: int = 3,
    dry_run: bool = False,
) -> dict:
    start_total = time.time()
    driver = get_neo4j_driver()

    try:
        # ====================================================================
        # Stage 1 : Mining via pivots
        # ====================================================================
        logger.info("=" * 60)
        logger.info("STAGE 1 : Mining paires via pivots d'entites")
        logger.info("=" * 60)

        miner = PivotMinerC6(driver, tenant_id=tenant_id)
        pivot_stats = miner.get_pivot_stats()
        logger.info(
            f"Pivots disponibles: {pivot_stats['pivot_count']} entites multi-doc "
            f"(avg {pivot_stats['avg_docs_per_pivot']} docs, max {pivot_stats['max_docs_per_pivot']})"
        )

        pairs = miner.mine_candidates(
            min_pivot_docs=min_pivot_docs,
            max_pairs_per_pivot=10,
            max_total_pairs=max_pairs,
            exclude_existing=True,
        )

        if not pairs:
            logger.warning("Aucune paire candidate. Fin.")
            return {"status": "no_candidates", "pairs": 0}

        logger.info(f"→ {len(pairs)} paires a adjudiquer")

        # ====================================================================
        # Stage 2 : Adjudication C6
        # ====================================================================
        logger.info("")
        logger.info("=" * 60)
        logger.info("STAGE 2 : Adjudication C6 (Claude Haiku)")
        logger.info("=" * 60)

        if not os.environ.get("ANTHROPIC_API_KEY"):
            logger.error("ANTHROPIC_API_KEY non definie.")
            return {"status": "error", "error": "missing_api_key"}

        adjudicator = PivotAdjudicatorC6(max_workers=max_workers)

        def on_adj_progress(done, total):
            logger.info(f"  Adjudication: {done}/{total} ({done*100//total}%)")

        results = adjudicator.adjudicate_batch(pairs, on_progress=on_adj_progress)

        if not results:
            logger.info("Aucune relation C6 detectee.")
            return {"status": "no_relations", "pairs_mined": len(pairs), "relations_found": 0}

        by_type = {}
        for r in results:
            by_type.setdefault(r.relation, []).append(r)

        logger.info(f"→ {len(results)} relations C6 trouvees :")
        for rel_type, rels in sorted(by_type.items()):
            logger.info(f"  {rel_type}: {len(rels)}")
            for r in rels[:3]:
                logger.info(f"    [{r.confidence:.2f}] pivot={r.pivot_entity}")
                logger.info(f"      A: \"{r.evidence_a[:80]}\"")
                logger.info(f"      B: \"{r.evidence_b[:80]}\"")

        if dry_run:
            logger.info("\n[DRY RUN] Pas de persistance.")
            return {
                "status": "dry_run",
                "pairs_mined": len(pairs),
                "relations_found": len(results),
                "by_type": {k: len(v) for k, v in by_type.items()},
            }

        # ====================================================================
        # Stage 3 : Persistance
        # ====================================================================
        logger.info("")
        logger.info("=" * 60)
        logger.info("STAGE 3 : Persistance Neo4j")
        logger.info("=" * 60)

        persister = RelationPersisterC4(driver, tenant_id=tenant_id)
        counts_before = persister.get_relation_counts()
        persist_stats = persister.persist_batch(results)
        counts_after = persister.get_relation_counts()

        # ====================================================================
        # Bilan
        # ====================================================================
        duration = time.time() - start_total
        logger.info("")
        logger.info("=" * 60)
        logger.info("BILAN C6 Cross-doc Pivots")
        logger.info("=" * 60)
        logger.info(f"Duree totale: {duration:.1f}s")
        logger.info(f"Paires minees: {len(pairs)}")
        logger.info(f"Relations trouvees: {len(results)}")
        logger.info(f"  - Creees: {persist_stats.created}")
        logger.info(f"  - Mises a jour: {persist_stats.updated}")
        logger.info(f"Relations avant/apres:")
        for rtype in ["CONTRADICTS", "QUALIFIES", "REFINES", "COMPLEMENTS", "EVOLVES_TO", "SPECIALIZES"]:
            before = counts_before.get(rtype, 0)
            after = counts_after.get(rtype, 0)
            if before or after:
                logger.info(f"  {rtype}: {before} → {after} (+{after - before})")
        logger.info(f"  TOTAL: {counts_before.get('total', 0)} → {counts_after.get('total', 0)}")

        report = {
            "timestamp": datetime.now().isoformat(),
            "duration_s": round(duration, 1),
            "config": {
                "min_pivot_docs": min_pivot_docs,
                "max_pairs": max_pairs,
                "max_workers": max_workers,
            },
            "mining": {"pairs_mined": len(pairs), "pivots": pivot_stats},
            "adjudication": {
                "relations_found": len(results),
                "by_type": {k: len(v) for k, v in by_type.items()},
            },
            "persistence": {
                "created": persist_stats.created,
                "updated": persist_stats.updated,
                "errors": persist_stats.errors,
            },
            "counts_before": counts_before,
            "counts_after": counts_after,
        }

        report_path = f"data/c6_relations_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        os.makedirs("data", exist_ok=True)
        with open(report_path, "w") as f:
            json.dump(report, f, indent=2)
        logger.info(f"Rapport: {report_path}")

        return report

    finally:
        driver.close()


def main():
    parser = argparse.ArgumentParser(description="C6 Cross-doc Pivots — Backfill")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--max-pairs", type=int, default=3000)
    parser.add_argument("--max-workers", type=int, default=3)
    parser.add_argument("--min-docs", type=int, default=2)
    parser.add_argument("--tenant", type=str, default="default")

    args = parser.parse_args()

    logger.info(f"C6 Cross-doc Pivots — max_pairs={args.max_pairs}, min_docs={args.min_docs}, dry_run={args.dry_run}")

    report = run_pipeline(
        tenant_id=args.tenant,
        min_pivot_docs=args.min_docs,
        max_pairs=args.max_pairs,
        max_workers=args.max_workers,
        dry_run=args.dry_run,
    )

    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
