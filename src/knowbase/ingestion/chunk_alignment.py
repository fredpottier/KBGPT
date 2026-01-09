"""
Chunk Alignment - Relations ALIGNS_WITH entre Coverage et Retrieval chunks.

Crée les alignements entre CoverageChunks et RetrievalChunks basés
sur l'intersection de leurs positions (char_start, char_end).

Architecture Dual Chunking:
- CoverageChunks: Couverture 100%, pour preuves ANCHORED_IN
- RetrievalChunks: Layout-aware, pour retrieval Qdrant
- ALIGNS_WITH: Lien par intersection de positions

ADR: doc/ongoing/ADR_DUAL_CHUNKING_ARCHITECTURE.md

Usage:
    alignments = create_alignments(coverage_chunks, retrieval_chunks)
    # Retourne liste de relations ALIGNS_WITH à persister dans Neo4j

Author: OSMOSE Phase 2
Date: 2026-01
"""

import logging
from typing import List, Dict, Any, Optional
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class AlignmentRelation:
    """
    Relation ALIGNS_WITH entre un CoverageChunk et un RetrievalChunk.
    """
    coverage_chunk_id: str
    retrieval_chunk_id: str
    overlap_chars: int
    overlap_ratio: float  # Ratio par rapport au CoverageChunk

    def to_dict(self) -> Dict[str, Any]:
        """Convertit en dict pour persistance Neo4j."""
        return {
            "coverage_chunk_id": self.coverage_chunk_id,
            "retrieval_chunk_id": self.retrieval_chunk_id,
            "overlap_chars": self.overlap_chars,
            "overlap_ratio": self.overlap_ratio,
        }


def calculate_overlap(
    a_start: int,
    a_end: int,
    b_start: int,
    b_end: int
) -> int:
    """
    Calcule le nombre de caractères en commun entre deux intervals.

    Args:
        a_start, a_end: Bornes du premier interval
        b_start, b_end: Bornes du second interval

    Returns:
        Nombre de caractères en intersection (≥0)
    """
    return max(0, min(a_end, b_end) - max(a_start, b_start))


def create_alignments(
    coverage_chunks: List[Dict[str, Any]],
    retrieval_chunks: List[Dict[str, Any]],
    min_overlap_chars: int = 0
) -> List[AlignmentRelation]:
    """
    Crée les relations ALIGNS_WITH entre Coverage et Retrieval chunks.

    Pour chaque CoverageChunk, trouve tous les RetrievalChunks qui
    ont une intersection de positions non-nulle.

    Args:
        coverage_chunks: Liste de CoverageChunks (dicts avec chunk_id, char_start, char_end)
        retrieval_chunks: Liste de RetrievalChunks (dicts avec chunk_id, char_start, char_end)
        min_overlap_chars: Overlap minimum pour créer une relation (défaut: 0 = tout overlap)

    Returns:
        Liste de AlignmentRelation
    """
    alignments = []

    for coverage in coverage_chunks:
        coverage_id = coverage.get("chunk_id")
        coverage_start = coverage.get("char_start", 0)
        coverage_end = coverage.get("char_end", 0)
        coverage_length = coverage_end - coverage_start

        if coverage_length <= 0:
            continue

        for retrieval in retrieval_chunks:
            retrieval_id = retrieval.get("chunk_id") or retrieval.get("id")
            retrieval_start = retrieval.get("char_start", 0)
            retrieval_end = retrieval.get("char_end", 0)

            overlap = calculate_overlap(
                coverage_start, coverage_end,
                retrieval_start, retrieval_end
            )

            if overlap > min_overlap_chars:
                overlap_ratio = overlap / coverage_length

                alignment = AlignmentRelation(
                    coverage_chunk_id=coverage_id,
                    retrieval_chunk_id=retrieval_id,
                    overlap_chars=overlap,
                    overlap_ratio=overlap_ratio
                )
                alignments.append(alignment)

    logger.info(
        f"[ChunkAlignment] Created {len(alignments)} ALIGNS_WITH relations "
        f"({len(coverage_chunks)} coverage x {len(retrieval_chunks)} retrieval)"
    )

    return alignments


