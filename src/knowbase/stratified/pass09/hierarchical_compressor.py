"""
OSMOSE Pipeline V2 - Pass 0.9 Hierarchical Compressor
======================================================
Compresse les résumés de sections en meta-document structuré.
"""

import logging
from typing import Dict, List, Optional

from knowbase.stratified.pass09.models import (
    GlobalViewCoverage,
    Pass09Config,
    SectionSummary,
)

logger = logging.getLogger(__name__)


class HierarchicalCompressor:
    """Compresse les résumés de sections en meta-document."""

    def __init__(self, config: Optional[Pass09Config] = None):
        """
        Initialise le HierarchicalCompressor.

        Args:
            config: Configuration Pass 0.9
        """
        self.config = config or Pass09Config()

    def compress(
        self,
        section_summaries: Dict[str, SectionSummary],
        sections_order: List[str],
        doc_title: str = "",
    ) -> tuple[str, str, GlobalViewCoverage]:
        """
        Compresse les résumés en meta-document.

        Args:
            section_summaries: Dict[section_id, SectionSummary]
            sections_order: Ordre des sections (liste d'IDs)
            doc_title: Titre du document

        Returns:
            Tuple (meta_document, toc_enhanced, coverage)
        """
        logger.info(f"[OSMOSE:Pass0.9] Compressing {len(section_summaries)} summaries...")

        # Calculer la couverture
        coverage = self._calculate_coverage(section_summaries)

        # Construire le meta-document structuré
        meta_document = self._build_meta_document(
            section_summaries=section_summaries,
            sections_order=sections_order,
            doc_title=doc_title,
        )

        # Construire la TOC enrichie
        toc_enhanced = self._build_enhanced_toc(
            section_summaries=section_summaries,
            sections_order=sections_order,
        )

        # Vérifier les contraintes de taille
        meta_document = self._enforce_size_limits(meta_document, coverage)

        coverage.chars_meta_document = len(meta_document)

        logger.info(
            f"[OSMOSE:Pass0.9] Meta-document: {len(meta_document)} chars "
            f"(compression: {coverage.compression_ratio:.1%})"
        )

        return meta_document, toc_enhanced, coverage

    def _calculate_coverage(
        self,
        section_summaries: Dict[str, SectionSummary],
    ) -> GlobalViewCoverage:
        """Calcule les statistiques de couverture."""
        coverage = GlobalViewCoverage()

        for summary in section_summaries.values():
            coverage.sections_total += 1
            coverage.chars_original += summary.char_count_original

            if summary.method == "llm":
                coverage.sections_summarized += 1
            elif summary.method == "verbatim":
                coverage.sections_verbatim += 1
            elif summary.method == "truncated":
                # Truncated compte comme summarized (fallback)
                coverage.sections_summarized += 1
            elif summary.method == "skipped":
                coverage.sections_skipped += 1

        return coverage

    def _build_meta_document(
        self,
        section_summaries: Dict[str, SectionSummary],
        sections_order: List[str],
        doc_title: str,
    ) -> str:
        """
        Construit le meta-document structuré.

        Format:
        # Document: [titre]

        ## 1. [Section niveau 1]
        [résumé]
        Concepts: concept1, concept2
        Types: definitional, prescriptive

        ### 1.1 [Section niveau 2]
        [résumé]
        ...
        """
        lines = []

        # En-tête
        if doc_title:
            lines.append(f"# Document: {doc_title}")
            lines.append("")

        # Sections dans l'ordre
        for section_id in sections_order:
            summary = section_summaries.get(section_id)
            if not summary:
                continue

            # Niveau de heading basé sur le niveau de section
            heading_prefix = "#" * min(summary.level + 1, 4)  # Max #### pour éviter pollution
            lines.append(f"{heading_prefix} {summary.section_title}")
            lines.append("")

            # Résumé
            if summary.summary:
                lines.append(summary.summary)
                lines.append("")

            # Métadonnées enrichies (si présentes)
            metadata_lines = []
            if summary.concepts_mentioned:
                concepts_str = ", ".join(summary.concepts_mentioned[:10])  # Max 10
                metadata_lines.append(f"**Concepts:** {concepts_str}")

            if summary.assertion_types:
                types_str = ", ".join(summary.assertion_types)
                metadata_lines.append(f"**Types:** {types_str}")

            if summary.key_values:
                values_str = ", ".join(summary.key_values[:8])  # Max 8
                metadata_lines.append(f"**Valeurs:** {values_str}")

            if metadata_lines:
                lines.extend(metadata_lines)
                lines.append("")

        return "\n".join(lines)

    def _build_enhanced_toc(
        self,
        section_summaries: Dict[str, SectionSummary],
        sections_order: List[str],
    ) -> str:
        """
        Construit une table des matières enrichie.

        Format:
        1. Section A [3 concepts, definitional/prescriptive]
           1.1 Sous-section A1 [2 concepts, factual]
           1.2 Sous-section A2 [4 concepts, procedural]
        2. Section B [5 concepts, definitional]
        ...
        """
        lines = ["# Table des Matières Enrichie", ""]

        section_counters = [0, 0, 0, 0, 0]  # Pour numérotation hiérarchique

        for section_id in sections_order:
            summary = section_summaries.get(section_id)
            if not summary:
                continue

            level = summary.level - 1  # 0-indexed
            if level < 0:
                level = 0
            if level >= len(section_counters):
                level = len(section_counters) - 1

            # Incrémenter le compteur du niveau et reset les niveaux inférieurs
            section_counters[level] += 1
            for i in range(level + 1, len(section_counters)):
                section_counters[i] = 0

            # Construire le numéro de section
            section_num = ".".join(
                str(section_counters[i])
                for i in range(level + 1)
                if section_counters[i] > 0
            )

            # Indentation
            indent = "  " * level

            # Info enrichie
            n_concepts = len(summary.concepts_mentioned)
            types_str = "/".join(summary.assertion_types[:3]) if summary.assertion_types else "info"

            line = f"{indent}{section_num}. {summary.section_title}"
            if n_concepts > 0 or summary.assertion_types:
                line += f" [{n_concepts} concepts, {types_str}]"

            lines.append(line)

        return "\n".join(lines)

    def _enforce_size_limits(
        self,
        meta_document: str,
        coverage: GlobalViewCoverage,
    ) -> str:
        """
        Applique les contraintes de taille au meta-document.

        Si trop long: compression agressive (raccourcir les résumés)
        Si trop court: normal (le document source était court)
        """
        current_len = len(meta_document)

        # Trop long - besoin de compression
        if current_len > self.config.meta_document_max_chars:
            logger.warning(
                f"[OSMOSE:Pass0.9] Meta-document trop long ({current_len} chars), "
                f"tronquage à {self.config.meta_document_max_chars}"
            )
            # Tronquer intelligemment avec marge de sécurité
            target = self.config.meta_document_max_chars - 100  # Marge de sécurité
            return self._smart_truncate(meta_document, target)

        # Dans les limites
        return meta_document

    def _smart_truncate(self, text: str, max_chars: int) -> str:
        """
        Tronque intelligemment en préservant la structure.

        Stratégie:
        - Garder les headings
        - Tronquer les résumés longs
        - Supprimer les métadonnées en dernier
        """
        if len(text) <= max_chars:
            return text

        lines = text.split("\n")
        result_lines = []
        current_len = 0

        for line in lines:
            line_len = len(line) + 1  # +1 pour le newline

            # Toujours garder les headings
            if line.startswith("#"):
                result_lines.append(line)
                current_len += line_len
                continue

            # Vérifier si on peut ajouter cette ligne
            if current_len + line_len <= max_chars - 100:  # Marge de sécurité
                result_lines.append(line)
                current_len += line_len
            else:
                # Tronquer cette ligne si c'est du contenu
                remaining = max_chars - current_len - 50
                if remaining > 50 and not line.startswith("**"):
                    result_lines.append(line[:remaining] + "...")
                    current_len += remaining + 3
                break

        result_lines.append("")
        result_lines.append("[... document tronqué pour respecter limite tokens ...]")

        return "\n".join(result_lines)
