"""
Linearizer - Genere full_text avec marqueurs pour OSMOSE.

Format de linearisation conforme a OSMOSIS_EXTRACTION_V2_DECISIONS.md - Decision 1.

Marqueurs:
- [PAGE n | TYPE=xxx] : Debut de page
- [TITLE level=n] : Titre
- [PARAGRAPH] : Paragraphe
- [TABLE_START id=x]...[TABLE_END] : Table en Markdown
- [TABLE_SUMMARY id=x]...[TABLE_RAW]...[TABLE_END] : Table avec résumé LLM (QW-1)
- [VISUAL_ENRICHMENT id=x confidence=y]...[END_VISUAL_ENRICHMENT] : Vision

Specification BNF:
    marker       ::= '[' marker_type attributes? ']'
    marker_type  ::= 'PAGE' | 'TITLE' | 'PARAGRAPH' | 'TABLE_START' | 'TABLE_END'
                   | 'TABLE_SUMMARY' | 'TABLE_RAW'
                   | 'VISUAL_ENRICHMENT' | 'END_VISUAL_ENRICHMENT'
    attributes   ::= (key '=' value)+
    key          ::= [a-z_]+
    value        ::= [a-zA-Z0-9_.-]+
"""

from __future__ import annotations
from typing import List, Optional, Tuple
import logging
import re

from knowbase.extraction_v2.models import PageIndex
from knowbase.extraction_v2.merge.merger import MergedPageOutput
from knowbase.extraction_v2.models.elements import TextBlock, TableData

logger = logging.getLogger(__name__)


# === Regex pour parsing des marqueurs ===

MARKER_PATTERN = re.compile(
    r"^\[(PAGE|TITLE|PARAGRAPH|TABLE_START|TABLE_END|TABLE_SUMMARY|TABLE_RAW|VISUAL_ENRICHMENT|END_VISUAL_ENRICHMENT)[^\]]*\]"
)


