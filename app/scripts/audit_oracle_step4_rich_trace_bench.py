"""A4.7 Step 4 — Bench 20q runtime_v6 avec rich trace pipeline complète.

Pour chaque question, on capture :
- claims_returned_by_execute : tous les claim_ids sortis d'Execute (par tool_call)
- claims_after_filter : claim_ids retenus par A3.11 claim_filter
- claims_cited : claim_ids cités par Synthesize dans answer_text
- evaluate_verdict + reasoning
- expected_claim_ids : top-5 oracle de Step 1 (référence)

Diff calculé :
- expected ∩ returned_by_execute → quels expected sont retrouvés par retrieval
- expected ∩ after_filter → quels expected survivent au filter
- expected ∩ cited → quels expected sont effectivement utilisés
- judge_score (C1)

Output : par question, on saura à quelle étape la preuve a disparu.

Usage :
    docker exec knowbase-app python scripts/audit_oracle_step4_rich_trace_bench.py
"""

from __future__ import annotations

import json
import logging
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("audit_oracle_step4")


ORACLE_INPUT = Path("data/benchmark/a47_oracle_audit/oracle_expected_claims_20q.json")
GOLD_50Q = Path("benchmark/questions/gold_set_a38_50q.json")
OUTPUT_PATH = Path("data/benchmark/a47_oracle_audit/rich_trace_bench_20q.json")
TOP_K_ORACLE = 5

_CITATION_RE = re.compile(r"\[claim_id=([a-zA-Z0-9_]+)\]")


def llm_judge(question: str, answer: str, ground_truth: str) -> Dict[str, Any]:
    from knowbase.common.llm_router import LLMRouter, TaskType
    JUDGE_SYSTEM = """You are an impartial benchmark judge.

Compare a candidate ANSWER vs a REFERENCE ground truth.
Score guide: 1.0=match, 0.5=partial, 0.0=wrong/hallucinated.
For abstention on out-of-scope: 1.0 if ground_truth marks unanswerable.

OUTPUT JSON ONLY: {"score": 0.0|0.5|1.0, "reasoning": "<short>"}"""
    try:
        router = LLMRouter()
        raw = router.complete(
            task_type=TaskType.FAST_CLASSIFICATION,
            messages=[
                {"role": "system", "content": JUDGE_SYSTEM},
                {"role": "user", "content": f"QUESTION: {question}\n\nREFERENCE: {ground_truth}\n\nANSWER: {answer}\n\nJSON only."},
            ],
            temperature=0.0, max_tokens=200,
        )
        raw = raw.strip()
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        return json.loads(raw)
    except Exception as e:
        return {"score": 0.0, "reasoning": f"judge_error: {e}"}


