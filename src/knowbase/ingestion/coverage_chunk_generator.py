"""
Coverage Chunk Generator - Dual Chunking Architecture.

Génère des CoverageChunks pour couverture 100% du document.
Ces chunks servent UNIQUEMENT pour les relations ANCHORED_IN (preuve).
Ils ne sont PAS vectorisés dans Qdrant.

Architecture Dual Chunking:
- CoverageChunks: Couverture 100%, Neo4j only, pour preuves
- RetrievalChunks: Layout-aware, Neo4j + Qdrant, pour retrieval

ADR: doc/ongoing/ADR_DUAL_CHUNKING_ARCHITECTURE.md

Invariants:
- Couverture ≥95% du document
- Aucun gap >100 chars entre chunks
- Tout anchor SPAN doit trouver son CoverageChunk

Author: OSMOSE Phase 2
Date: 2026-01
"""

import logging
from typing import List, Dict, Any, Optional
from dataclasses import dataclass, field

import tiktoken

logger = logging.getLogger(__name__)


# Configuration CoverageChunks (ADR section 11.1)
COVERAGE_CHUNK_SIZE_TOKENS = 800
COVERAGE_OVERLAP_TOKENS = 0  # Pas d'overlap (ADR)
COVERAGE_CHARS_PER_TOKEN = 4  # Approximation standard


@dataclass
class CoverageChunk:
    """
    Un chunk de couverture pour ancrage des concepts.

    Ne contient PAS d'embedding - stocké uniquement dans Neo4j.
    """
    chunk_id: str
    document_id: str
    tenant_id: str
    chunk_type: str = "coverage"

    # Positions
    char_start: int = 0
    char_end: int = 0
    coverage_seq: int = 0

    # Contexte (optionnel, pour compatibilité)
    context_id: Optional[str] = None
    section_path: Optional[str] = None

    # Texte (pour debug/validation, pas stocké en production)
    text: str = ""
    token_count: int = 0

    def to_dict(self) -> Dict[str, Any]:
        """Convertit en dict pour persistance Neo4j."""
        return {
            "chunk_id": self.chunk_id,
            "document_id": self.document_id,
            "tenant_id": self.tenant_id,
            "chunk_type": self.chunk_type,
            "char_start": self.char_start,
            "char_end": self.char_end,
            "coverage_seq": self.coverage_seq,
            "context_id": self.context_id,
            "section_path": self.section_path,
            "token_count": self.token_count,
        }


