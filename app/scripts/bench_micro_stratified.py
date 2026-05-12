#!/usr/bin/env python3
"""
Bench micro stratifié 30q post-leviers latence (5/type sur 5 types structurels +
2 unanswerable + 3 false_premise). Compare p50/p95 vs baseline 2026-05-07.

Usage (container) :
  docker cp scripts/bench_micro_stratified.py knowbase-app:/app/scripts/
  docker exec -e FACTS_FIRST_MODE=latency knowbase-app python /app/scripts/bench_micro_stratified.py [TAG]

Le TAG (optional) suffixe le fichier output pour différencier les runs A/B.
"""
from __future__ import annotations
import json
import os
import sys
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

PROJECT_ROOT = Path("/app")
if (PROJECT_ROOT / "src").exists():
    sys.path.insert(0, str(PROJECT_ROOT / "src"))
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

from bench_global_v4 import build_pipeline, evaluate_one  # type: ignore

GOLD = json.loads(Path("/app/benchmark/questions/gold_set_v4.json").read_text(encoding="utf-8"))

# Sample stratifié : 5/type sur les 5 types structurels + 2 unanswerable + 3 false_premise = 30q
QUOTA = {
    "factual": 5,
    "list": 5,
    "temporal": 5,
    "comparison": 5,
    "causal": 5,
    "unanswerable": 2,
    "false_premise": 3,
}

def sample_stratified():
    by_type: dict[str, list[dict]] = defaultdict(list)
    for q in GOLD:
        by_type[q.get("primary_type") or "?"].append(q)
    out = []
    for t, n in QUOTA.items():
        out.extend(by_type.get(t, [])[:n])
    return out


def percentile(vals, p):
    s = sorted(vals)
    if not s:
        return None
    idx = max(0, min(len(s) - 1, int(p / 100 * len(s))))
    return s[idx]


def main():
    tag = sys.argv[1] if len(sys.argv) > 1 else "default"
    structurer_model = os.getenv("FACTS_FIRST_STRUCTURER_MODEL", "qwen-default")
    nli_backend = os.getenv("NLI_BACKEND", "mdeberta")
    print(f"=== TAG={tag} | structurer={structurer_model} | nli={nli_backend} ===")
    sample = sample_stratified()
    print(f"Sampled {len(sample)} questions across {len(QUOTA)} types")

    pipeline = build_pipeline(use_transverse=True)
    print("Pipeline ready, running bench (workers=4) ...")

    results: list[dict] = []
    t_start = time.time()
    with ThreadPoolExecutor(max_workers=4) as ex:
        futures = {ex.submit(evaluate_one, pipeline, q): q for q in sample}
        for i, fut in enumerate(as_completed(futures), 1):
            try:
                results.append(fut.result())
            except Exception as exc:
                results.append({"id": futures[fut].get("id"), "error": str(exc)})
            if i % 5 == 0 or i == len(sample):
                print(f"  {i}/{len(sample)} done")
    elapsed = time.time() - t_start

    print()
    print(f"=== BENCH MICRO STRATIFIED — {len(results)} questions in {elapsed:.1f}s ===")
    print(f"{'type':<14} {'n':>3} {'p50_ms':>8} {'p95_ms':>8} {'verif':>6} {'route_ok':>9}")
    by_t: dict[str, list[dict]] = defaultdict(list)
    for r in results:
        if r.get("error"):
            continue
        by_t[r.get("expected_type") or "?"].append(r)
    for t in ("factual", "list", "temporal", "comparison", "causal", "unanswerable", "false_premise"):
        rs = by_t.get(t, [])
        if not rs:
            continue
        n = len(rs)
        elapsed_ms = [r.get("elapsed_ms") for r in rs if r.get("elapsed_ms") is not None]
        verif = sum(1 for r in rs if r.get("verifier_passed")) / n
        route_ok = sum(1 for r in rs if r.get("primary_type_predicted") == t) / n
        print(f"{t:<14} {n:>3} {percentile(elapsed_ms, 50):>8} {percentile(elapsed_ms, 95):>8} {verif:>6.2f} {route_ok:>9.2f}")
    print()
    all_elapsed = [r.get("elapsed_ms") for r in results if r.get("elapsed_ms") is not None]
    print(f"GLOBAL p50={percentile(all_elapsed, 50)}ms  p95={percentile(all_elapsed, 95)}ms  "
          f"mean={sum(all_elapsed) / len(all_elapsed):.0f}ms")
    out = {
        "tag": tag, "structurer_model": structurer_model, "nli_backend": nli_backend,
        "sample_size": len(results), "elapsed_seconds": elapsed,
        "per_sample": results,
    }
    out_path = f"/app/data/benchmark/calibration/bench_micro_stratified_{tag}.json"
    Path(out_path).write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Persisted: {out_path}")


if __name__ == "__main__":
    main()
