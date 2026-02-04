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

DEPRECATED: Phase 1 Semantic Core abandonnée au profit du pipeline stratified.
Ce module contient du code legacy qui n'est plus activement maintenu.
"""

from knowbase.common.deprecation import deprecated_module, DeprecationKind

deprecated_module(
    kind=DeprecationKind.PHASE_ABANDONED,
    reason="Phase 1 Semantic Core abandonnée, remplacée par pipeline stratified",
    alternative="knowbase.stratified pour l'extraction de connaissances",
    removal_version="2.0.0",
)

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
    ConceptType,
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
    "ConceptType",
    "DocumentRole",
    "SemanticConfig",
]

__version__ = "1.0.0-alpha"
