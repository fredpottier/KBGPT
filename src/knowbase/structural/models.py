"""
OSMOSE Structural Graph - Modèles de données (Option C)

Modèles Pydantic pour le Structural Graph from DoclingDocument.

Spec: doc/ongoing/ADR_STRUCTURAL_GRAPH_FROM_DOCLING.md
"""

from __future__ import annotations

import hashlib
import json
import logging
from copy import deepcopy
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Literal, Optional, Set

from pydantic import BaseModel, Field
from uuid import uuid4


logger = logging.getLogger(__name__)


# ===================================
# ENUMS - Types d'items (D3)
# ===================================

class DocItemType(str, Enum):
    """
    Types d'items documentaires.

    Mapping depuis DocItemLabel de Docling vers types canoniques.
    Spec: ADR D3.1, D3.2
    """
    # Relation-bearing types (D3.1)
    TEXT = "TEXT"
    HEADING = "HEADING"
    CAPTION = "CAPTION"
    FOOTNOTE = "FOOTNOTE"

    # Structure-bearing types (D3.2)
    TABLE = "TABLE"
    FIGURE = "FIGURE"
    CODE = "CODE"
    FORMULA = "FORMULA"
    FURNITURE = "FURNITURE"  # headers/footers
    REFERENCE = "REFERENCE"

    # Contextual
    LIST_ITEM = "LIST_ITEM"  # Relation-bearing dépend du contexte (D3.3)

    # Fallback
    OTHER = "OTHER"


class BboxUnit(str, Enum):
    """Unité des coordonnées bbox (D5.3)."""
    POINTS = "points"
    PIXELS = "pixels"
    NORMALIZED = "normalized"


class ChunkKind(str, Enum):
    """Types de chunks (type-aware chunking)."""
    NARRATIVE_TEXT = "NARRATIVE_TEXT"
    TABLE_TEXT = "TABLE_TEXT"
    FIGURE_TEXT = "FIGURE_TEXT"
    CODE_TEXT = "CODE_TEXT"


# ===================================
# CONSTANTES (D3)
# ===================================

RELATION_BEARING_TYPES: Set[DocItemType] = {
    DocItemType.TEXT,
    DocItemType.HEADING,
    DocItemType.CAPTION,
    DocItemType.FOOTNOTE,
}

STRUCTURE_BEARING_TYPES: Set[DocItemType] = {
    DocItemType.TABLE,
    DocItemType.FIGURE,
    DocItemType.CODE,
    DocItemType.FORMULA,
    DocItemType.FURNITURE,
    DocItemType.REFERENCE,
    DocItemType.OTHER,
}


# ===================================
# MAPPING DocItemLabel -> DocItemType
# ===================================

DOCLING_LABEL_MAPPING: Dict[str, DocItemType] = {
    # Text types
    "text": DocItemType.TEXT,
    "paragraph": DocItemType.TEXT,

    # Headings
    "title": DocItemType.HEADING,
    "section_header": DocItemType.HEADING,

    # Lists
    "list_item": DocItemType.LIST_ITEM,

    # Tables
    "table": DocItemType.TABLE,
    "chart": DocItemType.TABLE,  # Charts traités comme tables

    # Figures
    "picture": DocItemType.FIGURE,

    # Captions
    "caption": DocItemType.CAPTION,

    # Code
    "code": DocItemType.CODE,

    # Formulas
    "formula": DocItemType.FORMULA,

    # Footnotes
    "footnote": DocItemType.FOOTNOTE,

    # Furniture (headers/footers)
    "page_header": DocItemType.FURNITURE,
    "page_footer": DocItemType.FURNITURE,

    # References
    "reference": DocItemType.REFERENCE,

    # Special
    "document_index": DocItemType.OTHER,
    "checkbox_selected": DocItemType.OTHER,
    "checkbox_unselected": DocItemType.OTHER,
    "form": DocItemType.OTHER,
    "key_value_region": DocItemType.OTHER,
    "grading_scale": DocItemType.OTHER,
    "handwritten_text": DocItemType.TEXT,
    "empty_value": DocItemType.OTHER,
}


