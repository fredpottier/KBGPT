"""Test Selene-1-Mini-8B local (GPU, llama.cpp port 8083) sur les 5 mêmes questions sample."""
import io, json, sys, time
import httpx

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

JUDGE_PROMPT = """You are evaluating a RAG system's answer to a question.

Score the answer 0-100 on its category (the dimension that matters here).

Categories you will see:
- conditional, false_premise, multi_hop, causal_why, temporal_evolution
- lifecycle_filtering_active, set_list, anchor_applicability_temporal
- anchor_scope_hierarchy, negation, lifecycle_evolves_from, lifecycle_supersedes
- lifecycle_vs_conflict, hypothetical, synthesis_large, unanswerable

Score scale:
- 0-20  : Wrong, hallucinated, fails the category requirement entirely
- 30-50 : Partial — some elements right but missing key aspects
- 60-80 : Good — answers correctly but minor issues
- 90-100 : Excellent — fully addresses with evidence

Reply ONLY in this exact format on two lines:
SCORE: <number 0-100>
REASON: <one short sentence explaining the score, max 25 words>"""

prev_audit = json.load(open(r"C:/Projects/SAP_KB/benchmark/audit_judge_calibration.json", encoding="utf-8"))
sample_qids = ["q_122", "q_106", "q_80", "q_24", "q_36"]
SAMPLES = [r for r in prev_audit if r["qid"] in sample_qids]

robust = json.load(open(r"C:/Projects/SAP_KB/app/data/benchmark/results/robustness_run_20260504_133914.json", encoding="utf-8"))
ps_by_qid = {s["question_id"]: s for s in robust["per_sample"]}

QWEN_BASELINE = {r["qid"]: r["claude_score"] for r in prev_audit if r["qid"] in sample_qids}

import re

def call_selene(msg: str) -> dict:
    t0 = time.time()
    try:
        with httpx.Client(timeout=60.0) as client:
            resp = client.post(
                "http://localhost:8083/v1/chat/completions",
                headers={"Content-Type": "application/json"},
                json={
                    "model": "Selene-1-Mini-Llama-3.1-8B.Q4_K_M.gguf",
                    "max_tokens": 100,
                    "temperature": 0.0,
                    "messages": [
                        {"role": "system", "content": JUDGE_PROMPT},
                        {"role": "user", "content": msg},
                    ],
                },
            )
            resp.raise_for_status()
            data = resp.json()
    except Exception as e:
        return {"error": f"{type(e).__name__}: {str(e)[:160]}", "elapsed": round(time.time()-t0, 2)}
    elapsed = round(time.time()-t0, 2)
    content = data["choices"][0]["message"]["content"]
    usage = data.get("usage", {})
    m = re.search(r"SCORE\s*:\s*(\d+)", content, re.IGNORECASE)
    score = (int(m.group(1)) / 100.0) if m else None
    return {
        "score": score, "elapsed": elapsed,
        "in_tokens": usage.get("prompt_tokens", 0),
        "out_tokens": usage.get("completion_tokens", 0),
        "raw": content[:200],
    }


print("Test Selene-1-Mini-8B (Q4_K_M, GPU local port 8083)\n")

deltas = []
elapsed_arr = []
out_toks_arr = []

# Warmup (1er call long à cause du cache)
print("[warmup]")
warmup = call_selene("CATEGORY: test\n\nQUESTION: hi\n\nSYSTEM ANSWER: hi\n\nScore.")
print(f"  warmup elapsed={warmup.get('elapsed')}s")
print()

# Test sample
for s in SAMPLES:
    qid = s["qid"]
    cat = s["category"]
    full = ps_by_qid[qid]
    q = full["question"]
    ans = full["answer"]
    msg = (
        f"CATEGORY: {cat}\n\n"
        f"QUESTION: {q}\n\n"
        f"REFERENCE ANSWER: (not provided)\n\n"
        f"SYSTEM ANSWER:\n{ans}\n\n"
        f"Score this system answer."
    )
    out = call_selene(msg)
    if "error" in out:
        print(f"{qid}: ERROR {out['error']}")
        continue
    baseline = QWEN_BASELINE.get(qid)
    delta = (out["score"] - baseline) if (out["score"] is not None and baseline is not None) else None
    if delta is not None:
        deltas.append(delta)
    elapsed_arr.append(out["elapsed"])
    out_toks_arr.append(out["out_tokens"])
    print(f"{qid:8s} score={out['score']} (ref Qwen={baseline}) delta={delta} ({out['elapsed']}s, {out.get('out_tokens', 0)} out_tok)")

if elapsed_arr:
    avg_e = sum(elapsed_arr) / len(elapsed_arr)
    avg_o = sum(out_toks_arr) / len(out_toks_arr)
    avg_d = sum(deltas) / len(deltas) if deltas else None
    print(f"\nAVG: elapsed={avg_e:.2f}s tok/s={avg_o/max(avg_e,0.1):.1f} delta_vs_qwen={avg_d:+.3f}")

# Bonus : test parallel batch (4 calls simultanés pour vérifier les 4 slots GPU)
print("\n[parallel test — 4 calls simultanés]")
import concurrent.futures
def one():
    return call_selene("CATEGORY: test\n\nQUESTION: 2+2?\n\nSYSTEM ANSWER: 4\n\nScore.")
t0 = time.time()
with concurrent.futures.ThreadPoolExecutor(max_workers=4) as ex:
    futs = [ex.submit(one) for _ in range(4)]
    rs = [f.result() for f in futs]
total = round(time.time() - t0, 2)
print(f"4 parallel calls finished in {total}s (avg seq would be {sum(r.get('elapsed',0) for r in rs):.1f}s)")
for i, r in enumerate(rs):
    print(f"  call_{i+1}: {r.get('elapsed')}s score={r.get('score')}")
