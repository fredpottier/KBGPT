"""
OSMOSE Pipeline V2 - Assertion Unit Indexer
============================================
Ref: Plan Pointer-Based Extraction (2026-01-27)

Segmente les DocItems en unités d'assertion robustes pour éliminer
structurellement le problème de reformulation LLM.

Le LLM POINTE vers une unité au lieu de COPIER le texte:
- Input  → "U1: TLS 1.2 is required for all connections."
- LLM    → { "concept": "TLS requirement", "unit_id": "U1" }
- Code   → exact_quote = units["U1"]  // GARANTI VERBATIM

CRITÈRE DE SUCCÈS:
- Segmentation robuste (gère abréviations, versions, bullets)
- IDs stables et déterministes
- Unités entre 30 et 500 caractères
"""

import re
import logging
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


# ============================================================================
# DATA CLASSES
# ============================================================================

@dataclass
class AssertionUnit:
    """
    Unité d'assertion atomique extraite d'un DocItem.

    Une unité est un segment de texte stable qui peut être pointé
    par le LLM sans risque de reformulation.
    """
    unit_local_id: str        # "U{n}" - local au DocItem (ex: "U1", "U2")
    docitem_id: str           # Référence DocItem parent
    text: str                 # Texte verbatim (readonly)
    char_start: int           # Position dans DocItem.text
    char_end: int
    unit_type: str            # "sentence" | "clause" | "bullet" | "segment" | "table_row"

    @property
    def unit_global_id(self) -> str:
        """ID global calculé dynamiquement, jamais stocké."""
        return f"{self.docitem_id}#{self.unit_local_id}"

    def __len__(self) -> int:
        return len(self.text)


@dataclass
class UnitIndexResult:
    """Résultat de l'indexation d'un DocItem."""
    docitem_id: str
    units: List[AssertionUnit] = field(default_factory=list)
    stats: Dict[str, int] = field(default_factory=dict)

    @property
    def unit_count(self) -> int:
        return len(self.units)

    def get_unit_by_local_id(self, local_id: str) -> Optional[AssertionUnit]:
        """Retourne une unité par son ID local (U1, U2, etc.)."""
        for unit in self.units:
            if unit.unit_local_id == local_id:
                return unit
        return None


# ============================================================================
# ASSERTION UNIT INDEXER
# ============================================================================