def map_docling_label(label: str) -> DocItemType:
    """
    Mappe un label Docling vers un DocItemType.

    Args:
        label: Label Docling (ex: "text", "section_header")

    Returns:
        DocItemType correspondant, OTHER si inconnu
    """
    label_lower = label.lower() if label else ""
    return DOCLING_LABEL_MAPPING.get(label_lower, DocItemType.OTHER)


# ===================================
# MODÈLES PYDANTIC
# ===================================

class DocItem(BaseModel):
    """
    Item documentaire structurel.

    Représente un élément atomique du document (paragraphe, table, figure, etc.)
    avec sa provenance complète.

    Spec: ADR Section "Modèle de Données" - DocItem
    """
    # Identifiants (D1)
    tenant_id: str
    doc_id: str
    doc_version_id: str  # = doc_hash
    item_id: str  # = Docling self_ref

    # Type et contenu (D3)
    item_type: DocItemType
    heading_level: Optional[int] = None  # Pour HEADING uniquement
    text: str = ""  # Texte ou Markdown pour TABLE
    table_json: Optional[str] = None  # JSON canonique pour TABLE

    # Hiérarchie Docling (conservée comme metadata, D4.6)
    parent_item_id: Optional[str] = None
    group_id: Optional[str] = None

    # Provenance (D5)
    page_no: int
    page_span_min: Optional[int] = None  # Si multi-page
    page_span_max: Optional[int] = None
    bbox_x0: Optional[float] = None
    bbox_y0: Optional[float] = None  # top
    bbox_x1: Optional[float] = None
    bbox_y1: Optional[float] = None  # bottom
    bbox_unit: Optional[BboxUnit] = None
    charspan_start: Optional[int] = None  # Per-page (from Docling)
    charspan_end: Optional[int] = None    # Per-page (from Docling)

    # Charspan Contract v1: Document-wide positions (ADR_CHARSPAN_CONTRACT_V1.md)
    charspan_start_docwide: Optional[int] = None  # Document-wide start
    charspan_end_docwide: Optional[int] = None    # Document-wide end

    # Ordre (D2)
    reading_order_index: int

    # Metadata
    confidence: Optional[float] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)

    # Scope Layer (ADR_SCOPE_VS_ASSERTION_SEPARATION)
    # Liste des concept_ids mentionnés dans cet item - pour navigation, pas assertions
    # Peuplé par Pass 2 après extraction des concepts
    mentioned_concepts: List[str] = Field(default_factory=list)

    # Computed (non stocké en Neo4j directement)
    section_id: Optional[str] = None  # Assigné après analyse

    @property
    def has_bbox(self) -> bool:
        """Vérifie si l'item a une bbox valide."""
        return all(v is not None for v in [self.bbox_x0, self.bbox_y0, self.bbox_x1, self.bbox_y1])

    @property
    def is_multi_page(self) -> bool:
        """Vérifie si l'item s'étend sur plusieurs pages."""
        return (
            self.page_span_min is not None and
            self.page_span_max is not None and
            self.page_span_min != self.page_span_max
        )

    def to_neo4j_properties(self) -> Dict[str, Any]:
        """Convertit en properties Neo4j."""
        props = {
            "tenant_id": self.tenant_id,
            "doc_id": self.doc_id,
            "doc_version_id": self.doc_version_id,
            "item_id": self.item_id,
            "item_type": self.item_type.value,
            "text": self.text,
            "page_no": self.page_no,
            "reading_order_index": self.reading_order_index,
            "created_at": self.created_at.isoformat(),
        }

        # Optionnels
        if self.heading_level is not None:
            props["heading_level"] = self.heading_level
        if self.table_json:
            props["table_json"] = self.table_json
        if self.parent_item_id:
            props["parent_item_id"] = self.parent_item_id
        if self.group_id:
            props["group_id"] = self.group_id
        if self.page_span_min is not None:
            props["page_span_min"] = self.page_span_min
        if self.page_span_max is not None:
            props["page_span_max"] = self.page_span_max
        if self.has_bbox:
            props["bbox_x0"] = self.bbox_x0
            props["bbox_y0"] = self.bbox_y0
            props["bbox_x1"] = self.bbox_x1
            props["bbox_y1"] = self.bbox_y1
            props["bbox_unit"] = self.bbox_unit.value if self.bbox_unit else "points"
        if self.charspan_start is not None:
            props["charspan_start"] = self.charspan_start
        if self.charspan_end is not None:
            props["charspan_end"] = self.charspan_end
        # Charspan Contract v1: docwide positions (obligatoires)
        if self.charspan_start_docwide is not None:
            props["charspan_start_docwide"] = self.charspan_start_docwide
        if self.charspan_end_docwide is not None:
            props["charspan_end_docwide"] = self.charspan_end_docwide
        if self.confidence is not None:
            props["confidence"] = self.confidence
        if self.section_id:
            props["section_id"] = self.section_id
        # Scope Layer: concepts mentionnés (pour navigation)
        if self.mentioned_concepts:
            props["mentioned_concepts"] = self.mentioned_concepts

        return props


