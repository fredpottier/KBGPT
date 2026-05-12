"""POC-A — bench Reading Agent sur les 170 questions Robustness aerospace.

Charge toutes les questions depuis le bench V4.2 baseline (per_sample) qui contient
les ground_truths et les comparaisons V3/V4.2. Exécute Reading Agent en parallèle
(3 threads pour rester sous rate-limit DeepInfra). Score avec 2 juges.

Output :
  /app/data/benchmark/oracle_audit/poc_a_results_170q.json
"""
import json
import os
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import requests

sys.path.insert(0, "/app/src")
from knowbase.runtime_v5.reasoning_agent import run_agent

# Source des 170 questions + ground_truth (depuis bench V4.2 baseline)
V42_BENCH = "/app/data/benchmark/results/robustness_run_20260510_145658_v4_2_baseline.json"
V3_BENCH = "/app/data/benchmark/results/robustness_run_20260505_104355_V3_FINAL3.json"
# Source ground_truth riche (correct_fact, expected_behavior)
GT_SOURCE = "/app/benchmark/questions/aero_t6_robustness.json"

OUT = Path("/app/data/benchmark/oracle_audit/poc_a_results_170q.json")
OUT.parent.mkdir(parents=True, exist_ok=True)

DEEPINFRA_KEY = os.getenv("DEEPINFRA_API_KEY", "").strip()

JUDGES = {
    "llama-3.3-70b": "meta-llama/Llama-3.3-70B-Instruct",
    "qwen-2.5-72b": "Qwen/Qwen2.5-72B-Instruct",
}

CATEGORY_JUDGE_CRITERIA = {
    "false_premise": "The question contains a FALSE premise. A good answer should CORRECT the false premise and provide the correct information from the sources. A bad answer accepts the false premise without questioning it.",
    "temporal_evolution": "The question asks about how something CHANGED between document versions. A good answer identifies specific changes and cites both versions. A bad answer is vague or doesn't compare versions.",
    "causal_why": "The question asks WHY something is done. A good answer explains the reason based on documented facts. A bad answer gives generic reasons not grounded in the sources.",
    "negation": "The question asks what is NOT possible/supported. A good answer identifies the limitation or restriction from the sources. A bad answer fails to address the negation.",
    "synthesis_large": "The question asks for a comprehensive overview. A good answer covers multiple aspects from multiple documents. A bad answer is too narrow or misses major aspects.",
    "conditional": "The question asks about a specific condition or prerequisite. A good answer identifies and explains the condition from the sources. A bad answer misses the conditional aspect.",
    "set_list": "The question asks to LIST or ENUMERATE items. A good answer lists the correct items from the sources. A bad answer misses items or lists wrong ones.",
    "multi_hop": "The question requires CHAINING facts from multiple sources. A good answer connects the facts logically. A bad answer only addresses part of the chain.",
    "unanswerable": "The question asks for information that does NOT exist in the corpus. A good answer abstains, says it cannot find the information, or explains why the answer is unavailable. A bad answer fabricates an answer.",
    "hypothetical": "The question asks what would happen IF a condition is not met. A good answer infers consequences from documented facts. A bad answer speculates without source basis.",
    "lifecycle_supersedes": "The question asks about a regulation that REPLACED another (SUPERSEDES). A good answer identifies the replacement regulation and cites the explicit repeal/replacement. A bad answer misses the lifecycle relationship.",
    "lifecycle_evolves_from": "The question asks about regulations that MODIFY or update another via delegated/amending acts. A good answer identifies the modifications and the parent regulation. A bad answer treats them as unrelated documents.",
    "lifecycle_filtering_active": "The question requires returning ACTIVE versions only and excluding DEPRECATED ones. A good answer correctly filters and explains why deprecated content is excluded. A bad answer cites obsolete sources as applicable.",
    "anchor_applicability_temporal": "The question requires identifying which version was applicable at a given DATE (temporal anchor). A good answer selects the right version using publication dates. A bad answer ignores the date or uses the latest version.",
    "anchor_scope_hierarchy": "The question asks about the SCOPE relationship between concepts (subset/superset/disjoint). A good answer correctly identifies the hierarchy. A bad answer conflates distinct scopes.",
    "lifecycle_vs_conflict": "The question tests whether OSMOSIS distinguishes a real CONFLICT from a regulatory EVOLUTION (lifecycle). A good answer identifies it as evolution and selects the active value. A bad answer raises a false alarm of contradiction.",
}

JUDGE_PROMPT_TEMPLATE = """You are a strict benchmark evaluator for a document analysis system.

Question: "{question}"
Category: {category}
Expected behavior: {expected}
{evidence_line}

Evaluation criteria: {criteria}

Actual answer:
"{answer}"

Rate the answer from 0 to 100:
- 0-20: Completely wrong, irrelevant, or hallucinates
- 20-50: Partially relevant but misses the key point
- 50-70: Addresses the topic but incomplete
- 70-90: Good, mostly correct and grounded in sources
- 90-100: Excellent, fully addresses with evidence

Reply in this exact format on two lines:
SCORE: <number 0-100>
REASON: <one short sentence explaining the score, max 25 words>"""


