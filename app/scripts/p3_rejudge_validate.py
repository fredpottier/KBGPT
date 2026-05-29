"""Valide le juge recalibré : re-juge les réponses sauvegardées d'un run bench
avec le nouveau JUDGE_SYSTEM_PROMPT, et compare au juge d'origine + exact_id_recall.

Usage : p3_rejudge_validate.py <run.json>
"""
from __future__ import annotations
import json
import statistics
import sys

# importe le juge recalibré + le gold-set pour exact_id_recall
sys.path.insert(0, "scripts")
import importlib.util
spec = importlib.util.spec_from_file_location("bench", "scripts/bench_a38_runtime_v6.py")
bench = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bench)

GOLD = "benchmark/questions/gold_set_a38_50q.json"


def main():
    run = json.load(open(sys.argv[1]))
    gold = {q["id"]: q for q in json.load(open(GOLD))}

    rows = []
    for x in run["results_50q"]:
        q = gold.get(x["id"], {})
        gt = q.get("ground_truth", {}) or {}
        new = bench.llm_judge(
            x["question"], x["run"].get("answer_text", ""), gt.get("answer", ""),
            answerability=gt.get("answerability", "answerable"),
            false_premise=gt.get("false_premise", False),
            mode=x["run"].get("mode"),
        )
        rows.append({
            "type": x.get("primary_type"),
            "old": x.get("judge_score"),
            "new": new["score"],
            "eir": x.get("exact_id_recall"),
        })

    def mean(vals):
        vals = [v for v in vals if v is not None]
        return statistics.mean(vals) if vals else None

    print(f"GLOBAL : old_judge={mean([r['old'] for r in rows]):.3f}  "
          f"new_judge={mean([r['new'] for r in rows]):.3f}  "
          f"exact_id_recall={mean([r['eir'] for r in rows]):.3f}")
    print(f"\n{'type':<14} {'n':>3} {'old':>6} {'new':>6} {'eir':>6}")
    types = sorted(set(r["type"] for r in rows))
    for t in types:
        sub = [r for r in rows if r["type"] == t]
        eir = mean([r["eir"] for r in sub])
        print(f"{t:<14} {len(sub):>3} {mean([r['old'] for r in sub]):>6.2f} "
              f"{mean([r['new'] for r in sub]):>6.2f} "
              f"{(eir if eir is not None else float('nan')):>6.2f}")


if __name__ == "__main__":
    main()
