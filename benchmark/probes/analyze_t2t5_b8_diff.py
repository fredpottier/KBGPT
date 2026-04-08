"""
Compare T2/T5 pre-Perspective (04/04) vs POST_PerspectiveLayer (08/04 matin)
vs POST_PROMPT_B8 (08/04 apres-midi) — sur les memes metriques et avec
l'analyse de longueur des reponses qui avait revele -23% de compression.
"""
import json
from statistics import mean, median

PRE = "/data/benchmark/results/t2t5_run_20260404_074418_V3_MODES_VS_RAG.json"
POST_PL = "/data/benchmark/results/t2t5_run_20260408_065401_POST_PerspectiveLayer_v3.json"
POST_B8 = "/data/benchmark/results/t2t5_run_20260408_105221_POST_PROMPT_B8.json"


def load(path, label):
    d = json.load(open(path))
    return {
        "label": label,
        "by_id": {s["question_id"]: s for s in d["per_sample"]},
        "scores": d.get("scores", {}),
    }


def main():
    pre = load(PRE, "PRE V3 (04/04)")
    post_pl = load(POST_PL, "POST Perspective (08/04 matin)")
    post_b8 = load(POST_B8, "POST_PROMPT_B8 (08/04 apres-midi)")

    common = sorted(
        set(pre["by_id"]) & set(post_pl["by_id"]) & set(post_b8["by_id"])
    )
    t2_common = [
        q for q in common
        if pre["by_id"][q]["evaluation"].get("task_type") == "T2"
    ]

    print(f"T2 common across 3 runs: {len(t2_common)}")
    print()

    # Scores globaux
    metrics = [
        "both_sides_surfaced",
        "tension_mentioned",
        "both_sources_cited",
        "chain_coverage",
        "multi_doc_cited",
        "proactive_detection",
    ]

    print("=" * 78)
    print("Scores agreges (tout T2/T5 confondu) :")
    print("=" * 78)
    print(f"{'Metric':<25} {'PRE':>10} {'POST_PL':>10} {'POST_B8':>10} {'PL->B8':>10}")
    for m in metrics:
        p = pre["scores"].get(m)
        pl = post_pl["scores"].get(m)
        b8 = post_b8["scores"].get(m)
        if p is None or pl is None or b8 is None:
            continue
        delta_b8 = b8 - pl
        arrow = " ^" if delta_b8 > 0.01 else (" v" if delta_b8 < -0.01 else "  ")
        print(f"{m:<25} {p:>10.4f} {pl:>10.4f} {b8:>10.4f} {delta_b8:>+10.4f}{arrow}")
    print()

    # Claim coverage per-sample (la cause racine identifiee)
    print("=" * 78)
    print("Claim coverage moyen (sur T2 common n={}) :".format(len(t2_common)))
    print("=" * 78)
    for key in ("claim1_coverage", "claim2_coverage"):
        p_vals = [pre["by_id"][q]["evaluation"].get(key, 0) for q in t2_common]
        pl_vals = [post_pl["by_id"][q]["evaluation"].get(key, 0) for q in t2_common]
        b8_vals = [post_b8["by_id"][q]["evaluation"].get(key, 0) for q in t2_common]
        p_avg = mean(p_vals)
        pl_avg = mean(pl_vals)
        b8_avg = mean(b8_vals)
        print(f"{key:<25} PRE={p_avg:.4f}  POST_PL={pl_avg:.4f}  POST_B8={b8_avg:.4f}")
        print(f"{'':<25} delta PL->B8 = {b8_avg-pl_avg:+.4f}  (recovery vs PRE: {b8_avg-p_avg:+.4f})")
    print()

    # Longueur des reponses (la mesure qui avait revele le probleme de compression)
    print("=" * 78)
    print("Longueur des reponses T2 :")
    print("=" * 78)
    pre_lens = [pre["by_id"][q].get("answer_length", 0) for q in t2_common]
    pl_lens = [post_pl["by_id"][q].get("answer_length", 0) for q in t2_common]
    b8_lens = [post_b8["by_id"][q].get("answer_length", 0) for q in t2_common]

    print(f"{'':<15} {'PRE':>10} {'POST_PL':>10} {'POST_B8':>10}")
    print(f"{'mean':<15} {mean(pre_lens):>10.0f} {mean(pl_lens):>10.0f} {mean(b8_lens):>10.0f}")
    print(f"{'median':<15} {median(pre_lens):>10.0f} {median(pl_lens):>10.0f} {median(b8_lens):>10.0f}")
    print(f"{'min':<15} {min(pre_lens):>10} {min(pl_lens):>10} {min(b8_lens):>10}")
    print(f"{'max':<15} {max(pre_lens):>10} {max(pl_lens):>10} {max(b8_lens):>10}")
    print()
    ratio_pl = mean(pl_lens) / mean(pre_lens)
    ratio_b8 = mean(b8_lens) / mean(pre_lens)
    print(f"Ratio POST_PL vs PRE : {ratio_pl:.3f} ({(1-ratio_pl)*100:+.1f}% de compression)")
    print(f"Ratio POST_B8 vs PRE : {ratio_b8:.3f} ({(1-ratio_b8)*100:+.1f}% de compression)")

    # Questions individuelles - evolution PL -> B8
    print()
    print("=" * 78)
    print("Evolution individuelle PL -> B8 sur both_sources_cited :")
    print("=" * 78)
    improved_b8 = 0
    degraded_b8 = 0
    stable_b8 = 0
    for q in t2_common:
        pl = post_pl["by_id"][q]["evaluation"].get("both_sources_cited", 0)
        b8 = post_b8["by_id"][q]["evaluation"].get("both_sources_cited", 0)
        if b8 > pl:
            improved_b8 += 1
        elif b8 < pl:
            degraded_b8 += 1
        else:
            stable_b8 += 1
    print(f"  Improved B8: {improved_b8} ({100*improved_b8/len(t2_common):.1f}%)")
    print(f"  Degraded B8: {degraded_b8} ({100*degraded_b8/len(t2_common):.1f}%)")
    print(f"  Stable:      {stable_b8} ({100*stable_b8/len(t2_common):.1f}%)")

    # Et vs PRE?
    improved_vs_pre = 0
    still_below_pre = 0
    for q in t2_common:
        pr = pre["by_id"][q]["evaluation"].get("both_sources_cited", 0)
        b8 = post_b8["by_id"][q]["evaluation"].get("both_sources_cited", 0)
        if b8 >= pr:
            improved_vs_pre += 1
        else:
            still_below_pre += 1
    print(f"  B8 >= PRE  : {improved_vs_pre} ({100*improved_vs_pre/len(t2_common):.1f}%)")
    print(f"  B8 < PRE   : {still_below_pre} ({100*still_below_pre/len(t2_common):.1f}%)")


if __name__ == "__main__":
    main()
