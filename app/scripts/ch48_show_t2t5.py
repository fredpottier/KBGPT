"""Affiche T2T5 résultats CH-48 + comparaison baselines."""
import json
from pathlib import Path

base = Path("/app/data/benchmark/results")
new_runs = sorted([p for p in base.glob("t2t5_run_*.json") if "V4_CH48_LLAMA_TURBO_TOGETHER" in p.name],
                  key=lambda p: p.stat().st_mtime, reverse=True)
old_runs = sorted([p for p in base.glob("t2t5_run_*.json") if "V4_CH46_POSTOPT" in p.name],
                  key=lambda p: p.stat().st_mtime, reverse=True)

print(f"CH-48 runs: {[p.name for p in new_runs]}")
print(f"CH-46 runs: {[p.name for p in old_runs]}")

if not new_runs:
    print("Pas de run CH-48 disponible.")
else:
    new = json.loads(new_runs[0].read_text(encoding="utf-8"))
    print(f"\n== CH-48 ({new_runs[0].name}) ==")
    print(f"  duration: {new.get('duration_s', 0):.0f}s")
    print(f"  scores keys: {list((new.get('scores') or {}).keys())[:20]}")
    print(f"  per_sample n: {len(new.get('per_sample') or [])}")
    sc = new.get('scores') or {}
    for k, v in sc.items():
        if isinstance(v, (int, float)):
            print(f"    {k} = {v:.3f}")

    if old_runs:
        old = json.loads(old_runs[0].read_text(encoding="utf-8"))
        print(f"\n== CH-46 ({old_runs[0].name}) ==")
        print(f"  duration: {old.get('duration_s', 0):.0f}s")
        print(f"  per_sample n: {len(old.get('per_sample') or [])}")
        old_sc = old.get('scores') or {}
        print(f"\n== DELTA ==")
        all_keys = sorted(set(list(sc.keys()) + list(old_sc.keys())))
        for k in all_keys:
            n_v = sc.get(k)
            o_v = old_sc.get(k)
            if isinstance(n_v, (int, float)) and isinstance(o_v, (int, float)):
                d = n_v - o_v
                arrow = "↑" if d > 0 else ("↓" if d < 0 else "=")
                print(f"  {k:35s} {o_v:.3f} → {n_v:.3f} {arrow} ({d:+.3f})")
