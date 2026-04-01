"""
Evaluateur Robustesse — Teste les typologies de questions non couvertes.

Categorie par categorie :
- false_premise     : le systeme corrige-t-il la premisse fausse ?
- unanswerable      : le systeme admet-il ne pas savoir ?
- temporal_evolution : le systeme identifie-t-il les changements entre versions ?
- causal_why        : le systeme explique-t-il sans inventer ?
- hypothetical      : le systeme infere-t-il correctement ?
- negation          : le systeme identifie-t-il ce qui n'est PAS supporté ?
- synthesis_large   : le systeme couvre-t-il plusieurs aspects ?
- conditional       : le systeme extrait-il sous condition ?
- set_list          : le systeme enumere-t-il completement ?
- multi_hop         : le systeme chaine-t-il plusieurs faits ?

Usage :
    python -m benchmark.evaluators.robustness_diagnostic --profile standard
"""

from __future__ import annotations

import json
import logging
import os
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import redis
import requests

logger = logging.getLogger(__name__)

REDIS_KEY = "osmose:benchmark:robustness:state"
REDIS_TTL = 7200

# ═══════════════════════════════════════════════════════════════════════
# Keyword utilities
# ═══════════════════════════════════════════════════════════════════════

IGNORANCE_KEYWORDS = [
    "pas d'information",
    "ne dispose pas",
    "pas mentionne",
    "non disponible",
    "aucune donnee",
    "aucune reference",
    "ne mentionne pas",
    "ne traite pas",
    "hors du scope",
    "pas de donnee",
    "je ne sais pas",
    "impossible de repondre",
    "aucune information",
    "pas trouve",
    "not found",
    "no information",
    "cannot answer",
    "documents ne contiennent pas",
    "corpus ne contient pas",
    "pas dans les documents",
    "pas dans le corpus",
]

CORRECTION_KEYWORDS = [
    "en realite",
    "contrairement",
    "cependant",
    "neanmoins",
    "toutefois",
    "en fait",
    "il est important de noter",
    "attention",
    "incorrect",
    "inexact",
    "faux",
    "erreur",
    "la premisse",
    "actually",
    "however",
    "contrary",
    "not correct",
    "supporte", "supportent",
    "est disponible", "sont disponibles",
]

TEMPORAL_KEYWORDS = [
    "2021", "2022", "2023", "2024", "2025",
    "evolution", "evolue", "change", "modifie",
    "avant", "apres", "precedent", "nouveau",
    "ancienne", "nouvelle", "mise a jour",
    "version", "edition", "fps",
]


def normalize(text: str) -> str:
    t = text.lower().strip()
    t = re.sub(r"\s+", " ", t)
    return t


def extract_keywords(text: str, min_len: int = 4) -> set[str]:
    words = re.findall(r"[a-zA-Z0-9_/]{%d,}" % min_len, text.lower())
    return set(words)


# ═══════════════════════════════════════════════════════════════════════
# Evaluators by category
# ═══════════════════════════════════════════════════════════════════════


def evaluate_false_premise(answer: str, ground_truth: dict) -> dict[str, Any]:
    """Le systeme corrige-t-il la premisse fausse ?"""
    answer_lower = normalize(answer)

    # 1. Corrige la premisse ?
    corrects_premise = any(kw in answer_lower for kw in CORRECTION_KEYWORDS)

    # 2. Ne confirme PAS le faux claim
    correct_fact = ground_truth.get("correct_fact", "")
    correct_kw = extract_keywords(correct_fact)
    fact_mentioned = len(correct_kw & extract_keywords(answer)) / max(len(correct_kw), 1)

    # 3. Evidence citee ?
    evidence = ground_truth.get("evidence_claim", "")
    evidence_kw = extract_keywords(evidence)
    evidence_found = len(evidence_kw & extract_keywords(answer)) / max(len(evidence_kw), 1) >= 0.3

    return {
        "category": "false_premise",
        "premise_corrected": 1.0 if corrects_premise else 0.0,
        "correct_fact_mentioned": round(fact_mentioned, 3),
        "evidence_cited": 1.0 if evidence_found else 0.0,
        "score": round((
            (0.5 if corrects_premise else 0.0) +
            (0.3 * min(fact_mentioned, 1.0)) +
            (0.2 if evidence_found else 0.0)
        ), 3),
    }


