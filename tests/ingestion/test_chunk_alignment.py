"""
Tests pour le module chunk_alignment.

Vérifie que les alignements ALIGNS_WITH sont correctement créés
entre CoverageChunks et RetrievalChunks.
"""

import pytest
from knowbase.ingestion.chunk_alignment import (
    AlignmentRelation,
    calculate_overlap,
    create_alignments,
    create_alignments_optimized,
    get_aligned_coverage_for_retrieval,
    get_aligned_retrieval_for_coverage,
    build_alignment_index,
)


class TestCalculateOverlap:
    """Tests pour calculate_overlap()."""

    def test_no_overlap(self):
        """Pas d'intersection."""
        assert calculate_overlap(0, 100, 200, 300) == 0
        assert calculate_overlap(200, 300, 0, 100) == 0

    def test_full_overlap(self):
        """Un interval contient l'autre."""
        assert calculate_overlap(0, 100, 25, 75) == 50
        assert calculate_overlap(25, 75, 0, 100) == 50

    def test_partial_overlap(self):
        """Chevauchement partiel."""
        assert calculate_overlap(0, 100, 50, 150) == 50
        assert calculate_overlap(50, 150, 0, 100) == 50

    def test_adjacent(self):
        """Intervals adjacents (pas d'overlap)."""
        assert calculate_overlap(0, 100, 100, 200) == 0

    def test_same_interval(self):
        """Même interval."""
        assert calculate_overlap(50, 150, 50, 150) == 100


class TestCreateAlignments:
    """Tests pour create_alignments()."""

    def test_basic_alignment(self):
        """Crée des alignements basiques."""
        coverage = [
            {"chunk_id": "c1", "char_start": 0, "char_end": 100},
            {"chunk_id": "c2", "char_start": 100, "char_end": 200},
        ]
        retrieval = [
            {"chunk_id": "r1", "char_start": 0, "char_end": 150},
        ]

        alignments = create_alignments(coverage, retrieval)

        # r1 chevauche c1 (100 chars) et c2 (50 chars)
        assert len(alignments) == 2

        # Vérifier c1 <-> r1
        c1_align = [a for a in alignments if a.coverage_chunk_id == "c1"][0]
        assert c1_align.overlap_chars == 100
        assert c1_align.overlap_ratio == 1.0  # 100/100

        # Vérifier c2 <-> r1
        c2_align = [a for a in alignments if a.coverage_chunk_id == "c2"][0]
        assert c2_align.overlap_chars == 50
        assert c2_align.overlap_ratio == 0.5  # 50/100

    def test_no_alignments(self):
        """Pas d'alignements si pas d'overlap."""
        coverage = [
            {"chunk_id": "c1", "char_start": 0, "char_end": 100},
        ]
        retrieval = [
            {"chunk_id": "r1", "char_start": 200, "char_end": 300},
        ]

        alignments = create_alignments(coverage, retrieval)
        assert len(alignments) == 0

    def test_empty_inputs(self):
        """Gère les entrées vides."""
        assert create_alignments([], []) == []
        assert create_alignments([{"chunk_id": "c1", "char_start": 0, "char_end": 100}], []) == []
        assert create_alignments([], [{"chunk_id": "r1", "char_start": 0, "char_end": 100}]) == []

    def test_min_overlap_filter(self):
        """Filtre par overlap minimum."""
        coverage = [
            {"chunk_id": "c1", "char_start": 0, "char_end": 100},
        ]
        retrieval = [
            {"chunk_id": "r1", "char_start": 90, "char_end": 200},  # 10 chars overlap
        ]

        # Sans filtre
        alignments = create_alignments(coverage, retrieval, min_overlap_chars=0)
        assert len(alignments) == 1

        # Avec filtre 20 chars
        alignments = create_alignments(coverage, retrieval, min_overlap_chars=20)
        assert len(alignments) == 0

    def test_multiple_retrieval_per_coverage(self):
        """Un coverage peut aligner avec plusieurs retrieval."""
        coverage = [
            {"chunk_id": "c1", "char_start": 0, "char_end": 1000},
        ]
        retrieval = [
            {"chunk_id": "r1", "char_start": 0, "char_end": 300},
            {"chunk_id": "r2", "char_start": 250, "char_end": 550},
            {"chunk_id": "r3", "char_start": 500, "char_end": 800},
            {"chunk_id": "r4", "char_start": 750, "char_end": 1000},
        ]

        alignments = create_alignments(coverage, retrieval)

        # Tous les retrieval chevauchent le coverage
        assert len(alignments) == 4

    def test_alignment_relation_to_dict(self):
        """Vérifie la conversion en dict."""
        coverage = [{"chunk_id": "c1", "char_start": 0, "char_end": 100}]
        retrieval = [{"chunk_id": "r1", "char_start": 50, "char_end": 150}]

        alignments = create_alignments(coverage, retrieval)
        d = alignments[0].to_dict()

        assert d["coverage_chunk_id"] == "c1"
        assert d["retrieval_chunk_id"] == "r1"
        assert d["overlap_chars"] == 50
        assert d["overlap_ratio"] == 0.5


