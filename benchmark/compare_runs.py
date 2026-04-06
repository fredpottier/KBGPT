#!/usr/bin/env python3
"""Compare deux runs de benchmark pour detecter les regressions.

Usage:
    python benchmark/compare_runs.py --before judge_before.json --after judge_after.json [--threshold 0.05]

Affiche un diff colore et retourne exit code 1 si regression > threshold.
"""

import argparse
import json
import sys


def load_scores(path: str) -> dict:
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    return data.get("scores", {})


def compare(before_path: str, after_path: str, threshold: float = 0.05):
    before = load_scores(before_path)
    after = load_scores(after_path)

    all_keys = sorted(set(list(before.keys()) + list(after.keys())))

    # Metriques ou PLUS BAS = MIEUX
    inverted = {
        "false_idk_rate", "false_answer_rate", "irrelevant_rate",
        "total_error_rate", "silent_arbitration_rate", "version_mixing_rate",
    }

    regressions = []
    improvements = []
    neutral = []

    print(f"\n{'Metrique':<40} {'Avant':>8} {'Apres':>8} {'Delta':>8} {'Verdict':>12}")
    print("=" * 80)

    for key in all_keys:
        if key == "total_evaluated":
            continue

        v_before = before.get(key)
        v_after = after.get(key)

        if not isinstance(v_before, (int, float)) or not isinstance(v_after, (int, float)):
            continue

        delta = v_after - v_before
        is_inverted = key in inverted

        # Pour les metriques inversees, une BAISSE est une amelioration
        if is_inverted:
            is_regression = delta > threshold
            is_improvement = delta < -threshold
        else:
            is_regression = delta < -threshold
            is_improvement = delta > threshold

        if is_regression:
            verdict = "REGRESSION"
            regressions.append((key, v_before, v_after, delta))
        elif is_improvement:
            verdict = "IMPROVED"
            improvements.append((key, v_before, v_after, delta))
        else:
            verdict = "stable"
            neutral.append((key, v_before, v_after, delta))

        sign = "+" if delta > 0 else ""
        print(f"  {key:<38} {v_before:>8.3f} {v_after:>8.3f} {sign}{delta:>7.3f} {verdict:>12}")

    print(f"\n{'='*80}")
    print(f"  Improvements: {len(improvements)}")
    print(f"  Stable: {len(neutral)}")
    print(f"  Regressions: {len(regressions)}")

    if regressions:
        print(f"\n  REGRESSIONS DETECTEES (seuil {threshold}):")
        for key, vb, va, d in regressions:
            print(f"    {key}: {vb:.3f} -> {va:.3f} ({d:+.3f})")
        print(f"\n  EXIT CODE 1 — regressions detectees")
        sys.exit(1)
    else:
        print(f"\n  Aucune regression detectee (seuil {threshold})")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Compare benchmark runs")
    parser.add_argument("--before", required=True, help="Judge results JSON (baseline)")
    parser.add_argument("--after", required=True, help="Judge results JSON (nouveau)")
    parser.add_argument("--threshold", type=float, default=0.05, help="Seuil de regression (default 5pp)")
    args = parser.parse_args()
    compare(args.before, args.after, args.threshold)
