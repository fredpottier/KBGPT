#!/usr/bin/env python
"""
run_lineage_resolution.py — Résolution des contradictions par lignée documentaire
(ADR_RESOLUTION_CONTRADICTIONS, niveaux 1-2). Dry-run par défaut.

    python scripts/run_lineage_resolution.py --tenant default            # propose
    python scripts/run_lineage_resolution.py --tenant default --apply    # écrit
"""
from __future__ import annotations

import argparse
import json
import sys

from knowbase.common.clients.neo4j_client import get_neo4j_client
from knowbase.relations.lineage_resolution import LineageResolver


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tenant", default="default")
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    resolver = LineageResolver(get_neo4j_client().driver, tenant_id=args.tenant)
    report = resolver.run(dry_run=not args.apply)

    mode = "APPLY" if args.apply else "DRY-RUN (prévisions)"
    print("=" * 70)
    print(f"RÉSOLUTION PAR LIGNÉE — tenant={args.tenant} — {mode}")
    print("=" * 70)
    print(json.dumps(report.summary(), indent=1, ensure_ascii=False))
    if report.convention_edges_proposed:
        print("\nEdges convention de version (corroborés par dates) :")
        for e in report.convention_edges_proposed:
            print(f"  {e['superseder']} ▶ {e['superseded']}  (dates {e['dates'][0]} → {e['dates'][1]})")
    if report.convention_rejected:
        print("\nRejets convention (non corroborés — PAS d'invalidation, cf ADR §7.A) :")
        for r in report.convention_rejected:
            print("  ✗", r)
    return 0


if __name__ == "__main__":
    sys.exit(main())
