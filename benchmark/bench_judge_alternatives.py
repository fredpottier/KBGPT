"""
Bench juges DeepInfra alternatifs : latence + calibration vs Qwen-72B.

Pour 5 questions sample (déjà jugées par Qwen-72B), tester chaque candidat :
- latence
- score donné
- delta vs Qwen-72B (calibration)

Recommandation = candidat avec : latence < Qwen / delta proche 0 (calibration similaire) / coût bas.
"""
import io, json, os, sys, time
import httpx

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

DI_KEY = ""
for line in open(r"C:/Projects/SAP_KB/.env", encoding="utf-8"):
    if line.startswith("DEEPINFRA_API_KEY="):
        DI_KEY = line.split("=", 1)[1].strip().strip('"').strip("'")
        break
assert DI_KEY

# Candidats : varier taille, coût, vitesse
CANDIDATES = [
    # Modèles 2025 récents non encore testés
    ("deepseek-ai/DeepSeek-V3", "DeepSeek V3 671B MoE"),
    ("Qwen/Qwen3-Max", "Qwen3 Max"),
    ("meta-llama/Llama-4-Maverick-17B-128E-Instruct-FP8", "Llama 4 Maverick"),
    ("google/gemma-3-27b-it", "Gemma 3 27B"),
    ("mistralai/Mistral-Large-Instruct-2411", "Mistral Large 123B"),
]

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

# Charger 5 questions sample
prev_audit = json.load(open(r"C:/Projects/SAP_KB/benchmark/audit_judge_calibration.json", encoding="utf-8"))
# Prendre 5 questions variées
sample_qids = ["q_122", "q_106", "q_80", "q_24", "q_36"]
SAMPLES = []
for r in prev_audit:
    if r["qid"] in sample_qids:
        SAMPLES.append(r)

print(f"Bench {len(CANDIDATES)} judges sur {len(SAMPLES)} questions sample\n", flush=True)

# Charger le bench complet pour récupérer answer/category/question
robust = json.load(open(r"C:/Projects/SAP_KB/app/data/benchmark/results/robustness_run_20260504_133914.json", encoding="utf-8"))
ps_by_qid = {s["question_id"]: s for s in robust["per_sample"]}

# Score Qwen baseline = celui de l'audit précédent
QWEN_BASELINE = {r["qid"]: r["claude_score"] for r in prev_audit if r["qid"] in sample_qids}


def call_di(model: str, msg: str, timeout: float = 60.0) -> dict:
    t0 = time.time()
    try:
        with httpx.Client(timeout=timeout) as client:
            resp = client.post(
                "https://api.deepinfra.com/v1/openai/chat/completions",
                headers={"Authorization": f"Bearer {DI_KEY}", "Content-Type": "application/json"},
                json={
                    "model": model,
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
    import re
    m = re.search(r"SCORE\s*:\s*(\d+)", content, re.IGNORECASE)
    score = (int(m.group(1)) / 100.0) if m else None
    return {
        "score": score,
        "elapsed": elapsed,
        "in_tokens": usage.get("prompt_tokens", 0),
        "out_tokens": usage.get("completion_tokens", 0),
        "raw": content[:200],
    }


results_by_model = {}
for model, label in CANDIDATES:
    print(f"--- {model[:50]:50s} ({label})", flush=True)
    deltas = []
    elapsed_arr = []
    out_toks_arr = []
    err = None
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
        out = call_di(model, msg)
        if "error" in out:
            err = out["error"]
            print(f"    {qid}: ERROR {err[:100]}", flush=True)
            continue
        baseline = QWEN_BASELINE.get(qid)
        delta = (out["score"] - baseline) if (out["score"] is not None and baseline is not None) else None
        if delta is not None:
            deltas.append(delta)
        elapsed_arr.append(out["elapsed"])
        out_toks_arr.append(out["out_tokens"])
        print(f"    {qid:8s} score={out['score']} (ref Qwen={baseline}) delta={delta} {out['elapsed']}s", flush=True)
    if elapsed_arr:
        avg_elapsed = sum(elapsed_arr) / len(elapsed_arr)
        avg_out_tok = sum(out_toks_arr) / len(out_toks_arr) if out_toks_arr else 0
        avg_delta = sum(deltas) / len(deltas) if deltas else None
        results_by_model[model] = {
            "label": label,
            "avg_elapsed_s": round(avg_elapsed, 2),
            "avg_out_tokens": round(avg_out_tok, 1),
            "avg_delta_vs_qwen": round(avg_delta, 3) if avg_delta is not None else None,
            "n_samples": len(elapsed_arr),
            "tps": round(avg_out_tok / max(avg_elapsed, 0.1), 1),
            "n_parse_fails": len(SAMPLES) - len(deltas),
        }
        delta_str = f"{avg_delta:+.3f}" if avg_delta is not None else "N/A (parse fails)"
        print(f"    AVG: elapsed={avg_elapsed:.1f}s tok/s={avg_out_tok / max(avg_elapsed, 0.1):.1f} delta_vs_qwen={delta_str}\n", flush=True)
    elif err:
        results_by_model[model] = {"label": label, "error": err}
        print(f"    ERROR: {err[:100]}\n", flush=True)

# Recap
print("=" * 100)
print("RECAP COMPARATIF JUDGE CANDIDATES")
print("=" * 100)
print(f"{'Model':<55} {'avg_lat':>8} {'tps':>6} {'delta_vs_qwen':>15} {'note':<20}")
print("-" * 100)
for model, info in results_by_model.items():
    if "error" in info:
        print(f"{model:<55} ERROR: {info['error'][:30]}")
    else:
        d = info.get("avg_delta_vs_qwen")
        d_str = f"{d:+.3f}" if d is not None else "N/A"
        print(f"{model:<55} {info['avg_elapsed_s']:>7.2f}s {info['tps']:>6.0f} {d_str:>15} {info['label']:<20}")

with open(r"C:/Projects/SAP_KB/benchmark/bench_judge_alternatives.json", "w", encoding="utf-8") as f:
    json.dump(results_by_model, f, indent=2, ensure_ascii=False)
print(f"\nSaved to benchmark/bench_judge_alternatives.json")
