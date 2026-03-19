"""
Script de classification des contradictions CONTRADICTS dans Neo4j.

Usage:
    python scripts/classify_contradictions.py --dry-run
    python scripts/classify_contradictions.py --execute
    python scripts/classify_contradictions.py --stats
"""

from __future__ import annotations

import argparse
import json
import logging
import sys

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
logger = logging.getLogger("[OSMOSE] classify_contradictions")


def main():
    parser = argparse.ArgumentParser(description="Classification des contradictions CONTRADICTS")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--dry-run", action="store_true", help="Prévisualise sans modifier Neo4j")
    group.add_argument("--execute", action="store_true", help="Classifie et persiste dans Neo4j")
    group.add_argument("--stats", action="store_true", help="Affiche les statistiques actuelles")
    parser.add_argument("--tenant-id", default="default", help="Tenant ID (default: default)")
    parser.add_argument("--batch-size", type=int, default=5, help="Taille des batches LLM")
    args = parser.parse_args()

    from knowbase.common.clients.neo4j_client import get_neo4j_client

    client = get_neo4j_client()
    driver = client.driver

    from knowbase.claimfirst.clustering.contradiction_classifier import (
        ContradictionClassifier,
    )

    classifier = ContradictionClassifier(driver, batch_size=args.batch_size)

    if args.stats:
        stats = classifier.get_stats(tenant_id=args.tenant_id)
        print("\n=== Statistiques des contradictions ===")
        print(json.dumps(stats, indent=2, ensure_ascii=False))
        return

    if args.dry_run:
        pairs = classifier.load_unreviewed_pairs(tenant_id=args.tenant_id)
        print(f"\n=== DRY-RUN : {len(pairs)} paires à classifier ===\n")
        for i, pair in enumerate(pairs[:10]):
            inp = classifier.build_llm_input(pair)
            print(f"Paire {i}: {inp['claim_key']}")
            print(f"  A: {inp['claim_a']['text'][:100]}...")
            print(f"  B: {inp['claim_b']['text'][:100]}...")
            print(f"  Signals: {inp['context_signals']}")
            print()
        if len(pairs) > 10:
            print(f"... et {len(pairs) - 10} autres paires")
        return

    if args.execute:
        print("\n=== Classification des contradictions ===\n")
        stats = classifier.classify_all(
            tenant_id=args.tenant_id, dry_run=False
        )
        print("\n=== Résultats ===")
        print(json.dumps(stats, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
