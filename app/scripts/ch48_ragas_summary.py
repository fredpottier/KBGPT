"""Récap RAGAS CH-48 vs CH-46."""
import json
from pathlib import Path
from statistics import mean

RAGAS_CH48 = Path("/app/data/benchmark/results/ragas_run_20260509_191321_V4_CH48_LLAMA_TURBO_TOGETHER.json")
RAGAS_CH46 = Path("/app/data/benchmark/results/ragas_run_20260508_094926_V4_CH46_POSTOPT.json")

ch48 = json.loads(RAGAS_CH48.read_text(encoding="utf-8"))
ch46 = json.loads(RAGAS_CH46.read_text(encoding="utf-8"))

print(f"=== CH-48 ({RAGAS_CH48.name}) ===")
print(f"  duration: {ch48.get('duration_s', 0):.0f}s")
print(f"  per_sample: {len(ch48.get('per_sample') or [])}")
print(f"  top keys: {list(ch48.keys())[:15]}")

def avg_metric(samples, key):
    vals = [s.get(key) for s in samples if isinstance(s.get(key), (int, float))]
    return mean(vals) if vals else 0.0

s48 = ch48.get("per_sample") or []
s46 = ch46.get("per_sample") or []

print(f"\n{'Metric':25s} | {'CH-46':>8s} | {'CH-48':>8s} | {'Δ':>9s}")
print("-" * 60)
for m in ["faithfulness", "context_relevance", "factual_correctness"]:
    v46 = avg_metric(s46, m)
    v48 = avg_metric(s48, m)
    d = v48 - v46
    arrow = "↑" if d > 0.02 else ("↓" if d < -0.02 else "·")
    print(f"{m:25s} | {v46:>8.3f} | {v48:>8.3f} | {arrow}{d:>+8.3f}")

print(f"\nDuration RAGAS: CH-46={ch46.get('duration_s',0):.0f}s vs CH-48={ch48.get('duration_s',0):.0f}s")

# Scores agrégés top-level
sc48 = ch48.get("scores_osmosis") or {}
sc46 = ch46.get("scores_osmosis") or {}
if sc48 or sc46:
    print(f"\n=== scores_osmosis top-level ===")
    for k in sorted(set(list(sc48.keys()) + list(sc46.keys()))):
        v48 = sc48.get(k, 0)
        v46 = sc46.get(k, 0)
        if isinstance(v48, (int, float)) and isinstance(v46, (int, float)):
            d = v48 - v46
            arrow = "↑" if d > 0.02 else ("↓" if d < -0.02 else "·")
            print(f"  {k:30s}: {v46:.3f} → {v48:.3f} ({arrow}{d:+.3f})")
