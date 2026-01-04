"""
VDSFallback - Fallback pour le signal VDS.

Utilisé quand Docling ne fournit pas assez de détails sur les shapes/connecteurs.
- PDF: PyMuPDF page.get_drawings()
- PPTX: python-pptx MSO_SHAPE_TYPE

Implémentation complète en Phase 2.
"""

from __future__ import annotations
from typing import Any, Dict, List, Optional
import logging

logger = logging.getLogger(__name__)


class VDSFallback:
    """
    Fallback pour la détection VDS (Vector Drawing Signal).

    Utilisé quand Docling ne fournit pas assez d'informations
    sur les shapes vectoriels et connecteurs.

    Stratégie:
    - PDF: PyMuPDF page.get_drawings()
    - PPTX: python-pptx MSO_SHAPE_TYPE

    Usage:
        >>> fallback = VDSFallback()
        >>> connectors = fallback.count_connectors_pdf(pdf_path, page_index)
        >>> connectors = fallback.count_connectors_pptx(pptx_path, slide_index)

    Note: Implémentation complète en Phase 2.
    """

    def __init__(self):
        """Initialise le fallback VDS."""
        logger.info("[VDSFallback] Created")

    def count_connectors_pdf(
        self,
        pdf_path: str,
        page_index: int,
    ) -> int:
        """
        Compte les connecteurs dans une page PDF via PyMuPDF.

        Args:
            pdf_path: Chemin vers le PDF
            page_index: Index de la page

        Returns:
            Nombre de connecteurs détectés

        Raises:
            NotImplementedError: Implémentation en Phase 2
        """
        raise NotImplementedError(
            "VDSFallback.count_connectors_pdf() sera implémenté en Phase 2."
        )

    def count_connectors_pptx(
        self,
        pptx_path: str,
        slide_index: int,
    ) -> int:
        """
        Compte les connecteurs dans une slide PPTX via python-pptx.

        Args:
            pptx_path: Chemin vers le PPTX
            slide_index: Index de la slide

        Returns:
            Nombre de connecteurs détectés

        Raises:
            NotImplementedError: Implémentation en Phase 2
        """
        raise NotImplementedError(
            "VDSFallback.count_connectors_pptx() sera implémenté en Phase 2."
        )

    def get_vector_density_pdf(
        self,
        pdf_path: str,
        page_index: int,
    ) -> float:
        """
        Calcule la densité vectorielle d'une page PDF.

        Args:
            pdf_path: Chemin vers le PDF
            page_index: Index de la page

        Returns:
            Densité vectorielle (0.0 - 1.0)

        Raises:
            NotImplementedError: Implémentation en Phase 2
        """
        raise NotImplementedError(
            "VDSFallback.get_vector_density_pdf() sera implémenté en Phase 2."
        )


__all__ = ["VDSFallback"]
