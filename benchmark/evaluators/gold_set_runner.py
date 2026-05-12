"""Generic gold-set runner — corpus-agnostic evaluator.

Consume any gold-set JSON conforming to the schema:
  [{"id", "question", "primary_type", "language",
    "ground_truth": {"answer", "exact_identifiers", "supporting_doc_ids",
                     "answerability", "false_premise"}}, ...]

Run OSMOSIS pipeline on each question, compare with ground_truth.answer via
LLM-judge, compute structured metrics. Output per_sample + global scores.

Usage:
    python -m benchmark.evaluators.gold_set_runner \\
        --gold-set-path benchmark/questions/gold_set_sap_v1.json \\
        --runtime-version v4_2 \\
        --output benchmark/results/gold_set_sap_v1_v4_2.json

No corpus-specific logic in this file. The same code runs benchmark on any
gold-set following the schema above.
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any

import requests

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

# ---------------------------------------------------------------------------
# Configuration (env-driven, no domain assumptions)
# ---------------------------------------------------------------------------
API_BASE = os.getenv("API_BASE", "http://app:8000")
JUDGE_PROVIDER = os.getenv("ROBUSTNESS_JUDGE_PROVIDER", "deepinfra")
JUDGE_MODEL = os.getenv("ROBUSTNESS_JUDGE_MODEL", "meta-llama/Llama-3.3-70B-Instruct")
DEEPINFRA_API_KEY = os.getenv("DEEPINFRA_API_KEY", "")
TENANT_ID = os.getenv("TENANT_ID", "default")


# ---------------------------------------------------------------------------
# Step 1: Run OSMOSIS pipeline on a question
# ---------------------------------------------------------------------------
def query_osmosis(question: str, runtime_version: str, timeout: int = 120) -> dict[str, Any]:
    """Call OSMOSIS runtime endpoint. Returns the response dict."""
    endpoint_seg = "v4_2" if runtime_version == "v4_2" else runtime_version
    url = f"{API_BASE}/api/runtime_{endpoint_seg}/answer"
    payload = {"question": question, "tenant_id": TENANT_ID}
    try:
        r = requests.post(url, json=payload, timeout=timeout)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        return {"error": str(e), "answer": "", "latency_ms": -1}


# ---------------------------------------------------------------------------
# Step 2: LLM-judge comparison (corpus-agnostic prompt)
# ---------------------------------------------------------------------------
JUDGE_PROMPT = """You are an expert judge evaluating the quality of an answer
produced by an automated question-answering system.

QUESTION:
{question}

REFERENCE ANSWER (written by a domain expert):
{ref}

SYSTEM ANSWER (to evaluate):
{ans}

