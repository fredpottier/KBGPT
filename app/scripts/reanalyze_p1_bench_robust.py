"""Re-analyse les résultats P1.7 avec mapping expected_behavior corrigé.

Bug original : 'state_unanswerable' n'était pas mappé en 'unanswerable'
→ 10 questions UNA classées comme false_abstain à tort.

Mapping corrigé :
  - answer / explain → answerable
  - abstain / reject_premise / state_unanswerable / not_in_scope → unanswerable
"""
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path


CORRECT_MAPPING = {
    "answer": "answerable",
    "explain": "answerable",
    "abstain": "unanswerable",
    "reject_premise": "unanswerable",
    "state_unanswerable": "unanswerable",
    "not_in_scope": "unanswerable",
    "decline_partial": "partial",
}


def categorize(decision: str, gold_answerability: str) -> str:
    d = (decision or "").upper()
    a = (gold_answerability or "").lower()
    if d == "ANSWER":
        return "aligned"
    if d == "ABSTAIN":
        if a in ("unanswerable", "partial"):
            return "misaligned_abstain_correct"
        if a == "answerable":
            return "misaligned_but_answerable"
    return "unknown"


# Charge gold pour map id → expected_behavior
gold_path = Path("/app/benchmark/questions/aero_t6_robustness.json")
gold = {q["id"]: q for q in json.loads(gold_path.read_text(encoding="utf-8"))}

# Distribution des expected_behavior
behaviors = Counter(q["ground_truth"].get("expected_behavior") for q in gold.values())
print("Distribution expected_behavior dans gold :")
for b, n in behaviors.most_common():
    mapped = CORRECT_MAPPING.get(b, "?")
    print(f"  {b!r:30s} → {mapped!r:15s}  (n={n})")
print()

# Charge le bench output
audit_dir = Path("/app/data/audit")
candidates = sorted(audit_dir.glob("runtime_v4_2_p1_bench_robust_*.json"), reverse=True)
path = candidates[0]
data = json.loads(path.read_text(encoding="utf-8"))
rows = data["rows"]

# Re-categorize avec mapping corrigé
fixed_rows = []
for r in rows:
    qid = r["id"]
    g = gold.get(qid)
    expected_behavior = (g or {}).get("ground_truth", {}).get("expected_behavior")
    correct_answerability = CORRECT_MAPPING.get(expected_behavior, "answerable")
    new_cat = categorize(r["decision"], correct_answerability)
    fixed_rows.append({
        **r,
        "gold_expected_behavior": expected_behavior,
        "gold_answerability_corrected": correct_answerability,
        "abstain_category_corrected": new_cat,
    })

# Re-aggregate
print(f"{'category':22s} | {'n':>3s} | {'ans':>3s} | {'absC':>4s} | {'absA':>4s} | {'scoreM':>6s} | {'p50':>5s} | {'p95':>5s}")
print("-" * 80)
by_cat = defaultdict(list)
for r in fixed_rows:
    by_cat[r["category"]].append(r)
for cat in sorted(by_cat.keys()):
    rs = by_cat[cat]
    answer = sum(1 for r in rs if r["decision"] == "ANSWER")
    abs_correct = sum(1 for r in rs if r["abstain_category_corrected"] == "misaligned_abstain_correct")
    abs_answerable = sum(1 for r in rs if r["abstain_category_corrected"] == "misaligned_but_answerable")
    score_mean = sum(r["score_best"] for r in rs) / len(rs)
    walls = sorted([r["wall_ms"] for r in rs if r["wall_ms"]])
    p50 = walls[len(walls) // 2] if walls else 0
    p95 = walls[int(0.95 * (len(walls) - 1))] if walls else 0
    print(f"{cat:22s} | {len(rs):3d} | {answer:3d} | {abs_correct:4d} | {abs_answerable:4d} | {score_mean:.3f} | {p50:5d} | {p95:5d}")

# Stats globales
n_total = len(fixed_rows)
n_aligned = sum(1 for r in fixed_rows if r["abstain_category_corrected"] == "aligned")
n_abs_corr = sum(1 for r in fixed_rows if r["abstain_category_corrected"] == "misaligned_abstain_correct")
n_abs_ans = sum(1 for r in fixed_rows if r["abstain_category_corrected"] == "misaligned_but_answerable")
score_mean = sum(r["score_best"] for r in fixed_rows) / n_total
abstain_reward = sum(1 for r in fixed_rows if r["abstain_reward_applied"])

print()
print(f"=== GLOBAL avec mapping corrigé ===")
print(f"  n = {n_total}")
print(f"  aligned                       : {n_aligned} ({100*n_aligned/n_total:.1f}%)")
print(f"  misaligned_abstain_correct    : {n_abs_corr} ({100*n_abs_corr/n_total:.1f}%)")
print(f"  misaligned_but_answerable     : {n_abs_ans} ({100*n_abs_ans/n_total:.1f}%) ← FALSE ABSTAIN RATE")
print(f"  abstain reward applied        : {abstain_reward}")
print(f"  score_best mean               : {score_mean:.3f}")
print(f"  false_abstain_rate            : {n_abs_ans/n_total*100:.1f}% (gate ≤5%)")

# Save corrected
out = path.parent / f"{path.stem}_corrected.json"
out.write_text(json.dumps({
    "source": str(path),
    "rows": fixed_rows,
    "summary": {
        "n": n_total,
        "aligned": n_aligned,
        "misaligned_abstain_correct": n_abs_corr,
        "misaligned_but_answerable": n_abs_ans,
        "false_abstain_rate": round(n_abs_ans / n_total, 4),
        "score_best_mean": round(score_mean, 4),
        "abstain_reward_applied": abstain_reward,
    },
}, indent=2, ensure_ascii=False), encoding="utf-8")
print(f"\nWritten {out}")
