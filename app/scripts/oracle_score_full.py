"""Scoring complet 3 juges sur toutes les sources Oracle audit.

Sources consolidées :
  - Oracle Claude (oracle_answers.json) : 30
  - V3, V4.2 (oracle_audit_sample.json) : 60
  - DeepSeek-V3.1, R1, Qwen-72B (alt_models_answers.json) : 180
  - GPT-4o (libre/strict/ext), o1, o3-mini (openai_answers.json) : ~150
  Total ~420 réponses

Juges :
  - Llama-3.3-70B (DeepInfra) — juge officiel des benchs
  - Qwen-2.5-72B (DeepInfra) — cross-check
  - GPT-4o-mini (OpenAI) — 3e juge frontier (~$0.20)

Output : /app/data/benchmark/oracle_audit/full_scoring.json
"""
import json
import os
import re
import sys
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import requests

SAMPLE = "/app/data/benchmark/oracle_audit/oracle_audit_sample.json"
ORACLE = "/app/data/benchmark/oracle_audit/oracle_answers.json"
ALT = "/app/data/benchmark/oracle_audit/alt_models_answers.json"
OPENAI = "/app/data/benchmark/oracle_audit/openai_answers.json"
OUT = Path("/app/data/benchmark/oracle_audit/full_scoring.json")

DEEPINFRA_KEY = os.getenv("DEEPINFRA_API_KEY", "").strip()
OPENAI_KEY = os.getenv("OPENAI_API_KEY", "").strip()

JUDGES = {
    "llama-3.3-70b": {"provider": "deepinfra", "id": "meta-llama/Llama-3.3-70B-Instruct"},
    "qwen-2.5-72b": {"provider": "deepinfra", "id": "Qwen/Qwen2.5-72B-Instruct"},
    "gpt-4o-mini": {"provider": "openai", "id": "gpt-4o-mini"},
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


def call_judge(judge_name, prompt, max_retries=3):
    info = JUDGES[judge_name]
    if info["provider"] == "deepinfra":
        url = "https://api.deepinfra.com/v1/openai/chat/completions"
        key = DEEPINFRA_KEY
    else:
        url = "https://api.openai.com/v1/chat/completions"
        key = OPENAI_KEY

    payload = {
        "model": info["id"],
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": 100,
        "temperature": 0.0,
    }

    last_err = None
    for attempt in range(max_retries):
        try:
            r = requests.post(
                url,
                headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
                json=payload,
                timeout=120,
            )
            r.raise_for_status()
            data = r.json()
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
            usage = data.get("usage", {})
            return {"score": score, "reason": reason, "usage": usage, "error": None}
        except Exception as e:
            last_err = e
            if attempt < max_retries - 1:
                time.sleep(2 ** (attempt + 1))
    return {"score": None, "reason": "", "usage": {}, "error": str(last_err)}


def load_all_sources():
    """Charge toutes les sources et retourne {qid: {source_name: text}}."""
    sample = json.load(open(SAMPLE))
    oracle = json.load(open(ORACLE))
    alt = json.load(open(ALT))
    openai_ans = json.load(open(OPENAI)) if Path(OPENAI).exists() else {"per_question": []}

    questions_meta = {q["question_id"]: q for q in sample["questions"]}
    sources_by_qid = defaultdict(dict)

    # 1. V3, V4.2, Oracle Claude
    for q in sample["questions"]:
        qid = q["question_id"]
        sources_by_qid[qid]["v3"] = q["v3"]["answer"] or ""
        sources_by_qid[qid]["v4_2"] = q["v4_2"]["answer"] or ""
    for qid, ans in oracle["answers"].items():
        sources_by_qid[qid]["oracle_claude"] = ans

    # 2. Alt models (DeepSeek-V3.1/R1, Qwen-72B) — flatten model + option
    for q in alt["per_question"]:
        qid = q["question_id"]
        for model_name, options in q["answers"].items():
            for option, ans_data in options.items():
                if ans_data and ans_data.get("text"):
                    src_key = f"{model_name}_{option}"
                    sources_by_qid[qid][src_key] = ans_data["text"]

    # 3. OpenAI tests
    for q in openai_ans.get("per_question", []):
        qid = q["question_id"]
        for test_label, ans_data in q.get("answers", {}).items():
            if ans_data and ans_data.get("text"):
                sources_by_qid[qid][test_label] = ans_data["text"]

    return questions_meta, dict(sources_by_qid)


def main():
    questions_meta, sources_by_qid = load_all_sources()
    print(f"Loaded {len(sources_by_qid)} questions")
    src_counter = defaultdict(int)
    for qid, srcs in sources_by_qid.items():
        for s in srcs:
            src_counter[s] += 1
    print(f"Sources per type:")
    for s, n in sorted(src_counter.items()):
        print(f"  {s:<35} : {n}")

    # Reprise
    if OUT.exists():
        results = json.load(open(OUT))
        print(f"[resume] {len(results.get('per_question', []))} questions déjà scorées")
    else:
        results = {"_judges": JUDGES, "per_question": []}

    done_qids = {q["question_id"] for q in results["per_question"]}
    qids_todo = [qid for qid in sorted(sources_by_qid) if qid not in done_qids]
    print(f"À scorer : {len(qids_todo)}/30 questions\n")

    t0 = time.time()
    total_judge_calls = 0
    for i, qid in enumerate(qids_todo):
        sources = sources_by_qid[qid]
        meta = questions_meta[qid]
        category = meta["category"]
        expected = (meta.get("ground_truth") or {}).get("expected_behavior", "")
        evidence = (meta.get("ground_truth") or {}).get("correct_fact", "") or (meta.get("ground_truth") or {}).get("evidence_claim", "")
        criteria = CATEGORY_JUDGE_CRITERIA.get(category, "")
        evidence_line = f'Reference evidence: "{evidence[:300]}"' if evidence else ""

        per_q = {"question_id": qid, "category": category, "scoring": {}}
        print(f"[{i+1}/{len(qids_todo)}] {qid} | {category} | {len(sources)} sources")

        # Score chaque source par 3 juges en parallèle
        def score_one_source(src_name, ans_text):
            judge_results = {}
            for judge_name in JUDGES:
                jp = JUDGE_PROMPT_TEMPLATE.format(
                    question=meta["question"][:200],
                    category=category,
                    expected=expected,
                    evidence_line=evidence_line,
                    criteria=criteria,
                    answer=ans_text[:3000],
                )
                judge_results[judge_name] = call_judge(judge_name, jp)
            return src_name, judge_results

        with ThreadPoolExecutor(max_workers=8) as pool:
            futs = [pool.submit(score_one_source, src, txt) for src, txt in sources.items() if txt]
            for fut in as_completed(futs):
                src_name, jres = fut.result()
                total_judge_calls += len(JUDGES)
                per_q["scoring"][src_name] = jres
                ll = jres.get("llama-3.3-70b", {}).get("score")
                qw = jres.get("qwen-2.5-72b", {}).get("score")
                gpt = jres.get("gpt-4o-mini", {}).get("score")
                ll_s = f"{ll:.2f}" if ll is not None else "ERR"
                qw_s = f"{qw:.2f}" if qw is not None else "ERR"
                gpt_s = f"{gpt:.2f}" if gpt is not None else "ERR"
                print(f"  {src_name:<28} L={ll_s} Q={qw_s} G={gpt_s}")

        results["per_question"].append(per_q)
        with open(OUT, "w", encoding="utf-8") as f:
            json.dump(results, f, indent=2, ensure_ascii=False)

    elapsed = time.time() - t0
    print(f"\n=== Done. {total_judge_calls} judge calls, {elapsed:.0f}s ===")

    # Aggrégation
    agg = aggregate(results)
    results["aggregates"] = agg
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)

    print_summary(agg)


