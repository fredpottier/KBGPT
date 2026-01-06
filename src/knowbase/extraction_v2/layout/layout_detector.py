"""
Layout Detector - MT-1: Layout-Aware Chunking.

Detecte les regions structurelles dans le full_text linearise par le Linearizer.
Ces regions sont utilisees par HybridAnchorChunker pour ne jamais couper
les unites atomiques (tableaux, enrichissements Vision).

Specification ADR: doc/ongoing/ADR_REDUCTO_PARSING_PRIMITIVES.md

Regle non-negociable: "Ne jamais couper un tableau"

Regions atomiques (ne peuvent PAS etre coupees):
- TABLE: Entre [TABLE_START] et [TABLE_END] ou [TABLE_SUMMARY] et [TABLE_END]
- VISION: Entre [VISUAL_ENRICHMENT] et [END_VISUAL_ENRICHMENT]

Regions divisibles (peuvent etre coupees si trop grandes):
- PARAGRAPH: Bloc [PARAGRAPH]
- TITLE: Bloc [TITLE level=n]
- PAGE_MARKER: Marqueur [PAGE n]

Author: OSMOSE Phase 2
Date: 2026-01
"""

from __future__ import annotations
from dataclasses import dataclass, field
from enum import Enum
from typing import List, Optional, Tuple
import re
import logging

logger = logging.getLogger(__name__)


class RegionType(str, Enum):
    """Types de regions structurelles."""
    # Regions atomiques (ne pas couper)
    TABLE = "table"
    VISION = "vision"

    # Regions divisibles
    PAGE_MARKER = "page_marker"
    TITLE = "title"
    PARAGRAPH = "paragraph"
    TEXT = "text"  # Texte libre sans marqueur


@dataclass
class LayoutRegion:
    """
    Region structurelle dans le full_text.

    Attributes:
        type: Type de la region
        char_start: Position de debut (inclusive)
        char_end: Position de fin (exclusive)
        text: Contenu textuel de la region
        atomic: Si True, ne doit JAMAIS etre coupee
        metadata: Metadonnees additionnelles (id de table, etc.)
    """
    type: RegionType
    char_start: int
    char_end: int
    text: str
    atomic: bool = False
    metadata: dict = field(default_factory=dict)

    @property
    def char_length(self) -> int:
        """Longueur en caracteres."""
        return self.char_end - self.char_start

    def overlaps_range(self, start: int, end: int) -> bool:
        """Verifie si cette region chevauche une plage donnee."""
        return self.char_start < end and self.char_end > start

    def contains_range(self, start: int, end: int) -> bool:
        """Verifie si cette region contient entierement une plage."""
        return self.char_start <= start and self.char_end >= end

    def is_contained_by_range(self, start: int, end: int) -> bool:
        """Verifie si cette region est entierement contenue dans une plage."""
        return start <= self.char_start and end >= self.char_end

    def to_dict(self) -> dict:
        """Serialise en dictionnaire."""
        return {
            "type": self.type.value,
            "char_start": self.char_start,
            "char_end": self.char_end,
            "atomic": self.atomic,
            "metadata": self.metadata,
            "char_length": self.char_length,
        }


# === Regex pour detection des marqueurs ===

# Tables (formats standard et avec resume QW-1)
TABLE_START_PATTERN = re.compile(
    r"\[TABLE_(?:START|SUMMARY)\s+id=([^\]]+)\]",
    re.IGNORECASE
)
TABLE_END_PATTERN = re.compile(r"\[TABLE_END\]", re.IGNORECASE)

# Vision enrichment
VISION_START_PATTERN = re.compile(
    r"\[VISUAL_ENRICHMENT\s+id=([^\s\]]+)(?:\s+confidence=([0-9.]+))?\]",
    re.IGNORECASE
)
VISION_END_PATTERN = re.compile(r"\[END_VISUAL_ENRICHMENT\]", re.IGNORECASE)

# Paragraphes et titres
PARAGRAPH_PATTERN = re.compile(r"\[PARAGRAPH\]", re.IGNORECASE)
TITLE_PATTERN = re.compile(r"\[TITLE\s+level=(\d+)\]\s*(.+)", re.IGNORECASE)

