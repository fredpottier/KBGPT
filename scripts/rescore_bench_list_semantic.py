#!/usr/bin/env python3
"""
Rescoring du bench list Tranche 1 avec matcher embedding cosine sim.

Charge `data/benchmark/calibration/bench_list_tranche1.json` (résultat
du bench live) et recalcule item_recall / item_precision / item_f1 en
remplaçant le matcher token-overlap strict par un matcher e5 cosine ≥
threshold (défaut 0.85). e5 est multilingue → robuste aux paraphrases
et au cross-lingual FR↔EN.

Pas d'appel pipeline — uniquement lecture des per_sample.predicted_labels
et expected_labels déjà persistés.

Usage (dans le container app où l'embedder est déjà chargé) :
  docker cp scripts/rescore_bench_list_semantic.py knowbase-app:/app/scripts/
  docker exec knowbase-app python /app/scripts/rescore_bench_list_semantic.py
  docker exec knowbase-app python /app/scripts/rescore_bench_list_semantic.py --threshold 0.80
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("rescore")

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if (PROJECT_ROOT / "src").exists():
    sys.path.insert(0, str(PROJECT_ROOT / "src"))

INPUT_PATH = PROJECT_ROOT / "data" / "benchmark" / "calibration" / "bench_list_tranche1.json"
OUTPUT_PATH = PROJECT_ROOT / "data" / "benchmark" / "calibration" / "bench_list_tranche1_semantic.json"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--threshold", type=float, default=0.85,
                        help="Cosine similarity threshold (default 0.85)")
    args = parser.parse_args()

    if not INPUT_PATH.exists():
        logger.error("Input not found: %s — run bench_list_tranche1.py first", INPUT_PATH)
        return 1
    data = json.loads(INPUT_PATH.read_text(encoding="utf-8"))
    samples = data.get("per_sample", [])
    logger.info("Loaded %d samples", len(samples))

    # Load embedder
    from knowbase.common.clients.shared_clients import get_sentence_transformer
    from knowbase.config.settings import get_settings
    settings = get_settings()
    emb = get_sentence_transformer(settings.embeddings_model, cache_folder=str(settings.hf_home))
    logger.info("Embedder loaded")

    def cosine_match(pred_set, exp_set, threshold):
        pred = list(pred_set)
        exp = list(exp_set)
        if not pred or not exp:
            return 0, 0
        pred_vecs = emb.encode([f"passage: {p}" for p in pred], normalize_embeddings=True)
        exp_vecs = emb.encode([f"passage: {e}" for e in exp], normalize_embeddings=True)
        matched_pred = set()
        matched_exp = set()
        for i, ev in enumerate(exp_vecs):
            best = 0.0
            best_j = -1
            for j, pv in enumerate(pred_vecs):
                s = float(sum(a * b for a, b in zip(ev, pv)))
                if s > best:
                    best, best_j = s, j
            if best >= threshold and best_j >= 0:
                matched_exp.add(i)
                matched_pred.add(best_j)
        return len(matched_exp), len(matched_pred)

    # Recompute per sample
    new_metrics = []
    for s in samples:
        pred = set(s.get("predicted_labels") or [])
        exp = set(s.get("expected_labels") or [])
        if not exp or not pred:
            new_metrics.append({**s, "semantic_recall": None, "semantic_precision": None, "semantic_f1": None})
            continue
        n_match_exp, n_match_pred = cosine_match(pred, exp, args.threshold)
        recall = n_match_exp / len(exp) if exp else None
        precision = n_match_pred / len(pred) if pred else None
        f1 = (2 * precision * recall / (precision + recall)) if (precision and recall and (precision + recall) > 0) else None
        new_metrics.append({
            **s,
            "semantic_recall": recall,
            "semantic_precision": precision,
            "semantic_f1": f1,
            "n_match_exp_semantic": n_match_exp,
        })

    # Aggregates
    def _safe_mean(vals):
        vals = [v for v in vals if v is not None]
        return sum(vals) / len(vals) if vals else None

    summary = data.get("summary", {})
    summary["semantic_threshold"] = args.threshold
    summary["item_recall_mean_semantic"] = _safe_mean([m.get("semantic_recall") for m in new_metrics])
    summary["item_precision_mean_semantic"] = _safe_mean([m.get("semantic_precision") for m in new_metrics])
    summary["item_f1_mean_semantic"] = _safe_mean([m.get("semantic_f1") for m in new_metrics])

    out = {
        **data,
        "summary": summary,
        "per_sample": new_metrics,
        "rescored_at": __import__("time").strftime("%Y-%m-%dT%H:%M:%SZ", __import__("time").gmtime()),
    }
    OUTPUT_PATH.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    logger.info("Persisted rescored bench → %s", OUTPUT_PATH)

    print()
    print(f"=== RESCORING SEMANTIC (threshold {args.threshold}) ===")
    print(f"  item_recall_mean (strict)   = {summary.get('item_recall_mean'):.3f}")
    print(f"  item_recall_mean (semantic) = {summary['item_recall_mean_semantic']:.3f}  (vs gate 0.65)")
    print(f"  item_f1_mean (strict)       = {summary.get('item_f1_mean'):.3f}")
    print(f"  item_f1_mean (semantic)     = {summary['item_f1_mean_semantic']:.3f}")
    print(f"  item_precision_mean (sem)   = {summary['item_precision_mean_semantic']:.3f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
