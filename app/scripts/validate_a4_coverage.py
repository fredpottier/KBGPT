"""A4.4 step 1 — Validation coverage subject_canonical post-A4.3 backfill.

Vérifie l'objectif posé par la règle de gouvernance Fred (22/05/2026) :
- Cible : ≥ 92% du KG avec subject_canonical (au-delà du seuil 5% NULL toléré)
- 8% acceptable au max pour les claims marginaux (cat d audit empirique)

Métriques rapportées :
- Total claims (référence : 11622 avant backfill A4.3)
- Has subject_canonical (cible ≥ 92%)
- Flagged marginal (informatif, peut être 5-15%)
- Still orphan (= subject_canonical NULL AND marginal NULL) → cible < 5%

Affiche aussi distribution par claim_type pour s'assurer qu'on n'a pas un
biais cat (ex: PRESCRIPTIVE qui resterait coincée).

Usage:
    docker exec knowbase-app sh -c 'cd /app && python scripts/validate_a4_coverage.py'
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))


def main():
    from knowbase.common.clients.neo4j_client import get_neo4j_client
    neo = get_neo4j_client()

    print("\n" + "=" * 80)
    print(f"A4.4 — COVERAGE VALIDATION subject_canonical — {datetime.now(timezone.utc).isoformat()}")
    print("=" * 80)

    # 1. Vue globale
    print("\n[1/3] Vue globale du KG (tenant=default) ...")
    rows = neo.execute_query(
        """
        MATCH (c:Claim {tenant_id: 'default'})
        RETURN
          count(c) AS total,
          count(CASE WHEN c.subject_canonical IS NOT NULL THEN 1 END) AS n_subject,
          count(CASE WHEN c.marginal = true THEN 1 END) AS n_marginal,
          count(CASE WHEN c.subject_canonical IS NULL AND (c.marginal IS NULL OR c.marginal = false) THEN 1 END) AS n_orphan,
          count(CASE WHEN c.subject_extraction_confidence IS NOT NULL THEN 1 END) AS n_with_confidence,
          avg(c.subject_extraction_confidence) AS avg_confidence
        """,
    )
    g = rows[0]
    total = g["total"]
    if total == 0:
        print("  ⚠ Aucun claim — backfill non encore exécuté ?")
        return 0

    has_subj_pct = g["n_subject"] / total
    marginal_pct = g["n_marginal"] / total
    orphan_pct = g["n_orphan"] / total

    print(f"  Total claims              : {total}")
    print(f"  Has subject_canonical     : {g['n_subject']:>5d}  {has_subj_pct:6.1%}")
    print(f"  Flagged marginal          : {g['n_marginal']:>5d}  {marginal_pct:6.1%}")
    print(f"  Still orphan              : {g['n_orphan']:>5d}  {orphan_pct:6.1%}")
    avg_conf = g['avg_confidence'] if g['avg_confidence'] is not None else 0.0
    print(f"  With extraction confidence: {g['n_with_confidence']:>5d}  (avg conf = {avg_conf:.2f})")

    # 2. Distribution par claim_type
    print(f"\n[2/3] Distribution par claim_type ...")
    rows = neo.execute_query(
        """
        MATCH (c:Claim {tenant_id: 'default'})
        RETURN
          c.claim_type AS claim_type,
          count(c) AS total,
          count(CASE WHEN c.subject_canonical IS NOT NULL THEN 1 END) AS n_subject,
          count(CASE WHEN c.marginal = true THEN 1 END) AS n_marginal,
          count(CASE WHEN c.subject_canonical IS NULL AND (c.marginal IS NULL OR c.marginal = false) THEN 1 END) AS n_orphan
        ORDER BY total DESC
        """,
    )
    print(f"  {'claim_type':15s}  {'total':>6s}  {'subj%':>7s}  {'marg%':>7s}  {'orph%':>7s}")
    for r in rows:
        t = r["total"]
        if t == 0:
            continue
        print(
            f"  {(r['claim_type'] or 'NULL'):15s}  "
            f"{t:>6d}  "
            f"{r['n_subject']/t:>6.1%}  "
            f"{r['n_marginal']/t:>6.1%}  "
            f"{r['n_orphan']/t:>6.1%}"
        )

    # 3. GATE
    print(f"\n[3/3] GATES de validation A4")
    has_subj_or_marg = (g["n_subject"] + g["n_marginal"]) / total
    print(f"  has_subject OR marginal  : {has_subj_or_marg:.1%} (cible ≥ 95%)")
    print(f"  orphan rate              : {orphan_pct:.1%} (cible ≤ 5%)")

    if orphan_pct <= 0.05:
        print(f"\n  ✅ GATE PASS — orphans ≤ 5% (cible règle Fred 22/05)")
        gate_status = "PASS"
    elif orphan_pct <= 0.10:
        print(f"\n  ⚠ GATE MARGINAL — orphans dans [5-10%], possible rerun A4.3 sur résidus")
        gate_status = "MARGINAL"
    else:
        print(f"\n  ❌ GATE FAIL — orphans > 10% : enquête nécessaire")
        gate_status = "FAIL"

    # Persist summary
    out_dir = Path("/app/data/benchmark/a44_validation")
    out_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    summary_file = out_dir / f"coverage_{ts}.json"
    with open(summary_file, "w", encoding="utf-8") as f:
        json.dump({
            "timestamp": ts,
            "total": total,
            "n_subject": g["n_subject"],
            "n_marginal": g["n_marginal"],
            "n_orphan": g["n_orphan"],
            "has_subj_pct": has_subj_or_marg,
            "orphan_pct": orphan_pct,
            "avg_confidence": g["avg_confidence"],
            "gate_status": gate_status,
        }, f, indent=2, default=str)
    print(f"\nDétails : {summary_file}")

    return 0 if gate_status == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
