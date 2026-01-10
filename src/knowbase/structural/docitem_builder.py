"""
OSMOSE Structural Graph - DocItem Builder (Option C)

Extraction des DocItems depuis DoclingDocument.

Ce module est le coeur d'Option C : il consomme la structure native
de Docling au lieu de réinférer depuis le texte linéarisé.

Spec: doc/ongoing/ADR_STRUCTURAL_GRAPH_FROM_DOCLING.md
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple, TYPE_CHECKING

from knowbase.structural.models import (
    BboxUnit,
    DocItem,
    DocItemType,
    DocumentVersion,
    PageContext,
    compute_doc_hash,
    map_docling_label,
)

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)


# ===================================
# TABLE TO TEXT (D11)
# ===================================

MAX_TABLE_ROWS = 50
MAX_TABLE_COLS = 10


def escape_md(text: str) -> str:
    """Échappe les caractères Markdown dans une cellule de table."""
    if not text:
        return ""
    # Échapper les pipes et newlines
    return text.replace("|", "\\|").replace("\n", " ").strip()


def table_to_text(table_item: Any) -> str:
    """
    Convertit une table Docling en Markdown normalisé pour embeddings.

    Spec: ADR D11.2, D11.6, D11.7

    Args:
        table_item: Item table Docling avec data.table_cells

    Returns:
        Représentation Markdown de la table
    """
    try:
        # Extraire les cellules par row
        rows_dict: Dict[int, List[str]] = {}

        if hasattr(table_item, 'data') and hasattr(table_item.data, 'table_cells'):
            for cell in table_item.data.table_cells:
                # Docling 2.66+: row_span peut être int ou range
                if hasattr(cell, 'row_span'):
                    rs = cell.row_span
                    row_idx = rs.start if hasattr(rs, 'start') else int(rs)
                else:
                    row_idx = 0

                if row_idx not in rows_dict:
                    rows_dict[row_idx] = []
                rows_dict[row_idx].append(str(cell.text) if hasattr(cell, 'text') else "")

        if not rows_dict:
            return "[TABLE: empty]"

        # Organiser headers et cells
        sorted_rows = sorted(rows_dict.keys())
        headers = rows_dict.get(sorted_rows[0], [])[:MAX_TABLE_COLS]
        data_rows = [rows_dict.get(r, [])[:MAX_TABLE_COLS] for r in sorted_rows[1:]][:MAX_TABLE_ROWS]

        # Générer Markdown
        lines = []
        if headers:
            lines.append("| " + " | ".join(escape_md(h) for h in headers) + " |")
            lines.append("| " + " | ".join(["---"] * len(headers)) + " |")

        for row in data_rows:
            # Pad row si nécessaire
            padded = row + [""] * (len(headers) - len(row)) if headers else row
            lines.append("| " + " | ".join(escape_md(str(c)) for c in padded) + " |")

        return "\n".join(lines)

    except Exception as e:
        self_ref = getattr(table_item, 'self_ref', 'unknown')
        logger.warning(f"[table_to_text] Failed to convert table {self_ref}: {e}")
        return "[TABLE: parsing error]"


def table_to_json(table_item: Any) -> Optional[str]:
    """
    Convertit une table Docling en JSON canonique.

    Spec: ADR D11.1

    Args:
        table_item: Item table Docling

    Returns:
        JSON string de la structure table, None si erreur
    """
    try:
        rows_dict: Dict[int, List[str]] = {}

        if hasattr(table_item, 'data') and hasattr(table_item.data, 'table_cells'):
            for cell in table_item.data.table_cells:
                if hasattr(cell, 'row_span'):
                    rs = cell.row_span
                    row_idx = rs.start if hasattr(rs, 'start') else int(rs)
                else:
                    row_idx = 0

                if row_idx not in rows_dict:
                    rows_dict[row_idx] = []
                rows_dict[row_idx].append(str(cell.text) if hasattr(cell, 'text') else "")

        sorted_rows = sorted(rows_dict.keys())
        headers = rows_dict.get(sorted_rows[0], []) if sorted_rows else []
        cells = [rows_dict.get(r, []) for r in sorted_rows[1:]] if len(sorted_rows) > 1 else []

        return json.dumps({
            "headers": headers,
            "cells": cells,
            "row_count": len(cells) + (1 if headers else 0),
            "col_count": len(headers) if headers else (len(cells[0]) if cells else 0),
        }, ensure_ascii=False, sort_keys=True)

    except Exception as e:
        self_ref = getattr(table_item, 'self_ref', 'unknown')
        logger.warning(f"[table_to_json] Failed to convert table {self_ref}: {e}")
        return None


def figure_to_text(picture_item: Any, caption: Optional[str] = None) -> str:
    """
    Génère le texte pour une figure.

    Spec: ADR D11.3

    Args:
        picture_item: Item picture Docling
        caption: Caption si disponible

    Returns:
        Caption ou chaîne vide
    """
    return caption.strip() if caption else ""


# ===================================
# PROVENANCE SELECTION (D5)
# ===================================

def select_primary_prov(prov_list: List[Any]) -> Optional[Any]:
    """
    Sélectionne la provenance primaire de façon déterministe.

    Spec: ADR D5.1

    Règle: page_no minimal, puis bbox.top minimal, puis bbox.left minimal

    Args:
        prov_list: Liste de ProvenanceItem Docling

    Returns:
        ProvenanceItem primaire ou None
    """
    if not prov_list:
        return None
    if len(prov_list) == 1:
        return prov_list[0]

    # Tri déterministe
    def sort_key(p):
        page_no = getattr(p, 'page_no', 0) or 0
        bbox = getattr(p, 'bbox', None)
        top = bbox.t if bbox and hasattr(bbox, 't') else 0
        left = bbox.l if bbox and hasattr(bbox, 'l') else 0
        return (page_no, top, left)

    return min(prov_list, key=sort_key)


def extract_bbox(prov: Any) -> Tuple[Optional[float], Optional[float], Optional[float], Optional[float]]:
    """
    Extrait les coordonnées bbox d'une provenance.

    Args:
        prov: ProvenanceItem Docling

    Returns:
        Tuple (x0, y0, x1, y1) ou (None, None, None, None)
    """
    if not prov or not hasattr(prov, 'bbox') or not prov.bbox:
        return (None, None, None, None)

    bbox = prov.bbox
    return (
        getattr(bbox, 'l', None),  # x0 = left
        getattr(bbox, 't', None),  # y0 = top
        getattr(bbox, 'r', None),  # x1 = right
        getattr(bbox, 'b', None),  # y1 = bottom
    )


def compute_page_span(prov_list: List[Any]) -> Tuple[Optional[int], Optional[int]]:
    """
    Calcule le span de pages pour un item multi-page.

    Spec: ADR D5.2

    Args:
        prov_list: Liste de ProvenanceItem

    Returns:
        Tuple (page_span_min, page_span_max) ou (None, None) si single page
    """
    if not prov_list or len(prov_list) <= 1:
        return (None, None)

    pages = [getattr(p, 'page_no', 0) for p in prov_list if hasattr(p, 'page_no')]
    if not pages or len(set(pages)) <= 1:
        return (None, None)

    return (min(pages), max(pages))


# ===================================
# READING ORDER (D2)
# ===================================

def compute_reading_order(items: List[DocItem]) -> List[DocItem]:
    """
    Trie les items par ordre de lecture déterministe.

    Spec: ADR D2.2

    Règle: page_no ASC → bbox.top ASC → bbox.left ASC → item_id ASC (tie-breaker)

    Args:
        items: Liste de DocItems

    Returns:
        Liste triée avec reading_order_index mis à jour
    """
    sorted_items = sorted(items, key=lambda x: (
        x.page_no or 0,
        x.bbox_y0 or 0,      # top
        x.bbox_x0 or 0,      # left
        x.item_id,           # tie-breaker stable
    ))

    for idx, item in enumerate(sorted_items):
        item.reading_order_index = idx

    return sorted_items


# ===================================
# DOCITEM EXTRACTION
# ===================================

class DocItemBuilder:
    """
    Constructeur de DocItems depuis DoclingDocument.

    Usage:
        builder = DocItemBuilder(tenant_id="default", doc_id="mydoc")
        result = builder.build_from_docling(docling_document)

        # result.doc_items - Liste des DocItems
        # result.doc_version - DocumentVersion
        # result.page_contexts - Liste des PageContext
    """

    def __init__(
        self,
        tenant_id: str,
        doc_id: str,
        source_uri: Optional[str] = None,
        pipeline_version: Optional[str] = None,
    ):
        """
        Initialise le builder.

        Args:
            tenant_id: ID du tenant
            doc_id: ID du document
            source_uri: URI source (optionnel)
            pipeline_version: Version du pipeline (optionnel)
        """
        self.tenant_id = tenant_id
        self.doc_id = doc_id
        self.source_uri = source_uri
        self.pipeline_version = pipeline_version

    def build_from_docling(self, doc: Any) -> "DocItemBuildResult":
        """
        Extrait tous les DocItems depuis un DoclingDocument.

        Spec: ADR Section "Extraction depuis DoclingDocument"

        Args:
            doc: DoclingDocument de Docling

        Returns:
            DocItemBuildResult avec items, version, pages
        """
        # Calculer le hash du document (D6)
        doc_dict = doc.export_to_dict() if hasattr(doc, 'export_to_dict') else {}
        doc_hash = compute_doc_hash(doc_dict)

        logger.info(f"[DocItemBuilder] Building items for doc={self.doc_id}, hash={doc_hash[:20]}...")

        items: List[DocItem] = []

        # Extraire les textes
        if hasattr(doc, 'texts') and doc.texts:
            for text_item in doc.texts:
                item = self._extract_text_item(text_item, doc_hash)
                if item:
                    items.append(item)

        # Extraire les tables
        if hasattr(doc, 'tables') and doc.tables:
            for table_item in doc.tables:
                item = self._extract_table_item(table_item, doc_hash)
                if item:
                    items.append(item)

        # Extraire les images/figures
        if hasattr(doc, 'pictures') and doc.pictures:
            for pic_item in doc.pictures:
                item = self._extract_picture_item(pic_item, doc_hash)
                if item:
                    items.append(item)

        # Calculer l'ordre de lecture (D2)
        items = compute_reading_order(items)

        # Extraire les pages
        page_contexts = self._extract_page_contexts(doc, doc_hash)

        # Créer la version du document
        doc_version = DocumentVersion(
            tenant_id=self.tenant_id,
            doc_id=self.doc_id,
            doc_version_id=doc_hash,
            is_current=True,
            source_uri=self.source_uri,
            title=self._extract_title(doc),
            pipeline_version=self.pipeline_version,
            docling_version=self._get_docling_version(doc),
            page_count=len(page_contexts),
            item_count=len(items),
        )

        logger.info(
            f"[DocItemBuilder] Built {len(items)} items, "
            f"{len(page_contexts)} pages for doc={self.doc_id}"
        )

        return DocItemBuildResult(
            doc_items=items,
            doc_version=doc_version,
            page_contexts=page_contexts,
            doc_dict=doc_dict,
        )

    def _extract_text_item(self, text_item: Any, doc_hash: str) -> Optional[DocItem]:
        """Extrait un DocItem depuis un item texte Docling."""
        try:
            # Item ID = self_ref
            item_id = getattr(text_item, 'self_ref', None)
            if not item_id:
                item_id = f"text_{id(text_item)}"

            # Type
            label = str(getattr(text_item, 'label', 'text'))
            item_type = map_docling_label(label)

            # Heading level
            heading_level = None
            if item_type == DocItemType.HEADING:
                # Essayer d'extraire le niveau depuis le label
                import re
                match = re.search(r'(\d+)', label)
                heading_level = int(match.group(1)) if match else 1

            # Texte
            text = str(getattr(text_item, 'text', ''))

            # Provenance
            prov_list = getattr(text_item, 'prov', []) or []
            primary_prov = select_primary_prov(prov_list)
            page_no = getattr(primary_prov, 'page_no', 1) if primary_prov else 1
            bbox = extract_bbox(primary_prov)
            page_span = compute_page_span(prov_list)

            # Charspan
            charspan_start = None
            charspan_end = None
            if primary_prov and hasattr(primary_prov, 'charspan'):
                cs = primary_prov.charspan
                if cs:
                    charspan_start = getattr(cs, 'start', None) or (cs[0] if isinstance(cs, (list, tuple)) else None)
                    charspan_end = getattr(cs, 'end', None) or (cs[1] if isinstance(cs, (list, tuple)) else None)

            # Hiérarchie Docling
            parent_id = None
            if hasattr(text_item, 'parent') and text_item.parent:
                parent_id = getattr(text_item.parent, 'self_ref', None)

            group_id = None
            if hasattr(text_item, 'group') and text_item.group:
                group_id = getattr(text_item.group, 'self_ref', None)

            return DocItem(
                tenant_id=self.tenant_id,
                doc_id=self.doc_id,
                doc_version_id=doc_hash,
                item_id=item_id,
                item_type=item_type,
                heading_level=heading_level,
                text=text,
                parent_item_id=parent_id,
                group_id=group_id,
                page_no=page_no,
                page_span_min=page_span[0],
                page_span_max=page_span[1],
                bbox_x0=bbox[0],
                bbox_y0=bbox[1],
                bbox_x1=bbox[2],
                bbox_y1=bbox[3],
                bbox_unit=BboxUnit.POINTS if bbox[0] is not None else None,
                charspan_start=charspan_start,
                charspan_end=charspan_end,
                reading_order_index=0,  # Sera recalculé
            )

        except Exception as e:
            logger.warning(f"[DocItemBuilder] Failed to extract text item: {e}")
            return None

    def _extract_table_item(self, table_item: Any, doc_hash: str) -> Optional[DocItem]:
        """Extrait un DocItem depuis un item table Docling."""
        try:
            # Item ID = self_ref
            item_id = getattr(table_item, 'self_ref', None)
            if not item_id:
                item_id = f"table_{id(table_item)}"

            # Texte = Markdown (D11.2)
            text = table_to_text(table_item)

            # JSON canonique (D11.1)
            table_json = table_to_json(table_item)

            # Provenance
            prov_list = getattr(table_item, 'prov', []) or []
            primary_prov = select_primary_prov(prov_list)
            page_no = getattr(primary_prov, 'page_no', 1) if primary_prov else 1
            bbox = extract_bbox(primary_prov)
            page_span = compute_page_span(prov_list)

            return DocItem(
                tenant_id=self.tenant_id,
                doc_id=self.doc_id,
                doc_version_id=doc_hash,
                item_id=item_id,
                item_type=DocItemType.TABLE,
                text=text,
                table_json=table_json,
                page_no=page_no,
                page_span_min=page_span[0],
                page_span_max=page_span[1],
                bbox_x0=bbox[0],
                bbox_y0=bbox[1],
                bbox_x1=bbox[2],
                bbox_y1=bbox[3],
                bbox_unit=BboxUnit.POINTS if bbox[0] is not None else None,
                reading_order_index=0,
            )

        except Exception as e:
            logger.warning(f"[DocItemBuilder] Failed to extract table item: {e}")
            return None

    def _extract_picture_item(self, pic_item: Any, doc_hash: str) -> Optional[DocItem]:
        """Extrait un DocItem depuis un item picture Docling."""
        try:
            # Item ID = self_ref
            item_id = getattr(pic_item, 'self_ref', None)
            if not item_id:
                item_id = f"picture_{id(pic_item)}"

            # Caption (si disponible)
            caption = None
            if hasattr(pic_item, 'caption') and pic_item.caption:
                caption = str(pic_item.caption)

            # Texte = caption ou vide (D11.3)
            text = figure_to_text(pic_item, caption)

            # Provenance
            prov_list = getattr(pic_item, 'prov', []) or []
            primary_prov = select_primary_prov(prov_list)
            page_no = getattr(primary_prov, 'page_no', 1) if primary_prov else 1
            bbox = extract_bbox(primary_prov)
            page_span = compute_page_span(prov_list)

            return DocItem(
                tenant_id=self.tenant_id,
                doc_id=self.doc_id,
                doc_version_id=doc_hash,
                item_id=item_id,
                item_type=DocItemType.FIGURE,
                text=text,
                page_no=page_no,
                page_span_min=page_span[0],
                page_span_max=page_span[1],
                bbox_x0=bbox[0],
                bbox_y0=bbox[1],
                bbox_x1=bbox[2],
                bbox_y1=bbox[3],
                bbox_unit=BboxUnit.POINTS if bbox[0] is not None else None,
                reading_order_index=0,
            )

        except Exception as e:
            logger.warning(f"[DocItemBuilder] Failed to extract picture item: {e}")
            return None

    def _extract_page_contexts(self, doc: Any, doc_hash: str) -> List[PageContext]:
        """Extrait les PageContext depuis le DoclingDocument."""
        pages = []

        if hasattr(doc, 'pages') and isinstance(doc.pages, dict):
            for page_num, page_data in doc.pages.items():
                # Dimensions
                width = 612.0  # Default Letter
                height = 792.0
                if hasattr(page_data, 'size'):
                    width = getattr(page_data.size, 'width', 612.0)
                    height = getattr(page_data.size, 'height', 792.0)

                pages.append(PageContext(
                    tenant_id=self.tenant_id,
                    doc_id=self.doc_id,
                    doc_version_id=doc_hash,
                    page_no=int(page_num) if isinstance(page_num, (int, str)) else 1,
                    page_width=width,
                    page_height=height,
                    bbox_unit=BboxUnit.POINTS,
                ))

        # Fallback: si pas de pages, créer au moins une
        if not pages:
            pages.append(PageContext(
                tenant_id=self.tenant_id,
                doc_id=self.doc_id,
                doc_version_id=doc_hash,
                page_no=1,
                page_width=612.0,
                page_height=792.0,
                bbox_unit=BboxUnit.POINTS,
            ))

        return sorted(pages, key=lambda p: p.page_no)

    def _extract_title(self, doc: Any) -> Optional[str]:
        """Extrait le titre du document si disponible."""
        # Essayer différentes sources
        if hasattr(doc, 'name') and doc.name:
            return str(doc.name)[:200]

        # Chercher dans les metadata
        if hasattr(doc, 'origin') and doc.origin:
            if hasattr(doc.origin, 'filename') and doc.origin.filename:
                return str(doc.origin.filename)[:200]

        return None

    def _get_docling_version(self, doc: Any) -> Optional[str]:
        """Récupère la version de Docling utilisée."""
        try:
            import docling
            return getattr(docling, '__version__', None)
        except Exception:
            return None


class DocItemBuildResult:
    """Résultat du build DocItem."""

    def __init__(
        self,
        doc_items: List[DocItem],
        doc_version: DocumentVersion,
        page_contexts: List[PageContext],
        doc_dict: Dict[str, Any],
    ):
        self.doc_items = doc_items
        self.doc_version = doc_version
        self.page_contexts = page_contexts
        self.doc_dict = doc_dict

    @property
    def item_count(self) -> int:
        return len(self.doc_items)

    @property
    def page_count(self) -> int:
        return len(self.page_contexts)

    def get_items_by_type(self, item_type: DocItemType) -> List[DocItem]:
        """Retourne les items d'un type donné."""
        return [i for i in self.doc_items if i.item_type == item_type]

    def get_items_by_page(self, page_no: int) -> List[DocItem]:
        """Retourne les items d'une page donnée."""
        return [i for i in self.doc_items if i.page_no == page_no]

    def get_type_distribution(self) -> Dict[str, int]:
        """Retourne la distribution des types d'items."""
        from collections import Counter
        return dict(Counter(i.item_type.value for i in self.doc_items))

    def summary(self) -> str:
        """Résumé du build."""
        dist = self.get_type_distribution()
        types_str = ", ".join(f"{k}:{v}" for k, v in sorted(dist.items()))
        return (
            f"DocItemBuildResult: {self.item_count} items, "
            f"{self.page_count} pages, hash={self.doc_version.doc_version_id[:20]}... "
            f"Types: [{types_str}]"
        )
