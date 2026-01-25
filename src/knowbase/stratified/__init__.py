"""
OSMOSE Pipeline V2 - Lecture Stratifiée
========================================

Pipeline de traitement documentaire basé sur le modèle de lecture stratifiée.
Ref: doc/ongoing/ARCH_STRATIFIED_PIPELINE_V2.md

Passes:
- Pass 0: Extraction + Structural Graph (Document, Section, DocItem)
- Pass 1: Lecture Stratifiée (Subject, Theme, Concept, Information)
- Pass 2: Enrichissement (Relations inter-concepts)
- Pass 3: Consolidation Corpus (Entity Resolution cross-doc)
"""

__version__ = "2.0.0"

# Pass 0 - Structural Graph
from knowbase.stratified.pass0 import (
    Pass0Adapter,
    Pass0Result,
    build_structural_graph_v2,
)

# Pass 1 - Lecture Stratifiée
from knowbase.stratified.pass1 import (
    Pass1OrchestratorV2,
    run_pass1,
    DocumentAnalyzerV2,
    ConceptIdentifierV2,
    AssertionExtractorV2,
    AnchorResolverV2,
    RawAssertion,
    ConceptLink,
    PromotionResult,
    PROMOTION_POLICY,
    build_chunk_to_docitem_mapping,
)

# Models
from knowbase.stratified.models import (
    # Enums
    DocumentStructure,
    ConceptRole,
    AssertionType,
    AssertionStatus,
    AssertionLogReason,
    DocItemType,
    # Structures
    DocumentMeta,
    Section,
    DocItem,
    Subject,
    Theme,
    Concept,
    Anchor,
    Information,
    AssertionLogEntry,
    # Results
    Pass1Stats,
    Pass1Result,
    CanonicalConcept,
    CanonicalTheme,
)

__all__ = [
    # Pass 0
    "Pass0Adapter",
    "Pass0Result",
    "build_structural_graph_v2",
    # Pass 1
    "Pass1OrchestratorV2",
    "run_pass1",
    "DocumentAnalyzerV2",
    "ConceptIdentifierV2",
    "AssertionExtractorV2",
    "AnchorResolverV2",
    "RawAssertion",
    "ConceptLink",
    "PromotionResult",
    "PROMOTION_POLICY",
    "build_chunk_to_docitem_mapping",
    # Enums
    "DocumentStructure",
    "ConceptRole",
    "AssertionType",
    "AssertionStatus",
    "AssertionLogReason",
    "DocItemType",
    # Structures
    "DocumentMeta",
    "Section",
    "DocItem",
    "Subject",
    "Theme",
    "Concept",
    "Anchor",
    "Information",
    "AssertionLogEntry",
    # Results
    "Pass1Stats",
    "Pass1Result",
    "CanonicalConcept",
    "CanonicalTheme",
]
