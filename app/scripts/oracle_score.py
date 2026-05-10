"""Score les 30 questions Oracle avec deux juges DeepInfra.

Pour chaque question, score 3 sources (Oracle/V3/V4.2) avec 2 juges :
- Llama-3.3-70B-Instruct (judge actuel des benchs)
- Qwen2.5-72B-Instruct (cross-check, voir mémoire variance ±5-8pp)

Total : 30 × 3 × 2 = 180 appels DeepInfra (~10-15 min).

Output : /app/data/benchmark/oracle_audit/oracle_scoring_results.json
"""
import json
import os
import re
import sys
import time
from collections import defaultdict
from pathlib import Path

import requests

SAMPLE = "/app/data/benchmark/oracle_audit/oracle_audit_sample.json"
ORACLE = "/app/data/benchmark/oracle_audit/oracle_answers.json"
OUT = "/app/data/benchmark/oracle_audit/oracle_scoring_results.json"

DEEPINFRA_KEY = os.getenv("DEEPINFRA_API_KEY", "").strip()
if not DEEPINFRA_KEY:
    print("ERROR: DEEPINFRA_API_KEY env var not set", file=sys.stderr)
    sys.exit(1)

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
    """Appelle DeepInfra avec retry exponentiel 2s/4s/8s."""
    last_error = None
    for attempt in range(max_retries):
        try:
            resp = requests.post(
                "https://api.deepinfra.com/v1/openai/chat/completions",
                headers={
                    "Authorization": f"Bearer {DEEPINFRA_KEY}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": model_id,
                    "messages": [{"role": "user", "content": prompt}],
                    "max_tokens": 100,
                    "temperature": 0.0,
                },
                timeout=120,
            )
            resp.raise_for_status()
            data = resp.json()
            text = data["choices"][0]["message"]["content"].strip()
            score_m = re.search(r"SCORE\s*:\s*(\d+)", text, re.IGNORECASE)
            reason_m = re.search(r"REASON\s*:\s*(.+?)(?:$|\n)", text, re.IGNORECASE | re.DOTALL)
            if score_m:
                score = int(score_m.group(1)) / 100.0
            else:
                m = re.search(r"\d+", text)
                score = (int(m.group()) / 100.0) if m else 0.0
            score = max(0.0, min(1.0, score))
            reason = reason_m.group(1).strip() if reason_m else ""
            return {"score": score, "reason": reason, "raw": text, "error": None}
        except Exception as e:
            last_error = e
            if attempt < max_retries - 1:
                wait = 2 ** (attempt + 1)
                print(f"    [retry {attempt+1}/{max_retries}] {type(e).__name__}: {e} — waiting {wait}s")
                time.sleep(wait)
    return {"score": None, "reason": "", "raw": "", "error": str(last_error)}


def main():
    sample = json.load(open(SAMPLE))
    oracle = json.load(open(ORACLE))
    oracle_answers = oracle["answers"]
    questions = sample["questions"]

    print(f"Loaded {len(questions)} questions")
    print(f"Oracle answers : {len(oracle_answers)}")
    missing = [q["question_id"] for q in questions if q["question_id"] not in oracle_answers]
    if missing:
        print(f"WARNING: missing oracle answers for: {missing}")

    results = []
    judge_calls = 0
    judge_failures = 0
    t0 = time.time()

    for i, q in enumerate(questions):
        qid = q["question_id"]
        category = q["category"]
        question = q["question"]
        gt = q["ground_truth"] or {}
        expected = gt.get("expected_behavior", "")
        evidence = gt.get("correct_fact") or gt.get("evidence_claim") or ""
        criteria = CATEGORY_JUDGE_CRITERIA.get(category, "A good answer addresses the question based on the sources.")

        evidence_line = f'Reference evidence: "{evidence[:300]}"' if evidence else ""

        v3_answer = q["v3"]["answer"]
        v42_answer = q["v4_2"]["answer"]
        oracle_answer = oracle_answers.get(qid, "")

        sources = {"oracle": oracle_answer, "v3": v3_answer, "v4_2": v42_answer}

        per_q = {
            "question_id": qid,
            "category": category,
            "question": question[:200],
            "ground_truth_correct_fact": evidence[:200],
            "v3_score_bench": q["v3"]["score"],
            "v4_2_score_bench": q["v4_2"]["score"],
            "scoring": {},
        }

        for src_name, ans in sources.items():
            if not ans:
                per_q["scoring"][src_name] = {"empty_answer": True}
                continue

            prompt = JUDGE_PROMPT_TEMPLATE.format(
                question=question[:200],
                category=category,
                expected=expected,
                evidence_line=evidence_line,
                criteria=criteria,
                answer=ans[:3000],
            )

            judges_out = {}
            for judge_name, model_id in JUDGES.items():
                out = call_judge(model_id, prompt)
                judge_calls += 1
                if out["error"]:
                    judge_failures += 1
                    print(f"  [{i+1}/{len(questions)}] {qid} {src_name} {judge_name} ERROR: {out['error']}")
                else:
                    print(f"  [{i+1}/{len(questions)}] {qid} {src_name} {judge_name} score={out['score']:.2f}")
                judges_out[judge_name] = out

            per_q["scoring"][src_name] = judges_out

        results.append(per_q)

    elapsed = time.time() - t0
    print(f"\n=== Done. {judge_calls} calls, {judge_failures} failures, {elapsed:.0f}s elapsed ===")

    # Agrégation
    agg = compute_aggregates(results)

    output = {
        "_judges": JUDGES,
        "_total_calls": judge_calls,
        "_total_failures": judge_failures,
        "_elapsed_seconds": int(elapsed),
        "aggregates": agg,
        "per_question": results,
    }

    Path(OUT).parent.mkdir(exist_ok=True, parents=True)
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)

    print(f"\nSaved to {OUT}")
    print_summary(agg)


