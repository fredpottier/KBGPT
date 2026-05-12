"""Comparaison P1 / P2 full / P2 full + verifier veto sur Robust 120q.

Vérifie l'effet du verifier veto (correction architecturale 10/05) :
  - Combien de cas Layer 1 ANSWER ont été REMPLACES par fallback Layer 0 ?
  - Le score_best a-t-il monté ou baissé ?
  - Les misroutes (lifecycle/kg_query sur false_premise/causal/hypothetical) ont-elles disparu ?
"""
import json
from collections import Counter, defaultdict
from pathlib import Path

paths = {
    "P1 (A only)": "/app/data/audit/runtime_v4_2_p1_bench_robust_2026-05-10_101053.json",
    "P2 full (A+B+C+D, no veto)": "/app/data/audit/runtime_v4_2_p2full_bench_robust.json",
    "P2 full + veto": "/app/data/audit/runtime_v4_2_p2full_veto_bench_robust.json",
}

datasets = {}
for name, p in paths.items():
    f = Path(p)
    if f.exists():
        datasets[name] = json.loads(f.read_text(encoding="utf-8"))
    else:
        print(f"MISSING: {p}")

# Header
print(f"{'Run':32s} | {'n':>3s} | {'score_best':>10s} | {'p50':>5s} | {'p95':>5s} | {'L0':>3s} | {'L1':>3s} | {'wall_total':>10s}")
print("-" * 100)
for name, d in datasets.items():
    agg = d["aggregate"]
    rows = d["rows"]
    n = agg["n"]
    score = agg["global"]["means"]["score_best"]
    p50 = agg["global"]["wall_ms_p50"]
    p95 = agg["global"]["wall_ms_p95"]
    layers = Counter(r["layer"] for r in rows)
    l0 = layers.get("layer0", 0)
    l1 = sum(v for k, v in layers.items() if k.startswith("layer1_"))
    wt = d.get("wall_total_seconds", "?")
    print(f"{name:32s} | {n:3d} | {score:10.4f} | {p50:5d} | {p95:5d} | {l0:3d} | {l1:3d} | {wt:>10}")

# Distribution Layer 1 par run
print("\nLayer 1 sub-distribution :")
for name, d in datasets.items():
    rows = d["rows"]
    sub = Counter(r["layer"] for r in rows if r["layer"].startswith("layer1_"))
    print(f"  {name:32s} : {dict(sub)}")

# Misroutes par run (operators triggered sur catégorie incompatible)
print("\nMisroutes (Cap2.X triggered sur incompatible category) :")
INCOMPATIBLE = {
    "layer1_lifecycle_resolution": {"false_premise", "unanswerable", "causal_why",
                                    "hypothetical", "set_list", "synthesis_large"},
    "layer1_kg_query": {"unanswerable", "false_premise", "causal_why", "hypothetical"},
    "layer1_temporal_active": {"hypothetical", "false_premise"},
    "layer1_set_reasoning": {"false_premise", "unanswerable"},
}
for name, d in datasets.items():
    rows = d["rows"]
    misroutes = [r for r in rows if r["layer"] in INCOMPATIBLE
                 and r["category"] in INCOMPATIBLE.get(r["layer"], set())]
    print(f"  {name:32s} : {len(misroutes)} misroutes")
    by_cat = Counter((r["layer"], r["category"]) for r in misroutes)
    for (lyr, cat), n in by_cat.most_common(5):
        print(f"    {lyr} on {cat}: {n}")

# Score moyen sur les questions où le veto aurait dû déclencher
print("\nImpact veto sur les misroutes (P2 full vs P2 veto) :")
no_veto = datasets.get("P2 full (A+B+C+D, no veto)")
veto = datasets.get("P2 full + veto")
if no_veto and veto:
    nv_misroutes = {r["id"] for r in no_veto["rows"]
                    if r["layer"] in INCOMPATIBLE
                    and r["category"] in INCOMPATIBLE.get(r["layer"], set())}
    print(f"  Questions misroute identifiées (no veto): {len(nv_misroutes)}")
    veto_by_id = {r["id"]: r for r in veto["rows"]}
    nv_by_id = {r["id"]: r for r in no_veto["rows"]}
    n_recovered_l0 = 0
    n_score_up = 0
    n_score_down = 0
    for qid in nv_misroutes:
        nv_r = nv_by_id[qid]
        v_r = veto_by_id.get(qid)
        if v_r is None:
            continue
        if v_r["layer"] == "layer0":
            n_recovered_l0 += 1
        if v_r["score_best"] > nv_r["score_best"]:
            n_score_up += 1
        elif v_r["score_best"] < nv_r["score_best"]:
            n_score_down += 1
    print(f"  Recovered to layer0 with veto: {n_recovered_l0}/{len(nv_misroutes)}")
    print(f"  Score up post-veto: {n_score_up}, score down post-veto: {n_score_down}")
