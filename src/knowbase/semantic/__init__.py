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
from .narrative_detector import NarrativeThreadDetector
from .segmentation import IntelligentSegmentationEngine
from .extractor import DualStorageExtractor
from .models import (
    SemanticProfile,
    NarrativeThread,
    ComplexityZone,
    CandidateEntity,
    CandidateRelation,
)
from .config import SemanticConfig

__all__ = [
    "SemanticDocumentProfiler",
    "NarrativeThreadDetector",
    "IntelligentSegmentationEngine",
    "DualStorageExtractor",
    "SemanticProfile",
    "NarrativeThread",
    "ComplexityZone",
    "CandidateEntity",
    "CandidateRelation",
    "SemanticConfig",
]

__version__ = "1.0.0-alpha"
