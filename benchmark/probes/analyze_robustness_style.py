"""
Compare le style des reponses (headers / demarrage direct) entre
Robustness V17 (02/04) et POST_PerspectiveLayer (07/04).

Comme les answers sont tronquees a 500 chars, on ne peut pas mesurer
la compression totale, mais on peut detecter le changement de style
induit par le durcissement B7.
"""
import json

PRE = "/app/data/benchmark/results/robustness_run_20260402_140940_V17_PREMISE_VERIF.json"
POST = "/app/data/benchmark/results/robustness_run_20260407_131617_POST_PerspectiveLayer.json"


def starts_with_header(answer):
    if not answer:
        return False
    first_line = answer.lstrip().split("\n")[0].strip()
    if first_line.startswith("#"):
        return True
    for kw in ("Reponse", "Réponse", "Synthese", "Synthèse", "Analyse"):
        if first_line.lower().startswith(kw.lower()):
            return True
    return False


def main():
    pre = json.load(open(PRE))
    post = json.load(open(POST))

    pre_by = {s["question_id"]: s for s in pre["per_sample"]}
    post_by = {s["question_id"]: s for s in post["per_sample"]}
    common = sorted(set(pre_by) & set(post_by))

    pre_headers = sum(1 for q in common if starts_with_header(pre_by[q].get("answer", "")))
    post_headers = sum(1 for q in common if starts_with_header(post_by[q].get("answer", "")))

    print(f"=== Reponses qui commencent par un header (n={len(common)}) ===")
    print(f"PRE  (02/04 V17 pre-B7)      : {pre_headers:>3} ({100*pre_headers/len(common):.1f}%)")
    print(f"POST (07/04 post-Perspective): {post_headers:>3} ({100*post_headers/len(common):.1f}%)")
    print()

    # Par categorie
    cats = sorted(set(pre_by[q].get("category", "?") for q in common))
    print(f"=== Par categorie (n questions | PRE headers | POST headers | score PRE | score POST) ===")
    print(f"{'category':<25} {'n':>4} {'PRE_h':>6} {'POST_h':>7} {'score_PRE':>11} {'score_POST':>12}")
    for cat in cats:
        cat_q = [q for q in common if pre_by[q].get("category") == cat]
        pre_h = sum(1 for q in cat_q if starts_with_header(pre_by[q].get("answer", "")))
        post_h = sum(1 for q in cat_q if starts_with_header(post_by[q].get("answer", "")))
        score_field = f"{cat}_score"
        pre_score = pre["scores"].get(score_field)
        post_score = post["scores"].get(score_field)
        pre_str = f"{pre_score:.4f}" if isinstance(pre_score, (int, float)) else str(pre_score)
        post_str = f"{post_score:.4f}" if isinstance(post_score, (int, float)) else str(post_score)
        print(f"{cat:<25} {len(cat_q):>4} {pre_h:>6} {post_h:>7} {pre_str:>11} {post_str:>12}")

    # Echantillon textuel
    print()
    print(f"=== Echantillon : 3 questions causal_why (regression -37% constatee) ===")
    causal_q = [q for q in common if pre_by[q].get("category") == "causal_why"][:3]
    for q in causal_q:
        print()
        print(f"QID: {q}")
        print(f"Question: {pre_by[q].get('question','')[:100]}")
        print(f"PRE answer (premiers 300 chars):")
        print(f"  {pre_by[q].get('answer','')[:300]!r}")
        print(f"POST answer (premiers 300 chars):")
        print(f"  {post_by[q].get('answer','')[:300]!r}")


if __name__ == "__main__":
    main()
