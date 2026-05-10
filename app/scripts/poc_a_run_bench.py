"""POC-A — bench Reading Agent sur 5 questions both-KO + scoring 2 juges.

Sélection (gap Oracle vs V4.2 maximal) :
  q_0  — false_premise (Oracle 1.00, V4.2 0.20)
  q_45 — causal_why    (Oracle 0.95, V4.2 0.00)
  q_94 — set_list      (Oracle 0.95, V4.2 0.00)
  q_82 — multi_hop     (Oracle 0.95, V4.2 0.00)
  q_27 — temporal      (Oracle 0.95, V4.2 0.07)

Output:
  /app/data/benchmark/oracle_audit/poc_a_results.json
"""
import json
import os
import re
import sys
import time
from pathlib import Path

import requests

sys.path.insert(0, "/app/src")
from knowbase.runtime_v5.reasoning_agent import run_agent

SAMPLE = "/app/data/benchmark/oracle_audit/oracle_audit_sample.json"
OUT = Path("/app/data/benchmark/oracle_audit/poc_a_results.json")
OUT.parent.mkdir(parents=True, exist_ok=True)

DEEPINFRA_KEY = os.getenv("DEEPINFRA_API_KEY", "").strip()

# 5 questions sélectionnées
TARGET_QIDS = ["q_0", "q_45", "q_94", "q_82", "q_27"]

# Juges (mêmes que CH-50 pour comparaison)
JUDGES = {
    "llama-3.3-70b": "meta-llama/Llama-3.3-70B-Instruct",
    "qwen-2.5-72b": "Qwen/Qwen2.5-72B-Instruct",
}

CATEGORY_JUDGE_CRITERIA = {
    "false_premise": "The question contains a FALSE premise. A good answer should CORRECT the false premise and provide the correct information from the sources. A bad answer accepts the false premise without questioning it.",
    "temporal_evolution": "The question asks about how something CHANGED between document versions. A good answer identifies specific changes and cites both versions. A bad answer is vague or doesn't compare versions.",
    "causal_why": "The question asks WHY something is done. A good answer explains the reason based on documented facts. A bad answer gives generic reasons not grounded in the sources.",
    "set_list": "The question asks to LIST or ENUMERATE items. A good answer lists the correct items from the sources. A bad answer misses items or lists wrong ones.",
    "multi_hop": "The question requires CHAINING facts from multiple sources. A good answer connects the facts logically. A bad answer only addresses part of the chain.",
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


def main():
    sample = json.load(open(SAMPLE))
    questions_by_qid = {q["question_id"]: q for q in sample["questions"]}
    targets = [questions_by_qid[qid] for qid in TARGET_QIDS if qid in questions_by_qid]
    print(f"Target questions: {[q['question_id'] for q in targets]}\n")

    results = {"per_question": []}
    for i, q in enumerate(targets):
        qid = q["question_id"]
        question = q["question"]
        category = q["category"]
        gt = q.get("ground_truth") or {}
        expected = gt.get("expected_behavior", "")
        evidence = gt.get("correct_fact", "") or gt.get("evidence_claim", "")
        criteria = CATEGORY_JUDGE_CRITERIA.get(category, "")

        print(f"\n{'='*80}")
        print(f"[{i+1}/{len(targets)}] {qid} | {category}")
        print(f"Q: {question}")
        print(f"GT: {evidence[:200]}")
        print(f"{'='*80}")

        # Run Reading Agent
        t0 = time.time()
        agent_result = run_agent(question, max_iterations=8, verbose=True)
        elapsed = time.time() - t0
        agent_answer = agent_result.get("answer", "")

        print(f"\n[ANSWER] {agent_answer[:300]}...")

        # Score
        evidence_line = f'Reference evidence: "{evidence[:300]}"' if evidence else ""
        judge_prompt = JUDGE_PROMPT_TEMPLATE.format(
            question=question[:200],
            category=category,
            expected=expected,
            evidence_line=evidence_line,
            criteria=criteria,
            answer=agent_answer[:3000],
        )

        judge_results = {}
        for jname, jid in JUDGES.items():
            jr = call_judge(jid, judge_prompt)
            judge_results[jname] = jr
            print(f"  [JUDGE {jname}] score={jr['score']} | reason={jr['reason'][:80]}")

        # Compare to existing scores from CH-50
        oracle_score = None  # à charger si besoin
        v4_2_score = q["v4_2"]["score"]
        v3_score = q["v3"]["score"]

        per_q = {
            "question_id": qid,
            "category": category,
            "question": question,
            "ground_truth_correct_fact": evidence[:300],
            "agent_answer": agent_answer,
            "agent_n_iterations": agent_result["n_iterations"],
            "agent_stopped_reason": agent_result["stopped_reason"],
            "agent_tokens_total": agent_result["tokens_total"],
            "agent_n_tool_calls": len(agent_result["trace"]),
            "agent_tool_sequence": [t["tool"] for t in agent_result["trace"]],
            "agent_elapsed_s": int(elapsed),
            "scores": judge_results,
            "reference_scores": {
                "v3_bench": v3_score,
                "v4_2_bench": v4_2_score,
                # Oracle Claude était à 0.94-1.0 ; V4.2 et V3 from sample
            },
        }
        results["per_question"].append(per_q)

        # Sauvegarde incrémentale
        with open(OUT, "w", encoding="utf-8") as f:
            json.dump(results, f, indent=2, ensure_ascii=False)

    # Summary
    print(f"\n\n{'='*80}")
    print(f"=== POC-A RESULTS SUMMARY ===")
    print(f"{'='*80}\n")
    print(f"{'qid':<8} {'category':<22} {'iter':>5} {'tools':>6} {'tokens':>8} {'Llama':>7} {'Qwen':>7} {'V4.2':>7} {'Oracle':>7}")
    oracle_refs = {"q_0": 1.00, "q_45": 0.95, "q_94": 0.95, "q_82": 0.95, "q_27": 0.95}
    n_pass = 0
    for q in results["per_question"]:
        ll = q["scores"].get("llama-3.3-70b", {}).get("score") or 0
        qw = q["scores"].get("qwen-2.5-72b", {}).get("score") or 0
        v42 = q["reference_scores"]["v4_2_bench"]
        oracle = oracle_refs.get(q["question_id"], 0)
        print(f"{q['question_id']:<8} {q['category']:<22} {q['agent_n_iterations']:>5} {q['agent_n_tool_calls']:>6} {q['agent_tokens_total']:>8} {ll:>7.2f} {qw:>7.2f} {v42:>7.2f} {oracle:>7.2f}")
        if ll >= 0.70:
            n_pass += 1

    print(f"\nGate POC-A : {n_pass}/{len(results['per_question'])} questions ≥ 0.70 (Llama)")
    if n_pass >= 4:
        print("✅ POC-A VALIDÉ → lancer POC-B SAP")
    elif n_pass >= 2:
        print("⚠️ Mixed → analyser quelles questions échouent et adapter")
    else:
        print("❌ Pattern défaillant → repenser avant industrialisation")

    print(f"\nFichier final : {OUT}")


if __name__ == "__main__":
    main()