class Linearizer:
    """
    Genere full_text avec marqueurs pour OSMOSE.

    Le full_text est linearise avec marqueurs explicites permettant
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
    """

    def __init__(self, include_vision: bool = True, include_tables: bool = True):
        """
        Initialise le linearizer.

        Args:
            include_vision: Inclure les enrichissements Vision
            include_tables: Inclure les tables en Markdown
        """
        self.include_vision = include_vision
        self.include_tables = include_tables
        logger.info(
            f"[Linearizer] Created with vision={include_vision}, tables={include_tables}"
        )

    def linearize(
        self,
        merged_pages: List[MergedPageOutput],
    ) -> Tuple[str, List[PageIndex]]:
        """
        Linearise un document complet.

        Args:
            merged_pages: Pages fusionnees (Docling + Vision)

        Returns:
            Tuple (full_text, page_index)
            - full_text: Texte linearise avec marqueurs
            - page_index: Mapping offsets -> pages
        """
        full_text_parts = []
        page_indices = []
        current_offset = 0

        for merged_page in merged_pages:
            # Lineariser cette page
            page_text = self.linearize_page(merged_page)

            # Enregistrer l'offset de debut
            start_offset = current_offset

            # Ajouter le texte
            full_text_parts.append(page_text)

            # Calculer l'offset de fin
            end_offset = start_offset + len(page_text)

            # Creer l'index
            page_indices.append(PageIndex(
                page_index=merged_page.page_index,
                start_offset=start_offset,
                end_offset=end_offset,
            ))

            # Mettre a jour l'offset courant (+ 2 pour le \n\n entre pages)
            current_offset = end_offset + 2

        # Joindre avec double saut de ligne
        full_text = "\n\n".join(full_text_parts)

        logger.info(
            f"[Linearizer] Linearized {len(merged_pages)} pages, "
            f"{len(full_text)} chars"
        )

        return full_text, page_indices

    def linearize_page(
        self,
        merged_page: MergedPageOutput,
    ) -> str:
        """
        Linearise une seule page.

        Args:
            merged_page: Page fusionnee

        Returns:
            Texte linearise pour cette page
        """
        parts = []

        # 1. Marqueur de page
        page_type = self._detect_page_type(merged_page)
        page_marker = self.format_page_marker(merged_page.page_index, page_type)
        parts.append(page_marker)

        # 2. Titre (si present)
        if merged_page.title:
            title_marker = self.format_title_marker(1, merged_page.title)
            parts.append(title_marker)

        # 3. Blocs de texte
        for block in merged_page.base_blocks:
            block_text = self._format_block(block)
            if block_text:
                parts.append(block_text)

        # 4. Tables (si incluses)
        if self.include_tables:
            for table in merged_page.base_tables:
                table_text = self._format_table(table)
                if table_text:
                    parts.append(table_text)

        # 5. Enrichissement Vision (si inclus et present)
        if self.include_vision and merged_page.vision_enrichment:
            vision_text = merged_page.vision_enrichment.to_vision_text(
                page_index=merged_page.page_index
            )
            parts.append(vision_text)

        return "\n\n".join(parts)

    def _detect_page_type(self, merged_page: MergedPageOutput) -> Optional[str]:
        """
        Detecte le type de page (pour le marqueur).

        Args:
            merged_page: Page fusionnee

        Returns:
            Type de page ou None
        """
        # Si Vision a detecte un type de diagramme
        if merged_page.vision_enrichment:
            kind = merged_page.vision_enrichment.kind
            if kind and kind not in ("unknown", "parse_error", "api_error"):
                return kind.upper().replace(" ", "_")

        # Si gating a declenche Vision (mais pas d'extraction)
        if merged_page.gating_decision:
            if merged_page.gating_decision.requires_vision:
                return "VISUAL_CONTENT"

        # Par defaut
        return None

    def _format_block(self, block: TextBlock) -> str:
        """
        Formate un bloc de texte avec son marqueur.

        Args:
            block: Bloc de texte

        Returns:
            Texte formate
        """
        if not block.text or not block.text.strip():
            return ""

        if block.is_heading:
            return self.format_title_marker(block.level or 1, block.text)
        else:
            return self.format_paragraph_marker(block.text)

    def _format_table(self, table: TableData) -> str:
        """
        Formate une table avec marqueurs.

        Si un résumé LLM (QW-1) est disponible, utilise le format enrichi:
        [TABLE_SUMMARY id=x]
        {summary en langage naturel}
        [TABLE_RAW]
        {markdown brut}
        [TABLE_END]

        Sinon, utilise le format standard:
        [TABLE_START id=x]
        {markdown}
        [TABLE_END]

        Args:
            table: Donnees de la table

        Returns:
            Table formatee
        """
        # Construire le Markdown de la table
        markdown_lines = []

        # Headers
        if table.headers:
            header_row = "| " + " | ".join(table.headers) + " |"
            markdown_lines.append(header_row)

            # Separator
            separator = "| " + " | ".join(["---"] * len(table.headers)) + " |"
            markdown_lines.append(separator)

        # Data rows
        for row in table.cells:
            row_text = "| " + " | ".join(str(cell) for cell in row) + " |"
            markdown_lines.append(row_text)

        if not markdown_lines:
            return ""

        markdown_content = "\n".join(markdown_lines)

        # QW-1: Si un résumé est disponible, utiliser le format enrichi
        if table.summary:
            return self.format_table_with_summary(
                table.table_id,
                table.summary,
                markdown_content
            )

        # Sinon, format standard
        return self.format_table_markers(table.table_id, markdown_content)

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
        """Formate les marqueurs de table (format standard sans résumé)."""
        return f"[TABLE_START id={table_id}]\n{markdown_content}\n[TABLE_END]"

    @staticmethod
    def format_table_with_summary(table_id: str, summary: str, markdown_content: str) -> str:
        """
        Formate une table avec résumé LLM (QW-1).

        Le résumé est placé en premier pour optimiser l'embedding sémantique.
        Le Markdown brut est conservé dans [TABLE_RAW] pour traçabilité.

        Args:
            table_id: Identifiant de la table
            summary: Résumé en langage naturel généré par LLM
            markdown_content: Markdown brut de la table

        Returns:
            Format enrichi avec résumé
        """
        return (
            f"[TABLE_SUMMARY id={table_id}]\n"
            f"{summary}\n"
            f"[TABLE_RAW]\n"
            f"{markdown_content}\n"
            f"[TABLE_END]"
        )

    @staticmethod
    def is_marker_line(line: str) -> bool:
        """Verifie si une ligne est un marqueur."""
        return bool(MARKER_PATTERN.match(line.strip()))

    @staticmethod
    def parse_marker(line: str) -> Optional[Tuple[str, dict]]:
        """
        Parse une ligne de marqueur.

        Args:
            line: Ligne a parser

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
                elif part != "|":
                    # Value simple (ex: numero de page)
                    attrs["value"] = part

        return marker_type, attrs

    def extract_page_text(
        self,
        full_text: str,
        page_indices: List[PageIndex],
        page_index: int,
    ) -> Optional[str]:
        """
        Extrait le texte d'une page specifique.

        Args:
            full_text: Texte complet linearise
            page_indices: Index des pages
            page_index: Index de la page a extraire

        Returns:
            Texte de la page ou None si non trouve
        """
        for pi in page_indices:
            if pi.page_index == page_index:
                return full_text[pi.start_offset:pi.end_offset]
        return None


__all__ = [
    "Linearizer",
    "MARKER_PATTERN",
]
