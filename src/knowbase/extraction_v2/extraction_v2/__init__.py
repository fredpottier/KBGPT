"""
OSMOSE Extraction V2 - Pipeline d'extraction documentaire unifié.

Architecture:
- Docling comme extracteur unifié (PDF, DOCX, PPTX, XLSX)
- Vision Gating V4 avec 5 signaux (RIS, VDS, TFS, SDS, VTS)
- Vision Path avec Domain Context injectable
- Sortie bi-couche: full_text (OSMOSE) + structure (audit/futur)

Principe fondamental:
    "Vision observe. Vision décrit. OSMOSE raisonne."

Auteur: Claude Code
Date: 2026-01-02
"""

from knowbase.extraction_v2.models import (
    ExtractionResult,
    VisionUnit,
    VisionSignals,
    GatingDecision,
    ExtractionAction,
    BoundingBox,
    TextBlock,
    VisualElement,
    VisionExtraction,
    VisionDomainContext,
)
from knowbase.extraction_v2.pipeline import ExtractionPipelineV2

__all__ = [
    # Pipeline principal
    "ExtractionPipelineV2",
    # Modèles de données
    "ExtractionResult",
    "VisionUnit",
    "VisionSignals",
    "GatingDecision",
    "ExtractionAction",
    "BoundingBox",
    "TextBlock",
    "VisualElement",
    "VisionExtraction",
    "VisionDomainContext",
]

__version__ = "2.0.0"