def create_alignments_optimized(
    coverage_chunks: List[Dict[str, Any]],
    retrieval_chunks: List[Dict[str, Any]],
    min_overlap_chars: int = 0
) -> List[AlignmentRelation]:
    """
    Version optimisée de create_alignments pour grands documents.

    Utilise un tri préalable pour éviter les comparaisons inutiles.
    Complexité: O(n log n + m log m + k) au lieu de O(n * m)
    où k est le nombre d'alignements réels.

    Args:
        coverage_chunks: Liste de CoverageChunks triés par char_start
        retrieval_chunks: Liste de RetrievalChunks triés par char_start
        min_overlap_chars: Overlap minimum pour créer une relation

    Returns:
        Liste de AlignmentRelation
    """
    if not coverage_chunks or not retrieval_chunks:
        return []

    # Trier les chunks par position de début
    sorted_coverage = sorted(coverage_chunks, key=lambda c: c.get("char_start", 0))
    sorted_retrieval = sorted(retrieval_chunks, key=lambda c: c.get("char_start", 0))

    alignments = []
    retrieval_idx = 0

    for coverage in sorted_coverage:
        coverage_id = coverage.get("chunk_id")
        coverage_start = coverage.get("char_start", 0)
        coverage_end = coverage.get("char_end", 0)
        coverage_length = coverage_end - coverage_start

        if coverage_length <= 0:
            continue

        # Avancer retrieval_idx jusqu'au premier retrieval qui pourrait chevaucher
        while (retrieval_idx < len(sorted_retrieval) and
               sorted_retrieval[retrieval_idx].get("char_end", 0) <= coverage_start):
            retrieval_idx += 1

        # Scanner les retrieval chunks qui peuvent chevaucher ce coverage
        j = retrieval_idx
        while j < len(sorted_retrieval):
            retrieval = sorted_retrieval[j]
            retrieval_start = retrieval.get("char_start", 0)
            retrieval_end = retrieval.get("char_end", 0)

            # Si retrieval commence après la fin de coverage, on peut arrêter
            if retrieval_start >= coverage_end:
                break

            overlap = calculate_overlap(
                coverage_start, coverage_end,
                retrieval_start, retrieval_end
            )

            if overlap > min_overlap_chars:
                retrieval_id = retrieval.get("chunk_id") or retrieval.get("id")
                overlap_ratio = overlap / coverage_length

                alignment = AlignmentRelation(
                    coverage_chunk_id=coverage_id,
                    retrieval_chunk_id=retrieval_id,
                    overlap_chars=overlap,
                    overlap_ratio=overlap_ratio
                )
                alignments.append(alignment)

            j += 1

    logger.info(
        f"[ChunkAlignment] Created {len(alignments)} ALIGNS_WITH relations (optimized)"
    )

    return alignments


def get_aligned_coverage_for_retrieval(
    retrieval_chunk_id: str,
    alignments: List[AlignmentRelation]
) -> List[str]:
    """
    Trouve tous les CoverageChunks alignés avec un RetrievalChunk donné.

    Args:
        retrieval_chunk_id: ID du RetrievalChunk
        alignments: Liste des alignements

    Returns:
        Liste des chunk_id des CoverageChunks alignés
    """
    return [
        a.coverage_chunk_id
        for a in alignments
        if a.retrieval_chunk_id == retrieval_chunk_id
    ]


def get_aligned_retrieval_for_coverage(
    coverage_chunk_id: str,
    alignments: List[AlignmentRelation]
) -> List[str]:
    """
    Trouve tous les RetrievalChunks alignés avec un CoverageChunk donné.

    Args:
        coverage_chunk_id: ID du CoverageChunk
        alignments: Liste des alignements

    Returns:
        Liste des chunk_id des RetrievalChunks alignés
    """
    return [
        a.retrieval_chunk_id
        for a in alignments
        if a.coverage_chunk_id == coverage_chunk_id
    ]


def build_alignment_index(
    alignments: List[AlignmentRelation]
) -> Dict[str, List[AlignmentRelation]]:
    """
    Construit un index des alignements par retrieval_chunk_id.

    Utile pour alimenter rapidement le payload anchored_concepts
    de chaque RetrievalChunk.

    Args:
        alignments: Liste des alignements

    Returns:
        Dict mapping retrieval_chunk_id -> liste d'alignements
    """
    index: Dict[str, List[AlignmentRelation]] = {}

    for alignment in alignments:
        key = alignment.retrieval_chunk_id
        if key not in index:
            index[key] = []
        index[key].append(alignment)

    return index


__all__ = [
    "AlignmentRelation",
    "calculate_overlap",
    "create_alignments",
    "create_alignments_optimized",
    "get_aligned_coverage_for_retrieval",
    "get_aligned_retrieval_for_coverage",
    "build_alignment_index",
]