class StructuralProfile(BaseModel):
    """
    Profil structurel d'une section.

    Calculé depuis les DocItems d'une section pour déterminer
    si elle est relation-bearing ou structure-bearing.

    Spec: ADR D10
    """
    # Ratios par type (D10.1 - calculés par nombre d'items)
    text_ratio: float = 0.0
    heading_ratio: float = 0.0
    table_ratio: float = 0.0
    list_ratio: float = 0.0
    figure_ratio: float = 0.0
    caption_ratio: float = 0.0
    code_ratio: float = 0.0
    other_ratio: float = 0.0

    # Classification (D10.2, D10.3, D10.6)
    is_relation_bearing: bool = False
    is_structure_bearing: bool = False

    # Dominance (D10.5)
    dominant_types: List[str] = Field(default_factory=list)

    # Stats
    total_items: int = 0

    # Relation Likelihood (Pass 3 filtering)
    relation_likelihood: float = 0.5
    relation_likelihood_tier: str = "MEDIUM"  # HIGH | MEDIUM | LOW | VERY_LOW

    @classmethod
    def empty(cls) -> "StructuralProfile":
        """Crée un profil vide."""
        return cls()

    @classmethod
    def from_items(cls, items: List[DocItem]) -> "StructuralProfile":
        """
        Calcule le profil structurel depuis une liste d'items.

        Spec: ADR D10 compute_structural_profile
        """
        from collections import Counter
        from knowbase.structural.relation_likelihood import compute_features

        total = len(items)
        if total == 0:
            return cls.empty()

        counts = Counter(item.item_type for item in items)

        # Calcul des ratios
        text_count = counts.get(DocItemType.TEXT, 0)
        heading_count = counts.get(DocItemType.HEADING, 0)
        table_count = counts.get(DocItemType.TABLE, 0)
        list_count = counts.get(DocItemType.LIST_ITEM, 0)
        figure_count = counts.get(DocItemType.FIGURE, 0)
        caption_count = counts.get(DocItemType.CAPTION, 0)
        code_count = counts.get(DocItemType.CODE, 0)
        footnote_count = counts.get(DocItemType.FOOTNOTE, 0)

        # Top 2 types (D10.5)
        top_types = [t.value for t, _ in counts.most_common(2)]

        # Classification (D10.2, D10.3)
        relation_count = text_count + heading_count + caption_count + footnote_count
        structure_count = table_count + figure_count + list_count

        # Calcul du relation_likelihood_tier depuis le texte concaténé
        section_text = "\n".join(item.text for item in items if item.text)
        rl_features = compute_features(section_text)

        return cls(
            text_ratio=text_count / total,
            heading_ratio=heading_count / total,
            table_ratio=table_count / total,
            list_ratio=list_count / total,
            figure_ratio=figure_count / total,
            caption_ratio=caption_count / total,
            code_ratio=code_count / total,
            other_ratio=(total - relation_count - structure_count - code_count) / total,
            is_relation_bearing=relation_count / total > 0.5,
            is_structure_bearing=structure_count / total > 0.5,
            dominant_types=top_types,
            total_items=total,
            relation_likelihood=rl_features.relation_likelihood,
            relation_likelihood_tier=rl_features.tier,
        )

    def to_neo4j_properties(self) -> Dict[str, Any]:
        """Convertit en properties Neo4j pour SectionContext."""
        return {
            "text_ratio": round(self.text_ratio, 4),
            "heading_ratio": round(self.heading_ratio, 4),
            "table_ratio": round(self.table_ratio, 4),
            "list_ratio": round(self.list_ratio, 4),
            "figure_ratio": round(self.figure_ratio, 4),
            "caption_ratio": round(self.caption_ratio, 4),
            "code_ratio": round(self.code_ratio, 4),
            "is_relation_bearing": self.is_relation_bearing,
            "is_structure_bearing": self.is_structure_bearing,
            "dominant_types": self.dominant_types,
            "total_items": self.total_items,
            "relation_likelihood": round(self.relation_likelihood, 4),
            "relation_likelihood_tier": self.relation_likelihood_tier,
        }


