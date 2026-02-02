"""
OSMOSE Retrieval Layer — Re-chunker pour embeddings vectoriels.

Re-découpe les TypeAwareChunks en sous-chunks de ~target_chars caractères
pour optimiser la qualité des embeddings (fenêtre modèle ~512 tokens).

Inclut un pré-filtrage qualité pour éliminer les chunks vides, trop courts,
ou sans contenu sémantique exploitable avant embedding.

Spec: ADR_QDRANT_RETRIEVAL_PROJECTION_V2.md
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from typing import List, Optional

from knowbase.structural.models import ChunkKind, TypeAwareChunk

logger = logging.getLogger(__name__)

# --- Seuils de filtrage qualité ---
MIN_CHARS_MEANINGFUL = 30       # Sous ce seuil, un chunk n'a pas de valeur sémantique
MIN_CHARS_NON_NARRATIVE = 15    # Seuil minimal pour TABLE/FIGURE/CODE (plus permissif)
MIN_WORD_COUNT = 3              # Au moins 3 mots pour être exploitable

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


@dataclass
class FilterStats:
    """Statistiques de filtrage qualité pré-rechunking."""
    total_input: int = 0
    kept: int = 0
    dropped_empty: int = 0
    dropped_too_short: int = 0
    dropped_no_words: int = 0
    merged_into_next: int = 0


def _is_chunk_usable(chunk: TypeAwareChunk) -> bool:
    """
    Vérifie si un chunk a assez de contenu sémantique pour valoir un embedding.

    Critères :
    - Texte non vide après strip
    - Longueur minimale selon le type (NARRATIVE plus strict)
    - Au moins MIN_WORD_COUNT mots
    """
    text = chunk.text.strip()
    if not text:
        return False

    text_len = len(text)
    word_count = len(text.split())

    # Seuil adapté au type de chunk
    if chunk.kind == ChunkKind.NARRATIVE_TEXT:
        min_chars = MIN_CHARS_MEANINGFUL
    else:
        # TABLE/FIGURE/CODE : seuil plus bas (données structurées)
        min_chars = MIN_CHARS_NON_NARRATIVE

    if text_len < min_chars:
        return False

    if word_count < MIN_WORD_COUNT:
        return False

    return True


def _filter_chunks(chunks: List[TypeAwareChunk]) -> tuple[List[TypeAwareChunk], FilterStats]:
    """
    Filtre les chunks inutilisables avant rechunking.

    Stratégie :
    1. Exclure les chunks vides (texte vide ou whitespace-only)
    2. Exclure les chunks trop courts (< seuil selon type)
    3. Exclure les chunks avec moins de MIN_WORD_COUNT mots

    Les chunks NARRATIVE_TEXT courts (titres isolés) qui précèdent un autre
    NARRATIVE_TEXT sont fusionnés avec le chunk suivant plutôt que supprimés,
    pour préserver le contexte.

    Returns:
        (chunks filtrés, stats de filtrage)
    """
    stats = FilterStats(total_input=len(chunks))

    if not chunks:
        return [], stats

    # Phase 1 : Fusion des titres courts NARRATIVE dans le chunk NARRATIVE suivant
    merged: List[TypeAwareChunk] = []
    pending_prefix: Optional[str] = None  # texte d'un titre court à fusionner

    for i, chunk in enumerate(chunks):
        text = chunk.text.strip()

        # Chunk vide → drop immédiat
        if not text:
            stats.dropped_empty += 1
            continue

        # NARRATIVE court (titre isolé) → tenter fusion avec le suivant
        if (
            chunk.kind == ChunkKind.NARRATIVE_TEXT
            and len(text) < MIN_CHARS_MEANINGFUL
            and len(text.split()) < MIN_WORD_COUNT
        ):
            # Regarder si le prochain chunk est aussi NARRATIVE
            next_narrative = None
            for j in range(i + 1, len(chunks)):
                if chunks[j].text.strip():
                    if chunks[j].kind == ChunkKind.NARRATIVE_TEXT:
                        next_narrative = j
                    break

            if next_narrative is not None:
                # Accumuler comme préfixe pour le prochain NARRATIVE
                if pending_prefix:
                    pending_prefix = f"{pending_prefix}\n{text}"
                else:
                    pending_prefix = text
                stats.merged_into_next += 1
                continue

        # Si on a un préfixe en attente et que ce chunk est NARRATIVE, fusionner
        if pending_prefix and chunk.kind == ChunkKind.NARRATIVE_TEXT:
            # Créer un chunk modifié avec le préfixe
            merged_chunk = chunk.model_copy(
                update={"text": f"{pending_prefix}\n{text}"}
            )
            merged.append(merged_chunk)
            pending_prefix = None
            continue

        # Préfixe en attente mais chunk non-NARRATIVE → drop le préfixe
        if pending_prefix:
            # Le préfixe ne peut pas fusionner, on le compte comme trop court
            stats.dropped_too_short += 1
            pending_prefix = None

        merged.append(chunk)

    # Préfixe final non fusionné
    if pending_prefix:
        stats.dropped_too_short += 1

    # Phase 2 : Filtrage qualité sur les chunks restants
    result: List[TypeAwareChunk] = []
    for chunk in merged:
        if _is_chunk_usable(chunk):
            result.append(chunk)
        else:
            text = chunk.text.strip()
            if not text:
                stats.dropped_empty += 1
            elif len(text.split()) < MIN_WORD_COUNT:
                stats.dropped_no_words += 1
            else:
                stats.dropped_too_short += 1

    stats.kept = len(result)
    return result, stats


def rechunk_for_retrieval(
    chunks: List[TypeAwareChunk],
    tenant_id: str,
    doc_id: str,
    target_chars: int = 1500,
    overlap_chars: int = 200,
) -> List[SubChunk]:
    """
    Re-découpe les TypeAwareChunks en sous-chunks pour embeddings vectoriels.

    Applique d'abord un filtrage qualité pour éliminer les chunks vides,
    trop courts ou sans valeur sémantique, puis re-découpe.

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
    # --- Pré-filtrage qualité ---
    filtered_chunks, fstats = _filter_chunks(chunks)

    dropped_total = fstats.total_input - fstats.kept
    if dropped_total > 0:
        logger.info(
            f"[OSMOSE:Rechunker] Filtrage qualité: {fstats.total_input} → {fstats.kept} chunks "
            f"(dropped: {fstats.dropped_empty} vides, {fstats.dropped_too_short} trop courts, "
            f"{fstats.dropped_no_words} sans mots, {fstats.merged_into_next} fusionnés)"
        )

    sub_chunks: List[SubChunk] = []

    for chunk in filtered_chunks:
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
        f"[OSMOSE:Rechunker] {len(chunks)} chunks (→ {fstats.kept} après filtrage) "
        f"→ {len(sub_chunks)} sub-chunks (target={target_chars}, overlap={overlap_chars})"
    )

    return sub_chunks
