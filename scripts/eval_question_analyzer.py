#!/usr/bin/env python3
"""
CH-41.1 — Évaluation du QuestionAnalyzer multi-label top-2.

Mesure :
  - Accuracy top-1 et top-2 sur `benchmark/questions/gold_set_v4.json` (132q
    avec ground truth `primary_type`)
  - Couverture HFF5 sur `benchmark/questions/panel_stress_test_100q.json` (124q)
    = % de questions où primary_confidence ≥ 0.5

Gates ADR (CH-41.1) :
  - accuracy_top1 ≥ 0.90 sur gold-set
  - accuracy_top2 ≥ 0.95 sur gold-set
  - HFF5_coverage ≥ 0.95 sur panel stress-test

Usage :
  python scripts/eval_question_analyzer.py
  python scripts/eval_question_analyzer.py --limit 20  # smoke
  python scripts/eval_question_analyzer.py --workers 4
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from knowbase.facts_first import QuestionAnalyzer  # noqa: E402

GOLD_SET_PATH = PROJECT_ROOT / "benchmark" / "questions" / "gold_set_v4.json"
PANEL_PATH = PROJECT_ROOT / "benchmark" / "questions" / "panel_stress_test_100q.json"
OUTPUT_PATH = PROJECT_ROOT / "data" / "benchmark" / "calibration" / "question_analyzer_eval.json"


def load_deepinfra_key_into_env() -> None:
    if os.getenv("DEEPINFRA_API_KEY"):
        return
    env_path = PROJECT_ROOT / ".env"
    if not env_path.exists():
        return
    for line in env_path.read_text(encoding="utf-8").splitlines():
        if line.startswith("DEEPINFRA_API_KEY="):
            os.environ["DEEPINFRA_API_KEY"] = line.split("=", 1)[1].strip().strip('"').strip("'")
            return


def analyze_one(analyzer: QuestionAnalyzer, item: dict, gt_field: str) -> dict:
    question = item.get("question", "")
    expected = item.get(gt_field) or item.get("ground_truth", {}).get(gt_field)
    res = analyzer.analyze(question)
    top1_correct = (res.primary_type == expected) if expected else None
    top2_correct = top1_correct or (res.secondary_type == expected if expected else False)
    return {
        "id": item.get("id", "?"),
        "question": question[:120],
        "expected": expected,
        "predicted_primary": res.primary_type,
        "predicted_secondary": res.secondary_type,
        "primary_confidence": res.primary_confidence,
        "secondary_confidence": res.secondary_confidence,
        "language_predicted": res.language,
        "language_expected": item.get("language"),
        "routing": res.routing.value,
        "rationale": res.rationale,
        "latency_ms": res.latency_ms,
        "parse_error": res.parse_error,
        "top1_correct": top1_correct,
        "top2_correct": top2_correct,
    }


def run_dataset(name: str, items: list[dict], gt_field: str, workers: int) -> dict:
    analyzer = QuestionAnalyzer()
    t0 = time.time()
    samples: list[dict] = []
    n_total = len(items)
    n_done = 0
    with ThreadPoolExecutor(max_workers=workers) as ex:
        futures = {ex.submit(analyze_one, analyzer, it, gt_field): it for it in items}
        for fut in as_completed(futures):
            try:
                samples.append(fut.result())
            except Exception as exc:
                it = futures[fut]
                samples.append({
                    "id": it.get("id", "?"),
                    "expected": it.get(gt_field),
                    "predicted_primary": None,
                    "parse_error": str(exc),
                })
            n_done += 1
            if n_done % 10 == 0:
                logger.info("[%s] %d/%d analyses done", name, n_done, n_total)

    elapsed = time.time() - t0

    samples_with_gt = [s for s in samples if s.get("expected")]
    n_with_gt = len(samples_with_gt)
    n_correct_top1 = sum(1 for s in samples_with_gt if s.get("top1_correct"))
    n_correct_top2 = sum(1 for s in samples_with_gt if s.get("top2_correct"))
    n_high_conf = sum(1 for s in samples if (s.get("primary_confidence") or 0.0) >= 0.5)
    n_routing_eav = sum(1 for s in samples if s.get("routing") == "eav_fallback")
    n_routing_combined = sum(1 for s in samples if s.get("routing") == "combined")
    n_routing_single = sum(1 for s in samples if s.get("routing") == "single")
    parse_errors = sum(1 for s in samples if s.get("parse_error"))

    # Confusion
    confusion: dict[str, Counter] = {}
    for s in samples_with_gt:
        exp = s["expected"]
        pred = s.get("predicted_primary") or "?"
        confusion.setdefault(exp, Counter())[pred] += 1

    return {
        "dataset": name,
        "n_total": n_total,
        "n_with_ground_truth": n_with_gt,
        "n_parse_errors": parse_errors,
        "accuracy_top1": (n_correct_top1 / n_with_gt) if n_with_gt else None,
        "accuracy_top2": (n_correct_top2 / n_with_gt) if n_with_gt else None,
        "hff5_coverage_conf_ge_0_5": (n_high_conf / n_total) if n_total else None,
        "routing_distribution": {
            "single": n_routing_single,
            "combined": n_routing_combined,
            "eav_fallback": n_routing_eav,
        },
        "elapsed_seconds": round(elapsed, 1),
        "mean_latency_ms": (sum(s.get("latency_ms") or 0 for s in samples) / max(1, len(samples))),
        "confusion_matrix": {k: dict(v) for k, v in confusion.items()},
        "per_sample": samples,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=None, help="Limiter à N questions par dataset (smoke test)")
    parser.add_argument("--workers", type=int, default=4, help="Workers parallèles (default 4)")
    parser.add_argument("--gold-only", action="store_true", help="Skip panel stress-test")
    parser.add_argument("--panel-only", action="store_true", help="Skip gold-set")
    args = parser.parse_args()

    load_deepinfra_key_into_env()

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    final = {"started_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}

    if not args.panel_only:
        if not GOLD_SET_PATH.exists():
            logger.error("gold-set not found: %s", GOLD_SET_PATH)
            return 1
        gold = json.loads(GOLD_SET_PATH.read_text(encoding="utf-8"))
        if args.limit:
            gold = gold[: args.limit]
        logger.info("Eval gold-set v4: %d questions", len(gold))
        final["gold_set"] = run_dataset("gold_set_v4", gold, "primary_type", args.workers)
        logger.info(
            "[gold] top1=%.3f  top2=%.3f  HFF5=%.3f  parse_err=%d",
            final["gold_set"]["accuracy_top1"] or 0,
            final["gold_set"]["accuracy_top2"] or 0,
            final["gold_set"]["hff5_coverage_conf_ge_0_5"] or 0,
            final["gold_set"]["n_parse_errors"],
        )

    if not args.gold_only:
        if not PANEL_PATH.exists():
            logger.warning("panel stress-test not found: %s", PANEL_PATH)
        else:
            panel = json.loads(PANEL_PATH.read_text(encoding="utf-8"))
            if args.limit:
                panel = panel[: args.limit]
            logger.info("Eval panel stress-test: %d questions", len(panel))
            final["panel_stress_test"] = run_dataset(
                "panel_stress_test", panel, "expected_primary_type", args.workers
            )
            logger.info(
                "[panel] top1=%s  top2=%s  HFF5=%.3f  parse_err=%d",
                f"{final['panel_stress_test']['accuracy_top1']:.3f}" if final['panel_stress_test']['accuracy_top1'] is not None else "n/a",
                f"{final['panel_stress_test']['accuracy_top2']:.3f}" if final['panel_stress_test']['accuracy_top2'] is not None else "n/a",
                final["panel_stress_test"]["hff5_coverage_conf_ge_0_5"] or 0,
                final["panel_stress_test"]["n_parse_errors"],
            )

    final["completed_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    OUTPUT_PATH.write_text(json.dumps(final, ensure_ascii=False, indent=2), encoding="utf-8")
    logger.info("Persisted full eval to %s", OUTPUT_PATH)

    print()
    print("=== CH-41.1 GATES ===")
    if "gold_set" in final:
        gs = final["gold_set"]
        print(f"  accuracy_top1 = {gs['accuracy_top1']:.3f} (gate ≥ 0.90)  {'✓' if (gs['accuracy_top1'] or 0) >= 0.90 else '✗'}")
        print(f"  accuracy_top2 = {gs['accuracy_top2']:.3f} (gate ≥ 0.95)  {'✓' if (gs['accuracy_top2'] or 0) >= 0.95 else '✗'}")
    if "panel_stress_test" in final:
        ps = final["panel_stress_test"]
        print(f"  HFF5_coverage = {ps['hff5_coverage_conf_ge_0_5']:.3f} (gate ≥ 0.95)  {'✓' if (ps['hff5_coverage_conf_ge_0_5'] or 0) >= 0.95 else '✗'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
