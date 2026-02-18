# src/knowbase/claimfirst/quality/deterministic_gates.py
"""
Gates qualité déterministes (sans LLM).

3 filtres :
1. Tautologie: cos(S, O) > 0.96 → REJECT_TAUTOLOGY
2. Template leak: {placeholder}, [PLACEHOLDER], TODO → REJECT_TEMPLATE_LEAK
3. SF alignment: cos(SF, text) < 0.85 → DISCARD_SF_MISALIGNED (supprime SF, garde claim)

V1.3: Quality gates pipeline.
"""

from __future__ import annotations

import re
from typing import Dict, List, Optional, TYPE_CHECKING

from knowbase.claimfirst.quality.quality_action import QualityAction, QualityVerdict

if TYPE_CHECKING:
    from knowbase.claimfirst.models.claim import Claim

# Seuils calibrés empiriquement sur 300 claims (embeddings multilingual-e5-large)
TRIVIALITY_THRESHOLD = 0.96
SF_ALIGNMENT_THRESHOLD = 0.85

# Patterns de template leak
TEMPLATE_PATTERNS = [
    re.compile(r'\{[a-zA-Z_]+\}'),               # {placeholder}
    re.compile(r'\[PLACEHOLDER\]', re.IGNORECASE), # [PLACEHOLDER]
    re.compile(r'\bTODO\b'),                       # TODO
    re.compile(r'\bTBD\b'),                        # TBD
    re.compile(r'\bXXX\b'),                        # XXX
    re.compile(r'\{\{[^}]+\}\}'),                  # {{template}}
]


def check_tautology(
    claim: "Claim",
    triviality_scores: Dict[str, float],
) -> Optional[QualityVerdict]:
    """
    cos(S, O) > 0.96 → REJECT_TAUTOLOGY.

    Une claim dont le sujet et l'objet sont quasi-identiques
    n'apporte aucune information.
    """
    score = triviality_scores.get(claim.claim_id)
    if score is None:
        return None

    if score > TRIVIALITY_THRESHOLD:
        return QualityVerdict(
            action=QualityAction.REJECT_TAUTOLOGY,
            scores={"triviality": score},
            detail=f"cos(S,O)={score:.3f} > {TRIVIALITY_THRESHOLD}",
        )

    return None


def check_template_leak(claim: "Claim") -> Optional[QualityVerdict]:
    """
    Regex: {xxx}, [PLACEHOLDER], TODO, TBD → REJECT_TEMPLATE_LEAK.

    Détecte les résidus de templates non résolus dans le texte ET la SF.
    """
    text = claim.text
    for pattern in TEMPLATE_PATTERNS:
        match = pattern.search(text)
        if match:
            return QualityVerdict(
                action=QualityAction.REJECT_TEMPLATE_LEAK,
                scores={},
                detail=f"Template leak detected: '{match.group()}'",
            )

    # V1.3.1: Détecter les leaks dans structured_form (ex: "Name of the subject entity")
    sf = claim.structured_form
    if sf and isinstance(sf, dict):
        for field_name in ("subject", "object"):
            val = sf.get(field_name, "")
            if isinstance(val, str) and re.search(
                r'^Name of the|^Entity Name$|^Description|^Specific ',
                val, re.IGNORECASE,
            ):
                # Ne pas rejeter la claim, juste supprimer la SF
                return QualityVerdict(
                    action=QualityAction.DISCARD_SF_MISALIGNED,
                    scores={},
                    detail=f"SF template leak in {field_name}: '{val}'",
                )

    return None


def check_sf_alignment(
    claim: "Claim",
    sf_scores: Dict[str, float],
) -> Optional[QualityVerdict]:
    """
    cos(SF, text) < 0.85 → DISCARD_SF_MISALIGNED.

    Ne rejette PAS la claim — supprime juste le structured_form incohérent.
    Le quality_status et quality_scores sont conservés pour audit.
    """
    score = sf_scores.get(claim.claim_id)
    if score is None:
        return None

    if score < SF_ALIGNMENT_THRESHOLD:
        return QualityVerdict(
            action=QualityAction.DISCARD_SF_MISALIGNED,
            scores={"sf_alignment": score},
            detail=f"SF discarded: cos(SF,text)={score:.3f} < {SF_ALIGNMENT_THRESHOLD}",
        )

    return None


__all__ = [
    "check_tautology",
    "check_template_leak",
    "check_sf_alignment",
    "TRIVIALITY_THRESHOLD",
    "SF_ALIGNMENT_THRESHOLD",
    "TEMPLATE_PATTERNS",
]