def compute_aggregates(results):
    """Calcule moyennes par source × juge × catégorie."""
    by_source_judge = defaultdict(list)  # (source, judge) -> [scores]
    by_cat_source_judge = defaultdict(list)  # (cat, source, judge) -> [scores]

    for r in results:
        cat = r["category"]
        for src, judges_out in r["scoring"].items():
            if not isinstance(judges_out, dict) or "empty_answer" in judges_out:
                continue
            for judge_name, out in judges_out.items():
                if isinstance(out, dict) and out.get("score") is not None:
                    by_source_judge[(src, judge_name)].append(out["score"])
                    by_cat_source_judge[(cat, src, judge_name)].append(out["score"])

    overall = {}
    for (src, judge), scores in by_source_judge.items():
        overall[f"{src}_{judge}"] = {
            "mean": round(sum(scores) / len(scores), 3),
            "n": len(scores),
            "min": round(min(scores), 3),
            "max": round(max(scores), 3),
            "geq_0_85": sum(1 for s in scores if s >= 0.85),
            "geq_0_70": sum(1 for s in scores if s >= 0.70),
            "lt_0_50": sum(1 for s in scores if s < 0.50),
        }

    by_cat = defaultdict(dict)
    for (cat, src, judge), scores in by_cat_source_judge.items():
        by_cat[cat][f"{src}_{judge}"] = round(sum(scores) / len(scores), 3)

    return {"overall": overall, "by_category": dict(by_cat)}


def print_summary(agg):
    print("\n" + "=" * 70)
    print("RÉSUMÉ — Moyenne globale par source × juge")
    print("=" * 70)
    overall = agg["overall"]
    keys_sorted = sorted(overall.keys())
    print(f"{'Combination':<30} {'mean':>8} {'≥0.85':>8} {'≥0.70':>8} {'<0.50':>8} {'n':>4}")
    for k in keys_sorted:
        v = overall[k]
        print(f"{k:<30} {v['mean']:>8.3f} {v['geq_0_85']:>8} {v['geq_0_70']:>8} {v['lt_0_50']:>8} {v['n']:>4}")

    print("\n" + "=" * 70)
    print("Moyenne par catégorie (Oracle vs V3 vs V4.2, juge Llama-3.3-70B)")
    print("=" * 70)
    print(f"{'Category':<25} {'Oracle':>8} {'V3':>8} {'V4.2':>8}")
    for cat, scores in agg["by_category"].items():
        o = scores.get("oracle_llama-3.3-70b", float("nan"))
        v3 = scores.get("v3_llama-3.3-70b", float("nan"))
        v42 = scores.get("v4_2_llama-3.3-70b", float("nan"))
        print(f"{cat:<25} {o:>8.3f} {v3:>8.3f} {v42:>8.3f}")


if __name__ == "__main__":
    main()
