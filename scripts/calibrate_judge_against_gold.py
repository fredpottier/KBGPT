#!/usr/bin/env python3
"""
CH-40.4 — Calibration Pearson juge LLM contre gold-set v4.

Mesure la corrélation entre le score du LLM-judge (Llama-3.3-70B-Instruct via
DeepInfra) et un "score humain équivalent" dérivé des annotations criterion-level
du gold-set v4 (item_level_recall, exact_match_identifiers, citation_presence_rate).

Mode 1 (recommandé) : depuis un rapport bench Robustness existant
  python scripts/calibrate_judge_against_gold.py --report data/benchmark/results/robustness_run_<...>.json

Mode 2 : run live (interroge V3 sur les 100q du gold-set)
  python scripts/calibrate_judge_against_gold.py --live --concurrency 3

Verdict :
- pearson_global ≥ 0.7 ET pearson_per_type ≥ 0.6 sur tous les types → PASS
- Sinon → FAIL → recommander bake-off A/B/C (Llama-3.3-70B vs Qwen-72B vs Selene-1-Mini-8B)

Output : data/benchmark/calibration/judge_<model>_<date>.json
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
GOLD_SET_PATH = PROJECT_ROOT / "benchmark" / "questions" / "gold_set_v4.json"
CALIBRATION_DIR = PROJECT_ROOT / "data" / "benchmark" / "calibration"

# Critères go/no-go (cf ADR_OSMOSIS_V4_ARCHITECTURE.md gate S0)
PEARSON_GLOBAL_THRESHOLD = 0.7
PEARSON_PER_TYPE_THRESHOLD = 0.6


def _pearson(xs: list[float], ys: list[float]) -> float:
    """Pearson correlation coefficient (no scipy dependency)."""
    n = len(xs)
    if n < 2 or n != len(ys):
        return 0.0
    mean_x = sum(xs) / n
    mean_y = sum(ys) / n
    num = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys))
    den_x = sum((x - mean_x) ** 2 for x in xs) ** 0.5
    den_y = sum((y - mean_y) ** 2 for y in ys) ** 0.5
    if den_x == 0 or den_y == 0:
        return 0.0
    return num / (den_x * den_y)


def _spearman(xs: list[float], ys: list[float]) -> float:
    """Spearman rank correlation."""
    n = len(xs)
    if n < 2 or n != len(ys):
        return 0.0

    def _rank(arr: list[float]) -> list[float]:
        sorted_idx = sorted(range(len(arr)), key=lambda i: arr[i])
        ranks = [0.0] * len(arr)
        for r, i in enumerate(sorted_idx):
            ranks[i] = r + 1
        return ranks

    return _pearson(_rank(xs), _rank(ys))


def calibrate_from_report(report_path: Path) -> dict[str, Any]:
    """Mode 1 : extrait Pearson depuis un rapport bench Robustness existant.

    Utilise le champ `disagreement` ajouté en CH-40.6 (per_sample[i].disagreement)
    pour calculer judge_score vs structured_avg corrélation.
    """
    if not report_path.exists():
        raise FileNotFoundError(f"Report not found: {report_path}")
    data = json.loads(report_path.read_text(encoding="utf-8"))

    judge_model = data.get("judge_model", "unknown")
    per_sample = data.get("per_sample", [])

    pairs: list[tuple[float, float, str]] = []  # (judge, structured, primary_type)
    for s in per_sample:
        ev = s.get("evaluation", {})
        sm = s.get("structured_metrics", {})
        if not sm or not sm.get("applicable"):
            continue
        if "score" not in ev or ev.get("error"):
            continue
        if sm.get("structured_avg") is None:
            continue
        pairs.append((
            float(ev["score"]),
            float(sm["structured_avg"]),
            s.get("primary_type") or "unknown",
        ))

    if not pairs:
        return {
            "verdict": "ERROR",
            "reason": "no_pairs_extracted",
            "n_pairs": 0,
        }

    judge_scores = [p[0] for p in pairs]
    struct_scores = [p[1] for p in pairs]
    pearson_global = _pearson(judge_scores, struct_scores)
    spearman_global = _spearman(judge_scores, struct_scores)

    # Pearson par type
    by_type: dict[str, list[tuple[float, float]]] = {}
    for j, s, pt in pairs:
        by_type.setdefault(pt, []).append((j, s))

    pearson_per_type = {}
    for pt, items in by_type.items():
        if len(items) >= 3:  # min 3 pour avoir un Pearson significatif
            jx = [p[0] for p in items]
            sx = [p[1] for p in items]
            pearson_per_type[pt] = {
                "pearson": round(_pearson(jx, sx), 3),
                "spearman": round(_spearman(jx, sx), 3),
                "n": len(items),
                "mean_judge": round(sum(jx) / len(jx), 3),
                "mean_structured": round(sum(sx) / len(sx), 3),
            }
        else:
            pearson_per_type[pt] = {"n": len(items), "skipped": "n<3"}

    # Verdict
    fails = []
    if pearson_global < PEARSON_GLOBAL_THRESHOLD:
        fails.append(f"global_pearson={pearson_global:.3f}<{PEARSON_GLOBAL_THRESHOLD}")
    for pt, stats in pearson_per_type.items():
        if "pearson" in stats and stats["pearson"] < PEARSON_PER_TYPE_THRESHOLD:
            fails.append(f"{pt}_pearson={stats['pearson']:.3f}<{PEARSON_PER_TYPE_THRESHOLD}")
    verdict = "PASS" if not fails else "FAIL"

    return {
        "verdict": verdict,
        "fails": fails,
        "judge_model": judge_model,
        "n_pairs": len(pairs),
        "pearson_global": round(pearson_global, 3),
        "spearman_global": round(spearman_global, 3),
        "pearson_per_type": pearson_per_type,
        "thresholds": {
            "global": PEARSON_GLOBAL_THRESHOLD,
            "per_type": PEARSON_PER_TYPE_THRESHOLD,
        },
        "source_report": str(report_path),
    }


def calibrate_live(concurrency: int = 3, api_base: str = "http://localhost:8000") -> dict[str, Any]:
    """Mode 2 : run live — interroge V3 sur les 100q du gold-set, score, calcule Pearson.

    Usage déconseillé en S0 (lent ~17 min, double-paie les LLM calls). Préférer
    calibrate_from_report sur un bench Robustness frais.
    """
    raise NotImplementedError(
        "calibrate_live mode pas encore implémenté en CH-40.4. Utilisez --report sur un "
        "rapport bench Robustness V3_S0_BASELINE (CH-40.5) à la place."
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=str, help="Chemin vers un rapport bench Robustness existant (mode 1)")
    parser.add_argument("--live", action="store_true", help="Mode live : interroge V3 directement (mode 2, déconseillé)")
    parser.add_argument("--concurrency", type=int, default=3, help="Concurrency mode live")
    parser.add_argument("--judge", type=str, default="llama-3.3-70b", help="Identifiant juge (pour le nom de fichier output)")
    args = parser.parse_args()

    CALIBRATION_DIR.mkdir(parents=True, exist_ok=True)

    if args.live:
        result = calibrate_live(concurrency=args.concurrency)
    elif args.report:
        result = calibrate_from_report(Path(args.report))
    else:
        # Mode auto : trouve le bench Robustness le plus récent avec tag V3_S0_*
        results_dir = PROJECT_ROOT / "app" / "data" / "benchmark" / "results"
        candidates = sorted(
            results_dir.glob("robustness_run_*.json"),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        recent = next((p for p in candidates if "V3_S0" in p.name), None)
        if not recent:
            logger.error(
                "Aucun rapport bench V3_S0_* trouvé. Lancez d'abord CH-40.5 "
                "(bench Robustness baseline avec tag V3_S0_BASELINE) ou passez --report."
            )
            return 1
        logger.info(f"Mode auto : utilisation du rapport {recent.name}")
        result = calibrate_from_report(recent)

    # Persist
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    out_path = CALIBRATION_DIR / f"judge_{args.judge}_{ts}.json"
    out_path.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")

    # Summary
    print()
    print("=" * 60)
    print(f"CH-40.4 Judge Calibration — {args.judge}")
    print("=" * 60)
    print(f"  Verdict : {result.get('verdict', '?')}")
    print(f"  N pairs : {result.get('n_pairs', 0)}")
    print(f"  Pearson global : {result.get('pearson_global', '?')} (threshold {PEARSON_GLOBAL_THRESHOLD})")
    print(f"  Spearman global : {result.get('spearman_global', '?')}")
    print()
    print("Pearson par type :")
    for pt, stats in (result.get("pearson_per_type") or {}).items():
        if "pearson" in stats:
            mark = "✓" if stats["pearson"] >= PEARSON_PER_TYPE_THRESHOLD else "✗"
            print(f"  {mark} {pt:15} pearson={stats['pearson']:>+.3f} spearman={stats['spearman']:>+.3f} (n={stats['n']})")
        else:
            print(f"  ? {pt:15} {stats}")
    if result.get("fails"):
        print()
        print("FAILS :")
        for f in result["fails"]:
            print(f"  - {f}")
        print()
        print("→ Recommandation : déclencher bake-off A/B/C (CH-40.4 secondaire) :")
        print("    python scripts/judge_bakeoff.py --candidates llama-3.3-70b qwen-72b selene-1-mini-8b")
    print()
    print(f"Saved : {out_path}")
    return 0 if result.get("verdict") == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
