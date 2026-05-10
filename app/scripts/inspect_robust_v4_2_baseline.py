"""Inspecte les résultats du bench Robustness v4_2_baseline."""
import json
from collections import Counter

data = json.load(open("/app/data/benchmark/results/robustness_run_20260510_145658_v4_2_baseline.json"))
print(f"Tag: {data.get('tag')}")
print(f"Description: {data.get('description', '')[:120]}")
print(f"N samples: {len(data.get('per_sample', []))}")
print()

scores = data.get("scores") or {}
print(f"=== Global score: {scores.get('global_score')} ===\n")

print("Per category :")
for cat, info in (scores.get("per_category") or {}).items():
    if isinstance(info, dict):
        score = info.get("score")
        n = info.get("n")
        print(f"  {cat:25s} : {score:.3f}  (n={n})")
    else:
        print(f"  {cat:25s} : {info}")

# Layer distribution if available
print("\nLayer distribution (V4.2):")
layers = Counter()
for s in data.get("per_sample", []):
    meta = s.get("_v4_2_meta") or {}
    layer = meta.get("layer") or "?"
    layers[layer] += 1
for k, v in layers.most_common():
    print(f"  {k:30s} : {v}")

# Decision distribution
decisions = Counter()
for s in data.get("per_sample", []):
    meta = s.get("_v4_2_meta") or {}
    decisions[meta.get("decision") or "?"] += 1
print(f"\nDecision distribution: {dict(decisions)}")

# Latency
latencies = []
for s in data.get("per_sample", []):
    lat = (s.get("latency_ms") or s.get("api_latency_ms") or 0)
    if lat:
        latencies.append(lat)
if latencies:
    latencies.sort()
    p50 = latencies[len(latencies) // 2]
    p95 = latencies[int(0.95 * (len(latencies) - 1))]
    print(f"\nLatency: p50={p50}ms, p95={p95}ms, max={max(latencies)}ms (n={len(latencies)})")
