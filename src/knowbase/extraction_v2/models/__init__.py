"""
Modèles de données pour Extraction V2.

Ces modèles sont CRITIQUES et doivent être gelés avant Phase 3.
Tous les signaux, décisions et merges en dépendent.
"""

from knowbase.extraction_v2.models.elements import (
    BoundingBox,
    TextBlock,
    VisualElement,
    TableData,
)
from knowbase.extraction_v2.models.signals import VisionSignals
from knowbase.extraction_v2.models.gating import (
    ExtractionAction,
    GatingDecision,
)
from knowbase.extraction_v2.models.vision_unit import VisionUnit
from knowbase.extraction_v2.models.extraction_result import (
    ExtractionResult,
    PageIndex,
    DocumentStructure,
    PageOutput,
)
from knowbase.extraction_v2.models.domain_context import (
    VisionDomainContext,
    get_vision_domain_context,
    SAP_VISION_CONTEXT,
)
from knowbase.extraction_v2.models.vision_output import (
    VisionElement,
    VisionRelation,
    VisionAmbiguity,
    VisionUncertainty,
    VisionExtraction,
)

__all__ = [
    # Éléments de base
    "BoundingBox",
    "TextBlock",
    "VisualElement",
    "TableData",
    # Signaux
    "VisionSignals",
    # Gating
    "ExtractionAction",
    "GatingDecision",
    # Vision Unit
    "VisionUnit",
    # Résultat extraction
    "ExtractionResult",
    "PageIndex",
    "DocumentStructure",
    "PageOutput",
    # Domain Context
    "VisionDomainContext",
    "get_vision_domain_context",
    "SAP_VISION_CONTEXT",
    # Vision output
    "VisionElement",
    "VisionRelation",
    "VisionAmbiguity",
    "VisionUncertainty",
    "VisionExtraction",
]
