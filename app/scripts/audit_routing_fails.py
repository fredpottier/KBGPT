"""Audit A.1 — extraire les routing fails du bench global pour analyse pattern."""
import json
from collections import Counter, defaultdict

BENCH = "/app/data/benchmark/calibration/bench_global_v4.json"
GOLD = "/app/benchmark/questions/gold_set_v4.json"

bench = json.load(open(BENCH))
gold_index = {q["id"]: q for q in json.load(open(GOLD))}

fails_by_type: dict[str, list[dict]] = defaultdict(list)
for r in bench["per_sample"]:
    expected = r.get("expected_type")
    predicted = r.get("primary_type_predicted")
    if not expected or expected in ("false_premise", "unanswerable"):
        continue
    if predicted == expected:
        continue
    g = gold_index.get(r["id"], {})
    fails_by_type[expected].append({
        "id": r["id"],
        "question": r.get("question", g.get("question", ""))[:160],
        "language": r.get("language"),
        "predicted": predicted,
        "confidence": r.get("primary_confidence"),
        "category": g.get("category"),
        "rerouter_promoted": r.get("rerouter_was_promoted"),
        "rerouter_target": r.get("rerouter_promoted_type"),
        "expected_summary": g.get("ground_truth", {}).get("answer", "")[:120],
    })

print(f"=== ROUTING FAILS BY EXPECTED TYPE ===\n")
total = 0
for t, fs in fails_by_type.items():
    total += len(fs)
    print(f"## {t} : {len(fs)} fails")
    pred_dist = Counter(f["predicted"] for f in fs)
    print(f"   predicted distribution: {dict(pred_dist)}")
    for f in fs:
        print(f"   - [{f['id']}] (conf={f['confidence']:.2f}) → {f['predicted']:<10}")
        print(f"     Q: {f['question']}")
        print(f"     A_expected: {f['expected_summary']}")
        print()
print(f"TOTAL fails: {total}")