class AssertionUnitIndexer:
    """
    Segmente les DocItems en unités d'assertion robustes.

    Stratégie de segmentation:
    1. Si LIST_ITEM → une seule unité
    2. Sinon → segmentation intelligente (phrases + clauses)
    3. Re-découper si > max_unit_length chars

    Configuration:
    - min_unit_length: Longueur minimale (défaut: 30)
    - max_unit_length: Longueur maximale avant re-découpage (défaut: 500)
    - split_on_semicolon: Splitter sur ';' dans contexte prescriptif
    - split_on_colon: Splitter sur ':' sauf si suivi de valeur courte
    """

    # Types DocItem qui sont des unités atomiques
    ATOMIC_TYPES = {"list_item", "bullet", "table_cell"}

    def __init__(
        self,
        min_unit_length: int = 30,
        max_unit_length: int = 500,
        split_on_semicolon: bool = True,
        split_on_colon: bool = True,
    ):
        self.min_unit_length = min_unit_length
        self.max_unit_length = max_unit_length
        self.split_on_semicolon = split_on_semicolon
        self.split_on_colon = split_on_colon

        # Pattern pour détecter les valeurs courtes après ':'
        # Couvre: versions, tailles, protocoles, standards (AES-256, SHA-256, SOC 2)
        self._value_after_colon_pattern = re.compile(
            r':\s*(v?\d+(\.\d+)*\s*(%|GB|TB|MB|GiB|TiB)?|[A-Z][\w-]*\d*|[A-Z]{2,}-\d+)\s*$'
        )

        # Marqueurs prescriptifs pour détecter contexte règle
        self._prescriptive_markers = [
            "must", "shall", "required", "mandatory", "obligatory",
            "doit", "obligatoire", "nécessaire", "impératif"
        ]

    def index_docitem(
        self,
        docitem_id: str,
        text: str,
        item_type: Optional[str] = None,
    ) -> UnitIndexResult:
        """
        Segmente un DocItem en unités d'assertion.

        Args:
            docitem_id: ID composite du DocItem (tenant:doc:item)
            text: Texte du DocItem
            item_type: Type du DocItem (list_item, paragraph, etc.)

        Returns:
            UnitIndexResult avec les unités et statistiques
        """
        result = UnitIndexResult(docitem_id=docitem_id)
        result.stats = {
            "total_chars": len(text),
            "sentences": 0,
            "clauses": 0,
            "segments": 0,
            "redecoupes": 0,
        }

        if not text or len(text.strip()) < self.min_unit_length:
            return result

        # Cas 1: Type atomique (list item, bullet, etc.)
        if item_type and item_type.lower() in self.ATOMIC_TYPES:
            unit = AssertionUnit(
                unit_local_id="U1",
                docitem_id=docitem_id,
                text=text.strip(),
                char_start=0,
                char_end=len(text),
                unit_type="bullet",
            )
            result.units.append(unit)
            return result

        # Cas 2: Segmentation intelligente
        segments = self._segment_text(text)

        unit_index = 1
        for seg_text, start, end, seg_type in segments:
            # Ignorer segments trop courts
            if len(seg_text.strip()) < self.min_unit_length:
                continue

            # Re-découper si trop long
            if len(seg_text) > self.max_unit_length:
                sub_segments = self._split_long_segment(seg_text, start)
                result.stats["redecoupes"] += len(sub_segments) - 1

                for sub_text, sub_start, sub_end in sub_segments:
                    unit = AssertionUnit(
                        unit_local_id=f"U{unit_index}",
                        docitem_id=docitem_id,
                        text=sub_text.strip(),
                        char_start=sub_start,
                        char_end=sub_end,
                        unit_type="segment",
                    )
                    result.units.append(unit)
                    result.stats["segments"] += 1
                    unit_index += 1
            else:
                unit = AssertionUnit(
                    unit_local_id=f"U{unit_index}",
                    docitem_id=docitem_id,
                    text=seg_text.strip(),
                    char_start=start,
                    char_end=end,
                    unit_type=seg_type,
                )
                result.units.append(unit)
                result.stats[f"{seg_type}s" if not seg_type.endswith("s") else seg_type] = \
                    result.stats.get(f"{seg_type}s" if not seg_type.endswith("s") else seg_type, 0) + 1
                unit_index += 1

        logger.debug(
            f"[OSMOSE:UnitIndexer] {docitem_id}: {len(result.units)} unités "
            f"({result.stats})"
        )

        return result

    def index_docitems(
        self,
        docitems: Dict[str, "DocItem"],
    ) -> Dict[str, UnitIndexResult]:
        """
        Indexe tous les DocItems et retourne un index global.

        Args:
            docitems: Dict docitem_id → DocItem

        Returns:
            Dict docitem_id → UnitIndexResult
        """
        index = {}
        total_units = 0

        for docitem_id, docitem in docitems.items():
            # Extraire le texte selon le type de DocItem
            text = getattr(docitem, 'text', '') or getattr(docitem, 'content', '') or ''
            item_type = getattr(docitem, 'item_type', None)
            if hasattr(item_type, 'value'):
                item_type = item_type.value

            result = self.index_docitem(
                docitem_id=docitem_id,
                text=text,
                item_type=item_type,
            )

            if result.units:
                index[docitem_id] = result
                total_units += len(result.units)

        logger.info(
            f"[OSMOSE:UnitIndexer] Indexé {len(index)} DocItems → {total_units} unités"
        )

        return index

    def index_table_rows(
        self,
        docitem_id: str,
        table_data: List[Dict[str, str]],
    ) -> UnitIndexResult:
        """
        Indexe les rows d'une table comme unités.

        Crée une unité par row avec ID stable basé sur index.
        Format canonique: "Header1: Cell1 | Header2: Cell2 | ..."

        Args:
            docitem_id: ID du DocItem table parent
            table_data: Liste de dicts {header: value}

        Returns:
            UnitIndexResult avec une unité par row
        """
        result = UnitIndexResult(docitem_id=docitem_id)
        result.stats = {"table_rows": 0}

        for row_index, row in enumerate(table_data):
            # ID stable basé sur index
            unit_local_id = f"U{row_index + 1}"

            # Format canonique (tri alphabétique des headers pour stabilité)
            cells = sorted(row.items())
            text = " | ".join(f"{h}: {v}" for h, v in cells if v)

            if len(text) < self.min_unit_length:
                continue

            unit = AssertionUnit(
                unit_local_id=unit_local_id,
                docitem_id=docitem_id,
                text=text,
                char_start=0,  # N/A pour tables
                char_end=len(text),
                unit_type="table_row",
            )
            result.units.append(unit)
            result.stats["table_rows"] += 1

        return result

    # =========================================================================
    # SEGMENTATION INTELLIGENTE
    # =========================================================================

    def _segment_text(self, text: str) -> List[Tuple[str, int, int, str]]:
        """
        Segmente le texte en unités d'assertion.

        Retourne: [(text, start, end, type), ...]

        Règles:
        1. Protéger les abréviations par patterns (pas de whitelist)
        2. Split sur .!? + espace
        3. Split sur ; si contexte prescriptif
        4. Split sur : SI suivi d'une liste (pas si valeur courte)
        5. Re-découper segments > max_unit_length sur virgules
        """
        segments = []

        # Phase 1: Découper en phrases (protéger abréviations)
        sentences = self._split_sentences(text)

        # Phase 2: Découper les clauses si nécessaire
        for sent_text, sent_start, sent_end in sentences:
            # Vérifier si contexte prescriptif
            is_prescriptive = self._has_prescriptive_marker(sent_text)

            # Tenter découpage par clauses
            clauses = self._split_clauses(sent_text, sent_start, is_prescriptive)

            if len(clauses) > 1:
                for clause_text, clause_start, clause_end in clauses:
                    segments.append((clause_text, clause_start, clause_end, "clause"))
            else:
                segments.append((sent_text, sent_start, sent_end, "sentence"))

        return segments

    def _split_sentences(self, text: str) -> List[Tuple[str, int, int]]:
        """
        Découpe le texte en phrases en protégeant les abréviations.

        Utilise uniquement des patterns (pas de whitelist figée).
        """
        sentences = []
        current_start = 0

        # Trouver tous les points candidats
        i = 0
        while i < len(text):
            if text[i] in '.!?':
                # Vérifier si c'est une vraie fin de phrase
                if self._is_sentence_end(text, i):
                    # Capturer jusqu'à ce point
                    sentence = text[current_start:i + 1].strip()
                    if sentence:
                        sentences.append((
                            sentence,
                            current_start,
                            i + 1,
                        ))
                    current_start = i + 1
                    # Skip whitespace après ponctuation
                    while current_start < len(text) and text[current_start] in ' \t\n':
                        current_start += 1
            i += 1

        # Dernier segment
        if current_start < len(text):
            remaining = text[current_start:].strip()
            if remaining:
                sentences.append((remaining, current_start, len(text)))

        return sentences

    def _is_sentence_end(self, text: str, dot_pos: int) -> bool:
        """
        Détermine si un point est une fin de phrase.

        Patterns UNIQUEMENT (pas de liste figée):
        1. Suivi d'une majuscule après espace → fin de phrase
        2. Précédé d'un mot court (len <= 3) → probablement abréviation
        3. Token avec point interne (x.x pattern) → abréviation (e.g., i.e.)
        4. Acronyme pointé (X.X.) → abréviation (U.S., Ph.D.)
        5. Version-like (\\d+(\\.\\d+)+) → pas fin de phrase
        6. Fin de texte → fin de phrase
        """
        char = text[dot_pos]

        # Seulement gérer les points pour abréviations
        # ! et ? sont toujours des fins de phrase
        if char in '!?':
            return True

        # Pattern 1: Mot court avant point (1-3 lettres)
        word_before = ""
        j = dot_pos - 1
        while j >= 0 and text[j].isalpha():
            word_before = text[j] + word_before
            j -= 1

        if 1 <= len(word_before) <= 3:
            # Mot court = probablement abréviation (e.g., Dr., Fig., Sec., etc.)
            # SAUF si suivi d'une majuscule après espace
            if dot_pos + 2 < len(text):
                next_char = text[dot_pos + 1:dot_pos + 3].lstrip()
                if next_char and next_char[0].isupper():
                    # Pourrait être fin de phrase quand même
                    # Vérifier si le mot court est entièrement majuscule (acronyme)
                    if word_before.isupper():
                        return False  # Acronyme, pas fin de phrase
                    return True  # Mot normal suivi de majuscule = fin de phrase
            return False  # Probablement abréviation

        # Pattern 2: Point interne dans un token (i.e., e.g.)
        if dot_pos > 0 and dot_pos + 1 < len(text):
            if text[dot_pos - 1].isalpha() and text[dot_pos + 1].isalpha():
                return False  # Point interne

        # Pattern 3: Version (1.2, 2.0.1)
        if dot_pos > 0 and dot_pos + 1 < len(text):
            if text[dot_pos - 1].isdigit() and text[dot_pos + 1].isdigit():
                return False  # Version

        # Pattern 4: Suivi d'une majuscule après espace = fin de phrase
        if dot_pos + 2 < len(text):
            rest = text[dot_pos + 1:].lstrip()
            if rest and rest[0].isupper():
                return True

        # Pattern 5: Fin de texte = fin de phrase
        if dot_pos == len(text) - 1:
            return True

        # Pattern 6: Suivi uniquement de whitespace puis fin
        rest = text[dot_pos + 1:].strip()
        if not rest:
            return True

        # Par défaut, considérer comme fin de phrase si suivi d'espace
        if dot_pos + 1 < len(text) and text[dot_pos + 1] in ' \t\n':
            return True

        return False

    def _split_clauses(
        self,
        text: str,
        offset: int,
        is_prescriptive: bool,
    ) -> List[Tuple[str, int, int]]:
        """
        Découpe une phrase en clauses si approprié.

        Split sur:
        - ';' si contexte prescriptif
        - ':' si suivi d'une liste (pas si valeur courte)
        """
        clauses = []

        # Split sur ';' seulement si prescriptif
        if self.split_on_semicolon and is_prescriptive and ';' in text:
            parts = text.split(';')
            current_offset = offset
            for part in parts:
                part = part.strip()
                if part:
                    clauses.append((part, current_offset, current_offset + len(part)))
                current_offset += len(part) + 1  # +1 pour le ';'

            if len(clauses) > 1:
                return clauses

        # Split sur ':' si suivi d'une liste (pas si valeur courte)
        if self.split_on_colon and ':' in text:
            # Vérifier si c'est suivi d'une valeur courte
            if not self._value_after_colon_pattern.search(text):
                # Vérifier si c'est suivi d'une liste (bullets, énumération)
                colon_pos = text.find(':')
                after_colon = text[colon_pos + 1:].strip()

                # Heuristique: liste si commence par '-', '*', '•', ou contient plusieurs virgules
                is_list = (
                    after_colon and
                    (after_colon[0] in '-*•' or after_colon.count(',') >= 2)
                )

                if is_list:
                    before = text[:colon_pos].strip()
                    after = after_colon
                    if before and after:
                        clauses.append((before + ":", offset, offset + colon_pos + 1))
                        clauses.append((after, offset + colon_pos + 1, offset + len(text)))
                        return clauses

        # Pas de découpage
        return [(text, offset, offset + len(text))]

    def _has_prescriptive_marker(self, text: str) -> bool:
        """Détecte si le texte contient un marqueur prescriptif."""
        text_lower = text.lower()
        return any(marker in text_lower for marker in self._prescriptive_markers)

    def _split_long_segment(
        self,
        text: str,
        offset: int,
    ) -> List[Tuple[str, int, int]]:
        """
        Re-découpe un segment trop long sur les virgules.

        Essaie de garder des segments de taille raisonnable
        tout en respectant les limites naturelles.
        """
        if len(text) <= self.max_unit_length:
            return [(text, offset, offset + len(text))]

        segments = []
        current_start = 0
        current_segment = ""

        # Découper sur virgules
        parts = text.split(',')

        for i, part in enumerate(parts):
            test_segment = current_segment + (',' if current_segment else '') + part

            if len(test_segment) > self.max_unit_length and current_segment:
                # Sauvegarder le segment courant
                segments.append((
                    current_segment.strip(),
                    offset + current_start,
                    offset + current_start + len(current_segment),
                ))
                current_start += len(current_segment) + 1  # +1 pour virgule
                current_segment = part
            else:
                current_segment = test_segment

        # Dernier segment
        if current_segment.strip():
            segments.append((
                current_segment.strip(),
                offset + current_start,
                offset + len(text),
            ))

        return segments if segments else [(text, offset, offset + len(text))]


