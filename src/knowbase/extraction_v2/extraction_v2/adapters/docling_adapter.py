"""
DoclingAdapter - Convertit la sortie Docling en VisionUnit.

Normalise la sortie Docling pour une interface uniforme
quel que soit le format source (PDF, DOCX, PPTX, XLSX).

Implémentation complète en Phase 2.
"""

from __future__ import annotations
from typing import Any, Dict, List, Optional
import logging

from knowbase.extraction_v2.models import VisionUnit

logger = logging.getLogger(__name__)


class DoclingAdapter:
    """
    Adaptateur Docling → VisionUnit.

    Convertit la sortie structurée de Docling en VisionUnits
    normalisés pour le Vision Gating.

    Usage:
        >>> adapter = DoclingAdapter()
        >>> unit = adapter.adapt_page(docling_output, page_index=0, format="PDF")
        >>> print(f"Blocks: {unit.text_blocks_count}, Images: {unit.images_count}")

    Note: Implémentation complète en Phase 2.
    """

    def __init__(self):
        """Initialise l'adaptateur."""
        logger.info("[DoclingAdapter] Created")

    def adapt_page(
        self,
        docling_output: Dict[str, Any],
        page_index: int,
        format: str,
        page_dimensions: tuple = (612, 792),  # Letter par défaut
    ) -> VisionUnit:
        """
        Convertit une page Docling en VisionUnit.

        Args:
            docling_output: Sortie Docling pour la page
            page_index: Index de la page (0-based)
            format: Format source ("PDF", "PPTX", etc.)
            page_dimensions: Dimensions (width, height)

        Returns:
            VisionUnit normalisé

        Raises:
            NotImplementedError: Implémentation en Phase 2
        """
        raise NotImplementedError(
            "DoclingAdapter.adapt_page() sera implémenté en Phase 2."
        )

    def adapt_document(
        self,
        docling_result: Any,
        format: str,
    ) -> List[VisionUnit]:
        """
        Convertit un document Docling complet en liste de VisionUnits.

        Args:
            docling_result: Résultat complet Docling
            format: Format source ("PDF", "PPTX", etc.)

        Returns:
            Liste de VisionUnits (une par page)

        Raises:
            NotImplementedError: Implémentation en Phase 2
        """
        raise NotImplementedError(
            "DoclingAdapter.adapt_document() sera implémenté en Phase 2."
        )


__all__ = ["DoclingAdapter"]
