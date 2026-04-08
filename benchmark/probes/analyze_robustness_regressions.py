"""
Analyse detaillee des regressions persistantes sur Robustness POST_PROMPT_B8 :
categories causal_why et temporal_evolution.

Objectif : determiner si le probleme est dans la synthese (LLM) ou dans
le retrieval (chunks). Hypothese a tester : le LLM POST exprime frequemment
qu'il n'a pas assez d'information pour les questions qui regressent.

Compare les reponses V17 vs POST_PROMPT_B8 pour les questions qui ont baisse
de score dans ces deux categories.
"""
import json
import re

PRE_PATH = "/app/data/benchmark/results/robustness_run_20260402_140940_V17_PREMISE_VERIF.json"
POST_PATH = "/app/data/benchmark/results/robustness_run_20260408_083959_POST_PROMPT_B8.json"

# Patterns indiquant que le LLM signale un manque d'information
IDK_PATTERNS = [
    r"ne fournissent pas",
    r"ne contiennent pas",
    r"ne permet(ten)?t pas",
    r"pas (suffisamment|assez) d['e]",
    r"aucune? (information|indication|mention|precision)",
    r"ne pr[eé]cisent? pas",
    r"non d[eé]taill[eé]",
    r"absence d['e] (information|precision)",
    r"impossible de (repondre|determiner)",
    r"ne (dit|specifie|mentionne|indique|couvre)",
    r"les documents ne",
    r"non disponible",
    r"les sources n['e]",
    r"ne sont pas couvert",
    r"non documente",
    r"n'(offrent|apportent|precisent) pas",
]
RE_IDK = re.compile("|".join(f"({p})" for p in IDK_PATTERNS), re.IGNORECASE)


def has_idk(text):
    if not text:
        return False
    return bool(RE_IDK.search(text))


def main():
    pre = json.load(open(PRE_PATH))
    post = json.load(open(POST_PATH))
    pre_by = {s["question_id"]: s for s in pre["per_sample"]}
    post_by = {s["question_id"]: s for s in post["per_sample"]}

    # Filter questions that have score in both
    def score_of(s):
        e = s.get("evaluation", {})
        return e.get("score") if isinstance(e.get("score"), (int, float)) else None

    for cat in ("causal_why", "conditional", "temporal_evolution", "negation"):
        print("=" * 78)
        print(f"=== Category: {cat} ===")
        cat_qs = [q for q in sorted(set(pre_by) & set(post_by))
                  if pre_by[q].get("category") == cat and post_by[q].get("category") == cat]

        regressed = []
        improved = []
        for q in cat_qs:
            sp = score_of(pre_by[q])
            so = score_of(post_by[q])
            if sp is None or so is None:
                continue
            if so < sp - 0.05:  # meaningful regression
                regressed.append((q, sp, so))
            elif so > sp + 0.05:
                improved.append((q, sp, so))

        print(f"Total: {len(cat_qs)}, regressed (>0.05 drop): {len(regressed)}, improved: {len(improved)}")
        print()

        # Count idk patterns in regressed PRE vs POST answers
        pre_idk_count = 0
        post_idk_count = 0
        for q, sp, so in regressed:
            pre_ans = pre_by[q].get("answer", "") or ""
            post_ans = post_by[q].get("answer", "") or ""
            if has_idk(pre_ans):
                pre_idk_count += 1
            if has_idk(post_ans):
                post_idk_count += 1

        if regressed:
            print(f"Sur les {len(regressed)} questions regressees :")
            print(f"  PRE : {pre_idk_count} reponses avec pattern 'manque info' ({100*pre_idk_count/len(regressed):.0f}%)")
            print(f"  POST: {post_idk_count} reponses avec pattern 'manque info' ({100*post_idk_count/len(regressed):.0f}%)")
            print()

        # Dump 3 worst regressions
        regressed_sorted = sorted(regressed, key=lambda x: x[2] - x[1])
        for q, sp, so in regressed_sorted[:3]:
            print(f"--- {q} (score {sp:.2f} -> {so:.2f}) ---")
            print(f"Q: {pre_by[q].get('question','')[:120]}")
            print(f"PRE answer (first 400 chars):")
            pre_ans = pre_by[q].get("answer", "") or ""
            print(f"  {pre_ans[:400]}")
            print(f"POST answer (first 400 chars):")
            post_ans = post_by[q].get("answer", "") or ""
            print(f"  {post_ans[:400]}")
            print(f"PRE idk: {has_idk(pre_ans)}  POST idk: {has_idk(post_ans)}")
            print()
        print()


if __name__ == "__main__":
    main()
