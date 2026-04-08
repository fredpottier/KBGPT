"""
Analyse des 25 questions temporal_evolution dans le rapport RESCORED.

Objectif : identifier pourquoi temporal_evolution reste a 0.504 (-17 points
vs baseline V17) alors que les autres categories sont OK ou meilleures.

Etapes :
1. Filtrer les reponses potentiellement vides/erronees (limite budget Haiku)
2. Compter combien de questions ont regresse (score LLM < 0.6)
3. Lire le judge_reason pour chacune
4. Proposer une hypothese : retrieval, synthese, enrichissement KG ?
"""
import json
import sys
from statistics import mean

RESCORED = "/app/data/benchmark/results/robustness_run_20260408_161824_POST_JUDGE_FIX_RESCORED.json"
PRE_V17 = "/app/data/benchmark/results/robustness_run_20260402_140940_V17_PREMISE_VERIF.json"


def is_answer_suspect(answer: str) -> tuple[bool, str]:
    """Detecte si la reponse semble tronquee/vide/erronee."""
    if not answer:
        return True, "empty"
    if len(answer) < 100:
        return True, f"too_short ({len(answer)} chars)"
    lower = answer.lower()
    err_markers = [
        "rate limit", "quota exceeded", "credit balance", "api error",
        "erreur:", "error:", "429", "insufficient", "anthropic error",
    ]
    for marker in err_markers:
        if marker in lower:
            return True, f"error_marker: {marker}"
    return False, ""


def main():
    rescored = json.load(open(RESCORED))
    pre = json.load(open(PRE_V17))

    pre_by = {s["question_id"]: s for s in pre["per_sample"]}
    r_by = {s["question_id"]: s for s in rescored["per_sample"]}

    te_samples = [s for s in rescored["per_sample"] if s.get("category") == "temporal_evolution"]
    print(f"temporal_evolution samples : {len(te_samples)}")
    print()

    # Step 1 : filter suspect answers
    print("=" * 100)
    print("STEP 1 : Reponses suspectes (potentielles erreurs Haiku)")
    print("=" * 100)
    suspects = []
    clean = []
    for s in te_samples:
        suspect, reason = is_answer_suspect(s.get("answer", ""))
        if suspect:
            suspects.append((s, reason))
        else:
            clean.append(s)
    print(f"Suspects : {len(suspects)}")
    print(f"Clean    : {len(clean)}")
    for s, reason in suspects:
        print(f"  {s['question_id']}: {reason}")
    print()

    # Step 2 : score distribution on clean samples
    print("=" * 100)
    print("STEP 2 : Distribution des scores LLM (clean samples only)")
    print("=" * 100)
    good = [s for s in clean if s.get("evaluation", {}).get("score", 0) >= 0.7]
    medium = [s for s in clean if 0.4 <= s.get("evaluation", {}).get("score", 0) < 0.7]
    bad = [s for s in clean if s.get("evaluation", {}).get("score", 0) < 0.4]
    avg = mean(s.get("evaluation", {}).get("score", 0) for s in clean) if clean else 0
    print(f"Good (>=0.7)  : {len(good)}")
    print(f"Medium        : {len(medium)}")
    print(f"Bad (<0.4)    : {len(bad)}")
    print(f"Average       : {avg:.3f}")
    print(f"PRE V17 avg   : {pre['scores'].get('temporal_evolution_score', 0):.3f}")
    print()

    # Step 3 : worst cases with judge reason
    print("=" * 100)
    print("STEP 3 : Les 10 pires cas (score LLM le plus bas)")
    print("=" * 100)
    worst = sorted(clean, key=lambda s: s.get("evaluation", {}).get("score", 0))[:10]
    for s in worst:
        ev = s["evaluation"]
        score = ev.get("score", 0)
        reason = ev.get("judge_reason", "")
        raw = ev.get("judge_raw", "")
        qid = s["question_id"]
        pre_s = pre_by.get(qid, {})
        pre_score = pre_s.get("evaluation", {}).get("score", 0) if pre_s else "?"
        print()
        print(f"── {qid}  LLM_new={score:.2f}  PRE_V17(keyword)={pre_score}")
        print(f"Q: {s.get('question','')[:140]}")
        print(f"JUDGE REASON: {reason}")
        if not reason and raw:
            print(f"JUDGE RAW (parse failed?): {raw[:200]!r}")
        # Extract the first sentence of the answer to see how it starts
        ans = s.get("answer", "") or ""
        print(f"Answer len: {len(ans)} chars")
        print(f"Answer first 600 chars:")
        print(f"  {ans[:600]}")
    print()


if __name__ == "__main__":
    main()
