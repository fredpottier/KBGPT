# src/knowbase/perspectives/runtime.py
"""
Point d'entree unique du mode PERSPECTIVE pour search.py.

search.py ne fait qu'appeler assemble_perspective_context().
Toute la logique (resolution sujets, chargement, scoring, selection,
hints, prompt) est encapsulee ici.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Tuple

from .models import ScoredPerspective
from .prompt_builder import build_perspective_prompt, derive_structuring_hints
from .scorer import (
    load_perspectives,
    resolve_subject_ids_from_claims,
    score_perspectives,
    select_perspectives,
)

logger = logging.getLogger(__name__)


def should_activate_perspectives(
    question: str,
    kg_claim_results: List[Dict],
    reranked_chunks: List[Dict],
) -> bool:
    """
    Detecte si la question est ouverte/panoramique et merite le mode PERSPECTIVE.

    Heuristique composite :
    - Patterns linguistiques ouverts (cross-domain)
    - Dispersion des facets dans les chunks (facet_diversity >= 4)
    """
    q_lower = question.lower()

    # Patterns linguistiques cross-domain
    open_patterns = [
        "qu'apporte", "que propose", "quoi de neuf", "what's new", "what is new",
        "vue d'ensemble", "vue d ensemble", "overview", "resume", "summary",
        "quels sont les", "what are the", "decrivez", "describe", "expliquez",
        "differences entre", "compare", "evolution", "changements",
        "tout savoir sur", "tell me about", "parlez-moi de",
        "points cles", "key points", "principales", "main features",
    ]
    has_open_pattern = any(p in q_lower for p in open_patterns)

    # Facet diversity : compter les facets distinctes dans les claims KG
    facet_ids = set()
    for claim in (kg_claim_results or []):
        for fid in claim.get("facet_ids", []):
            facet_ids.add(fid)
    facet_diversity = len(facet_ids)

    activated = facet_diversity >= 4 or has_open_pattern

    logger.info(
        f"[PERSPECTIVE:DETECT] question='{question[:60]}...', "
        f"facet_diversity={facet_diversity}, has_open_pattern={has_open_pattern}, "
        f"activated={activated}"
    )
    return activated


def assemble_perspective_context(
    question: str,
    question_embedding: List[float],
    kg_claim_results: List[Dict],
    reranked_chunks: List[Dict],
    tenant_id: str,
) -> Tuple[str, Dict[str, Any]]:
    """
    Point d'entree unique du mode PERSPECTIVE.

    Encapsule : resolution sujets -> chargement Perspectives -> scoring ->
    selection -> hints -> build prompt.

    Args:
        question: Question utilisateur
        question_embedding: Embedding de la question
        kg_claim_results: Claims KG recuperes en Phase A
        reranked_chunks: Chunks apres reranking
        tenant_id: Tenant ID

    Returns:
        (graph_context_text, metadata)
        metadata contient les infos pour l'instrumentation et le frontend.
    """
    metadata: Dict[str, Any] = {
        "mode": "PERSPECTIVE",
        "activated": False,
        "subject_ids": [],
        "subject_resolution_mode": "fallback",
        "perspectives_loaded": 0,
        "perspectives_selected": 0,
        "claims_injected": 0,
        "hints": [],
        "fallback_reason": None,
    }

    # 1. Resoudre les subject_ids
    subject_ids, resolution_mode = resolve_subject_ids_from_claims(
        kg_claim_results, tenant_id
    )
    metadata["subject_ids"] = subject_ids
    metadata["subject_resolution_mode"] = resolution_mode

    if not subject_ids:
        metadata["fallback_reason"] = "no_subject_resolved"
        logger.info("[PERSPECTIVE:FALLBACK] Aucun sujet resolu")
        return "", metadata

    # 2. Charger les Perspectives
    perspectives = load_perspectives(subject_ids, tenant_id)
    metadata["perspectives_loaded"] = len(perspectives)

    if len(perspectives) < 2:
        metadata["fallback_reason"] = f"too_few_perspectives ({len(perspectives)})"
        logger.info(f"[PERSPECTIVE:FALLBACK] {len(perspectives)} perspectives < 2")
        return "", metadata

    # 3. Scorer et selectionner
    scored = score_perspectives(question_embedding, question, perspectives)
    selected = select_perspectives(scored, min_count=3, max_count=5)
    metadata["perspectives_selected"] = len(selected)

    if len(selected) < 2:
        metadata["fallback_reason"] = f"too_few_selected ({len(selected)})"
        logger.info(f"[PERSPECTIVE:FALLBACK] {len(selected)} selected < 2")
        return "", metadata

    # 4. Verifier la couverture
    total_coverage = sum(sp.perspective.coverage_ratio for sp in selected)
    if total_coverage < 0.3:
        metadata["fallback_reason"] = f"low_coverage ({total_coverage:.1%})"
        logger.info(f"[PERSPECTIVE:FALLBACK] coverage {total_coverage:.1%} < 30%")
        return "", metadata

    # 5. Hints de structuration
    hints = derive_structuring_hints(question, selected)
    metadata["hints"] = hints

    # 6. Build prompt
    graph_context_text = build_perspective_prompt(question, selected, hints)
    metadata["activated"] = True
    metadata["claims_injected"] = sum(
        len(sp.perspective.representative_texts[:8]) for sp in selected
    )

    logger.info(
        f"[PERSPECTIVE:SELECT] {len(selected)} perspectives, "
        f"{metadata['claims_injected']} claims injectes, "
        f"{len(hints)} hints, coverage={total_coverage:.1%}"
    )
    for sp in selected:
        logger.info(
            f"  [{sp.perspective.label}] score={sp.relevance_score:.3f} "
            f"(semantic={sp.semantic_score:.3f}, kw_overlap={sp.keyword_overlap})"
        )

    return graph_context_text, metadata
