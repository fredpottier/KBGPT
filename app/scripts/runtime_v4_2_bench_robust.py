"""Bench non-régression P1.7 — Robust 120q sur /api/runtime_v4_2/answer.

Mesure :
  - Multi-view scorer (exact/fuzzy/semantic) pour chaque réponse
  - Distribution layer (layer0 / layer1_temporal_active)
  - 3 catégories abstain (Amendment 1)
  - Latence p50 / p95 par catégorie
  - Decision distribution

Compare aux gates ADR Phase 1 :
  - Robust global ≥ 0.45 (V4.1 baseline = 0.403)
  - false_abstain_rate (`misaligned_but_answerable`) ≤ 5%
  - p95 latency ≤ 12s
  - Aucune régression > 0.05pp factual/list/unanswerable

Output : data/audit/runtime_v4_2_p1_bench_robust_<timestamp>.json

Usage :
    docker exec knowbase-app python /app/app/scripts/runtime_v4_2_bench_robust.py [--workers 4] [--limit 120]
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import statistics
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import requests

API = "http://knowbase-app:8000/api/runtime_v4_2/answer"
HEALTH = "http://knowbase-app:8000/api/runtime_v4_2/health"
QUESTIONS_PATH = Path("/app/benchmark/questions/aero_t6_robustness.json")


def map_expected_behavior(behavior: str) -> str:
    return {
        "answer": "answerable",
        "abstain": "unanswerable",
        "reject_premise": "unanswerable",  # On considère false_premise comme abstain-correct
    }.get(behavior, "answerable")


def call_api(question: str, top_k: int = 12, timeout: int = 120) -> dict:
    t0 = time.time()
    try:
        r = requests.post(API, json={"question": question, "top_k_claims": top_k}, timeout=timeout)
        wall = int((time.time() - t0) * 1000)
        if r.status_code != 200:
            return {"error": f"HTTP {r.status_code}", "_wall_ms": wall}
        d = r.json()
        d["_wall_ms"] = wall
        return d
    except Exception as exc:  # noqa: BLE001
        return {"error": str(exc), "_wall_ms": int((time.time() - t0) * 1000)}


def score_one(api_result: dict, question_meta: dict, scorer) -> dict:
    """Score multi-view + abstain category sur 1 réponse."""
    from benchmark.evaluators.abstain_categorizer import categorize

    answer = api_result.get("answer", "")
    decision = api_result.get("decision", "ABSTAIN")
    gold = question_meta.get("ground_truth") or {}
    gold_answer = gold.get("correct_fact") or gold.get("evidence_claim") or ""
    gold_answerability = map_expected_behavior(gold.get("expected_behavior", "answer"))

    score = scorer(
        answer=answer,
        gold_answer=gold_answer,
        expected_identifiers=None,  # aero_t6 ne fournit pas identifiers explicites
        list_items_expected=None,
        answerability=gold_answerability,
        decision=decision,
    )

    abstain_cat = categorize(decision=decision, gold_answerability=gold_answerability)

    return {
        "id": question_meta.get("id"),
        "category": question_meta.get("category"),
        "expected_behavior": gold.get("expected_behavior"),
        "gold_answerability": gold_answerability,
        "decision": decision,
        "layer": api_result.get("layer", "?"),
        "abstention_reason": api_result.get("abstention_reason"),
        "abstain_category_runtime": api_result.get("abstain_category"),
        "abstain_category_postdoc": abstain_cat,
        "answer_excerpt": (answer or "")[:300],
        "score_exact": score.exact,
        "score_fuzzy": score.fuzzy,
        "score_semantic": score.semantic,
        "score_best": score.best,
        "dominant_signal": score.dominant_signal,
        "abstain_reward_applied": score.abstain_reward_applied,
        "wall_ms": api_result.get("_wall_ms"),
        "latency_breakdown_ms": api_result.get("latency_breakdown_ms"),
        "qa_alignment": api_result.get("qa_alignment"),
        "qa_confidence": api_result.get("qa_confidence"),
        "n_chunks_used": api_result.get("n_chunks_used"),
        "doc_ids_cited": api_result.get("doc_ids_cited") or [],
        "error": api_result.get("error"),
    }


def aggregate(rows: list[dict]) -> dict:
    n = len(rows)
    valid = [r for r in rows if not r.get("error")]
    if not valid:
        return {"n": n, "n_valid": 0, "error": "no_valid_results"}

    means = {
        "score_exact": _mean(r["score_exact"] for r in valid),
        "score_fuzzy": _mean(r["score_fuzzy"] for r in valid),
        "score_semantic": _mean(r["score_semantic"] for r in valid),
        "score_best": _mean(r["score_best"] for r in valid),
    }
    by_cat: dict[str, dict] = {}
    for r in valid:
        cat = r["category"] or "unknown"
        if cat not in by_cat:
            by_cat[cat] = {"rows": []}
        by_cat[cat]["rows"].append(r)
    by_cat_summary = {}
    for k, v in by_cat.items():
        rs = v["rows"]
        by_cat_summary[k] = {
            "n": len(rs),
            "score_best_mean": _mean(r["score_best"] for r in rs),
            "score_exact_mean": _mean(r["score_exact"] for r in rs),
            "score_fuzzy_mean": _mean(r["score_fuzzy"] for r in rs),
            "score_semantic_mean": _mean(r["score_semantic"] for r in rs),
            "decision_answer": sum(1 for r in rs if r["decision"] == "ANSWER"),
            "decision_abstain": sum(1 for r in rs if r["decision"] == "ABSTAIN"),
            "abstain_reward_applied": sum(1 for r in rs if r["abstain_reward_applied"]),
            "wall_ms_p50": _percentile([r["wall_ms"] for r in rs if r["wall_ms"]], 0.5),
            "wall_ms_p95": _percentile([r["wall_ms"] for r in rs if r["wall_ms"]], 0.95),
        }
    layer_counts: dict[str, int] = {}
    abstain_counts: dict[str, int] = {}
    dominant_counts: dict[str, int] = {}
    for r in valid:
        layer_counts[r["layer"]] = layer_counts.get(r["layer"], 0) + 1
        abstain_counts[r["abstain_category_postdoc"]] = abstain_counts.get(r["abstain_category_postdoc"], 0) + 1
        dominant_counts[r["dominant_signal"]] = dominant_counts.get(r["dominant_signal"], 0) + 1

    latencies = [r["wall_ms"] for r in valid if r["wall_ms"]]
    return {
        "n": n,
        "n_valid": len(valid),
        "n_errors": n - len(valid),
        "global": {
            "means": means,
            "wall_ms_p50": _percentile(latencies, 0.5),
            "wall_ms_p95": _percentile(latencies, 0.95),
            "wall_ms_max": max(latencies) if latencies else None,
            "wall_ms_mean": int(_mean(latencies)) if latencies else None,
        },
        "layer_distribution": layer_counts,
        "abstain_distribution": abstain_counts,
        "dominant_distribution": dominant_counts,
        "false_abstain_rate": round(
            abstain_counts.get("misaligned_but_answerable", 0) / max(1, len(valid)), 4
        ),
        "by_category": by_cat_summary,
    }


def _mean(it) -> float:
    values = list(it)
    return round(sum(values) / len(values), 4) if values else 0.0


def _percentile(values: list[int], q: float):
    if not values:
        return None
    s = sorted(values)
    idx = int(round(q * (len(s) - 1)))
    return s[max(0, min(idx, len(s) - 1))]


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--workers", type=int, default=4)
    p.add_argument("--limit", type=int, default=None)
    p.add_argument("--top_k", type=int, default=12)
    p.add_argument("--out", type=str, default=None)
    args = p.parse_args()

    print("Health check...")
    h = requests.get(HEALTH, timeout=10).json()
    print(f"  {json.dumps(h, indent=2)[:400]}")

    questions = json.loads(QUESTIONS_PATH.read_text(encoding="utf-8"))
    if args.limit:
        questions = questions[: args.limit]
    print(f"\nLoaded {len(questions)} questions from {QUESTIONS_PATH.name}")

    # Lazy import scorer (warmup model)
    from benchmark.evaluators.multi_view_scorer import multi_view_score
    print("Warming up multi-view scorer (e5 embedder)...")
    _ = multi_view_score("warmup", "warmup")
    print("  ok")

    timestamp = dt.datetime.utcnow().strftime("%Y-%m-%d_%H%M%S")
    out_path = Path(args.out or f"/app/data/audit/runtime_v4_2_p1_bench_robust_{timestamp}.json")
    out_path.parent.mkdir(parents=True, exist_ok=True)

    t_start = time.time()
    rows: list[dict] = []
    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        futures = {
            ex.submit(call_api, q["question"], args.top_k): q for q in questions
        }
        for i, fut in enumerate(as_completed(futures), 1):
            qmeta = futures[fut]
            try:
                api_res = fut.result()
            except Exception as exc:  # noqa: BLE001
                api_res = {"error": str(exc), "_wall_ms": 0}
            row = score_one(api_res, qmeta, multi_view_score)
            rows.append(row)
            print(
                f"  [{i:3d}/{len(questions)}] {qmeta['id']:25s} | "
                f"cat={qmeta['category']:18s} | dec={row['decision']:7s} | "
                f"layer={row['layer']:24s} | best={row['score_best']:.3f} | "
                f"wall={row['wall_ms']}ms"
            )

    total_wall = int(time.time() - t_start)
    agg = aggregate(rows)
    payload = {
        "timestamp": timestamp,
        "questions_path": str(QUESTIONS_PATH),
        "n_questions": len(questions),
        "workers": args.workers,
        "top_k": args.top_k,
        "wall_total_seconds": total_wall,
        "aggregate": agg,
        "rows": rows,
    }
    out_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")

    print(f"\nWritten {out_path}")
    print(f"Total wall: {total_wall}s")
    print(f"Global score_best mean: {agg['global']['means']['score_best']}")
    print(f"Latency p50/p95: {agg['global']['wall_ms_p50']}ms / {agg['global']['wall_ms_p95']}ms")
    print(f"False abstain rate: {agg['false_abstain_rate']}")
    print(f"Layer distribution: {agg['layer_distribution']}")
    print(f"Abstain distribution: {agg['abstain_distribution']}")


if __name__ == "__main__":
    main()