class CoverageChunkGenerator:
    """
    Génère des CoverageChunks avec couverture 100% du document.

    Stratégie: Chunking linéaire simple sans filtrage.
    - Pas de layout-aware (contrairement aux RetrievalChunks)
    - Pas de min_tokens filter
    - Overlap nul pour éviter doublons de preuve

    Usage:
        generator = CoverageChunkGenerator()
        chunks = generator.generate(text_content, document_id, tenant_id)
    """

    def __init__(
        self,
        chunk_size_tokens: int = COVERAGE_CHUNK_SIZE_TOKENS,
        overlap_tokens: int = COVERAGE_OVERLAP_TOKENS,
        chars_per_token: int = COVERAGE_CHARS_PER_TOKEN
    ):
        """
        Initialise le générateur.

        Args:
            chunk_size_tokens: Taille cible en tokens (défaut: 800)
            overlap_tokens: Overlap entre chunks (défaut: 0)
            chars_per_token: Ratio chars/token pour approximation (défaut: 4)
        """
        self.chunk_size_tokens = chunk_size_tokens
        self.overlap_tokens = overlap_tokens
        self.chars_per_token = chars_per_token

        # Taille en caractères
        self.chunk_size_chars = chunk_size_tokens * chars_per_token
        self.overlap_chars = overlap_tokens * chars_per_token

        # Tokenizer optionnel pour comptage précis
        try:
            self.tokenizer = tiktoken.get_encoding("cl100k_base")
        except Exception:
            self.tokenizer = None

        logger.info(
            f"[CoverageChunkGenerator] Initialized "
            f"(size={chunk_size_tokens} tokens, overlap={overlap_tokens}, "
            f"~{self.chunk_size_chars} chars/chunk)"
        )

    def generate(
        self,
        text_content: str,
        document_id: str,
        tenant_id: str = "default"
    ) -> List[CoverageChunk]:
        """
        Génère les CoverageChunks pour un document.

        Garantit une couverture 100% du texte sans gaps.

        Args:
            text_content: Texte complet du document
            document_id: ID du document
            tenant_id: ID du tenant

        Returns:
            Liste de CoverageChunks couvrant tout le document
        """
        if not text_content:
            logger.warning(
                f"[CoverageChunkGenerator] Empty text for document {document_id}"
            )
            return []

        chunks = []
        seq = 0
        text_length = len(text_content)

        # Stride = taille - overlap
        stride = max(1, self.chunk_size_chars - self.overlap_chars)

        start = 0
        while start < text_length:
            # Calculer la fin du chunk
            end = min(start + self.chunk_size_chars, text_length)

            # Extraire le texte du chunk
            chunk_text = text_content[start:end]

            # Compter les tokens (approximatif si pas de tokenizer)
            if self.tokenizer:
                token_count = len(self.tokenizer.encode(chunk_text))
            else:
                token_count = len(chunk_text) // self.chars_per_token

            # Créer le chunk
            chunk = CoverageChunk(
                chunk_id=f"{document_id}::coverage::{seq}",
                document_id=document_id,
                tenant_id=tenant_id,
                chunk_type="coverage",
                char_start=start,
                char_end=end,
                coverage_seq=seq,
                text=chunk_text,  # Pour debug
                token_count=token_count
            )
            chunks.append(chunk)

            # Avancer
            seq += 1
            start += stride

        # Validation de couverture
        self._validate_coverage(chunks, text_length, document_id)

        logger.info(
            f"[CoverageChunkGenerator] Generated {len(chunks)} coverage chunks "
            f"for document {document_id} ({text_length} chars)"
        )

        return chunks

    def _validate_coverage(
        self,
        chunks: List[CoverageChunk],
        text_length: int,
        document_id: str
    ) -> None:
        """
        Valide que les chunks couvrent bien tout le document.

        Vérifie:
        - Premier chunk commence à 0
        - Dernier chunk finit à text_length
        - Pas de gap significatif entre chunks

        Raises:
            ValueError si la couverture est incomplète
        """
        if not chunks:
            if text_length > 0:
                raise ValueError(
                    f"No coverage chunks generated for non-empty document {document_id}"
                )
            return

        # Premier chunk doit commencer à 0
        if chunks[0].char_start != 0:
            raise ValueError(
                f"First coverage chunk doesn't start at 0 "
                f"(starts at {chunks[0].char_start})"
            )

        # Dernier chunk doit finir à text_length
        if chunks[-1].char_end != text_length:
            raise ValueError(
                f"Last coverage chunk doesn't reach end "
                f"(ends at {chunks[-1].char_end}, text_length={text_length})"
            )

        # Vérifier les gaps entre chunks consécutifs
        for i in range(1, len(chunks)):
            prev_end = chunks[i - 1].char_end
            curr_start = chunks[i].char_start

            gap = curr_start - prev_end
            if gap > 100:  # Seuil ADR
                logger.warning(
                    f"[CoverageChunkGenerator] Gap detected: "
                    f"[{prev_end} - {curr_start}] = {gap} chars"
                )
                # Non-bloquant pour l'instant, mais loggé

        # Calculer le ratio de couverture
        total_covered = sum(c.char_end - c.char_start for c in chunks)
        # Avec overlap=0, devrait être ~100%
        coverage_ratio = total_covered / text_length if text_length > 0 else 0

        if coverage_ratio < 0.95:
            raise ValueError(
                f"Coverage ratio {coverage_ratio:.1%} < 95% threshold "
                f"for document {document_id}"
            )

        logger.debug(
            f"[CoverageChunkGenerator] Coverage validation passed: "
            f"{coverage_ratio:.1%} ({len(chunks)} chunks)"
        )


def generate_coverage_chunks(
    text_content: str,
    document_id: str,
    tenant_id: str = "default"
) -> List[Dict[str, Any]]:
    """
    Fonction utilitaire pour générer des CoverageChunks.

    Wrapper simple autour de CoverageChunkGenerator.

    Args:
        text_content: Texte complet du document
        document_id: ID du document
        tenant_id: ID du tenant

    Returns:
        Liste de dicts représentant les CoverageChunks
    """
    generator = CoverageChunkGenerator()
    chunks = generator.generate(text_content, document_id, tenant_id)
    return [chunk.to_dict() for chunk in chunks]


__all__ = [
    "CoverageChunk",
    "CoverageChunkGenerator",
    "generate_coverage_chunks",
    "COVERAGE_CHUNK_SIZE_TOKENS",
    "COVERAGE_OVERLAP_TOKENS",
]
