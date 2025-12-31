"""
Hybrid Anchor Model - Classification Module

Phase 5: Classification hybride
- Pass 1: Heuristique (rapide, pas de LLM)
- Pass 2: LLM fine-grained (enrichissement)

ADR: doc/ongoing/ADR_HYBRID_ANCHOR_MODEL.md
"""

from .heuristic_classifier import (
    HeuristicClassifier,
    classify_heuristic,
    ConceptTypeHeuristic,
)
from .fine_classifier import (
    FineClassifier,
    get_fine_classifier,
)

__all__ = [
    "HeuristicClassifier",
    "classify_heuristic",
    "ConceptTypeHeuristic",
    "FineClassifier",
    "get_fine_classifier",
]
