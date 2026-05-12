"""
Re-juge 30 questions échouées (Robustness, score < 0.5) avec un 2nd juge
plus puissant (Claude Sonnet via Anthropic) pour calibrer Prometheus.

Si le 2nd juge donne des scores significativement plus hauts → bug Prometheus.
Si scores similaires → vraie régression pipeline.
"""
import io, json, os, sys, time
import httpx

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

REPORT = json.load(open(r"C:/Projects/SAP_KB/app/data/benchmark/results/robustness_run_20260504_133914.json", encoding="utf-8"))
ps = REPORT["per_sample"]

# Charger la clé DeepInfra (fallback car Anthropic crédit épuisé)
DEEPINFRA_KEY = ""
env_path = r"C:/Projects/SAP_KB/.env"
if os.path.exists(env_path):
    for line in open(env_path, encoding="utf-8"):
        if line.startswith("DEEPINFRA_API_KEY="):
            DEEPINFRA_KEY = line.split("=", 1)[1].strip().strip('"').strip("'")
            break
assert DEEPINFRA_KEY, "DEEPINFRA_API_KEY missing"

# Juge candidat : Llama-3.3-70B-Instruct (DeepInfra) — choix CH-34 final
DEEPINFRA_MODEL = "meta-llama/Llama-3.3-70B-Instruct"

JUDGE_PROMPT = """You are evaluating a RAG system's answer to a question.

Score the answer 0-100 on its category (the dimension that matters here).

Categories you will see:
- conditional : does the answer correctly handle the IF/THEN conditional aspect of the question?
- false_premise : does the answer correctly identify and reject the false premise?
- multi_hop : does the answer chain facts correctly across multiple documents?
- causal_why : does the answer explain the WHY (the cause)?
- temporal_evolution : does the answer correctly capture the temporal aspect?
- lifecycle_filtering_active : does the answer correctly identify the active version vs deprecated?
- set_list : does the answer cover the expected set/list?
- anchor_applicability_temporal : does the answer correctly apply the temporal anchor?
- anchor_scope_hierarchy : does the answer respect the scope hierarchy?
- negation : does the answer correctly handle negation/exclusion?
- lifecycle_evolves_from / lifecycle_supersedes / lifecycle_vs_conflict : lifecycle aspects.
- multi_hop / hypothetical : reasoning across docs / hypothetical reasoning.
- synthesis_large : large synthesis quality.
- unanswerable : does the system correctly say it can't answer (no information available)?

Score scale:
- 0-20  : Wrong, hallucinated, or fails the category requirement entirely
- 30-50 : Partial — some elements right but missing key aspects
- 60-80 : Good — answers correctly but minor issues
- 90-100 : Excellent — fully addresses with evidence

Reply ONLY in this exact format on two lines:
SCORE: <number 0-100>
REASON: <one short sentence explaining the score, max 25 words>"""


