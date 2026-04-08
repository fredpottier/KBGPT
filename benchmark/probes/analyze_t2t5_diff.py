"""
Analyse question par question de la régression both_sources_cited entre
le run T2/T5 du 04/04 (V3_MODES_VS_RAG, pre Perspective layer) et celui
du 08/04 (POST_PerspectiveLayer_v3).

Objectif : confirmer ou infirmer les hypothèses sur la cause du -13%.
"""
import json
import sys
from pathlib import Path

PRE_PATH = "/data/benchmark/results/t2t5_run_20260404_074418_V3_MODES_VS_RAG.json"
POST_PATH = "/data/benchmark/results/t2t5_run_20260408_065401_POST_PerspectiveLayer_v3.json"


def main():
    pre = json.load(open(PRE_PATH))
    post = json.load(open(POST_PATH))

    pre_by_id = {s["question_id"]: s for s in pre["per_sample"]}
    post_by_id = {s["question_id"]: s for s in post["per_sample"]}

    common = sorted(set(pre_by_id.keys()) & set(post_by_id.keys()))
    print(f"PRE questions: {len(pre_by_id)}")
    print(f"POST questions: {len(post_by_id)}")
    print(f"Common qids: {len(common)}")
    print(f"Only in PRE: {len(set(pre_by_id) - set(post_by_id))}")
    print(f"Only in POST: {len(set(post_by_id) - set(pre_by_id))}")

    t2_common = [q for q in common if pre_by_id[q]["evaluation"].get("task_type") == "T2"]
    print(f"T2 common: {len(t2_common)}")

    # Agrege
    improved, degraded, stable = [], [], []
    for qid in t2_common:
        a = pre_by_id[qid]["evaluation"].get("both_sources_cited", 0)
        b = post_by_id[qid]["evaluation"].get("both_sources_cited", 0)
        if b > a:
            improved.append((qid, a, b))
        elif b < a:
            degraded.append((qid, a, b))
        else:
            stable.append(qid)

    print()
    print(f"both_sources_cited (T2 common only):")
    print(f"  Improved: {len(improved):>3} ({100*len(improved)/len(t2_common):.1f}%)")
    print(f"  Degraded: {len(degraded):>3} ({100*len(degraded)/len(t2_common):.1f}%)")
    print(f"  Stable:   {len(stable):>3} ({100*len(stable)/len(t2_common):.1f}%)")

    pre_avg = sum(pre_by_id[q]["evaluation"].get("both_sources_cited", 0) for q in t2_common) / len(t2_common)
    post_avg = sum(post_by_id[q]["evaluation"].get("both_sources_cited", 0) for q in t2_common) / len(t2_common)
    print()
    print(f"PRE avg:  {pre_avg:.4f}")
    print(f"POST avg: {post_avg:.4f}")
    print(f"Delta:    {post_avg - pre_avg:+.4f}")

    # Echantillon des questions degradees — les 10 pires
    degraded_sorted = sorted(degraded, key=lambda x: x[2] - x[1])  # tri par pire regression
    print()
    print(f"=== 10 premieres regressions (pire en premier) ===")
    for qid, a, b in degraded_sorted[:10]:
        pre_s = pre_by_id[qid]
        post_s = post_by_id[qid]
        q_text = pre_s["question"][:120]
        pre_sources = pre_s.get("sources_used", [])
        post_sources = post_s.get("sources_used", [])
        pre_chunks = pre_s.get("chunks_retrieved", "?")
        post_chunks = post_s.get("chunks_retrieved", "?")
        print()
        print(f"QID: {qid}")
        print(f"  Question: {q_text}")
        print(f"  both_sources_cited PRE={a:.2f} POST={b:.2f}")
        print(f"  claim1_coverage PRE={pre_s['evaluation'].get('claim1_coverage',0):.2f} POST={post_s['evaluation'].get('claim1_coverage',0):.2f}")
        print(f"  claim2_coverage PRE={pre_s['evaluation'].get('claim2_coverage',0):.2f} POST={post_s['evaluation'].get('claim2_coverage',0):.2f}")
        print(f"  tension_mentioned PRE={pre_s['evaluation'].get('tension_mentioned',0):.2f} POST={post_s['evaluation'].get('tension_mentioned',0):.2f}")
        print(f"  both_sides_surfaced PRE={pre_s['evaluation'].get('both_sides_surfaced',0):.2f} POST={post_s['evaluation'].get('both_sides_surfaced',0):.2f}")
        print(f"  sources_used count PRE={len(pre_sources)} POST={len(post_sources)}")
        print(f"  chunks_retrieved PRE={pre_chunks} POST={post_chunks}")

    # Analyse croisee : parmi les degradees, combien ont perdu des sources ?
    lost_sources = 0
    same_sources = 0
    gained_sources = 0
    lost_chunks = 0
    same_chunks = 0
    gained_chunks = 0
    for qid, a, b in degraded:
        pre_s = pre_by_id[qid]
        post_s = post_by_id[qid]
        pre_n_src = len(pre_s.get("sources_used", []) or [])
        post_n_src = len(post_s.get("sources_used", []) or [])
        pre_n_chk = pre_s.get("chunks_retrieved", 0) or 0
        post_n_chk = post_s.get("chunks_retrieved", 0) or 0
        if post_n_src < pre_n_src: lost_sources += 1
        elif post_n_src > pre_n_src: gained_sources += 1
        else: same_sources += 1
        if post_n_chk < pre_n_chk: lost_chunks += 1
        elif post_n_chk > pre_n_chk: gained_chunks += 1
        else: same_chunks += 1

    print()
    print(f"=== Parmi les {len(degraded)} questions degradees sur both_sources_cited ===")
    print(f"  sources_used count: +{gained_sources} / ={same_sources} / -{lost_sources}")
    print(f"  chunks_retrieved count: +{gained_chunks} / ={same_chunks} / -{lost_chunks}")

    # Comparer les claim coverage
    avg_c1_delta = sum(post_by_id[q]["evaluation"].get("claim1_coverage",0) - pre_by_id[q]["evaluation"].get("claim1_coverage",0) for q,_,_ in degraded) / max(len(degraded),1)
    avg_c2_delta = sum(post_by_id[q]["evaluation"].get("claim2_coverage",0) - pre_by_id[q]["evaluation"].get("claim2_coverage",0) for q,_,_ in degraded) / max(len(degraded),1)
    print(f"  avg claim1_coverage delta: {avg_c1_delta:+.4f}")
    print(f"  avg claim2_coverage delta: {avg_c2_delta:+.4f}")

    # Sur les stables et improved, voir si claim coverage a change
    all_c1_pre = sum(pre_by_id[q]["evaluation"].get("claim1_coverage",0) for q in t2_common) / len(t2_common)
    all_c1_post = sum(post_by_id[q]["evaluation"].get("claim1_coverage",0) for q in t2_common) / len(t2_common)
    all_c2_pre = sum(pre_by_id[q]["evaluation"].get("claim2_coverage",0) for q in t2_common) / len(t2_common)
    all_c2_post = sum(post_by_id[q]["evaluation"].get("claim2_coverage",0) for q in t2_common) / len(t2_common)
    print()
    print(f"=== claim coverage global (T2 common) ===")
    print(f"  claim1: PRE={all_c1_pre:.4f} POST={all_c1_post:.4f} delta={all_c1_post-all_c1_pre:+.4f}")
    print(f"  claim2: PRE={all_c2_pre:.4f} POST={all_c2_post:.4f} delta={all_c2_post-all_c2_pre:+.4f}")


if __name__ == "__main__":
    main()
