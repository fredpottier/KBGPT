"""Audit A.2 — sample 10 UNFAITHFUL du bench global pour vérification verbatim."""
import json
import random
from collections import Counter

BENCH = "/app/data/benchmark/calibration/bench_global_v4.json"
GOLD = "/app/benchmark/questions/gold_set_v4.json"

bench = json.load(open(BENCH))
gold_index = {q["id"]: q for q in json.load(open(GOLD))}

unfaithful = [r for r in bench["per_sample"] if r.get("channel2_verdict") == "UNFAITHFUL"]
print(f"Total UNFAITHFUL: {len(unfaithful)}")
print(f"Distribution by type: {Counter(r.get('expected_type') for r in unfaithful)}")

random.seed(42)
sample = random.sample(unfaithful, min(10, len(unfaithful)))

print("\n=== AUDIT 10 UNFAITHFUL CASES ===\n")
for r in sample:
    qid = r["id"]
    g = gold_index.get(qid, {})
    print(f"## [{qid}] type={r.get('expected_type')} | route={r.get('routing_decision')}")
    print(f"   QUESTION: {g.get('question', '')[:200]}")
    print(f"   ANSWER  : {(r.get('answer_text') or '')[:300]}")
    print(f"   GROUND  : {g.get('ground_truth', {}).get('answer', '')[:200]}")
    print(f"   ch2_score: {r.get('channel2_score')}")
    print()