def evaluate_unanswerable(answer: str, ground_truth: dict) -> dict[str, Any]:
    """Le systeme admet-il ne pas savoir ?"""
    answer_lower = normalize(answer)

    admits_ignorance = any(kw in answer_lower for kw in IGNORANCE_KEYWORDS)

    # Check expected keywords
    expected_kw = ground_truth.get("expected_keywords", [])
    kw_found = sum(1 for kw in expected_kw if kw.lower() in answer_lower)
    kw_coverage = kw_found / max(len(expected_kw), 1)

    # Penalite si le systeme invente (reponse longue = probable hallucination)
    word_count = len(answer.split())
    likely_hallucination = word_count > 150 and not admits_ignorance

    return {
        "category": "unanswerable",
        "admits_ignorance": 1.0 if admits_ignorance else 0.0,
        "keyword_coverage": round(kw_coverage, 3),
        "likely_hallucination": 1.0 if likely_hallucination else 0.0,
        "score": round((
            (0.6 if admits_ignorance else 0.0) +
            (0.2 * kw_coverage) +
            (0.2 if not likely_hallucination else 0.0)
        ), 3),
    }


def evaluate_temporal(answer: str, sources: list[str], ground_truth: dict) -> dict[str, Any]:
    """Le systeme identifie-t-il les changements entre versions ?"""
    answer_lower = normalize(answer)
    answer_words = extract_keywords(answer)

    # 1. Mentionne les versions ?
    temporal_found = sum(1 for kw in TEMPORAL_KEYWORDS if kw in answer_lower)
    temporal_score = min(temporal_found / 3, 1.0)

    # 2. Identifie le changement specifique ?
    evolution = ground_truth.get("evolution", "")
    evo_kw = extract_keywords(evolution)
    evo_coverage = len(evo_kw & answer_words) / max(len(evo_kw), 1) if evo_kw else 0

    # 3. Cite les docs
    docs = ground_truth.get("docs", [])
    docs_found = 0
    for doc in docs:
        doc_prefix = doc[:3]
        if any(doc_prefix in s for s in sources):
            docs_found += 1
    doc_coverage = docs_found / max(len(docs), 1)

    return {
        "category": "temporal_evolution",
        "temporal_awareness": round(temporal_score, 3),
        "change_identified": round(evo_coverage, 3),
        "docs_cited": round(doc_coverage, 3),
        "score": round((
            (0.3 * temporal_score) +
            (0.4 * min(evo_coverage, 1.0)) +
            (0.3 * doc_coverage)
        ), 3),
    }


def evaluate_causal(answer: str, ground_truth: dict) -> dict[str, Any]:
    """Le systeme explique-t-il sans inventer ?"""
    answer_lower = normalize(answer)
    answer_words = extract_keywords(answer)

    evidence = ground_truth.get("evidence_claim", "")
    evidence_kw = extract_keywords(evidence)
    evidence_coverage = len(evidence_kw & answer_words) / max(len(evidence_kw), 1)

    # Longueur raisonnable (pas trop court = esquive, pas trop long = hallucination)
    word_count = len(answer.split())
    reasonable_length = 30 <= word_count <= 400

    return {
        "category": "causal_why",
        "evidence_coverage": round(evidence_coverage, 3),
        "reasonable_length": 1.0 if reasonable_length else 0.0,
        "score": round((
            (0.7 * min(evidence_coverage, 1.0)) +
            (0.3 if reasonable_length else 0.0)
        ), 3),
    }


def evaluate_hypothetical(answer: str, ground_truth: dict) -> dict[str, Any]:
    """Le systeme infere-t-il correctement ?"""
    answer_lower = normalize(answer)
    answer_words = extract_keywords(answer)

    evidence = ground_truth.get("evidence_claim", ground_truth.get("expected_inference", ""))
    evidence_kw = extract_keywords(evidence)
    evidence_coverage = len(evidence_kw & answer_words) / max(len(evidence_kw), 1)

    # Mentionne un risque/consequence ?
    consequence_kw = ["risque", "consequence", "impact", "probleme", "danger",
                      "risk", "issue", "without", "sans", "ne pas", "impossible"]
    mentions_consequence = any(kw in answer_lower for kw in consequence_kw)

    return {
        "category": "hypothetical",
        "evidence_coverage": round(evidence_coverage, 3),
        "mentions_consequence": 1.0 if mentions_consequence else 0.0,
        "score": round((
            (0.5 * min(evidence_coverage, 1.0)) +
            (0.5 if mentions_consequence else 0.0)
        ), 3),
    }


