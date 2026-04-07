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
    Derive des indices de structuration UNIQUEMENT a partir des metadonnees
    structurelles des Perspectives (pas de la question).

    Pas d'appel LLM, pas de listes de mots, pas de patterns lexicaux.
    Multilingue et domain-agnostic par construction.

    Les hints sont en anglais (langue neutre) — le LLM de synthese les
    reformulera dans la langue de la question.
    """
    hints = []

    # Hint cross-version (signal structurel : evolution_summary ou claim diffs)
    has_evolution = any(
        sp.perspective.evolution_summary
        or sp.perspective.added_claim_count > 0
        or sp.perspective.changed_claim_count > 0
        for sp in perspectives
    )
    if has_evolution:
        hints.append(
            "Some elements have evolved across versions — "
            "distinguish what is new, modified, or unchanged."
        )

    # Hint tensions (signal structurel : tension_count > 0)
    tension_perspectives = [sp for sp in perspectives if sp.perspective.tension_count > 0]
    if tension_perspectives:
        hints.append(
            "Divergent positions exist between sources on some points — "
            "present them explicitly."
        )

    # Hint dispersion : si les axes selectionnes ont des coverage_ratio
    # tres heterogenes, c'est qu'un axe domine — signaler la hierarchie.
    if len(perspectives) >= 2:
        coverages = sorted([sp.perspective.coverage_ratio for sp in perspectives], reverse=True)
        if coverages[0] > 0 and coverages[0] > 2 * coverages[-1]:
            hints.append(
                "Coverage is uneven across the identified axes — "
                "prioritize the most representative ones."
            )

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

    # Le prompt structurel est ecrit en anglais (langue neutre).
    # Le LLM de synthese le reformule automatiquement dans la langue de la question.
    lines = []
    subject_names = set(sp.perspective.subject_name for sp in scored_perspectives if sp.perspective.subject_name)
    subject_label = ", ".join(subject_names) if subject_names else "the topic"

    lines.append(f"## Thematic axes identified for {subject_label}")
    lines.append("")

    for i, sp in enumerate(scored_perspectives, 1):
        p = sp.perspective

        # Header de l'axe
        meta_parts = []
        if p.claim_count:
            meta_parts.append(f"{p.claim_count} facts")
        if p.doc_count:
            meta_parts.append(f"{p.doc_count} sources")
        meta = f" ({', '.join(meta_parts)})" if meta_parts else ""

        lines.append(f"### Axis {i}: {p.label}{meta}")
        lines.append("")

        if p.description:
            lines.append(f"*{p.description}*")
            lines.append("")

        # Claims representatifs (top N) — preserves dans leur langue d'origine
        claims_to_show = p.representative_texts[:MAX_CLAIMS_PER_PERSPECTIVE]
        if claims_to_show:
            lines.append("**Key facts:**")
            for claim_text in claims_to_show:
                lines.append(f"- {claim_text}")
            lines.append("")

        # Evolution (Phase 1B — vide pour l'instant, pret pour le futur)
        if p.evolution_summary:
            lines.append(f"**Evolution:** {p.evolution_summary}")
            lines.append("")

        # Tensions
        if p.tension_count > 0:
            lines.append(f"**Tensions:** {p.tension_count} divergence(s) detected between sources.")
            lines.append("")

        lines.append("---")
        lines.append("")

    # Blind spots : signal structurel sur la couverture
    total_coverage = sum(sp.perspective.coverage_ratio for sp in scored_perspectives)
    if total_coverage < 0.7:
        lines.append("### Potentially uncovered areas")
        lines.append(f"The axes above cover ~{total_coverage:.0%} of corpus information on this topic.")
        lines.append("Other aspects may exist in the corpus but were not retained as primary axes.")
        lines.append("")

    # Hints de structuration
    if hints:
        lines.append("### Structuring hints")
        for hint in hints:
            lines.append(f"- {hint}")
        lines.append("")

    return "\n".join(lines)
