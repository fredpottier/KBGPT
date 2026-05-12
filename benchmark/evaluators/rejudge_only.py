"""Re-judge an existing gold-set bench report without re-running OSMOSIS.

Reuses 'osmosis_answer' fields already stored in per_sample. Useful when:
- judge prompt or model changed
- judge had parsing failures (response_format not supported, timeout, etc.)
- want to compare judge_v1 vs judge_v2 without burning EC2 again

Usage:
    python -m benchmark.evaluators.rejudge_only \\
        --input benchmark/results/gold_set_sap_v1_v4_2_baseline.json \\
        --output benchmark/results/gold_set_sap_v1_v4_2_rejudged.json

Re-runs ONLY the llm_judge step + recomputes aggregates. Corpus-agnostic.
"""
from __future__ import annotations

import argparse
import json
import logging
from datetime import datetime
from pathlib import Path

from benchmark.evaluators.gold_set_runner import (
    llm_judge,
    exact_match_identifiers,
    citation_presence,
    aggregate,
    JUDGE_MODEL,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)


def rejudge(input_path: Path, output_path: Path, force: bool = False) -> dict:
    """Reload report, re-judge each sample (or only failed ones), rewrite."""
    report = json.loads(input_path.read_text(encoding="utf-8"))
    per_sample = report.get("per_sample", [])
    logger.info(f"Loaded {len(per_sample)} samples from {input_path}")
    logger.info(f"Judge model: {JUDGE_MODEL}")

    new_per_sample = []
    rejudged = 0
    kept = 0
    for s in per_sample:
        qid = s.get("id")
        question = s.get("question")
        ref = s.get("reference_answer", "")
        ans = s.get("osmosis_answer", "")

        existing_score = s.get("judge", {}).get("score", -1.0)
        should_rejudge = force or existing_score < 0

        if should_rejudge:
            logger.info(f"  rejudging {qid} (was: {existing_score})")
            judge = llm_judge(question, ref, ans)
            s["judge"] = judge

            # Recompute structured metrics + disagreement
            ids = s.get("structured_metrics", {}).get("exact_match_identifiers", {})
            # Reuse existing structured (computed at run time) — they don't depend on judge
            structured_avg = s.get("structured_metrics", {}).get("structured_avg")
            judge_score = judge.get("score", -1.0)
            if judge_score >= 0 and structured_avg is not None:
                s["disagreement"] = abs(judge_score - structured_avg)
            rejudged += 1
            logger.info(f"    → new score: {judge.get('score')}")
        else:
            kept += 1

        new_per_sample.append(s)

    logger.info(f"\nRejudged: {rejudged} | Kept: {kept}")

    # Recompute aggregates
    new_scores = aggregate(new_per_sample)

    # Update report
    report["per_sample"] = new_per_sample
    report["scores"] = new_scores
    report["metadata"]["rejudged_at"] = datetime.utcnow().isoformat()
    report["metadata"]["judge_model_after_rejudge"] = JUDGE_MODEL

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    logger.info(f"\n✓ Rewritten: {output_path}")
    logger.info(f"  Global avg_judge_score: {new_scores['global']['avg_judge_score']}")
    logger.info(f"  n_judge_failed: {new_scores['global']['n_judge_failed']}")
    logger.info(f"  Per-category: {new_scores['by_category']}")
    return report


def main():
    parser = argparse.ArgumentParser(description="Re-judge existing bench (corpus-agnostic).")
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--force", action="store_true",
                        help="Re-judge ALL samples (not just failed ones)")
    args = parser.parse_args()
    rejudge(args.input, args.output, force=args.force)


if __name__ == "__main__":
    main()
