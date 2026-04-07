# src/knowbase/perspectives/orchestrator.py
"""
Orchestrateur batch pour la construction des Perspectives V2 (theme-scoped).

Usage :
    python -m knowbase.perspectives.orchestrator [--tenant default] [--dry-run] [--skip-llm]
"""

from __future__ import annotations

import logging
import os
import time
from typing import Dict

from .builder import build_all_perspectives
from .models import PerspectiveConfig
from .persister import delete_all_perspectives, persist_perspectives

logger = logging.getLogger(__name__)


def _get_neo4j_driver():
    from neo4j import GraphDatabase
    uri = os.environ.get("NEO4J_URI", "bolt://neo4j:7687")
    user = os.environ.get("NEO4J_USER", "neo4j")
    password = os.environ.get("NEO4J_PASSWORD", "graphiti_neo4j_pass")
    return GraphDatabase.driver(uri, auth=(user, password))


def run_perspective_engine(
    tenant_id: str = "default",
    dry_run: bool = False,
    skip_llm: bool = False,
    config: PerspectiveConfig = None,
) -> Dict:
    """
    Execute le pipeline Perspective theme-scoped.

    Args:
        tenant_id: Tenant ID
        dry_run: Si True, ne pas persister
        skip_llm: Si True, ne pas labelliser (debug clustering)
        config: Configuration du builder

    Returns:
        Stats globales
    """
    config = config or PerspectiveConfig()
    start = time.time()
    driver = _get_neo4j_driver()

    logger.info("=" * 60)
    logger.info(f"PERSPECTIVE ENGINE V2 — {'DRY RUN' if dry_run else 'PRODUCTION'}")
    logger.info("=" * 60)
    logger.info(f"Tenant: {tenant_id}")
    logger.info(f"Config: UMAP({config.umap_n_components}D) + HDBSCAN(min={config.hdbscan_min_cluster_size})")
    logger.info(f"Skip LLM: {skip_llm}")

    # 1. Construire les Perspectives
    perspectives, claim_assignments = build_all_perspectives(
        driver, tenant_id, config=config, skip_llm=skip_llm,
    )

    if not perspectives:
        logger.warning("No perspectives created — abort")
        driver.close()
        return {"perspectives": 0}

    logger.info(f"\nBuilt {len(perspectives)} perspectives")

    # 2. Persister
    if dry_run:
        logger.info("[DRY RUN] Skipping persistence")
        stats = {"perspectives_created": 0, "claims_linked": 0, "subjects_linked": 0}
    else:
        # Cleanup ancienne version (subject-scoped) + nouvelle (theme-scoped)
        deleted = delete_all_perspectives(driver, tenant_id)
        logger.info(f"Deleted {deleted} previous perspectives")

        stats = persist_perspectives(driver, tenant_id, perspectives, claim_assignments)

    elapsed = time.time() - start
    logger.info("\n" + "=" * 60)
    logger.info(f"DONE in {elapsed:.1f}s")
    logger.info(f"Perspectives created : {len(perspectives)}")
    logger.info(f"Claims linked        : {stats.get('claims_linked', 0)}")
    logger.info(f"Subjects linked      : {stats.get('subjects_linked', 0)}")
    logger.info("=" * 60)

    driver.close()
    return {
        "perspectives": len(perspectives),
        "claims_linked": stats.get("claims_linked", 0),
        "subjects_linked": stats.get("subjects_linked", 0),
        "elapsed_s": round(elapsed, 1),
    }


def main():
    """Point d'entree CLI."""
    import argparse
    parser = argparse.ArgumentParser(description="OSMOSIS Perspective Engine V2 (theme-scoped)")
    parser.add_argument("--tenant", default="default")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--skip-llm", action="store_true", help="Skip LLM labelling (debug)")
    parser.add_argument("--min-cluster-size", type=int, default=30)
    parser.add_argument("--umap-dim", type=int, default=15)
    parser.add_argument("--max-clusters", type=int, default=60)
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(message)s")

    config = PerspectiveConfig(
        umap_n_components=args.umap_dim,
        hdbscan_min_cluster_size=args.min_cluster_size,
        max_clusters_to_label=args.max_clusters,
    )

    run_perspective_engine(
        tenant_id=args.tenant,
        dry_run=args.dry_run,
        skip_llm=args.skip_llm,
        config=config,
    )


if __name__ == "__main__":
    main()
