"""
ZoneSegmenter - Segmentation des pages en zones logiques.

Segmente chaque page d'un document en trois zones :
- TOP : Premieres lignes significatives (headers, titres)
- MAIN : Corps du contenu
- BOTTOM : Dernieres lignes significatives (footers, legal)

Ce composant est agnostique et ne fait aucune hypothese metier.

Spec: doc/ongoing/ADR_DOCUMENT_STRUCTURAL_AWARENESS.md - Section 4.1
"""

from __future__ import annotations
from typing import List, Optional
import logging

from knowbase.extraction_v2.context.structural.models import (
    Zone,
    ZoneConfig,
    ZonedLine,
    PageZones,
    StructuralConfidence,
    is_significant_line,
)


logger = logging.getLogger(__name__)


class ZoneSegmenter:
    """
    Segmente les pages d'un document en zones logiques.

    Usage:
        >>> segmenter = ZoneSegmenter()
        >>> page_zones = segmenter.segment_page("Line 1\\nLine 2\\n...", page_index=0)
        >>> print(page_zones.top_lines)

        >>> all_zones = segmenter.segment_document(["Page 1 text", "Page 2 text"])
    """

    def __init__(self, config: Optional[ZoneConfig] = None):
        """
        Initialise le segmenter.

        Args:
            config: Configuration de segmentation. Si None, utilise les valeurs par defaut.
        """
        self.config = config or ZoneConfig()

    def segment_page(self, page_text: str, page_index: int = 0) -> PageZones:
        """
        Segmente une page en zones TOP/MAIN/BOTTOM.

        Args:
            page_text: Texte brut de la page
            page_index: Index de la page dans le document

        Returns:
            PageZones avec les lignes classees par zone
        """
        if not page_text:
            return PageZones(page_index=page_index)

        # Separer en lignes
        lines = page_text.split('\n')

        # Filtrer les lignes significatives avec leurs indices originaux
        significant_lines: List[tuple[int, str]] = []
        for i, line in enumerate(lines):
            if is_significant_line(line, self.config):
                cleaned = line.strip()
                if self.config.normalize_whitespace:
                    cleaned = ' '.join(cleaned.split())
                significant_lines.append((i, cleaned))

        if not significant_lines:
            return PageZones(page_index=page_index, total_lines=len(lines))

        # Determiner les zones
        total_significant = len(significant_lines)
        top_count = min(self.config.top_lines_count, total_significant // 3 + 1)
        bottom_count = min(self.config.bottom_lines_count, total_significant // 3 + 1)

        # S'assurer qu'on a au moins une ligne MAIN si possible
        if total_significant > 2:
            remaining_for_main = total_significant - top_count - bottom_count
            if remaining_for_main < 1:
                # Reduire top et bottom pour laisser de la place a main
                top_count = max(1, total_significant // 3)
                bottom_count = max(1, total_significant // 3)

        # Classifier les lignes
        top_lines: List[ZonedLine] = []
        main_lines: List[ZonedLine] = []
        bottom_lines: List[ZonedLine] = []

        for idx, (original_index, text) in enumerate(significant_lines):
            if idx < top_count:
                zone = Zone.TOP
                zoned_line = ZonedLine(text=text, zone=zone, line_index=original_index)
                top_lines.append(zoned_line)
            elif idx >= total_significant - bottom_count:
                zone = Zone.BOTTOM
                zoned_line = ZonedLine(text=text, zone=zone, line_index=original_index)
                bottom_lines.append(zoned_line)
            else:
                zone = Zone.MAIN
                zoned_line = ZonedLine(text=text, zone=zone, line_index=original_index)
                main_lines.append(zoned_line)

        return PageZones(
            page_index=page_index,
            top_lines=top_lines,
            main_lines=main_lines,
            bottom_lines=bottom_lines,
            total_lines=len(lines),
        )

    def segment_document(self, pages_text: List[str]) -> List[PageZones]:
        """
        Segmente toutes les pages d'un document.

        Args:
            pages_text: Liste des textes par page (index 0 = premiere page)

        Returns:
            Liste de PageZones pour chaque page
        """
        if not pages_text:
            return []

        result = []
        for i, page_text in enumerate(pages_text):
            page_zones = self.segment_page(page_text, page_index=i)
            result.append(page_zones)

        logger.info(
            f"[ZoneSegmenter] Segmented {len(result)} pages"
        )

        return result

    def get_structural_confidence(self, page_count: int) -> StructuralConfidence:
        """
        Determine la confiance structurelle basee sur le nombre de pages.

        Args:
            page_count: Nombre de pages du document

        Returns:
            StructuralConfidence (HIGH/MEDIUM/LOW)
        """
        return StructuralConfidence.from_page_count(page_count)


# === Singleton ===

_segmenter_instance: Optional[ZoneSegmenter] = None


def get_zone_segmenter(config: Optional[ZoneConfig] = None) -> ZoneSegmenter:
    """
    Retourne l'instance singleton du ZoneSegmenter.

    Args:
        config: Configuration optionnelle (utilisee seulement a la premiere creation)

    Returns:
        Instance de ZoneSegmenter
    """
    global _segmenter_instance
    if _segmenter_instance is None:
        _segmenter_instance = ZoneSegmenter(config)
    return _segmenter_instance


__all__ = [
    "ZoneSegmenter",
    "get_zone_segmenter",
]
