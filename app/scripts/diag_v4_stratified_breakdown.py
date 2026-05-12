"""
CH-46 diag — bench micro stratifié 30q (6q × 5 types) post-CH46 sur runtime_v4.

Sample équilibré par primary_type pour mesurer la latence par type :
  list, factual, temporal, comparison, causal

Output : data/router/v4_stratified_breakdown_CH46.json + agrégat console par type.

Usage : docker exec knowbase-app python /app/scripts/diag_v4_stratified_breakdown.py [--n_per_type 6]
"""
from __future__ import annotations
import argparse
import json
import random
import time
from collections import defaultdict
from pathlib import Path

import requests

API = "http://knowbase-app:8000/api/runtime_v4/answer"
GOLD = Path("/app/benchmark/questions/gold_set_v4.json")
TYPES = ["list", "factual", "temporal", "comparison", "causal"]
SEED = 42


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--n_per_type", type=int, default=6)
    p.add_argument("--out", type=str, default="/app/data/router/v4_stratified_breakdown_CH46.json")
    args = p.parse_args()

    rng = random.Random(SEED)
    gold = json.loads(GOLD.read_text(encoding="utf-8"))
    by_type: dict[str, list] = defaultdict(list)
    for q in gold:
        t = q.get("primary_type")
        if t in TYPES:
            by_type[t].append(q)

    sample: list[dict] = []
    for t in TYPES:
        pool = by_type.get(t, [])
        rng.shuffle(pool)
        sample.extend(pool[: args.n_per_type])

    print(f"Sample stratifié : {len(sample)} questions ({args.n_per_type}/type sur {len(TYPES)} types)")
    for t in TYPES:
        print(f"  {t}: {len([q for q in sample if q.get('primary_type') == t])}")

    results = []
    for i, q in enumerate(sample, 1):
        qid = q["id"]
        ptype = q.get("primary_type")
        question = q["question"]
        print(f"\n[{i}/{len(sample)}] [{qid}] type={ptype}")
        print(f"  Q: {question[:140]}")

        t0 = time.time()
        try:
            resp = requests.post(API, json={"question": question, "top_k_claims": 12}, timeout=300)
            wall_ms = int((time.time() - t0) * 1000)
            if resp.status_code != 200:
                print(f"  FAIL HTTP {resp.status_code}")
                results.append({"id": qid, "primary_type": ptype, "wall_ms": wall_ms,
                                "error": f"http_{resp.status_code}"})
                continue
            data = resp.json()
        except requests.Timeout:
            wall_ms = int((time.time() - t0) * 1000)
            print(f"  TIMEOUT after {wall_ms}ms")
            results.append({"id": qid, "primary_type": ptype, "wall_ms": wall_ms, "error": "timeout"})
            continue
        except Exception as exc:
            print(f"  EXC {exc}")
            results.append({"id": qid, "primary_type": ptype, "wall_ms": int((time.time() - t0) * 1000),
                            "error": str(exc)})
            continue

        bd = data.get("latency_breakdown_ms") or {}
        decision = data.get("decision")
        regen = data.get("regenerated")
        route = data.get("routing_decision")
        answer = data.get("answer") or ""
        doc_ids = data.get("doc_ids_cited") or []
        faithfulness_score = data.get("faithfulness_score")
        faithfulness_verdict = data.get("faithfulness_verdict")
        gt = q.get("ground_truth") or {}
        print(f"  wall={wall_ms}ms | decision={decision} | regen={regen} | route={route}")
        print(f"  analyzer={bd.get('analyzer_ms')} structurer={bd.get('structurer_ms')} composer={bd.get('composer_ms')} retry={bd.get('selfcorrector_retry_ms')} ch2={bd.get('channel2_nli_ms')}")
        results.append({
            "id": qid, "primary_type": ptype, "language": q.get("language"),
            "question": question,
            "wall_ms": wall_ms, "breakdown": bd,
            "decision": decision, "regenerated": regen, "routing": route,
            "answer": answer, "doc_ids_cited": doc_ids,
            "faithfulness_score": faithfulness_score,
            "faithfulness_verdict": faithfulness_verdict,
            "ground_truth": {
                "answer": gt.get("ground_truth_answer") or gt.get("answer") or "",
                "answerability": gt.get("answerability"),
                "false_premise": gt.get("false_premise"),
                "exact_identifiers": gt.get("exact_identifiers") or [],
                "supporting_doc_ids": gt.get("supporting_doc_ids") or [],
            },
        })

    # Aggregate by type
    print(f"\n=== AGGREGATE BY TYPE ===")
    print(f"{'type':<12} {'n':>3} {'min':>7} {'p50':>7} {'p95':>7} {'max':>7} {'mean':>7} {'analyzer':>9} {'structurer':>11} {'composer':>9} {'retry%':>7}")

    def stats(arr):
        s = sorted([x for x in arr if x is not None])
        n = len(s)
        if n == 0:
            return None
        return {"min": s[0], "p50": s[n // 2], "p95": s[max(0, min(n - 1, int(n * 0.95)))],
                "max": s[-1], "mean": sum(s) // n, "n": n}

    for t in TYPES:
        rs = [r for r in results if r.get("primary_type") == t and "error" not in r]
        walls = [r["wall_ms"] for r in rs]
        analyzers = [(r.get("breakdown") or {}).get("analyzer_ms") for r in rs]
        structurers = [(r.get("breakdown") or {}).get("structurer_ms") for r in rs]
        composers = [(r.get("breakdown") or {}).get("composer_ms") for r in rs]
        retries = sum(1 for r in rs if r.get("regenerated"))
        s = stats(walls)
        if s is None:
            print(f"{t:<12} {0:>3} (none)")
            continue
        a = stats(analyzers); st = stats(structurers); co = stats(composers)
        print(f"{t:<12} {s['n']:>3} {s['min']:>7} {s['p50']:>7} {s['p95']:>7} {s['max']:>7} {s['mean']:>7} "
              f"{(a['mean'] if a else 0):>9} {(st['mean'] if st else 0):>11} "
              f"{(co['mean'] if co else 0):>9} {(retries / max(s['n'], 1) * 100):>6.0f}%")

    # Errors
    errors = [r for r in results if "error" in r]
    if errors:
        print(f"\n=== ERRORS ({len(errors)}) ===")
        for r in errors:
            print(f"  [{r['id']}] type={r.get('primary_type')}: {r.get('error')}")

    # Persist
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nPersisted → {out}")


if __name__ == "__main__":
    main()
