"""
OSMOSE Extraction V2 - Pipeline d'extraction documentaire unifie.

Architecture:
- Docling comme extracteur unifie (PDF, DOCX, PPTX, XLSX)
- Vision Gating V4 avec 5 signaux (RIS, VDS, TFS, SDS, VTS)
- Vision Path avec Domain Context injectable
- Sortie bi-couche: full_text (OSMOSE) + structure (audit/futur)

Principe fondamental:
    "Vision observe. Vision decrit. OSMOSE raisonne."

Usage:
    >>> from knowbase.extraction_v2 import ExtractionPipelineV2, extract_document
    >>>
    >>> # Usage simple
    >>> result = await extract_document("/path/to/doc.pdf")
    >>> print(result.full_text)
    >>>
    >>> # Usage avance
    >>> pipeline = ExtractionPipelineV2(config)
    >>> result = await pipeline.process_document("/path/to/doc.pdf")

Auteur: Claude Code
Date: 2026-01-02
"""

# Modeles de donnees
from knowbase.extraction_v2.models import (
    # Elements de base
    BoundingBox,
    TextBlock,
    VisualElement,
    TableData,
    # Signaux et gating
    VisionSignals,
    GatingDecision,
    ExtractionAction,
    # VisionUnit
    VisionUnit,
    # Domain Context
    VisionDomainContext,
    get_vision_domain_context,
    SAP_VISION_CONTEXT,
    # Vision Output
    VisionElement,
    VisionRelation,
    VisionAmbiguity,
    VisionUncertainty,
    VisionExtraction,
    # Extraction Result
    ExtractionResult,
    DocumentStructure,
    PageOutput,
    PageIndex,
)

# Pipeline principal
from knowbase.extraction_v2.pipeline import (
    ExtractionPipelineV2,
    PipelineConfig,
    PipelineMetrics,
    extract_document,
)

# Extracteurs
from knowbase.extraction_v2.extractors.docling_extractor import (
    DoclingExtractor,
    SUPPORTED_FORMATS,
)
from knowbase.extraction_v2.extractors.vds_fallback import VDSFallback

# Gating
from knowbase.extraction_v2.gating.engine import GatingEngine
from knowbase.extraction_v2.gating.signals import (
    compute_raster_image_signal,
    compute_vector_drawing_signal,
    compute_text_fragmentation_signal,
    compute_spatial_dispersion_signal,
    compute_visual_table_signal,
    compute_all_signals,
)
from knowbase.extraction_v2.gating.weights import (
    DEFAULT_GATING_WEIGHTS,
    GATING_THRESHOLDS,
    get_weights_for_domain,
)

# Vision
from knowbase.extraction_v2.vision.analyzer import VisionAnalyzer
from knowbase.extraction_v2.vision.prompts import (
    build_vision_prompt,
    get_vision_messages,
    VISION_SYSTEM_PROMPT,
)
from knowbase.extraction_v2.vision.text_generator import VisionTextGenerator

# Merge
from knowbase.extraction_v2.merge.merger import (
    StructuredMerger,
    MergedPageOutput,
    MergeProvenance,
)
from knowbase.extraction_v2.merge.linearizer import Linearizer


__all__ = [
    # === Pipeline principal ===
    "ExtractionPipelineV2",
    "PipelineConfig",
    "PipelineMetrics",
    "extract_document",

    # === Modeles de donnees ===
    # Elements
    "BoundingBox",
    "TextBlock",
    "VisualElement",
    "TableData",
    # Signaux
    "VisionSignals",
    "GatingDecision",
    "ExtractionAction",
    # VisionUnit
    "VisionUnit",
    # Domain Context
    "VisionDomainContext",
    "get_vision_domain_context",
    "SAP_VISION_CONTEXT",
    # Vision Output
    "VisionElement",
    "VisionRelation",
    "VisionAmbiguity",
    "VisionUncertainty",
    "VisionExtraction",
    # Extraction Result
    "ExtractionResult",
    "DocumentStructure",
    "PageOutput",
    "PageIndex",

    # === Extracteurs ===
    "DoclingExtractor",
    "SUPPORTED_FORMATS",
    "VDSFallback",

    # === Gating ===
    "GatingEngine",
    "compute_raster_image_signal",
    "compute_vector_drawing_signal",
    "compute_text_fragmentation_signal",
    "compute_spatial_dispersion_signal",
    "compute_visual_table_signal",
    "compute_all_signals",
    "DEFAULT_GATING_WEIGHTS",
    "GATING_THRESHOLDS",
    "get_weights_for_domain",

    # === Vision ===
    "VisionAnalyzer",
    "build_vision_prompt",
    "get_vision_messages",
    "VISION_SYSTEM_PROMPT",
    "VisionTextGenerator",

    # === Merge ===
    "StructuredMerger",
    "MergedPageOutput",
    "MergeProvenance",
    "Linearizer",
]

__version__ = "2.0.0"