def evaluate_negation(answer: str, ground_truth: dict) -> dict[str, Any]:
    """Le systeme identifie-t-il ce qui n'est PAS supporte ?"""
    answer_lower = normalize(answer)
    answer_words = extract_keywords(answer)

    evidence = ground_truth.get("evidence_claim", "")
    evidence_kw = extract_keywords(evidence)
    evidence_coverage = len(evidence_kw & answer_words) / max(len(evidence_kw), 1)

    negation_kw = ["ne pas", "n'est pas", "ne peut pas", "impossible",
                   "pas supporte", "no longer", "not", "cannot", "doesn't",
                   "limite", "restriction", "exception", "condition"]
    mentions_negation = any(kw in answer_lower for kw in negation_kw)

    return {
        "category": "negation",
        "evidence_coverage": round(evidence_coverage, 3),
        "mentions_negation": 1.0 if mentions_negation else 0.0,
        "score": round((
            (0.6 * min(evidence_coverage, 1.0)) +
            (0.4 if mentions_negation else 0.0)
        ), 3),
    }


def evaluate_synthesis(answer: str, sources: list[str], ground_truth: dict) -> dict[str, Any]:
    """Le systeme couvre-t-il plusieurs aspects ?"""
    answer_lower = normalize(answer)

    expected_aspects = ground_truth.get("expected_aspects", [])
    aspects_found = 0
    for aspect in expected_aspects:
        aspect_words = set(aspect.lower().replace("_", " ").split())
        if any(w in answer_lower for w in aspect_words if len(w) > 3):
            aspects_found += 1
    aspect_coverage = aspects_found / max(len(expected_aspects), 1)

    # Multi-doc cite ?
    unique_docs = set()
    for s in sources:
        prefix = s[:3]
        if prefix and prefix[0].isdigit():
            unique_docs.add(prefix)
    min_docs = ground_truth.get("min_docs", 2)
    doc_coverage = min(len(unique_docs) / max(min_docs, 1), 1.0)

    # Longueur (synthese = reponse substantielle)
    word_count = len(answer.split())
    good_length = word_count >= 80

    return {
        "category": "synthesis_large",
        "aspect_coverage": round(aspect_coverage, 3),
        "aspects_found": aspects_found,
        "aspects_total": len(expected_aspects),
        "doc_coverage": round(doc_coverage, 3),
        "good_length": 1.0 if good_length else 0.0,
        "score": round((
            (0.5 * aspect_coverage) +
            (0.3 * doc_coverage) +
            (0.2 if good_length else 0.0)
        ), 3),
    }


def evaluate_conditional(answer: str, ground_truth: dict) -> dict[str, Any]:
    """Le systeme extrait-il sous condition ?"""
    answer_words = extract_keywords(answer)

    evidence = ground_truth.get("evidence_claim", ground_truth.get("answer", ""))
    evidence_kw = extract_keywords(evidence)
    evidence_coverage = len(evidence_kw & answer_words) / max(len(evidence_kw), 1)

    return {
        "category": "conditional",
        "evidence_coverage": round(evidence_coverage, 3),
        "score": round(min(evidence_coverage, 1.0), 3),
    }


def evaluate_set_list(answer: str, ground_truth: dict) -> dict[str, Any]:
    """Le systeme enumere-t-il completement ?"""
    answer_lower = normalize(answer)

    expected_items = ground_truth.get("expected_items", [])
    items_found = 0
    for item in expected_items:
        item_words = set(item.lower().replace("_", " ").split())
        significant_words = [w for w in item_words if len(w) > 3]
        if significant_words and any(w in answer_lower for w in significant_words):
            items_found += 1

    min_items = ground_truth.get("min_items", len(expected_items))
    completeness = items_found / max(len(expected_items), 1)

    return {
        "category": "set_list",
        "items_found": items_found,
        "items_total": len(expected_items),
        "completeness": round(completeness, 3),
        "score": round(completeness, 3),
    }


def evaluate_multi_hop(answer: str, sources: list[str], ground_truth: dict) -> dict[str, Any]:
    """Le systeme chaine-t-il plusieurs faits ?"""
    answer_words = extract_keywords(answer)

    chain = ground_truth.get("chain", [])
    chain_hits = 0
    for link in chain:
        link_text = link if isinstance(link, str) else link.get("text", str(link))
        link_kw = extract_keywords(link_text)
        coverage = len(link_kw & answer_words) / max(len(link_kw), 1)
        if coverage >= 0.3:
            chain_hits += 1

    chain_coverage = chain_hits / max(len(chain), 1)

    # Multi-doc
    unique_docs = set()
    for s in sources:
        prefix = s[:3]
        if prefix and prefix[0].isdigit():
            unique_docs.add(prefix)

    return {
        "category": "multi_hop",
        "chain_hits": chain_hits,
        "chain_total": len(chain),
        "chain_coverage": round(chain_coverage, 3),
        "docs_cited": len(unique_docs),
        "score": round(chain_coverage, 3),
    }


