"""Diag A.3 — distribution latence factual : effet queue ou régression code ?"""
import json
import statistics
from collections import Counter

BENCH = "/app/data/benchmark/calibration/bench_global_v4.json"
data = json.load(open(BENCH))

factual = [r for r in data["per_sample"] if r.get("expected_type") == "factual" and not r.get("error")]
times = sorted([r.get("elapsed_ms", 0) for r in factual])

print(f"=== FACTUAL LATENCY DISTRIBUTION ({len(factual)} questions) ===")
print(f"min  = {times[0]/1000:.1f}s")
print(f"p25  = {times[len(times)//4]/1000:.1f}s")
print(f"p50  = {times[len(times)//2]/1000:.1f}s")
print(f"p75  = {times[3*len(times)//4]/1000:.1f}s")
print(f"p90  = {times[int(len(times)*0.9)]/1000:.1f}s")
print(f"p95  = {times[int(len(times)*0.95)]/1000:.1f}s")
print(f"max  = {times[-1]/1000:.1f}s")
print(f"mean = {statistics.mean(times)/1000:.1f}s")
print(f"std  = {statistics.stdev(times)/1000:.1f}s")
print()

print("=== HISTOGRAM (10s bins) ===")
bins = Counter()
for t in times:
    b = int(t // 10000) * 10
    bins[b] += 1
for b in sorted(bins):
    print(f"  {b:>3}-{b+10}s : {'#' * bins[b]} ({bins[b]})")

# Decompose : structurer + composer + others (verifier + channel2)
print("\n=== TOP 5 SLOWEST FACTUAL ===")
slow = sorted(factual, key=lambda r: -r.get("elapsed_ms", 0))[:5]
for r in slow:
    print(f"  {r['id']:30} {r['elapsed_ms']/1000:.1f}s | rejected={r.get('structurer_rejected_count')} | route={r.get('routing_decision')}")

print("\n=== TOP 5 FASTEST FACTUAL ===")
fast = sorted(factual, key=lambda r: r.get("elapsed_ms", 0))[:5]
for r in fast:
    print(f"  {r['id']:30} {r['elapsed_ms']/1000:.1f}s | rejected={r.get('structurer_rejected_count')} | route={r.get('routing_decision')}")
