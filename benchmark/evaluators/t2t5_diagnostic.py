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
# Configurable via env :
#   T2T5_JUDGE_PROVIDER = "openai" (defaut) ou "ollama"
#   T2T5_JUDGE_MODEL_NAME = "gpt-4o-mini" (defaut) ou "m-prometheus-14b"
LLM_JUDGE_PROVIDER = os.getenv("T2T5_JUDGE_PROVIDER", "openai")
LLM_JUDGE_MODEL = os.getenv("T2T5_JUDGE_MODEL_NAME", "gpt-4o-mini")


def _get_llm_judge():
    """Retourne un client OpenAI-compatible.

    Providers supportés (CH-30.15) :
    - "llamacpp" → Prometheus via http://prometheus-judge:8000 (DEFAUT pratique
      du docker-compose worker, modèle spécialisé judge m-prometheus-14b)
    - "ollama"   → Ollama local
    - "deepinfra" → DeepInfra Qwen2.5-72B (cloud)
    - "openai"   → gpt-4o-mini (legacy)
    """
    global _llm_judge_client, LLM_JUDGE_PROVIDER, LLM_JUDGE_MODEL
    if _llm_judge_client is not None:
        return _llm_judge_client

    LLM_JUDGE_PROVIDER = os.getenv("T2T5_JUDGE_PROVIDER", "openai")
    LLM_JUDGE_MODEL = os.getenv("T2T5_JUDGE_MODEL_NAME", "gpt-4o-mini")

    try:
        from openai import OpenAI

        if LLM_JUDGE_PROVIDER == "llamacpp":
            llamacpp_url = os.getenv("LLAMACPP_URL", "http://prometheus-judge:8000")
            _llm_judge_client = OpenAI(api_key="local", base_url=f"{llamacpp_url}/v1")
            logger.info(f"[T2T5] LLM judge initialized (llama.cpp/Prometheus: {LLM_JUDGE_MODEL} at {llamacpp_url})")
            return _llm_judge_client

        if LLM_JUDGE_PROVIDER == "ollama":
            ollama_url = os.getenv("OLLAMA_URL", "http://host.docker.internal:11434")
            _llm_judge_client = OpenAI(api_key="ollama", base_url=f"{ollama_url}/v1")
            logger.info(f"[T2T5] LLM judge initialized (Ollama: {LLM_JUDGE_MODEL} at {ollama_url})")
            return _llm_judge_client

        if LLM_JUDGE_PROVIDER == "deepinfra":
            di_key = os.environ.get("DEEPINFRA_API_KEY", "").strip()
            if not di_key:
                logger.warning("[T2T5] DEEPINFRA_API_KEY missing")
                return None
            _llm_judge_client = OpenAI(api_key=di_key, base_url="https://api.deepinfra.com/v1/openai")
            logger.info(f"[T2T5] LLM judge initialized (DeepInfra: {LLM_JUDGE_MODEL})")
            return _llm_judge_client

        # default openai
        api_key = os.environ.get("OPENAI_API_KEY", "")
        if not api_key:
            return None
        _llm_judge_client = OpenAI(api_key=api_key)
        logger.info(f"[T2T5] LLM judge initialized (OpenAI: {LLM_JUDGE_MODEL})")
        return _llm_judge_client
    except Exception as e:
        logger.warning(f"[T2T5] LLM judge unavailable: {e}")
        return None