# ═══════════════════════════════════════════════════════════════════════
# Router
# ═══════════════════════════════════════════════════════════════════════

EVALUATORS = {
    "false_premise": lambda ans, src, gt: evaluate_false_premise(ans, gt),
    "unanswerable": lambda ans, src, gt: evaluate_unanswerable(ans, gt),
    "temporal_evolution": lambda ans, src, gt: evaluate_temporal(ans, src, gt),
    "causal_why": lambda ans, src, gt: evaluate_causal(ans, gt),
    "hypothetical": lambda ans, src, gt: evaluate_hypothetical(ans, gt),
    "negation": lambda ans, src, gt: evaluate_negation(ans, gt),
    "synthesis_large": lambda ans, src, gt: evaluate_synthesis(ans, src, gt),
    "conditional": lambda ans, src, gt: evaluate_conditional(ans, gt),
    "set_list": lambda ans, src, gt: evaluate_set_list(ans, gt),
    "multi_hop": lambda ans, src, gt: evaluate_multi_hop(ans, src, gt),
}


# ═══════════════════════════════════════════════════════════════════════
# API call
# ═══════════════════════════════════════════════════════════════════════

def _call_osmosis_api(question: str, api_base: str, token: str = "") -> dict:
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"

    resp = requests.post(
        f"{api_base}/api/search",
        json={
            "question": question,
            "graph_enrichment_level": "standard",
            "use_graph_first": True,
            "use_kg_traversal": True,
            "use_latest": True,
        },
        headers=headers,
        timeout=120,
    )
    resp.raise_for_status()
    data = resp.json()

    # Extraire la reponse (format OSMOSIS: synthesis.synthesized_answer)
    synthesis = data.get("synthesis", {})
    if isinstance(synthesis, dict):
        answer = synthesis.get("synthesized_answer", "")
    else:
        answer = data.get("answer", data.get("response", ""))

    sources = []
    for s in data.get("results", data.get("sources", data.get("chunks", []))):
        if isinstance(s, dict):
            src = s.get("source_file", s.get("doc_id", s.get("metadata", {}).get("source_file", "")))
            if src:
                sources.append(src)

    return {"answer": answer, "sources_used": sources}


# ═══════════════════════════════════════════════════════════════════════
# Redis state
# ═══════════════════════════════════════════════════════════════════════

_redis_client = None

def _update_redis_state(redis_url: str, state: dict):
    global _redis_client
    try:
        if _redis_client is None:
            _redis_client = redis.Redis.from_url(redis_url)
        _redis_client.setex(REDIS_KEY, REDIS_TTL, json.dumps(state))
    except Exception:
        pass


# ═══════════════════════════════════════════════════════════════════════
# Aggregation
# ═══════════════════════════════════════════════════════════════════════

def aggregate_scores(per_sample: list[dict]) -> dict[str, Any]:
    """Aggrege les scores par categorie."""
    categories: dict[str, list[dict]] = {}
    for s in per_sample:
        ev = s.get("evaluation", {})
        if "error" in ev:
            continue
        cat = ev.get("category", "unknown")
        categories.setdefault(cat, []).append(ev)

    scores: dict[str, Any] = {}

    # Score global
    all_scores = [s["evaluation"]["score"] for s in per_sample
                  if "score" in s.get("evaluation", {}) and "error" not in s.get("evaluation", {})]
    if all_scores:
        scores["global_score"] = round(sum(all_scores) / len(all_scores), 4)

    # Par categorie
    for cat, evals in sorted(categories.items()):
        cat_scores = [e["score"] for e in evals if "score" in e]
        if cat_scores:
            scores[f"{cat}_score"] = round(sum(cat_scores) / len(cat_scores), 4)
            scores[f"{cat}_count"] = len(cat_scores)

    scores["total_evaluated"] = len([s for s in per_sample if "error" not in s.get("evaluation", {})])
    scores["total_errors"] = len([s for s in per_sample if "error" in s.get("evaluation", {})])

    return scores


# ═══════════════════════════════════════════════════════════════════════
# Main job
# ═══════════════════════════════════════════════════════════════════════

