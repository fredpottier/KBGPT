"""
OSMOSE Pipeline V2 - Pass 1 (Lecture Stratifiée)
=================================================
Ref: doc/ongoing/ARCH_STRATIFIED_PIPELINE_V2.md

Pass 1 transforme un document structuré (depuis Pass 0) en structure sémantique:
- Phase 1.1: Document Analysis → Subject + Structure + Themes
- Phase 1.2: Concept Identification → Concepts (max 30, V2.1)
- Phase 1.2b: Concept Refinement → Itération jusqu'à saturation (V2.1)
- Phase 1.3: Assertion Extraction → RawAssertions
- Phase 1.3b: Anchor Resolution → chunk_id → docitem_id (CRITIQUE)
- Phase 1.4: Semantic Linking + Promotion → Information + AssertionLog

Usage:
    from knowbase.stratified.pass1 import Pass1OrchestratorV2, run_pass1

    result = run_pass1(
        doc_id="doc_123",
        doc_title="Mon Document",
        content="...",
        docitems={...},
        chunks={...},
        llm_client=my_llm_client
    )
"""

# Orchestrator principal
from knowbase.stratified.pass1.orchestrator import (
    Pass1OrchestratorV2,
    run_pass1,
)

# Composants individuels
from knowbase.stratified.pass1.document_analyzer import DocumentAnalyzerV2
from knowbase.stratified.pass1.concept_identifier import ConceptIdentifierV2
from knowbase.stratified.pass1.assertion_extractor import (
    AssertionExtractorV2,
    RawAssertion,
    ConceptLink,
    MultiConceptLink,
    PromotionResult,
    PromotionTier,
    PROMOTION_POLICY,
)
from knowbase.stratified.pass1.concept_refiner import (
    ConceptRefinerV2,
    SaturationMetrics,
)
from knowbase.stratified.pass1.anchor_resolver import (
    AnchorResolverV2,
    AnchorResolutionResult,
    ChunkToDocItemMapping,
    AnchorResolverStats,
    build_chunk_to_docitem_mapping,
)
from knowbase.stratified.pass1.persister import (
    Pass1PersisterV2,
    persist_pass1_result,
)

__all__ = [
    # Orchestrator
    "Pass1OrchestratorV2",
    "run_pass1",
    # Components
    "DocumentAnalyzerV2",
    "ConceptIdentifierV2",
    "ConceptRefinerV2",
    "AssertionExtractorV2",
    "AnchorResolverV2",
    # Data classes
    "RawAssertion",
    "ConceptLink",
    "MultiConceptLink",
    "PromotionResult",
    "SaturationMetrics",
    "AnchorResolutionResult",
    "ChunkToDocItemMapping",
    "AnchorResolverStats",
    # Utilities
    "PromotionTier",
    "PROMOTION_POLICY",
    "build_chunk_to_docitem_mapping",
    # Persistence
    "Pass1PersisterV2",
    "persist_pass1_result",
]
