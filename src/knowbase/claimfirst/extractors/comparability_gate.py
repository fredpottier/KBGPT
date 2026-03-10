# src/knowbase/claimfirst/extractors/comparability_gate.py
"""
Candidate Gating — Filtre déterministe domain-agnostic (Étape 0).

Détecte les claims portant une réponse à une question factuelle stable
en analysant des signaux structurels (valeur + unité, version, contrainte,
booléen, opérateur normatif...).

Aucun mot-clé domaine (TLS, SLA, backup, RAM...) n'est utilisé.
Les signaux sont purement linguistiques/structurels.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import List, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from knowbase.claimfirst.models.claim import Claim


# ── Signaux forts (1 suffit) ───────────────────────────────────────────

STRONG_SIGNALS = {
    "strong:numeric_with_unit": re.compile(
        r"\d+(?:\.\d+)?\s*(%|GB|MB|TB|KB|days?|hours?|seconds?|ms|minutes?|years?|months?|weeks?)\b",
        re.IGNORECASE,
    ),
    "strong:version_explicit": re.compile(
        r"(?:v\.?\s*)?\d+\.\d+(?:\.\d+)*|(?:version|release)\s+\d+",
        re.IGNORECASE,
    ),
    "strong:constraint_min_max": re.compile(
        r"\b(minimum|maximum|at\s+least|at\s+most|up\s+to)\s+\d+",
        re.IGNORECASE,
    ),
    "strong:deprecation": re.compile(
        r"\b(deprecated|end\s+of\s+(support|life|maintenance)|replaced\s+by|superseded)\b",
        re.IGNORECASE,
    ),
    "strong:default_value": re.compile(
        r"\b(default|defaults?\s+to)\s+\S+",
        re.IGNORECASE,
    ),
}

# ── Signaux faibles (≥2 nécessaires, ou 1 + entité liée) ──────────────

WEAK_SIGNALS = {
    "weak:normative_with_value": re.compile(
        r"\b(must|shall|requires?|mandatory|prohibited)\b.*\b(\d+|enabled|disabled|supported)\b",
        re.IGNORECASE,
    ),
    "weak:implicit_boolean": re.compile(
        r"\b(enabled|disabled|supported|not\s+supported|allowed|not\s+allowed)\b",
        re.IGNORECASE,
    ),
    "weak:frequency": re.compile(
        r"\b(daily|weekly|monthly|quarterly|hourly)\b",
        re.IGNORECASE,
    ),
    "weak:threshold_limit": re.compile(
        r"\b(threshold|limit|cap|ceiling|floor)\b",
        re.IGNORECASE,
    ),
    "weak:comparison_words": re.compile(
        r"\b(more|less|higher|lower|greater|fewer|between|compared)\b",
        re.IGNORECASE,
    ),
    "weak:temporal_marker": re.compile(
        r"\b(since|until|from\s+version|starting\s+with|as\s+of)\b",
        re.IGNORECASE,
    ),
    "weak:list_constraint": re.compile(
        r"\b(one\s+of|either|any\s+of|none\s+of|only)\b",
        re.IGNORECASE,
    ),
    "weak:protocol_format": re.compile(
        # Pattern opportuniste : capte formats techno/standards (ex: TLS 1.2, HTTP 2.0)
        # Pas universel mais utile pour corpus techniques
        r"\b[A-Z]{2,6}\s*\d+(?:\.\d+)*\b",
    ),
}


@dataclass
class GatingResult:
    """Résultat du candidate gating."""

    claim_id: str
    retained: bool
    signals: List[str] = field(default_factory=list)
    score: int = 0
    rejection_reason: Optional[str] = None


def _has_linked_entities(claim) -> bool:
    """Vérifie si la claim a des entités liées via structured_form."""
    sf = getattr(claim, "structured_form", None)
    if not sf:
        return False
    if isinstance(sf, dict):
        # structured_form peut contenir subject, predicate, object, entities, etc.
        if sf.get("entities") or sf.get("subject") or sf.get("object"):
            return True
    return False


def candidate_gate(claim) -> GatingResult:
    """
    Filtre déterministe domain-agnostic.

    Retourne retained=True si :
    - ≥1 signal fort, OU
    - ≥2 signaux faibles, OU
    - 1 signal faible + entité liée
    ET aucun signal négatif bloquant.

    Args:
        claim: Objet Claim avec .claim_id, .text, .claim_type, .structured_form

    Returns:
        GatingResult
    """
    claim_id = getattr(claim, "claim_id", "unknown")
    text = getattr(claim, "text", "")

    # ── Signaux négatifs (bloquants) ───────────────────────────────────
    if len(text) < 30:
        return GatingResult(
            claim_id=claim_id,
            retained=False,
            rejection_reason="text_too_short",
        )

    # Claim de type EXAMPLE
    claim_type = getattr(claim, "claim_type", None)
    if claim_type:
        ct_str = claim_type.value if hasattr(claim_type, "value") else str(claim_type)
        if ct_str.upper() == "EXAMPLE":
            return GatingResult(
                claim_id=claim_id,
                retained=False,
                rejection_reason="claim_type_example",
            )

    has_entities = _has_linked_entities(claim)

    # Pas de structured_form ET pas d'entités → bloquant
    sf = getattr(claim, "structured_form", None)
    if not sf and not has_entities:
        return GatingResult(
            claim_id=claim_id,
            retained=False,
            rejection_reason="no_structured_form_no_entities",
        )

    # ── Signaux positifs ───────────────────────────────────────────────
    matched_signals: List[str] = []

    # Signaux forts
    strong_count = 0
    for name, pattern in STRONG_SIGNALS.items():
        if pattern.search(text):
            matched_signals.append(name)
            strong_count += 1

    if strong_count >= 1:
        return GatingResult(
            claim_id=claim_id,
            retained=True,
            signals=matched_signals,
            score=strong_count + len(matched_signals),
        )

    # Signaux faibles
    weak_count = 0
    for name, pattern in WEAK_SIGNALS.items():
        if pattern.search(text):
            matched_signals.append(name)
            weak_count += 1

    # ≥2 faibles OU 1 faible + entité OU 1 faible + structured_form non vide
    has_structured_form = bool(sf)
    if weak_count >= 2 or (weak_count >= 1 and has_entities) or (weak_count >= 1 and has_structured_form):
        return GatingResult(
            claim_id=claim_id,
            retained=True,
            signals=matched_signals,
            score=weak_count,
        )

    # Aucun signal suffisant
    return GatingResult(
        claim_id=claim_id,
        retained=False,
        signals=matched_signals,
        rejection_reason="insufficient_signals",
    )


__all__ = [
    "GatingResult",
    "candidate_gate",
    "STRONG_SIGNALS",
    "WEAK_SIGNALS",
]
