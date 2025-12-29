"""
OSMOSE Vision Gating - Décision intelligente Vision vs Text-Only

Réduit les appels Vision de 40-60% en détectant les slides "triviales"
qui ne nécessitent pas d'analyse visuelle (titre, merci, Q&A, texte suffisant).

Règles de gating:
1. Slide triviale (titre, merci, agenda) → SKIP Vision
2. Slide avec beaucoup de texte (>500 chars) → SKIP Vision (texte suffit)
3. Slide presque vide (<30 chars) mais avec image → NEED Vision
4. Slide avec schéma/graphique probable → NEED Vision

Author: OSMOSE Burst Ingestion
Date: 2025-12
"""

import re
import logging
from typing import Dict, Any, Tuple
from dataclasses import dataclass
from enum import Enum

logger = logging.getLogger(__name__)


class VisionDecision(Enum):
    """Décision de gating Vision."""
    SKIP = "skip"      # Pas besoin de Vision, texte suffit
    REQUIRED = "required"  # Vision nécessaire (schéma, image complexe)
    OPTIONAL = "optional"  # Cas limite, Vision recommandée mais pas critique


@dataclass
class GatingResult:
    """Résultat du gating avec justification."""
    decision: VisionDecision
    reason: str
    text_richness_score: float  # 0-1, plus c'est haut plus le texte est riche
    visual_complexity_hint: float  # 0-1, estimation complexité visuelle


# Patterns de slides triviales (multi-langue)
TRIVIAL_PATTERNS = [
    # Français
    r"^merci\b",
    r"^questions\s*\??$",
    r"^q\s*&\s*a\s*\??$",
    r"^agenda\b",
    r"^sommaire\b",
    r"^table\s+des\s+mati[eè]res",
    r"^introduction\s*$",
    r"^conclusion\s*$",
    r"^contacts?\s*$",
    r"^coordonn[ée]es\s*$",
    # English
    r"^thank\s+you\b",
    r"^thanks\b",
    r"^questions\s*\??$",
    r"^q\s*&\s*a\s*\??$",
    r"^agenda\b",
    r"^table\s+of\s+contents",
    r"^introduction\s*$",
    r"^conclusion\s*$",
    r"^contact\s*(us)?\s*$",
    r"^appendix\b",
    r"^backup\s+slides?\b",
    # German
    r"^danke\b",
    r"^vielen\s+dank\b",
    r"^fragen\s*\??$",
    r"^inhalt\s*$",
    r"^einleitung\s*$",
]

# Patterns suggérant un contenu visuel complexe
VISUAL_COMPLEXITY_PATTERNS = [
    r"architecture",
    r"diagram",
    r"workflow",
    r"process\s+flow",
    r"organi[sz]ation",
    r"timeline",
    r"roadmap",
    r"schema",
    r"schéma",
    r"integration",
    r"landscape",
    r"overview",
    r"infographic",
    r"chart",
    r"graph",
    r"matrix",
    r"comparison",
    r"versus|vs\.",
]


