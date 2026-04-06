#!/usr/bin/env python
"""
run_facet_engine_v2.py — Execute le FacetEngine V2.

Remplace le matching par keywords par un scoring semantique
base sur des prototypes composites (embeddings).

Usage:
    docker compose exec app python scripts/run_facet_engine_v2.py
    docker compose exec app python scripts/run_facet_engine_v2.py --dry-run
    docker compose exec app python scripts/run_facet_engine_v2.py --top-k 30
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s: %(message)s")
logger = logging.getLogger(__name__)


def main():
    parser = argparse.ArgumentParser(description="FacetEngine V2")
    parser.add_argument("--tenant-id", default="default")
    parser.add_argument("--top-k", type=int, default=20, help="Prototypes per facet")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--emergent", action="store_true",
                        help="Use emergent clustering (HDBSCAN) instead of pre-defined facets")
    args = parser.parse_args()

    from neo4j import GraphDatabase

    uri = os.getenv("NEO4J_URI", "bolt://neo4j:7687")
    user = os.getenv("NEO4J_USER", "neo4j")
    password = os.getenv("NEO4J_PASSWORD", "graphiti_neo4j_pass")
    driver = GraphDatabase.driver(uri, auth=(user, password))

    if args.emergent:
        from knowbase.facets.orchestrator import run_facet_engine_v2_emergent
        stats = run_facet_engine_v2_emergent(
            driver=driver,
            tenant_id=args.tenant_id,
            dry_run=args.dry_run,
        )
    else:
        from knowbase.facets.orchestrator import run_facet_engine_v2
        stats = run_facet_engine_v2(
            driver=driver,
            tenant_id=args.tenant_id,
            top_k_prototypes=args.top_k,
            dry_run=args.dry_run,
        )

    print(json.dumps(stats, indent=2, default=str))
    driver.close()


if __name__ == "__main__":
    main()
