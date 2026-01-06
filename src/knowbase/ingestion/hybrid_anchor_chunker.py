"""
Hybrid Anchor Model - Document-Centric Chunker (Phase 4)

Remplace le TextChunker Phase 1.6 pour le Hybrid Anchor Model:
- Chunking 256 tokens (vs 512) pour meilleure granularite
- SUPPRESSION des concept-focused chunks (source de l'explosion combinatoire)
- Enrichissement payload avec anchored_concepts (liens vers concepts via anchors)

Invariants d'Architecture:
- Les chunks sont decoupes selon des regles fixes (taille, overlap)
- Les concepts sont lies aux chunks via anchors (pas de duplication de contenu)
- Le payload Qdrant ne contient que: concept_id, label, role, span

V2.1 (2024-12): Segment Mapping
- Chaque chunk est mappe vers le segment avec overlap maximal
- Tie-breakers: distance au centre, puis segment le plus ancien
- Validation de couverture segment avec fail-fast optionnel

ADR: doc/ongoing/ADR_HYBRID_ANCHOR_MODEL.md

Author: OSMOSE Phase 2
Date: 2024-12
"""

import uuid
import logging
from typing import List, Dict, Any, Optional, Tuple

import tiktoken

from knowbase.common.clients.embeddings import get_embedding_manager
from knowbase.api.schemas.concepts import Anchor, AnchorPayload
from knowbase.config.feature_flags import get_hybrid_anchor_config
from knowbase.extraction_v2.confidence import get_confidence_scorer  # QW-2
from knowbase.extraction_v2.layout import get_layout_detector, LayoutRegion  # MT-1

logger = logging.getLogger(__name__)


