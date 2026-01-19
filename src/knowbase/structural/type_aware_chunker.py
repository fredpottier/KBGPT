"""
OSMOSE Structural Graph - Type-Aware Chunker (Option C)

Chunking conscient du type pour séparation NARRATIVE/TABLE/FIGURE.

Ce module implémente le chunking type-aware:
- NARRATIVE_TEXT: TEXT, HEADING, CAPTION, FOOTNOTE → relation extraction
- TABLE_TEXT: TABLE → traitement spécifique tables
- FIGURE_TEXT: FIGURE + CAPTION → enrichissement vision
- CODE_TEXT: CODE, FORMULA → analyse code (optionnel)

Spec: doc/ongoing/ADR_STRUCTURAL_GRAPH_FROM_DOCLING.md - Section "Chunking Type-Aware"
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Tuple
from uuid import uuid4

from knowbase.structural.models import (
    ChunkKind,
    DocItem,
    DocItemType,
    SectionInfo,
    StructuralProfile,
    TypeAwareChunk,
    RELATION_BEARING_TYPES,
)
from knowbase.structural.section_profiler import is_item_relation_bearing

logger = logging.getLogger(__name__)


# ===================================
# CONFIGURATION
# ===================================

# Types narratifs (relation extraction eligible)
NARRATIVE_TYPES = {
    DocItemType.TEXT,
    DocItemType.HEADING,
    DocItemType.CAPTION,
    DocItemType.FOOTNOTE,
}

# Taille maximale des chunks narratifs (en caractères)
MAX_NARRATIVE_CHUNK_SIZE = 3000

# Overlap pour les chunks narratifs
NARRATIVE_OVERLAP_RATIO = 0.15


# ===================================
# TYPE-AWARE CHUNKER
# ===================================

class TypeAwareChunker:
    """
    Chunker conscient du type pour Option C.

    Crée des chunks séparés par type:
    - NARRATIVE_TEXT: Agrège les items textuels consécutifs
    - TABLE_TEXT: Un chunk par table
    - FIGURE_TEXT: Un chunk par figure (avec caption si disponible)
    - CODE_TEXT: Un chunk par bloc de code

    Les chunks NARRATIVE_TEXT sont les seuls éligibles pour la relation extraction.

    Usage:
        chunker = TypeAwareChunker(
            tenant_id="default",
            doc_id="mydoc",
            doc_version_id="v1:abc123..."
        )
        chunks = chunker.create_chunks(doc_items, sections)
    """

    def __init__(
        self,
        tenant_id: str,
        doc_id: str,
        doc_version_id: str,
        max_chunk_size: int = MAX_NARRATIVE_CHUNK_SIZE,
        overlap_ratio: float = NARRATIVE_OVERLAP_RATIO,
    ):
        """
        Initialise le chunker.

        Args:
            tenant_id: ID du tenant
            doc_id: ID du document
            doc_version_id: Hash de la version
            max_chunk_size: Taille max des chunks narratifs
            overlap_ratio: Ratio d'overlap pour les chunks narratifs
        """
        self.tenant_id = tenant_id
        self.doc_id = doc_id
        self.doc_version_id = doc_version_id
        self.max_chunk_size = max_chunk_size
        self.overlap_ratio = overlap_ratio

    def create_chunks(
        self,
        items: List[DocItem],
        sections: List[SectionInfo],
    ) -> List[TypeAwareChunk]:
        """
        Crée des chunks type-aware depuis les DocItems.

        Args:
            items: Liste de DocItems triés par reading_order_index
            sections: Liste de SectionInfo avec profils

        Returns:
            Liste de TypeAwareChunk
        """
        if not items:
            return []

        # Trier par reading_order
        sorted_items = sorted(items, key=lambda x: x.reading_order_index)

        # Créer un mapping section_id → profile
        section_profiles = {
            s.section_id: s.structural_profile or StructuralProfile.empty()
            for s in sections
        }

        chunks: List[TypeAwareChunk] = []
        narrative_buffer: List[DocItem] = []

        for item in sorted_items:
            profile = section_profiles.get(item.section_id, StructuralProfile.empty())

            # Déterminer si c'est un item narratif
            if self._is_narrative_item(item, profile):
                narrative_buffer.append(item)

                # Vérifier si on doit flush le buffer
                if self._should_flush_narrative(narrative_buffer):
                    chunk = self._create_narrative_chunk(narrative_buffer, profile)
                    if chunk:
                        chunks.append(chunk)

                    # Garder les derniers items pour overlap
                    overlap_count = max(1, int(len(narrative_buffer) * self.overlap_ratio))
                    narrative_buffer = narrative_buffer[-overlap_count:]

            else:
                # Flush le buffer narratif
                if narrative_buffer:
                    chunk = self._create_narrative_chunk(narrative_buffer, profile)
                    if chunk:
                        chunks.append(chunk)
                    narrative_buffer = []

                # Créer un chunk dédié pour cet item
                chunk = self._create_dedicated_chunk(item)
                if chunk:
                    chunks.append(chunk)

        # Flush le buffer final
        if narrative_buffer:
            profile = section_profiles.get(
                narrative_buffer[0].section_id,
                StructuralProfile.empty()
            )
            chunk = self._create_narrative_chunk(narrative_buffer, profile)
            if chunk:
                chunks.append(chunk)

        logger.info(
            f"[TypeAwareChunker] Created {len(chunks)} chunks from "
            f"{len(items)} items for doc={self.doc_id}"
        )

        return chunks

    def _is_narrative_item(self, item: DocItem, profile: StructuralProfile) -> bool:
        """
        Détermine si un item est narratif.

        Args:
            item: DocItem à vérifier
            profile: Profil de la section

        Returns:
            True si l'item est narratif
        """
        if item.item_type in NARRATIVE_TYPES:
            return True

        # LIST_ITEM dépend du contexte (D3.3)
        if item.item_type == DocItemType.LIST_ITEM:
            return profile.is_relation_bearing and profile.list_ratio < 0.5

        return False

    def _should_flush_narrative(self, buffer: List[DocItem]) -> bool:
        """
        Détermine si le buffer narratif doit être flush.

        Args:
            buffer: Buffer d'items narratifs

        Returns:
            True si on doit créer un chunk
        """
        if not buffer:
            return False

        # Calculer la taille totale
        total_size = sum(len(item.text or "") for item in buffer)

        return total_size >= self.max_chunk_size

    def _create_narrative_chunk(
        self,
        items: List[DocItem],
        profile: StructuralProfile,
    ) -> Optional[TypeAwareChunk]:
        """
        Crée un chunk narratif depuis un groupe d'items.

        Args:
            items: Liste d'items narratifs
            profile: Profil de la section

        Returns:
            TypeAwareChunk ou None si vide
        """
        if not items:
            return None

        # Merger les textes
        texts = [item.text for item in items if item.text]
        if not texts:
            return None

        merged_text = "\n\n".join(texts)

        # Calculer page span
        pages = [i.page_no for i in items]
        page_no = min(pages)
        page_span_min = min(pages) if len(set(pages)) > 1 else None
        page_span_max = max(pages) if len(set(pages)) > 1 else None

        # Section ID (premier item)
        section_id = items[0].section_id

        return TypeAwareChunk(
            tenant_id=self.tenant_id,
            doc_id=self.doc_id,
            doc_version_id=self.doc_version_id,
            section_id=section_id,
            kind=ChunkKind.NARRATIVE_TEXT,
            text=merged_text,
            item_ids=[i.item_id for i in items],
            page_no=page_no,
            page_span_min=page_span_min,
            page_span_max=page_span_max,
            is_relation_bearing=True,  # NARRATIVE chunks sont toujours relation-bearing
        )

    def _create_dedicated_chunk(self, item: DocItem) -> Optional[TypeAwareChunk]:
        """
        Crée un chunk dédié pour un item non-narratif.

        Args:
            item: DocItem (TABLE, FIGURE, CODE, etc.)

        Returns:
            TypeAwareChunk ou None
        """
        # Déterminer le type de chunk
        if item.item_type == DocItemType.TABLE:
            kind = ChunkKind.TABLE_TEXT
        elif item.item_type == DocItemType.FIGURE:
            kind = ChunkKind.FIGURE_TEXT
        elif item.item_type in {DocItemType.CODE, DocItemType.FORMULA}:
            kind = ChunkKind.CODE_TEXT
        else:
            # Autres types structure-bearing: pas de chunk dédié
            return None

        # Pour FIGURE, le texte peut être vide (D11.4)
        text = item.text or ""

        return TypeAwareChunk(
            tenant_id=self.tenant_id,
            doc_id=self.doc_id,
            doc_version_id=self.doc_version_id,
            section_id=item.section_id,
            kind=kind,
            text=text,
            item_ids=[item.item_id],
            page_no=item.page_no,
            is_relation_bearing=False,  # Structure chunks ne sont pas relation-bearing
        )


# ===================================
# CHUNK FILTERING UTILITIES
# ===================================

def get_narrative_chunks(chunks: List[TypeAwareChunk]) -> List[TypeAwareChunk]:
    """
    Filtre les chunks narratifs (éligibles pour relation extraction).

    Args:
        chunks: Liste de TypeAwareChunk

    Returns:
        Liste des chunks NARRATIVE_TEXT uniquement
    """
    return [c for c in chunks if c.kind == ChunkKind.NARRATIVE_TEXT]


def get_table_chunks(chunks: List[TypeAwareChunk]) -> List[TypeAwareChunk]:
    """Filtre les chunks de tables."""
    return [c for c in chunks if c.kind == ChunkKind.TABLE_TEXT]


def get_figure_chunks(chunks: List[TypeAwareChunk]) -> List[TypeAwareChunk]:
    """Filtre les chunks de figures."""
    return [c for c in chunks if c.kind == ChunkKind.FIGURE_TEXT]


def get_code_chunks(chunks: List[TypeAwareChunk]) -> List[TypeAwareChunk]:
    """Filtre les chunks de code."""
    return [c for c in chunks if c.kind == ChunkKind.CODE_TEXT]


# ===================================
# CHUNK ANALYSIS
# ===================================

def analyze_chunks(chunks: List[TypeAwareChunk]) -> Dict[str, Any]:
    """
    Analyse la distribution des chunks.

    Args:
        chunks: Liste de TypeAwareChunk

    Returns:
        Dictionnaire d'analyse
    """
    from collections import Counter

    kind_counts = Counter(c.kind.value for c in chunks)
    total_text_size = sum(len(c.text) for c in chunks)
    narrative_chunks = get_narrative_chunks(chunks)
    narrative_text_size = sum(len(c.text) for c in narrative_chunks)

    return {
        "total_chunks": len(chunks),
        "kind_distribution": dict(kind_counts),
        "total_text_size": total_text_size,
        "narrative_chunks": len(narrative_chunks),
        "narrative_text_size": narrative_text_size,
        "narrative_ratio": len(narrative_chunks) / len(chunks) if chunks else 0,
        "avg_chunk_size": total_text_size / len(chunks) if chunks else 0,
        "avg_items_per_chunk": sum(len(c.item_ids) for c in chunks) / len(chunks) if chunks else 0,
    }


# ===================================
# CHUNK-ITEM MAPPING
# ===================================

def build_item_to_chunk_mapping(chunks: List[TypeAwareChunk]) -> Dict[str, str]:
    """
    Construit un mapping item_id → chunk_id.

    Args:
        chunks: Liste de TypeAwareChunk

    Returns:
        Dict mapping item_id vers chunk_id
    """
    mapping = {}
    for chunk in chunks:
        for item_id in chunk.item_ids:
            mapping[item_id] = chunk.chunk_id
    return mapping


def get_chunks_for_items(
    chunks: List[TypeAwareChunk],
    item_ids: List[str],
) -> List[TypeAwareChunk]:
    """
    Trouve les chunks contenant des items donnés.

    Args:
        chunks: Liste de TypeAwareChunk
        item_ids: Liste d'item_ids à chercher

    Returns:
        Liste des chunks contenant au moins un item
    """
    item_set = set(item_ids)
    return [c for c in chunks if any(iid in item_set for iid in c.item_ids)]
