#!/usr/bin/env python3
"""
T2/T5 Diagnostic — Evaluation contradiction detection & cross-doc reasoning.

Metriques T2 (contradictions) :
- both_sides_surfaced   : la reponse mentionne-t-elle les DEUX claims ?
- tension_mentioned     : la reponse signale-t-elle explicitement une divergence ?
- both_sources_cited    : les deux documents sources sont-ils cites ?

Metriques T5 (KG differentiators) :
- chain_coverage        : combien d'elements de la chaine attendue sont presents ?
- multi_doc_cited       : combien des documents requis sont cites ?
- proactive_detection   : le systeme detecte-t-il une contradiction cachee ?

Mode hybride : keyword matching + LLM-juge (GPT-4o-mini) pour les metriques
cross-lingue (both_sides_surfaced T2, chain_coverage T5 multi_source_synthesis).
Le LLM-juge est active si OPENAI_API_KEY est disponible.

Usage :
    # Live : interroge l'API et evalue
    python benchmark/evaluators/t2t5_diagnostic.py --live --profile standard
    python benchmark/evaluators/t2t5_diagnostic.py --live --profile quick
    python benchmark/evaluators/t2t5_diagnostic.py --live --profile full
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests

logging.basicConfig(level=logging.INFO, format="%(asctime)s [T2T5] %(message)s")
logger = logging.getLogger("t2t5-diagnostic")


# ═══════════════════════════════════════════════════════════════════════
# LLM Judge (GPT-4o-mini) — pour evaluation cross-lingue
# ═══════════════════════════════════════════════════════════════════════

_llm_judge_client = None
LLM_JUDGE_MODEL = "gpt-4o-mini"


def _get_llm_judge():
    """Retourne un client OpenAI si OPENAI_API_KEY est disponible, sinon None."""
    global _llm_judge_client
    if _llm_judge_client is not None:
        return _llm_judge_client
    api_key = os.environ.get("OPENAI_API_KEY", "")
    if not api_key:
        return None
    try:
        from openai import OpenAI
        _llm_judge_client = OpenAI(api_key=api_key)
        logger.info(f"[T2T5] LLM judge initialized ({LLM_JUDGE_MODEL})")
        return _llm_judge_client
    except Exception as e:
        logger.warning(f"[T2T5] LLM judge unavailable: {e}")
        return None


def _llm_judge_t2(client, question: str, claim1_text: str, claim2_text: str, answer: str) -> dict | None:
    """LLM-juge pour T2 : evalue both_sides, tension, sources (scores 0-100)."""
    # Pre-traitement LOCAL au juge : convertir [[SOURCE:...]] en (Doc, p. X)
    # Voir benchmark/evaluators/_judge_preprocess.py pour le contrat.
    from benchmark.evaluators._judge_preprocess import preprocess_answer_for_judge
    judge_answer = preprocess_answer_for_judge(answer)
    MAX_JUDGE_CHARS = 3000

    prompt = (
        'You are a benchmark evaluator for a document contradiction detection system.\n\n'
        f'Question: "{question[:200]}"\n\n'
        f'Claim 1 (from document A): "{claim1_text[:150]}"\n'
        f'Claim 2 (from document B): "{claim2_text[:150]}"\n\n'
        f'The system produced this answer:\n"{judge_answer[:MAX_JUDGE_CHARS]}"\n\n'
        'Rate each aspect from 0 to 100:\n'
        '1. both_sides: Does the answer present information from BOTH claims? Even paraphrased, '
        'in a different language, or summarized — if BOTH perspectives are covered, score high.\n'
        '2. tension: Does the answer acknowledge a difference, evolution, tension, contradiction, '
        'or divergence between sources? Look for words like "however", "but", "cependant", '
        '"toutefois", "differs", "changed", "evolution" in ANY language.\n'
        '3. sources: Does the answer reference or cite multiple source documents? '
        'Look for any mention of document names, years, guide names, version numbers.\n\n'
        'Reply with ONLY three numbers (0-100) separated by commas.\n'
        'Example: 85,70,60'
    )
    try:
        resp = client.chat.completions.create(
            model=LLM_JUDGE_MODEL, max_tokens=10, temperature=0.0,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = resp.choices[0].message.content.strip()
        parts = [float(x.strip()) for x in raw.split(",")]
        if len(parts) >= 3:
            return {
                "both_sides_surfaced": round(min(parts[0], 100) / 100.0, 3),
                "tension_mentioned": round(min(parts[1], 100) / 100.0, 3),
                "both_sources_cited": round(min(parts[2], 100) / 100.0, 3),
                "judge_raw": raw,
            }
    except Exception as e:
        logger.debug(f"[T2T5] LLM judge T2 error: {e}")
    return None


def _llm_judge_t5(client, question: str, category: str, answer: str) -> dict | None:
    """LLM-juge pour T5 : evalue chain_coverage et multi_doc (scores 0-100)."""
    # Pre-traitement LOCAL au juge (voir _judge_preprocess.py pour le contrat)
    from benchmark.evaluators._judge_preprocess import preprocess_answer_for_judge
    judge_answer = preprocess_answer_for_judge(answer)
    MAX_JUDGE_CHARS = 3000

    prompt = (
        'You are a benchmark evaluator for a cross-document analysis system.\n\n'
        f'Question: "{question[:200]}"\nCategory: {category}\n\n'
        f'The system produced this answer:\n"{judge_answer[:MAX_JUDGE_CHARS]}"\n\n'
        'Rate each aspect from 0 to 100:\n'
        '1. chain_coverage: How well does the answer cover facts from multiple documents to '
        'build a complete answer? A good answer connects information across sources and covers '
        'the main aspects asked in the question.\n'
        '2. multi_doc: Does the answer reference or cite multiple source documents? '
        'Look for any document names, years, or version references.\n\n'
        'Reply with ONLY two numbers (0-100) separated by commas.\n'
        'Example: 75,80'
    )
    try:
        resp = client.chat.completions.create(
            model=LLM_JUDGE_MODEL, max_tokens=10, temperature=0.0,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = resp.choices[0].message.content.strip()
        parts = [float(x.strip()) for x in raw.split(",")]
        if len(parts) >= 2:
            return {
                "chain_coverage": round(min(parts[0], 100) / 100.0, 3),
                "multi_doc_cited": round(min(parts[1], 100) / 100.0, 3),
                "judge_raw": raw,
            }
    except Exception as e:
        logger.debug(f"[T2T5] LLM judge T5 error: {e}")
    return None


# ═══════════════════════════════════════════════════════════════════════
# Profiles
# ═══════════════════════════════════════════════════════════════════════

T2T5_PROFILES: dict[str, dict] = {
    "quick": {
        "label": "Quick T5 (25q)",
        "tasks": [
            {
                "name": "T5 KG Differentiators",
                "questions_file": "benchmark/questions/task5_kg_differentiators.json",
                "task_type": "T5",
            },
        ],
    },
    "standard": {
        "label": "Standard T2+T5 (50q)",
        "tasks": [
            {
                "name": "T2 Contradictions Expert",
                "questions_file": "benchmark/questions/task2_contradictions_human_v2.json",
                "task_type": "T2",
            },
            {
                "name": "T5 KG Differentiators",
                "questions_file": "benchmark/questions/task5_kg_differentiators.json",
                "task_type": "T5",
            },
        ],
    },
    "full": {
        "label": "Full T2+T5 (175q)",
        "tasks": [
            {
                "name": "T2 Contradictions Expert",
                "questions_file": "benchmark/questions/task2_contradictions_human_v2.json",
                "task_type": "T2",
            },
            {
                "name": "T2 Contradictions KG",
                "questions_file": "benchmark/questions/task2_contradictions_kg.json",
                "task_type": "T2",
            },
            {
                "name": "T5 KG Differentiators",
                "questions_file": "benchmark/questions/task5_kg_differentiators.json",
                "task_type": "T5",
            },
        ],
    },
}

REDIS_KEY = "osmose:benchmark:t2t5:state"
REDIS_TTL = 7200  # 2h


# ═══════════════════════════════════════════════════════════════════════
# Text Utilities
# ═══════════════════════════════════════════════════════════════════════


def normalize(text: str) -> str:
    """Normalise pour comparaison : lowercase, whitespace, ponctuation."""
    t = text.lower().strip()
    t = re.sub(r"\s+", " ", t)
    t = re.sub(r"[^\w\s]", " ", t)
    return t


def extract_keywords(text: str, min_len: int = 4) -> set[str]:
    """Extrait les mots significatifs (>= min_len chars)."""
    return {w for w in normalize(text).split() if len(w) >= min_len}


# ═══════════════════════════════════════════════════════════════════════
# Tension Detection Keywords
# ═══════════════════════════════════════════════════════════════════════

TENSION_KEYWORDS = [
    "divergen",
    "contradict",
    "differ",
    "disagree",
    "however",
    "en revanche",
    "toutefois",
    "cependant",
    "attention",
    "contradiction",
    "while",
    "whereas",
    "points d'attention",
    "noter que",
    "incoheren",
    "tension",
    "deux version",
    "a change",
    "renomm",
    "version 2022",
    "version 2023",
    "discrepan",
    "deux document",
]


# ═══════════════════════════════════════════════════════════════════════
# T2 Evaluation — Contradiction Detection
# ═══════════════════════════════════════════════════════════════════════


def evaluate_t2(answer: str, sources_used: list[str], ground_truth: dict) -> dict[str, Any]:
    """Evalue une reponse T2 (contradiction detection) de maniere deterministe."""
    if not answer or len(answer) < 20:
        return {
            "both_sides_surfaced": 0.0,
            "tension_mentioned": 0.0,
            "both_sources_cited": 0.0,
            "task_type": "T2",
        }

    answer_norm = normalize(answer)
    answer_words = set(answer_norm.split())
    answer_lower = answer.lower()

    claim1 = ground_truth.get("claim1", {})
    claim2 = ground_truth.get("claim2", {})

    # 1. both_sides_surfaced — check keywords from both claims
    c1_keywords = extract_keywords(claim1.get("text", ""))
    c2_keywords = extract_keywords(claim2.get("text", ""))

    c1_matched = c1_keywords & answer_words
    c2_matched = c2_keywords & answer_words

    c1_coverage = len(c1_matched) / len(c1_keywords) if c1_keywords else 0
    c2_coverage = len(c2_matched) / len(c2_keywords) if c2_keywords else 0

    c1_surfaced = c1_coverage >= 0.5
    c2_surfaced = c2_coverage >= 0.5

    if c1_surfaced and c2_surfaced:
        both_sides = 1.0
    elif c1_surfaced or c2_surfaced:
        both_sides = 0.5
    else:
        both_sides = 0.0

    # 2. tension_mentioned — explicit divergence acknowledgement
    tension = 1.0 if any(kw in answer_lower for kw in TENSION_KEYWORDS) else 0.0

    # 3. both_sources_cited — check doc names
    c1_doc = claim1.get("doc_id", "")
    c2_doc = claim2.get("doc_id", "")

    def _doc_in_sources(doc_id: str, sources: list[str]) -> bool:
        if not doc_id:
            return False
        # Match by prefix (e.g. "027_SAP..." or just "027")
        doc_prefix = doc_id[:3] if len(doc_id) >= 3 else doc_id
        # Check in sources_used list
        for s in sources:
            if doc_prefix in s:
                return True
        # Also check in answer text (doc names often cited inline)
        if doc_prefix in answer_lower or doc_id[:20] in answer_lower:
            return True
        return False

    c1_cited = _doc_in_sources(c1_doc, sources_used)
    c2_cited = _doc_in_sources(c2_doc, sources_used)

    if c1_cited and c2_cited:
        both_sources = 1.0
    elif c1_cited or c2_cited:
        both_sources = 0.5
    else:
        both_sources = 0.0

    return {
        "both_sides_surfaced": both_sides,
        "tension_mentioned": tension,
        "both_sources_cited": both_sources,
        "claim1_coverage": round(c1_coverage, 3),
        "claim2_coverage": round(c2_coverage, 3),
        "task_type": "T2",
    }


# ═══════════════════════════════════════════════════════════════════════
# T5 Evaluation — KG Differentiators
# ═══════════════════════════════════════════════════════════════════════


def evaluate_t5(
    answer: str,
    sources_used: list[str],
    ground_truth: dict,
    grading_rules: dict,
    category: str,
) -> dict[str, Any]:
    """Evalue une reponse T5 (KG differentiator) de maniere deterministe."""
    if not answer or len(answer) < 20:
        return {
            "chain_coverage": 0.0,
            "multi_doc_cited": 0.0,
            "proactive_detection": 0.0,
            "task_type": "T5",
            "category": category,
        }

    answer_norm = normalize(answer)
    answer_words = set(answer_norm.split())
    answer_lower = answer.lower()

    # Extract unique doc prefixes from sources_used
    unique_docs = set()
    for s in sources_used:
        doc_prefix = s[:3] if len(s) >= 3 else s
        if doc_prefix and doc_prefix[0].isdigit():
            unique_docs.add(doc_prefix)

    result: dict[str, Any] = {
        "task_type": "T5",
        "category": category,
    }

    if category == "cross_doc_chain":
        # chain_coverage — how many chain elements are found
        chain = ground_truth.get("chain", [])
        chain_hits = 0
        chain_details = []
        for link in chain:
            link_text = link.get("text", "") if isinstance(link, dict) else str(link)
            link_keywords = extract_keywords(link_text)
            matched = link_keywords & answer_words
            coverage = len(matched) / len(link_keywords) if link_keywords else 0
            hit = coverage >= 0.4
            if hit:
                chain_hits += 1
            chain_details.append({
                "text": link_text[:80],
                "coverage": round(coverage, 3),
                "hit": hit,
            })

        chain_coverage = chain_hits / len(chain) if chain else 0

        # multi_doc_cited
        docs_required = ground_truth.get("docs_required", 2)
        # Count how many required doc prefixes appear
        required_docs = set()
        for link in chain:
            if isinstance(link, dict):
                doc_id = link.get("doc_id", "")
                if doc_id:
                    required_docs.add(doc_id[:3])

        docs_found = required_docs & unique_docs
        multi_doc = len(docs_found) / len(required_docs) if required_docs else min(len(unique_docs) / max(docs_required, 1), 1.0)

        result["chain_coverage"] = round(chain_coverage, 3)
        result["multi_doc_cited"] = round(multi_doc, 3)
        result["proactive_detection"] = 0.0  # N/A for cross_doc_chain
        result["chain_hits"] = chain_hits
        result["chain_total"] = len(chain)
        result["docs_cited"] = len(unique_docs)
        result["chain_details"] = chain_details

    elif category == "proactive_contradiction":
        # proactive_detection — did the system detect a hidden contradiction?
        hidden = ground_truth.get("hidden_contradiction", {})
        proactive = 1.0 if any(kw in answer_lower for kw in TENSION_KEYWORDS) else 0.0

        # Also check both sides surfaced
        c1_kw = extract_keywords(hidden.get("claim1", {}).get("text", ""))
        c2_kw = extract_keywords(hidden.get("claim2", {}).get("text", ""))
        c1_matched = c1_kw & answer_words
        c2_matched = c2_kw & answer_words
        c1_cov = len(c1_matched) / len(c1_kw) if c1_kw else 0
        c2_cov = len(c2_matched) / len(c2_kw) if c2_kw else 0

        result["chain_coverage"] = 0.0  # N/A
        result["multi_doc_cited"] = min(len(unique_docs) / 2, 1.0)
        result["proactive_detection"] = proactive
        result["both_sides_surfaced"] = 1.0 if (c1_cov >= 0.4 and c2_cov >= 0.4) else 0.0
        result["docs_cited"] = len(unique_docs)

    elif category == "multi_source_synthesis":
        # chain_coverage — based on expected_aspects
        expected_aspects = ground_truth.get("expected_aspects", [])
        aspects_found = 0
        for aspect in expected_aspects:
            aspect_keywords = set(aspect.lower().replace("_", " ").split())
            if any(kw in answer_lower for kw in aspect_keywords if len(kw) > 3):
                aspects_found += 1
        aspect_coverage = aspects_found / len(expected_aspects) if expected_aspects else 0

        # multi_doc_cited
        min_docs = ground_truth.get("min_docs_required", 3)
        expected_doc_ids = ground_truth.get("expected_docs", [])
        if expected_doc_ids:
            expected_prefixes = {d[:3] for d in expected_doc_ids}
            docs_found = expected_prefixes & unique_docs
            multi_doc = len(docs_found) / len(expected_prefixes)
        else:
            multi_doc = min(len(unique_docs) / max(min_docs, 1), 1.0)

        result["chain_coverage"] = round(aspect_coverage, 3)  # reuse metric for aspects
        result["multi_doc_cited"] = round(multi_doc, 3)
        result["proactive_detection"] = 0.0  # N/A
        result["aspects_found"] = aspects_found
        result["aspects_total"] = len(expected_aspects)
        result["docs_cited"] = len(unique_docs)

    else:
        result["chain_coverage"] = 0.0
        result["multi_doc_cited"] = 0.0
        result["proactive_detection"] = 0.0

    return result


# ═══════════════════════════════════════════════════════════════════════
# API Interaction
# ═══════════════════════════════════════════════════════════════════════


def _get_api_token(api_base: str) -> str:
    """Obtient un token d'authentification depuis l'API OSMOSIS."""
    resp = requests.post(
        f"{api_base}/api/auth/login",
        json={"email": "admin@example.com", "password": "admin123"},
        timeout=10,
    )
    if resp.status_code == 200:
        return resp.json().get("access_token", "")
    raise RuntimeError(f"[T2T5] Auth failed: {resp.status_code}")


def _call_osmosis_api(
    question: str,
    api_base: str,
    token_mgr,
    use_kg: bool = True,
) -> dict:
    """Appelle l'API OSMOSIS search et retourne la reponse structuree."""
    payload = {
        "question": question,
        "use_graph_context": use_kg,
        "graph_enrichment_level": "standard" if use_kg else "none",
        "use_graph_first": use_kg,
        "use_kg_traversal": use_kg,
        "use_latest": True,
    }
    headers = {
        "Authorization": f"Bearer {token_mgr.get()}",
        "Content-Type": "application/json",
    }
    resp = requests.post(
        f"{api_base}/api/search",
        json=payload,
        headers=headers,
        timeout=120,
    )
    resp.raise_for_status()
    data = resp.json()

    results = data.get("results", [])
    synthesis = data.get("synthesis", {})
    answer = synthesis.get("synthesized_answer", "") if isinstance(synthesis, dict) else ""
    sources_used = list(set(r.get("source_file", "") for r in results if isinstance(r, dict) and r.get("source_file")))

    return {
        "answer": answer,
        "sources_used": sources_used,
        "chunks_retrieved": len(results),
        "latency_ms": data.get("latency_ms", 0),
    }


