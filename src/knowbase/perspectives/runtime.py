# src/knowbase/perspectives/runtime.py
"""
Point d'entree unique pour l'injection du contexte PERSPECTIVE dans search.py.

Contrairement aux versions precedentes, ce module ne fait PLUS de decision
ni de pre-gate lexical/heuristique. La decision est prise en amont dans
strategy_analyzer.py via un LLM informe par la topologie des preuves.

Role du runtime :
- Recevoir des Perspectives deja chargees et scorees
- Construire le prompt structure (markdown avec axes thematiques, tensions, hints)
- Loguer l'instrumentation

AUCUNE heuristique lexicale, AUCUNE liste de mots, AUCUN pattern domaine.
Domain-agnostic et multilingue par construction.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Tuple

from .models import ScoredPerspective
from .prompt_builder import build_perspective_prompt, derive_structuring_hints
from .scorer import select_perspectives

logger = logging.getLogger(__name__)


def assemble_perspective_context(
    question: str,
    scored_perspectives: List[ScoredPerspective],
    subject_ids: List[str],
    subject_resolution_mode: str = "single",
) -> Tuple[str, Dict[str, Any]]:
    """
    Point d'entree unique de l'injection du contexte PERSPECTIVE.

    Cette fonction ne decide plus rien : elle recoit des Perspectives
    deja chargees et scorees par le pipeline amont (signal_policy via
    strategy_analyzer), et construit le markdown a injecter.

    Args:
        question: Question utilisateur (pour les hints)
        scored_perspectives: Perspectives deja chargees et scorees
        subject_ids: IDs des sujets resolus (pour la metadata)
        subject_resolution_mode: mode de resolution (single|multi|fallback)

    Returns:
        (graph_context_text, metadata)
    """
    metadata: Dict[str, Any] = {
        "mode": "PERSPECTIVE",
        "activated": False,
        "subject_ids": subject_ids,
        "subject_resolution_mode": subject_resolution_mode,
        "perspectives_loaded": len(scored_perspectives),
        "perspectives_selected": 0,
        "claims_injected": 0,
        "hints": [],
        "fallback_reason": None,
    }

    if not scored_perspectives or len(scored_perspectives) < 2:
        metadata["fallback_reason"] = (
            f"too_few_perspectives ({len(scored_perspectives)})"
        )
        logger.info(
            f"[PERSPECTIVE:ASSEMBLE] Insufficient perspectives "
            f"({len(scored_perspectives)} < 2), returning empty context"
        )
        return "", metadata

    # Selection finale (toutes les Perspectives sont deja scorees et triees)
    selected = select_perspectives(scored_perspectives, min_count=2, max_count=5)
    metadata["perspectives_selected"] = len(selected)

    if len(selected) < 2:
        metadata["fallback_reason"] = f"too_few_selected ({len(selected)})"
        logger.info(
            f"[PERSPECTIVE:ASSEMBLE] Too few selected ({len(selected)} < 2), "
            f"returning empty context"
        )
        return "", metadata

    # Hints de structuration (derives des metadonnees des Perspectives)
    hints = derive_structuring_hints(question, selected)
    metadata["hints"] = hints

    # Build prompt
    graph_context_text = build_perspective_prompt(question, selected, hints)
    metadata["activated"] = True
    metadata["claims_injected"] = sum(
        len(sp.perspective.representative_texts[:8]) for sp in selected
    )

    logger.info(
        f"[PERSPECTIVE:ASSEMBLE] {len(selected)} perspectives, "
        f"{metadata['claims_injected']} claims injectes, "
        f"{len(hints)} hints"
    )
    for sp in selected:
        logger.info(
            f"  [{sp.perspective.label}] score={sp.relevance_score:.3f} "
            f"(semantic={sp.semantic_score:.3f})"
        )

    return graph_context_text, metadata
