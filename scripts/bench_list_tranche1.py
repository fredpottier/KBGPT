#!/usr/bin/env python3
"""
CH-41.4 — Bench dédié list end-to-end sur la Tranche 1 facts-first.

Itère sur les 55 questions list de `benchmark/questions/gold_set_v4.json`,
exécute le pipeline complet [A]→[E] (QuestionAnalyzer → EvidenceCollector →
ListStructurer → ListComposer → Channel1Verifier), et mesure :
  - item_recall, item_precision, item_f1 (matching normalized_label)
  - source_accuracy (source.doc_id ∈ supporting_doc_ids du gold)
  - verifier_passed_rate
  - latence p50, p95
  - distribution coverage_state predicted vs expected
  - taux d'items rejetés par le Structurer (hallucinations)

Usage (dans le container app où tous les clients sont disponibles) :
  docker cp scripts/bench_list_tranche1.py knowbase-app:/app/scripts/
  docker exec knowbase-app python /app/scripts/bench_list_tranche1.py
  docker exec knowbase-app python /app/scripts/bench_list_tranche1.py --limit 5  # smoke
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
logger = logging.getLogger("bench_list")

PROJECT_ROOT = Path(__file__).resolve().parent.parent
# Ensure src/ on path (depuis hôte ou container)
if (PROJECT_ROOT / "src").exists():
    sys.path.insert(0, str(PROJECT_ROOT / "src"))

GOLD_SET_PATH = PROJECT_ROOT / "benchmark" / "questions" / "gold_set_v4.json"
OUTPUT_DIR = PROJECT_ROOT / "data" / "benchmark" / "calibration"
OUTPUT_PATH = OUTPUT_DIR / "bench_list_tranche1.json"


def normalize_label(s: str) -> str:
    """Normalisation pour matching : lowercase, strip, espaces compactés."""
    if not s:
        return ""
    return " ".join(s.lower().split()).strip()


def doc_id_match(pred_doc_id: str, supporting: set[str]) -> bool:
    """Match tolérant doc_id : exact OR préfixe normalisé partagé.

    Le gold-set utilise des doc_ids courts (`dualuse_reg_2021_821_original_65eef5dc`,
    `easa_cs25_amdt28`) tandis que le pipeline retourne des doc_ids canoniques
    Neo4j/Qdrant qui peuvent inclure ou non le suffix hash. On match si l'un est
    préfixe de l'autre (à 6+ chars).
    """
    if not pred_doc_id or not supporting:
        return False
    pred_norm = pred_doc_id.lower().strip()
    for sup in supporting:
        sup_norm = (sup or "").lower().strip()
        if not sup_norm or len(sup_norm) < 6:
            continue
        if pred_norm == sup_norm:
            return True
        # Prefix match : si l'un commence par l'autre (préfixe ≥ 12 chars pour éviter les faux positifs)
        common_prefix_len = 0
        for a, b in zip(pred_norm, sup_norm):
            if a == b:
                common_prefix_len += 1
            else:
                break
        if common_prefix_len >= 12:
            return True
    return False


def load_list_questions(limit: int | None = None, only_handcrafted: bool = True) -> list[dict]:
    """Charge les questions list du gold-set v4.

    Args:
        only_handcrafted: si True (défaut), ne garde que les 35 GOLD_v4_LIST_NEW_*
            qui ont le schéma propre `list_items_expected: [{label, normalized_label, source, ...}]`.
            Les anciennes T6 ont des items au format descriptif méta non-mesurable.
    """
    gold = json.loads(GOLD_SET_PATH.read_text(encoding="utf-8"))
    items = [q for q in gold if q.get("primary_type") == "list"]
    if only_handcrafted:
        items = [
            q for q in items
            if (q.get("annotation_meta") or {}).get("phase") == "ch41.0_handcrafted_v1"
        ]
    if limit:
        items = items[:limit]
    return items


def build_pipeline(use_transverse: bool = False):
    """Instancie le pipeline complet via les clients runtime_v3 existants.

    Args:
        use_transverse: si True, active SelfCorrector (Couche B) + Channel2 NLI (Couche C).
    """
    from neo4j import GraphDatabase
    from knowbase.common.clients.shared_clients import (
        get_qdrant_client,
        get_sentence_transformer,
    )
    from knowbase.config.settings import get_settings
    from knowbase.runtime_v3.retriever import ClaimRetriever
    from knowbase.facts_first.pipeline import FactsFirstPipeline
    from knowbase.facts_first import (
        QuestionAnalyzer,
        EvidenceCollector,
        ListStructurer,
        ListComposer,
        Channel1ListVerifier,
        SelfCorrector,
        Channel2NLIVerifier,
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
        self_corrector=SelfCorrector() if use_transverse else None,
        channel2_verifier=Channel2NLIVerifier(enabled=use_transverse) if use_transverse else None,
        tenant_id=tenant_id,
    )
    return pipeline


_embedder_cache = {"emb": None}


def get_bench_embedder():
    """Lazy-load le sentence-transformer pour matching sémantique cross-lingual."""
    if _embedder_cache["emb"] is not None:
        return _embedder_cache["emb"]
    try:
        from knowbase.common.clients.shared_clients import get_sentence_transformer
        from knowbase.config.settings import get_settings
        settings = get_settings()
        _embedder_cache["emb"] = get_sentence_transformer(
            settings.embeddings_model, cache_folder=str(settings.hf_home)
        )
    except Exception as exc:
        logger.warning("Could not load embedder for semantic matching: %s", exc)
        _embedder_cache["emb"] = None
    return _embedder_cache["emb"]


def semantic_match(pred_labels: set[str], exp_labels: set[str], threshold: float = 0.85):
    """Cosine sim multilingue via e5. Returns (matched_pred, matched_exp).

    Le matcher strict (token overlap, substring) sous-estime le recall sur :
      - paraphrases LLM ("global licence" vs "global export authorisation")
      - cross-lingual (FR question avec labels FR vs prédictions EN)
    e5 est multilingue → cosine sim > 0.85 sur paraphrases équivalentes.
    """
    matched_pred: set[str] = set()
    matched_exp: set[str] = set()
    if not pred_labels or not exp_labels:
        return matched_pred, matched_exp
    emb = get_bench_embedder()
    if emb is None:
        return matched_pred, matched_exp
    try:
        # e5 nécessite "query: " prefix pour query / "passage: " pour passage
        pred_list = list(pred_labels)
        exp_list = list(exp_labels)
        pred_vecs = emb.encode([f"passage: {p}" for p in pred_list], normalize_embeddings=True)
        exp_vecs = emb.encode([f"passage: {e}" for e in exp_list], normalize_embeddings=True)
        # cosine = dot product (vecs normalisés)
        for i, ev in enumerate(exp_vecs):
            best_sim = 0.0
            best_pred = None
            for j, pv in enumerate(pred_vecs):
                sim = float(sum(a * b for a, b in zip(ev, pv)))
                if sim > best_sim:
                    best_sim = sim
                    best_pred = pred_list[j]
            if best_sim >= threshold and best_pred is not None:
                matched_exp.add(exp_list[i])
                matched_pred.add(best_pred)
    except Exception as exc:
        logger.warning("Semantic matching failed: %s", exc)
    return matched_pred, matched_exp


def evaluate_one(pipeline, question_obj: dict) -> dict:
    """Exécute le pipeline sur une question et calcule les métriques."""
    qid = question_obj.get("id", "?")
    question = question_obj["question"]
    gt = question_obj.get("ground_truth", {})
    expected_items = gt.get("list_items_expected") or []
    # Le gold-set a 2 schémas : anciennes questions T6 = liste de strings,
    # nouvelles GOLD_v4_LIST_NEW_* = liste de dicts {label, normalized_label, normalized_label_en, ...}
    # Priorité : normalized_label_en (post-cleanup 2026-05-06) > normalized_label > label.
    expected_norm_labels: set[str] = set()
    for it in expected_items:
        if isinstance(it, dict):
            label = it.get("normalized_label_en") or it.get("normalized_label") or it.get("label", "")
        else:
            label = str(it)
        expected_norm_labels.add(normalize_label(label))
    expected_norm_labels.discard("")
    supporting_doc_ids = set(gt.get("supporting_doc_ids") or [])
    expected_min_items = (gt.get("_phase1_metadata") or {}).get("expected_min_items", len(expected_items))

    t0 = time.time()
    try:
        response = pipeline.answer(question, top_k_evidence=20)
    except Exception as exc:
        logger.error("pipeline failed for %s: %s", qid, exc)
        return {
            "id": qid, "language": question_obj.get("language"),
            "error": str(exc), "elapsed_ms": int((time.time() - t0) * 1000),
        }
    elapsed_ms = int((time.time() - t0) * 1000)

    # Cas non-list-path (devrait pas arriver sur des q list, mais possible si analyzer se trompe)
    if response.routing_decision != "list_path":
        return {
            "id": qid, "language": question_obj.get("language"),
            "elapsed_ms": elapsed_ms,
            "routing_decision": response.routing_decision,
            "primary_type_predicted": response.analyzer.primary_type,
            "primary_confidence": response.analyzer.primary_confidence,
            "skipped": True,
            "answer_text": response.answer_text,
        }

    # Items prédits
    items_predicted = (response.facts_first or {}).get("list_specific", {}).get("items", []) or []
    pred_norm_labels = {normalize_label(it.get("normalized_label") or it.get("label", "")) for it in items_predicted}
    pred_norm_labels.discard("")

    # Item-level recall/precision/f1 avec matching fuzzy (substring tolérant)
    def _matches(pred: str, exp: str) -> bool:
        if not pred or not exp:
            return False
        if pred == exp:
            return True
        # Tolerance : un est substring de l'autre (evite "individual export authorisation"
        # vs "individual auth" miss à cause de normalisation différente)
        if pred in exp or exp in pred:
            return True
        # Token overlap >= 50% (mots > 3 chars)
        p_toks = {t for t in pred.split() if len(t) > 3}
        e_toks = {t for t in exp.split() if len(t) > 3}
        if p_toks and e_toks:
            overlap = len(p_toks & e_toks) / max(1, min(len(p_toks), len(e_toks)))
            if overlap >= 0.6:
                return True
        return False

    if expected_norm_labels:
        matched_expected: set[str] = set()
        matched_predicted: set[str] = set()
        for exp in expected_norm_labels:
            for pred in pred_norm_labels:
                if _matches(pred, exp):
                    matched_expected.add(exp)
                    matched_predicted.add(pred)
        recall = len(matched_expected) / len(expected_norm_labels)
        precision = len(matched_predicted) / max(1, len(pred_norm_labels))
    else:
        recall = None
        precision = None
    f1 = (
        2 * precision * recall / (precision + recall)
        if (recall is not None and precision is not None and (precision + recall) > 0)
        else None
    )

    # Source accuracy : combien de pred items ont leur doc_id dans supporting_doc_ids gold ?
    # Avec matcher tolérant (préfixe ≥ 12 chars) pour gérer les formats canonical vs short.
    if items_predicted:
        n_source_match = sum(
            1 for it in items_predicted
            if doc_id_match((it.get("source") or {}).get("doc_id", ""), supporting_doc_ids)
        )
        source_accuracy = n_source_match / len(items_predicted) if supporting_doc_ids else None
    else:
        source_accuracy = None

    coverage_state = (response.facts_first or {}).get("coverage_state")
    answerability = (response.facts_first or {}).get("answerability")

    sc = response.self_correction or {}
    ch2 = response.channel2
    return {
        "id": qid,
        "language": question_obj.get("language"),
        "question": question[:140],
        "elapsed_ms": elapsed_ms,
        "routing_decision": response.routing_decision,
        "primary_type_predicted": response.analyzer.primary_type,
        "primary_confidence": response.analyzer.primary_confidence,
        "n_evidence_qdrant": (response.evidence_bundle.n_qdrant_hits if response.evidence_bundle else 0),
        "n_evidence_neo4j_enriched": (response.evidence_bundle.n_neo4j_enriched if response.evidence_bundle else 0),
        "n_predicted": len(items_predicted),
        "n_expected": len(expected_norm_labels),
        "expected_min_items": expected_min_items,
        "item_recall": recall,
        "item_precision": precision,
        "item_f1": f1,
        "source_accuracy": source_accuracy,
        "coverage_state_predicted": coverage_state,
        "answerability_predicted": answerability,
        "verifier_passed": response.verifier.passed if response.verifier else None,
        "verifier_severity": response.verifier.severity if response.verifier else None,
        "structurer_rejected_count": (response.diagnostic or {}).get("structurer_rejected_count"),
        # Couches transverses (B + C)
        "self_correction_should_retry": sc.get("should_retry"),
        "self_correction_retry_executed": sc.get("retry_executed"),
        "self_correction_outcome": sc.get("retry_outcome"),
        "self_correction_actionable_codes": sc.get("actionable_codes", []),
        "channel2_verdict": ch2.overall_verdict if ch2 else None,
        "channel2_score": ch2.overall_score if ch2 else None,
        "channel2_n_supported": ch2.n_claims_supported if ch2 else None,
        "channel2_n_unsupported": ch2.n_claims_unsupported if ch2 else None,
        "answer_text": response.answer_text[:400] if response.answer_text else "",
        "predicted_labels": sorted(list(pred_norm_labels))[:30],
        "expected_labels": sorted(list(expected_norm_labels))[:30],
    }


def aggregate(results: list[dict]) -> dict:
    valid = [r for r in results if not r.get("error") and not r.get("skipped")]
    skipped = [r for r in results if r.get("skipped")]

    def _safe_mean(vals):
        vals = [v for v in vals if v is not None]
        return sum(vals) / len(vals) if vals else None

    def _percentile(vals, p):
        if not vals:
            return None
        s = sorted(vals)
        idx = max(0, min(len(s) - 1, int(p / 100 * len(s))))
        return s[idx]

    return {
        "n_total": len(results),
        "n_valid": len(valid),
        "n_skipped_routing": len(skipped),
        "n_errors": sum(1 for r in results if r.get("error")),
        "item_recall_mean": _safe_mean([r.get("item_recall") for r in valid]),
        "item_precision_mean": _safe_mean([r.get("item_precision") for r in valid]),
        "item_f1_mean": _safe_mean([r.get("item_f1") for r in valid]),
        "source_accuracy_mean": _safe_mean([r.get("source_accuracy") for r in valid]),
        "verifier_passed_rate": (
            sum(1 for r in valid if r.get("verifier_passed")) / len(valid) if valid else None
        ),
        "latency_p50_ms": _percentile([r.get("elapsed_ms") for r in valid], 50),
        "latency_p95_ms": _percentile([r.get("elapsed_ms") for r in valid], 95),
        "coverage_state_distribution": {
            cs: sum(1 for r in valid if r.get("coverage_state_predicted") == cs)
            for cs in ("complete", "partial", "unknown", "not_applicable")
        },
        "answerability_distribution": {
            a: sum(1 for r in valid if r.get("answerability_predicted") == a)
            for a in ("answerable", "partial", "unanswerable", "false_premise")
        },
        "routing_skips_by_predicted_type": {
            t: sum(1 for r in skipped if r.get("primary_type_predicted") == t)
            for t in ("factual", "list", "temporal", "comparison", "causal", "unanswerable", "false_premise")
        },
        "n_structurer_rejected_total": sum(
            (r.get("structurer_rejected_count") or 0) for r in valid
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--workers", type=int, default=2)
    parser.add_argument("--include-old-t6", action="store_true",
                        help="Inclure les anciennes T6_AERO list questions (items méta-descriptifs)")
    parser.add_argument("--transverse", action="store_true",
                        help="Activer Couches B (SelfCorrector) + C (Channel2 NLI)")
    args = parser.parse_args()

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    questions = load_list_questions(args.limit, only_handcrafted=not args.include_old_t6)
    logger.info("Loaded %d list questions (only_handcrafted=%s, transverse=%s)",
                len(questions), not args.include_old_t6, args.transverse)

    pipeline = build_pipeline(use_transverse=args.transverse)
    logger.info("Pipeline ready — starting bench")

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

    elapsed = time.time() - t0
    summary = aggregate(results)
    summary["elapsed_seconds"] = round(elapsed, 1)

    print()
    print("=== CH-41.4 BENCH LIST TRANCHE 1 — RÉSUMÉ ===")
    for k in (
        "n_total", "n_valid", "n_skipped_routing", "n_errors",
        "item_recall_mean", "item_precision_mean", "item_f1_mean",
        "source_accuracy_mean", "verifier_passed_rate",
        "latency_p50_ms", "latency_p95_ms",
    ):
        v = summary.get(k)
        if isinstance(v, float):
            print(f"  {k}: {v:.3f}")
        else:
            print(f"  {k}: {v}")
    print(f"  coverage_state_distribution: {summary['coverage_state_distribution']}")
    print(f"  answerability_distribution: {summary['answerability_distribution']}")
    print(f"  routing_skips_by_predicted_type: {summary['routing_skips_by_predicted_type']}")
    print(f"  n_structurer_rejected_total: {summary['n_structurer_rejected_total']}")
    print()
    print("=== GATES ADR CH-41.4 ===")
    item_f1 = summary.get("item_f1_mean") or 0
    item_recall = summary.get("item_recall_mean") or 0
    source_acc = summary.get("source_accuracy_mean") or 0
    p95 = summary.get("latency_p95_ms") or 0
    print(f"  item_f1     = {item_f1:.3f}  (gate ≥ 0.70)  {'✓' if item_f1 >= 0.70 else '✗'}")
    print(f"  item_recall = {item_recall:.3f}  (gate ≥ 0.65, was 0.07 in V3 = +58pp)  {'✓' if item_recall >= 0.65 else '✗'}")
    print(f"  source_acc  = {source_acc:.3f}  (gate ≥ 0.80)  {'✓' if source_acc >= 0.80 else '✗'}")
    print(f"  p95_latency = {p95}ms  (gate ≤ 35000)  {'✓' if p95 <= 35000 else '✗'}")

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
