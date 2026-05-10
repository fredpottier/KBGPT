"""
CH-44.b — Mini bench instrumenté sur 10 questions list V4 pour décomposer les 115s.

Sample 10 questions list du gold_set_v4. Pour chaque, appelle /api/runtime_v4/answer
et collecte le latency_breakdown_ms (analyzer/rerouter/retrieval/structurer/composer/...).

Output : agrégat moyen par stage + identification du goulet.
"""
from __future__ import annotations
import json
import random
import time
from collections import defaultdict
from pathlib import Path

import requests

API = "http://knowbase-app:8000/api/runtime_v4/answer"
GOLD = Path("/app/benchmark/questions/gold_set_v4.json")
SEED = 42


def main():
    rng = random.Random(SEED)
    gold = json.loads(GOLD.read_text(encoding="utf-8"))
    list_qs = [q for q in gold if q.get("primary_type") == "list"]
    rng.shuffle(list_qs)
    sample = list_qs[:10]
    print(f"Sample: {len(sample)} list questions")

    results = []
    for i, q in enumerate(sample, 1):
        qid = q["id"]
        question = q["question"]
        print(f"\n[{i}/{len(sample)}] [{qid}]")
        print(f"  Q: {question[:150]}")

        t0 = time.time()
        try:
            resp = requests.post(API, json={"question": question, "top_k_claims": 20}, timeout=300)
            wall_ms = int((time.time() - t0) * 1000)
            if resp.status_code != 200:
                print(f"  FAIL HTTP {resp.status_code}")
                continue
            data = resp.json()
        except Exception as exc:
            print(f"  EXC {exc}")
            continue

        breakdown = data.get("latency_breakdown_ms") or {}
        decision = data.get("decision")
        regen = data.get("regenerated")
        primary = data.get("primary_type")
        routing = data.get("routing_decision")

        print(f"  wall={wall_ms}ms | decision={decision} | regen={regen} | route={routing}")
        print(f"  breakdown:")
        for k, v in breakdown.items():
            if v is not None:
                print(f"    {k:<40} = {v}")
        results.append({
            "id": qid, "wall_ms": wall_ms, "decision": decision, "regenerated": regen,
            "primary_type": primary, "routing": routing, "breakdown": breakdown,
        })

    # Aggregate
    print(f"\n=== AGGREGATE on {len(results)} valid ===")
    agg = defaultdict(list)
    for r in results:
        agg["wall"].append(r["wall_ms"])
        for k, v in (r["breakdown"] or {}).items():
            if isinstance(v, (int, float)) and v is not None:
                agg[k].append(v)

    def stats(arr):
        s = sorted(arr)
        n = len(s)
        if n == 0:
            return None
        p50 = s[n // 2]
        p95 = s[max(0, min(n - 1, int(n * 0.95)))]
        return {"min": s[0], "p50": p50, "p95": p95, "max": s[-1], "mean": sum(s) // n, "n": n}

    print(f"{'stage':<40} {'min':>8} {'p50':>8} {'p95':>8} {'max':>8} {'mean':>8}")
    for k in ["wall", "analyzer_ms", "rerouter_preview_retrieval_ms", "rerouter_decision_ms",
              "main_retrieval_ms", "structurer_ms", "composer_ms", "verifier_ms",
              "selfcorrector_retry_ms", "channel2_nli_ms"]:
        s = stats(agg.get(k, []))
        if s:
            print(f"{k:<40} {s['min']:>8} {s['p50']:>8} {s['p95']:>8} {s['max']:>8} {s['mean']:>8}")

    # Retry rate
    n_retries = sum(1 for r in results if r.get("regenerated"))
    print(f"\nSelfCorrector retry triggered: {n_retries}/{len(results)} ({n_retries/max(len(results),1)*100:.0f}%)")

    out = Path("/app/data/router/v4_list_breakdown.json")
    out.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nPersisted → {out}")


if __name__ == "__main__":
    main()
