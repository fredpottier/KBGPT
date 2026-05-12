"""
Audit retrieval coverage : sur les 170 questions robustness, distribution
du nombre d'authoritative_doc_ids et corrélation avec score.

Hypothèse : les questions échouées (score < 0.5) ont en moyenne moins
de docs autoritaires (filter trop agressif).
"""
import io, json, sys
from collections import defaultdict, Counter

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

REPORT = json.load(open(r"C:/Projects/SAP_KB/app/data/benchmark/results/robustness_run_20260504_133914.json", encoding="utf-8"))
ps = REPORT["per_sample"]

# Distribution n_authoritative_docs
docs_count = Counter()
docs_by_score = defaultdict(list)  # score_bin -> list of n_docs
score_by_cat = defaultdict(list)

for s in ps:
    score = s.get("evaluation", {}).get("score", 0)
    docs = s.get("sources_used") or []
    n_docs = len(docs)
    cat = s.get("category", "unknown")
    docs_count[n_docs] += 1
    score_by_cat[cat].append(score)

    if score < 0.3:
        docs_by_score["FAIL (<0.3)"].append(n_docs)
    elif score < 0.7:
        docs_by_score["MID (0.3-0.7)"].append(n_docs)
    else:
        docs_by_score["PASS (>=0.7)"].append(n_docs)

print("=" * 80)
print("DISTRIBUTION N_AUTHORITATIVE_DOCS")
print("=" * 80)
total = sum(docs_count.values())
for n in sorted(docs_count):
    pct = 100 * docs_count[n] / total
    bar = "#" * int(pct / 2)
    print(f"  {n} docs : {docs_count[n]:3d} ({pct:5.1f}%) {bar}")

print()
print("=" * 80)
print("AVG N_DOCS PAR BUCKET DE SCORE")
print("=" * 80)
for bucket in ["FAIL (<0.3)", "MID (0.3-0.7)", "PASS (>=0.7)"]:
    arr = docs_by_score.get(bucket, [])
    if arr:
        avg = sum(arr) / len(arr)
        n_one = sum(1 for x in arr if x == 1)
        n_two = sum(1 for x in arr if x == 2)
        n_4plus = sum(1 for x in arr if x >= 4)
        print(f"  {bucket:25s} n={len(arr):3d}  avg_docs={avg:.2f}  "
              f"n_1doc={n_one}({100*n_one/len(arr):.0f}%)  "
              f"n_2doc={n_two}({100*n_two/len(arr):.0f}%)  "
              f"n_4+={n_4plus}({100*n_4plus/len(arr):.0f}%)")

print()
print("=" * 80)
print("SCORE MOYEN PAR CATEGORIE (tri croissant)")
print("=" * 80)
cat_avg = [(cat, sum(scores)/len(scores), len(scores)) for cat, scores in score_by_cat.items()]
cat_avg.sort(key=lambda x: x[1])
for cat, avg, n in cat_avg:
    bar = "#" * int(avg * 50)
    print(f"  {cat:35s} n={n:3d}  avg={avg:.3f}  {bar}")

# Cross-tab : pour les FAIL, dans combien de cas le synthesizer dit "ne contient pas"?
print()
print("=" * 80)
print("ABSTENTION RATE PAR CATEGORIE (failed questions only)")
print("=" * 80)
abstention_markers = ["ne contient pas", "ne fournit pas", "is not", "does not provide",
                      "does not contain", "n'est pas explicitement", "n'est pas clairement",
                      "ne mentionne pas", "ne précise pas", "n'est pas précis"]
absten_by_cat = defaultdict(lambda: [0, 0])
for s in ps:
    score = s.get("evaluation", {}).get("score", 0)
    if score >= 0.3:
        continue
    cat = s.get("category", "unknown")
    ans = (s.get("answer") or "").lower()
    is_absten = any(m in ans for m in abstention_markers)
    absten_by_cat[cat][1] += 1
    if is_absten:
        absten_by_cat[cat][0] += 1

for cat in sorted(absten_by_cat):
    n_absten, n_fail = absten_by_cat[cat]
    pct = 100 * n_absten / max(1, n_fail)
    print(f"  {cat:35s} {n_absten}/{n_fail} failures = {pct:.0f}% abstention")
