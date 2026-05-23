"""A4.7 Step 3 — Test Synthesize Oracle (upper bound réel du Synthesize).

Pour chaque question, on COURT-CIRCUITE Parse/Plan/Execute/Evaluate :
- On construit un SynthesizeInput minimal avec les top-K claims oracle (issus de Step 1)
- On appelle directement Synthesizer.synthesize()
- On mesure C1 via llm_judge (même que bench_a38)

Objectif : si C1_oracle ≈ 0.8-0.9 → Synthesize OK, le problème est en amont (retrieval).
          Si C1_oracle ≈ 0.3 → Synthesize lui-même cassé (impossible de répondre même avec bons claims).

Usage :
    docker exec knowbase-app python scripts/audit_oracle_step3_synthesize_test.py
"""

from __future__ import annotations

import json
import logging
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("audit_oracle_step3")


ORACLE_INPUT = Path("data/benchmark/a47_oracle_audit/oracle_expected_claims_20q.json")
OUTPUT_PATH = Path("data/benchmark/a47_oracle_audit/synthesize_oracle_results.json")
TOP_K_INJECT = 5  # combien de claims top oracle on injecte dans le Synthesize


def llm_judge(question: str, answer: str, ground_truth: str) -> Dict[str, Any]:
    """Réutilise le judge LLM du bench A3.8 (DeepSeek-V3.1 via long_summary)."""
    from knowbase.common.llm_router import LLMRouter, TaskType
    JUDGE_SYSTEM = """You are an impartial benchmark judge.

Compare a candidate ANSWER vs a REFERENCE ground truth. Decide if the candidate
correctly answers the question (semantically equivalent to or stricter than
reference). Tolerate paraphrasing.

Score guide:
- 1.0 : answer fully matches reference (same facts, same conclusion)
- 0.5 : partial match (some facts correct, missing context OR small errors)
- 0.0 : wrong / hallucinated / unrelated

For ABSTENTION cases: if ground_truth says "out of scope" or marks the question
as unanswerable, and the candidate answer abstains → score 1.0.
If candidate fabricates facts on out-of-scope → 0.0.

OUTPUT JSON ONLY:
{"score": 0.0|0.5|1.0, "reasoning": "<short>"}
"""
    try:
        router = LLMRouter()
        user = (
            f"QUESTION: {question}\n\n"
            f"REFERENCE (ground truth): {ground_truth}\n\n"
            f"CANDIDATE ANSWER: {answer}\n\n"
            "Respond with JSON only."
        )
        raw = router.complete(
            task_type=TaskType.FAST_CLASSIFICATION,
            messages=[
                {"role": "system", "content": JUDGE_SYSTEM},
                {"role": "user", "content": user},
            ],
            temperature=0.0,
            max_tokens=200,
        )
        raw = raw.strip()
        # strip markdown fences
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        return json.loads(raw)
    except Exception as e:
        logger.warning("llm_judge failed: %s", e)
        return {"score": 0.0, "reasoning": f"judge_error: {e}"}


def build_synthesize_input_oracle(
    question: str,
    oracle_claims: List[Dict[str, Any]],
) -> Any:
    """Construit un SynthesizeInput minimal avec les claims oracle injectés."""
    from knowbase.runtime_a3.schemas import (
        ParseOutput, SubGoal, PlanOutput, EvaluateOutput,
        ExecuteOutput, ToolResult, ClaimSummary, SynthesizeInput,
    )

    # ParseOutput minimal — 1 sub_goal fact_lookup
    parse = ParseOutput(
        sub_goals=[SubGoal(
            kind="fact_lookup",
            subject_canonical=None,
            predicate_hint=None,
            object_hint=None,
            expected_value_kind="string",
            time_filter="current",
            priority=1,
        )],
        entities=[],
        language="fr",
        raw_question=question,
        parse_confidence=1.0,
        parse_warnings=[],
    )

    # ExecuteOutput avec un seul ToolResult contenant les claims oracle
    claims_summaries = []
    for c in oracle_claims:
        claims_summaries.append(ClaimSummary(
            claim_id=c["claim_id"],
            subject_canonical=c.get("subject_canonical"),
            predicate=c.get("predicate"),
            value=c.get("value") or c.get("claim_text"),  # fallback sur texte complet
            confidence=0.95,
            source_doc_id=c.get("doc_id"),
        ))

    execute = ExecuteOutput(
        results=[ToolResult(
            sub_goal_idx=0,
            tool="kg_claims",
            claims=claims_summaries,
            coverage_signal="full",
            duration_s=0.0,
        )],
        total_duration_s=0.0,
    )

    # EvaluateOutput : CORRECT verdict avec haute confidence
    evaluate = EvaluateOutput(
        verdict="CORRECT",
        covered_sub_goals=[0],
        uncovered_sub_goals=[],
        re_plan_hint="none",
        confidence=1.0,
        reasoning="oracle: claims injectés manuellement",
    )

    return SynthesizeInput(
        parse_output=parse,
        execute_output=execute,
        evaluate_output=evaluate,
        response_mode="structured",
    )