Score the SYSTEM ANSWER on the following criteria:
1. **Factual correctness** (does it match the reference answer's facts?)
2. **Completeness** (does it cover the main points of the reference?)
3. **No hallucination** (does it avoid inventing facts not in the reference?)
4. **Appropriate epistemic stance** (if the reference signals "unanswerable" or
   "false premise", does the system also abstain or refuse rather than bluff?)

Return JSON with this exact structure:
{{
  "score": <float between 0.0 and 1.0>,
  "factual_correctness": <float>,
  "completeness": <float>,
  "no_hallucination": <bool>,
  "appropriate_stance": <bool>,
  "rationale": "<one sentence explaining the score>"
}}

Score guidelines:
- 1.0 = system answer is fully correct, complete, well-stanced
- 0.7-0.9 = correct main points, minor omissions
- 0.4-0.6 = partial answer, missing key facts
- 0.1-0.3 = mostly incorrect or hallucinated
- 0.0 = wrong or harmful
"""


def llm_judge(question: str, reference: str, answer: str, max_retries: int = 3) -> dict[str, Any]:
    """Call LLM judge to score system answer against reference.
    Robust parsing : extracts JSON via regex (response_format not supported on
    all DeepInfra models). Retries on transient failures."""
    import re as _re
    prompt = JUDGE_PROMPT.format(question=question, ref=reference, ans=answer)
    last_err = None
    for attempt in range(max_retries):
        try:
            from openai import OpenAI
            client = OpenAI(
                api_key=DEEPINFRA_API_KEY,
                base_url="https://api.deepinfra.com/v1/openai",
            )
            resp = client.chat.completions.create(
                model=JUDGE_MODEL,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.0,
                max_tokens=600,
            )
            content = (resp.choices[0].message.content or "").strip()
            if not content:
                last_err = "empty_response"
                continue
            # Try direct JSON parse first
            try:
                return json.loads(content)
            except json.JSONDecodeError:
                pass
            # Extract first {...} block (handle prefixes/suffixes from non-strict models)
            m = _re.search(r"\{.*\}", content, _re.DOTALL)
            if m:
                try:
                    return json.loads(m.group(0))
                except json.JSONDecodeError as e:
                    last_err = f"json_parse_after_regex: {e}"
            else:
                last_err = "no_json_block_in_response"
        except Exception as e:
            last_err = str(e)
        # Brief backoff
        import time as _time
        _time.sleep(1 + attempt)
    return {"error": last_err or "judge_failed", "score": -1.0}


# ---------------------------------------------------------------------------
# Step 3: Structured metrics (corpus-agnostic)
# ---------------------------------------------------------------------------
def exact_match_identifiers(answer: str, expected: list[str]) -> dict[str, Any]:
    """Count how many expected identifiers appear in the answer (case-insensitive)."""
    if not expected:
        return {"n_matched": 0, "n_expected": 0, "score": None}
    ans_lower = answer.lower()
    matched = sum(1 for ident in expected if ident.lower() in ans_lower)
    return {
        "n_matched": matched,
        "n_expected": len(expected),
        "score": matched / len(expected) if expected else None,
    }


def citation_presence(answer: str, expected_doc_ids: list[str]) -> dict[str, Any]:
    """Check if any of the expected supporting doc_ids are cited in the answer."""
    if not expected_doc_ids:
        return {"n_cited": 0, "n_expected": 0, "score": None}
    cited = sum(1 for d in expected_doc_ids if d in answer or d.split("_")[0] in answer)
    return {
        "n_cited": cited,
        "n_expected": len(expected_doc_ids),
        "score": cited / len(expected_doc_ids) if expected_doc_ids else None,
    }


# ---------------------------------------------------------------------------
# Step 4: Run one sample
# ---------------------------------------------------------------------------
def evaluate_sample(item: dict[str, Any], runtime_version: str) -> dict[str, Any]:
    """Evaluate one gold-set item end-to-end."""
    qid = item.get("id")
    question = item.get("question")
    gt = item.get("ground_truth", {})
    ref_answer = gt.get("answer", "")
    expected_ids = gt.get("exact_identifiers", [])
    expected_docs = gt.get("supporting_doc_ids", [])

    t0 = time.time()
    osmosis_resp = query_osmosis(question, runtime_version)
    latency_ms = int((time.time() - t0) * 1000)

    osmosis_answer = osmosis_resp.get("answer", "")

    # LLM-judge
    judge = llm_judge(question, ref_answer, osmosis_answer)

    # Structured metrics
    em = exact_match_identifiers(osmosis_answer, expected_ids)
    cp = citation_presence(osmosis_answer, expected_docs)

    structured_avg_parts = [m["score"] for m in (em, cp) if m.get("score") is not None]
    structured_avg = sum(structured_avg_parts) / len(structured_avg_parts) if structured_avg_parts else None

    judge_score = judge.get("score", -1.0)
    disagreement = None
    if judge_score >= 0 and structured_avg is not None:
        disagreement = abs(judge_score - structured_avg)

    return {
        "id": qid,
        "question": question,
        "primary_type": item.get("primary_type"),
        "reference_answer": ref_answer,
        "osmosis_answer": osmosis_answer,
        "latency_ms": latency_ms,
        "judge": judge,
        "structured_metrics": {
            "exact_match_identifiers": em,
            "citation_presence": cp,
            "structured_avg": structured_avg,
        },
        "disagreement": disagreement,
        "osmosis_meta": {k: v for k, v in osmosis_resp.items() if k not in ("answer",)},
    }


# ---------------------------------------------------------------------------
# Step 5: Aggregate + report
# ---------------------------------------------------------------------------
def aggregate(per_sample: list[dict[str, Any]]) -> dict[str, Any]:
    """Compute global + per-category scores."""
    judge_scores = [s["judge"].get("score", -1) for s in per_sample if s["judge"].get("score", -1) >= 0]
    avg_judge = sum(judge_scores) / len(judge_scores) if judge_scores else 0.0

    em_scores = [s["structured_metrics"]["exact_match_identifiers"]["score"]
                 for s in per_sample
                 if s["structured_metrics"]["exact_match_identifiers"]["score"] is not None]
    avg_em = sum(em_scores) / len(em_scores) if em_scores else 0.0

    cp_scores = [s["structured_metrics"]["citation_presence"]["score"]
                 for s in per_sample
                 if s["structured_metrics"]["citation_presence"]["score"] is not None]
    avg_cp = sum(cp_scores) / len(cp_scores) if cp_scores else 0.0

    # Per-category breakdown
    from collections import defaultdict
    by_cat = defaultdict(list)
    for s in per_sample:
        if s["judge"].get("score", -1) >= 0:
            by_cat[s["primary_type"]].append(s["judge"]["score"])
    cat_scores = {cat: sum(v) / len(v) if v else 0.0 for cat, v in by_cat.items()}

    return {
        "global": {
            "avg_judge_score": round(avg_judge, 3),
            "avg_exact_match_identifiers": round(avg_em, 3),
            "avg_citation_presence": round(avg_cp, 3),
            "n_evaluated": len(per_sample),
            "n_judge_failed": sum(1 for s in per_sample if s["judge"].get("score", -1) < 0),
        },
        "by_category": {k: round(v, 3) for k, v in cat_scores.items()},
    }


# ---------------------------------------------------------------------------
# Main entry
# ---------------------------------------------------------------------------
def run(gold_set_path: Path, runtime_version: str, output_path: Path) -> dict[str, Any]:
    items = json.loads(gold_set_path.read_text(encoding="utf-8"))
    logger.info(f"Loaded {len(items)} questions from {gold_set_path}")
    logger.info(f"Runtime: {runtime_version} | Judge: {JUDGE_MODEL}")

    per_sample = []
    for i, item in enumerate(items, 1):
        logger.info(f"[{i}/{len(items)}] {item.get('id')} — {item.get('primary_type')}")
        try:
            result = evaluate_sample(item, runtime_version)
            per_sample.append(result)
            logger.info(f"  → judge={result['judge'].get('score', 'fail')} "
                        f"latency={result['latency_ms']}ms")
        except Exception as e:
            logger.error(f"  Sample {item.get('id')} failed: {e}")

    scores = aggregate(per_sample)

    report = {
        "metadata": {
            "gold_set_path": str(gold_set_path),
            "runtime_version": runtime_version,
            "judge_model": JUDGE_MODEL,
            "tenant_id": TENANT_ID,
            "ran_at": datetime.utcnow().isoformat(),
        },
        "scores": scores,
        "per_sample": per_sample,
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    logger.info(f"\n✓ Report written: {output_path}")
    logger.info(f"  Global avg_judge_score: {scores['global']['avg_judge_score']}")
    logger.info(f"  Per-category: {scores['by_category']}")
    return report


def main():
    parser = argparse.ArgumentParser(description="Generic gold-set evaluator (corpus-agnostic).")
    parser.add_argument("--gold-set-path", required=True, type=Path,
                        help="Path to gold-set JSON file (any corpus).")
    parser.add_argument("--runtime-version", default="v4_2",
                        help="OSMOSIS runtime version (v2/v3/v4/v4_2).")
    parser.add_argument("--output", type=Path,
                        help="Output path (default: benchmark/results/gold_set_{name}_{runtime}.json)")
    args = parser.parse_args()

    if not args.output:
        stem = args.gold_set_path.stem
        args.output = Path(f"benchmark/results/{stem}_{args.runtime_version}_{int(time.time())}.json")

    run(args.gold_set_path, args.runtime_version, args.output)


if __name__ == "__main__":
    main()
