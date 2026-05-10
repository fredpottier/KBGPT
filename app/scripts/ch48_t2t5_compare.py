"""Comparaison T2T5 CH-48 vs CH-46 baseline (lit fichier le plus récent par tag)."""
import json
from pathlib import Path

paths = [Path("/app/data/benchmark/results"), Path("/data/benchmark/results")]
all_t2t5 = []
for base in paths:
    if base.exists():
        all_t2t5.extend(base.glob("t2t5_run_*.json"))
all_t2t5 = sorted(all_t2t5, key=lambda p: p.stat().st_mtime, reverse=True)

new = next((p for p in all_t2t5 if "V4_CH48" in p.name), None)
old = next((p for p in all_t2t5 if "V4_CH46_POSTOPT" in p.name), None)

if not new:
    print("Pas de T2T5 CH-48 trouvé")
    exit(1)

n_d = json.loads(new.read_text(encoding="utf-8"))
print(f"== T2T5 CH-48 ({new.name}) ==")
print(f"  duration: {n_d.get('duration_s', 0):.1f}s")
n_sc = n_d.get('scores') or {}

if old:
    o_d = json.loads(old.read_text(encoding="utf-8"))
    print(f"\n== T2T5 CH-46 baseline ({old.name}) ==")
    print(f"  duration: {o_d.get('duration_s', 0):.1f}s")
    o_sc = o_d.get('scores') or {}

    print(f"\n== DELTA T2T5 ==")
    print(f"{'metric':45s} | {'CH-46':>8s} | {'CH-48':>8s} | {'Δ':>8s}")
    print("-" * 80)
    keys = sorted(set(list(n_sc.keys()) + list(o_sc.keys())))
    for k in keys:
        n_v = n_sc.get(k)
        o_v = o_sc.get(k)
        if isinstance(n_v, (int, float)) and isinstance(o_v, (int, float)):
            d = n_v - o_v
            arrow = "↑" if d > 0.02 else ("↓" if d < -0.02 else "·")
            print(f"{k:45s} | {o_v:>8.3f} | {n_v:>8.3f} | {arrow}{d:+8.3f}")
        elif isinstance(n_v, (int, float)):
            print(f"{k:45s} | {'N/A':>8s} | {n_v:>8.3f} | (new)")
    dur_gain = (o_d.get('duration_s', 0) - n_d.get('duration_s', 0))
    print(f"\nDuration: CH-46={o_d.get('duration_s', 0):.0f}s vs CH-48={n_d.get('duration_s', 0):.0f}s (gain {dur_gain:.0f}s)")
else:
    print("Pas de baseline CH-46 trouvée")
    print("\nScores CH-48 seuls :")
    for k, v in n_sc.items():
        if isinstance(v, (int, float)):
            print(f"  {k:45s} = {v:.3f}")
