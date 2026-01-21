"""
OSMOSE - StructureParser

Parseur pour l'extraction de SpecFacts depuis des structures tabulaires
et listes clé-valeur.

ADR: doc/ongoing/ADR_NORMATIVE_RULES_SPEC_FACTS.md

Invariants:
- INV-NORM-01: Preuve locale obligatoire (evidence_text)
- INV-NORM-03: Structure explicite requise
- INV-NORM-04: Pas de sujet inventé
- INV-AGN-01: Domain-agnostic

Author: Claude Code
Date: 2026-01-21
"""

import re
import logging
from typing import List, Optional, Tuple, Dict, Any
from dataclasses import dataclass
from datetime import datetime
import ulid

from .types import (
    SpecFact,
    SpecType,
    StructureType,
    ExtractionMethod,
    ScopeAnchor,
)

logger = logging.getLogger(__name__)


# =============================================================================
# Patterns de détection de structures
# =============================================================================

# Pattern pour tables Markdown
TABLE_PATTERN = re.compile(
    r'^\|(.+?)\|$',
    re.MULTILINE
)

# Pattern pour lignes de séparation de table
TABLE_SEPARATOR_PATTERN = re.compile(
    r'^\|[-:\s|]+\|$',
    re.MULTILINE
)

# Patterns pour key-value
KEY_VALUE_PATTERNS = [
    # Label: Value
    re.compile(r'^([A-Za-z][A-Za-z0-9\s_-]*?)\s*:\s*(.+?)$', re.MULTILINE),
    # Label = Value
    re.compile(r'^([A-Za-z][A-Za-z0-9\s_-]*?)\s*=\s*(.+?)$', re.MULTILINE),
    # Label → Value (arrow)
    re.compile(r'^([A-Za-z][A-Za-z0-9\s_-]*?)\s*[→->]+\s*(.+?)$', re.MULTILINE),
]

# Pattern pour bullet list avec key-value
BULLET_KEY_VALUE_PATTERN = re.compile(
    r'^[\s]*[-*•]\s*([A-Za-z][A-Za-z0-9\s_-]*?)\s*:\s*(.+?)$',
    re.MULTILINE
)

# Marqueurs de type de spec dans les headers de colonnes
SPEC_TYPE_MARKERS = {
    SpecType.MIN: ["min", "minimum", "at least", ">=", "required"],
    SpecType.MAX: ["max", "maximum", "at most", "<=", "limit"],
    SpecType.DEFAULT: ["default", "défaut", "standard"],
    SpecType.RECOMMENDED: ["recommended", "recommandé", "optimal", "suggested"],
    SpecType.VALUE: ["value", "valeur", "spec", "specification"],
}


@dataclass
class TableRow:
    """Ligne d'un tableau parsé."""
    cells: List[str]
    row_index: int
    is_header: bool = False


@dataclass
class ParsedTable:
    """Tableau parsé."""
    headers: List[str]
    rows: List[TableRow]
    raw_text: str


@dataclass
class KeyValuePair:
    """Paire clé-valeur extraite."""
    key: str
    value: str
    raw_line: str
    structure_type: StructureType


