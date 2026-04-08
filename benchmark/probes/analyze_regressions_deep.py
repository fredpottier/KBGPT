"""
Investigation des regressions Robustness qui n'ont PAS le pattern "manque info".

Les regressions "manque info" sont expliquees (effet de bord regle #4 du fix B8
qui induit un meta-commentaire sur les sources). Mais il reste 36 questions
qui ont regresse sans ce pattern. Que partagent-elles ?

Hypotheses a verifier :
1. Toutes commencent par un header meta (#, ##) malgre l'interdiction
2. Les reponses sont systematiquement plus longues ou plus courtes
3. Elles ont un style stereotype commun (meta discussion, reformulation question)
4. Elles portent sur des sujets techniques specifiques
5. Le LLM repete la question en titre au lieu de repondre
"""
import json
import re
from collections import Counter, defaultdict
from statistics import mean, median

PRE_PATH = "/app/data/benchmark/results/robustness_run_20260402_140940_V17_PREMISE_VERIF.json"
POST_PATH = "/app/data/benchmark/results/robustness_run_20260408_083959_POST_PROMPT_B8.json"

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
    r"faible (couverture|pertinence)",
    r"avertissement pr[eé]alable",
    r"constat pr[eé]liminaire",
    r"note sur la pertinence",
    r"pertinence faible",
    r"ne traitent pas",
    r"absent du corpus",
    r"pas d[ae] donn[eé]es",
]
RE_IDK = re.compile("|".join(f"(?:{p})" for p in IDK_PATTERNS), re.IGNORECASE)

CATS = ("causal_why", "conditional", "temporal_evolution")


def has_idk(text):
    if not text:
        return False
    return bool(RE_IDK.search(text))


def first_line(text):
    if not text:
        return ""
    return text.lstrip().split("\n")[0].strip()


def starts_with_header(text):
    fl = first_line(text)
    return fl.startswith("#")


def starts_with_meta_header(text):
    """Header qui reformule la question ou introduit la reponse."""
    fl = first_line(text).lower()
    if not fl.startswith("#"):
        return False
    meta_kw = [
        "reponse", "réponse", "analyse", "synthese", "synthèse",
        "question", "comprendre", "comprehension", "introduction",
        "contexte", "presentation", "présentation"
    ]
    return any(kw in fl for kw in meta_kw)


def extract_headers(text):
    """Returne tous les headers (lignes commencant par #)."""
    if not text:
        return []
    return [l.strip() for l in text.split("\n") if l.lstrip().startswith("#")]


