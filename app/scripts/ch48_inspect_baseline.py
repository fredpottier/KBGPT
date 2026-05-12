"""Inspect baseline V4_CH46_POSTOPT bench files schema."""
import json
from pathlib import Path

base = Path("/app/data/benchmark/results")
files = {
    "robust": "robustness_run_20260508_060359_V4_CH46_POSTOPT.json",
    "ragas": "ragas_run_20260508_094926_V4_CH46_POSTOPT.json",
    "t2t5": "t2t5_run_20260508_062858_V4_CH46_POSTOPT.json",
}
for name, fname in files.items():
    p = base / fname
    if not p.exists():
        print(f"-- {name}: MISSING {fname}")
        continue
    d = json.loads(p.read_text(encoding="utf-8"))
    print(f"\n== {name} == ({fname})")
    print("  top keys:", list(d.keys()))
    if "scores" in d:
        scores = d["scores"]
        if isinstance(scores, dict):
            print("  scores keys:", list(scores.keys())[:15])
            for k, v in list(scores.items())[:6]:
                if isinstance(v, (int, float)):
                    print(f"    {k} = {v:.3f}")
                elif isinstance(v, dict):
                    print(f"    {k} (dict) keys = {list(v.keys())[:6]}")
                else:
                    print(f"    {k} ({type(v).__name__})")
    samples = d.get("per_sample") or d.get("results") or d.get("samples") or []
    if samples:
        print(f"  per_sample n={len(samples)}")
        s0 = samples[0] if samples else {}
        print(f"  per_sample[0] keys: {list(s0.keys())[:15]}")
