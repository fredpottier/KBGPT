# src/knowbase/perspectives/prompt_builder.py
"""
Construction du prompt structure pour le mode PERSPECTIVE.

Les Perspectives sont des briques d'assemblage — le prompt explicite
que le LLM est libre de les recomposer selon la question.
"""

from __future__ import annotations

import logging
from typing import Dict, List

from .models import ScoredPerspective

logger = logging.getLogger(__name__)

# Limites de complexite (ADR section 6e)
MAX_CLAIMS_PER_PERSPECTIVE = 8
MAX_HINTS = 3


# ---------------------------------------------------------------------------
# Hints de structuration (deterministes, sans LLM)
# ---------------------------------------------------------------------------

def derive_structuring_hints(
    question: str,
    perspectives: List[ScoredPerspective],
) -> List[str]:
    """
    Derive des indices de structuration a partir des metadonnees Perspectives.

    Pas d'appel LLM. Regles deterministes sur les metadonnees.
    """
    hints = []
    q_lower = question.lower()

    # Hint cross-version
    has_evolution = any(
        sp.perspective.evolution_summary
        or sp.perspective.added_claim_count > 0
        or sp.perspective.changed_claim_count > 0
        for sp in perspectives
    )
    if has_evolution:
        hints.append(
            "Certains elements ont evolue entre versions — "
            "distinguez ce qui est nouveau, modifie ou inchange."
        )

    # Hint tensions
    tension_perspectives = [sp for sp in perspectives if sp.perspective.tension_count > 0]
    if tension_perspectives:
        hints.append(
            "Des positions divergentes existent entre sources "
            "sur certains points — presentez-les explicitement."
        )

    # Hints question-dependants (forme, pas domaine)
    if any(w in q_lower for w in ["migr", "transition", "passage", "upgrade", "conversion"]):
        hints.append("Distinguez les prerequis, les changements de comportement et les impacts.")

    elif any(w in q_lower for w in ["compar", "difference", "vs", "entre", "versus"]):
        hints.append("Structurez autour des dimensions comparees, pas des sources.")

    elif any(w in q_lower for w in ["risque", "risk", "impact", "consequence", "probleme", "issue"]):
        hints.append("Distinguez les elements critiques des elements secondaires.")

    return hints[:MAX_HINTS]


# ---------------------------------------------------------------------------
# Prompt structure
# ---------------------------------------------------------------------------

def build_perspective_prompt(
    question: str,
    scored_perspectives: List[ScoredPerspective],
    hints: List[str],
) -> str:
    """
    Construit le markdown structure injecte dans graph_context_text.

    Les Perspectives sont presentees comme "matiere premiere" que le LLM
    est libre de restructurer selon la question.
    """
    if not scored_perspectives:
        return ""

    lines = []
    subject_names = set(sp.perspective.subject_name for sp in scored_perspectives if sp.perspective.subject_name)
    subject_label = ", ".join(subject_names) if subject_names else "le sujet"

    lines.append(f"## Axes thematiques identifies pour {subject_label}")
    lines.append("")

    for i, sp in enumerate(scored_perspectives, 1):
        p = sp.perspective

        # Header de l'axe
        meta_parts = []
        if p.claim_count:
            meta_parts.append(f"{p.claim_count} faits")
        if p.doc_count:
            meta_parts.append(f"{p.doc_count} sources")
        meta = f" ({', '.join(meta_parts)})" if meta_parts else ""

        lines.append(f"### Axe {i} : {p.label}{meta}")
        lines.append("")

        if p.description:
            lines.append(f"*{p.description}*")
            lines.append("")

        # Claims representatifs (top N)
        claims_to_show = p.representative_texts[:MAX_CLAIMS_PER_PERSPECTIVE]
        if claims_to_show:
            lines.append("**Faits cles :**")
            for claim_text in claims_to_show:
                lines.append(f"- {claim_text}")
            lines.append("")

        # Evolution (Phase 1B — vide pour l'instant, pret pour le futur)
        if p.evolution_summary:
            lines.append(f"**Evolution :** {p.evolution_summary}")
            lines.append("")

        # Tensions
        if p.tension_count > 0:
            lines.append(f"**Tensions :** {p.tension_count} divergence(s) detectee(s) entre sources.")
            lines.append("")

        lines.append("---")
        lines.append("")

    # Blind spots : sujets avec faible couverture
    low_coverage = [sp for sp in scored_perspectives if sp.perspective.coverage_ratio < 0.05]
    total_coverage = sum(sp.perspective.coverage_ratio for sp in scored_perspectives)
    if total_coverage < 0.7:
        lines.append("### Zones potentiellement non couvertes")
        lines.append(f"Les axes ci-dessus couvrent ~{total_coverage:.0%} des informations du corpus sur ce sujet.")
        lines.append("D'autres aspects peuvent exister dans le corpus mais n'ont pas ete retenus comme axes principaux.")
        lines.append("")

    # Hints de structuration
    if hints:
        lines.append("### Indices de structuration")
        for hint in hints:
            lines.append(f"- {hint}")
        lines.append("")

    return "\n".join(lines)