def main():
    pre = json.load(open(PRE_PATH))
    post = json.load(open(POST_PATH))
    pre_by = {s["question_id"]: s for s in pre["per_sample"]}
    post_by = {s["question_id"]: s for s in post["per_sample"]}

    def score_of(s):
        e = s.get("evaluation", {})
        return e.get("score") if isinstance(e.get("score"), (int, float)) else None

    # Collect all regressions across the 3 categories
    all_regressed = []
    for cat in CATS:
        cat_qs = [q for q in sorted(set(pre_by) & set(post_by))
                  if pre_by[q].get("category") == cat]
        for q in cat_qs:
            sp = score_of(pre_by[q])
            so = score_of(post_by[q])
            if sp is None or so is None:
                continue
            if so < sp - 0.05:
                all_regressed.append({
                    "qid": q,
                    "cat": cat,
                    "pre_score": sp,
                    "post_score": so,
                    "delta": so - sp,
                    "question": pre_by[q].get("question", ""),
                    "pre_answer": pre_by[q].get("answer", "") or "",
                    "post_answer": post_by[q].get("answer", "") or "",
                })

    print(f"Total regressions sur {CATS} : {len(all_regressed)}")

    # Separate IDK vs non-IDK
    idk = [r for r in all_regressed if has_idk(r["post_answer"])]
    non_idk = [r for r in all_regressed if not has_idk(r["post_answer"])]
    print(f"  avec pattern 'manque info' (explique par regle #4 du fix B8) : {len(idk)}")
    print(f"  SANS pattern 'manque info' (a investiguer) : {len(non_idk)}")
    print()

    if not non_idk:
        return

    # ============================================================
    # Analyse des 36 regressions SANS pattern "manque info"
    # ============================================================
    print("=" * 78)
    print(f"INVESTIGATION : {len(non_idk)} regressions SANS pattern 'manque info'")
    print("=" * 78)
    print()

    # H1 : Les reponses POST commencent-elles par un header (meta ou pas) ?
    pre_header_count = sum(1 for r in non_idk if starts_with_header(r["pre_answer"]))
    post_header_count = sum(1 for r in non_idk if starts_with_header(r["post_answer"]))
    post_meta_header = sum(1 for r in non_idk if starts_with_meta_header(r["post_answer"]))
    print(f"H1. Header au debut de la reponse :")
    print(f"  PRE  : {pre_header_count}/{len(non_idk)} ({100*pre_header_count/len(non_idk):.0f}%)")
    print(f"  POST : {post_header_count}/{len(non_idk)} ({100*post_header_count/len(non_idk):.0f}%)")
    print(f"  POST qui sont un header *meta* (reformule la question) : {post_meta_header}/{len(non_idk)} ({100*post_meta_header/len(non_idk):.0f}%)")
    print()

    # H2 : Comparaison des longueurs (attention, tronquees a 500 chars)
    pre_lens = [len(r["pre_answer"]) for r in non_idk]
    post_lens = [len(r["post_answer"]) for r in non_idk]
    # Detecter les reponses tronquees a exactement 500 chars (vraies reponses plus longues)
    pre_trunc = sum(1 for l in pre_lens if l >= 499)
    post_trunc = sum(1 for l in post_lens if l >= 499)
    print(f"H2. Longueur visible (reponses tronquees a 500 chars) :")
    print(f"  PRE  : mean={mean(pre_lens):.0f}, median={median(pre_lens):.0f}, truncated={pre_trunc}/{len(non_idk)}")
    print(f"  POST : mean={mean(post_lens):.0f}, median={median(post_lens):.0f}, truncated={post_trunc}/{len(non_idk)}")
    print()

    # H3 : Patterns stereotypes dans le debut de reponse POST
    print("H3. Patterns stereotypes en debut de reponse POST (5 premiers mots) :")
    first_words = Counter()
    for r in non_idk:
        words = " ".join(r["post_answer"].lstrip().split()[:5])
        first_words[words] += 1
    for phrase, count in first_words.most_common(10):
        if count >= 2:
            print(f"  {count}x  : {phrase}")
    print()

    # H4 : Le LLM repete la question dans le titre du header ?
    question_in_header = 0
    for r in non_idk:
        fl = first_line(r["post_answer"]).lower()
        if not fl.startswith("#"):
            continue
        q_words = set(re.findall(r"\w{4,}", r["question"].lower()))
        h_words = set(re.findall(r"\w{4,}", fl))
        overlap = len(q_words & h_words) / max(len(q_words), 1)
        if overlap >= 0.3:  # au moins 30% des mots de la question dans le header
            question_in_header += 1
    print(f"H4. Le header POST reformule-t-il la question (>=30% de mots en commun) ?")
    print(f"  {question_in_header}/{len(non_idk)} ({100*question_in_header/len(non_idk):.0f}%)")
    print()

    # H5 : Comparaison par categorie
    print("H5. Breakdown par categorie :")
    for cat in CATS:
        cat_non_idk = [r for r in non_idk if r["cat"] == cat]
        if not cat_non_idk:
            continue
        post_h = sum(1 for r in cat_non_idk if starts_with_header(r["post_answer"]))
        post_mh = sum(1 for r in cat_non_idk if starts_with_meta_header(r["post_answer"]))
        avg_delta = mean(r["delta"] for r in cat_non_idk)
        print(f"  {cat:<22} n={len(cat_non_idk):>3} | POST headers={post_h} (meta={post_mh}) | avg score delta={avg_delta:+.3f}")
    print()

    # H6 : Les 5 regressions les plus severes sans IDK — dump complet
    print("=" * 78)
    print("H6. Les 5 regressions les plus severes SANS pattern 'manque info' :")
    print("=" * 78)
    worst = sorted(non_idk, key=lambda r: r["delta"])[:5]
    for r in worst:
        print()
        print(f"QID: {r['qid']} ({r['cat']}) score {r['pre_score']:.2f} -> {r['post_score']:.2f} (delta {r['delta']:+.2f})")
        print(f"Q: {r['question'][:140]}")
        print(f"PRE answer first line : {first_line(r['pre_answer'])[:140]}")
        print(f"PRE answer (300 chars): {r['pre_answer'][:300]}")
        print()
        print(f"POST answer first line: {first_line(r['post_answer'])[:140]}")
        print(f"POST answer (300 chars): {r['post_answer'][:300]}")
        print()
        print("-" * 78)


if __name__ == "__main__":
    main()
