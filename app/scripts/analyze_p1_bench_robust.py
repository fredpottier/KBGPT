"""Analyse détaillée des résultats P1.7 bench Robust 120q sur runtime_v4_2."""
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

# Trouve le dernier output
audit_dir = Path("/app/data/audit")
candidates = sorted(audit_dir.glob("runtime_v4_2_p1_bench_robust_*.json"), reverse=True)
if not candidates:
    print("No bench output found")
    sys.exit(1)
path = candidates[0]
print(f"Analysing : {path.name}\n")
data = json.loads(path.read_text(encoding="utf-8"))
rows = data["rows"]
agg = data["aggregate"]

# Distribution par catégorie : decisions + abstain category + scores
print(f"{'category':22s} | {'n':>3s} | {'ans':>3s} | {'absC':>4s} | {'absA':>4s} | {'scoreM':>6s} | {'p50':>5s} | {'p95':>5s}")
print("-" * 80)
by_cat = defaultdict(list)
for r in rows:
    by_cat[r["category"] or "unknown"].append(r)

for cat in sorted(by_cat.keys()):
    rs = by_cat[cat]
    answer = sum(1 for r in rs if r["decision"] == "ANSWER")
    abs_correct = sum(1 for r in rs if r["abstain_category_postdoc"] == "misaligned_abstain_correct")
    abs_answerable = sum(1 for r in rs if r["abstain_category_postdoc"] == "misaligned_but_answerable")
    score_mean = sum(r["score_best"] for r in rs) / len(rs)
    walls = sorted([r["wall_ms"] for r in rs if r["wall_ms"]])
    p50 = walls[len(walls) // 2] if walls else 0
    p95 = walls[int(0.95 * (len(walls) - 1))] if walls else 0
    print(f"{cat:22s} | {len(rs):3d} | {answer:3d} | {abs_correct:4d} | {abs_answerable:4d} | {score_mean:.3f} | {p50:5d} | {p95:5d}")

print()
print(f"GLOBAL : score_best={agg['global']['means']['score_best']:.3f}  "
      f"p50={agg['global']['wall_ms_p50']}ms p95={agg['global']['wall_ms_p95']}ms  "
      f"false_abstain={agg['false_abstain_rate']*100:.1f}%")

# Distribution layer par catégorie
print("\nLayer par catégorie:")
for cat in sorted(by_cat.keys()):
    rs = by_cat[cat]
    layers = Counter(r["layer"] for r in rs)
    print(f"  {cat:22s} : {dict(layers)}")

# Top 10 cas misaligned_but_answerable (false abstain)
print("\nTop 10 false_abstain cases :")
fas = [r for r in rows if r["abstain_category_postdoc"] == "misaligned_but_answerable"]
for r in fas[:10]:
    print(f"  {r['id']:25s} | cat={r['category']:18s} | abs_reason={r.get('abstention_reason', '?')[:80]}")
