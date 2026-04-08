"""
Re-juge hors-ligne un rapport Robustness existant.

Pourquoi :
---------
Le LLM-juge de Robustness a ete silencieusement casse pendant 5 jours
(fallback foireux vers OSMOSIS_SYNTHESIS_MODEL=claude-haiku via le client
OpenAI qui plantait a chaque appel). Les runs POST_PL, B8, B9 et JUDGE_FIX
ont tous utilise le fallback keyword, pas le vrai LLM-juge.

Le fix du bug est dans robustness_diagnostic.py (defaut hardcode gpt-4o-mini,
warning visible en cas d'echec, stats en fin de run). Mais on n'a pas besoin
de relancer les 246 questions via l'API OSMOSIS (50 min) : les reponses sont
deja stockees completes dans le dernier rapport JUDGE_FIX. On peut juste
re-juger offline, ce qui prend 5 min et coute ~$0.05.

Ce script :
1. Charge un rapport existant (avec reponses completes)
2. Pour chaque question dans LLM_JUDGE_CATEGORIES, rappelle le LLM-juge
   (avec la nouvelle logique : defaut gpt-4o-mini, pre-traitement [[SOURCE:...]],
    troncature 3000 chars, format SCORE+REASON)
3. Remplace l'evaluation par celle du LLM-juge
4. Ecrit un nouveau rapport tagge `_RESCORED`
"""
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, "/app")
from benchmark.evaluators.robustness_diagnostic import (
    evaluate_with_llm_judge,
    aggregate_scores,
    LLM_JUDGE_CATEGORIES,
    _get_llm_judge_client,
)

INPUT_PATH = "/app/data/benchmark/results/robustness_run_20260408_151547_POST_JUDGE_FIX.json"
QUESTIONS_PATH = "/app/benchmark/questions/task6_robustness.json"
OUTPUT_DIR = Path("/app/data/benchmark/results")


def main():
    print(f"Loading: {INPUT_PATH}")
    d = json.load(open(INPUT_PATH))
    samples = d["per_sample"]
    print(f"Total samples: {len(samples)}")

    # Charger ground_truth depuis le fichier source des questions
    # (pas stocke dans le rapport per_sample)
    print(f"Loading ground truth: {QUESTIONS_PATH}")
    qs_data = json.load(open(QUESTIONS_PATH))
    qs_list = qs_data if isinstance(qs_data, list) else qs_data.get("questions", [])
    gt_by_qid = {q["question_id"]: q.get("ground_truth", {}) for q in qs_list}
    print(f"Ground truth loaded for {len(gt_by_qid)} questions")

    client = _get_llm_judge_client()
    if not client:
        print("ERROR: No LLM judge client available. Check OPENAI_API_KEY.")
        return 1

    rescored = 0
    skipped_no_llm_cat = 0
    skipped_no_answer = 0
    failed = 0

    for i, s in enumerate(samples, 1):
        category = s.get("category", "?")
        if category not in LLM_JUDGE_CATEGORIES:
            skipped_no_llm_cat += 1
            continue

        answer = s.get("answer", "") or ""
        if not answer:
            skipped_no_answer += 1
            continue

        question = s.get("question", "")
        qid = s.get("question_id", "")
        ground_truth = gt_by_qid.get(qid, {})

        new_eval = evaluate_with_llm_judge(answer, question, category, ground_truth)
        if new_eval is None:
            failed += 1
            continue

        # Preserve old eval under a different key for comparison
        s["evaluation_keyword_old"] = s.get("evaluation", {}).copy()
        s["evaluation"] = new_eval
        rescored += 1

        if i % 25 == 0:
            print(f"  [{i}/{len(samples)}] rescored={rescored} failed={failed}")

    print()
    print(f"Rescored: {rescored}")
    print(f"Skipped (not in LLM_JUDGE_CATEGORIES): {skipped_no_llm_cat}")
    print(f"Skipped (no answer): {skipped_no_answer}")
    print(f"Failed: {failed}")

    if rescored == 0:
        print("ERROR: 0 questions rescored — aborting save")
        return 2

    # Recompute aggregated scores
    new_scores = aggregate_scores(samples)
    d["scores"] = new_scores
    d["tag"] = (d.get("tag") or "") + "_RESCORED"
    d["description"] = (d.get("description") or "") + " | Rescored offline with fixed LLM judge (08/04 after discovery of 5-day silent bug)"

    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    output_path = OUTPUT_DIR / f"robustness_run_{ts}_POST_JUDGE_FIX_RESCORED.json"
    output_path.write_text(json.dumps(d, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\nSaved: {output_path}")
    print(f"\nNew scores: {json.dumps(new_scores, indent=2)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
