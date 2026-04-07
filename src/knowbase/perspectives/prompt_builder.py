# src/knowbase/perspectives/prompt_builder.py
"""
Construction du prompt structure pour le mode PERSPECTIVE V2 (theme-scoped).

Les Perspectives sont des briques d'assemblage thematiques transversales —
le prompt explicite que le LLM est libre de les recomposer selon la question.
"""

from __future__ import annotations

import logging
from typing import List

from .models import ScoredPerspective

logger = logging.getLogger(__name__)

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
    structurelles des Perspectives. Pas de listes de mots, pas de patterns
    lexicaux. Multilingue et domain-agnostic par construction.

    Hints en anglais (langue neutre) — le LLM de synthese les reformule.

    IMPORTANT (Phase B7) : les hints sont calcules sur les CLAIMS RELLEMENT
    INJECTES (reranked_claims si disponibles), pas sur les metadonnees globales
    des Perspectives. Cela evite les faux positifs (ex: signaler une tension
    qui existe dans la Perspective complete mais pas dans les claims selectionnes
    pour cette question).
    """
    hints = []

    # Hint cross-version (sur metadonnees globales — vrai signal de la perspective)
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

    # Hint tensions : seulement si plusieurs Perspectives selectionnees
    # ont des tensions ET qu'elles sont les Perspectives DOMINANTES (top 2-3).
    # Ne plus declencher sur une seule Perspective avec tension_count > 0
    # car le rerank peut ne pas avoir injecte les claims en tension.
    tension_perspectives = [
        sp for sp in perspectives[:3]  # top 3 seulement
        if sp.perspective.tension_count >= 5  # seuil minimal eleve
    ]
    if len(tension_perspectives) >= 2:
        hints.append(
            "Multiple selected axes contain known divergences between sources — "
            "if the cited facts show conflicting positions, present them explicitly."
        )

    # Hint cross-subject : si les Perspectives selectionnees touchent
    # plusieurs sujets distincts, signaler la dimension cross-doc
    all_subjects = set()
    for sp in perspectives:
        all_subjects.update(sp.perspective.linked_subject_names or [])
    if len(all_subjects) >= 2:
        subjects_str = ", ".join(sorted(all_subjects)[:3])
        hints.append(
            f"The selected axes span multiple subjects ({subjects_str}). "
            f"Highlight commonalities and differences across them."
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

    Les Perspectives sont presentees comme "matiere premiere" thematique
    transversale. Chaque axe peut toucher plusieurs sujets/documents.
    """
    if not scored_perspectives:
        return ""

    lines = []
    lines.append("## Thematic axes identified")
    lines.append("")
    lines.append(
        "*Each axis is a transversal theme that may span multiple subjects "
        "and documents. Use them as raw material to compose your answer.*"
    )
    lines.append("")

    for i, sp in enumerate(scored_perspectives, 1):
        p = sp.perspective

        # Header de l'axe : label + meta
        meta_parts = []
        if p.claim_count:
            meta_parts.append(f"{p.claim_count} facts")
        if p.doc_count:
            meta_parts.append(f"{p.doc_count} documents")
        if p.linked_subject_names:
            n_subjects = len(p.linked_subject_names)
            meta_parts.append(f"{n_subjects} subject{'s' if n_subjects > 1 else ''}")
        meta = f" ({', '.join(meta_parts)})" if meta_parts else ""

        lines.append(f"### Axis {i}: {p.label}{meta}")
        lines.append("")

        if p.description:
            lines.append(f"*{p.description}*")
            lines.append("")

        # Subjects touches (info utile pour les questions cross-subject)
        if p.linked_subject_names:
            subjects_str = ", ".join(p.linked_subject_names[:5])
            lines.append(f"**Subjects covered:** {subjects_str}")
            lines.append("")

        # Claims a injecter : reranked si disponibles (Phase B6),
        # sinon representative_texts figes au build (fallback)
        # Format des doc_id : on utilise [[doc:ID]] pour que le LLM
        # produise des citations propres sans dupliquer "source"
        if sp.reranked_claims:
            claims_with_meta = sp.reranked_claims[:MAX_CLAIMS_PER_PERSPECTIVE]
            if claims_with_meta:
                lines.append("**Key facts (most relevant to the question):**")
                for c in claims_with_meta:
                    text = c.get("text", "")[:300]
                    doc_id = c.get("doc_id", "")
                    if doc_id:
                        # Format avec balise [[doc:ID]] que le LLM convertira
                        # en citation propre selon les regles du prompt de synthese
                        lines.append(f"- {text} [[doc:{doc_id}]]")
                    else:
                        lines.append(f"- {text}")
                lines.append("")
        else:
            # Fallback : claims representatifs figes au build
            claims_to_show = p.representative_texts[:MAX_CLAIMS_PER_PERSPECTIVE]
            if claims_to_show:
                lines.append("**Key facts:**")
                for claim_text in claims_to_show:
                    lines.append(f"- {claim_text}")
                lines.append("")

        # Evolution (Phase 1B — vide pour l'instant)
        if p.evolution_summary:
            lines.append(f"**Evolution:** {p.evolution_summary}")
            lines.append("")

        # Tensions
        if p.tension_count > 0:
            lines.append(
                f"**Tensions:** {p.tension_count} divergence(s) detected between sources."
            )
            lines.append("")

        lines.append("---")
        lines.append("")

    # Hints de structuration
    if hints:
        lines.append("### Structuring hints")
        for hint in hints:
            lines.append(f"- {hint}")
        lines.append("")

    return "\n".join(lines)