# ============================================================================
# CONVENIENCE FUNCTIONS
# ============================================================================

def index_docitems_to_units(
    docitems: Dict[str, "DocItem"],
    min_unit_length: int = 30,
    max_unit_length: int = 500,
) -> Dict[str, UnitIndexResult]:
    """
    Fonction helper pour indexer tous les DocItems en unités.

    Args:
        docitems: Dict docitem_id → DocItem
        min_unit_length: Longueur minimale d'une unité
        max_unit_length: Longueur maximale avant re-découpage

    Returns:
        Dict docitem_id → UnitIndexResult
    """
    indexer = AssertionUnitIndexer(
        min_unit_length=min_unit_length,
        max_unit_length=max_unit_length,
    )
    return indexer.index_docitems(docitems)


def format_units_for_llm(units: List[AssertionUnit]) -> str:
    """
    Formate les unités pour envoi au LLM.

    Format:
    U1: First assertion text here.
    U2: Second assertion text here.
    ...

    Args:
        units: Liste d'AssertionUnit

    Returns:
        Texte formaté avec préfixes U{n}:
    """
    lines = []
    for unit in units:
        lines.append(f"{unit.unit_local_id}: {unit.text}")
    return "\n".join(lines)


def lookup_unit_text(
    unit_index: Dict[str, UnitIndexResult],
    docitem_id: str,
    unit_local_id: str,
) -> Optional[str]:
    """
    Retrouve le texte verbatim d'une unité.

    Args:
        unit_index: Index global docitem_id → UnitIndexResult
        docitem_id: ID du DocItem parent
        unit_local_id: ID local de l'unité (U1, U2, etc.)

    Returns:
        Texte de l'unité ou None si non trouvée
    """
    result = unit_index.get(docitem_id)
    if not result:
        return None

    unit = result.get_unit_by_local_id(unit_local_id)
    return unit.text if unit else None
