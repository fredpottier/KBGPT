"""Diag confusion matrix on hold-outs."""
import json

d = json.load(open("/app/data/router/eval_holdouts.json"))
labels = ["causal", "comparison", "factual", "false_premise", "list", "temporal", "unanswerable"]

for tag in ("gold_set_v4", "panel_stress_test"):
    print(f"\n=== {tag} confusion (rows=true, cols=pred) ===")
    cm = d[tag]["confusion_top1"]
    header = "true\\pred".ljust(14) + "".join(f"{l[:6]:>9}" for l in labels)
    print(header)
    for true_lbl in labels:
        row = cm.get(true_lbl, {})
        cells = "".join(f"{row.get(p,0):>9}" for p in labels)
        n_true = sum(row.values())
        diag = row.get(true_lbl, 0)
        recall = diag / n_true if n_true else 0
        print(f"{true_lbl:<14}{cells}  | n={n_true}, recall={recall:.2f}")

# Plus : examine per-language breakdown
print("\n=== per-language analysis gold_set_v4 ===")
preds = json.load(open("/app/data/router/eval_predictions_gold.json"))
from collections import defaultdict
by_lang_type = defaultdict(lambda: {"n": 0, "ok": 0})
for p in preds:
    key = (p["language"], p["label_name"])
    by_lang_type[key]["n"] += 1
    if p["correct_top1"]:
        by_lang_type[key]["ok"] += 1
for (lang, t), v in sorted(by_lang_type.items()):
    print(f"  {lang} | {t:<14} n={v['n']:>3}  acc={v['ok']/v['n']:.2f}")
