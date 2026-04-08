"""
Lecture des reponses brutes pour les pires regressions T2.
Objectif : voir ce que le LLM ecrit reellement avant/apres.
"""
import json

PRE_PATH = "/data/benchmark/results/t2t5_run_20260404_074418_V3_MODES_VS_RAG.json"
POST_PATH = "/data/benchmark/results/t2t5_run_20260408_065401_POST_PerspectiveLayer_v3.json"

QIDS_TO_INSPECT = [
    "T2_EXP_0021",  # pire : claim1 1.00->0.38, claim2 1.00->0.33
    "T2_KG_0003",   # claim1 0.93->0.27, claim2 0.93->0.64
    "T2_KG_0030",   # claim1 1.00->0.58, claim2 1.00->0.50
]


def main():
    pre = json.load(open(PRE_PATH))
    post = json.load(open(POST_PATH))
    pre_by = {s["question_id"]: s for s in pre["per_sample"]}
    post_by = {s["question_id"]: s for s in post["per_sample"]}

    for qid in QIDS_TO_INSPECT:
        pr = pre_by[qid]
        po = post_by[qid]
        print("=" * 80)
        print(f"QID: {qid}")
        print(f"Question: {pr['question']}")
        print()
        print(f"Ground truth:")
        gt = pr.get("ground_truth", {})
        c1 = gt.get("claim1", {}) if isinstance(gt, dict) else {}
        c2 = gt.get("claim2", {}) if isinstance(gt, dict) else {}
        print(f"  claim1 text: {c1.get('text','N/A')[:200]}")
        print(f"  claim1 source: {c1.get('source','N/A')}")
        print(f"  claim2 text: {c2.get('text','N/A')[:200]}")
        print(f"  claim2 source: {c2.get('source','N/A')}")
        print()
        print(f"Metriques PRE:")
        for k, v in pr["evaluation"].items():
            if isinstance(v, (int, float)):
                print(f"  {k}: {v}")
        print(f"Sources PRE: {pr.get('sources_used', [])}")
        print()
        print(f"Reponse PRE ({pr.get('answer_length','?')} chars):")
        print(pr["answer"][:2000])
        print()
        print("-" * 80)
        print(f"Metriques POST:")
        for k, v in po["evaluation"].items():
            if isinstance(v, (int, float)):
                print(f"  {k}: {v}")
        print(f"Sources POST: {po.get('sources_used', [])}")
        print()
        print(f"Reponse POST ({po.get('answer_length','?')} chars):")
        print(po["answer"][:2000])
        print()
        print()


if __name__ == "__main__":
    main()
