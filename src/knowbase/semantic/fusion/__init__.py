"""
🌊 OSMOSE Semantic Intelligence - Module Fusion

Phase 1.8.1d: Extraction Locale + Fusion Contextuelle

Ce module implémente la fusion intelligente de concepts locaux extraits de documents structurés (PPTX).

Architecture:
- SmartConceptMerger: Orchestrateur de fusion basée sur règles
- FusionRule (ABC): Interface règle de fusion
- Règles MVP: MainEntitiesMergeRule, AlternativesFeaturesRule, SlideSpecificPreserveRule
- Integration: process_document_with_fusion (point d'entrée pipeline)

Usage:
    from knowbase.semantic.fusion import process_document_with_fusion

    # Pipeline intégré (détection automatique PPTX)
    canonical_concepts = await process_document_with_fusion(
        document_type="PPTX",
        slides_data=slides,
        document_context=context,
        concept_extractor=extractor
    )

    # Ou usage direct SmartConceptMerger
    from knowbase.semantic.fusion import SmartConceptMerger
    from knowbase.semantic.fusion.rules import MainEntitiesMergeRule

    merger = SmartConceptMerger(rules=[MainEntitiesMergeRule(config)])
    canonical_concepts = await merger.merge(local_concepts)
"""

from .smart_concept_merger import SmartConceptMerger
from .fusion_rules import FusionRule
from .models import FusionResult, FusionConfig
from .fusion_integration import (
    process_document_with_fusion,
    load_fusion_config,
    create_fusion_rules
)

__all__ = [
    "SmartConceptMerger",
    "FusionRule",
    "FusionResult",
    "FusionConfig",
    "process_document_with_fusion",
    "load_fusion_config",
    "create_fusion_rules",
]
