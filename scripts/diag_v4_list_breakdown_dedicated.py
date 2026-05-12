"""
CH-45 Phase 0 — Bench V4 list 10q via DeepInfra Dedicated Qwen-72B.

Setter dans le container avant exécution :
  DEEPINFRA_RUNTIME_MODEL=fredpottier/qwen72b-runtime-v4
  LIST_COMPOSER_MODEL=fredpottier/qwen72b-runtime-v4

Output : data/router/v4_list_breakdown_dedicated.json
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
    print(f"Sample: {len(sample)} list questions (DEDICATED Qwen-72B 2× H100)")

    results = []
    for i, q in enumerate(sample, 1):
        qid = q["id"]
        question = q["question"]
        print(f"\n[{i}/{len(sample)}] [{qid}]")
        print(f"  Q: {question[:140]}")

        t0 = time.time()
        try:
            resp = requests.post(API, json={"question": question, "top_k_claims": 20}, timeout=300)
            wall_ms = int((time.time() - t0) * 1000)
            if resp.status_code != 200:
                print(f"  FAIL HTTP {resp.status_code}: {resp.text[:200]}")
                continue
            data = resp.json()
        except Exception as exc:
            print(f"  EXC {exc}")
            continue

        bd = data.get("latency_breakdown_ms") or {}
        print(f"  wall={wall_ms}ms | analyzer={bd.get('analyzer_ms')} | structurer={bd.get('structurer_ms')} | retry={bd.get('selfcorrector_retry_ms')} | composer={bd.get('composer_ms')}")
        results.append({"id": qid, "wall_ms": wall_ms, "breakdown": bd,
                        "regenerated": data.get("regenerated"),
                        "decision": data.get("decision")})

    print(f"\n=== AGGREGATE on {len(results)} valid (DEDICATED) ===")
    agg = defaultdict(list)
    for r in results:
        agg["wall"].append(r["wall_ms"])
        for k, v in (r["breakdown"] or {}).items():
            if isinstance(v, (int, float)) and v is not None:
                agg[k].append(v)

    def stats(arr):
        s = sorted(arr); n = len(s)
        if n == 0:
            return None
        return {"min": s[0], "p50": s[n // 2],
                "p95": s[max(0, min(n - 1, int(n * 0.95)))],
                "max": s[-1], "mean": sum(s) // n, "n": n}

    print(f"{'stage':<40} {'min':>8} {'p50':>8} {'p95':>8} {'max':>8} {'mean':>8}")
    for k in ["wall", "analyzer_ms", "rerouter_preview_retrieval_ms",
              "main_retrieval_ms", "structurer_ms", "composer_ms",
              "verifier_ms", "selfcorrector_retry_ms", "channel2_nli_ms"]:
        s = stats(agg.get(k, []))
        if s:
            print(f"{k:<40} {s['min']:>8} {s['p50']:>8} {s['p95']:>8} {s['max']:>8} {s['mean']:>8}")

    n_retries = sum(1 for r in results if r.get("regenerated"))
    print(f"\nSelfCorrector retry: {n_retries}/{len(results)} ({n_retries / max(len(results), 1) * 100:.0f}%)")

    out = Path("/app/data/router/v4_list_breakdown_dedicated.json")
    out.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nPersisted → {out}")


if __name__ == "__main__":
    main()
