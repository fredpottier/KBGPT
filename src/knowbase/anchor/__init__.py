"""
Anchor Extraction & Filtering — V2-S2.

Conformément à VISION_RECENTREE_OSMOSIS_2026-04-30 §3 et §4 :
- Anchor Extractor : LLM sémantique pur evidence-locked extrait l'anchor
  (point | range | current_default) depuis la question utilisateur.
- Anchor Filter : restreint les claims candidats au cadre d'applicabilité
  porté par l'anchor (via ApplicabilityFrame V2 + TemporalFrame).

Domain-agnostic par construction :
- Aucun regex, aucun keyword
- Prompt sémantique multilingue
- Validator evidence-locked : extraction_evidence doit être substring de la question

Pipeline runtime (référence Vision §3) :
    Subject Resolver → Anchor Extractor → Anchor Filter → Current Resolver →
    Conflict Detector intra-anchor → Evolution Builder (si range)
"""

from knowbase.anchor.models import (
    AnchorType,
    AnchorScope,
    ResolvedAnchor,
    AnchorExtractionDiagnostic,
)
from knowbase.anchor.anchor_extractor import AnchorExtractor
from knowbase.anchor.anchor_filter import AnchorFilter

__all__ = [
    "AnchorType",
    "AnchorScope",
    "ResolvedAnchor",
    "AnchorExtractionDiagnostic",
    "AnchorExtractor",
    "AnchorFilter",
]
