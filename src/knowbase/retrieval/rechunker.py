"""
OSMOSE Retrieval Layer — Re-chunker pour embeddings vectoriels.

Re-découpe les TypeAwareChunks en sous-chunks de ~target_chars caractères
pour optimiser la qualité des embeddings (fenêtre modèle ~512 tokens).

Spec: ADR_QDRANT_RETRIEVAL_PROJECTION_V2.md
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from typing import List, Optional

from knowbase.structural.models import TypeAwareChunk

logger = logging.getLogger(__name__)

# Namespace UUID5 constant pour idempotence Qdrant (jamais re-généré)
OSMOSE_NAMESPACE = uuid.UUID("a1b2c3d4-e5f6-7890-abcd-ef1234567890")


@dataclass
class SubChunk:
    """Sous-chunk pour embedding vectoriel dans Qdrant Layer R."""

    chunk_id: str           # ID du chunk parent
    sub_index: int          # Index du sous-chunk (0 si chunk non découpé)
    text: str               # Texte original (affiché/cité)
    parent_chunk_id: str    # = chunk_id
    section_id: Optional[str]
    doc_id: str
    tenant_id: str
    kind: str               # ChunkKind.value
    page_no: int
    page_span_min: Optional[int] = None
    page_span_max: Optional[int] = None
    item_ids: List[str] = field(default_factory=list)
    text_origin: Optional[str] = None

    def point_id(self) -> str:
        """UUID5 déterministe pour idempotence Qdrant."""
        key = f"{self.tenant_id}:{self.doc_id}:{self.chunk_id}:{self.sub_index}"
        return str(uuid.uuid5(OSMOSE_NAMESPACE, key))


def _find_sentence_break(text: str, window_start: int, window_end: int) -> Optional[int]:
    """
    Cherche la dernière fin de phrase (. ! ?) dans la fenêtre [window_start, window_end].

    Returns:
        Position après le caractère de fin de phrase, ou None si aucun trouvé.
    """
    best = None
    for i in range(window_end - 1, window_start - 1, -1):
        if text[i] in ".!?":
            best = i + 1
            break
    return best


def _find_line_break(text: str, window_start: int, window_end: int) -> Optional[int]:
    """
    Cherche le dernier saut de ligne dans la fenêtre [window_start, window_end].

    Returns:
        Position après le \n, ou None si aucun trouvé.
    """
    best = None
    for i in range(window_end - 1, window_start - 1, -1):
        if text[i] == "\n":
            best = i + 1
            break
    return best


def rechunk_for_retrieval(
    chunks: List[TypeAwareChunk],
    tenant_id: str,
    doc_id: str,
    target_chars: int = 1500,
    overlap_chars: int = 200,
) -> List[SubChunk]:
    """
    Re-découpe les TypeAwareChunks en sous-chunks pour embeddings vectoriels.

    Stratégie de coupe (3 niveaux):
    1. Fin de phrase (. ! ?) dans les 200 derniers chars de la fenêtre
    2. Fin de ligne (\n) dans les 200 derniers chars
    3. Hard cut à target_chars (garantit terminaison)

    Args:
        chunks: Liste de TypeAwareChunks à re-découper
        tenant_id: ID du tenant
        doc_id: ID du document
        target_chars: Taille cible par sous-chunk (dynamique depuis EmbeddingModelManager)
        overlap_chars: Chevauchement entre sous-chunks consécutifs

    Returns:
        Liste de SubChunks prêts pour embedding
    """
    sub_chunks: List[SubChunk] = []

    for chunk in chunks:
        text = chunk.text
        text_len = len(text)

        # Chunk suffisamment court → 1 seul SubChunk
        if text_len <= target_chars:
            sub_chunks.append(SubChunk(
                chunk_id=chunk.chunk_id,
                sub_index=0,
                text=text,
                parent_chunk_id=chunk.chunk_id,
                section_id=chunk.section_id,
                doc_id=doc_id,
                tenant_id=tenant_id,
                kind=chunk.kind.value,
                page_no=chunk.page_no,
                page_span_min=chunk.page_span_min,
                page_span_max=chunk.page_span_max,
                item_ids=chunk.item_ids,
                text_origin=chunk.text_origin.value if chunk.text_origin else None,
            ))
            continue

        # Découpe en sous-chunks avec overlap
        sub_index = 0
        pos = 0

        while pos < text_len:
            # Fin de la fenêtre courante
            window_end = min(pos + target_chars, text_len)

            # Si on couvre le reste du texte, prendre tout
            if window_end >= text_len:
                sub_text = text[pos:]
            else:
                # Stratégie de coupe à 3 niveaux
                # Fenêtre de recherche: les 200 derniers chars de la fenêtre
                search_start = max(pos, window_end - overlap_chars)

                # 1. Chercher une fin de phrase
                cut_pos = _find_sentence_break(text, search_start, window_end)

                # 2. Sinon, chercher un saut de ligne
                if cut_pos is None:
                    cut_pos = _find_line_break(text, search_start, window_end)

                # 3. Hard cut fallback (garantit la terminaison)
                if cut_pos is None:
                    cut_pos = window_end

                sub_text = text[pos:cut_pos]

            if sub_text.strip():  # Ne pas créer de sous-chunks vides
                sub_chunks.append(SubChunk(
                    chunk_id=chunk.chunk_id,
                    sub_index=sub_index,
                    text=sub_text,
                    parent_chunk_id=chunk.chunk_id,
                    section_id=chunk.section_id,
                    doc_id=doc_id,
                    tenant_id=tenant_id,
                    kind=chunk.kind.value,
                    page_no=chunk.page_no,
                    page_span_min=chunk.page_span_min,
                    page_span_max=chunk.page_span_max,
                    item_ids=chunk.item_ids,
                    text_origin=chunk.text_origin.value if chunk.text_origin else None,
                ))
                sub_index += 1

            # Avancer avec overlap
            new_pos = pos + len(sub_text)
            if new_pos <= pos:
                # Sécurité: avancer d'au moins 1 char pour éviter boucle infinie
                new_pos = pos + 1
            # Reculer de overlap_chars pour le chevauchement
            if new_pos < text_len:
                pos = max(new_pos - overlap_chars, pos + 1)
            else:
                pos = new_pos

    logger.info(
        f"[OSMOSE:Rechunker] {len(chunks)} chunks → {len(sub_chunks)} sub-chunks "
        f"(target={target_chars}, overlap={overlap_chars})"
    )

    return sub_chunks