class PageContext(BaseModel):
    """
    Contexte de page.

    Spec: ADR Section "Modèle de Données" - PageContext
    """
    tenant_id: str
    doc_id: str
    doc_version_id: str
    page_no: int
    page_width: float
    page_height: float
    bbox_unit: BboxUnit = BboxUnit.POINTS

    def to_neo4j_properties(self) -> Dict[str, Any]:
        """Convertit en properties Neo4j."""
        return {
            "tenant_id": self.tenant_id,
            "doc_id": self.doc_id,
            "doc_version_id": self.doc_version_id,
            "page_no": self.page_no,
            "page_width": self.page_width,
            "page_height": self.page_height,
            "bbox_unit": self.bbox_unit.value,
        }


class DocumentVersion(BaseModel):
    """
    Version de document.

    Représente une version spécifique d'un document avec son hash.

    Spec: ADR D1.2, D1.4
    """
    tenant_id: str
    doc_id: str
    doc_version_id: str  # = doc_hash
    is_current: bool = True

    # Metadata
    source_uri: Optional[str] = None
    title: Optional[str] = None
    pipeline_version: Optional[str] = None
    docling_version: Optional[str] = None

    # Stats
    page_count: int = 0
    item_count: int = 0

    # Timestamps
    ingested_at: datetime = Field(default_factory=datetime.utcnow)

    def to_neo4j_properties(self) -> Dict[str, Any]:
        """Convertit en properties Neo4j."""
        props = {
            "tenant_id": self.tenant_id,
            "doc_id": self.doc_id,
            "doc_version_id": self.doc_version_id,
            "is_current": self.is_current,
            "page_count": self.page_count,
            "item_count": self.item_count,
            "ingested_at": self.ingested_at.isoformat(),
        }
        if self.source_uri:
            props["source_uri"] = self.source_uri
        if self.title:
            props["title"] = self.title
        if self.pipeline_version:
            props["pipeline_version"] = self.pipeline_version
        if self.docling_version:
            props["docling_version"] = self.docling_version
        return props


class SectionInfo(BaseModel):
    """
    Information de section pour assignment DocItem → Section.

    Spec: ADR D4
    """
    section_id: str
    doc_id: str
    doc_version_id: str
    tenant_id: str

    # Hiérarchie
    section_path: str  # Ex: "1. Introduction / 1.1 Overview"
    section_level: int = 1
    title: Optional[str] = None
    parent_section_id: Optional[str] = None

    # Profil structurel (calculé après assignment)
    structural_profile: Optional[StructuralProfile] = None

    # Items assignés
    item_ids: List[str] = Field(default_factory=list)

    def to_neo4j_properties(self) -> Dict[str, Any]:
        """Convertit en properties Neo4j."""
        props = {
            "section_id": self.section_id,
            "context_id": self.section_id,  # Compat avec SectionContext existant
            "doc_id": self.doc_id,
            "doc_version_id": self.doc_version_id,
            "tenant_id": self.tenant_id,
            "section_path": self.section_path,
            "section_level": self.section_level,
        }
        if self.title:
            props["title"] = self.title
        if self.parent_section_id:
            props["parent_section_id"] = self.parent_section_id
        if self.structural_profile:
            props.update(self.structural_profile.to_neo4j_properties())
        return props