def call_judge(model_id: str, prompt: str, max_retries: int = 3) -> dict:
    last_err = None
    for attempt in range(max_retries):
        try:
            r = requests.post(
                "https://api.deepinfra.com/v1/openai/chat/completions",
                headers={"Authorization": f"Bearer {DEEPINFRA_KEY}", "Content-Type": "application/json"},
                json={
                    "model": model_id,
                    "messages": [{"role": "user", "content": prompt}],
                    "max_tokens": 100,
                    "temperature": 0.0,
                },
                timeout=120,
            )
            r.raise_for_status()
            data = r.json()
            text = data["choices"][0]["message"]["content"].strip()
            score_m = re.search(r"SCORE\s*:\s*(\d+)", text, re.IGNORECASE)
            reason_m = re.search(r"REASON\s*:\s*(.+?)(?:$|\n)", text, re.IGNORECASE | re.DOTALL)
            score = int(score_m.group(1)) / 100.0 if score_m else 0.0
            score = max(0.0, min(1.0, score))
            reason = reason_m.group(1).strip() if reason_m else ""
            return {"score": score, "reason": reason, "error": None}
        except Exception as e:
            last_err = e
            if attempt < max_retries - 1:
                time.sleep(2 ** (attempt + 1))
    return {"score": None, "reason": "", "error": str(last_err)}


def load_questions():
    """Charge les 170 questions du bench Robustness depuis V4.2 baseline + GT enrichis."""
    v42_data = json.load(open(V42_BENCH))
    v3_data = json.load(open(V3_BENCH))
    gt_source = json.load(open(GT_SOURCE))

    v3_by_qid = {s["question_id"]: s for s in v3_data["per_sample"]}
    # Index ground_truth source par texte de question pour matching
    gt_by_question = {(g.get("question") or "").strip(): g for g in gt_source}

    questions = []
    for s in v42_data["per_sample"]:
        qid = s["question_id"]
        question = s.get("question") or ""
        v42_ans = s.get("answer") or ""
        v42_score = (s.get("evaluation") or {}).get("score") or 0
        v3 = v3_by_qid.get(qid, {})
        v3_ans = v3.get("answer") or ""
        v3_score = (v3.get("evaluation") or {}).get("score") or 0

        # Look up enriched GT (correct_fact, evidence_quote)
        gt = gt_by_question.get(question.strip(), {}).get("ground_truth", {})
        expected = gt.get("expected_behavior", "")
        evidence = gt.get("correct_fact") or gt.get("evidence_claim") or ""

        questions.append({
            "question_id": qid,
            "question": question,
            "category": s.get("category"),
            "expected_behavior": expected,
            "correct_fact": evidence,
            "v3_score_bench": v3_score,
            "v4_2_score_bench": v42_score,
        })
    return questions


def process_question(q: dict) -> dict:
    """Exécute Reading Agent + scoring 2 juges sur 1 question."""
    qid = q["question_id"]
    question = q["question"]
    category = q["category"]

    # Run agent
    t0 = time.time()
    try:
        agent_result = run_agent(question, max_iterations=8, verbose=False)
    except Exception as e:
        return {
            **q,
            "agent_answer": "",
            "agent_error": f"{type(e).__name__}: {e}",
            "scores": {},
        }
    elapsed = time.time() - t0
    agent_answer = agent_result.get("answer", "")

    # Scoring 2 juges
    criteria = CATEGORY_JUDGE_CRITERIA.get(category, "")
    evidence_line = f'Reference evidence: "{q["correct_fact"][:300]}"' if q["correct_fact"] else ""
    judge_prompt = JUDGE_PROMPT_TEMPLATE.format(
        question=question[:200],
        category=category,
        expected=q["expected_behavior"],
        evidence_line=evidence_line,
        criteria=criteria,
        answer=agent_answer[:3000],
    )

    judges_out = {}
    for jname, jid in JUDGES.items():
        judges_out[jname] = call_judge(jid, judge_prompt)

    return {
        **q,
        "agent_answer": agent_answer,
        "agent_n_iterations": agent_result.get("n_iterations", 0),
        "agent_stopped_reason": agent_result.get("stopped_reason"),
        "agent_tokens_total": agent_result.get("tokens_total", 0),
        "agent_n_tool_calls": len(agent_result.get("trace", [])),
        "agent_tool_sequence": [t["tool"] for t in agent_result.get("trace", [])],
        "agent_elapsed_s": int(elapsed),
        "scores": judges_out,
    }


