"""Bench A3.8 — BRAS RAG CLASSIQUE (baseline comparatif vs OSMOSIS runtime_v6).

Objectif (demande Fred 29/05/2026) : mesurer si OSMOSIS répond MIEUX qu'un système
RAG vanille sur le MÊME gold-set, avec les MÊMES métriques et le MÊME LLM de synthèse.
C'est le test qui légitime (ou non) la complexité KG + Parse + Plan + Evaluate.

DIFFÉRENCE UNIQUE vs OSMOSIS : le retrieval.
    - OSMOSIS : KG (Neo4j claims) + Parse/Plan multi-aspect + RRF + cross-encoder + Evaluate.
    - RAG classique (ici) : embed question → Qdrant top-K chunks bruts → synthèse directe.
      AUCUN KG, AUCUN planner, AUCUN evaluate, AUCUN re-rank custom. Juste
      "retrieve passages / generate answer", l'archi RAG standard de la littérature.

IDENTIQUE des deux côtés (pour un comparatif honnête) :
    - gold-set 50q (benchmark/questions/gold_set_a38_50q.json)
    - LLM de synthèse (Novita deepseek-v3.2 via TaskType.LONG_TEXT_SUMMARY)
    - métriques déterministes (exact_id_recall + abstention_correct) — décisionnelles
    - juge LLM recalibré (orienté rappel) — diagnostic secondaire bruité
    - corpus (collection Qdrant knowbase_chunks_v2, même tenant)

Le run JSON produit a la MÊME structure que bench_a38_runtime_v6 → réutilisable par
le frontend et les scripts de comparaison.

Usage :
    docker exec knowbase-app sh -c 'cd /app && python scripts/bench_a38_classic_rag.py'
    docker exec knowbase-app sh -c 'cd /app && python scripts/bench_a38_classic_rag.py --limit 5'
    docker exec knowbase-app sh -c 'cd /app && python scripts/bench_a38_classic_rag.py --top-k 12'
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import logging
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("bench_rag")

# Réutilise tout le harness du bench OSMOSIS (gold-set, métriques, juge, agrégation)
_spec = importlib.util.spec_from_file_location(
    "bench_a38_runtime_v6", str(Path(__file__).parent / "bench_a38_runtime_v6.py")
)
bench = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(bench)


# ============================================================================
# Pipeline RAG classique — EXTRAIT vers le package (05/06/2026) pour être
# réutilisé par l'API (toggle A/B use_kg=false du chat). Source unique :
# src/knowbase/runtime_a3/classic_rag.py (prompt, classe, abstention).
# ============================================================================

from knowbase.runtime_a3.classic_rag import ClassicRAG  # noqa: E402


# Marqueurs d'abstention spécifiques au bras RAG (en plus de ceux du bench OSMOSIS)
_RAG_ABSTENTION_MARKERS = (
    "insufficient_context",
    "does not contain",
    "no information",
    "cannot be answered",
    "not supported by the context",
    "not contained in the context",
)


def _rag_is_abstention(answer: str) -> bool:
    if not answer:
        return False
    low = answer.lower()
    if low.strip().startswith("insufficient_context"):
        return True
    # Réutilise aussi les marqueurs génériques du bench OSMOSIS (FR + EN)
    if any(m.lower() in low for m in bench._ABSTENTION_MARKERS):
        return True
    return any(m in low for m in _RAG_ABSTENTION_MARKERS)


# ============================================================================
# ============================================================================
# Bench runner (mêmes métriques que le bench OSMOSIS)
# ============================================================================


def run_bench_rag(rag: ClassicRAG, gold_path: Path, limit: Optional[int]) -> List[Dict[str, Any]]:
    with open(gold_path, "r", encoding="utf-8") as f:
        questions = json.load(f)
    if limit:
        questions = questions[:limit]
    logger.info("Bench RAG: %d questions", len(questions))

    results: List[Dict[str, Any]] = []
    for i, q in enumerate(questions, 1):
        logger.info("[RAG %d/%d] type=%s id=%s", i, len(questions),
                    q.get("primary_type"), q.get("id"))
        run = rag.answer(q["question"])
        gt = q.get("ground_truth", {})
        gt_answer = gt.get("answer", "")
        if gt_answer and run.get("ok"):
            judge = bench.llm_judge(
                q["question"], run["answer_text"], gt_answer,
                answerability=gt.get("answerability", "answerable"),
                false_premise=gt.get("false_premise", False),
                mode=run.get("mode"),
            )
        else:
            judge = {"score": 0.0, "reasoning": "no_ground_truth_or_run_failed"}
        det = bench.deterministic_metrics(q, run)
        results.append({
            "id": q["id"],
            "primary_type": q.get("primary_type"),
            "language": q.get("language"),
            "question": q["question"],
            "ground_truth_answer": gt_answer,
            "run": run,
            "judge_score": judge["score"],
            "judge_reasoning": judge["reasoning"],
            "judge_attempts": judge.get("attempts"),
            "judge_used_fallback": judge.get("used_fallback", False),
            "exact_id_recall": det["exact_id_recall"],
            "n_expected_ids": det["n_expected_ids"],
            "abstention_correct": det["abstention_correct"],
        })
    return results


def main():
    parser = argparse.ArgumentParser(description="A3.8 bench RAG classique (baseline)")
    parser.add_argument("--gold-50q", type=Path,
                        default=Path("benchmark/questions/gold_set_a38_50q.json"))
    parser.add_argument("--output-dir", type=Path,
                        default=Path("data/benchmark/a38_classic_rag"))
    parser.add_argument("--collection", default="knowbase_chunks_v2")
    parser.add_argument("--top-k", type=int, default=12)
    parser.add_argument("--score-threshold", type=float, default=None)
    parser.add_argument("--limit", type=int, default=None)
    args = parser.parse_args()

    rag = ClassicRAG(
        collection=args.collection,
        top_k=args.top_k,
        score_threshold=args.score_threshold,
    )

    t0 = time.perf_counter()
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")

    results = run_bench_rag(rag, args.gold_50q, args.limit)
    agg = bench.aggregate_50q(results) if results else {}
    total_duration = time.perf_counter() - t0

    # Rapport (même format que bench OSMOSIS, sans gates CP)
    print("\n" + "=" * 70)
    print(f"A3.8 BENCH — BRAS RAG CLASSIQUE (baseline) — {timestamp}")
    print(f"  retrieval = Qdrant {args.collection} top-{args.top_k} (vector seul, no KG)")
    print("=" * 70)
    if agg:
        print(f"\n  n={agg['n_total']} run_ok={agg['n_run_ok']} failed={agg['n_run_failed']}")
        eir = agg.get("exact_id_recall_mean")
        if eir is not None:
            print(f"  ★ exact_id_recall : {eir:.3f}  (n={agg['n_with_expected_ids']} q avec identifiants) [DÉTERMINISTE]")
        print(f"  ★ abstention_correct_rate : {agg.get('abstention_correct_rate', 0):.1%} [DÉTERMINISTE]")
        if agg.get("exact_id_recall_per_type"):
            parts = [f"{t}={d['mean']:.2f}(n{d['n']})"
                     for t, d in sorted(agg["exact_id_recall_per_type"].items())]
            print(f"    exact_id_recall/type : {', '.join(parts)}")
        print(f"  C1 (LLM-judge, bruité) : {agg['C1_mean']:.3f}  "
              f"[valid={agg['n_judge_valid']}/{agg['n_total']}, "
              f"judge_failed={agg['n_judge_failed']} ({agg['judge_failure_rate']:.1%})]")
        print(f"  Latency : p50={agg['latency_p50_s']:.1f}s p95={agg['latency_p95_s']:.1f}s")
        print("  Per type (juge LLM):")
        for t, st in sorted(agg["per_type"].items()):
            print(f"    {t:20s} n={st['n']:2d} mean={st['mean']:.3f}")

    print(f"\nTotal duration: {total_duration:.1f}s")

    args.output_dir.mkdir(parents=True, exist_ok=True)
    out_file = args.output_dir / f"run_{timestamp}.json"
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump({
            "timestamp": timestamp,
            "arm": "classic_rag",
            "config": {
                "collection": args.collection,
                "top_k": args.top_k,
                "score_threshold": args.score_threshold,
                "synthesis_task": "LONG_TEXT_SUMMARY",
            },
            "total_duration_s": total_duration,
            "agg_50q": agg,
            "results_50q": results,
        }, f, ensure_ascii=False, indent=2, default=str)
    print(f"\nResults: {out_file}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