def call_claude(question: str, answer: str, category: str, ground_truth: str = "") -> dict:
    msg = (
        f"CATEGORY: {category}\n\n"
        f"QUESTION: {question}\n\n"
        f"REFERENCE ANSWER (ground truth, what would be ideal): {ground_truth or '(not provided)'}\n\n"
        f"SYSTEM ANSWER:\n{answer}\n\n"
        f"Score this system answer."
    )
    t0 = time.time()
    try:
        with httpx.Client(timeout=60.0) as client:
            resp = client.post(
                "https://api.deepinfra.com/v1/openai/chat/completions",
                headers={
                    "Authorization": f"Bearer {DEEPINFRA_KEY}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": DEEPINFRA_MODEL,
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
        return {"error": f"{type(e).__name__}: {e}", "elapsed": round(time.time()-t0, 2)}
    elapsed = round(time.time()-t0, 2)
    content = data["choices"][0]["message"]["content"]
    import re
    m = re.search(r"SCORE\s*:\s*(\d+)", content, re.IGNORECASE)
    score = int(m.group(1)) / 100.0 if m else 0.0
    score = max(0.0, min(1.0, score))
    rm = re.search(r"REASON\s*:\s*(.+?)$", content, re.IGNORECASE | re.DOTALL)
    reason = (rm.group(1).strip() if rm else "")[:200]
    return {"score": score, "reason": reason, "raw": content[:300], "elapsed": elapsed}


# Sélection : 30 cas variés (pires catégories d'abord)
PRIORITY_CATS = ["lifecycle_filtering_active", "conditional", "multi_hop", "set_list",
                 "temporal_evolution", "anchor_applicability_temporal", "causal_why",
                 "anchor_scope_hierarchy", "negation"]

selected = []
for cat in PRIORITY_CATS:
    cat_samples = [s for s in ps if s.get("category") == cat
                   and (s.get("evaluation") or {}).get("score", 1.0) < 0.5]
    selected.extend(cat_samples[:4])  # 4 par catégorie max
    if len(selected) >= 30:
        break
selected = selected[:30]

print(f"Re-judging {len(selected)} samples with Claude Haiku 4.5 ...\n", flush=True)

deltas = []
results = []
for i, s in enumerate(selected, 1):
    qid = s["question_id"]
    cat = s["category"]
    q = s["question"]
    ans = s["answer"]
    prom_score = s["evaluation"].get("score", 0)
    prom_reason = s["evaluation"].get("judge_reason", "")
    # No ground truth in robustness data → empty string
    gt = s.get("ground_truth_answer") or s.get("expected_answer") or ""

    out = call_claude(q, ans, cat, gt)
    if "error" in out:
        print(f"[{i}/{len(selected)}] {qid:8s} [{cat:30s}] ERROR: {out['error']}", flush=True)
        continue

    delta = out["score"] - prom_score
    deltas.append(delta)
    arrow = "↑" if delta > 0.15 else ("↓" if delta < -0.15 else "≈")
    print(f"[{i}/{len(selected)}] {qid:8s} [{cat:25s}] "
          f"Prom={prom_score:.2f}  Claude={out['score']:.2f}  {arrow} ({delta:+.2f}) "
          f"({out['elapsed']}s)", flush=True)
    print(f"    Claude reason: {out['reason'][:140]}", flush=True)

    results.append({
        "qid": qid, "category": cat, "question": q,
        "prometheus_score": prom_score,
        "prometheus_reason": prom_reason,
        "claude_score": out["score"],
        "claude_reason": out["reason"],
        "delta": delta,
    })

# Recap
print("\n" + "=" * 80)
print("RECAP")
print("=" * 80)
import statistics
if deltas:
    avg = statistics.mean(deltas)
    median = statistics.median(deltas)
    n_higher = sum(1 for d in deltas if d > 0.15)
    n_lower = sum(1 for d in deltas if d < -0.15)
    n_close = sum(1 for d in deltas if abs(d) <= 0.15)
    print(f"  Avg delta (Claude - Prometheus): {avg:+.3f}")
    print(f"  Median delta : {median:+.3f}")
    print(f"  Claude SIGNIFICANTLY higher (delta > +0.15) : {n_higher}/{len(deltas)} ({100*n_higher/len(deltas):.0f}%)")
    print(f"  Claude SIGNIFICANTLY lower  (delta < -0.15) : {n_lower}/{len(deltas)} ({100*n_lower/len(deltas):.0f}%)")
    print(f"  Close (|delta| <= 0.15) : {n_close}/{len(deltas)} ({100*n_close/len(deltas):.0f}%)")

with open(r"C:/Projects/SAP_KB/benchmark/audit_judge_calibration_llama70b.json", "w", encoding="utf-8") as f:
    json.dump(results, f, indent=2, ensure_ascii=False)
print(f"\nSaved details to benchmark/audit_judge_calibration_llama70b.json")
