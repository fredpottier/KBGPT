"""Synthèse détaillée des résultats 170q par catégorie."""
import json
from collections import defaultdict

d = json.load(open("/app/data/benchmark/oracle_audit/poc_a_results_170q.json"))
qs = d["per_question"]

by_cat_agent = defaultdict(list)
by_cat_v3 = defaultdict(list)
by_cat_v42 = defaultdict(list)

for q in qs:
    cat = q["category"]
    ll = q.get("scores", {}).get("llama-3.3-70b", {}).get("score")
    if ll is not None:
        by_cat_agent[cat].append(ll)
    by_cat_v3[cat].append(q["v3_score_bench"])
    by_cat_v42[cat].append(q["v4_2_score_bench"])

print(f"\n{'Category':<30} {'n':>4} {'Agent':>8} {'V3':>8} {'V4.2':>8} {'ΔvsV4.2':>10}")
print(f"{'-'*30:<30} {'-'*4:>4} {'-'*8:>8} {'-'*8:>8} {'-'*8:>8} {'-'*10:>10}")

# Sort by Agent score descending
cats_sorted = sorted(by_cat_agent.keys(), key=lambda c: -sum(by_cat_agent[c])/len(by_cat_agent[c]))
total_agent, total_v3, total_v42 = 0, 0, 0
total_n = 0
for cat in cats_sorted:
    n = len(by_cat_agent[cat])
    agent_m = sum(by_cat_agent[cat]) / n
    v3_m = sum(by_cat_v3[cat]) / n
    v42_m = sum(by_cat_v42[cat]) / n
    delta = (agent_m - v42_m) * 100
    print(f"{cat:<30} {n:>4} {agent_m:>8.3f} {v3_m:>8.3f} {v42_m:>8.3f} {delta:>+9.1f}pp")
    total_agent += agent_m * n
    total_v3 += v3_m * n
    total_v42 += v42_m * n
    total_n += n

print(f"{'-'*30:<30} {'-'*4:>4} {'-'*8:>8} {'-'*8:>8} {'-'*8:>8}")
print(f"{'TOTAL':<30} {total_n:>4} {total_agent/total_n:>8.3f} {total_v3/total_n:>8.3f} {total_v42/total_n:>8.3f}")

# Cas où Reading Agent < V3 (régressions à investiguer)
print(f"\n=== Catégories où Reading Agent < V3 ===")
for cat in cats_sorted:
    agent_m = sum(by_cat_agent[cat]) / len(by_cat_agent[cat])
    v3_m = sum(by_cat_v3[cat]) / len(by_cat_v3[cat])
    if agent_m < v3_m:
        print(f"  {cat}: Agent={agent_m:.3f} V3={v3_m:.3f} delta={agent_m-v3_m:+.3f}")