# Pages
PAGE_PATTERN = re.compile(
    r"\[PAGE\s+(\d+)(?:\s*\|\s*TYPE=([^\]]+))?\]",
    re.IGNORECASE
)


class LayoutDetector:
    """
    Detecte les regions structurelles dans le full_text linearise.

    Usage:
        detector = LayoutDetector()
        regions = detector.detect_regions(full_text)

        for region in regions:
            if region.atomic:
                print(f"Region atomique: {region.type} [{region.char_start}:{region.char_end}]")

    La liste des regions couvre tout le texte sans chevauchement,
    triee par position (char_start croissant).
    """

    def __init__(self):
        """Initialise le detecteur."""
        logger.info("[LayoutDetector] Initialized")

    def detect_regions(self, full_text: str) -> List[LayoutRegion]:
        """
        Detecte toutes les regions dans le full_text.

        Args:
            full_text: Texte linearise avec marqueurs

        Returns:
            Liste de LayoutRegion couvrant tout le texte,
            triee par char_start, sans chevauchement
        """
        if not full_text:
            return []

        # 1. Detecter les regions atomiques (tables, vision)
        atomic_regions = self._detect_atomic_regions(full_text)

        # 2. Detecter les paragraphes et titres
        block_regions = self._detect_block_regions(full_text)

        # 3. Fusionner et combler les trous
        all_regions = self._merge_and_fill_gaps(
            full_text, atomic_regions, block_regions
        )

        # 4. Trier par position
        all_regions.sort(key=lambda r: r.char_start)

        # Stats
        atomic_count = sum(1 for r in all_regions if r.atomic)
        table_count = sum(1 for r in all_regions if r.type == RegionType.TABLE)
        vision_count = sum(1 for r in all_regions if r.type == RegionType.VISION)

        logger.info(
            f"[LayoutDetector] Detected {len(all_regions)} regions "
            f"(atomic={atomic_count}, tables={table_count}, vision={vision_count})"
        )

        return all_regions

    def _detect_atomic_regions(self, full_text: str) -> List[LayoutRegion]:
        """
        Detecte les regions atomiques (tables et vision).

        Ces regions ne doivent JAMAIS etre coupees.
        """
        regions = []

        # Tables
        regions.extend(self._detect_table_regions(full_text))

        # Vision enrichment
        regions.extend(self._detect_vision_regions(full_text))

        return regions

    def _detect_table_regions(self, full_text: str) -> List[LayoutRegion]:
        """Detecte les tables entre [TABLE_START/SUMMARY] et [TABLE_END]."""
        regions = []

        # Trouver tous les debuts de table
        for start_match in TABLE_START_PATTERN.finditer(full_text):
            table_id = start_match.group(1)
            start_pos = start_match.start()

            # Chercher la fin correspondante
            remaining_text = full_text[start_match.end():]
            end_match = TABLE_END_PATTERN.search(remaining_text)

            if end_match:
                end_pos = start_match.end() + end_match.end()
                table_text = full_text[start_pos:end_pos]

                regions.append(LayoutRegion(
                    type=RegionType.TABLE,
                    char_start=start_pos,
                    char_end=end_pos,
                    text=table_text,
                    atomic=True,  # NE JAMAIS COUPER
                    metadata={"table_id": table_id}
                ))
            else:
                # Table non fermee, prendre jusqu'a la fin
                logger.warning(
                    f"[LayoutDetector] Unclosed table {table_id} at pos {start_pos}"
                )
                regions.append(LayoutRegion(
                    type=RegionType.TABLE,
                    char_start=start_pos,
                    char_end=len(full_text),
                    text=full_text[start_pos:],
                    atomic=True,
                    metadata={"table_id": table_id, "unclosed": True}
                ))

        return regions

    def _detect_vision_regions(self, full_text: str) -> List[LayoutRegion]:
        """Detecte les enrichissements Vision."""
        regions = []

        for start_match in VISION_START_PATTERN.finditer(full_text):
            vision_id = start_match.group(1)
            confidence = float(start_match.group(2)) if start_match.group(2) else None
            start_pos = start_match.start()

            # Chercher la fin correspondante
            remaining_text = full_text[start_match.end():]
            end_match = VISION_END_PATTERN.search(remaining_text)

            if end_match:
                end_pos = start_match.end() + end_match.end()
                vision_text = full_text[start_pos:end_pos]

                regions.append(LayoutRegion(
                    type=RegionType.VISION,
                    char_start=start_pos,
                    char_end=end_pos,
                    text=vision_text,
                    atomic=True,  # NE JAMAIS COUPER
                    metadata={
                        "vision_id": vision_id,
                        "confidence": confidence
                    }
                ))
            else:
                logger.warning(
                    f"[LayoutDetector] Unclosed vision {vision_id} at pos {start_pos}"
                )
                regions.append(LayoutRegion(
                    type=RegionType.VISION,
                    char_start=start_pos,
                    char_end=len(full_text),
                    text=full_text[start_pos:],
                    atomic=True,
                    metadata={"vision_id": vision_id, "unclosed": True}
                ))

        return regions

    def _detect_block_regions(self, full_text: str) -> List[LayoutRegion]:
        """
        Detecte les blocs non-atomiques (paragraphes, titres, pages).

        Ces regions PEUVENT etre coupees si necessaire.
        """
        regions = []

        # Pages
        for match in PAGE_PATTERN.finditer(full_text):
            page_num = int(match.group(1))
            page_type = match.group(2)

            regions.append(LayoutRegion(
                type=RegionType.PAGE_MARKER,
                char_start=match.start(),
                char_end=match.end(),
                text=match.group(0),
                atomic=False,  # Peut etre coupe
                metadata={"page_num": page_num, "page_type": page_type}
            ))

        # Titres
        for match in TITLE_PATTERN.finditer(full_text):
            level = int(match.group(1))
            title_text = match.group(2)

            regions.append(LayoutRegion(
                type=RegionType.TITLE,
                char_start=match.start(),
                char_end=match.end(),
                text=match.group(0),
                atomic=False,
                metadata={"level": level, "title": title_text}
            ))

        # Paragraphes - detecter le marqueur et son contenu
        # Le paragraphe va jusqu'au prochain marqueur ou fin de texte
        for match in PARAGRAPH_PATTERN.finditer(full_text):
            para_start = match.start()

            # Trouver la fin du paragraphe (prochain marqueur ou fin)
            para_end = self._find_block_end(full_text, match.end())
            para_text = full_text[para_start:para_end]

            regions.append(LayoutRegion(
                type=RegionType.PARAGRAPH,
                char_start=para_start,
                char_end=para_end,
                text=para_text,
                atomic=False,
            ))

        return regions

    def _find_block_end(self, full_text: str, start_after: int) -> int:
        """
        Trouve la fin d'un bloc (prochain marqueur ou fin de texte).
        """
        # Patterns de fin de bloc
        next_marker = re.search(
            r"\n\n\[(?:PAGE|TITLE|PARAGRAPH|TABLE_|VISUAL_ENRICHMENT)",
            full_text[start_after:],
            re.IGNORECASE
        )

        if next_marker:
            return start_after + next_marker.start()
        return len(full_text)

    def _merge_and_fill_gaps(
        self,
        full_text: str,
        atomic_regions: List[LayoutRegion],
        block_regions: List[LayoutRegion],
    ) -> List[LayoutRegion]:
        """
        Fusionne les regions et comble les trous avec des regions TEXT.

        Priorite: regions atomiques > regions block
        """
        # Trier toutes les regions par position
        all_regions = atomic_regions + block_regions
        all_regions.sort(key=lambda r: (r.char_start, -r.char_length))

        # Filtrer les regions qui chevauchent des regions atomiques
        final_regions = []
        covered_ranges: List[Tuple[int, int]] = []

        # D'abord, ajouter toutes les regions atomiques
        for region in all_regions:
            if region.atomic:
                final_regions.append(region)
                covered_ranges.append((region.char_start, region.char_end))

        # Ensuite, ajouter les regions non-atomiques qui ne chevauchent pas
        for region in all_regions:
            if region.atomic:
                continue

            # Verifier si cette region chevauche une region atomique
            overlaps_atomic = any(
                region.char_start < end and region.char_end > start
                for start, end in covered_ranges
            )

            if not overlaps_atomic:
                final_regions.append(region)
                covered_ranges.append((region.char_start, region.char_end))

        # Trier par position
        final_regions.sort(key=lambda r: r.char_start)

        # Combler les trous avec des regions TEXT
        filled_regions = self._fill_gaps_with_text(full_text, final_regions)

        return filled_regions

    def _fill_gaps_with_text(
        self,
        full_text: str,
        regions: List[LayoutRegion],
    ) -> List[LayoutRegion]:
        """
        Comble les trous entre les regions avec des regions TEXT.
        """
        if not full_text:
            return regions

        filled = []
        last_end = 0

        for region in regions:
            # S'il y a un trou avant cette region
            if region.char_start > last_end:
                gap_text = full_text[last_end:region.char_start]
                # Ne creer une region TEXT que si le trou contient du texte significatif
                if gap_text.strip():
                    filled.append(LayoutRegion(
                        type=RegionType.TEXT,
                        char_start=last_end,
                        char_end=region.char_start,
                        text=gap_text,
                        atomic=False,
                    ))

            filled.append(region)
            last_end = max(last_end, region.char_end)

        # Trou final
        if last_end < len(full_text):
            gap_text = full_text[last_end:]
            if gap_text.strip():
                filled.append(LayoutRegion(
                    type=RegionType.TEXT,
                    char_start=last_end,
                    char_end=len(full_text),
                    text=gap_text,
                    atomic=False,
                ))

        return filled

    def get_atomic_boundaries(
        self,
        full_text: str,
    ) -> List[Tuple[int, int]]:
        """
        Retourne les bornes des regions atomiques (pour le chunker).

        Utilise par HybridAnchorChunker pour savoir ou NE PAS couper.

        Args:
            full_text: Texte linearise

        Returns:
            Liste de tuples (start, end) des regions atomiques
        """
        regions = self.detect_regions(full_text)
        return [
            (r.char_start, r.char_end)
            for r in regions
            if r.atomic
        ]

    def validate_no_cut_tables(
        self,
        chunks: List[dict],
        full_text: str,
    ) -> Tuple[bool, List[str]]:
        """
        Valide qu'aucun tableau n'a ete coupe par le chunking.

        Utilise pour les tests et le monitoring.

        Args:
            chunks: Liste de chunks avec char_start, char_end
            full_text: Texte complet

        Returns:
            Tuple (is_valid, list_of_violations)
            - is_valid: True si aucun tableau coupe
            - violations: Liste des tables coupees (pour debug)
        """
        # Detecter les tables
        table_regions = self._detect_table_regions(full_text)
        violations = []

        for table in table_regions:
            table_start = table.char_start
            table_end = table.char_end
            table_id = table.metadata.get("table_id", "unknown")

            # Verifier si un chunk coupe cette table
            for i, chunk in enumerate(chunks):
                chunk_start = chunk.get("char_start", 0)
                chunk_end = chunk.get("char_end", 0)

                # Un chunk coupe une table si:
                # - Le chunk commence dans la table mais finit apres
                # - Le chunk commence avant la table mais finit dedans
                starts_inside = table_start < chunk_start < table_end
                ends_inside = table_start < chunk_end < table_end

                if starts_inside != ends_inside:  # XOR: coupe detectee
                    violations.append(
                        f"Table {table_id} cut by chunk {i} "
                        f"[table:{table_start}-{table_end}, chunk:{chunk_start}-{chunk_end}]"
                    )

        is_valid = len(violations) == 0

        if violations:
            logger.error(
                f"[LayoutDetector] VALIDATION FAILED: {len(violations)} tables cut!"
            )
            for v in violations[:5]:  # Log les 5 premiers
                logger.error(f"  - {v}")
        else:
            logger.debug(
                f"[LayoutDetector] Validation passed: 0 tables cut "
                f"({len(table_regions)} tables, {len(chunks)} chunks)"
            )

        return is_valid, violations


# =============================================================================
# Factory Pattern
# =============================================================================

_detector_instance: Optional[LayoutDetector] = None


def get_layout_detector() -> LayoutDetector:
    """
    Recupere l'instance singleton du detecteur.

    Returns:
        LayoutDetector instance
    """
    global _detector_instance

    if _detector_instance is None:
        _detector_instance = LayoutDetector()

    return _detector_instance


__all__ = [
    "LayoutDetector",
    "LayoutRegion",
    "RegionType",
    "get_layout_detector",
]
