"""
Replay des lemon questions sur le pipeline V2 enrichi (CH-31).
Compare la nouvelle réponse aux précédents jugements.
"""
import json
import sys
import time
import urllib.request

LEMONS_PATH = r"C:/Projects/SAP_KB/benchmark/lemon_set.json"
OUT_PATH = r"C:/Projects/SAP_KB/benchmark/lemon_replay_ch32.json"
API = "http://localhost:8000/api/runtime_v2/answer"


def call(question: str, top_k: int = 8, timeout: float = 180.0) -> dict:
    payload = {"question": question, "top_k_claims": top_k}
    req = urllib.request.Request(
        API,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    t0 = time.time()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            d = json.loads(resp.read().decode("utf-8"))
            d["_elapsed"] = round(time.time() - t0, 1)
            return d
    except Exception as e:
        return {"error": f"{type(e).__name__}: {e}", "_elapsed": round(time.time() - t0, 1)}


def summarize(d: dict) -> dict:
    if "error" in d:
        return {"error": d["error"], "_elapsed": d["_elapsed"]}
    diag = d.get("diagnostic", {}) or {}
    dec = diag.get("decomposer", {}) or {}
    lf = diag.get("llm_filter", {}) or {}
    grades = lf.get("grades") or {}
    top_grades = sorted(
        [(g.get("score"), cid, g.get("keep")) for cid, g in grades.items()],
        reverse=True,
    )[:3]
    pv = diag.get("premise_validator", {}) or {}
    fj = diag.get("faithfulness", {}) or {}
    return {
        "elapsed_s": d["_elapsed"],
        "decision": d.get("decision"),
        "anchor": (diag.get("anchor", {}) or {}).get("type"),
        "subject_label": dec.get("subject_label"),
        "answer_shape": dec.get("answer_shape"),
        "has_hyde": dec.get("has_hyde"),
        "must_contain": dec.get("must_contain"),
        "filter_in": lf.get("n_input"),
        "filter_kept": lf.get("n_kept"),
        "filter_dropped": lf.get("n_dropped"),
        "filter_called": lf.get("llm_called"),
        "filter_fallback": lf.get("fallback_reason"),
        "top_grades": [{"cid": cid[:24], "score": s, "keep": k} for s, cid, k in top_grades],
        "authoritative_doc_ids": d.get("authoritative_doc_ids"),
        "n_claims_kept": len(d.get("claims") or []),
        "synthesized_answer": d.get("synthesized_answer"),
        "answer_gap_classification": d.get("answer_gap_classification"),
        "answer_gap_score": d.get("answer_gap_score"),
        "trust_score": d.get("trust_score"),
        # CH-32 fields
        "premise_n_presup": pv.get("n_presuppositions"),
        "premise_false_premise": pv.get("has_false_premise"),
        "premise_verdicts": [
            (p.get("verdict"), round(p.get("confidence") or 0, 2))
            for p in (pv.get("presuppositions") or [])
        ],
        "synthesis_bypassed": diag.get("synthesis_bypassed"),
        "faith_verdict": fj.get("verdict"),
        "faith_score": fj.get("score"),
        "faith_n_supported": fj.get("n_supported"),
        "faith_n_unsupported": fj.get("n_unsupported"),
        "faith_n_neutral": fj.get("n_neutral"),
        "faith_regenerated": fj.get("regenerated"),
        "faith_unsupported_claims": [
            ac.get("claim") for ac in (fj.get("atomic_claims") or [])
            if ac.get("verdict") == "UNSUPPORTED"
        ][:5],
    }


def main():
    lemons = json.load(open(LEMONS_PATH, encoding="utf-8"))
    print(f"Replaying {len(lemons)} lemons through V2 enriched pipeline (CH-31)...\n", flush=True)

    results = []
    for i, lem in enumerate(lemons, 1):
        qid = lem["question_id"]
        task = lem["task"]
        question = lem["question"]
        prev = lem["previous_judgment"]
        print(f"[{i}/{len(lemons)}] {qid} ({task})", flush=True)
        print(f"  Q: {question[:160]}", flush=True)
        print(
            f"  Previous: factual={prev.get('factual_correctness', '?')} "
            f"correct_doc={prev.get('correct_doc_cited', '?')} "
            f"says_idk={prev.get('says_idk_when_info_exists', '?')} "
            f"no_hall={prev.get('no_hallucination', '?')} "
            f"answers_correctly={prev.get('answers_correctly', '?')}",
            flush=True,
        )
        resp = call(question)
        summ = summarize(resp)
        print(f"  -> elapsed={summ.get('elapsed_s')}s decision={summ.get('decision')} ", flush=True)
        print(
            f"     filter: in={summ.get('filter_in')} kept={summ.get('filter_kept')} "
            f"dropped={summ.get('filter_dropped')} ({summ.get('filter_fallback')})",
            flush=True,
        )
        print(f"     gap={summ.get('answer_gap_classification')} trust={summ.get('trust_score')}", flush=True)
        ans = summ.get("synthesized_answer") or ""
        print(f"     answer: {ans[:280]}", flush=True)
        print(flush=True)

        results.append(
            {
                "question_id": qid,
                "task": task,
                "category": lem.get("category"),
                "question": question,
                "ground_truth": lem.get("ground_truth"),
                "previous_judgment": prev,
                "new_run": summ,
            }
        )

    with open(OUT_PATH, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)
    print(f"\nSaved {len(results)} replays to {OUT_PATH}")


if __name__ == "__main__":
    main()
