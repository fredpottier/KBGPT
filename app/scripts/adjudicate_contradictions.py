#!/usr/bin/env python
"""
adjudicate_contradictions.py — Adjudication en contexte des paires CONTRADICTS (#446).

Pour chaque arête CONTRADICTS non encore adjugée, un juge LLM reçoit les DEUX
claims AVEC LEURS PASSAGES SOURCES (claim.passage_text, doc, page) et classe :
CONFIRMED / DIFFERENT_SCOPE / COMPLEMENTARY / EQUIVALENT / UNCLEAR.
Verdict posé sur l'arête (réversible) + rapport JSON complet pour relecture.

    docker exec knowbase-app python scripts/adjudicate_contradictions.py --tenant default
    docker exec knowbase-app python scripts/adjudicate_contradictions.py --limit 10   # smoke
    docker exec knowbase-app python scripts/adjudicate_contradictions.py --force      # re-juge tout
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tenant", default="default")
    ap.add_argument("--force", action="store_true", help="Re-juger même les arêtes déjà adjugées")
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--report", default=None, help="Chemin du rapport JSON (défaut: staging horodaté)")
    ap.add_argument("--workers", type=int, default=4)
    args = ap.parse_args()

    from knowbase.relations.contradiction_adjudicator import ContradictionAdjudicator

    adj = ContradictionAdjudicator()
    summary = adj.run(
        tenant_id=args.tenant,
        force=args.force,
        limit=args.limit,
        report_path=args.report,
        max_workers=args.workers,
    )
    print(f"\n=== ADJUDICATION TERMINÉE ({summary.duration_s:.0f}s) ===")
    print(f"  paires évaluées : {summary.n_total} (déjà faites: {summary.n_skipped_already})")
    for v, n in sorted(summary.by_verdict.items(), key=lambda kv: -kv[1]):
        print(f"  {v:18s} {n}")
    print(f"  rapport : {summary.report_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
