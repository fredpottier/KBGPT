"""
Text Chunker - Phase 1.6 Cross-Référence Neo4j-Qdrant

Découpe documents en chunks avec embeddings pour recherche vectorielle.
Associe chunks aux concepts Proto-KG pour navigation bidirectionnelle.

Architecture:
    Document text → Chunks (512 tokens, overlap 128)
                  → Embeddings (multilingual-e5-large, 1024D)
                  → Proto-concept attribution (mention detection)
                  → Qdrant payload (chunk ↔ concepts)

Author: OSMOSE Phase 1.6
Date: 2025-10-17
"""

import re
import uuid
import logging
from typing import List, Dict, Any, Optional
from sentence_transformers import SentenceTransformer
import tiktoken

logger = logging.getLogger(__name__)


class TextChunker:
    """
    Découpe texte en chunks avec embeddings et attribution concepts.

    Fonctionnalités:
    - Chunking intelligent (512 tokens, overlap 128, respect phrase boundaries)
    - Embeddings multilingues (multilingual-e5-large, 1024D)
    - Attribution concepts (détection mention dans chunk)
    - Format output Qdrant-compatible
    """

    def __init__(
        self,
        model_name: str = "intfloat/multilingual-e5-large",
        chunk_size: int = 512,
        overlap: int = 128,
        encoding_name: str = "cl100k_base"
    ):
        """
        Initialize TextChunker.

        Args:
            model_name: Sentence transformer model (default: multilingual-e5-large)
            chunk_size: Max tokens per chunk (default: 512)
            overlap: Overlap between chunks in tokens (default: 128)
            encoding_name: Tiktoken encoding (default: cl100k_base)
        """
        self.chunk_size = chunk_size
        self.overlap = overlap

        # Init sentence transformer pour embeddings
        try:
            self.model = SentenceTransformer(model_name)
            logger.info(f"[TextChunker] Loaded model: {model_name} (dim={self.model.get_sentence_embedding_dimension()})")
        except Exception as e:
            logger.error(f"[TextChunker] Failed to load model {model_name}: {e}")
            raise

        # Init tokenizer pour découpage précis
        try:
            self.tokenizer = tiktoken.get_encoding(encoding_name)
            logger.info(f"[TextChunker] Loaded tokenizer: {encoding_name}")
        except Exception as e:
            logger.warning(f"[TextChunker] Failed to load tokenizer {encoding_name}: {e}, using char-based fallback")
            self.tokenizer = None

    def chunk_document(
        self,
        text: str,
        document_id: str,
        document_name: str,
        segment_id: str,
        concepts: List[Dict[str, Any]],
        tenant_id: str = "default",
        use_hybrid: bool = True
    ) -> List[Dict[str, Any]]:
        """
        Découpe document en chunks avec stratégie HYBRIDE.

        Stratégie Hybride (use_hybrid=True):
        1. Chunks génériques: Coverage complète (512 tokens, overlap 128)
        2. Chunks concept-focused: Contexte autour de chaque mention concept (±256 tokens)

        Args:
            text: Texte complet du document/segment
            document_id: ID unique document
            document_name: Nom fichier document
            segment_id: ID segment (pour lien avec Proto-KG)
            concepts: Liste concepts extraits par Extractor
                      Format: [{"id": "proto-123", "name": "SAP S/4HANA", ...}]
            tenant_id: ID tenant (multi-tenant isolation)
            use_hybrid: Si True, génère chunks génériques + concept-focused (default: True)

        Returns:
            List of chunks ready for Qdrant:
            [
                {
                    "id": "chunk-uuid",
                    "text": "SAP S/4HANA est une suite...",
                    "embedding": [0.123, 0.456, ...],  # 1024D
                    "document_id": "doc-123",
                    "document_name": "SAP Overview.pdf",
                    "segment_id": "segment-1",
                    "chunk_index": 0,
                    "chunk_type": "generic" | "concept_focused",  # Type chunk
                    "primary_concept_id": "proto-123" | None,  # Concept principal si focused
                    "proto_concept_ids": ["proto-123", "proto-124"],
                    "canonical_concept_ids": [],  # Vide initialement
                    "tenant_id": "default",
                    "char_start": 0,
                    "char_end": 512
                }
            ]
        """
        if not text or not text.strip():
            logger.warning(f"[TextChunker] Empty text for document {document_id}")
            return []

        try:
            all_chunks = []

            # ===== PARTIE 1: Chunks Génériques (Coverage Complète) =====
            generic_chunks = self._split_text_into_chunks(text)
            logger.debug(
                f"[TextChunker:Generic] Created {len(generic_chunks)} generic chunks "
                f"for document {document_id}"
            )

            # Générer embeddings pour chunks génériques
            generic_texts = [chunk["text"] for chunk in generic_chunks]
            generic_embeddings = self._generate_embeddings_batch(generic_texts)

            # Créer chunks génériques avec attribution concepts
            for i, (chunk_data, embedding) in enumerate(zip(generic_chunks, generic_embeddings)):
                chunk_text = chunk_data["text"]
                mentioned_concept_ids = self._find_mentioned_concepts(chunk_text, concepts)

                all_chunks.append({
                    "id": str(uuid.uuid4()),
                    "text": chunk_text,
                    "embedding": embedding.tolist(),
                    "document_id": document_id,
                    "document_name": document_name,
                    "segment_id": segment_id,
                    "chunk_index": i,
                    "chunk_type": "generic",  # Type: generic
                    "primary_concept_id": None,  # Pas de concept principal
                    "proto_concept_ids": mentioned_concept_ids,
                    "canonical_concept_ids": [],
                    "tenant_id": tenant_id,
                    "char_start": chunk_data["char_start"],
                    "char_end": chunk_data["char_end"]
                })

            # ===== PARTIE 2: Chunks Concept-Focused (Si Hybride Activé) =====
            if use_hybrid and concepts:
                concept_focused_chunks = self._create_concept_focused_chunks(
                    text=text,
                    document_id=document_id,
                    document_name=document_name,
                    segment_id=segment_id,
                    concepts=concepts,
                    tenant_id=tenant_id,
                    start_index=len(all_chunks)  # Continuer numérotation après generics
                )

                all_chunks.extend(concept_focused_chunks)

                logger.info(
                    f"[TextChunker:Hybrid] Generated {len(generic_chunks)} generic + "
                    f"{len(concept_focused_chunks)} concept-focused chunks "
                    f"({len(all_chunks)} total)"
                )
            else:
                logger.info(
                    f"[TextChunker:Generic] Generated {len(all_chunks)} generic chunks "
                    f"(hybrid disabled or no concepts)"
                )

            return all_chunks

        except Exception as e:
            logger.error(f"[TextChunker] Error chunking document {document_id}: {e}", exc_info=True)
            return []

    def _split_text_into_chunks(self, text: str) -> List[Dict[str, Any]]:
        """
        Découpe texte en chunks avec overlap.

        Stratégie:
        1. Split par tokens (512 tokens/chunk)
        2. Overlap 128 tokens entre chunks
        3. Respect des limites de phrases si possible

        Returns:
            [{"text": "...", "char_start": 0, "char_end": 512}, ...]
        """
        chunks = []

        if self.tokenizer:
            # Token-based splitting (plus précis)
            tokens = self.tokenizer.encode(text)

            start_idx = 0
            while start_idx < len(tokens):
                # Extract chunk tokens
                end_idx = min(start_idx + self.chunk_size, len(tokens))
                chunk_tokens = tokens[start_idx:end_idx]

                # Decode chunk text
                chunk_text = self.tokenizer.decode(chunk_tokens)

                # Trouver position dans texte original (approximation)
                char_start = max(0, len(self.tokenizer.decode(tokens[:start_idx])))
                char_end = min(len(text), len(self.tokenizer.decode(tokens[:end_idx])))

                chunks.append({
                    "text": chunk_text.strip(),
                    "char_start": char_start,
                    "char_end": char_end
                })

                # Move start with overlap
                start_idx += (self.chunk_size - self.overlap)
        else:
            # Fallback: char-based splitting (moins précis mais fonctionne toujours)
            # Approximation: 1 token ≈ 4 chars
            chunk_size_chars = self.chunk_size * 4
            overlap_chars = self.overlap * 4

            start_idx = 0
            while start_idx < len(text):
                end_idx = min(start_idx + chunk_size_chars, len(text))

                # Essayer de couper à une limite de phrase
                chunk_text = text[start_idx:end_idx]
                if end_idx < len(text):
                    # Chercher dernier point/ligne
                    last_sentence_end = max(
                        chunk_text.rfind('. '),
                        chunk_text.rfind('.\n'),
                        chunk_text.rfind('! '),
                        chunk_text.rfind('? ')
                    )
                    if last_sentence_end > len(chunk_text) // 2:  # Si au moins 50% du chunk
                        end_idx = start_idx + last_sentence_end + 1
                        chunk_text = text[start_idx:end_idx]

                chunks.append({
                    "text": chunk_text.strip(),
                    "char_start": start_idx,
                    "char_end": end_idx
                })

                start_idx += (chunk_size_chars - overlap_chars)

        return chunks

    def _generate_embeddings_batch(self, texts: List[str]) -> List[Any]:
        """
        Générer embeddings pour batch de textes (plus efficace).

        Args:
            texts: Liste de textes à embedder

        Returns:
            Liste embeddings (numpy arrays 1024D)
        """
        try:
            embeddings = self.model.encode(
                texts,
                batch_size=32,
                show_progress_bar=False,
                convert_to_numpy=True
            )
            return embeddings
        except Exception as e:
            logger.error(f"[TextChunker] Error generating embeddings: {e}")
            # Fallback: embeddings vides
            import numpy as np
            return [np.zeros(1024) for _ in texts]

    def _find_mentioned_concepts(
        self,
        chunk_text: str,
        concepts: List[Dict[str, Any]]
    ) -> List[str]:
        """
        Trouver concepts mentionnés dans chunk (détection simple).

        Stratégie:
        - Recherche exacte (case-insensitive)
        - Support variantes (avec/sans tirets, espaces)

        Args:
            chunk_text: Texte du chunk
            concepts: Liste concepts avec proto_concept_id Neo4j [{"proto_concept_id": "uuid", "name": "SAP"}]

        Returns:
            Liste proto_concept_ids Neo4j mentionnés: ["uuid-1", "uuid-2"]
        """
        mentioned_ids = []
        chunk_lower = chunk_text.lower()

        for concept in concepts:
            concept_name = concept.get("name", "").lower()
            proto_concept_id = concept.get("proto_concept_id")  # ID Neo4j (UUID)

            if not concept_name or not proto_concept_id:
                continue

            # Recherche exacte
            if concept_name in chunk_lower:
                mentioned_ids.append(proto_concept_id)
                continue

            # Recherche variantes (avec/sans tirets, espaces)
            # Ex: "S/4HANA" vs "S4HANA" vs "S 4 HANA"
            concept_normalized = re.sub(r'[/\-\s]+', '', concept_name)
            chunk_normalized = re.sub(r'[/\-\s]+', '', chunk_lower)

            if concept_normalized in chunk_normalized:
                mentioned_ids.append(proto_concept_id)

        return mentioned_ids

    def _create_concept_focused_chunks(
        self,
        text: str,
        document_id: str,
        document_name: str,
        segment_id: str,
        concepts: List[Dict[str, Any]],
        tenant_id: str,
        start_index: int
    ) -> List[Dict[str, Any]]:
        """
        Créer chunks concept-focused (contexte autour de mentions).

        Stratégie:
        1. Pour chaque concept, trouver toutes ses mentions dans le texte
        2. Extraire contexte autour de chaque mention (±256 tokens)
        3. Générer embeddings pour chunks focused
        4. Retourner chunks avec chunk_type="concept_focused" et primary_concept_id set

        Args:
            text: Texte complet du document
            document_id: ID document
            document_name: Nom document
            segment_id: ID segment
            concepts: Liste concepts extraits
            tenant_id: ID tenant
            start_index: Index de départ pour numérotation chunks

        Returns:
            Liste chunks concept-focused
        """
        concept_focused_chunks = []
        chunk_index = start_index

        for concept in concepts:
            proto_concept_id = concept.get("proto_concept_id")  # ID Neo4j
            concept_name = concept.get("name", "")

            if not concept_name or not proto_concept_id:
                continue

            # Trouver toutes les mentions du concept dans le texte
            mentions = self._find_concept_mentions(text, concept_name)

            if not mentions:
                continue

            # Pour chaque mention, créer un chunk focused
            for mention_start, mention_end in mentions:
                # Extraire contexte autour de la mention (±256 tokens)
                chunk_text, char_start, char_end = self._extract_context_window(
                    text=text,
                    mention_start=mention_start,
                    mention_end=mention_end,
                    context_tokens=256
                )

                if not chunk_text or not chunk_text.strip():
                    continue

                # Générer embedding pour ce chunk focused
                embedding = self._generate_embeddings_batch([chunk_text])[0]

                # Trouver tous les concepts mentionnés dans ce chunk (pas seulement le principal)
                mentioned_concept_ids = self._find_mentioned_concepts(chunk_text, concepts)

                # Créer chunk concept-focused
                concept_focused_chunks.append({
                    "id": str(uuid.uuid4()),
                    "text": chunk_text.strip(),
                    "embedding": embedding.tolist(),
                    "document_id": document_id,
                    "document_name": document_name,
                    "segment_id": segment_id,
                    "chunk_index": chunk_index,
                    "chunk_type": "concept_focused",  # Type: concept_focused
                    "primary_concept_id": proto_concept_id,  # Concept principal (Proto ID Neo4j)
                    "proto_concept_ids": mentioned_concept_ids,  # Tous les concepts mentionnés (Proto IDs Neo4j)
                    "canonical_concept_ids": [],
                    "tenant_id": tenant_id,
                    "char_start": char_start,
                    "char_end": char_end
                })

                chunk_index += 1

        logger.debug(
            f"[TextChunker:ConceptFocused] Created {len(concept_focused_chunks)} "
            f"concept-focused chunks for {len(concepts)} concepts"
        )

        return concept_focused_chunks

    def _find_concept_mentions(
        self,
        text: str,
        concept_name: str
    ) -> List[tuple]:
        """
        Trouver toutes les positions des mentions d'un concept dans le texte.

        Stratégie:
        - Recherche case-insensitive
        - Support variantes (avec/sans tirets, espaces)
        - Retourne positions (char_start, char_end)

        Args:
            text: Texte complet
            concept_name: Nom du concept

        Returns:
            Liste de tuples (char_start, char_end) pour chaque mention
        """
        mentions = []
        text_lower = text.lower()
        concept_lower = concept_name.lower()

        # Recherche exacte (case-insensitive)
        start_pos = 0
        while True:
            pos = text_lower.find(concept_lower, start_pos)
            if pos == -1:
                break
            mentions.append((pos, pos + len(concept_lower)))
            start_pos = pos + 1

        # Si aucune mention exacte, chercher variantes normalisées
        if not mentions:
            # Normaliser concept (supprimer tirets/espaces/slashes)
            concept_normalized = re.sub(r'[/\-\s]+', '', concept_lower)

            # Créer pattern pour matcher variantes
            # Ex: "S/4HANA" → pattern qui match "S4HANA", "S 4 HANA", etc.
            pattern_parts = []
            for char in concept_normalized:
                if char.isalnum():
                    pattern_parts.append(char)
                    pattern_parts.append(r'[/\-\s]*')  # Caractères optionnels entre chaque lettre/chiffre

            if pattern_parts:
                # Retirer dernier séparateur optionnel
                pattern_parts = pattern_parts[:-1]
                pattern = ''.join(pattern_parts)

                try:
                    for match in re.finditer(pattern, text_lower, re.IGNORECASE):
                        mentions.append((match.start(), match.end()))
                except re.error:
                    # Si pattern invalide, ignorer
                    pass

        return mentions

    def _extract_context_window(
        self,
        text: str,
        mention_start: int,
        mention_end: int,
        context_tokens: int = 256
    ) -> tuple:
        """
        Extraire fenêtre de contexte autour d'une mention.

        Stratégie:
        - Centrer sur la mention
        - Étendre de ±context_tokens (ou chars si tokenizer indisponible)
        - Respecter limites de phrases si possible

        Args:
            text: Texte complet
            mention_start: Position début mention (chars)
            mention_end: Position fin mention (chars)
            context_tokens: Nombre tokens de contexte de chaque côté (default: 256)

        Returns:
            (chunk_text, char_start, char_end)
        """
        if self.tokenizer:
            # Token-based context extraction (plus précis)
            # Encoder texte complet pour connaître positions tokens
            tokens = self.tokenizer.encode(text)

            # Approximer position token de la mention
            # (simple approximation: compter tokens avant mention_start)
            text_before = text[:mention_start]
            tokens_before = self.tokenizer.encode(text_before)
            mention_token_start = len(tokens_before)

            # Calculer fenêtre token
            window_start_token = max(0, mention_token_start - context_tokens)
            window_end_token = min(len(tokens), mention_token_start + context_tokens)

            # Extraire tokens de la fenêtre
            window_tokens = tokens[window_start_token:window_end_token]

            # Décoder chunk
            chunk_text = self.tokenizer.decode(window_tokens)

            # Approximer positions char (pas parfait mais suffisant)
            char_start = max(0, len(self.tokenizer.decode(tokens[:window_start_token])))
            char_end = min(len(text), len(self.tokenizer.decode(tokens[:window_end_token])))

        else:
            # Fallback: char-based context extraction
            # Approximation: 1 token ≈ 4 chars
            context_chars = context_tokens * 4

            char_start = max(0, mention_start - context_chars)
            char_end = min(len(text), mention_end + context_chars)

            chunk_text = text[char_start:char_end]

        # Essayer de couper aux limites de phrases
        if char_start > 0:
            # Chercher début de phrase avant
            sentence_starts = [
                chunk_text.find('. ') + 2,
                chunk_text.find('.\n') + 2,
                chunk_text.find('! ') + 2,
                chunk_text.find('? ') + 2
            ]
            valid_starts = [s for s in sentence_starts if s > 1]
            if valid_starts:
                first_sentence = min(valid_starts)
                chunk_text = chunk_text[first_sentence:]
                char_start += first_sentence

        if char_end < len(text):
            # Chercher fin de phrase après
            sentence_ends = [
                chunk_text.rfind('. ') + 1,
                chunk_text.rfind('.\n') + 1,
                chunk_text.rfind('! ') + 1,
                chunk_text.rfind('? ') + 1
            ]
            valid_ends = [e for e in sentence_ends if e > 0]
            if valid_ends:
                last_sentence = max(valid_ends)
                chunk_text = chunk_text[:last_sentence]
                char_end = char_start + last_sentence

        return (chunk_text, char_start, char_end)


# Singleton instance pour réutilisation (model loading coûteux)
_text_chunker_instance: Optional[TextChunker] = None


def get_text_chunker(
    model_name: str = "intfloat/multilingual-e5-large",
    chunk_size: int = 512,
    overlap: int = 128
) -> TextChunker:
    """
    Get singleton TextChunker instance.

    Args:
        model_name: Sentence transformer model
        chunk_size: Max tokens per chunk
        overlap: Overlap between chunks

    Returns:
        TextChunker instance
    """
    global _text_chunker_instance

    if _text_chunker_instance is None:
        _text_chunker_instance = TextChunker(
            model_name=model_name,
            chunk_size=chunk_size,
            overlap=overlap
        )
        logger.info("[TextChunker] Singleton instance created")

    return _text_chunker_instance