class HybridAnchorChunker:
    """
    Chunker document-centric pour le Hybrid Anchor Model.

    Differences vs TextChunker Phase 1.6:
    - Taille chunk: 256 tokens (vs 512) -> ~180 chunks au lieu de 84
    - Overlap: 64 tokens (vs 128)
    - PAS de concept-focused chunks -> 0 au lieu de 11,713
    - Payload enrichi avec anchored_concepts (liens, pas duplications)

    V2.1: Segment Mapping
    - Chaque chunk recoit segment_id du segment avec overlap maximal
    - Tie-breakers pour overlap egaux: centre le plus proche, puis earliest

    Resultat: ~180 chunks au lieu de ~12,000 -> 98% de reduction
    """

    def __init__(
        self,
        model_name: str = "intfloat/multilingual-e5-large",
        tenant_id: str = "default"
    ):
        """
        Initialize HybridAnchorChunker.

        Args:
            model_name: Embedding model name
            tenant_id: Tenant ID for configuration
        """
        self.tenant_id = tenant_id
        self._model_name = model_name

        # Charger configuration depuis feature flags
        chunking_config = get_hybrid_anchor_config("chunking_config", tenant_id) or {}
        self.chunk_size = chunking_config.get("chunk_size_tokens", 256)
        self.overlap = chunking_config.get("chunk_overlap_tokens", 64)
        self.min_chunk_tokens = chunking_config.get("min_chunk_tokens", 50)

        # Embedding manager (singleton avec auto-unload)
        self._embedding_manager = get_embedding_manager()

        # Tokenizer
        try:
            self.tokenizer = tiktoken.get_encoding("cl100k_base")
        except Exception as e:
            logger.warning(f"[HybridAnchorChunker] Tokenizer failed: {e}")
            self.tokenizer = None

        # QW-2: Confidence scorer pour parse_confidence
        self._confidence_scorer = get_confidence_scorer()

        # MT-1: Layout detector pour chunking structure-aware
        self._layout_detector = get_layout_detector()
        self.layout_aware = chunking_config.get("layout_aware", True)  # Defaut: active

        logger.info(
            f"[HybridAnchorChunker] Initialized "
            f"(chunk_size={self.chunk_size}, overlap={self.overlap}, "
            f"layout_aware={self.layout_aware})"
        )

    def chunk_document(
        self,
        text: str,
        document_id: str,
        document_name: str,
        anchors: Optional[List[Anchor]] = None,
        concept_labels: Optional[Dict[str, str]] = None,
        tenant_id: Optional[str] = None,
        segments: Optional[List[Dict[str, Any]]] = None,
        fail_fast_orphans: bool = False,
        orphan_overlap_min_chars: int = 1
    ) -> List[Dict[str, Any]]:
        """
        Decoupe document en chunks document-centric.

        IMPORTANT: Pas de concept-focused chunks!
        Les concepts sont lies via anchors dans le payload.

        V2.1: Segment Mapping
        - Si segments fournis, chaque chunk recoit segment_id
        - Mapping par overlap maximal avec tie-breakers

        Args:
            text: Texte complet du document
            document_id: ID unique document
            document_name: Nom fichier document
            anchors: Liste d'anchors a mapper vers les chunks
            concept_labels: Mapping concept_id -> label pour enrichir le payload
            tenant_id: ID tenant (optionnel, utilise self.tenant_id)
            segments: Liste de segments avec {segment_id, text, section_id, char_offset}
            fail_fast_orphans: Si True, ValueError si chunks sans segment_id
            orphan_overlap_min_chars: Overlap minimum pour etre considere mappe (defaut: 1)

        Returns:
            Liste de chunks prets pour Qdrant
        """
        if not text or not text.strip():
            logger.warning(f"[HybridAnchorChunker] Empty text for {document_id}")
            return []

        tenant = tenant_id or self.tenant_id

        try:
            # 1. Decouper en chunks (document-centric, pas concept-focused)
            # MT-1: Utiliser le chunking layout-aware si active
            if self.layout_aware:
                raw_chunks = self._split_into_chunks_layout_aware(text)
            else:
                raw_chunks = self._split_into_chunks(text)

            logger.info(
                f"[HybridAnchorChunker] Created {len(raw_chunks)} chunks "
                f"from {len(text)} chars (doc={document_id}, layout_aware={self.layout_aware})"
            )

            # 2. Mapper chunks vers segments (V2.1)
            if segments:
                self._map_chunks_to_segments(
                    raw_chunks, segments, orphan_overlap_min_chars
                )
                logger.info(
                    f"[HybridAnchorChunker] Mapped chunks to {len(segments)} segments"
                )

            # 3. Generer embeddings en batch
            chunk_texts = [c["text"] for c in raw_chunks]
            embeddings = self._generate_embeddings(chunk_texts)

            # 4. Mapper anchors vers chunks
            anchor_mapping = self._map_anchors_to_chunks(raw_chunks, anchors or [])

            # 5. Construire chunks finaux avec payload enrichi
            final_chunks = []
            labels_map = concept_labels or {}
            for i, (chunk_data, embedding) in enumerate(zip(raw_chunks, embeddings)):
                chunk_id = str(uuid.uuid4())

                # Recuperer anchored_concepts pour ce chunk
                anchored_concepts = self._build_anchor_payload(
                    chunk_id, chunk_data, anchor_mapping.get(i, []), labels_map
                )

                # QW-2: Calculer parse_confidence pour ce chunk
                confidence_result = self._confidence_scorer.compute(chunk_data["text"])
                parse_confidence = confidence_result.score

                final_chunks.append({
                    "id": chunk_id,
                    "text": chunk_data["text"],
                    "embedding": embedding.tolist(),
                    "document_id": document_id,
                    "document_name": document_name,
                    "chunk_index": i,
                    "chunk_type": "document_centric",  # JAMAIS "concept_focused"
                    "char_start": chunk_data["char_start"],
                    "char_end": chunk_data["char_end"],
                    "token_count": chunk_data["token_count"],
                    "tenant_id": tenant,
                    # V2.1: Segment mapping
                    "segment_id": chunk_data.get("segment_id"),
                    "segment_overlap_chars": chunk_data.get("segment_overlap_chars", 0),
                    # Payload enrichi avec anchored_concepts (Invariant d'Architecture)
                    "anchored_concepts": anchored_concepts,
                    # Champs legacy pour compatibilite
                    "proto_concept_ids": [ac["concept_id"] for ac in anchored_concepts],
                    "canonical_concept_ids": [],
                    # QW-2: Confidence scores (ADR_REDUCTO_PARSING_PRIMITIVES)
                    "parse_confidence": parse_confidence,
                    "confidence_signals": confidence_result.signals,
                    # MT-1: Layout-aware chunking (ADR_REDUCTO_PARSING_PRIMITIVES)
                    "is_atomic": chunk_data.get("is_atomic", False),
                    "region_type": chunk_data.get("region_type", "unknown"),
                })

            # 6. Valider couverture segment (V2.1)
            if segments:
                self._validate_segment_coverage(final_chunks, fail_fast_orphans)

            # 7. MT-1: Valider qu'aucune table n'a ete coupee
            if self.layout_aware:
                is_valid, violations = self._layout_detector.validate_no_cut_tables(
                    final_chunks, text
                )
                if not is_valid:
                    logger.error(
                        f"[HybridAnchorChunker] MT-1 VIOLATION: {len(violations)} tables coupees!"
                    )

            # 8. Metriques de qualite
            orphan_count = sum(1 for c in final_chunks if not c.get("segment_id"))
            segment_coverage = 1.0 - (orphan_count / len(final_chunks)) if final_chunks else 0.0
            total_anchors = sum(len(c['anchored_concepts']) for c in final_chunks)
            atomic_count = sum(1 for c in final_chunks if c.get("is_atomic", False))

            logger.info(
                f"[HybridAnchorChunker] Done: {len(final_chunks)} chunks "
                f"(segment_coverage={segment_coverage:.1%}, orphans={orphan_count}, "
                f"anchors={total_anchors}, atomic={atomic_count})"
            )

            return final_chunks

        except Exception as e:
            logger.error(
                f"[HybridAnchorChunker] Error chunking {document_id}: {e}",
                exc_info=True
            )
            return []

    def _split_into_chunks(self, text: str) -> List[Dict[str, Any]]:
        """
        Decoupe texte en chunks de taille fixe avec overlap.

        Configuration: 256 tokens, overlap 64 (depuis feature flags)

        Args:
            text: Texte a decouper

        Returns:
            Liste de dicts avec text, char_start, char_end, token_count
        """
        chunks = []

        if self.tokenizer:
            tokens = self.tokenizer.encode(text)

            start_idx = 0
            while start_idx < len(tokens):
                end_idx = min(start_idx + self.chunk_size, len(tokens))
                chunk_tokens = tokens[start_idx:end_idx]

                # Skip si chunk trop petit
                if len(chunk_tokens) < self.min_chunk_tokens and chunks:
                    break

                chunk_text = self.tokenizer.decode(chunk_tokens)

                # Positions dans le texte original
                char_start = len(self.tokenizer.decode(tokens[:start_idx]))
                char_end = len(self.tokenizer.decode(tokens[:end_idx]))

                chunks.append({
                    "text": chunk_text.strip(),
                    "char_start": char_start,
                    "char_end": char_end,
                    "token_count": len(chunk_tokens)
                })

                # Avancer avec overlap
                start_idx += (self.chunk_size - self.overlap)

        else:
            # Fallback char-based (approximation 1 token = 4 chars)
            chunk_chars = self.chunk_size * 4
            overlap_chars = self.overlap * 4

            start_idx = 0
            while start_idx < len(text):
                end_idx = min(start_idx + chunk_chars, len(text))
                chunk_text = text[start_idx:end_idx]

                # Skip si trop petit
                if len(chunk_text) < self.min_chunk_tokens * 4 and chunks:
                    break

                chunks.append({
                    "text": chunk_text.strip(),
                    "char_start": start_idx,
                    "char_end": end_idx,
                    "token_count": len(chunk_text) // 4  # Approximation
                })

                start_idx += (chunk_chars - overlap_chars)

        return chunks

    def _split_into_chunks_layout_aware(self, text: str) -> List[Dict[str, Any]]:
        """
        MT-1: Decoupe texte en chunks en respectant les unites structurelles.

        Regle non-negociable: "Ne jamais couper un tableau"

        Algorithme:
        1. Detecter les regions atomiques (tables, vision)
        2. Pour chaque region non-atomique, chunker normalement
        3. Les regions atomiques deviennent des chunks entiers (meme si > chunk_size)

        Args:
            text: Texte a decouper

        Returns:
            Liste de dicts avec text, char_start, char_end, token_count, is_atomic
        """
        if not text:
            return []

        # 1. Detecter les regions structurelles
        regions = self._layout_detector.detect_regions(text)

        if not regions:
            # Fallback si pas de regions detectees
            return self._split_into_chunks(text)

        chunks = []

        for region in regions:
            if region.atomic:
                # Region atomique: garder entiere (TABLE, VISION)
                # Meme si elle depasse chunk_size
                token_count = self._count_tokens(region.text)
                chunks.append({
                    "text": region.text.strip(),
                    "char_start": region.char_start,
                    "char_end": region.char_end,
                    "token_count": token_count,
                    "is_atomic": True,
                    "region_type": region.type.value,
                })

                if token_count > self.chunk_size:
                    logger.debug(
                        f"[HybridAnchorChunker] Atomic region kept whole: "
                        f"{region.type.value} ({token_count} tokens > {self.chunk_size})"
                    )
            else:
                # Region non-atomique: chunker normalement si assez grande
                region_text = region.text
                if not region_text.strip():
                    continue

                token_count = self._count_tokens(region_text)

                if token_count <= self.chunk_size:
                    # Region petite: un seul chunk
                    if token_count >= self.min_chunk_tokens:
                        chunks.append({
                            "text": region_text.strip(),
                            "char_start": region.char_start,
                            "char_end": region.char_end,
                            "token_count": token_count,
                            "is_atomic": False,
                            "region_type": region.type.value,
                        })
                else:
                    # Region grande: decouper en plusieurs chunks
                    sub_chunks = self._split_region_into_chunks(
                        region_text,
                        region.char_start,
                    )
                    for sc in sub_chunks:
                        sc["is_atomic"] = False
                        sc["region_type"] = region.type.value
                    chunks.extend(sub_chunks)

        # Stats
        atomic_chunks = sum(1 for c in chunks if c.get("is_atomic", False))
        logger.debug(
            f"[HybridAnchorChunker] Layout-aware: {len(chunks)} chunks "
            f"({atomic_chunks} atomic, {len(regions)} regions)"
        )

        return chunks

    def _split_region_into_chunks(
        self,
        region_text: str,
        base_offset: int,
    ) -> List[Dict[str, Any]]:
        """
        Decoupe une region non-atomique en chunks de taille fixe.

        Args:
            region_text: Texte de la region
            base_offset: Offset de debut de la region dans le texte complet

        Returns:
            Liste de chunks
        """
        chunks = []

        if self.tokenizer:
            tokens = self.tokenizer.encode(region_text)

            start_idx = 0
            while start_idx < len(tokens):
                end_idx = min(start_idx + self.chunk_size, len(tokens))
                chunk_tokens = tokens[start_idx:end_idx]

                # Skip si chunk trop petit (sauf le dernier)
                if len(chunk_tokens) < self.min_chunk_tokens and chunks:
                    break

                chunk_text = self.tokenizer.decode(chunk_tokens)

                # Positions relatives dans la region
                rel_char_start = len(self.tokenizer.decode(tokens[:start_idx]))
                rel_char_end = len(self.tokenizer.decode(tokens[:end_idx]))

                chunks.append({
                    "text": chunk_text.strip(),
                    "char_start": base_offset + rel_char_start,
                    "char_end": base_offset + rel_char_end,
                    "token_count": len(chunk_tokens),
                })

                # Avancer avec overlap
                start_idx += (self.chunk_size - self.overlap)

        else:
            # Fallback char-based
            chunk_chars = self.chunk_size * 4
            overlap_chars = self.overlap * 4

            start_idx = 0
            while start_idx < len(region_text):
                end_idx = min(start_idx + chunk_chars, len(region_text))
                chunk_text = region_text[start_idx:end_idx]

                if len(chunk_text) < self.min_chunk_tokens * 4 and chunks:
                    break

                chunks.append({
                    "text": chunk_text.strip(),
                    "char_start": base_offset + start_idx,
                    "char_end": base_offset + end_idx,
                    "token_count": len(chunk_text) // 4,
                })

                start_idx += (chunk_chars - overlap_chars)

        return chunks

    def _count_tokens(self, text: str) -> int:
        """Compte le nombre de tokens dans un texte."""
        if self.tokenizer:
            return len(self.tokenizer.encode(text))
        else:
            # Approximation: 1 token = 4 chars
            return len(text) // 4

    def _generate_embeddings(self, texts: List[str]) -> List[Any]:
        """
        Genere embeddings via EmbeddingManager.

        Args:
            texts: Textes a embedder

        Returns:
            Liste d'embeddings numpy
        """
        import numpy as np

        if not texts:
            return []

        try:
            embeddings = self._embedding_manager.encode(
                texts,
                batch_size=64,
                show_progress_bar=len(texts) > 50,
                convert_to_numpy=True
            )
            return embeddings

        except Exception as e:
            logger.error(f"[HybridAnchorChunker] Embedding error: {e}")
            # Fallback: embeddings vides
            return [np.zeros(1024) for _ in texts]

    def _map_anchors_to_chunks(
        self,
        chunks: List[Dict[str, Any]],
        anchors: List[Anchor]
    ) -> Dict[int, List[Anchor]]:
        """
        Mappe les anchors vers les chunks qui les contiennent.

        Un anchor est mappe vers un chunk si sa position (char_start, char_end)
        tombe dans les bornes du chunk.

        Args:
            chunks: Liste des chunks avec char_start, char_end
            anchors: Liste des anchors avec positions

        Returns:
            Dict chunk_index -> liste d'anchors
        """
        mapping = {}

        for anchor in anchors:
            anchor_start = anchor.char_start
            anchor_end = anchor.char_end

            for i, chunk in enumerate(chunks):
                chunk_start = chunk["char_start"]
                chunk_end = chunk["char_end"]

                # Anchor est dans ce chunk si overlap
                if anchor_start < chunk_end and anchor_end > chunk_start:
                    if i not in mapping:
                        mapping[i] = []
                    mapping[i].append(anchor)

        logger.debug(
            f"[HybridAnchorChunker] Mapped {len(anchors)} anchors to {len(mapping)} chunks"
        )

        return mapping

    def _build_anchor_payload(
        self,
        chunk_id: str,
        chunk_data: Dict[str, Any],
        anchors: List[Anchor],
        concept_labels: Dict[str, str]
    ) -> List[Dict[str, Any]]:
        """
        Construit le payload anchored_concepts pour Qdrant.

        Respecte l'Invariant d'Architecture (ADR):
        - Seuls champs autorises: concept_id, label, role, span

        Args:
            chunk_id: ID du chunk
            chunk_data: Donnees du chunk (positions)
            anchors: Anchors mappes vers ce chunk
            concept_labels: Mapping concept_id -> label

        Returns:
            Liste de dicts pour le payload Qdrant
        """
        anchored_concepts = []
        chunk_start = chunk_data["char_start"]

        for anchor in anchors:
            # Recalculer span relatif au chunk
            relative_start = max(0, anchor.char_start - chunk_start)
            relative_end = anchor.char_end - chunk_start

            # Payload minimal (Invariant d'Architecture ADR)
            anchored_concepts.append({
                "concept_id": anchor.concept_id,
                "label": concept_labels.get(anchor.concept_id, ""),
                "role": anchor.role.value if hasattr(anchor.role, 'value') else str(anchor.role),
                "span": [relative_start, relative_end]
            })

        return anchored_concepts

    # =========================================================================
    # V2.1: Segment Mapping Methods
    # =========================================================================

    def _segment_range(self, seg: Dict[str, Any]) -> Tuple[int, int]:
        """
        Calcule les bornes caracteres d'un segment.

        Args:
            seg: Segment avec {segment_id, text, section_id, char_offset}

        Returns:
            Tuple (seg_start, seg_end) positions caracteres
        """
        seg_start = int(seg.get("char_offset", 0))
        seg_text = seg.get("text", "") or ""
        seg_end = seg_start + len(seg_text)
        return seg_start, seg_end

    def _overlap_len(
        self,
        a_start: int,
        a_end: int,
        b_start: int,
        b_end: int
    ) -> int:
        """
        Calcule la longueur d'overlap entre deux intervalles.

        Args:
            a_start, a_end: Bornes premier intervalle
            b_start, b_end: Bornes second intervalle

        Returns:
            Nombre de caracteres en commun (>= 0)
        """
        return max(0, min(a_end, b_end) - max(a_start, b_start))

    def _map_chunks_to_segments(
        self,
        raw_chunks: List[Dict[str, Any]],
        segments: List[Dict[str, Any]],
        overlap_min_chars: int = 1
    ) -> None:
        """
        Mappe chaque chunk vers le segment avec overlap maximal.

        Modifie raw_chunks in-place en ajoutant:
        - segment_id: ID du segment mappe (ou None si orphelin)
        - segment_overlap_chars: Nombre de chars d'overlap

        Tie-breakers si overlap egaux:
        1. Centre du chunk le plus proche du centre du segment
        2. Segment avec l'index le plus bas (earliest)

        Args:
            raw_chunks: Liste des chunks (modifiee in-place)
            segments: Liste des segments avec char_offset et text
            overlap_min_chars: Overlap minimum pour etre considere mappe
        """
        for chunk in raw_chunks:
            c_start = chunk["char_start"]
            c_end = chunk["char_end"]
            c_center = (c_start + c_end) / 2.0

            best_seg_id = None
            best_overlap = 0
            best_center_dist = float("inf")
            best_seg_idx = float("inf")

            for seg_idx, seg in enumerate(segments):
                seg_start, seg_end = self._segment_range(seg)
                overlap = self._overlap_len(c_start, c_end, seg_start, seg_end)

                if overlap < overlap_min_chars:
                    continue

                seg_center = (seg_start + seg_end) / 2.0
                center_dist = abs(c_center - seg_center)

                # Tie-breaker logic: max overlap -> min center dist -> earliest
                is_better = False
                if overlap > best_overlap:
                    is_better = True
                elif overlap == best_overlap:
                    if center_dist < best_center_dist:
                        is_better = True
                    elif center_dist == best_center_dist and seg_idx < best_seg_idx:
                        is_better = True

                if is_better:
                    best_seg_id = seg.get("segment_id")
                    best_overlap = overlap
                    best_center_dist = center_dist
                    best_seg_idx = seg_idx

            # Mettre a jour le chunk in-place
            chunk["segment_id"] = best_seg_id
            chunk["segment_overlap_chars"] = best_overlap

    def _validate_segment_coverage(
        self,
        final_chunks: List[Dict[str, Any]],
        fail_fast: bool
    ) -> None:
        """
        Valide la couverture segment et log les metriques.

        Args:
            final_chunks: Liste des chunks avec segment_id
            fail_fast: Si True, raise ValueError si orphans detectes

        Raises:
            ValueError: Si fail_fast=True et chunks sans segment_id
        """
        if not final_chunks:
            return

        orphan_chunks = [c for c in final_chunks if not c.get("segment_id")]
        orphan_count = len(orphan_chunks)
        total_count = len(final_chunks)
        coverage = 1.0 - (orphan_count / total_count)

        if orphan_count > 0:
            # Log les premiers orphelins pour debug
            sample_orphans = orphan_chunks[:3]
            orphan_positions = [
                f"[{c['char_start']}-{c['char_end']}]"
                for c in sample_orphans
            ]

            if fail_fast:
                raise ValueError(
                    f"[HybridAnchorChunker] {orphan_count}/{total_count} chunks "
                    f"sans segment_id (fail_fast=True). Positions: {orphan_positions}"
                )
            else:
                logger.warning(
                    f"[HybridAnchorChunker] {orphan_count}/{total_count} chunks "
                    f"orphelins (coverage={coverage:.1%}). Positions: {orphan_positions}"
                )
        else:
            logger.debug(
                f"[HybridAnchorChunker] Segment coverage: 100% ({total_count} chunks)"
            )


# =============================================================================
# Factory Pattern
# =============================================================================

_chunker_instance: Optional[HybridAnchorChunker] = None


def get_hybrid_anchor_chunker(
    tenant_id: str = "default"
) -> HybridAnchorChunker:
    """
    Recupere l'instance singleton du chunker.

    Args:
        tenant_id: ID tenant

    Returns:
        HybridAnchorChunker instance
    """
    global _chunker_instance

    if _chunker_instance is None:
        _chunker_instance = HybridAnchorChunker(tenant_id=tenant_id)

    return _chunker_instance
