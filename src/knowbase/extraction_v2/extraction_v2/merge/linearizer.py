"""
Linearizer - Génère full_text avec marqueurs pour OSMOSE.

Format de linéarisation conforme à OSMOSIS_EXTRACTION_V2_DECISIONS.md - Décision 1.

Marqueurs:
- [PAGE n | TYPE=xxx] : Début de page
- [TITLE level=n] : Titre
- [PARAGRAPH] : Paragraphe
- [TABLE_START id=x]...[TABLE_END] : Table en Markdown
- [VISUAL_ENRICHMENT id=x confidence=y]...[END_VISUAL_ENRICHMENT] : Vision

Spécification BNF:
    marker       ::= '[' marker_type attributes? ']'
    marker_type  ::= 'PAGE' | 'TITLE' | 'PARAGRAPH' | 'TABLE_START' | 'TABLE_END'
                   | 'VISUAL_ENRICHMENT' | 'END_VISUAL_ENRICHMENT'
    attributes   ::= (key '=' value)+
    key          ::= [a-z_]+
    value        ::= [a-zA-Z0-9_.-]+

Implémentation complète en Phase 5.
"""

from __future__ import annotations
from typing import List, Optional, Tuple
import logging
import re

from knowbase.extraction_v2.models import PageIndex
from knowbase.extraction_v2.merge.merger import MergedPageOutput

logger = logging.getLogger(__name__)


# === Regex pour parsing des marqueurs ===

MARKER_PATTERN = re.compile(
    r"^\[(PAGE|TITLE|PARAGRAPH|TABLE_START|TABLE_END|VISUAL_ENRICHMENT|END_VISUAL_ENRICHMENT)[^\]]*\]"
)


class Linearizer:
    """
    Génère full_text avec marqueurs pour OSMOSE.

    Le full_text est linéarisé avec marqueurs explicites permettant
    de retracer l'origine de chaque portion (page, type de contenu).

    Exemple de sortie:
    ```
    [PAGE 6 | TYPE=ARCHITECTURE_DIAGRAM]
    [TITLE level=1] Target Architecture Overview

    [TABLE_START id=tbl_1]
    | Component | Role |
    | SAP BTP   | Integration Platform |
    [TABLE_END]

    [VISUAL_ENRICHMENT id=vision_6_1 confidence=0.82]
    diagram_type: architecture_diagram
    visible_elements:
    - [E1|box] "SAP Enterprise Cloud Services"
    [END_VISUAL_ENRICHMENT]

    [PARAGRAPH]
    This architecture enables seamless integration between...
    ```

    Usage:
        >>> linearizer = Linearizer()
        >>> full_text, page_index = linearizer.linearize(merged_pages)
        >>> print(full_text)  # Pour OSMOSE

    Note: Implémentation complète en Phase 5.
    """

    def __init__(self):
        """Initialise le linearizer."""
        logger.info("[Linearizer] Created")

    def linearize(
        self,
        merged_pages: List[MergedPageOutput],
    ) -> Tuple[str, List[PageIndex]]:
        """
        Linéarise un document complet.

        Args:
            merged_pages: Pages fusionnées (Docling + Vision)

        Returns:
            Tuple (full_text, page_index)
            - full_text: Texte linéarisé avec marqueurs
            - page_index: Mapping offsets → pages

        Raises:
            NotImplementedError: Implémentation en Phase 5
        """
        raise NotImplementedError(
            "Linearizer.linearize() sera implémenté en Phase 5."
        )

    def linearize_page(
        self,
        merged_page: MergedPageOutput,
    ) -> str:
        """
        Linéarise une seule page.

        Args:
            merged_page: Page fusionnée

        Returns:
            Texte linéarisé pour cette page

        Raises:
            NotImplementedError: Implémentation en Phase 5
        """
        raise NotImplementedError(
            "Linearizer.linearize_page() sera implémenté en Phase 5."
        )

    @staticmethod
    def format_page_marker(
        page_index: int,
        page_type: Optional[str] = None,
    ) -> str:
        """Formate un marqueur de page."""
        if page_type:
            return f"[PAGE {page_index} | TYPE={page_type}]"
        return f"[PAGE {page_index}]"

    @staticmethod
    def format_title_marker(level: int, text: str) -> str:
        """Formate un marqueur de titre."""
        return f"[TITLE level={level}] {text}"

    @staticmethod
    def format_paragraph_marker(text: str) -> str:
        """Formate un marqueur de paragraphe."""
        return f"[PARAGRAPH]\n{text}"

    @staticmethod
    def format_table_markers(table_id: str, markdown_content: str) -> str:
        """Formate les marqueurs de table."""
        return f"[TABLE_START id={table_id}]\n{markdown_content}\n[TABLE_END]"

    @staticmethod
    def is_marker_line(line: str) -> bool:
        """Vérifie si une ligne est un marqueur."""
        return bool(MARKER_PATTERN.match(line.strip()))

    @staticmethod
    def parse_marker(line: str) -> Optional[Tuple[str, dict]]:
        """
        Parse une ligne de marqueur.

        Args:
            line: Ligne à parser

        Returns:
            Tuple (marker_type, attributes) ou None
        """
        line = line.strip()
        if not line.startswith("["):
            return None

        # Extraire le type et les attributs
        match = re.match(r"\[(\w+)([^\]]*)\]", line)
        if not match:
            return None

        marker_type = match.group(1)
        attrs_str = match.group(2).strip()

        # Parser les attributs
        attrs = {}
        if attrs_str:
            # Format: key=value ou simple value
            for part in attrs_str.split():
                if "=" in part:
                    key, value = part.split("=", 1)
                    attrs[key] = value
                else:
                    # Value simple (ex: numéro de page)
                    attrs["value"] = part

        return marker_type, attrs


__all__ = [
    "Linearizer",
    "MARKER_PATTERN",
]
