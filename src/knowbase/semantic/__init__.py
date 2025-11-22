"""
🌊 OSMOSE Semantic Intelligence Module

Ce module implémente l'intelligence sémantique d'OSMOSE (Phase 1).

Composants Clés :
- SemanticDocumentProfiler : Analyse sémantique des documents
- NarrativeThreadDetector : Détection des fils narratifs
- IntelligentSegmentationEngine : Segmentation contextuelle
- DualStorageExtractor : Extraction Proto-KG

Projet : KnowWhere (OSMOSE)
Phase : 1 - Semantic Core
"""

from .profiler import SemanticDocumentProfiler
# Modules Phase 1 non encore implémentés (TODO):
# from .narrative_detector import NarrativeThreadDetector
# from .segmentation import IntelligentSegmentationEngine
# from .extractor import DualStorageExtractor

from .models import (
    SemanticProfile,
    ComplexityZone,
    CandidateEntity,
    CandidateRelation,
    Concept,
    CanonicalConcept,
    Topic,
    ConceptConnection,
    DocumentRole,
)
from .config import SemanticConfig

__all__ = [
    "SemanticDocumentProfiler",
    # "NarrativeThreadDetector",  # TODO Phase 1
    # "IntelligentSegmentationEngine",  # TODO Phase 1
    # "DualStorageExtractor",  # TODO Phase 1
    "SemanticProfile",
    "ComplexityZone",
    "CandidateEntity",
    "CandidateRelation",
    "Concept",
    "CanonicalConcept",
    "Topic",
    "ConceptConnection",
    "DocumentRole",
    "SemanticConfig",
]

__version__ = "1.0.0-alpha"
