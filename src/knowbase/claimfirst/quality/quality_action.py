# src/knowbase/claimfirst/quality/quality_action.py
"""
Enum QualityAction et dataclass QualityVerdict pour les gates qualité.

V1.3: Quality gates pipeline — 5 familles de défauts.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional


class QualityAction(str, Enum):
    """Actions possibles des gates qualité sur une claim."""

    PASS = "PASS"
    REJECT_FABRICATION = "REJECT_FABRICATION"
    REWRITE_EVIDENCE_LOCKED = "REWRITE_EVIDENCE_LOCKED"
    BUCKET_NOT_CLAIMABLE = "BUCKET_NOT_CLAIMABLE"
    REJECT_TAUTOLOGY = "REJECT_TAUTOLOGY"
    REJECT_TEMPLATE_LEAK = "REJECT_TEMPLATE_LEAK"
    DISCARD_SF_MISALIGNED = "DISCARD_SF_MISALIGNED"
    SPLIT_ATOMICITY = "SPLIT_ATOMICITY"
    RESOLVE_INDEPENDENCE = "RESOLVE_INDEPENDENCE"
    BUCKET_LOW_INDEPENDENCE = "BUCKET_LOW_INDEPENDENCE"
    FLAG_REDUNDANT_CROSSDOC = "FLAG_REDUNDANT_CROSSDOC"


@dataclass
class QualityVerdict:
    """Résultat d'une gate qualité pour une claim."""

    action: QualityAction
    scores: Dict[str, float] = field(default_factory=dict)
    detail: Optional[str] = None
    rewritten_text: Optional[str] = None
    split_claims: Optional[List[str]] = None
    resolved_text: Optional[str] = None
    claim_id: Optional[str] = None  # V1.3.1: pour mapping correct verdict→claim


__all__ = [
    "QualityAction",
    "QualityVerdict",
]
