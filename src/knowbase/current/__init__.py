"""
Current Resolver — V2-S3.

Détermine le document autoritaire pour un sujet quand l'anchor est CURRENT_DEFAULT.

Conformément à VISION_RECENTREE §4.3 :
- Composition runtime de faits documentés + heuristiques sûres
- Aucune écriture dans le KG (les inférences sont transitoires)
- 3 phases : filtrage strict → ranking heuristiques → politique graduée seuils 0.85/0.55
- Si ambiguïté irréductible → remonter au user (pas d'auto-pick à confiance basse)

Pipeline runtime amont :
    Subject Resolver → Anchor Extractor → Anchor Filter → Current Resolver (ce module)
                                                       → Conflict Detector intra-anchor
                                                       → Evolution Builder
"""

from knowbase.current.models import (
    CurrentCandidate,
    CurrentResolverDecision,
    CurrentResolverResult,
    ConfidenceWeights,
)
from knowbase.current.current_resolver import CurrentResolver

__all__ = [
    "CurrentCandidate",
    "CurrentResolverDecision",
    "CurrentResolverResult",
    "ConfidenceWeights",
    "CurrentResolver",
]
