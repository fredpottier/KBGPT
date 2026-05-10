"""Audit A.1 suite — vérifie si secondary_type capture les routing fails."""
import json
import os
import sys
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
from collections import Counter

sys.path.insert(0, "/app/src")

GOLD = "/app/benchmark/questions/gold_set_v4.json"
BENCH = "/app/data/benchmark/calibration/bench_global_v4.json"

bench = json.load(open(BENCH))
gold_index = {q["id"]: q for q in json.load(open(GOLD))}

fails = []
for r in bench["per_sample"]:
    expected = r.get("expected_type")
    predicted = r.get("primary_type_predicted")
    if not expected or expected in ("false_premise", "unanswerable"):
        continue
    if predicted == expected:
        continue
    fails.append((r["id"], gold_index.get(r["id"], {}).get("question", ""), expected, predicted))

print(f"Re-running QuestionAnalyzer on {len(fails)} fail cases to inspect secondary_type")

from knowbase.facts_first.question_analyzer import QuestionAnalyzer
analyzer = QuestionAnalyzer()

def analyze_one(item):
    qid, q, expected, prev_pred = item
    res = analyzer.analyze(q)
    return (qid, expected, prev_pred, res.primary_type, res.primary_confidence,
            res.secondary_type, res.secondary_confidence)

results = []
with ThreadPoolExecutor(max_workers=4) as ex:
    futures = [ex.submit(analyze_one, f) for f in fails]
    for fut in as_completed(futures):
        results.append(fut.result())

print(f"\n=== TOP-2 MULTI-LABEL ANALYSIS ===\n")
n_top2_match = 0
n_top1_match_re_run = 0  # variance LLM
for qid, expected, prev_pred, top1, c1, top2, c2 in sorted(results):
    top2_match = top2 == expected
    top1_match_now = top1 == expected
    if top2_match:
        n_top2_match += 1
    if top1_match_now:
        n_top1_match_re_run += 1
    flag = "OK-top2" if top2_match else ("now-top1" if top1_match_now else "FAIL")
    top2_str = (top2 or "none")
    c2_str = f"{c2:.2f}" if c2 is not None else "n/a"
    print(f"  [{qid}] expected={expected:<10} prev={prev_pred:<10} re-top1={top1:<10}({c1:.2f}) top2={top2_str:<12}({c2_str}) {flag}")

print(f"\n=== SUMMARY ===")
print(f"Total fails analyzed: {len(results)}")
print(f"Re-run top1 matched (LLM variance): {n_top1_match_re_run}/{len(results)}")
print(f"Top-2 captured the right label: {n_top2_match}/{len(results)}")
print(f"Effective potential routing if top-2 fallback: {n_top1_match_re_run + n_top2_match}/{len(results)}")