class TypeAwareChunk(BaseModel):
    """
    Chunk avec conscience du type.

    Résultat du type-aware chunking.
    """
    chunk_id: str = Field(default_factory=lambda: f"chunk_{uuid4().hex[:12]}")

    # Identifiants
    tenant_id: str
    doc_id: str
    doc_version_id: str
    section_id: Optional[str] = None

    # Type
    kind: ChunkKind

    # Contenu
    text: str
    item_ids: List[str] = Field(default_factory=list)  # DocItems sources

    # Provenance
    page_no: int
    page_span_min: Optional[int] = None
    page_span_max: Optional[int] = None

    # Metadata
    is_relation_bearing: bool = False  # Peut être utilisé pour relation extraction
    created_at: datetime = Field(default_factory=datetime.utcnow)

    def to_neo4j_properties(self) -> Dict[str, Any]:
        """Convertit en properties Neo4j."""
        return {
            "chunk_id": self.chunk_id,
            "tenant_id": self.tenant_id,
            "doc_id": self.doc_id,
            "doc_version_id": self.doc_version_id,
            "section_id": self.section_id,
            "kind": self.kind.value,
            "text": self.text,
            "item_ids": self.item_ids,
            "page_no": self.page_no,
            "page_span_min": self.page_span_min,
            "page_span_max": self.page_span_max,
            "is_relation_bearing": self.is_relation_bearing,
            "created_at": self.created_at.isoformat(),
        }


# ===================================
# DOC_HASH COMPUTATION (D6)
# ===================================

# Champs volatiles à exclure (D6.2)
VOLATILE_ORIGIN_KEYS = {"mtime", "atime", "ctime", "path", "uri", "filename"}
VOLATILE_ROOT_KEYS = {
    "created_at", "processed_at", "timestamp", "runtime",
    "elapsed", "pipeline_version", "docling_version"
}

# Précision par défaut pour l'arrondi (D6.6)
HASH_FLOAT_PRECISION = 2


def round_floats_recursive(obj: Any, decimals: int = HASH_FLOAT_PRECISION) -> None:
    """
    Arrondit tous les floats récursivement (in-place).

    Spec: ADR D6.3
    """
    if isinstance(obj, dict):
        for k, v in obj.items():
            if isinstance(v, float):
                obj[k] = round(v, decimals)
            else:
                round_floats_recursive(v, decimals)
    elif isinstance(obj, list):
        for i, item in enumerate(obj):
            if isinstance(item, float):
                obj[i] = round(item, decimals)
            else:
                round_floats_recursive(item, decimals)


def compute_doc_hash(doc_dict: Dict[str, Any], precision: int = HASH_FLOAT_PRECISION) -> str:
    """
    Calcule un hash stable du DoclingDocument.

    Spec: ADR D6

    Args:
        doc_dict: Dictionnaire du DoclingDocument (export_to_dict())
        precision: Nombre de décimales pour l'arrondi

    Returns:
        Hash au format "v1:{sha256}"
    """
    canonical = deepcopy(doc_dict)

    # Supprimer champs volatiles au niveau origin (D6.2)
    if "origin" in canonical and isinstance(canonical["origin"], dict):
        for key in VOLATILE_ORIGIN_KEYS:
            canonical["origin"].pop(key, None)

    # Supprimer champs volatiles au niveau root (D6.2)
    for key in VOLATILE_ROOT_KEYS:
        canonical.pop(key, None)

    # Trier les listes par self_ref pour déterminisme (D6.4)
    for key in ["texts", "tables", "pictures", "groups"]:
        if key in canonical and isinstance(canonical[key], list):
            canonical[key] = sorted(
                canonical[key],
                key=lambda x: x.get("self_ref", "") if isinstance(x, dict) else ""
            )

    # Arrondir les floats (D6.3)
    round_floats_recursive(canonical, decimals=precision)

    # JSON canonique (clés triées, pas d'espaces)
    json_str = json.dumps(canonical, sort_keys=True, separators=(',', ':'))

    # SHA-256 (D6.1)
    sha = hashlib.sha256(json_str.encode()).hexdigest()

    # Préfixe version (D6.5)
    return f"v1:{sha}"