def run_benchmark_job(
    profile: str = "standard",
    redis_url: str = "redis://localhost:6379/0",
    tag: str = "",
    description: str = "",
):
    """Execute un benchmark robustesse complet."""
    job_start = time.time()
    api_base = os.getenv("OSMOSIS_API_URL", "http://localhost:8000")

    questions_file = Path("benchmark/questions/task6_robustness.json")
    if not questions_file.exists():
        _update_redis_state(redis_url, {"status": "failed", "error": "Questions file not found"})
        return

    data = json.loads(questions_file.read_text(encoding="utf-8"))
    all_questions = data.get("questions", [])

    logger.info(f"[ROBUSTESSE] Starting benchmark — {len(all_questions)} questions, tag={tag}")

    _update_redis_state(redis_url, {
        "status": "running",
        "phase": "api_eval",
        "progress": 0,
        "total": len(all_questions),
        "current_question": "Starting...",
    })

    # Auth
    token = ""
    try:
        resp = requests.post(f"{api_base}/api/auth/login",
                             json={"email": "admin@example.com", "password": "admin123"}, timeout=10)
        if resp.status_code == 200:
            token = resp.json().get("access_token", "")
            logger.info("[ROBUSTESSE] Auth OK")
        else:
            logger.warning(f"[ROBUSTESSE] Auth failed: {resp.status_code}")
    except Exception as e:
        logger.warning(f"[ROBUSTESSE] Auth error: {e}")

    per_sample = []
    errors = 0

    for i, q_item in enumerate(all_questions):
        question = q_item.get("question", "")
        category = q_item.get("category", "")
        question_id = q_item.get("question_id", f"q_{i}")
        ground_truth = q_item.get("ground_truth", {})

        _update_redis_state(redis_url, {
            "status": "running",
            "phase": "api_eval",
            "progress": i,
            "total": len(all_questions),
            "current_question": question[:100],
        })

        try:
            api_result = _call_osmosis_api(question, api_base, token)
            answer = api_result["answer"]
            sources = api_result["sources_used"]

            evaluator = EVALUATORS.get(category)
            if evaluator:
                evaluation = evaluator(answer, sources, ground_truth)
            else:
                evaluation = {"category": category, "score": 0.0, "error": f"Unknown category: {category}"}

            per_sample.append({
                "question_id": question_id,
                "question": question[:200],
                "category": category,
                "answer": answer[:500],
                "evaluation": evaluation,
            })

            logger.info(
                f"[ROBUSTESSE] [{i+1}/{len(all_questions)}] {question_id} "
                f"({category}) — score={evaluation.get('score', '?')}"
            )

        except Exception as e:
            errors += 1
            per_sample.append({
                "question_id": question_id,
                "question": question[:200],
                "category": category,
                "evaluation": {"error": str(e)[:200], "category": category},
            })
            logger.warning(f"[ROBUSTESSE] Error on {question_id}: {e}")

    # Aggregation
    scores = aggregate_scores(per_sample)
    duration_s = round(time.time() - job_start, 1)

    logger.info(f"[ROBUSTESSE] Completed in {duration_s}s — scores: {scores}")

    # Save report
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    tag_suffix = f"_{tag}" if tag else ""
    report_filename = f"robustness_run_{ts}{tag_suffix}.json"
    results_dir = Path("data/benchmark/results")
    results_dir.mkdir(parents=True, exist_ok=True)

    report_data = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "profile": profile,
        "tag": tag or "",
        "description": description or "",
        "duration_s": duration_s,
        "scores": scores,
        "per_sample": per_sample,
        "errors": errors,
    }

    report_path = results_dir / report_filename
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(report_data, f, indent=2, ensure_ascii=False)

    logger.info(f"[ROBUSTESSE] Report saved to {report_path}")

    _update_redis_state(redis_url, {
        "status": "completed",
        "phase": "report",
        "progress": 1,
        "total": 1,
        "report_file": report_filename,
        "duration_s": duration_s,
        "scores": scores,
    })


# ═══════════════════════════════════════════════════════════════════════
# CLI
# ═══════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    import argparse

    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

    parser = argparse.ArgumentParser(description="Benchmark Robustesse")
    parser.add_argument("--api", default="http://localhost:8000")
    parser.add_argument("--tag", default="")
    parser.add_argument("--description", default="")
    args = parser.parse_args()

    os.environ["OSMOSIS_API_URL"] = args.api
    run_benchmark_job(tag=args.tag, description=args.description)