def aggregate(results):
    by_src_judge = defaultdict(list)
    by_cat_src_judge = defaultdict(lambda: defaultdict(list))

    for q in results["per_question"]:
        cat = q["category"]
        for src, jres in q["scoring"].items():
            for judge_name, jdata in jres.items():
                s = jdata.get("score") if isinstance(jdata, dict) else None
                if s is None:
                    continue
                by_src_judge[(src, judge_name)].append(s)
                by_cat_src_judge[cat][(src, judge_name)].append(s)

    overall = {}
    for (src, j), vs in by_src_judge.items():
        overall[f"{src}__{j}"] = {
            "mean": round(sum(vs) / len(vs), 3),
            "n": len(vs),
            "geq_0_85": sum(1 for v in vs if v >= 0.85),
            "geq_0_70": sum(1 for v in vs if v >= 0.70),
            "lt_0_50": sum(1 for v in vs if v < 0.50),
        }

    by_cat = {}
    for cat, srcj in by_cat_src_judge.items():
        by_cat[cat] = {f"{s}__{j}": round(sum(vs) / len(vs), 3) for (s, j), vs in srcj.items()}

    return {"overall": overall, "by_category": by_cat}


def print_summary(agg):
    print("\n" + "=" * 110)
    print("RÉSUMÉ — Scoring complet 3 juges")
    print("=" * 110)
    print(f"{'Source__Judge':<55} {'mean':>8} {'≥0.85':>8} {'≥0.70':>8} {'<0.50':>8} {'n':>4}")
    overall = agg["overall"]
    for k in sorted(overall.keys()):
        v = overall[k]
        print(f"{k:<55} {v['mean']:>8.3f} {v['geq_0_85']:>8} {v['geq_0_70']:>8} {v['lt_0_50']:>8} {v['n']:>4}")


if __name__ == "__main__":
    main()