def main():
    questions = load_questions()
    print(f"Loaded {len(questions)} questions from Robustness bench\n")

    # Reprise depuis fichier existant si présent
    if OUT.exists():
        existing = json.load(open(OUT))
        done_qids = {q["question_id"] for q in existing.get("per_question", [])}
        results = existing
        print(f"[resume] {len(done_qids)} questions déjà traitées")
    else:
        done_qids = set()
        results = {"per_question": []}

    todo = [q for q in questions if q["question_id"] not in done_qids]
    print(f"À traiter : {len(todo)}/{len(questions)}\n")

    t0 = time.time()
    completed_count = len(done_qids)

    # Parallélisation 6 threads (Together AI moins saturé que DeepInfra)
    with ThreadPoolExecutor(max_workers=6) as pool:
        futures = {pool.submit(process_question, q): q for q in todo}
        for fut in as_completed(futures):
            try:
                r = fut.result()
            except Exception as e:
                print(f"  ERROR processing: {e}")
                continue
            results["per_question"].append(r)
            completed_count += 1

            # Affichage progression
            ll = r["scores"].get("llama-3.3-70b", {}).get("score")
            qw = r["scores"].get("qwen-2.5-72b", {}).get("score")
            ll_s = f"{ll:.2f}" if ll is not None else "ERR"
            qw_s = f"{qw:.2f}" if qw is not None else "ERR"
            elapsed_total = int(time.time() - t0)
            eta = int(elapsed_total / max(1, completed_count - len(done_qids)) * (len(questions) - completed_count))
            print(f"  [{completed_count}/{len(questions)}] {r['question_id']:<8} {r['category']:<22} | "
                  f"iter={r.get('agent_n_iterations',0)} tools={r.get('agent_n_tool_calls',0)} "
                  f"tokens={r.get('agent_tokens_total',0)} | Llama={ll_s} Qwen={qw_s} "
                  f"V4.2={r['v4_2_score_bench']:.2f} | eta={eta}s")

            # Sauvegarde incrémentale tous les 5 résultats
            if completed_count % 5 == 0:
                with open(OUT, "w", encoding="utf-8") as f:
                    json.dump(results, f, indent=2, ensure_ascii=False)

    elapsed = time.time() - t0
    print(f"\n=== Done. {len(results['per_question'])} questions, {elapsed:.0f}s ===")

    # Final save
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)

    # Aggregation
    print_summary(results)


def print_summary(results: dict):
    from collections import defaultdict
    by_judge = defaultdict(list)
    by_cat_judge = defaultdict(lambda: defaultdict(list))
    bench_v3, bench_v42 = [], []

    for q in results["per_question"]:
        for jname, jdata in q.get("scores", {}).items():
            s = jdata.get("score") if isinstance(jdata, dict) else None
            if s is not None:
                by_judge[jname].append(s)
                by_cat_judge[q["category"]][jname].append(s)
        bench_v3.append(q["v3_score_bench"])
        bench_v42.append(q["v4_2_score_bench"])

    print("\n" + "=" * 90)
    print("RÉSUMÉ — Reading Agent sur 170q Robustness aerospace")
    print("=" * 90)
    print(f"\n{'Source':<35} {'Mean':>8} {'≥0.85':>8} {'≥0.70':>8} {'<0.50':>8} {'n':>5}")
    for jname, vs in sorted(by_judge.items()):
        n = len(vs)
        m = sum(vs) / n if n else 0
        g85 = sum(1 for v in vs if v >= 0.85)
        g70 = sum(1 for v in vs if v >= 0.70)
        lt50 = sum(1 for v in vs if v < 0.50)
        print(f"Reading Agent ({jname:<20})  {m:>8.3f} {g85:>8} {g70:>8} {lt50:>8} {n:>5}")

    # Référence V3/V4.2
    n = len(bench_v3)
    print(f"\n{'V3 bench officiel':<35}  {sum(bench_v3)/n:>8.3f} {sum(1 for v in bench_v3 if v >= 0.85):>8} {sum(1 for v in bench_v3 if v >= 0.70):>8} {sum(1 for v in bench_v3 if v < 0.50):>8} {n:>5}")
    print(f"{'V4.2 bench officiel':<35}  {sum(bench_v42)/n:>8.3f} {sum(1 for v in bench_v42 if v >= 0.85):>8} {sum(1 for v in bench_v42 if v >= 0.70):>8} {sum(1 for v in bench_v42 if v < 0.50):>8} {n:>5}")

    # Par catégorie
    print("\n" + "=" * 90)
    print("PAR CATÉGORIE (juge Llama-3.3-70B)")
    print("=" * 90)
    print(f"{'Category':<28} {'n':>5} {'Reading Agent':>15} {'V3':>8} {'V4.2':>8}")
    cat_v3 = defaultdict(list)
    cat_v42 = defaultdict(list)
    for q in results["per_question"]:
        cat_v3[q["category"]].append(q["v3_score_bench"])
        cat_v42[q["category"]].append(q["v4_2_score_bench"])

    for cat in sorted(by_cat_judge.keys()):
        agent_scores = by_cat_judge[cat].get("llama-3.3-70b", [])
        agent_mean = sum(agent_scores) / max(1, len(agent_scores))
        v3_mean = sum(cat_v3[cat]) / max(1, len(cat_v3[cat]))
        v42_mean = sum(cat_v42[cat]) / max(1, len(cat_v42[cat]))
        print(f"{cat:<28} {len(agent_scores):>5} {agent_mean:>15.3f} {v3_mean:>8.3f} {v42_mean:>8.3f}")


if __name__ == "__main__":
    main()