def main():
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)

    with open(ORACLE_INPUT, "r", encoding="utf-8") as f:
        oracle = json.load(f)

    with open(GOLD_50Q, "r", encoding="utf-8") as f:
        gold = json.load(f)
    gold_by_id = {q["id"]: q for q in gold[:20]}

    from knowbase.runtime_a3.orchestrator import Orchestrator

    orch = Orchestrator()

    results = []
    for i, oq in enumerate(oracle, 1):
        qid = oq["id"]
        q = oq["question"]
        gt = oq.get("ground_truth_answer") or gold_by_id.get(qid, {}).get("ground_truth", {}).get("answer", "")

        # Expected claim ids (top-5 oracle)
        expected_ids: Set[str] = {c["claim_id"] for c in oq.get("top_candidates", [])[:TOP_K_ORACLE]}

        logger.info("[%d/%d] %s — expected=%d", i, len(oracle), qid, len(expected_ids))

        # Run pipeline
        t0 = time.perf_counter()
        try:
            res = orch.run(
                question=q,
                tenant_id="default",
                as_of_date=datetime.now(timezone.utc),
                response_mode="structured",
            )
            dt = time.perf_counter() - t0
            ok = True
            err = None
        except Exception as e:
            dt = time.perf_counter() - t0
            logger.exception("orch failed for %s", qid)
            results.append({
                "id": qid, "question": q, "expected_claim_ids": list(expected_ids),
                "error": str(e)[:300], "ok": False,
            })
            continue

        # Extract trace
        # 1. Claims returned by Execute (last iteration's execute_output)
        last_it = res.iterations[-1] if res.iterations else None
        returned_ids: Set[str] = set()
        if last_it and hasattr(last_it, "execute_output") and last_it.execute_output:
            for r in last_it.execute_output.results:
                for c in r.claims:
                    if c.claim_id:
                        returned_ids.add(c.claim_id)

        # 2. Claims after filter — pas exposé directement, mais on a synth input
        # On peut récupérer depuis SynthesizeInput last passing through filter,
        # mais ce n'est pas directement dans res. On utilise cited_claims comme proxy aval.

        # 3. Claims cited dans answer_text
        cited_ids_in_text: Set[str] = set(_CITATION_RE.findall(res.synthesize_output.answer_text))
        # Aussi via synth.cited_claims (officiel)
        cited_ids_official: Set[str] = {c.claim_id for c in res.synthesize_output.cited_claims}
        cited_ids = cited_ids_official | cited_ids_in_text

        # Judge
        judge = llm_judge(q, res.synthesize_output.answer_text, gt) if gt else {"score": 0.0, "reasoning": "no_gt"}

        # Diff metrics
        retr_recall = len(expected_ids & returned_ids) / max(len(expected_ids), 1)
        cited_recall = len(expected_ids & cited_ids) / max(len(expected_ids), 1)

        # Verdict (où la preuve se perd)
        if not expected_ids:
            verdict = "no_oracle"
        elif retr_recall == 0:
            verdict = "lost_at_RETRIEVAL"  # 0 claim oracle ramené par Execute
        elif cited_recall == 0:
            verdict = "lost_at_FILTER_or_SYNTHESIZE"  # ramené mais pas cité
        elif judge["score"] >= 0.5:
            verdict = "OK"
        else:
            verdict = "cited_but_bad_answer"  # cité mais réponse mauvaise (Synthesize hallucine ?)

        logger.info("  → %s | retr_recall=%.2f cited_recall=%.2f judge=%s | answer: %s",
                    verdict, retr_recall, cited_recall, judge["score"],
                    res.synthesize_output.answer_text[:100])

        # Eval verdict from last iteration
        eval_verdict = None
        eval_reasoning = None
        if last_it and hasattr(last_it, "evaluate_output") and last_it.evaluate_output:
            eval_verdict = last_it.evaluate_output.verdict
            eval_reasoning = (last_it.evaluate_output.reasoning or "")[:200]

        results.append({
            "id": qid,
            "question": q,
            "primary_type": oq.get("primary_type"),
            "ground_truth_answer": gt[:300],
            "expected_claim_ids": list(expected_ids),
            "n_expected": len(expected_ids),
            "returned_claim_ids": list(returned_ids),
            "n_returned": len(returned_ids),
            "cited_claim_ids": list(cited_ids),
            "n_cited": len(cited_ids),
            "expected_in_returned": list(expected_ids & returned_ids),
            "expected_in_cited": list(expected_ids & cited_ids),
            "retr_recall": retr_recall,
            "cited_recall": cited_recall,
            "evaluate_verdict": eval_verdict,
            "evaluate_reasoning": eval_reasoning,
            "synthesize_mode": res.synthesize_output.mode,
            "answer_text": res.synthesize_output.answer_text,
            "duration_s": dt,
            "judge_score": judge["score"],
            "judge_reasoning": judge.get("reasoning", ""),
            "diagnostic_verdict": verdict,
        })

    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, ensure_ascii=False, default=str)
    logger.info("Wrote %s", OUTPUT_PATH)

    # Summary
    logger.info("=" * 60)
    verdict_counts: Dict[str, int] = {}
    judge_by_verdict: Dict[str, List[float]] = {}
    for r in results:
        v = r.get("diagnostic_verdict", "error")
        verdict_counts[v] = verdict_counts.get(v, 0) + 1
        judge_by_verdict.setdefault(v, []).append(r.get("judge_score", 0.0))
    for v, n in sorted(verdict_counts.items(), key=lambda x: -x[1]):
        scores = judge_by_verdict.get(v, [])
        avg = sum(scores) / len(scores) if scores else 0
        logger.info("  %s : %d questions, judge_avg=%.2f", v, n, avg)

    judges = [r.get("judge_score", 0.0) for r in results if "judge_score" in r]
    logger.info("Mean C1: %.3f", sum(judges) / len(judges) if judges else 0)
    avg_retr_recall = sum(r.get("retr_recall", 0) for r in results) / len(results)
    avg_cited_recall = sum(r.get("cited_recall", 0) for r in results) / len(results)
    logger.info("Mean retrieval recall (expected ∩ returned / expected): %.2f", avg_retr_recall)
    logger.info("Mean cited recall (expected ∩ cited / expected): %.2f", avg_cited_recall)


if __name__ == "__main__":
    main()
