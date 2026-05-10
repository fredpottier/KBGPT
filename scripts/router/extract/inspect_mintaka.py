"""Quick inspection of Mintaka complexity types + categories."""
import json
from collections import Counter

all_qs = []
for split in ["train", "dev", "test"]:
    with open(f"/app/data/router/external/mintaka_{split}.json") as f:
        all_qs.extend(json.load(f))

print(f"Total Mintaka : {len(all_qs)} questions")
print(f"\ncomplexityType distribution: {dict(Counter(q['complexityType'] for q in all_qs))}")
print(f"\ncategory distribution (top10): {Counter(q['category'] for q in all_qs).most_common(10)}")
print(f"\nFR translation available: {sum(1 for q in all_qs if q.get('translations', {}).get('fr'))}/{len(all_qs)}")

# Sample par complexityType
print("\n=== Sample par complexityType ===")
by_type = {}
for q in all_qs:
    t = q["complexityType"]
    if t not in by_type:
        by_type[t] = []
    if len(by_type[t]) < 2:
        by_type[t].append(q)

for t, samples in by_type.items():
    print(f"\n[{t}]")
    for s in samples:
        print(f"  EN: {s['question']}")
        print(f"  FR: {s.get('translations', {}).get('fr', '')}")
