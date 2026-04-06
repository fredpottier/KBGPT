#!/usr/bin/env python3
"""
Comparateur complet — Compare les jugements LLM entre OSMOSIS et baselines.

Produit un rapport markdown avec metriques, deltas, et conclusions.

Usage:
    python benchmark/analysis/compare.py --osmosis benchmark/results/judge_osmosis_T1.json --baseline benchmark/results/judge_rag_claim_T1.json
    python benchmark/analysis/compare.py --results-dir benchmark/results/ --task T1
"""

from __future__ import annotations

import argparse
import glob
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
logger = logging.getLogger("benchmark-compare")


def compare_judge_results(osmosis_path: str, baseline_path: str) -> Dict[str, Any]:
    """Compare deux fichiers de jugements LLM."""

    with open(osmosis_path, "r", encoding="utf-8") as f:
        osm_data = json.load(f)
    with open(baseline_path, "r", encoding="utf-8") as f:
        bas_data = json.load(f)

    osm_scores = osm_data["scores"]
    bas_scores = bas_data["scores"]

    task = osm_data["metadata"]["task"]
    osm_system = osm_data["metadata"]["system"]
    bas_system = bas_data["metadata"]["system"]

    # Calculer les deltas
    deltas = {}
    for key in osm_scores:
        if key in bas_scores and isinstance(osm_scores[key], (int, float)) and isinstance(bas_scores[key], (int, float)):
            deltas[key] = osm_scores[key] - bas_scores[key]

    # Determiner gagnant par metrique
    wins = {"osmosis": 0, "baseline": 0, "tie": 0}
    results_by_metric = {}

    for key, delta in deltas.items():
        # Metriques inversees (plus bas = mieux)
        inverted = "arbitration" in key or "mixing" in key or "hallucination" in key
        if abs(delta) < 0.01:
            winner = "tie"
        elif inverted:
            winner = "osmosis" if delta < 0 else "baseline"
        else:
            winner = "osmosis" if delta > 0 else "baseline"

        wins[winner] += 1
        results_by_metric[key] = {
            "osmosis": osm_scores[key],
            "baseline": bas_scores[key],
            "delta": delta,
            "winner": winner,
        }

    return {
        "task": task,
        "osmosis_system": osm_system,
        "baseline_system": bas_system,
        "results_by_metric": results_by_metric,
        "wins": wins,
        "osmosis_scores": osm_scores,
        "baseline_scores": bas_scores,
    }


def generate_markdown_report(comparisons: List[Dict], output_path: str = None) -> str:
    """Genere un rapport markdown complet."""

    lines = [
        "# OSMOSIS Benchmark Report",
        "",
        f"**Date**: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}",
        f"**Tasks evaluated**: {len(comparisons)}",
        "",
        "---",
        "",
    ]

    # Resume executif
    total_osm_wins = sum(c["wins"]["osmosis"] for c in comparisons)
    total_bas_wins = sum(c["wins"]["baseline"] for c in comparisons)
    total_ties = sum(c["wins"]["tie"] for c in comparisons)

    lines.extend([
        "## Executive Summary",
        "",
        f"| Metric | OSMOSIS Wins | Baseline Wins | Ties |",
        f"|--------|-------------|---------------|------|",
        f"| **Total** | **{total_osm_wins}** | **{total_bas_wins}** | **{total_ties}** |",
        "",
    ])

    # Detail par tache
    for comp in comparisons:
        task = comp["task"]
        baseline = comp["baseline_system"]

        lines.extend([
            f"## {task} — OSMOSIS vs {baseline}",
            "",
            f"| Metric | OSMOSIS | {baseline} | Delta | Winner |",
            f"|--------|---------|---------|-------|--------|",
        ])

        for key, result in sorted(comp["results_by_metric"].items()):
            osm_val = f"{result['osmosis']:.3f}" if isinstance(result["osmosis"], float) else str(result["osmosis"])
            bas_val = f"{result['baseline']:.3f}" if isinstance(result["baseline"], float) else str(result["baseline"])
            delta = f"{result['delta']:+.3f}" if isinstance(result["delta"], float) else ""
            winner_icon = "OSMOSIS" if result["winner"] == "osmosis" else baseline if result["winner"] == "baseline" else "Tie"

            lines.append(f"| {key} | {osm_val} | {bas_val} | {delta} | {winner_icon} |")

        lines.extend([
            "",
            f"**Score**: OSMOSIS {comp['wins']['osmosis']} — {baseline} {comp['wins']['baseline']} — Ties {comp['wins']['tie']}",
            "",
            "---",
            "",
        ])

    report = "\n".join(lines)

    if output_path:
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(report)
        logger.info(f"Report saved to {output_path}")

    return report


def auto_compare_task(results_dir: str, task: str):
    """Auto-decouvre et compare les fichiers de resultats pour une tache."""

    dir_path = Path(results_dir)
    judge_files = list(dir_path.glob(f"judge_*_{task}_*.json"))

    if len(judge_files) < 2:
        logger.error(f"Besoin d'au moins 2 fichiers judge pour {task}, trouve: {len(judge_files)}")
        return

    # Trouver OSMOSIS vs baselines
    osmosis_file = None
    baseline_files = []

    for f in judge_files:
        if "osmosis" in f.name:
            osmosis_file = f
        else:
            baseline_files.append(f)

    if not osmosis_file:
        logger.error("Fichier OSMOSIS non trouve")
        return

    comparisons = []
    for bf in baseline_files:
        logger.info(f"Comparing {osmosis_file.name} vs {bf.name}")
        comp = compare_judge_results(str(osmosis_file), str(bf))
        comparisons.append(comp)

    report = generate_markdown_report(comparisons)
    print(report)

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    report_path = dir_path / f"report_{task}_{timestamp}.md"
    with open(report_path, "w", encoding="utf-8") as f:
        f.write(report)
    logger.info(f"Report: {report_path}")


def main():
    parser = argparse.ArgumentParser(description="Compare benchmark results")
    parser.add_argument("--osmosis", help="OSMOSIS judge results")
    parser.add_argument("--baseline", help="Baseline judge results")
    parser.add_argument("--results-dir", help="Auto-discover results in directory")
    parser.add_argument("--task", help="Task to compare (with --results-dir)")
    parser.add_argument("--output", default=None)
    args = parser.parse_args()

    if args.osmosis and args.baseline:
        comp = compare_judge_results(args.osmosis, args.baseline)
        report = generate_markdown_report([comp], args.output)
        print(report)
    elif args.results_dir and args.task:
        auto_compare_task(args.results_dir, args.task)
    else:
        parser.error("Provide --osmosis + --baseline, or --results-dir + --task")


if __name__ == "__main__":
    main()
