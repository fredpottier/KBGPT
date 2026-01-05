"""
OSMOSE Corpus Consolidation Module

Implements corpus-level Entity Resolution and weak links.

Components:
- CorpusERPipeline: Entity Resolution inter-document
- CorpusLinker: Weak links (CO_OCCURS_IN_CORPUS, MENTIONED_IN_DOCUMENT)
- MergeStore: Audit and storage of merge operations
- MarkerStore: Marker nodes pour diff queries (PR3)
- AssertionStore: EXTRACTED_FROM avec assertions (PR4)

Author: Claude Code
Date: 2026-01-01
Spec: doc/ongoing/SPEC_CORPUS_CONSOLIDATION.md
"""

from .types import (
    DecisionType,
    MergeProposal,
    MergeResult,
    CorpusERConfig,
)
from .lex_utils import compute_lex_key, lex_score
from .corpus_er_pipeline import CorpusERPipeline, get_corpus_er_pipeline
from .marker_store import (
    MarkerKind,
    MarkerNode,
    ConceptMarkerLink,
    DiffResult,
    MarkerStore,
    get_marker_store,
    detect_marker_kind,
)
from .assertion_store import (
    AssertionData,
    DocumentContextData,
    AssertionStore,
    get_assertion_store,
)

__all__ = [
    # Types
    "DecisionType",
    "MergeProposal",
    "MergeResult",
    "CorpusERConfig",
    # Utils
    "compute_lex_key",
    "lex_score",
    # Pipeline
    "CorpusERPipeline",
    "get_corpus_er_pipeline",
    # PR3: MarkerStore
    "MarkerKind",
    "MarkerNode",
    "ConceptMarkerLink",
    "DiffResult",
    "MarkerStore",
    "get_marker_store",
    "detect_marker_kind",
    # PR4: AssertionStore
    "AssertionData",
    "DocumentContextData",
    "AssertionStore",
    "get_assertion_store",
]
