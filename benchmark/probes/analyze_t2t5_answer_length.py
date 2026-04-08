"""
Stat sur la longueur des reponses T2 avant/apres.
Objectif : confirmer que la baisse de claim coverage est expliquee par la
compression des reponses post-B7 (durcissement du prompt TENSION).
"""
import json
from statistics import mean, median

PRE_PATH = "/data/benchmark/results/t2t5_run_20260404_074418_V3_MODES_VS_RAG.json"
POST_PATH = "/data/benchmark/results/t2t5_run_20260408_065401_POST_PerspectiveLayer_v3.json"


def main():
    pre = json.load(open(PRE_PATH))
    post = json.load(open(POST_PATH))
    pre_by = {s["question_id"]: s for s in pre["per_sample"]}
    post_by = {s["question_id"]: s for s in post["per_sample"]}

    common = sorted(set(pre_by) & set(post_by))
    t2 = [q for q in common if pre_by[q]["evaluation"].get("task_type") == "T2"]

    # Note : le champ "answer" est tronque a 500 chars dans le rapport,
    # mais "answer_length" porte la vraie longueur totale.
    pre_lens = [pre_by[q].get("answer_length", 0) for q in t2]
    post_lens = [post_by[q].get("answer_length", 0) for q in t2]

    print(f"=== Longueur des reponses T2 (n={len(t2)}) ===")
    print()
    print(f"{'':<12} {'PRE':>10} {'POST':>10} {'Delta':>10}")
    print(f"{'mean':<12} {mean(pre_lens):>10.0f} {mean(post_lens):>10.0f} {mean(post_lens)-mean(pre_lens):>+10.0f}")
    print(f"{'median':<12} {median(pre_lens):>10.0f} {median(post_lens):>10.0f} {median(post_lens)-median(pre_lens):>+10.0f}")
    print(f"{'min':<12} {min(pre_lens):>10} {min(post_lens):>10}")
    print(f"{'max':<12} {max(pre_lens):>10} {max(post_lens):>10}")

    # Ratio
    print()
    ratio = mean(post_lens) / mean(pre_lens)
    print(f"Ratio moyen POST/PRE : {ratio:.3f} ({(1-ratio)*100:.1f}% de compression)")

    # Par question : combien ont raccourci, combien ont rallonge ?
    shorter = sum(1 for a, b in zip(pre_lens, post_lens) if b < a)
    longer = sum(1 for a, b in zip(pre_lens, post_lens) if b > a)
    same = sum(1 for a, b in zip(pre_lens, post_lens) if b == a)
    print()
    print(f"Questions dont la reponse est plus courte POST : {shorter} ({100*shorter/len(t2):.1f}%)")
    print(f"Questions dont la reponse est plus longue POST : {longer} ({100*longer/len(t2):.1f}%)")
    print(f"Questions identiques : {same}")

    # Correlation : est-ce que la baisse de longueur correlees avec la baisse de claim coverage ?
    print()
    print("=== Correlation baisse longueur / baisse claim coverage ===")
    deltas = []
    for q in t2:
        len_delta = post_by[q].get("answer_length", 0) - pre_by[q].get("answer_length", 0)
        cov_delta = (
            post_by[q]["evaluation"].get("claim1_coverage", 0)
            + post_by[q]["evaluation"].get("claim2_coverage", 0)
            - pre_by[q]["evaluation"].get("claim1_coverage", 0)
            - pre_by[q]["evaluation"].get("claim2_coverage", 0)
        )
        deltas.append((len_delta, cov_delta))

    # Corr simple (Pearson-like)
    n = len(deltas)
    sum_x = sum(d[0] for d in deltas)
    sum_y = sum(d[1] for d in deltas)
    sum_xy = sum(d[0]*d[1] for d in deltas)
    sum_x2 = sum(d[0]*d[0] for d in deltas)
    sum_y2 = sum(d[1]*d[1] for d in deltas)
    num = n*sum_xy - sum_x*sum_y
    denom = ((n*sum_x2 - sum_x**2) * (n*sum_y2 - sum_y**2)) ** 0.5
    corr = num/denom if denom > 0 else 0
    print(f"Correlation (delta_length, delta_coverage): {corr:.4f}")
    print(f"  (proche de +1 = plus la reponse raccourcit, plus la couverture baisse)")


if __name__ == "__main__":
    main()
