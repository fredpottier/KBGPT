"""
Layout Detection pour Extraction V2.

MT-1: Layout-Aware Chunking (ADR_REDUCTO_PARSING_PRIMITIVES)

LayoutDetector: Detecte les regions structurelles dans le full_text linearise.
LayoutRegion: Region atomique qui ne doit pas etre coupee lors du chunking.

Principe: "Ne jamais couper un tableau" -> regle non-negociable.
"""

from knowbase.extraction_v2.layout.layout_detector import (
    LayoutDetector,
    LayoutRegion,
    RegionType,
    get_layout_detector,
)

__all__ = [
    "LayoutDetector",
    "LayoutRegion",
    "RegionType",
    "get_layout_detector",
]
