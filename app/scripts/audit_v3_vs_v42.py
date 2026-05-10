"""Audit profond V3 vs V4.2 — question par question, identifier les régressions.

Compare per_sample entre :
  - V3_FINAL3 (05/05) : score 0.545
  - V4.2_BASELINE (10/05) : score 0.408 (-25%)

Pour les 170 questions du bench Robustness, on croise par question_id et on
cherche les patterns :
  - V3 réussit (score > 0.5) ET V4.2 échoue (score = 0) = régression
  - V3 abstient correctement ET V4.2 hallucine = régression
  - V4.2 réussit ET V3 échouait = gain (rare attendu)
"""
import json
from collections import Counter, defaultdict

V3 = "/app/data/benchmark/results/robustness_run_20260505_104355_V3_FINAL3.json"
V42 = "/app/data/benchmark/results/robustness_run_20260510_145658_v4_2_baseline.json"

v3_data = json.load(open(V3))
v42_data = json.load(open(V42))

v3_by_qid = {s["question_id"]: s for s in v3_data["per_sample"]}
v42_by_qid = {s["question_id"]: s for s in v42_data["per_sample"]}

# Croisement
both = sorted(set(v3_by_qid) & set(v42_by_qid))
print(f"Questions en commun : {len(both)} (V3:{len(v3_by_qid)} V4.2:{len(v42_by_qid)})")

# Comparatifs
regressions = []  # V3 réussit, V4.2 échoue
gains = []        # V4.2 réussit, V3 échouait
both_ok = 0
both_ko = 0

for qid in both:
    v3 = v3_by_qid[qid]
    v42 = v42_by_qid[qid]
    v3_score = (v3.get("evaluation") or {}).get("score") or 0
    v42_score = (v42.get("evaluation") or {}).get("score") or 0
    v3_score = float(v3_score)
    v42_score = float(v42_score)
    if v3_score >= 0.5 and v42_score < 0.5:
        regressions.append((qid, v3, v42, v3_score, v42_score))
    elif v42_score >= 0.5 and v3_score < 0.5:
        gains.append((qid, v3, v42, v3_score, v42_score))
    elif v3_score >= 0.5 and v42_score >= 0.5:
        both_ok += 1
    else:
        both_ko += 1

print(f"\nRégressions (V3 OK → V4.2 KO) : {len(regressions)}")
print(f"Gains (V3 KO → V4.2 OK) : {len(gains)}")
print(f"Both OK : {both_ok}")
print(f"Both KO : {both_ko}")

# Régressions par catégorie
reg_by_cat = Counter(r[1].get("category") for r in regressions)
print(f"\nRégressions par catégorie :")
for cat, n in reg_by_cat.most_common():
    total_cat = sum(1 for qid in both if v3_by_qid[qid].get("category") == cat)
    print(f"  {cat:25s} : {n}/{total_cat} ({100*n/max(1,total_cat):.0f}%)")

# Sample des régressions les plus parlantes
print(f"\n=== TOP 15 régressions (avec answer V3 vs V4.2) ===")
for qid, v3, v42, v3s, v42s in regressions[:15]:
    print(f"\n--- {qid} | cat={v3.get('category')} | V3={v3s} → V4.2={v42s} ---")
    print(f"Q: {v3.get('question', '')[:200]}")
    print(f"V3 answer: {(v3.get('answer') or '')[:250]}")
    v3_eval = v3.get("evaluation") or {}
    print(f"V3 judge: {(v3_eval.get('judge_reason') or '')[:200]}")
    print(f"V4.2 answer: {(v42.get('answer') or '')[:250]}")
    v42_eval = v42.get("evaluation") or {}
    print(f"V4.2 judge: {(v42_eval.get('judge_reason') or '')[:200]}")

# Pattern : V4.2 abstient (answer = "n'a pas été trouvé") vs V3 répond
v42_abstain_pattern_count = 0
for qid, v3, v42, _, _ in regressions:
    a = (v42.get("answer") or "").lower()
    if "n'a pas" in a or "not found" in a or "not been found" in a:
        v42_abstain_pattern_count += 1
print(f"\nRégressions où V4.2 abstient (n'a pas trouvé) : {v42_abstain_pattern_count}/{len(regressions)} ({100*v42_abstain_pattern_count/max(1,len(regressions)):.0f}%)")

# Pattern : V4.2 répond mais hors-cible (judge dit MISALIGNED ou OFF_TARGET)
import re
v42_offtarget = 0
for qid, v3, v42, _, _ in regressions:
    judge = ((v42.get("evaluation") or {}).get("judge_reason") or "").lower()
    if "misalign" in judge or "off-target" in judge or "off topic" in judge or "irrelevant" in judge or "does not address" in judge:
        v42_offtarget += 1
print(f"Régressions où V4.2 hors-cible selon judge : {v42_offtarget}/{len(regressions)}")