def main():
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)

    with open(ORACLE_INPUT, "r", encoding="utf-8") as f:
        oracle_data = json.load(f)

    from knowbase.runtime_a3.synthesize import Synthesizer

    synth = Synthesizer()

    results = []
    n_ok = 0
    n_failed = 0
    scores: List[float] = []

    for i, q in enumerate(oracle_data, 1):
        if not q.get("top_candidates"):
            logger.warning("[%d/%d] %s — SKIP (no oracle claims)", i, len(oracle_data), q["id"])
            results.append({
                "id": q["id"],
                "question": q["question"],
                "skipped_reason": q.get("note", "no_top_candidates"),
                "judge_score": None,
            })
            continue

        top = q["top_candidates"][:TOP_K_INJECT]
        logger.info("[%d/%d] %s — injecting %d oracle claims", i, len(oracle_data), q["id"], len(top))

        inp = build_synthesize_input_oracle(q["question"], top)
        t0 = time.perf_counter()
        try:
            out = synth.synthesize(inp)
            dt = time.perf_counter() - t0
            answer = out.answer_text
            n_ok += 1
        except Exception as e:
            dt = time.perf_counter() - t0
            logger.exception("Synthesize failed for %s", q["id"])
            results.append({
                "id": q["id"],
                "question": q["question"],
                "error": str(e)[:300],
                "judge_score": 0.0,
            })
            n_failed += 1
            continue

        # Judge
        gt = q["ground_truth_answer"]
        judge = llm_judge(q["question"], answer, gt) if gt else {"score": 0.0, "reasoning": "no_gt"}
        scores.append(float(judge["score"]))

        logger.info("  → answer (%d chars): %s", len(answer), answer[:120])
        logger.info("  → judge score: %s | reasoning: %s", judge["score"], judge.get("reasoning", "")[:80])

        results.append({
            "id": q["id"],
            "primary_type": q.get("primary_type"),
            "question": q["question"],
            "ground_truth_answer": gt,
            "top_oracle_claim_text": top[0]["claim_text"] if top else None,
            "top_oracle_claim_score": top[0]["score"] if top else None,
            "answer_text": answer,
            "n_cited_claims": len(out.cited_claims) if hasattr(out, "cited_claims") else 0,
            "mode": getattr(out, "mode", "?"),
            "duration_s": dt,
            "judge_score": judge["score"],
            "judge_reasoning": judge.get("reasoning", ""),
        })

    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, ensure_ascii=False, default=str)
    logger.info("Wrote %s", OUTPUT_PATH)

    logger.info("=" * 60)
    n_tested = len(scores)
    mean_c1 = sum(scores) / n_tested if n_tested else 0
    logger.info("Synthesize Oracle results: n_tested=%d, n_ok=%d, n_failed=%d", n_tested, n_ok, n_failed)
    logger.info("C1_oracle (mean) = %.3f", mean_c1)
    by_score = {1.0: 0, 0.5: 0, 0.0: 0}
    for s in scores:
        if s >= 0.99:
            by_score[1.0] += 1
        elif s >= 0.4:
            by_score[0.5] += 1
        else:
            by_score[0.0] += 1
    logger.info("Distribution: 1.0=%d, 0.5=%d, 0.0=%d", by_score[1.0], by_score[0.5], by_score[0.0])
    logger.info("=" * 60)
    logger.info("VERDICT:")
    if mean_c1 >= 0.7:
        logger.info("  ✅ Synthesize OK quand on lui donne les bons claims — bottleneck = retrieval/evaluator")
    elif mean_c1 >= 0.4:
        logger.info("  ⚠ Synthesize partiellement OK — gap mixte retrieval ET Synthesize")
    else:
        logger.info("  ❌ Synthesize cassé — même avec bons claims ne répond pas")


if __name__ == "__main__":
    main()