# ═══════════════════════════════════════════════════════════════════════
# Redis Progress (Singleton pattern)
# ═══════════════════════════════════════════════════════════════════════

_redis_client = None


def _get_redis(redis_url: str):
    """Singleton Redis client."""
    global _redis_client
    if _redis_client is None:
        import redis as redis_lib
        _redis_client = redis_lib.from_url(redis_url, decode_responses=True)
    return _redis_client


def _update_redis_state(redis_url: str, state: dict):
    """Met a jour l'etat du benchmark dans Redis avec TTL."""
    try:
        rc = _get_redis(redis_url)
        rc.setex(REDIS_KEY, REDIS_TTL, json.dumps(state, default=str))
    except Exception as e:
        logger.error(f"[T2T5:BENCH] Redis update failed: {type(e).__name__}: {e}")


# ═══════════════════════════════════════════════════════════════════════
# Aggregation
# ═══════════════════════════════════════════════════════════════════════


def aggregate_scores(per_sample: list[dict]) -> dict[str, float]:
    """Aggrege les metriques T2 et T5 en scores moyens."""
    t2_samples = [s for s in per_sample if s.get("evaluation", {}).get("task_type") == "T2"]
    t5_samples = [s for s in per_sample if s.get("evaluation", {}).get("task_type") == "T5"]

    scores: dict[str, Any] = {}

    # T2 metrics
    if t2_samples:
        evals = [s["evaluation"] for s in t2_samples if "error" not in s.get("evaluation", {})]
        if evals:
            scores["both_sides_surfaced"] = round(sum(e.get("both_sides_surfaced", 0) for e in evals) / len(evals), 4)
            scores["tension_mentioned"] = round(sum(e.get("tension_mentioned", 0) for e in evals) / len(evals), 4)
            scores["both_sources_cited"] = round(sum(e.get("both_sources_cited", 0) for e in evals) / len(evals), 4)
        scores["t2_count"] = len(t2_samples)

    # T5 metrics
    if t5_samples:
        evals = [s["evaluation"] for s in t5_samples if "error" not in s.get("evaluation", {})]
        if evals:
            # chain_coverage : exclure proactive_contradiction (force a 0, pas applicable)
            chain_evals = [e for e in evals if e.get("category") != "proactive_contradiction"]
            if chain_evals:
                scores["chain_coverage"] = round(sum(e.get("chain_coverage", 0) for e in chain_evals) / len(chain_evals), 4)
            scores["multi_doc_cited"] = round(sum(e.get("multi_doc_cited", 0) for e in evals) / len(evals), 4)

        # proactive_detection only for proactive questions
        proactive_evals = [e for e in evals if e.get("category") == "proactive_contradiction"]
        if proactive_evals:
            scores["proactive_detection"] = round(
                sum(e.get("proactive_detection", 0) for e in proactive_evals) / len(proactive_evals), 4
            )
            scores["proactive_count"] = len(proactive_evals)

        # Per-category breakdown
        categories = {}
        for e in evals:
            cat = e.get("category", "unknown")
            if cat not in categories:
                categories[cat] = []
            categories[cat].append(e)

        for cat, cat_evals in categories.items():
            prefix = f"t5_{cat}"
            scores[f"{prefix}_count"] = len(cat_evals)
            scores[f"{prefix}_chain_coverage"] = round(
                sum(e["chain_coverage"] for e in cat_evals) / len(cat_evals), 4
            )
            scores[f"{prefix}_multi_doc_cited"] = round(
                sum(e["multi_doc_cited"] for e in cat_evals) / len(cat_evals), 4
            )

        scores["t5_count"] = len(t5_samples)

    scores["total_evaluated"] = len(per_sample)
    return scores


