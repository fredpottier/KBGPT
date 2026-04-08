"""
Analyse de la deviation entre le jugement du LLM-juge (gpt-4o-mini avec
judge_reason) et mon jugement qualitatif direct sur les reponses OSMOSIS.

Objectif : identifier systematiquement les cas ou le juge note bas alors
que la reponse repond correctement a la question, et inversement. Mesurer
le biais global du juge.

Utilise le rapport POST_JUDGE_FIX qui contient :
- reponses completes (pas de troncature a 500)
- judge_reason (raisonnement du juge en 1 phrase)
"""
import json
import sys
from statistics import mean

REPORT = "/app/data/benchmark/results/robustness_run_20260408_151547_POST_JUDGE_FIX.json"

CATEGORIES_TO_ANALYZE = ("causal_why", "conditional", "temporal_evolution")
MAX_PER_CAT = 7  # limit sample output


def main():
    d = json.load(open(REPORT))
    samples = d["per_sample"]

    by_cat = {}
    for s in samples:
        cat = s.get("category", "?")
        by_cat.setdefault(cat, []).append(s)

    for cat in CATEGORIES_TO_ANALYZE:
        cs = by_cat.get(cat, [])
        print("=" * 100)
        print(f"CATEGORY: {cat}  (n={len(cs)}, avg score={mean(s.get('evaluation',{}).get('score',0) for s in cs):.3f})")
        print("=" * 100)

        # Sort by score ascending (pires en premier)
        cs_sorted = sorted(cs, key=lambda s: s.get("evaluation", {}).get("score", 0))

        for s in cs_sorted[:MAX_PER_CAT]:
            ev = s.get("evaluation", {})
            score = ev.get("score", 0)
            reason = ev.get("judge_reason", "")
            judge_raw = ev.get("judge_raw", "")
            qid = s.get("question_id", "?")
            question = s.get("question", "")
            answer = s.get("answer", "") or ""

            print()
            print(f"─── {qid}  score={score:.2f} ────────────────────────")
            print(f"Q: {question[:140]}")
            print(f"JUDGE REASON: {reason}")
            print(f"JUDGE RAW: {judge_raw[:200]!r}")
            print(f"ANSWER LENGTH: {len(answer)} chars")
            print(f"ANSWER (first 600 chars):")
            print(f"  {answer[:600]}")
            if len(answer) > 600:
                print(f"  [...{len(answer)-600} chars omitted]")
        print()


if __name__ == "__main__":
    main()
