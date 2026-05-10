"""
CH-44 Étape 1 — Audit latence V3 vs V4 sur sample 20q stratifié.

Mesure :
  - V3 endpoint /api/runtime_v3/answer (baseline 15-35s)
  - V4 endpoint /api/runtime_v4/answer (suspect 30-90s)
  - Décomposition V4 (latency_breakdown_ms si exposé)

Sample : 20 questions du gold_set_v4 stratifiées par primary_type.

Usage :
  docker exec knowbase-app python /app/scripts/audit_latency_v3_vs_v4.py
"""
from __future__ import annotations
import json
import random
import time
from collections import defaultdict
from pathlib import Path

import requests

API = "http://knowbase-app:8000"
GOLD = Path("/app/benchmark/questions/gold_set_v4.json")
OUT_PATH = Path("/app/data/router/latency_audit_v3_vs_v4.json")

SEED = 42
QUOTA = {
    "factual": 4,
    "list": 4,
    "temporal": 4,
    "comparison": 3,
    "causal": 3,
    "unanswerable": 1,
    "false_premise": 1,
}


def load_sample():
    rng = random.Random(SEED)
    qs = json.loads(GOLD.read_text(encoding="utf-8"))
    by_type: dict[str, list] = defaultdict(list)
    for q in qs:
        by_type[q.get("primary_type") or "?"].append(q)
    out = []
    for t, n in QUOTA.items():
        items = by_type.get(t, [])
        rng.shuffle(items)
        out.extend(items[:n])
    return out


def call_endpoint(version: str, question: str, top_k: int = 15, timeout: int = 240) -> dict:
    path = f"/api/runtime_{version}/answer"
    payload = {"question": question, "top_k_claims": top_k}
    t0 = time.time()
    try:
        resp = requests.post(f"{API}{path}", json=payload, timeout=timeout)
        wall_ms = int((time.time() - t0) * 1000)
        if resp.status_code != 200:
            return {"version": version, "wall_ms": wall_ms, "error": f"HTTP {resp.status_code}: {resp.text[:200]}"}
        data = resp.json()
        return {
            "version": version,
            "wall_ms": wall_ms,
            "decision": data.get("decision"),
            "answer_len": len(data.get("answer") or ""),
            "n_chunks_retrieved": data.get("n_chunks_retrieved"),
            "n_doc_ids_cited": len(data.get("doc_ids_cited") or []),
            "regenerated": data.get("regenerated"),
            "faithfulness_score": data.get("faithfulness_score"),
            "faithfulness_verdict": data.get("faithfulness_verdict"),
            "latency_breakdown_ms": data.get("latency_breakdown_ms") or {},
            # V4-specific
            "primary_type": data.get("primary_type"),
            "routing_decision": data.get("routing_decision"),
            "rerouter_promoted": data.get("rerouter_promoted"),
        }
    except Exception as exc:
        wall_ms = int((time.time() - t0) * 1000)
        return {"version": version, "wall_ms": wall_ms, "error": str(exc)[:200]}


def main():
    sample = load_sample()
    print(f"Sample: {len(sample)} questions")

    results = []
    for i, q in enumerate(sample, 1):
        qid = q["id"]
        question = q["question"]
        ptype = q.get("primary_type")
        print(f"\n[{i}/{len(sample)}] [{qid}] type={ptype}")
        print(f"  Q: {question[:120]}")

        # V3 first
        v3 = call_endpoint("v3", question)
        print(f"  V3 wall = {v3['wall_ms']}ms | err={v3.get('error', 'no')[:60]}")

        # V4 second
        v4 = call_endpoint("v4", question)
        print(f"  V4 wall = {v4['wall_ms']}ms | route={v4.get('routing_decision')} | err={v4.get('error', 'no')[:60]}")

        delta = v4["wall_ms"] - v3["wall_ms"]
        ratio = v4["wall_ms"] / max(v3["wall_ms"], 1)
        print(f"  Δ V4-V3 = +{delta}ms ({ratio:.2f}×)")

        results.append({
            "id": qid,
            "primary_type": ptype,
            "language": q.get("language"),
            "question": question[:200],
            "v3": v3,
            "v4": v4,
            "delta_ms": delta,
            "ratio": ratio,
        })

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n=== AGGREGATE ===")
    valid = [r for r in results if not r["v3"].get("error") and not r["v4"].get("error")]
    print(f"valid: {len(valid)}/{len(results)}")
    if valid:
        v3_times = sorted(r["v3"]["wall_ms"] for r in valid)
        v4_times = sorted(r["v4"]["wall_ms"] for r in valid)
        n = len(v3_times)
        def p(arr, q):
            return arr[max(0, min(n - 1, int(q / 100 * n)))]
        print(f"V3 ms : p50={p(v3_times, 50)} | p95={p(v3_times, 95)} | mean={sum(v3_times) // n}")
        print(f"V4 ms : p50={p(v4_times, 50)} | p95={p(v4_times, 95)} | mean={sum(v4_times) // n}")
        print(f"Ratio mean V4/V3: {(sum(v4_times) / sum(v3_times)):.2f}×")

        # By type
        by_type: dict[str, list] = defaultdict(list)
        for r in valid:
            by_type[r["primary_type"]].append(r)
        print(f"\nBy type (V3 → V4):")
        for t, rs in by_type.items():
            v3m = sum(r["v3"]["wall_ms"] for r in rs) // len(rs)
            v4m = sum(r["v4"]["wall_ms"] for r in rs) // len(rs)
            print(f"  {t:<14} n={len(rs)} V3={v3m}ms V4={v4m}ms ratio={v4m / max(v3m, 1):.2f}×")
    print(f"\nPersisted → {OUT_PATH}")


if __name__ == "__main__":
    main()
