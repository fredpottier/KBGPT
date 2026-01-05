"""
Context Extraction pour Assertion-aware Knowledge Graph.

Ce module extrait les marqueurs de contexte documentaire (DocContextFrame)
et enrichit les assertions (Anchors) avec polarity, scope et markers.

Architecture (ADR_ASSERTION_AWARE_KG.md):
- PR1: DocContext Extraction
  - Candidate Mining: extraction deterministe de marqueurs candidats
  - LLM Validation: validation par Qwen 14B (anti-hallucination)
  - DocContextFrame: resultat stocke sur ExtractionResult

- PR2: AnchorContext + Inheritance
  - Heuristics: detection polarity/override sans LLM
  - AnchorContextAnalyzer: orchestration heuristics + LLM
  - InheritanceEngine: propagation DocContext -> AnchorContext

Spec: doc/ongoing/ADR_ASSERTION_AWARE_KG.md
"""

# === PR1: DocContext Extraction ===
from knowbase.extraction_v2.context.models import (
    DocScope,
    MarkerEvidence,
    ScopeSignals,
    DocContextFrame,
    DocScopeAnalysis,
)
from knowbase.extraction_v2.context.candidate_mining import (
    CandidateMiner,
    MarkerCandidate,
)
from knowbase.extraction_v2.context.doc_context_extractor import (
    DocContextExtractor,
)

# === PR2: AnchorContext + Inheritance ===
from knowbase.extraction_v2.context.anchor_models import (
    Polarity,
    AssertionScope,
    OverrideType,
    QualifierSource,
    LocalMarker,
    AnchorContext,
    ProtoConceptContext,
)
from knowbase.extraction_v2.context.heuristics import (
    PassageHeuristics,
    HeuristicResult,
    detect_polarity_simple,
    detect_local_markers_simple,
)
from knowbase.extraction_v2.context.anchor_context_analyzer import (
    AnchorContextAnalyzer,
    get_anchor_context_analyzer,
)
from knowbase.extraction_v2.context.inheritance import (
    InheritanceEngine,
    InheritanceRule,
    get_inheritance_engine,
)


__all__ = [
    # === PR1: DocContext Models ===
    "DocScope",
    "MarkerEvidence",
    "ScopeSignals",
    "DocContextFrame",
    "DocScopeAnalysis",
    # Candidate Mining
    "CandidateMiner",
    "MarkerCandidate",
    # Extractor
    "DocContextExtractor",
    # === PR2: AnchorContext Models ===
    "Polarity",
    "AssertionScope",
    "OverrideType",
    "QualifierSource",
    "LocalMarker",
    "AnchorContext",
    "ProtoConceptContext",
    # Heuristics
    "PassageHeuristics",
    "HeuristicResult",
    "detect_polarity_simple",
    "detect_local_markers_simple",
    # Anchor Analyzer
    "AnchorContextAnalyzer",
    "get_anchor_context_analyzer",
    # Inheritance
    "InheritanceEngine",
    "InheritanceRule",
    "get_inheritance_engine",
]
