"""
Tests pour le CoverageChunkGenerator.

Vérifie que le générateur produit des chunks avec:
- Couverture 100% du document
- Aucun gap significatif
- Positions correctes
"""

import pytest
from knowbase.ingestion.coverage_chunk_generator import (
    CoverageChunkGenerator,
    CoverageChunk,
    generate_coverage_chunks,
    COVERAGE_CHUNK_SIZE_TOKENS,
)


class TestCoverageChunkGenerator:
    """Tests pour CoverageChunkGenerator."""

    def test_basic_generation(self):
        """Génère des chunks pour un texte simple."""
        generator = CoverageChunkGenerator()
        text = "A" * 10000  # 10K caractères
        chunks = generator.generate(text, "doc_001", "default")

        assert len(chunks) > 0
        assert all(isinstance(c, CoverageChunk) for c in chunks)
        assert all(c.chunk_type == "coverage" for c in chunks)

    def test_full_coverage(self):
        """Vérifie que tout le texte est couvert."""
        generator = CoverageChunkGenerator()
        text = "Hello world. " * 1000  # ~13K caractères

        chunks = generator.generate(text, "doc_002", "default")

        # Premier chunk commence à 0
        assert chunks[0].char_start == 0

        # Dernier chunk finit à la fin
        assert chunks[-1].char_end == len(text)

    def test_no_gaps(self):
        """Vérifie qu'il n'y a pas de gaps entre chunks."""
        generator = CoverageChunkGenerator()
        text = "Test content. " * 500

        chunks = generator.generate(text, "doc_003", "default")

        # Vérifier continuité (avec overlap=0, les chunks sont contigus)
        for i in range(1, len(chunks)):
            prev_end = chunks[i - 1].char_end
            curr_start = chunks[i].char_start
            # Avec overlap=0 et stride=chunk_size, curr_start devrait être <= prev_end
            # (égal si pas d'overlap, chevauchement si overlap>0)
            assert curr_start <= prev_end, f"Gap detected: {prev_end} -> {curr_start}"

    def test_chunk_ids_format(self):
        """Vérifie le format des chunk_id."""
        generator = CoverageChunkGenerator()
        text = "A" * 5000

        chunks = generator.generate(text, "my_doc_123", "tenant_x")

        for i, chunk in enumerate(chunks):
            expected_id = f"my_doc_123::coverage::{i}"
            assert chunk.chunk_id == expected_id
            assert chunk.coverage_seq == i

    def test_tenant_id_propagation(self):
        """Vérifie que le tenant_id est propagé."""
        generator = CoverageChunkGenerator()
        text = "A" * 5000

        chunks = generator.generate(text, "doc_001", "custom_tenant")

        for chunk in chunks:
            assert chunk.tenant_id == "custom_tenant"

    def test_empty_text(self):
        """Gère les textes vides."""
        generator = CoverageChunkGenerator()

        chunks = generator.generate("", "doc_empty", "default")

        assert chunks == []

    def test_small_text(self):
        """Texte plus petit qu'un chunk."""
        generator = CoverageChunkGenerator()
        text = "Short text."

        chunks = generator.generate(text, "doc_small", "default")

        assert len(chunks) == 1
        assert chunks[0].char_start == 0
        assert chunks[0].char_end == len(text)

    def test_exact_chunk_boundary(self):
        """Texte exactement de la taille d'un chunk."""
        generator = CoverageChunkGenerator()
        # Taille exacte = 800 tokens * 4 chars = 3200 chars
        text = "A" * 3200

        chunks = generator.generate(text, "doc_exact", "default")

        assert len(chunks) == 1
        assert chunks[0].char_start == 0
        assert chunks[0].char_end == 3200

    def test_coverage_validation_threshold(self):
        """La validation de couverture passe avec >95%."""
        generator = CoverageChunkGenerator()
        text = "B" * 10000

        # Ne devrait pas lever d'exception
        chunks = generator.generate(text, "doc_valid", "default")

        # Calculer la couverture
        total = sum(c.char_end - c.char_start for c in chunks)
        ratio = total / len(text)
        assert ratio >= 0.95

    def test_to_dict_conversion(self):
        """Vérifie la conversion en dict."""
        generator = CoverageChunkGenerator()
        text = "A" * 5000

        chunks = generator.generate(text, "doc_dict", "default")
        dicts = [c.to_dict() for c in chunks]

        for d in dicts:
            assert "chunk_id" in d
            assert "document_id" in d
            assert "chunk_type" in d
            assert d["chunk_type"] == "coverage"
            assert "char_start" in d
            assert "char_end" in d
            assert "coverage_seq" in d


class TestGenerateCoverageChunksUtility:
    """Tests pour la fonction utilitaire generate_coverage_chunks."""

    def test_returns_dicts(self):
        """Retourne une liste de dicts, pas d'objets."""
        text = "Content. " * 500

        chunks = generate_coverage_chunks(text, "doc_util", "default")

        assert isinstance(chunks, list)
        assert all(isinstance(c, dict) for c in chunks)

    def test_dict_structure(self):
        """Vérifie la structure des dicts retournés."""
        text = "A" * 5000

        chunks = generate_coverage_chunks(text, "doc_struct", "tenant_y")

        for chunk in chunks:
            assert chunk["document_id"] == "doc_struct"
            assert chunk["tenant_id"] == "tenant_y"
            assert chunk["chunk_type"] == "coverage"
            assert "chunk_id" in chunk
            assert "char_start" in chunk
            assert "char_end" in chunk


class TestCoverageChunkRealWorld:
    """Tests avec des scénarios réalistes."""

    def test_gdpr_document_size(self):
        """Simule un document GDPR (~150K caractères)."""
        generator = CoverageChunkGenerator()
        # Simuler un document GDPR de taille réaliste
        text = "[PARAGRAPH]\nArticle content here. " * 5000  # ~175K chars

        chunks = generator.generate(text, "gdpr_doc", "default")

        # Environ 175000 / 3200 = ~55 chunks
        assert len(chunks) >= 50
        assert len(chunks) <= 60

        # Couverture complète
        assert chunks[0].char_start == 0
        assert chunks[-1].char_end == len(text)

    def test_with_markers(self):
        """Fonctionne avec les marqueurs Docling."""
        generator = CoverageChunkGenerator()
        text = """[PAGE 1]
[TITLE level=1] Introduction

[PARAGRAPH]
This is the introduction paragraph with important content.

[TABLE_START id=tbl_1]
| Column A | Column B |
| Value 1 | Value 2 |
[TABLE_END]

[PARAGRAPH]
Conclusion paragraph here.
"""
        chunks = generator.generate(text, "doc_markers", "default")

        # Le texte est petit, donc 1 chunk
        assert len(chunks) == 1
        # Les marqueurs sont INCLUS dans le chunk (pas nettoyés)
        assert "[PAGE 1]" in chunks[0].text
        assert "[PARAGRAPH]" in chunks[0].text

    def test_sequential_ids(self):
        """Les coverage_seq sont séquentiels."""
        generator = CoverageChunkGenerator()
        text = "X" * 20000  # Plusieurs chunks

        chunks = generator.generate(text, "doc_seq", "default")

        for i, chunk in enumerate(chunks):
            assert chunk.coverage_seq == i
