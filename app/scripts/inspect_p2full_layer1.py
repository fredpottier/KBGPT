"""Inspecte les 12 cas où un operator Layer 1 a triggered (P2 full bench)."""
import json
from pathlib import Path

data = json.load(open("/app/data/audit/runtime_v4_2_p2full_bench_robust.json"))
gold = {q["id"]: q for q in json.load(open("/app/benchmark/questions/aero_t6_robustness.json"))}
rows = data["rows"]

l1_rows = [r for r in rows if r["layer"].startswith("layer1_")]
print(f"=== {len(l1_rows)} questions traitées par Layer 1 ===\n")

for r in l1_rows:
    g = gold.get(r["id"])
    expected = (g or {}).get("ground_truth", {}).get("correct_fact", "")[:200]
    print(f"--- {r['id']} | layer={r['layer']} | best={r['score_best']:.3f} ---")
    print(f"  Cat: {r['category']} | exp_behavior: {(g or {}).get('ground_truth', {}).get('expected_behavior')}")
    print(f"  Decision: {r['decision']}")
    print(f"  Answer: {(r.get('answer_excerpt') or '')[:200]}")
    print(f"  Gold:   {expected}")
    print()
