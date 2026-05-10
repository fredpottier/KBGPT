#!/usr/bin/env python3
"""
CH-41 — Bench global V4 multi-types (list, factual, temporal, comparison, causal).

Itère sur le gold-set v4 complet (132 questions tous types confondus), exécute
le pipeline FactsFirstPipeline étendu (Tranches 1-5 + couches transverses B+C),
et mesure :

Par type :
  - n_total, n_valid, n_skipped_routing
  - verifier_passed_rate
  - latency p50, p95
  - exact_match_identifiers (sur expected_identifiers du gold)
  - source_accuracy
  - distribution answerability/coverage_state
Métriques transverses :
  - SelfCorrector retry rate + outcome distribution
  - Channel 2 NLI verdict distribution

Usage (container) :
  docker cp scripts/bench_global_v4.py knowbase-app:/app/scripts/
  docker exec knowbase-app python /app/scripts/bench_global_v4.py [--limit N] [--no-transverse]
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("bench_global")

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if (PROJECT_ROOT / "src").exists():
    sys.path.insert(0, str(PROJECT_ROOT / "src"))

GOLD_SET_PATH = PROJECT_ROOT / "benchmark" / "questions" / "gold_set_v4.json"
OUTPUT_PATH = PROJECT_ROOT / "data" / "benchmark" / "calibration" / "bench_global_v4.json"


def normalize(s: str) -> str:
    return " ".join((s or "").lower().split()).strip()


def doc_id_match(pred: str, supporting: set[str]) -> bool:
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


def load_gold(limit: int | None = None) -> list[dict]:
    gold = json.loads(GOLD_SET_PATH.read_text(encoding="utf-8"))
    if limit:
        gold = gold[:limit]
    return gold


def build_pipeline(use_transverse: bool):
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
        TemporalStructurer, TemporalComposer, Channel1TemporalVerifier,
        ComparisonStructurer, ComparisonComposer, Channel1ComparisonVerifier,
        CausalStructurer, CausalComposer, Channel1CausalVerifier,
        SelfCorrector, Channel2NLIVerifier, EvidenceRerouter,
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
    return FactsFirstPipeline(
        analyzer=QuestionAnalyzer(),
        evidence_collector=evidence_collector,
        list_structurer=ListStructurer(),
        list_composer=ListComposer(),
        list_verifier=Channel1ListVerifier(),
        factual_structurer=FactualStructurer(),
        factual_composer=FactualComposer(),
        factual_verifier=Channel1FactualVerifier(),
        temporal_structurer=TemporalStructurer(),
        temporal_composer=TemporalComposer(),
        temporal_verifier=Channel1TemporalVerifier(),
        comparison_structurer=ComparisonStructurer(),
        comparison_composer=ComparisonComposer(),
        comparison_verifier=Channel1ComparisonVerifier(),
        causal_structurer=CausalStructurer(),
        causal_composer=CausalComposer(),
        causal_verifier=Channel1CausalVerifier(),
        self_corrector=SelfCorrector() if use_transverse else None,
        channel2_verifier=Channel2NLIVerifier(enabled=use_transverse) if use_transverse else None,
        evidence_rerouter=EvidenceRerouter(neo4j_driver=driver, tenant_id=tenant_id) if use_transverse else None,
        tenant_id=tenant_id,
    )


def evaluate_one(pipeline, q: dict) -> dict:
    qid = q.get("id", "?")
    question = q["question"]
    gt = q.get("ground_truth", {})
    expected_ids = [str(x).lower() for x in (gt.get("exact_identifiers") or [])]
    supporting = set(gt.get("supporting_doc_ids") or [])
    expected_type = q.get("primary_type")

    t0 = time.time()
    try:
        response = pipeline.answer(question, top_k_evidence=20)
    except Exception as exc:
        return {"id": qid, "error": str(exc), "elapsed_ms": int((time.time() - t0) * 1000)}
    elapsed_ms = int((time.time() - t0) * 1000)

    routing = response.routing_decision
    answer_lower = (response.answer_text or "").lower()
    n_id_matched = sum(1 for ident in expected_ids if ident in answer_lower)
    exact_match = n_id_matched / len(expected_ids) if expected_ids else None

    facts_first = response.facts_first or {}
    # Source accuracy : extraction des doc_ids de tous les sources possibles
    pred_doc_ids = []
    for ts_key in ("list_specific", "factual_specific", "temporal_specific", "comparison_specific", "causal_specific"):
        ts = facts_first.get(ts_key) or {}
        for collection_key in ("items", "facts", "timeline", "compared_facts", "causal_chains"):
            for entry in ts.get(collection_key, []) or []:
                if isinstance(entry, dict):
                    src = entry.get("source") or entry.get("fact", {}).get("source")
                    if isinstance(src, dict) and src.get("doc_id"):
                        pred_doc_ids.append(src["doc_id"])
                    # causal_chains have nested steps
                    for sub in (entry.get("steps") or []):
                        sub_src = (sub or {}).get("source")
                        if isinstance(sub_src, dict) and sub_src.get("doc_id"):
                            pred_doc_ids.append(sub_src["doc_id"])
    if pred_doc_ids and supporting:
        n_match = sum(1 for d in pred_doc_ids if doc_id_match(d, supporting))
        source_acc = n_match / len(pred_doc_ids)
    else:
        source_acc = None

    sc = response.self_correction or {}
    ch2 = response.channel2
    rerouter = (response.diagnostic or {}).get("rerouter") or {}

    return {
        "id": qid,
        "expected_type": expected_type,
        "rerouter_was_promoted": rerouter.get("was_promoted"),
        "rerouter_original_type": rerouter.get("original_type"),
        "rerouter_promoted_type": rerouter.get("promoted_type"),
        "rerouter_rationale": rerouter.get("rationale"),
        "language": q.get("language"),
        "question": question[:140],
        "elapsed_ms": elapsed_ms,
        "routing_decision": routing,
        "primary_type_predicted": response.analyzer.primary_type,
        "primary_confidence": response.analyzer.primary_confidence,
        "answerability_predicted": facts_first.get("answerability"),
        "coverage_state_predicted": facts_first.get("coverage_state"),
        "verifier_passed": response.verifier.passed if response.verifier else None,
        "verifier_severity": response.verifier.severity if response.verifier else None,
        "structurer_rejected_count": (response.diagnostic or {}).get("structurer_rejected_count"),
        "exact_match_identifiers": exact_match,
        "source_accuracy": source_acc,
        "n_id_expected": len(expected_ids),
        "n_id_matched": n_id_matched,
        # Couches transverses
        "self_correction_should_retry": sc.get("should_retry"),
        "self_correction_retry_executed": sc.get("retry_executed"),
        "self_correction_outcome": sc.get("retry_outcome"),
        "channel2_verdict": ch2.overall_verdict if ch2 else None,
        "channel2_score": ch2.overall_score if ch2 else None,
        "answer_text": (response.answer_text or "")[:300],
    }


def aggregate_by_type(results: list[dict]) -> dict:
    by_type: dict[str, list[dict]] = defaultdict(list)
    for r in results:
        if r.get("error"):
            continue
        by_type[r.get("expected_type") or "?"].append(r)

    def _safe_mean(vals):
        vals = [v for v in vals if v is not None]
        return sum(vals) / len(vals) if vals else None

    def _percentile(vals, p):
        if not vals:
            return None
        s = sorted(vals); idx = max(0, min(len(s) - 1, int(p / 100 * len(s))))
        return s[idx]

    out = {}
    for t, rs in by_type.items():
        n = len(rs)
        n_correct_routing = sum(1 for r in rs if r.get("primary_type_predicted") == t)
        n_handled = sum(1 for r in rs if r.get("routing_decision") in
                         ("list_path", "factual_path", "temporal_path", "comparison_path", "causal_path"))
        out[t] = {
            "n_total": n,
            "routing_correct_rate": n_correct_routing / n if n else None,
            "n_handled_pipeline": n_handled,
            "exact_match_identifiers_mean": _safe_mean([r.get("exact_match_identifiers") for r in rs]),
            "source_accuracy_mean": _safe_mean([r.get("source_accuracy") for r in rs]),
            "verifier_passed_rate": _safe_mean([1 if r.get("verifier_passed") else 0 for r in rs if r.get("verifier_passed") is not None]),
            "latency_p50_ms": _percentile([r.get("elapsed_ms") for r in rs], 50),
            "latency_p95_ms": _percentile([r.get("elapsed_ms") for r in rs], 95),
            "answerability_distribution": dict(Counter(r.get("answerability_predicted") for r in rs)),
        }
    return out


def aggregate_transverse(results: list[dict]) -> dict:
    valid = [r for r in results if not r.get("error")]
    n = len(valid)
    n_retry_recommended = sum(1 for r in valid if r.get("self_correction_should_retry"))
    n_retry_executed = sum(1 for r in valid if r.get("self_correction_retry_executed"))
    outcomes = Counter(r.get("self_correction_outcome") for r in valid if r.get("self_correction_outcome"))
    ch2_verdicts = Counter(r.get("channel2_verdict") for r in valid if r.get("channel2_verdict"))
    return {
        "n_valid": n,
        "self_correction_retry_recommended_rate": n_retry_recommended / n if n else None,
        "self_correction_retry_executed_rate": n_retry_executed / n if n else None,
        "self_correction_outcomes": dict(outcomes),
        "channel2_verdict_distribution": dict(ch2_verdicts),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--workers", type=int, default=4,
                        help="Default 4 (>4 risque cascade timeout DeepInfra sur factual)")
    parser.add_argument("--no-transverse", action="store_true",
                        help="Désactive Couches B+C pour comparaison baseline")
    parser.add_argument("--filter-types", type=str, default=None,
                        help="Comma-separated primary_types to keep (e.g. 'temporal,comparison,causal')")
    args = parser.parse_args()

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    questions = load_gold(args.limit)
    if args.filter_types:
        wanted = {t.strip() for t in args.filter_types.split(",") if t.strip()}
        questions = [q for q in questions if q.get("primary_type") in wanted]
        logger.info("Filtered to types %s : %d questions", wanted, len(questions))
    use_transverse = not args.no_transverse
    logger.info("Loaded %d questions, transverse=%s", len(questions), use_transverse)

    pipeline = build_pipeline(use_transverse=use_transverse)
    logger.info("Pipeline ready (transverse=%s) — starting bench", use_transverse)

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
            if i % 10 == 0 or i == len(futures):
                logger.info("Evaluated %d/%d", i, len(futures))

    elapsed = time.time() - t0
    by_type = aggregate_by_type(results)
    transverse = aggregate_transverse(results)

    output = {
        "config": {"transverse_enabled": use_transverse, "n_questions": len(questions)},
        "by_type": by_type,
        "transverse": transverse,
        "elapsed_seconds": round(elapsed, 1),
        "per_sample": results,
        "completed_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    OUTPUT_PATH.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    logger.info("Persisted %s", OUTPUT_PATH)

    print()
    print(f"=== BENCH GLOBAL V4 (transverse={use_transverse}) — RÉSUMÉ PAR TYPE ===")
    print(f"{'type':<14} {'n':>4} {'route_ok':>9} {'handled':>8} {'verif_pass':>11} {'exact_id':>9} {'src_acc':>8} {'p50':>7} {'p95':>7}")
    for t in ("factual", "list", "temporal", "comparison", "causal", "false_premise", "unanswerable"):
        if t not in by_type:
            continue
        m = by_type[t]
        def _f(v):
            return f"{v:.3f}" if isinstance(v, float) else (str(v) if v is not None else "n/a")
        print(f"{t:<14} {m['n_total']:>4} {_f(m.get('routing_correct_rate')):>9} {m['n_handled_pipeline']:>8} "
              f"{_f(m.get('verifier_passed_rate')):>11} {_f(m.get('exact_match_identifiers_mean')):>9} "
              f"{_f(m.get('source_accuracy_mean')):>8} {_f(m.get('latency_p50_ms')):>7} {_f(m.get('latency_p95_ms')):>7}")

    print()
    print("=== TRANSVERSE LAYERS DIAGNOSTICS ===")
    for k, v in transverse.items():
        print(f"  {k}: {v}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
