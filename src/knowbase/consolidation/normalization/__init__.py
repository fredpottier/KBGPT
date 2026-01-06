"""
Marker Normalization Layer - ADR_MARKER_NORMALIZATION_LAYER.

Architecture:
- MarkerMention: Ce qui est extrait brut du document
- CanonicalMarker: Forme normalisée (via rules/aliases)
- NormalizationStore: Gestion Neo4j des mentions et canoniques
- NormalizationEngine: Moteur de règles (YAML config + Entity Anchor)

Principe fondamental:
> Un marker non-normalisé est acceptable. Un marker mal-normalisé est toxique.

Safe-by-default: Si normalisation incertaine → reste "unresolved"
"""

from knowbase.consolidation.normalization.models import (
    MarkerMention,
    CanonicalMarker,
    NormalizationRule,
    NormalizationResult,
    NormalizationStatus,
)
from knowbase.consolidation.normalization.normalization_store import (
    NormalizationStore,
    get_normalization_store,
)
from knowbase.consolidation.normalization.normalization_engine import (
    NormalizationEngine,
    get_normalization_engine,
)

__all__ = [
    # Models
    "MarkerMention",
    "CanonicalMarker",
    "NormalizationRule",
    "NormalizationResult",
    "NormalizationStatus",
    # Store
    "NormalizationStore",
    "get_normalization_store",
    # Engine
    "NormalizationEngine",
    "get_normalization_engine",
]
