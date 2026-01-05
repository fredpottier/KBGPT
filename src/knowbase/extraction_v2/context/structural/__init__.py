"""
Structural Awareness Layer - Document Structure Analysis.

Ce module fournit les composants pour la detection de structure documentaire :
- ZoneSegmenter : Segmentation des pages en zones (TOP/MAIN/BOTTOM)
- TemplateDetector : Detection des fragments repetitifs (boilerplate)
- LinguisticCueDetector : Scoring des patterns linguistiques

Spec: doc/ongoing/ADR_DOCUMENT_STRUCTURAL_AWARENESS.md
"""

from knowbase.extraction_v2.context.structural.models import (
    StructuralConfidence,
    Zone,
    PageZones,
    ZonedLine,
    TemplateFragment,
    TemplateCluster,
    StructuralAnalysis,
    ZoneConfig,
)
from knowbase.extraction_v2.context.structural.zone_segmenter import (
    ZoneSegmenter,
    get_zone_segmenter,
)
from knowbase.extraction_v2.context.structural.template_detector import (
    TemplateDetector,
    get_template_detector,
)
from knowbase.extraction_v2.context.structural.linguistic_cue_detector import (
    LinguisticCueDetector,
    ContextualCues,
    get_linguistic_cue_detector,
)


__all__ = [
    # Enums
    "StructuralConfidence",
    "Zone",
    # Models
    "PageZones",
    "ZonedLine",
    "TemplateFragment",
    "TemplateCluster",
    "StructuralAnalysis",
    "ZoneConfig",
    "ContextualCues",
    # Segmenter
    "ZoneSegmenter",
    "get_zone_segmenter",
    # Detector
    "TemplateDetector",
    "get_template_detector",
    # Linguistic
    "LinguisticCueDetector",
    "get_linguistic_cue_detector",
]