class TestCreateAlignmentsOptimized:
    """Tests pour create_alignments_optimized()."""

    def test_same_results_as_basic(self):
        """Même résultats que la version basique."""
        coverage = [
            {"chunk_id": "c1", "char_start": 0, "char_end": 100},
            {"chunk_id": "c2", "char_start": 100, "char_end": 200},
            {"chunk_id": "c3", "char_start": 200, "char_end": 300},
        ]
        retrieval = [
            {"chunk_id": "r1", "char_start": 50, "char_end": 150},
            {"chunk_id": "r2", "char_start": 175, "char_end": 275},
        ]

        basic = create_alignments(coverage, retrieval)
        optimized = create_alignments_optimized(coverage, retrieval)

        # Même nombre d'alignements
        assert len(basic) == len(optimized)

        # Mêmes paires (l'ordre peut différer)
        basic_pairs = {(a.coverage_chunk_id, a.retrieval_chunk_id) for a in basic}
        optim_pairs = {(a.coverage_chunk_id, a.retrieval_chunk_id) for a in optimized}
        assert basic_pairs == optim_pairs

    def test_handles_unsorted_input(self):
        """Fonctionne même avec des entrées non triées."""
        coverage = [
            {"chunk_id": "c3", "char_start": 200, "char_end": 300},
            {"chunk_id": "c1", "char_start": 0, "char_end": 100},
            {"chunk_id": "c2", "char_start": 100, "char_end": 200},
        ]
        retrieval = [
            {"chunk_id": "r2", "char_start": 150, "char_end": 250},
            {"chunk_id": "r1", "char_start": 50, "char_end": 150},
        ]

        alignments = create_alignments_optimized(coverage, retrieval)

        # Doit trouver les alignements malgré le désordre
        assert len(alignments) > 0


class TestAlignmentHelpers:
    """Tests pour les fonctions helper."""

    def test_get_aligned_coverage_for_retrieval(self):
        """Trouve les coverage alignés avec un retrieval."""
        alignments = [
            AlignmentRelation("c1", "r1", 100, 1.0),
            AlignmentRelation("c2", "r1", 50, 0.5),
            AlignmentRelation("c1", "r2", 80, 0.8),
        ]

        result = get_aligned_coverage_for_retrieval("r1", alignments)
        assert set(result) == {"c1", "c2"}

        result = get_aligned_coverage_for_retrieval("r2", alignments)
        assert result == ["c1"]

        result = get_aligned_coverage_for_retrieval("r_unknown", alignments)
        assert result == []

    def test_get_aligned_retrieval_for_coverage(self):
        """Trouve les retrieval alignés avec un coverage."""
        alignments = [
            AlignmentRelation("c1", "r1", 100, 1.0),
            AlignmentRelation("c1", "r2", 80, 0.8),
            AlignmentRelation("c2", "r1", 50, 0.5),
        ]

        result = get_aligned_retrieval_for_coverage("c1", alignments)
        assert set(result) == {"r1", "r2"}

        result = get_aligned_retrieval_for_coverage("c2", alignments)
        assert result == ["r1"]

    def test_build_alignment_index(self):
        """Construit l'index par retrieval_chunk_id."""
        alignments = [
            AlignmentRelation("c1", "r1", 100, 1.0),
            AlignmentRelation("c2", "r1", 50, 0.5),
            AlignmentRelation("c1", "r2", 80, 0.8),
        ]

        index = build_alignment_index(alignments)

        assert "r1" in index
        assert len(index["r1"]) == 2
        assert "r2" in index
        assert len(index["r2"]) == 1


class TestRealWorldScenarios:
    """Tests avec des scénarios réalistes."""

    def test_typical_document(self):
        """Simule un document typique avec plusieurs chunks."""
        # Simuler un document de ~15K caractères
        # CoverageChunks: 3200 chars chacun (800 tokens * 4)
        coverage = [
            {"chunk_id": "doc::coverage::0", "char_start": 0, "char_end": 3200},
            {"chunk_id": "doc::coverage::1", "char_start": 3200, "char_end": 6400},
            {"chunk_id": "doc::coverage::2", "char_start": 6400, "char_end": 9600},
            {"chunk_id": "doc::coverage::3", "char_start": 9600, "char_end": 12800},
            {"chunk_id": "doc::coverage::4", "char_start": 12800, "char_end": 15000},
        ]

        # RetrievalChunks: 1024 chars chacun (256 tokens * 4), overlap 256 chars
        retrieval = []
        for i, start in enumerate(range(0, 15000, 768)):  # stride = 1024-256
            end = min(start + 1024, 15000)
            retrieval.append({
                "chunk_id": f"doc::retrieval::{i}",
                "char_start": start,
                "char_end": end
            })

        alignments = create_alignments(coverage, retrieval)

        # Chaque coverage devrait avoir plusieurs alignements
        for c in coverage:
            aligned = [a for a in alignments if a.coverage_chunk_id == c["chunk_id"]]
            assert len(aligned) >= 1, f"Coverage {c['chunk_id']} has no alignments"

        # Chaque retrieval devrait avoir au moins un alignement
        for r in retrieval:
            aligned = [a for a in alignments if a.retrieval_chunk_id == r["chunk_id"]]
            assert len(aligned) >= 1, f"Retrieval {r['chunk_id']} has no alignments"