# ═══════════════════════════════════════════════════════════════════════
# Benchmark Job — Execution pilotee par l'API avec progression Redis
# ═══════════════════════════════════════════════════════════════════════


def run_benchmark_job(
    profile: str = "standard",
    redis_url: str = "redis://localhost:6379/0",
    tag: str = "",
    description: str = "",
    compare_rag: bool = False,
):
    """Execute un benchmark T2/T5 complet en arriere-plan.

    Parametres:
        profile: "quick" | "standard" | "full"
        redis_url: URL Redis pour les mises a jour de progression
        tag: Tag optionnel pour identifier le rapport (ex: "BASELINE_PRE_C4")
        description: Description libre du test (ex: "Apres ajout C4 relations")
        compare_rag: si True, execute aussi en mode RAG pur (sans KG) pour comparaison
    """
    job_start = time.time()
    api_base = os.getenv("OSMOSIS_API_URL", "http://localhost:8000")

    prof = T2T5_PROFILES.get(profile)
    if not prof:
        _update_redis_state(redis_url, {
            "status": "failed",
            "error": f"Unknown profile: {profile}",
        })
        return

    logger.info(f"[T2T5:BENCH] Starting benchmark job — profile={profile} ({prof['label']})")

    try:
        # ── Phase 0 : Auth ──────────────────────────────────────────
        _update_redis_state(redis_url, {
            "status": "running",
            "profile": profile,
            "phase": "auth",
            "progress": 0,
            "total": 0,
        })
        from benchmark.evaluators._auth import TokenManager
        token_mgr = TokenManager(api_base)
        token_mgr.get()  # fail fast if creds invalid

        # ── Phase 1 : Load questions ────────────────────────────────
        all_questions: list[dict] = []
        for task in prof["tasks"]:
            qfile = task["questions_file"]
            try:
                with open(qfile, "r", encoding="utf-8") as f:
                    qdata = json.load(f)
                qlist = qdata if isinstance(qdata, list) else qdata.get("questions", [])
                for q in qlist:
                    q["_task_name"] = task["name"]
                    q["_task_type"] = task["task_type"]
                all_questions.extend(qlist)
            except FileNotFoundError:
                logger.warning(f"[T2T5:BENCH] Questions file not found: {qfile}")
            except Exception as e:
                logger.warning(f"[T2T5:BENCH] Error loading {qfile}: {e}")

        total = len(all_questions)
        if total == 0:
            _update_redis_state(redis_url, {
                "status": "failed",
                "error": "No questions loaded",
            })
            return

        logger.info(f"[T2T5:BENCH] Loaded {total} questions")

        # ── Phase 2 : API calls + evaluation ────────────────────────
        per_sample: list[dict] = []
        errors = 0
        judge_client = _get_llm_judge()
        judge_mode = "hybrid" if judge_client else "keyword"
        logger.info(f"[T2T5:BENCH] Evaluation mode: {judge_mode}")

        for i, q_item in enumerate(all_questions):
            question = q_item.get("question", "")
            if not question:
                continue

            _update_redis_state(redis_url, {
                "status": "running",
                "profile": profile,
                "phase": "api_eval",
                "progress": i,
                "total": total,
                "current_question": question[:100],
            })

            try:
                # Call API
                api_result = _call_osmosis_api(question, api_base, token_mgr)

                # Evaluate
                task_type = q_item.get("_task_type", "")
                ground_truth = q_item.get("ground_truth", {})
                grading_rules = q_item.get("grading_rules", {})
                category = q_item.get("category", "")

                if task_type == "T2":
                    evaluation = evaluate_t2(
                        api_result["answer"],
                        api_result["sources_used"],
                        ground_truth,
                    )
                    # LLM-juge enrichissement T2 — uniquement both_sides_surfaced
                    # tension_mentioned et both_sources_cited fonctionnent bien en keyword
                    if judge_client and api_result["answer"]:
                        claim1_text = ground_truth.get("claim1", {}).get("text", "")
                        claim2_text = ground_truth.get("claim2", {}).get("text", "")
                        llm_scores = _llm_judge_t2(
                            judge_client, question, claim1_text, claim2_text, api_result["answer"]
                        )
                        if llm_scores:
                            evaluation["keyword_both_sides"] = evaluation["both_sides_surfaced"]
                            evaluation["both_sides_surfaced"] = llm_scores["both_sides_surfaced"]
                            evaluation["judge_model"] = LLM_JUDGE_MODEL

                elif task_type == "T5":
                    # Determine category from task field or category field
                    if not category:
                        task_field = q_item.get("task", "")
                        if "cross_doc" in task_field:
                            category = "cross_doc_chain"
                        elif "proactive" in task_field:
                            category = "proactive_contradiction"
                        elif "multi_source" in task_field:
                            category = "multi_source_synthesis"

                    evaluation = evaluate_t5(
                        api_result["answer"],
                        api_result["sources_used"],
                        ground_truth,
                        grading_rules,
                        category,
                    )
                    # LLM-juge enrichissement T5 — uniquement chain_coverage
                    # multi_doc_cited fonctionne bien en keyword (doc prefixes)
                    if judge_client and api_result["answer"] and category in ("cross_doc_chain", "multi_source_synthesis"):
                        llm_scores = _llm_judge_t5(
                            judge_client, question, category, api_result["answer"]
                        )
                        if llm_scores:
                            evaluation["keyword_chain_coverage"] = evaluation["chain_coverage"]
                            evaluation["chain_coverage"] = llm_scores["chain_coverage"]
                            evaluation["judge_model"] = LLM_JUDGE_MODEL

                else:
                    evaluation = {"task_type": "unknown"}

                per_sample.append({
                    "question_id": q_item.get("question_id", f"q_{i}"),
                    "question": question,
                    "task_name": q_item.get("_task_name", ""),
                    "evaluation": evaluation,
                    "answer": api_result["answer"],  # reponse complete (pas de troncature)
                    "answer_length": len(api_result["answer"]),
                    "ground_truth": q_item.get("ground_truth", {}),
                    "chunks_retrieved": api_result["chunks_retrieved"],
                    "sources_used": api_result["sources_used"],
                    "latency_ms": api_result["latency_ms"],
                })

                logger.info(
                    f"[T2T5:BENCH] [{i + 1}/{total}] {q_item.get('question_id', '')} "
                    f"— {task_type} evaluated"
                )

            except Exception as e:
                logger.warning(f"[T2T5:BENCH] Error on q={question[:60]}: {e}")
                errors += 1
                per_sample.append({
                    "question_id": q_item.get("question_id", f"q_{i}"),
                    "question": question[:200],
                    "task_name": q_item.get("_task_name", ""),
                    "evaluation": {"task_type": q_item.get("_task_type", ""), "error": str(e)[:200]},
                    "error": str(e)[:200],
                })

        # ── Phase 3 : Aggregation & Report ──────────────────────────
        _update_redis_state(redis_url, {
            "status": "running",
            "profile": profile,
            "phase": "report",
            "progress": 0,
            "total": 1,
            "current_question": "Generating report...",
        })

        osmosis_scores = aggregate_scores(per_sample)

        # ── Phase 3b : RAG baseline (optionnel) ───────────────────────
        rag_scores = None
        rag_per_sample = None
        if compare_rag:
            _update_redis_state(redis_url, {
                "status": "running",
                "profile": profile,
                "phase": "rag_baseline",
                "progress": 0,
                "total": total,
                "current_question": "Collecting RAG baseline...",
            })

            rag_per_sample = []
            rag_errors = 0
            for i, q_item in enumerate(all_questions):
                question = q_item.get("question", "")
                if not question:
                    continue

                _update_redis_state(redis_url, {
                    "status": "running",
                    "profile": profile,
                    "phase": "rag_baseline",
                    "progress": i,
                    "total": total,
                    "current_question": question[:100],
                })

                try:
                    api_result = _call_osmosis_api(question, api_base, token_mgr, use_kg=False)
                    task_type = q_item.get("_task_type", "")
                    ground_truth = q_item.get("ground_truth", {})
                    category = q_item.get("category", "")

                    if task_type == "T2":
                        evaluation = evaluate_t2(api_result["answer"], api_result["sources_used"], ground_truth)
                        # LLM-juge T2 (meme juge que OSMOSIS)
                        if judge_client and api_result["answer"]:
                            claim1_text = ground_truth.get("claim1", {}).get("text", "")
                            claim2_text = ground_truth.get("claim2", {}).get("text", "")
                            llm_scores = _llm_judge_t2(
                                judge_client, question, claim1_text, claim2_text, api_result["answer"]
                            )
                            if llm_scores:
                                evaluation["keyword_both_sides"] = evaluation["both_sides_surfaced"]
                                evaluation["both_sides_surfaced"] = llm_scores["both_sides_surfaced"]
                    elif task_type == "T5":
                        if not category:
                            task_field = q_item.get("task", "")
                            if "cross_doc" in task_field:
                                category = "cross_doc_chain"
                            elif "proactive" in task_field:
                                category = "proactive_contradiction"
                            elif "multi_source" in task_field:
                                category = "multi_source_synthesis"
                        evaluation = evaluate_t5(api_result["answer"], api_result["sources_used"], ground_truth, q_item.get("grading_rules", {}), category)
                        # LLM-juge T5 (meme juge que OSMOSIS)
                        if judge_client and api_result["answer"] and category in ("cross_doc_chain", "multi_source_synthesis"):
                            llm_scores = _llm_judge_t5(
                                judge_client, question, category, api_result["answer"]
                            )
                            if llm_scores:
                                evaluation["keyword_chain_coverage"] = evaluation["chain_coverage"]
                                evaluation["chain_coverage"] = llm_scores["chain_coverage"]
                    else:
                        evaluation = {"task_type": "unknown"}

                    rag_per_sample.append({
                        "question_id": q_item.get("question_id", f"q_{i}"),
                        "question": question,
                        "answer": api_result["answer"],  # reponse complete
                        "answer_length": len(api_result["answer"]),
                        "sources_used": api_result["sources_used"],
                        "evaluation": evaluation,
                    })
                except Exception as e:
                    rag_errors += 1
                    rag_per_sample.append({
                        "question_id": q_item.get("question_id", f"q_{i}"),
                        "question": question[:200],
                        "evaluation": {"error": str(e)[:200]},
                    })

            rag_scores = aggregate_scores(rag_per_sample)
            logger.info(f"[T2T5:BENCH] RAG baseline scores: {rag_scores}")

        # ── Phase 4 : Report ──────────────────────────────────────────
        _update_redis_state(redis_url, {
            "status": "running",
            "profile": profile,
            "phase": "report",
            "progress": 0,
            "total": 1,
            "current_question": "Generating report...",
        })

        duration_s = round(time.time() - job_start, 1)
        ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        tag_suffix = f"_{tag}" if tag else ""
        report_filename = f"t2t5_run_{ts}{tag_suffix}.json"

        # Utiliser /data (volume Docker) si disponible, sinon chemin relatif (local)
        if Path("/data").exists():
            results_dir = Path("/data/benchmark/results")
        else:
            results_dir = Path("data/benchmark/results")
        results_dir.mkdir(parents=True, exist_ok=True)
        report_path = results_dir / report_filename

        synthesis_model = os.getenv("OSMOSIS_SYNTHESIS_MODEL", "")
        synthesis_provider = os.getenv("OSMOSIS_SYNTHESIS_PROVIDER", "anthropic")
        if not synthesis_model:
            synthesis_model = "claude-haiku-4-5-20251001" if synthesis_provider == "anthropic" else "gpt-4o-mini"

        report_data = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "profile": profile,
            "profile_label": prof["label"],
            "tag": tag or "",
            "judge_mode": judge_mode,
            "judge_model": LLM_JUDGE_MODEL if judge_client else None,
            "description": description or "",
            "synthesis_model": synthesis_model,
            "synthesis_provider": synthesis_provider,
            "duration_s": duration_s,
            "scores": osmosis_scores,
            "scores_rag": rag_scores,
            "per_sample": per_sample,
            "per_sample_rag": rag_per_sample,
            "errors": errors,
        }

        with open(report_path, "w", encoding="utf-8") as f:
            json.dump(report_data, f, indent=2, ensure_ascii=False)

        logger.info(f"[T2T5:BENCH] Report saved to {report_path}")

        # ── Termine ─────────────────────────────────────────────────
        _update_redis_state(redis_url, {
            "status": "completed",
            "profile": profile,
            "phase": "report",
            "progress": 1,
            "total": 1,
            "report_file": report_filename,
            "duration_s": duration_s,
            "scores": osmosis_scores,
            "scores_rag": rag_scores,
        })

        logger.info(
            f"[T2T5:BENCH] Benchmark completed in {duration_s}s — "
            f"OSMOSIS scores: {osmosis_scores}"
            + (f", RAG scores: {rag_scores}" if rag_scores else "")
        )

    except Exception as e:
        logger.error(f"[T2T5:BENCH] Benchmark job failed: {e}", exc_info=True)
        _update_redis_state(redis_url, {
            "status": "failed",
            "profile": profile,
            "error": str(e)[:500],
        })


# ═══════════════════════════════════════════════════════════════════════
# CLI Main
# ═══════════════════════════════════════════════════════════════════════


def main():
    parser = argparse.ArgumentParser(description="T2/T5 Diagnostic — Contradiction & Cross-Doc")
    parser.add_argument("--live", action="store_true", help="Mode live : interroger l'API")
    parser.add_argument(
        "--profile",
        default="standard",
        choices=list(T2T5_PROFILES.keys()),
        help="Profil de benchmark (quick/standard/full)",
    )
    parser.add_argument("--api", default="http://localhost:8000", help="URL API OSMOSIS")
    args = parser.parse_args()

    if not args.live:
        parser.error("--live requis (seul mode supporte actuellement)")

    # En mode CLI, on utilise le meme job mais sans Redis
    os.environ.setdefault("OSMOSIS_API_URL", args.api)
    run_benchmark_job(
        profile=args.profile,
        redis_url=os.getenv("REDIS_URL", "redis://localhost:6379/0"),
    )


if __name__ == "__main__":
    main()
