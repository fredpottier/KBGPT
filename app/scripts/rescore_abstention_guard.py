"""Re-score offline des benchs existants avec le garde-fou anti-overfit abstention.

Pour chaque question d'un run existant :
  - Si abstention ET question answerable (non false_premise) → 0.0 (anti-overfit)
  - Si abstention ET (unanswerable OU false_premise) → 1.0 (légitime)
  - Sinon → garde le judge_score LLM existant (inchangé)

Ne re-lance PAS le pipeline ni le LLM judge sur les non-abstentions.
Charge le gold-set pour answerability + false_premise.

Usage:
    python scripts/rescore_abstention_guard.py <run.json>
"""

from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path
from statistics import mean

ROOT = Path(__file__).resolve().parent.parent

_ABSTENTION_MARKERS = (
    "documents indexés contiennent des informations proches",
    "documents indexés ne",
    "aucune information",
    "no relevant claim",
    "ne peut être fournie",
    "prémisse que les documents",
    "risquerait d'être inexact",
)


def is_abstention(answer: str, mode: str) -> bool:
    if mode == "ABSTENTION":
        return True
    if not answer:
        return False
    low = answer.lower()
    return any(m.lower() in low for m in _ABSTENTION_MARKERS)


def main():
    run_path = Path(sys.argv[1]) if len(sys.argv) > 1 else \
        ROOT / "data/benchmark/a38_runtime_v6/run_20260525_090751.json"

    gold = {q["id"]: q for q in json.load(
        open(ROOT / "benchmark/questions/gold_set_a38_50q.json", encoding="utf-8"))}

    run = json.load(open(run_path, encoding="utf-8"))
    results = run["results_50q"]

    print(f"Re-scoring {run_path.name} ({len(results)} questions)")
    print("=" * 70)

    rescored = []
    changes = []
    for r in results:
        qid = r["id"]
        old_score = r["judge_score"]
        mode = r["run"].get("mode", "")
        answer = r["run"].get("answer_text", "")
        g = gold.get(qid, {}).get("ground_truth", {})
        answerability = g.get("answerability", "answerable")
        false_premise = g.get("false_premise", False)

        if is_abstention(answer, mode):
            legit = (answerability != "answerable") or bool(false_premise)
            new_score = 1.0 if legit else 0.0
            reason = "legit_abstention" if legit else "abstention_on_answerable→0"
        else:
            new_score = old_score  # LLM judge inchangé
            reason = "non_abstention_kept"

        if new_score != old_score:
            changes.append((qid, r["primary_type"], old_score, new_score, answerability, false_premise))

        rescored.append({**r, "judge_score_rescored": new_score, "rescore_reason": reason})

    # Agrégats
    def agg(key):
        by_type = {}
        for r in rescored:
            t = r["primary_type"]
            by_type.setdefault(t, []).append(r[key] if r[key] is not None else 0.0)
        return by_type

    print("\n=== C1 par type : ANCIEN -> RE-SCORÉ ===")
    old_by = agg("judge_score")
    new_by = agg("judge_score_rescored")
    for t in sorted(old_by):
        o = mean(old_by[t]); n = mean(new_by[t])
        flag = " ⬇" if n < o else (" ⬆" if n > o else "")
        print(f"  {t:14s} n={len(old_by[t]):2d}  {o:.3f} -> {n:.3f}{flag}")

    all_old = mean([s for r in rescored for s in [r['judge_score'] or 0.0]])
    all_new = mean([r['judge_score_rescored'] for r in rescored])
    print(f"\n  {'GLOBAL C1':14s}       {all_old:.3f} -> {all_new:.3f}")

    # Abstention stats
    n_abst = sum(1 for r in rescored if is_abstention(r['run'].get('answer_text',''), r['run'].get('mode','')))
    print(f"\n  Abstentions : {n_abst}/{len(rescored)} ({n_abst*2}%)")
    n_abst_penalized = sum(1 for c in changes if c[3] == 0.0)
    print(f"  Abstentions sur question answerable (pénalisées 1.0→0.0) : {n_abst_penalized}")

    print(f"\n=== Changements ({len(changes)}) ===")
    for qid, t, o, n, ans, fp in changes:
        print(f"  {qid:22s} {t:13s} {o}->{n}  answerability={ans} fp={fp}")


if __name__ == "__main__":
    main()