def _llm_judge_t2(client, question: str, claim1_text: str, claim2_text: str, answer: str) -> dict | None:
    """LLM-juge evidence-based pour T2 : vérifie la couverture de chaque claim.

    Approche : le LLM extrait (YES/NO par claim), le code calcule le score.
    Plus stable et déterministe que le scoring 0-100 subjectif.
    """
    from benchmark.evaluators._judge_preprocess import preprocess_answer_for_judge
    judge_answer = preprocess_answer_for_judge(answer)
    MAX_JUDGE_CHARS = 3000

    prompt = (
        'You are verifying if a system answer covers specific claims from a document corpus.\n\n'
        f'Question asked: "{question[:200]}"\n\n'
        'CLAIMS THAT SHOULD BE COVERED:\n'
        f'- Claim 1: "{claim1_text[:200]}"\n'
        f'- Claim 2: "{claim2_text[:200]}"\n\n'
        f'SYSTEM ANSWER:\n"{judge_answer[:MAX_JUDGE_CHARS]}"\n\n'
        'For each item below, answer YES or NO:\n'
        '1. claim1_covered: Does the answer mention or paraphrase the content of Claim 1? '
        '(even in a different language, summarized, or with different wording)\n'
        '2. claim2_covered: Does the answer mention or paraphrase the content of Claim 2? '
        '(even in a different language, summarized, or with different wording)\n'
        '3. tension_acknowledged: Does the answer acknowledge a difference, divergence, '
        'tension, or contradiction between the two claims? '
        '(look for "however", "but", "cependant", "toutefois", "en revanche", "differs", "unlike")\n'
        '4. multiple_sources: Does the answer reference or cite 2+ different source documents?\n\n'
        'Reply with ONLY four answers (YES or NO) separated by commas.\n'
        'Example: YES,YES,YES,NO'
    )
    try:
        resp = client.chat.completions.create(
            model=LLM_JUDGE_MODEL,
            max_tokens=30, temperature=0.0,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = resp.choices[0].message.content.strip()
        # Parser YES/NO — prendre les 4 premiers tokens YES ou NO
        tokens = [t.strip().upper().rstrip(".,;") for t in raw.split(",")]
        bools = [t.startswith("YES") for t in tokens[:4]]

        if len(bools) >= 4:
            c1, c2, tension, sources = bools[0], bools[1], bools[2], bools[3]

            # Scoring déterministe basé sur la couverture
            claims_covered = sum([c1, c2])
            if claims_covered == 2:
                both_sides = 1.0
            elif claims_covered == 1:
                both_sides = 0.3  # partiel = pénalisé, pas 0.5
            else:
                both_sides = 0.0

            return {
                "both_sides_surfaced": both_sides,
                "tension_mentioned": 1.0 if tension else 0.0,
                "both_sources_cited": 1.0 if sources else 0.0,
                "claim1_coverage": 1.0 if c1 else 0.0,
                "claim2_coverage": 1.0 if c2 else 0.0,
                "judge_raw": raw,
                "judge_model": LLM_JUDGE_MODEL,
            }
    except Exception as e:
        logger.debug(f"[T2T5] LLM judge T2 error: {e}")
    return None


def _llm_judge_t5(client, question: str, category: str, answer: str, ground_truth: dict = None) -> dict | None:
    """LLM-juge evidence-based pour T5 : vérifie la couverture de chaque élément de la chain.

    Approche : le LLM vérifie YES/NO par claim de la chain, le code calcule la couverture.
    """
    from benchmark.evaluators._judge_preprocess import preprocess_answer_for_judge
    judge_answer = preprocess_answer_for_judge(answer)
    MAX_JUDGE_CHARS = 3000

    # Extraire les claims de la chain depuis le ground_truth
    chain = []
    if ground_truth:
        chain = ground_truth.get("chain", [])

    if chain:
        # Mode evidence-based : vérifier chaque claim de la chain
        claims_text = "\n".join(
            f'- Claim {i+1} (from {c.get("doc_id", "?")[:40]}): "{c.get("text", "")[:150]}"'
            for i, c in enumerate(chain)
        )
        checks = "\n".join(
            f'{i+1}. claim{i+1}_covered: Does the answer mention or paraphrase Claim {i+1}? (YES/NO)'
            for i in range(len(chain))
        )
        n_claims = len(chain)

        prompt = (
            'You are verifying if a system answer covers specific facts from multiple documents.\n\n'
            f'Question asked: "{question[:200]}"\n\n'
            f'CLAIMS THAT SHOULD BE COVERED (from {n_claims} different documents):\n'
            f'{claims_text}\n\n'
            f'SYSTEM ANSWER:\n"{judge_answer[:MAX_JUDGE_CHARS]}"\n\n'
            f'For each claim, answer YES or NO (is it covered in the answer, even paraphrased or in a different language?):\n'
            f'{checks}\n'
            f'{n_claims+1}. multiple_sources: Does the answer cite or reference 2+ different source documents? (YES/NO)\n\n'
            f'Reply with ONLY {n_claims+1} answers (YES or NO) separated by commas.\n'
            f'Example: {"YES," * n_claims}NO'
        )
    else:
        # Fallback : ancien prompt si pas de ground_truth
        prompt = (
            'You are a benchmark evaluator for a cross-document analysis system.\n\n'
            f'Question: "{question[:200]}"\nCategory: {category}\n\n'
            f'The system produced this answer:\n"{judge_answer[:MAX_JUDGE_CHARS]}"\n\n'
            'Rate each aspect from 0 to 100:\n'
            '1. chain_coverage: How well does the answer cover facts from multiple documents?\n'
            '2. multi_doc: Does the answer reference multiple source documents?\n\n'
            'Reply with ONLY two numbers (0-100) separated by commas.\nExample: 75,80'
        )

    try:
        resp = client.chat.completions.create(
            model=LLM_JUDGE_MODEL,
            max_tokens=30, temperature=0.0,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = resp.choices[0].message.content.strip()

        if chain:
            # Parser YES/NO evidence-based
            tokens = [t.strip().upper().rstrip(".,;") for t in raw.split(",")]
            bools = [t.startswith("YES") for t in tokens[:len(chain) + 1]]

            if len(bools) >= len(chain) + 1:
                claims_covered = sum(bools[:len(chain)])
                sources = bools[len(chain)]

                coverage = claims_covered / len(chain)

                return {
                    "chain_coverage": round(coverage, 3),
                    "multi_doc_cited": 1.0 if sources else 0.0,
                    "claims_covered": claims_covered,
                    "claims_total": len(chain),
                    "judge_raw": raw,
                    "judge_model": LLM_JUDGE_MODEL,
                }
        else:
            # Fallback : parser scores 0-100
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
        "label": "Quick T5 (30q)",
        "tasks": [
            {
                "name": "T5 Cross-doc",
                "questions_file": "benchmark/questions/aero_t5_cross_doc.json",
                "task_type": "T5",
            },
        ],
    },
    "standard": {
        "label": "Standard T2+T5 (70q)",
        "tasks": [
            {
                "name": "T2 Contradictions",
                "questions_file": "benchmark/questions/aero_t2_contradictions.json",
                "task_type": "T2",
            },
            {
                "name": "T5 Cross-doc",
                "questions_file": "benchmark/questions/aero_t5_cross_doc.json",
                "task_type": "T5",
            },
        ],
    },
    "full": {
        "label": "Full T2+T5 (70q)",
        "tasks": [
            {
                "name": "T2 Contradictions",
                "questions_file": "benchmark/questions/aero_t2_contradictions.json",
                "task_type": "T2",
            },
            {
                "name": "T5 Cross-doc",
                "questions_file": "benchmark/questions/aero_t5_cross_doc.json",
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
# Tension Detection Keywords — CH-12 externalisé vers config/detection_keywords.yaml
# ═══════════════════════════════════════════════════════════════════════

from knowbase.config.detection_keywords import get_detection_keywords as _get_dk

TENSION_KEYWORDS = list(_get_dk().tension_keywords)


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

    # CH-30.9 — supporte le format aero V2 (claim_a/claim_b) en plus du legacy (claim1/claim2)
    claim1 = ground_truth.get("claim1") or ground_truth.get("claim_a") or {}
    claim2 = ground_truth.get("claim2") or ground_truth.get("claim_b") or {}

    # 1. both_sides_surfaced — check keywords from both claims
    # Keywords: curated (si presentes) + extraites du texte
    c1_keywords = set(claim1.get("keywords", [])) | extract_keywords(claim1.get("text", ""))
    c2_keywords = set(claim2.get("keywords", [])) | extract_keywords(claim2.get("text", ""))

    c1_matched = c1_keywords & answer_words
    c2_matched = c2_keywords & answer_words

    c1_coverage = len(c1_matched) / len(c1_keywords) if c1_keywords else 0
    c2_coverage = len(c2_matched) / len(c2_keywords) if c2_keywords else 0

    # Seuil adaptatif : au moins 3 mots OU 40% de couverture (le plus permissif)
    # Evite de penaliser les claims longues (beaucoup de keywords = seuil % trop strict)
    c1_surfaced = len(c1_matched) >= 3 or c1_coverage >= 0.4
    c2_surfaced = len(c2_matched) >= 3 or c2_coverage >= 0.4

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


_CANONICAL_T5_CATEGORIES = ("cross_doc_chain", "proactive_contradiction", "multi_source_synthesis")


def _map_to_canonical_category(category: str, ground_truth: dict) -> str:
    """CH-30.9 — mappe une category aero V2 vers une des 3 canoniques (frontend hardcoded).

    Heuristique :
    - ground_truth.chain[] existe → cross_doc_chain
    - ground_truth.hidden_contradiction → proactive_contradiction
    - ground_truth.expected_aspects → multi_source_synthesis
    - sinon : fallback cross_doc_chain (cas le plus fréquent)
    """
    if category in _CANONICAL_T5_CATEGORIES:
        return category
    if isinstance(ground_truth.get("hidden_contradiction"), dict):
        return "proactive_contradiction"
    if isinstance(ground_truth.get("expected_aspects"), list) and ground_truth.get("expected_aspects"):
        return "multi_source_synthesis"
    if isinstance(ground_truth.get("chain"), list) and ground_truth.get("chain"):
        return "cross_doc_chain"
    return "cross_doc_chain"  # safe default


def evaluate_t5(
    answer: str,
    sources_used: list[str],
    ground_truth: dict,
    grading_rules: dict,
    category: str,
) -> dict[str, Any]:
    """Evalue une reponse T5 (KG differentiator) de maniere deterministe."""
    canonical_cat = _map_to_canonical_category(category, ground_truth)
    if not answer or len(answer) < 20:
        return {
            "chain_coverage": 0.0,
            "multi_doc_cited": 0.0,
            "proactive_detection": 0.0,
            "task_type": "T5",
            "category": canonical_cat,
            "original_category": category,
        }

    answer_norm = normalize(answer)
    answer_words = set(answer_norm.split())
    answer_lower = answer.lower()

    # CH-30.9 — domain-agnostic doc identification :
    # 1) legacy SAP : "027_SAP..." → prefix 3 chars numériques
    # 2) aero V2 : "cs25_amdt_28_32f1a9ac" → strip hash hex final, garder le rest
    def _doc_label(doc_id: str) -> str:
        if not doc_id:
            return ""
        d = doc_id.lower()
        # Strip hash hex final (>=6 chars hex, séparé par _)
        if "_" in d:
            tail = d.rsplit("_", 1)[-1]
            if len(tail) >= 6 and all(c in "0123456789abcdef" for c in tail):
                d = d[: -(len(tail) + 1)]
        return d

    unique_docs = set()
    for s in sources_used:
        if not s:
            continue
        label = _doc_label(s)
        if label:
            unique_docs.add(label)
        # Conserve aussi l'ancien matching par prefix numérique pour rétrocompat SAP
        if len(s) >= 3 and s[0].isdigit():
            unique_docs.add(s[:3])

    result: dict[str, Any] = {
        "task_type": "T5",
        "category": canonical_cat,
        "original_category": category,
    }

    # CH-30.9 — déclencher la logique chain dès qu'il y a un ground_truth.chain[]
    # (les catégories aero V2 sont diverses : evolution_chronological, cs25_provision_evolution,
    # lifecycle_chain_full, etc. — pas seulement "cross_doc_chain").
    has_chain = isinstance(ground_truth.get("chain"), list) and ground_truth.get("chain")
    if has_chain or category == "cross_doc_chain":
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

        # multi_doc_cited — CH-30.9 : matching par doc_label (sans hash) ou substring dans answer
        docs_required_min = ground_truth.get("docs_required") or ground_truth.get("min_docs_required", 2)
        required_docs: set[str] = set()
        for link in chain:
            if isinstance(link, dict):
                doc_id = link.get("doc_id", "")
                if doc_id:
                    label = _doc_label(doc_id)
                    if label:
                        required_docs.add(label)
                    if len(doc_id) >= 3 and doc_id[0].isdigit():
                        required_docs.add(doc_id[:3])

        docs_found: set[str] = set()
        for r in required_docs:
            if r in unique_docs:
                docs_found.add(r)
                continue
            # Sinon : substring match dans la réponse (cas où le système cite "cs25_amdt_28" inline)
            if r and r in answer_lower:
                docs_found.add(r)
                continue
            # Match partiel : si la moitié du label apparaît dans answer ou sources_used
            short = r.split("_")
            if len(short) >= 2:
                short_key = "_".join(short[:2])  # ex: "cs25_amdt", "dualuse_reg"
                if short_key in answer_lower or any(short_key in (s or "").lower() for s in sources_used):
                    docs_found.add(r)

        multi_doc = (
            len(docs_found) / len(required_docs)
            if required_docs
            else min(len(unique_docs) / max(docs_required_min, 1), 1.0)
        )

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
        result["both_sides_surfaced"] = 1.0 if (
            (len(c1_matched) >= 3 or c1_cov >= 0.4) and (len(c2_matched) >= 3 or c2_cov >= 0.4)
        ) else 0.0
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
    use_kg: bool = True,  # legacy param kept for callsite compat (ignored, V2 always)
) -> dict:
    """CH-30.14 — V2 only. Plus de fallback /api/search V1.1.

    Appelle exclusivement /api/runtime_v2/answer (pipeline anchor-driven avec
    insight_hints + entropy + answer_gap actifs).
    """
    headers = {
        "Authorization": f"Bearer {token_mgr.get()}",
        "Content-Type": "application/json",
    }
    resp = requests.post(
        f"{api_base}/api/runtime_v2/answer",
        json={"question": question, "audit_mode": False, "top_k_claims": 10},
        headers=headers,
        timeout=180,
    )
    resp.raise_for_status()
    data = resp.json()
    answer = data.get("synthesized_answer") or ""
    sources_used = list(data.get("authoritative_doc_ids") or [])
    if not sources_used:
        for c in data.get("claims") or []:
            doc = c.get("doc_id")
            if doc and doc not in sources_used:
                sources_used.append(doc)
    return {
        "answer": answer,
        "sources_used": sources_used,
        "chunks_retrieved": len(data.get("claims") or []),
        "latency_ms": 0,
        "_v2_meta": {
            "decision": data.get("decision"),
            "trust_score": data.get("trust_score"),
            "synthesis_entropy": data.get("synthesis_entropy"),
            "answer_gap_classification": data.get("answer_gap_classification"),
            "n_insight_hints": len(data.get("insight_hints") or []),
            "n_conflicts": len(data.get("conflicts") or []),
        },
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

        # ── Phase 2 : API calls + evaluation (parallelise) ─────────
        # Note: contrairement a RAGAS (collecte-first, eval-after), T2/T5
        # evalue chaque question immediatement apres l'appel API. En mode local,
        # cela cause un swap Ollama par question (synthese → juge → synthese).
        # Acceptable car Ollama swap automatiquement (~5-10s), et T2/T5 est
        # sequentiel par nature (1 question a la fois pour le juge).
        per_sample: list[dict] = []
        errors = 0

        # Retry judge init (Ollama peut mettre quelques secondes a charger le modele)
        judge_client = _get_llm_judge()
        if not judge_client:
            import time as _time
            logger.warning("[T2T5:BENCH] Judge unavailable on first try, retrying in 10s...")
            _time.sleep(10)
            _llm_judge_client = None  # Reset singleton pour retry
            judge_client = _get_llm_judge()

        judge_mode = "hybrid" if judge_client else "keyword"
        if not judge_client:
            logger.error("[T2T5:BENCH] ⚠️ LLM JUDGE UNAVAILABLE — falling back to keyword-only mode. Scores will be less accurate.")

        import threading
        from concurrent.futures import ThreadPoolExecutor, as_completed
        # Concurrence collecte : haute si synthese cloud (DeepInfra), basse si Ollama local
        # Concurrence juge : toujours 1 si Ollama (sequentiel)
        is_local_judge = os.getenv("T2T5_JUDGE_PROVIDER") == "ollama"
        collect_concurrency = int(os.getenv("BENCHMARK_COLLECT_CONCURRENCY", "15"))
        judge_concurrency = 1 if is_local_judge else int(os.getenv("BENCHMARK_CONCURRENCY", "15"))
        logger.info(f"[T2T5:BENCH] Evaluation mode: {judge_mode}, collect_concurrency: {collect_concurrency}, judge_concurrency: {judge_concurrency}")

        # ══════════════════════════════════════════════════════════════
        # COLLECTE-FIRST, EVAL-AFTER : toutes les collectes (synthese)
        # d'abord, puis toutes les evaluations (juge). Minimise les swaps
        # de modele Ollama en mode local (1 swap au lieu de 80).
        # ══════════════════════════════════════════════════════════════

        _progress_counter = [0]

        # ── Phase 2a : Collecte API + evaluation keyword (synthese) ──
        def _collect_and_keyword_eval(i, q_item):
            question = q_item.get("question", "")
            if not question:
                return None, False

            try:
                api_result = _call_osmosis_api(question, api_base, token_mgr)

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

                elif task_type == "T5":
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
                else:
                    evaluation = {"task_type": "unknown"}

                _progress_counter[0] += 1
                if _progress_counter[0] % 5 == 0 or _progress_counter[0] == total:
                    _update_redis_state(redis_url, {
                        "status": "running", "profile": profile,
                        "phase": "api_collect", "progress": _progress_counter[0],
                        "total": total, "current_question": question[:100],
                    })

                logger.info(
                    f"[T2T5:BENCH] [{_progress_counter[0]}/{total}] {q_item.get('question_id', '')} "
                    f"— {task_type} collected"
                )

                return {
                    "question_id": q_item.get("question_id", f"q_{i}"),
                    "question": question,
                    "task_name": q_item.get("_task_name", ""),
                    "evaluation": evaluation,
                    "answer": api_result["answer"],
                    "answer_length": len(api_result["answer"]),
                    "ground_truth": q_item.get("ground_truth", {}),
                    "chunks_retrieved": api_result["chunks_retrieved"],
                    "sources_used": api_result["sources_used"],
                    "latency_ms": api_result["latency_ms"],
                    "_task_type": task_type,
                    "_category": category,
                }, False

            except Exception as e:
                logger.warning(f"[T2T5:BENCH] Error on q={question[:60]}: {e}")
                return {
                    "question_id": q_item.get("question_id", f"q_{i}"),
                    "question": question[:200],
                    "task_name": q_item.get("_task_name", ""),
                    "evaluation": {"task_type": q_item.get("_task_type", ""), "error": str(e)[:200]},
                    "error": str(e)[:200],
                    "_task_type": q_item.get("_task_type", ""),
                    "_category": "",
                }, True

        logger.info(f"[T2T5:BENCH] Phase 2a: Collecting {total} answers (synthesis model)...")
        with ThreadPoolExecutor(max_workers=collect_concurrency) as executor:
            futures = {
                executor.submit(_collect_and_keyword_eval, i, q): i
                for i, q in enumerate(all_questions)
            }
            for future in as_completed(futures):
                result, is_error = future.result()
                if result is not None:
                    per_sample.append(result)
                    if is_error:
                        errors += 1

        logger.info(f"[T2T5:BENCH] Phase 2a complete: {len(per_sample)} samples collected")

        # ── Phase 2b : Evaluation LLM juge (1 seul swap Ollama ici) ──
        if judge_client:
            _update_redis_state(redis_url, {
                "status": "running", "profile": profile,
                "phase": "llm_judge", "progress": 0,
                "total": len(per_sample),
                "current_question": "LLM judge evaluation...",
            })
            logger.info(f"[T2T5:BENCH] Phase 2b: LLM judge on {len(per_sample)} samples (judge model: {LLM_JUDGE_MODEL})...")

            judged = 0
            for sample in per_sample:
                if sample.get("error"):
                    continue

                task_type = sample.get("_task_type", "")
                evaluation = sample["evaluation"]
                answer = sample.get("answer", "")
                question = sample.get("question", "")
                ground_truth = sample.get("ground_truth", {})
                category = sample.get("_category", "")

                if not answer:
                    continue

                # CH-30.15 — V2 calibration : LLM-juge Prometheus override systématiquement
                # le keyword scorer (qui pénalise les réponses V2 concises).
                # Compat double : claim1/claim2 (legacy SAP) + claim_a/claim_b (aero V2).
                if task_type == "T2":
                    c1 = ground_truth.get("claim1") or ground_truth.get("claim_a") or {}
                    c2 = ground_truth.get("claim2") or ground_truth.get("claim_b") or {}
                    claim1_text = c1.get("text", "") if isinstance(c1, dict) else str(c1)
                    claim2_text = c2.get("text", "") if isinstance(c2, dict) else str(c2)
                    llm_scores = _llm_judge_t2(
                        judge_client, question, claim1_text, claim2_text, answer
                    )
                    if llm_scores:
                        # Préserver la version keyword pour comparaison/audit
                        evaluation["keyword_both_sides"] = evaluation.get("both_sides_surfaced")
                        evaluation["keyword_tension"] = evaluation.get("tension_mentioned")
                        evaluation["keyword_both_sources"] = evaluation.get("both_sources_cited")
                        # Override avec scores LLM-juge (3 métriques T2)
                        evaluation["both_sides_surfaced"] = llm_scores["both_sides_surfaced"]
                        evaluation["tension_mentioned"] = llm_scores["tension_mentioned"]
                        evaluation["both_sources_cited"] = llm_scores["both_sources_cited"]
                        evaluation["claim1_coverage"] = llm_scores.get("claim1_coverage", 0.0)
                        evaluation["claim2_coverage"] = llm_scores.get("claim2_coverage", 0.0)
                        evaluation["judge_model"] = LLM_JUDGE_MODEL

                elif task_type == "T5":
                    # CH-30.15 — déclencher LLM-juge dès qu'il y a une chain[]
                    # (mes 30 questions aero T5 ont toutes une chain[], catégories diverses)
                    has_chain = isinstance(ground_truth.get("chain"), list) and ground_truth.get("chain")
                    if has_chain or category in ("cross_doc_chain", "multi_source_synthesis"):
                        llm_scores = _llm_judge_t5(
                            judge_client, question, category, answer,
                            ground_truth=ground_truth,
                        )
                        if llm_scores:
                            evaluation["keyword_chain_coverage"] = evaluation.get("chain_coverage")
                            evaluation["keyword_multi_doc_cited"] = evaluation.get("multi_doc_cited")
                            evaluation["chain_coverage"] = llm_scores["chain_coverage"]
                            if "multi_doc_cited" in llm_scores:
                                evaluation["multi_doc_cited"] = llm_scores["multi_doc_cited"]
                            evaluation["judge_model"] = LLM_JUDGE_MODEL

                judged += 1
                if judged % 10 == 0:
                    _update_redis_state(redis_url, {
                        "status": "running", "profile": profile,
                        "phase": "llm_judge", "progress": judged,
                        "total": len(per_sample),
                    })
                    logger.info(f"[T2T5:BENCH] Judge progress: {judged}/{len(per_sample)}")

            logger.info(f"[T2T5:BENCH] Phase 2b complete: {judged} samples judged")

        # Cleanup temp fields
        for sample in per_sample:
            sample.pop("_task_type", None)
            sample.pop("_category", None)

        per_sample.sort(key=lambda s: s.get("question_id", ""))

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

        # V2 config snapshot (reproductibilite benchmark)
        config_snapshot = None
        try:
            from knowbase.common.llm_config import get_usage_config_store
            config_snapshot = get_usage_config_store().snapshot()
        except Exception:
            pass

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
            "config_snapshot": config_snapshot,
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
