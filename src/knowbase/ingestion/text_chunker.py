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
        tenant_id: str = "default"
    ) -> List[Dict[str, Any]]:
        """
        Découpe document en chunks avec embeddings et attribution concepts.

        Args:
            text: Texte complet du document/segment
            document_id: ID unique document
            document_name: Nom fichier document
            segment_id: ID segment (pour lien avec Proto-KG)
            concepts: Liste concepts extraits par Extractor
                      Format: [{"id": "proto-123", "name": "SAP S/4HANA", ...}]
            tenant_id: ID tenant (multi-tenant isolation)

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
                    "proto_concept_ids": ["proto-123", "proto-124"],
                    "canonical_concept_ids": [],  # Vide initialement, rempli après promotion
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
            # 1. Découper texte en chunks
            text_chunks = self._split_text_into_chunks(text)
            logger.debug(f"[TextChunker] Created {len(text_chunks)} chunks for document {document_id}")

            # 2. Générer embeddings batch (plus efficace)
            chunk_texts = [chunk["text"] for chunk in text_chunks]
            embeddings = self._generate_embeddings_batch(chunk_texts)

            # 3. Attribution concepts (détection mentions)
            chunks_with_concepts = []
            for i, (chunk_data, embedding) in enumerate(zip(text_chunks, embeddings)):
                chunk_text = chunk_data["text"]

                # Trouver concepts mentionnés dans ce chunk
                mentioned_concept_ids = self._find_mentioned_concepts(chunk_text, concepts)

                chunk_id = str(uuid.uuid4())

                chunks_with_concepts.append({
                    "id": chunk_id,
                    "text": chunk_text,
                    "embedding": embedding.tolist(),  # Convertir numpy array → list
                    "document_id": document_id,
                    "document_name": document_name,
                    "segment_id": segment_id,
                    "chunk_index": i,
                    "proto_concept_ids": mentioned_concept_ids,
                    "canonical_concept_ids": [],  # Rempli après promotion par Gatekeeper
                    "tenant_id": tenant_id,
                    "char_start": chunk_data["char_start"],
                    "char_end": chunk_data["char_end"]
                })

            logger.info(
                f"[TextChunker] Generated {len(chunks_with_concepts)} chunks "
                f"({sum(len(c['proto_concept_ids']) for c in chunks_with_concepts)} concept mentions)"
            )

            return chunks_with_concepts

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
            concepts: Liste concepts [{"id": "proto-123", "name": "SAP S/4HANA"}]

        Returns:
            Liste concept IDs mentionnés: ["proto-123", "proto-124"]
        """
        mentioned_ids = []
        chunk_lower = chunk_text.lower()

        for concept in concepts:
            concept_name = concept.get("name", "").lower()
            if not concept_name:
                continue

            # Recherche exacte
            if concept_name in chunk_lower:
                mentioned_ids.append(concept["id"])
                continue

            # Recherche variantes (avec/sans tirets, espaces)
            # Ex: "S/4HANA" vs "S4HANA" vs "S 4 HANA"
            concept_normalized = re.sub(r'[/\-\s]+', '', concept_name)
            chunk_normalized = re.sub(r'[/\-\s]+', '', chunk_lower)

            if concept_normalized in chunk_normalized:
                mentioned_ids.append(concept["id"])

        return mentioned_ids


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