class StructureParser:
    """
    Parseur de structures pour l'extraction de SpecFacts.

    Détecte et parse:
    - Tables (Markdown, pipe-separated)
    - Listes clé-valeur (Label: Value)
    - Bullet lists avec key-value

    Usage:
        parser = StructureParser()
        facts = parser.extract_from_text(text, doc_id, chunk_id)
    """

    VERSION = "v1.0.0"

    def __init__(self, min_confidence: float = 0.7):
        """
        Initialise le parseur.

        Args:
            min_confidence: Seuil minimum de confidence
        """
        self.min_confidence = min_confidence

    def extract_from_text(
        self,
        text: str,
        source_doc_id: str,
        source_chunk_id: str,
        source_segment_id: Optional[str] = None,
        evidence_section: Optional[str] = None,
        structure_context: Optional[str] = None,
        tenant_id: str = "default",
    ) -> List[SpecFact]:
        """
        Extrait les SpecFacts d'un texte.

        Args:
            text: Texte à analyser
            source_doc_id: ID du document source
            source_chunk_id: ID du chunk source
            source_segment_id: ID du segment (optionnel)
            evidence_section: Titre de section
            structure_context: Contexte de la structure (ex: "System Requirements")
            tenant_id: ID tenant

        Returns:
            Liste de SpecFact extraits
        """
        facts: List[SpecFact] = []

        # 1. Détecter et parser les tables
        tables = self._detect_tables(text)
        for table in tables:
            table_facts = self._extract_from_table(
                table=table,
                source_doc_id=source_doc_id,
                source_chunk_id=source_chunk_id,
                source_segment_id=source_segment_id,
                evidence_section=evidence_section,
                structure_context=structure_context,
                tenant_id=tenant_id,
            )
            facts.extend(table_facts)

        # 2. Détecter et parser les key-value pairs
        kv_pairs = self._detect_key_value_pairs(text)
        for kv in kv_pairs:
            fact = self._create_fact_from_kv(
                kv=kv,
                source_doc_id=source_doc_id,
                source_chunk_id=source_chunk_id,
                source_segment_id=source_segment_id,
                evidence_section=evidence_section,
                structure_context=structure_context,
                tenant_id=tenant_id,
            )
            if fact:
                facts.append(fact)

        logger.debug(f"[StructureParser] Extrait {len(facts)} SpecFacts")
        return facts

    def _detect_tables(self, text: str) -> List[ParsedTable]:
        """
        Détecte et parse les tables dans le texte.

        Supporte les tables Markdown avec pipes (|).
        """
        tables: List[ParsedTable] = []

        # Chercher les blocs de lignes avec pipes
        lines = text.split('\n')
        table_lines: List[str] = []
        in_table = False

        for line in lines:
            if '|' in line and line.strip().startswith('|'):
                if not in_table:
                    in_table = True
                    table_lines = []
                table_lines.append(line)
            else:
                if in_table and table_lines:
                    # Fin du tableau
                    parsed = self._parse_table(table_lines)
                    if parsed:
                        tables.append(parsed)
                in_table = False
                table_lines = []

        # Traiter le dernier tableau si on est encore dedans
        if in_table and table_lines:
            parsed = self._parse_table(table_lines)
            if parsed:
                tables.append(parsed)

        return tables

    def _parse_table(self, lines: List[str]) -> Optional[ParsedTable]:
        """Parse un bloc de lignes comme tableau."""
        if len(lines) < 2:
            return None

        # Extraire les cellules de chaque ligne
        rows: List[TableRow] = []
        for i, line in enumerate(lines):
            # Ignorer les lignes de séparation
            if TABLE_SEPARATOR_PATTERN.match(line.strip()):
                continue

            cells = self._parse_table_row(line)
            if cells:
                rows.append(TableRow(
                    cells=cells,
                    row_index=i,
                    is_header=(i == 0)
                ))

        if len(rows) < 2:  # Header + au moins une ligne de data
            return None

        # La première ligne est le header
        headers = rows[0].cells
        data_rows = rows[1:]

        return ParsedTable(
            headers=headers,
            rows=data_rows,
            raw_text='\n'.join(lines)
        )

    def _parse_table_row(self, line: str) -> List[str]:
        """Parse une ligne de tableau en cellules."""
        # Supprimer les pipes de début et fin
        line = line.strip()
        if line.startswith('|'):
            line = line[1:]
        if line.endswith('|'):
            line = line[:-1]

        # Splitter sur les pipes
        cells = [cell.strip() for cell in line.split('|')]
        return cells

    def _extract_from_table(
        self,
        table: ParsedTable,
        source_doc_id: str,
        source_chunk_id: str,
        source_segment_id: Optional[str],
        evidence_section: Optional[str],
        structure_context: Optional[str],
        tenant_id: str,
    ) -> List[SpecFact]:
        """Extrait les SpecFacts d'un tableau parsé."""
        facts: List[SpecFact] = []

        # Identifier quelle colonne contient l'attribut et quelle colonne contient la valeur
        # Heuristique: première colonne = attribut, autres colonnes = valeurs

        if len(table.headers) < 2:
            return facts

        attribute_col = 0  # Première colonne = nom de l'attribut

        # Mapper les colonnes valeur aux types de spec
        col_spec_types: Dict[int, SpecType] = {}
        for i, header in enumerate(table.headers[1:], start=1):
            spec_type = self._detect_spec_type_from_header(header)
            col_spec_types[i] = spec_type

        # Extraire un fact par cellule de valeur
        for row in table.rows:
            if len(row.cells) <= attribute_col:
                continue

            attribute_name = row.cells[attribute_col].strip()
            if not attribute_name or attribute_name == '-':
                continue

            for col_idx, spec_type in col_spec_types.items():
                if col_idx >= len(row.cells):
                    continue

                cell_value = row.cells[col_idx].strip()
                if not cell_value or cell_value == '-':
                    continue

                # Parser la valeur et l'unité
                value, value_numeric, unit = self._parse_value(cell_value)

                # Créer le fact
                fact = SpecFact(
                    fact_id=str(ulid.new()),
                    tenant_id=tenant_id,
                    attribute_name=attribute_name,
                    attribute_concept_id=None,
                    spec_type=spec_type,
                    value=value,
                    value_numeric=value_numeric,
                    unit=unit,
                    source_structure=StructureType.TABLE,
                    structure_context=structure_context or evidence_section,
                    row_header=attribute_name,
                    column_header=table.headers[col_idx] if col_idx < len(table.headers) else None,
                    evidence_text=cell_value,
                    evidence_section=evidence_section,
                    scope_anchors=[ScopeAnchor(
                        doc_id=source_doc_id,
                        scope_setter_ids=[],
                        scope_tags=[],
                    )],
                    source_doc_id=source_doc_id,
                    source_chunk_id=source_chunk_id,
                    source_segment_id=source_segment_id,
                    extraction_method=ExtractionMethod.PATTERN,
                    confidence=0.85,  # Haute confidence pour tables
                    extractor_version=self.VERSION,
                    created_at=datetime.utcnow(),
                )
                facts.append(fact)

        return facts

    def _detect_spec_type_from_header(self, header: str) -> SpecType:
        """Détecte le SpecType depuis un header de colonne."""
        header_lower = header.lower()

        for spec_type, markers in SPEC_TYPE_MARKERS.items():
            for marker in markers:
                if marker in header_lower:
                    return spec_type

        return SpecType.VALUE  # Par défaut

    def _detect_key_value_pairs(self, text: str) -> List[KeyValuePair]:
        """
        Détecte les paires clé-valeur dans le texte.

        Supporte:
        - Label: Value
        - Label = Value
        - - Label: Value (bullet)
        """
        pairs: List[KeyValuePair] = []

        # Bullet key-value
        for match in BULLET_KEY_VALUE_PATTERN.finditer(text):
            key = match.group(1).strip()
            value = match.group(2).strip()
            if self._is_valid_kv_pair(key, value):
                pairs.append(KeyValuePair(
                    key=key,
                    value=value,
                    raw_line=match.group(0),
                    structure_type=StructureType.BULLET_LIST,
                ))

        # Autres patterns key-value
        for pattern in KEY_VALUE_PATTERNS:
            for match in pattern.finditer(text):
                key = match.group(1).strip()
                value = match.group(2).strip()
                if self._is_valid_kv_pair(key, value):
                    # Éviter les doublons avec bullet
                    if not any(p.key == key and p.value == value for p in pairs):
                        pairs.append(KeyValuePair(
                            key=key,
                            value=value,
                            raw_line=match.group(0),
                            structure_type=StructureType.KEY_VALUE_LIST,
                        ))

        return pairs

    def _is_valid_kv_pair(self, key: str, value: str) -> bool:
        """Vérifie si une paire clé-valeur est valide."""
        # Filtrer les clés trop courtes ou trop longues
        if len(key) < 2 or len(key) > 50:
            return False

        # Filtrer les valeurs vides
        if not value:
            return False

        # Filtrer les patterns qui ne sont pas des specs
        # (ex: "Note: blabla" n'est pas une spec)
        noise_keys = {
            "note", "example", "see", "cf", "reference", "source",
            "url", "link", "warning", "caution", "tip", "info",
        }
        if key.lower() in noise_keys:
            return False

        return True

    def _create_fact_from_kv(
        self,
        kv: KeyValuePair,
        source_doc_id: str,
        source_chunk_id: str,
        source_segment_id: Optional[str],
        evidence_section: Optional[str],
        structure_context: Optional[str],
        tenant_id: str,
    ) -> Optional[SpecFact]:
        """Crée un SpecFact depuis une paire clé-valeur."""
        # Détecter le spec_type depuis la clé
        spec_type = self._detect_spec_type_from_key(kv.key)

        # Parser la valeur
        value, value_numeric, unit = self._parse_value(kv.value)

        # Calculer la confidence
        confidence = 0.75 if kv.structure_type == StructureType.KEY_VALUE_LIST else 0.70

        return SpecFact(
            fact_id=str(ulid.new()),
            tenant_id=tenant_id,
            attribute_name=kv.key,
            attribute_concept_id=None,
            spec_type=spec_type,
            value=value,
            value_numeric=value_numeric,
            unit=unit,
            source_structure=kv.structure_type,
            structure_context=structure_context or evidence_section,
            row_header=None,
            column_header=None,
            evidence_text=kv.raw_line,
            evidence_section=evidence_section,
            scope_anchors=[ScopeAnchor(
                doc_id=source_doc_id,
                scope_setter_ids=[],
                scope_tags=[],
            )],
            source_doc_id=source_doc_id,
            source_chunk_id=source_chunk_id,
            source_segment_id=source_segment_id,
            extraction_method=ExtractionMethod.PATTERN,
            confidence=confidence,
            extractor_version=self.VERSION,
            created_at=datetime.utcnow(),
        )

    def _detect_spec_type_from_key(self, key: str) -> SpecType:
        """Détecte le SpecType depuis une clé."""
        key_lower = key.lower()

        # Patterns dans la clé
        if any(m in key_lower for m in ["min", "minimum"]):
            return SpecType.MIN
        if any(m in key_lower for m in ["max", "maximum"]):
            return SpecType.MAX
        if any(m in key_lower for m in ["default", "défaut"]):
            return SpecType.DEFAULT
        if any(m in key_lower for m in ["recommended", "recomm"]):
            return SpecType.RECOMMENDED

        return SpecType.VALUE

    def _parse_value(self, raw_value: str) -> Tuple[str, Optional[float], Optional[str]]:
        """
        Parse une valeur brute en (value, value_numeric, unit).

        Ex: "256GB" → ("256GB", 256.0, "GB")
        Ex: "30 seconds" → ("30 seconds", 30.0, "seconds")
        Ex: "enabled" → ("enabled", None, None)
        """
        raw_value = raw_value.strip()

        # Pattern numérique avec unité
        match = re.match(
            r'^([\d,.]+)\s*([A-Za-z%]+)?$',
            raw_value
        )
        if match:
            num_str = match.group(1).replace(',', '')
            try:
                value_numeric = float(num_str)
            except ValueError:
                value_numeric = None
            unit = match.group(2)
            return raw_value, value_numeric, unit

        # Pattern avec unité séparée
        match = re.match(
            r'^([\d,.]+)\s+([A-Za-z]+)$',
            raw_value
        )
        if match:
            num_str = match.group(1).replace(',', '')
            try:
                value_numeric = float(num_str)
            except ValueError:
                value_numeric = None
            unit = match.group(2)
            return raw_value, value_numeric, unit

        # Pas de parsing possible
        return raw_value, None, None


# =============================================================================
# Fonctions utilitaires
# =============================================================================

def extract_spec_facts(
    text: str,
    doc_id: str,
    chunk_id: str,
    **kwargs
) -> List[SpecFact]:
    """
    Fonction convenience pour l'extraction de SpecFacts.

    Usage:
        facts = extract_spec_facts(text, doc_id, chunk_id)
    """
    parser = StructureParser()
    return parser.extract_from_text(text, doc_id, chunk_id, **kwargs)
