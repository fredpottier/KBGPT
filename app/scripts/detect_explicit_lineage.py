#!/usr/bin/env python
"""
Récolte la lignée explicite de document (SUPERSEDES_DOC) depuis les claims.

Dry-run par défaut (propose, n'écrit RIEN). `--apply` pour matérialiser.

    python scripts/detect_explicit_lineage.py --tenant default            # dry-run
    python scripts/detect_explicit_lineage.py --tenant default --apply    # écrit

Voir src/knowbase/relations/explicit_lineage_detector.py pour la logique.
"""
from __future__ import annotations

import argparse
import sys

from knowbase.common.clients.neo4j_client import get_neo4j_client
from knowbase.relations.explicit_lineage_detector import ExplicitLineageDetector


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tenant", default="default")
    ap.add_argument("--apply", action="store_true", help="Écrit les edges (sinon dry-run)")
    args = ap.parse_args()

    driver = get_neo4j_client().driver
    det = ExplicitLineageDetector(driver, tenant_id=args.tenant)

    edges, rejects = det.scan()

    print("=" * 72)
    print(f"LIGNÉE EXPLICITE — tenant={args.tenant} — {'APPLY' if args.apply else 'DRY-RUN'}")
    print("=" * 72)
    print(f"\nEdges proposées : {len(edges)}\n")
    for e in sorted(edges, key=lambda x: (x.superseded_key, x.superseder_key)):
        ext = "" if e.superseded_ingested else "  [externe, non ingéré]"
        date = f"  (daté {e.stated_date})" if e.stated_date else ""
        print(f"  {e.superseder_key}  ──SUPERSEDES──▶  {e.superseded_key}{ext}{date}")
        print(f"      pattern={e.pattern} conf={e.confidence}  claim={e.source_claim_id}")
        print(f"      « {e.evidence[:130]} »")

    # Chaînes reconstituées (pour visualiser la démo lignée)
    succ = {}
    for e in edges:
        succ.setdefault(e.superseded_key, []).append(e.superseder_key)
    print(f"\nRejets : {len(rejects)} claims (raisons agrégées)")
    from collections import Counter

    for reason, n in Counter(r for _, r in rejects).most_common():
        print(f"  {n:3}  {reason}")

    if args.apply:
        res = det.apply(edges)
        print(f"\n✅ APPLIQUÉ : {res['edges_written']} edges écrites.")
    else:
        print("\n(dry-run — rien écrit. Relancer avec --apply pour matérialiser.)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
