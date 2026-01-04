"""
Merge et Linéarisation pour Extraction V2.

StructuredMerger: Fusionne Docling + Vision sans écrasement.
Linearizer: Génère full_text avec marqueurs pour OSMOSE.

Règle d'or: Vision n'écrase JAMAIS Docling.
"""

from knowbase.extraction_v2.merge.merger import StructuredMerger
from knowbase.extraction_v2.merge.linearizer import Linearizer

__all__ = [
    "StructuredMerger",
    "Linearizer",
]
