"""
Runtime V2 — Pipeline anchor-driven (Vision recentrée 30/04/2026).

Remplace Runtime V1.1 (7 modes auto-classifiés + 3 régimes RAG_LED/KG_LED/HYBRID)
par un pipeline linéaire 5 étapes :

  Question → Anchor Extractor → Anchor Filter → Current Resolver (si CURRENT_DEFAULT)
                              → Retrieval Qdrant intra-scope
                              → Conflict Detector intra-anchor (Audit only)
                              → Evolution Builder (si anchor=range)
                              → Réponse structurée

Conformément à VISION_RECENTREE §3 (pipeline 6 étapes — Subject Resolver est
optionnel/déféré, à brancher en V2-S4+).

Domain-agnostic, pas de regex, pas de mode-classifier, pas de personas multiples.
Toggle Audit unique pour le maintainer (default OFF).
"""

from knowbase.runtime_v2.models import (
    PipelineDecision,
    PipelineResponse,
    EvidenceClaim,
    ConflictReport,
    EvolutionPoint,
)
from knowbase.runtime_v2.pipeline import RuntimeV2Pipeline

__all__ = [
    "PipelineDecision",
    "PipelineResponse",
    "EvidenceClaim",
    "ConflictReport",
    "EvolutionPoint",
    "RuntimeV2Pipeline",
]
