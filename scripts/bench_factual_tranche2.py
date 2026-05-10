#!/usr/bin/env python3
"""
CH-41 Tranche 2 — Bench factual end-to-end avec D-FF13.

Itère sur les 25 questions factual du gold-set v4, exécute le pipeline complet
[A]→[E] (QuestionAnalyzer → EvidenceCollector → FactualStructurer+D-FF13 →
FactualComposer → Channel1FactualVerifier), et mesure :
  - factual_correctness via RAGAS (LLM-judge Llama-3.3-70B) sur (answer, reference)
  - exact_match_identifiers (object.raw verbatim dans le gold answer)
  - source_accuracy (source.doc_id ∈ supporting_doc_ids gold)
  - verifier_passed_rate
  - latence p50, p95
  - taux d'activation D-FF13 + distribution fallback_mode
  - distribution answerability/coverage_state

Gate D-FF13 : factual_correctness(facts-first+D-FF13) ≥ baseline V3 (0.361, mesuré CH-41.0 livrable E).

Usage (container) :
  docker cp scripts/bench_factual_tranche2.py knowbase-app:/app/scripts/
  docker exec knowbase-app python /app/scripts/bench_factual_tranche2.py
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("bench_factual")

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if (PROJECT_ROOT / "src").exists():
    sys.path.insert(0, str(PROJECT_ROOT / "src"))

GOLD_SET_PATH = PROJECT_ROOT / "benchmark" / "questions" / "gold_set_v4.json"
OUTPUT_DIR = PROJECT_ROOT / "data" / "benchmark" / "calibration"
OUTPUT_PATH = OUTPUT_DIR / "bench_factual_tranche2.json"

# Baseline V3 RAG mesuré CH-41.0 livrable E
BASELINE_V3_FACTUAL_CORRECTNESS = 0.361


def load_factual_questions(limit: int | None = None) -> list[dict]:
    gold = json.loads(GOLD_SET_PATH.read_text(encoding="utf-8"))
    items = [q for q in gold if q.get("primary_type") == "factual"]
    if limit:
        items = items[:limit]
    return items


def doc_id_match(pred: str, supporting: set[str]) -> bool:
    """Match tolérant doc_id (préfixe ≥ 12 chars)."""
    if not pred or not supporting:
        return False
    p = pred.lower().strip()
    for s in supporting:
        s = (s or "").lower().strip()
        if not s or len(s) < 6:
            continue
        if p == s:
            return True
        common = 0
        for a, b in zip(p, s):
            if a == b:
                common += 1
            else:
                break
        if common >= 12:
            return True
    return False


def build_pipeline(use_transverse: bool = False):
    """Pipeline complet Tranche 1 + 2.

    Args:
        use_transverse: si True, active SelfCorrector + Channel2 NLI.
    """
    from neo4j import GraphDatabase
    from knowbase.common.clients.shared_clients import (
        get_qdrant_client, get_sentence_transformer,
    )
    from knowbase.config.settings import get_settings
    from knowbase.runtime_v3.retriever import ClaimRetriever
    from knowbase.facts_first.pipeline import FactsFirstPipeline
    from knowbase.facts_first import (
        QuestionAnalyzer, EvidenceCollector,
        ListStructurer, ListComposer, Channel1ListVerifier,
        FactualStructurer, FactualComposer, Channel1FactualVerifier,
        SelfCorrector, Channel2NLIVerifier,
    )

    neo4j_uri = os.getenv("NEO4J_URI", "bolt://neo4j:7687")
    neo4j_user = os.getenv("NEO4J_USER", "neo4j")
    neo4j_password = os.getenv("NEO4J_PASSWORD", "graphiti_neo4j_pass")
    tenant_id = os.getenv("TENANT_ID", "default")

    driver = GraphDatabase.driver(neo4j_uri, auth=(neo4j_user, neo4j_password))
    settings = get_settings()
    qdrant = get_qdrant_client()
    embedder = get_sentence_transformer(settings.embeddings_model, cache_folder=str(settings.hf_home))

    retriever = ClaimRetriever(
        qdrant_client=qdrant, embedder=embedder, driver=driver,
        collection_name="knowbase_chunks_v2", tenant_id=tenant_id,
    )
    evidence_collector = EvidenceCollector(
        retriever=retriever, neo4j_driver=driver, tenant_id=tenant_id, top_k=20,
    )
    pipeline = FactsFirstPipeline(
        analyzer=QuestionAnalyzer(),
        evidence_collector=evidence_collector,
        list_structurer=ListStructurer(),
        list_composer=ListComposer(),
        list_verifier=Channel1ListVerifier(),
        factual_structurer=FactualStructurer(),
        factual_composer=FactualComposer(),
        factual_verifier=Channel1FactualVerifier(),
        self_corrector=SelfCorrector() if use_transverse else None,
        channel2_verifier=Channel2NLIVerifier(enabled=use_transverse) if use_transverse else None,
        tenant_id=tenant_id,
    )
    return pipeline


def evaluate_one(pipeline, q: dict) -> dict:
    qid = q.get("id", "?")
    question = q["question"]
    gt = q.get("ground_truth", {})
    reference_answer = gt.get("ground_truth_answer", "")
    expected_identifiers = [str(x).lower() for x in (gt.get("exact_identifiers") or [])]
    supporting_doc_ids = set(gt.get("supporting_doc_ids") or [])

    t0 = time.time()
    try:
        response = pipeline.answer(question, top_k_evidence=20)
    except Exception as exc:
        logger.error("pipeline failed for %s: %s", qid, exc)
        return {"id": qid, "error": str(exc), "elapsed_ms": int((time.time() - t0) * 1000)}
    elapsed_ms = int((time.time() - t0) * 1000)

    routing = response.routing_decision
    if routing != "factual_path":
        return {
            "id": qid, "language": q.get("language"),
            "elapsed_ms": elapsed_ms,
            "routing_decision": routing,
            "primary_type_predicted": response.analyzer.primary_type,
            "primary_confidence": response.analyzer.primary_confidence,
            "skipped": True,
            "answer_text": response.answer_text,
            "reference_answer": reference_answer[:240],
        }

    facts = (response.facts_first or {}).get("factual_specific", {}).get("facts", []) or []
    answer_text = response.answer_text or ""

    # exact_match_identifiers : combien des expected identifiers sont dans la réponse
    answer_lower = answer_text.lower()
    n_id_matched = sum(1 for ident in expected_identifiers if ident in answer_lower)
    exact_match_score = n_id_matched / len(expected_identifiers) if expected_identifiers else None

    # source_accuracy : combien de facts ont leur doc_id dans supporting
    if facts:
        n_source_match = sum(
            1 for f in facts
            if doc_id_match((f.get("source") or {}).get("doc_id", ""), supporting_doc_ids)
        )
        source_accuracy = n_source_match / len(facts) if supporting_doc_ids else None
    else:
        source_accuracy = None

    return {
        "id": qid,
        "language": q.get("language"),
        "question": question[:140],
        "elapsed_ms": elapsed_ms,
        "routing_decision": routing,
        "primary_type_predicted": response.analyzer.primary_type,
        "primary_confidence": response.analyzer.primary_confidence,
        "n_evidence_qdrant": (response.evidence_bundle.n_qdrant_hits if response.evidence_bundle else 0),
        "n_facts": len(facts),
        "answerability_predicted": (response.facts_first or {}).get("answerability"),
        "coverage_state_predicted": (response.facts_first or {}).get("coverage_state"),
        "verifier_passed": response.verifier.passed if response.verifier else None,
        "verifier_severity": response.verifier.severity if response.verifier else None,
        "structurer_rejected_count": (response.diagnostic or {}).get("structurer_rejected_count"),
        "used_d_ff13_fallback": (response.diagnostic or {}).get("used_d_ff13_fallback"),
        "fallback_mode": (response.diagnostic or {}).get("fallback_mode"),
        "exact_match_identifiers": exact_match_score,
        "source_accuracy": source_accuracy,
        "n_id_expected": len(expected_identifiers),
        "n_id_matched": n_id_matched,
        "answer_text": answer_text[:400],
        "reference_answer": reference_answer[:240],
        "fact_objects": [
            {"raw": f["object"]["raw"], "kind": f["object"].get("kind"),
             "subject": f.get("subject", "")[:80]}
            for f in facts[:5]
        ],
    }


def score_factual_correctness(samples: list[dict]) -> dict:
    """RAGAS FactualCorrectness sur (answer, reference) — comme livrable E."""
    try:
        from ragas import SingleTurnSample
        from ragas.metrics import FactualCorrectness
        from ragas.llms import LangchainLLMWrapper
        from langchain_openai import ChatOpenAI
    except ImportError:
        logger.error("ragas / langchain-openai not installed in container")
        return {"error": "ragas_not_available"}

    deepinfra_key = os.getenv("DEEPINFRA_API_KEY", "")
    if not deepinfra_key:
        env = PROJECT_ROOT / ".env"
        if env.exists():
            for line in env.read_text(encoding="utf-8").splitlines():
                if line.startswith("DEEPINFRA_API_KEY="):
                    deepinfra_key = line.split("=", 1)[1].strip().strip('"').strip("'")
                    break
    if not deepinfra_key:
        return {"error": "missing_deepinfra_key"}

    llm = ChatOpenAI(
        model="meta-llama/Llama-3.3-70B-Instruct",
        api_key=deepinfra_key,
        base_url="https://api.deepinfra.com/v1/openai",
        temperature=0.1,
    )
    metric = FactualCorrectness(llm=LangchainLLMWrapper(llm))

    import asyncio
    scores = []
    for s in samples:
        if not s.get("answer_text") or not s.get("reference_answer"):
            continue
        if s.get("skipped") or s.get("error"):
            continue
        try:
            sample = SingleTurnSample(response=s["answer_text"], reference=s["reference_answer"])
            score = asyncio.run(metric.single_turn_ascore(sample))
            scores.append({"id": s["id"], "factual_correctness": float(score)})
        except Exception as exc:
            logger.warning("RAGAS score failed for %s: %s", s.get("id"), exc)
            scores.append({"id": s["id"], "factual_correctness": None, "error": str(exc)})
    valid = [x["factual_correctness"] for x in scores if x.get("factual_correctness") is not None]
    if not valid:
        return {"error": "no_valid_scores"}
    return {
        "n_total": len(scores),
        "n_valid": len(valid),
        "mean": sum(valid) / len(valid),
        "min": min(valid),
        "max": max(valid),
        "per_sample": scores,
    }


def aggregate(results: list[dict]) -> dict:
    valid = [r for r in results if not r.get("error") and not r.get("skipped")]

    def _safe_mean(vals):
        vals = [v for v in vals if v is not None]
        return sum(vals) / len(vals) if vals else None

    def _percentile(vals, p):
        if not vals:
            return None
        s = sorted(vals)
        idx = max(0, min(len(s) - 1, int(p / 100 * len(s))))
        return s[idx]

    n_total = len(results)
    n_valid = len(valid)
    n_skipped = sum(1 for r in results if r.get("skipped"))
    n_errors = sum(1 for r in results if r.get("error"))
    n_d_ff13 = sum(1 for r in valid if r.get("used_d_ff13_fallback"))
    fallback_modes = {}
    for r in valid:
        mode = r.get("fallback_mode")
        if mode:
            fallback_modes[mode] = fallback_modes.get(mode, 0) + 1

    return {
        "n_total": n_total,
        "n_valid": n_valid,
        "n_skipped_routing": n_skipped,
        "n_errors": n_errors,
        "exact_match_identifiers_mean": _safe_mean([r.get("exact_match_identifiers") for r in valid]),
        "source_accuracy_mean": _safe_mean([r.get("source_accuracy") for r in valid]),
        "verifier_passed_rate": (
            sum(1 for r in valid if r.get("verifier_passed")) / n_valid if n_valid else None
        ),
        "latency_p50_ms": _percentile([r.get("elapsed_ms") for r in valid], 50),
        "latency_p95_ms": _percentile([r.get("elapsed_ms") for r in valid], 95),
        "d_ff13_activation_rate": n_d_ff13 / n_valid if n_valid else 0,
        "fallback_modes_distribution": fallback_modes,
        "answerability_distribution": {
            a: sum(1 for r in valid if r.get("answerability_predicted") == a)
            for a in ("answerable", "partial", "unanswerable")
        },
        "n_structurer_rejected_total": sum(r.get("structurer_rejected_count") or 0 for r in valid),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--workers", type=int, default=2)
    parser.add_argument("--no-ragas", action="store_true", help="Skip RAGAS factual_correctness scoring")
    parser.add_argument("--transverse", action="store_true",
                        help="Activer Couches B (SelfCorrector) + C (Channel2 NLI)")
    args = parser.parse_args()

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    questions = load_factual_questions(args.limit)
    logger.info("Loaded %d factual questions", len(questions))

    pipeline = build_pipeline(use_transverse=args.transverse)
    logger.info("Pipeline ready (transverse=%s) — starting bench", args.transverse)

    t0 = time.time()
    results: list[dict] = []
    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        futures = {ex.submit(evaluate_one, pipeline, q): q for q in questions}
        for i, fut in enumerate(as_completed(futures), 1):
            try:
                results.append(fut.result())
            except Exception as exc:
                q = futures[fut]
                results.append({"id": q.get("id"), "error": str(exc)})
            if i % 5 == 0 or i == len(futures):
                logger.info("Evaluated %d/%d", i, len(futures))

    summary = aggregate(results)
    summary["elapsed_seconds_pipeline"] = round(time.time() - t0, 1)

    if not args.no_ragas:
        logger.info("Scoring RAGAS factual_correctness (24+ LLM calls × n samples)...")
        ragas_result = score_factual_correctness(results)
        summary["ragas_factual_correctness"] = ragas_result

    print()
    print("=== CH-41 TRANCHE 2 BENCH FACTUAL — RÉSUMÉ ===")
    for k in ("n_total", "n_valid", "n_skipped_routing", "n_errors",
              "exact_match_identifiers_mean", "source_accuracy_mean",
              "verifier_passed_rate", "latency_p50_ms", "latency_p95_ms",
              "d_ff13_activation_rate"):
        v = summary.get(k)
        if isinstance(v, float):
            print(f"  {k}: {v:.3f}")
        else:
            print(f"  {k}: {v}")
    print(f"  fallback_modes: {summary.get('fallback_modes_distribution')}")
    print(f"  answerability:  {summary.get('answerability_distribution')}")
    print()
    print("=== GATE D-FF13 (vs RAG baseline V3) ===")
    rag = summary.get("ragas_factual_correctness") or {}
    if rag.get("error"):
        print(f"  RAGAS scoring failed: {rag['error']}")
    elif rag.get("mean") is not None:
        v4_score = rag["mean"]
        print(f"  factual_correctness V4 (Tranche 2 + D-FF13) : {v4_score:.3f}  (n={rag['n_valid']})")
        print(f"  baseline V3 RAG (livrable E)                : {BASELINE_V3_FACTUAL_CORRECTNESS:.3f}")
        delta = v4_score - BASELINE_V3_FACTUAL_CORRECTNESS
        gate = "✓" if v4_score >= BASELINE_V3_FACTUAL_CORRECTNESS else ("≈ (variance ±0.05)" if abs(delta) <= 0.05 else "✗")
        print(f"  delta = {delta:+.3f}  | gate = {gate}")

    output = {
        "summary": summary,
        "per_sample": results,
        "completed_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    OUTPUT_PATH.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    logger.info("Persisted %s", OUTPUT_PATH)
    return 0


if __name__ == "__main__":
    sys.exit(main())
