"""A4.4 step 3 — Comparaison bench A3.11 vs post-A4 (delta par question).

Compare le run A3.11 stratifié (run_20260522_085016.json) au run post-A4
(à passer en argument). Met en évidence :
- Delta C1 par question
- Delta C1 par catégorie de fail initial (cat A claim hors-sujet,
  cat B KG manque info, cat C subject non extrait)
- Distribution finale (combien à 1.0 / 0.5 / 0.0)
- Gate décision : si gain C1 ≥ +0.10pp → A4 validé.

Usage:
    docker exec knowbase-app sh -c 'cd /app && python scripts/compare_a311_vs_a4_bench.py \\
        --post-a4 data/benchmark/a38_runtime_v6/run_<YYYYMMDD_HHMMSS>.json'

Si --post-a4 non fourni, prend automatiquement le run le plus récent.
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


# Run A3.11 de référence (post-stratification claim_filter)
DEFAULT_PRE_A4 = "/app/data/benchmark/a38_runtime_v6/run_20260522_085016.json"


def find_latest_run(except_path: str | None = None) -> str | None:
    """Trouve le run JSON le plus récent (autre que except_path)."""
    runs_dir = Path("/app/data/benchmark/a38_runtime_v6")
    if not runs_dir.exists():
        return None
    candidates = sorted(runs_dir.glob("run_*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    for p in candidates:
        if except_path and str(p) == except_path:
            continue
        return str(p)
    return None


def main():
    parser = argparse.ArgumentParser(description="A4.4 compare bench A3.11 vs post-A4")
    parser.add_argument("--pre-a4", default=DEFAULT_PRE_A4, help="Run A3.11 référence")
    parser.add_argument("--post-a4", default=None, help="Run post-A4 (défaut = dernier run)")
    args = parser.parse_args()

    post_a4_path = args.post_a4 or find_latest_run(except_path=args.pre_a4)
    if not post_a4_path:
        print(f"\n❌ Aucun run post-A4 trouvé. Lance d'abord le bench 20q.")
        return 1

    print("\n" + "=" * 80)
    print(f"A4.4 — COMPARAISON A3.11 vs POST-A4 — {datetime.now(timezone.utc).isoformat()}")
    print("=" * 80)
    print(f"  Pre A4 (A3.11)  : {args.pre_a4}")
    print(f"  Post A4         : {post_a4_path}")

    with open(args.pre_a4) as f:
        pre = json.load(f)
    with open(post_a4_path) as f:
        post = json.load(f)

    pre_by_id = {r["id"]: r for r in pre.get("results_50q", [])}
    post_by_id = {r["id"]: r for r in post.get("results_50q", [])}

    pre_scores = []
    post_scores = []
    common_ids = sorted(set(pre_by_id) & set(post_by_id))

    print(f"\n  Common questions : {len(common_ids)}")
    if not common_ids:
        print("  ⚠ Aucune question commune — vérifier les deux runs")
        return 1

    # Delta par question
    print(f"\n[1/4] Delta par question")
    print(f"  {'id':35s} {'type':12s}  {'pre':>5s} {'post':>5s} {'Δ':>5s}  flag")
    n_improved = 0
    n_degraded = 0
    n_same = 0
    delta_by_type: Dict[str, List[float]] = {}
    for qid in common_ids:
        r_pre = pre_by_id[qid]
        r_post = post_by_id[qid]
        s_pre = r_pre.get("judge_score", 0)
        s_post = r_post.get("judge_score", 0)
        delta = s_post - s_pre
        typ = r_pre.get("primary_type", "?") or "?"
        flag = "★+" if delta > 0 else ("✗-" if delta < 0 else "=")
        print(f"  {qid[:33]:33s} {typ[:10]:10s}   {s_pre:.1f}  {s_post:.1f}  {delta:+.1f}  {flag}")
        pre_scores.append(s_pre)
        post_scores.append(s_post)
        delta_by_type.setdefault(typ, []).append(delta)
        if delta > 0:
            n_improved += 1
        elif delta < 0:
            n_degraded += 1
        else:
            n_same += 1

    # Agrégation
    pre_c1 = statistics.mean(pre_scores) if pre_scores else 0
    post_c1 = statistics.mean(post_scores) if post_scores else 0
    delta_c1 = post_c1 - pre_c1

    print(f"\n[2/4] Agrégation globale")
    print(f"  Pre A4 C1   : {pre_c1:.3f}")
    print(f"  Post A4 C1  : {post_c1:.3f}")
    print(f"  Delta C1    : {delta_c1:+.3f}pp")
    print(f"  Improved    : {n_improved}/{len(common_ids)}")
    print(f"  Degraded    : {n_degraded}/{len(common_ids)}")
    print(f"  Unchanged   : {n_same}/{len(common_ids)}")

    # Per type
    print(f"\n[3/4] Delta par type")
    for typ, deltas in sorted(delta_by_type.items()):
        n_pos = sum(1 for d in deltas if d > 0)
        n_neg = sum(1 for d in deltas if d < 0)
        avg = statistics.mean(deltas)
        print(f"  {typ:15s} n={len(deltas):2d} avg_delta={avg:+.3f} pos={n_pos} neg={n_neg}")

    # Distribution finale
    print(f"\n[4/4] Distribution finale judge scores (post-A4)")
    from collections import Counter
    pre_dist = Counter(round(s, 1) for s in pre_scores)
    post_dist = Counter(round(s, 1) for s in post_scores)
    for sc in [0.0, 0.5, 1.0]:
        print(f"  score={sc:.1f}  pre={pre_dist.get(sc, 0):3d}  post={post_dist.get(sc, 0):3d}  Δ={post_dist.get(sc, 0)-pre_dist.get(sc, 0):+d}")

    # GATE
    print(f"\nGATE A4 (cible Δ C1 ≥ +0.10pp) :")
    if delta_c1 >= 0.10:
        print(f"  ✅ PASS — gain mesuré {delta_c1:+.3f} ≥ +0.10pp")
        gate = "PASS"
    elif delta_c1 >= 0.05:
        print(f"  ⚠ MARGINAL — gain {delta_c1:+.3f} dans [0.05-0.10], surveiller variance")
        gate = "MARGINAL"
    elif delta_c1 >= 0:
        print(f"  ⚠ FAIBLE — gain {delta_c1:+.3f} positif mais sous le seuil")
        gate = "WEAK"
    else:
        print(f"  ❌ FAIL — régression {delta_c1:+.3f}")
        gate = "FAIL"

    # Persist
    out_dir = Path("/app/data/benchmark/a44_validation")
    out_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    out_file = out_dir / f"compare_{ts}.json"
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump({
            "timestamp": ts,
            "pre_a4_path": args.pre_a4,
            "post_a4_path": post_a4_path,
            "pre_c1": pre_c1,
            "post_c1": post_c1,
            "delta_c1": delta_c1,
            "n_improved": n_improved,
            "n_degraded": n_degraded,
            "n_same": n_same,
            "delta_by_type": {k: statistics.mean(v) for k, v in delta_by_type.items()},
            "gate": gate,
        }, f, indent=2, default=str)
    print(f"\nDétails : {out_file}")
    return 0 if gate in ("PASS", "MARGINAL") else 1


if __name__ == "__main__":
    sys.exit(main())
