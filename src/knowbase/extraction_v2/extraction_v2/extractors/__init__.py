"""
Extracteurs pour Extraction V2.

DoclingExtractor: Extracteur unifié pour tous les formats Office.
VDSFallback: Fallback pour le signal VDS si Docling ne fournit pas assez de détails.
"""

from knowbase.extraction_v2.extractors.docling_extractor import DoclingExtractor
from knowbase.extraction_v2.extractors.vds_fallback import VDSFallback

__all__ = [
    "DoclingExtractor",
    "VDSFallback",
]
