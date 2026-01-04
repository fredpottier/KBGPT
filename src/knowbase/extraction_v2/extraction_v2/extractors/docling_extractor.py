"""
DoclingExtractor - Extracteur unifié basé sur Docling.

Supporte tous les formats Office: PDF, DOCX, PPTX, XLSX.

Implémentation complète en Phase 2.
"""

from __future__ import annotations
from typing import Any, Dict, List, Optional, Tuple
import logging

from knowbase.extraction_v2.models import VisionUnit

logger = logging.getLogger(__name__)


class DoclingExtractor:
    """
    Extracteur unifié basé sur Docling.

    Supporte:
    - PDF (documents, présentations scannées)
    - DOCX (documents Word)
    - PPTX (présentations PowerPoint)
    - XLSX (tableurs Excel)
    - Images (PNG, JPEG, etc. via OCR)

    Usage:
        >>> extractor = DoclingExtractor()
        >>> units = await extractor.extract_to_units("/path/to/doc.pdf")
        >>> for unit in units:
        ...     print(f"Page {unit.index}: {unit.text_blocks_count} blocks")

    Note: Implémentation complète en Phase 2.
    """

    def __init__(self):
        """Initialise l'extracteur Docling."""
        self._converter = None
        self._initialized = False
        logger.info("[DoclingExtractor] Created (not yet initialized)")

    async def initialize(self) -> None:
        """
        Initialise le convertisseur Docling.

        Charge les modèles nécessaires.
        """
        if self._initialized:
            return

        try:
            from docling.document_converter import DocumentConverter
            self._converter = DocumentConverter()
            self._initialized = True
            logger.info("[DoclingExtractor] ✅ Docling converter initialized")
        except ImportError as e:
            logger.error(f"[DoclingExtractor] ❌ Failed to import Docling: {e}")
            raise ImportError(
                "Docling n'est pas installé. Installer avec: pip install docling>=2.14.0"
            ) from e

    async def extract_to_units(
        self,
        file_path: str,
        include_raw_output: bool = False,
    ) -> List[VisionUnit]:
        """
        Extrait un document et retourne une liste de VisionUnits.

        Chaque VisionUnit correspond à une page/slide.

        Args:
            file_path: Chemin vers le document
            include_raw_output: Inclure la sortie brute Docling

        Returns:
            Liste de VisionUnits (une par page/slide)

        Raises:
            NotImplementedError: Implémentation en Phase 2
        """
        raise NotImplementedError(
            "DoclingExtractor.extract_to_units() sera implémenté en Phase 2."
        )

    async def extract_document(
        self,
        file_path: str,
    ) -> Tuple[str, Dict[str, Any]]:
        """
        Extrait un document et retourne (markdown, json_struct).

        Args:
            file_path: Chemin vers le document

        Returns:
            Tuple (markdown, json_struct)

        Raises:
            NotImplementedError: Implémentation en Phase 2
        """
        raise NotImplementedError(
            "DoclingExtractor.extract_document() sera implémenté en Phase 2."
        )

    def get_supported_formats(self) -> List[str]:
        """Retourne la liste des formats supportés."""
        return ["pdf", "docx", "pptx", "xlsx", "png", "jpg", "jpeg", "tiff", "bmp"]

    def is_format_supported(self, file_path: str) -> bool:
        """Vérifie si le format est supporté."""
        ext = file_path.lower().rsplit(".", 1)[-1]
        return ext in self.get_supported_formats()


__all__ = ["DoclingExtractor"]