def should_use_vision(
    slide_text: str,
    slide_notes: str = "",
    slide_index: int = 0,
    has_shapes: bool = False,
    has_images: bool = False,
    has_charts: bool = False,
    min_text_threshold: int = 500,
    max_empty_threshold: int = 30,
) -> GatingResult:
    """
    Détermine si une slide nécessite une analyse Vision.

    Args:
        slide_text: Texte extrait de la slide
        slide_notes: Notes du présentateur
        slide_index: Index de la slide (pour logging)
        has_shapes: La slide contient-elle des formes/schémas?
        has_images: La slide contient-elle des images?
        has_charts: La slide contient-elle des graphiques?
        min_text_threshold: Seuil de texte "suffisant" (défaut: 500 chars)
        max_empty_threshold: Seuil de texte "vide" (défaut: 30 chars)

    Returns:
        GatingResult avec décision et justification
    """
    combined_text = f"{slide_text} {slide_notes}".strip().lower()
    text_length = len(combined_text)

    # Calculer scores
    text_richness = min(1.0, text_length / min_text_threshold)
    visual_complexity = 0.0

    # === Règle 1: Slides triviales (titre, merci, Q&A) ===
    for pattern in TRIVIAL_PATTERNS:
        if re.search(pattern, combined_text, re.IGNORECASE):
            logger.debug(f"Slide {slide_index}: SKIP Vision (trivial pattern: {pattern})")
            return GatingResult(
                decision=VisionDecision.SKIP,
                reason=f"Trivial slide (pattern: {pattern})",
                text_richness_score=text_richness,
                visual_complexity_hint=0.1
            )

    # === Règle 2: Slide vide mais avec visuels ===
    if text_length < max_empty_threshold:
        if has_images or has_charts or has_shapes:
            logger.debug(f"Slide {slide_index}: REQUIRED Vision (empty text but has visuals)")
            return GatingResult(
                decision=VisionDecision.REQUIRED,
                reason="Empty text but contains visual elements",
                text_richness_score=0.0,
                visual_complexity_hint=0.9
            )
        else:
            # Slide vraiment vide, skip
            logger.debug(f"Slide {slide_index}: SKIP Vision (empty slide)")
            return GatingResult(
                decision=VisionDecision.SKIP,
                reason="Empty slide",
                text_richness_score=0.0,
                visual_complexity_hint=0.0
            )

    # === Règle 3: Beaucoup de texte = pas besoin de Vision ===
    if text_length > min_text_threshold:
        # Vérifier si le texte suggère des visuels complexes
        has_visual_keywords = any(
            re.search(p, combined_text, re.IGNORECASE)
            for p in VISUAL_COMPLEXITY_PATTERNS
        )

        if has_visual_keywords and (has_shapes or has_images or has_charts):
            # Texte riche MAIS parle de schémas/architecture → Vision utile
            visual_complexity = 0.7
            logger.debug(f"Slide {slide_index}: OPTIONAL Vision (rich text but visual keywords)")
            return GatingResult(
                decision=VisionDecision.OPTIONAL,
                reason="Rich text but references visual content",
                text_richness_score=text_richness,
                visual_complexity_hint=visual_complexity
            )

        # Texte riche, pas de visuels complexes → skip
        logger.debug(f"Slide {slide_index}: SKIP Vision (text sufficient: {text_length} chars)")
        return GatingResult(
            decision=VisionDecision.SKIP,
            reason=f"Text sufficient ({text_length} chars > {min_text_threshold})",
            text_richness_score=text_richness,
            visual_complexity_hint=0.2
        )

    # === Règle 4: Slides intermédiaires ===
    # Texte modéré (30-500 chars), check si visuels complexes probables

    # Détecter indices de complexité visuelle
    visual_keyword_count = sum(
        1 for p in VISUAL_COMPLEXITY_PATTERNS
        if re.search(p, combined_text, re.IGNORECASE)
    )
    visual_complexity = min(1.0, visual_keyword_count * 0.3)

    if has_charts:
        visual_complexity = max(visual_complexity, 0.9)
    if has_shapes and visual_keyword_count > 0:
        visual_complexity = max(visual_complexity, 0.7)
    if has_images:
        visual_complexity = max(visual_complexity, 0.5)

    # Décision basée sur complexité
    if visual_complexity >= 0.7:
        logger.debug(f"Slide {slide_index}: REQUIRED Vision (visual complexity: {visual_complexity:.2f})")
        return GatingResult(
            decision=VisionDecision.REQUIRED,
            reason=f"High visual complexity ({visual_complexity:.2f})",
            text_richness_score=text_richness,
            visual_complexity_hint=visual_complexity
        )
    elif visual_complexity >= 0.4:
        logger.debug(f"Slide {slide_index}: OPTIONAL Vision (moderate complexity: {visual_complexity:.2f})")
        return GatingResult(
            decision=VisionDecision.OPTIONAL,
            reason=f"Moderate visual complexity ({visual_complexity:.2f})",
            text_richness_score=text_richness,
            visual_complexity_hint=visual_complexity
        )
    else:
        # Peu de texte, peu de visuels → utiliser texte
        logger.debug(f"Slide {slide_index}: SKIP Vision (low complexity: {visual_complexity:.2f})")
        return GatingResult(
            decision=VisionDecision.SKIP,
            reason="Low visual complexity, text sufficient",
            text_richness_score=text_richness,
            visual_complexity_hint=visual_complexity
        )


def estimate_vision_savings(
    slides_data: list,
    include_optional: bool = False
) -> Dict[str, Any]:
    """
    Estime les économies de gating sur un deck.

    Args:
        slides_data: Liste des slides avec text, notes, etc.
        include_optional: Inclure les OPTIONAL dans les appels Vision?

    Returns:
        Dict avec statistiques d'économie
    """
    total = len(slides_data)
    skip_count = 0
    required_count = 0
    optional_count = 0

    for slide in slides_data:
        result = should_use_vision(
            slide_text=slide.get("text", ""),
            slide_notes=slide.get("notes", ""),
            slide_index=slide.get("slide_index", 0),
            has_shapes=slide.get("has_shapes", False),
            has_images=slide.get("has_images", False),
            has_charts=slide.get("has_charts", False),
        )

        if result.decision == VisionDecision.SKIP:
            skip_count += 1
        elif result.decision == VisionDecision.REQUIRED:
            required_count += 1
        else:
            optional_count += 1

    # Calcul appels Vision avec/sans gating
    vision_calls_no_gating = total
    vision_calls_with_gating = required_count + (optional_count if include_optional else 0)

    # Estimation coût (gpt-4o vision ~$0.03/slide)
    cost_per_vision_call = 0.03
    cost_no_gating = vision_calls_no_gating * cost_per_vision_call
    cost_with_gating = vision_calls_with_gating * cost_per_vision_call
    savings = cost_no_gating - cost_with_gating
    savings_percent = (savings / cost_no_gating * 100) if cost_no_gating > 0 else 0

    return {
        "total_slides": total,
        "skip_vision": skip_count,
        "required_vision": required_count,
        "optional_vision": optional_count,
        "vision_calls_no_gating": vision_calls_no_gating,
        "vision_calls_with_gating": vision_calls_with_gating,
        "estimated_cost_no_gating_usd": round(cost_no_gating, 2),
        "estimated_cost_with_gating_usd": round(cost_with_gating, 2),
        "estimated_savings_usd": round(savings, 2),
        "savings_percent": round(savings_percent, 1),
    }


__all__ = [
    "VisionDecision",
    "GatingResult",
    "should_use_vision",
    "estimate_vision_savings",
]
