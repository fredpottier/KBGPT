"""Sélectionne 30 questions stratifiées parmi les 35 both KO auditables."""
import json
from collections import defaultdict
from pathlib import Path

EXTRACT = "/app/data/benchmark/oracle_audit/both_ko_extract.json"
OUT = "/app/data/benchmark/oracle_audit/oracle_audit_sample.json"

# Quota par catégorie (somme = 30)
QUOTA = {
    "set_list": 7,
    "false_premise": 6,
    "causal_why": 3,
    "synthesis_large": 3,
    "temporal_evolution": 3,
    "negation": 2,
    "conditional": 2,
    "multi_hop": 2,
    "unanswerable": 1,
    # 1 buffer libre
}

data = json.load(open(EXTRACT))
auditables = [q for q in data["questions"] if not q.get("is_meta_kg")]

# Group par catégorie
by_cat = defaultdict(list)
for q in auditables:
    by_cat[q["category"]].append(q)

# Sélectionne stratifié
selected = []
for cat, n in QUOTA.items():
    pool = by_cat.get(cat, [])
    selected.extend(pool[:n])

# Si on n'a pas atteint 30, compléter avec ce qui reste (toutes catégories)
remaining_quota = 30 - len(selected)
if remaining_quota > 0:
    already_ids = {q["question_id"] for q in selected}
    extras = [q for q in auditables if q["question_id"] not in already_ids]
    selected.extend(extras[:remaining_quota])

print(f"Sélectionnés : {len(selected)}/30")
from collections import Counter
print("\nDistribution finale :")
for cat, n in Counter(q["category"] for q in selected).most_common():
    print(f"  {cat:35s} : {n}")

# Persist
with open(OUT, "w", encoding="utf-8") as f:
    json.dump({"count": len(selected), "questions": selected}, f, indent=2, ensure_ascii=False)

print(f"\nÉcrit : {OUT}")
print("\n=== Liste des questions sélectionnées ===")
for q in selected:
    ed = q.get("evidence_docs") or []
    print(f"\n{q['question_id']} | {q['category']} | docs={ed}")
    print(f"  Q: {q['question'][:140]}")
    print(f"  GT correct_fact: {(q['ground_truth'].get('correct_fact') or '')[:140]}")
