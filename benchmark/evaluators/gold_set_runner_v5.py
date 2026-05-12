"""V5 Reading Agent gold-set runner — invokes run_agent() directly (no API).

Same schema as gold_set_runner.py output, so rejudge_only.py can score it.

Usage:
    python -m benchmark.evaluators.gold_set_runner_v5 \\
        --gold-set-path benchmark/questions/gold_set_sap_v1.json \\
        --output benchmark/results/gold_set_sap_v1_v5_baseline.json \\
        --max-iter 8

Corpus-agnostic: works with any gold-set + any set of Document Structures
present in /app/data/poc_a/structures.
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from datetime import datetime
from pathlib import Path

sys.path.insert(0, "/app/src")
sys.path.insert(0, "/app")

from knowbase.runtime_v5.reasoning_agent import run_agent
from knowbase.runtime_v5.reading_tools import list_doc_ids
from benchmark.evaluators.gold_set_runner import (
    exact_match_identifiers,
    citation_presence,
    aggregate,
)

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")


def evaluate_sample(item: dict, max_iter: int, available_docs: list[str]) -> dict:
    """Run V5 Reading Agent on one question + compute structured metrics."""
    qid = item.get("id")
    question = item.get("question")
    gt = item.get("ground_truth", {})
    ref = gt.get("answer", "")
    expected_ids = gt.get("exact_identifiers", [])
    expected_docs = gt.get("supporting_doc_ids", [])

    t0 = time.time()
    try:
        result = run_agent(
            question,
            available_doc_ids=available_docs,
            max_iterations=max_iter,
            verbose=False,
        )
        answer = result.get("answer", "")
        meta = {
            "n_iterations": result.get("n_iterations"),
            "stopped_reason": result.get("stopped_reason"),
            "tokens_total": result.get("tokens_total"),
        }
    except Exception as e:
        answer = ""
        meta = {"error": str(e)}
    latency_ms = int((time.time() - t0) * 1000)

    em = exact_match_identifiers(answer, expected_ids)
    cp = citation_presence(answer, expected_docs)
    parts = [m["score"] for m in (em, cp) if m.get("score") is not None]
    structured_avg = sum(parts) / len(parts) if parts else None

    return {
        "id": qid,
        "question": question,
        "primary_type": item.get("primary_type"),
        "reference_answer": ref,
        "osmosis_answer": answer,  # keep key for rejudge_only.py compat
        "latency_ms": latency_ms,
        "judge": {"score": -1.0, "error": "not_judged_yet"},
        "structured_metrics": {
            "exact_match_identifiers": em,
            "citation_presence": cp,
            "structured_avg": structured_avg,
        },
        "disagreement": None,
        "osmosis_meta": {"system": "OSMOSIS V5 Reading Agent", **meta},
    }


def main():
    parser = argparse.ArgumentParser(description="V5 Reading Agent gold-set runner.")
    parser.add_argument("--gold-set-path", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--max-iter", type=int, default=8)
    args = parser.parse_args()

    items = json.loads(args.gold_set_path.read_text(encoding="utf-8"))
    available_docs = list_doc_ids()
    logger.info(f"Loaded {len(items)} questions, V5 has {len(available_docs)} docs available")

    per_sample = []
    for i, item in enumerate(items, 1):
        logger.info(f"[{i}/{len(items)}] {item.get('id')} — {item.get('primary_type')}")
        r = evaluate_sample(item, args.max_iter, available_docs)
        per_sample.append(r)
        logger.info(f"  → latency={r['latency_ms']}ms, ans={len(r['osmosis_answer'])} chars, "
                    f"stopped={r['osmosis_meta'].get('stopped_reason')}")

    report = {
        "metadata": {
            "gold_set_path": str(args.gold_set_path),
            "system_under_test": "OSMOSIS V5 Reading Agent (CH-51)",
            "max_iter": args.max_iter,
            "available_docs_count": len(available_docs),
            "ran_at": datetime.utcnow().isoformat(),
        },
        "scores": {"global": {}, "by_category": {}},  # filled by rejudge_only
        "per_sample": per_sample,
    }

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    logger.info(f"\n✓ Written: {args.output} (NOT YET JUDGED — run rejudge_only.py)")


if __name__ == "__main__":
    main()
