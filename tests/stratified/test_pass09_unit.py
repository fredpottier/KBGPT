"""
Tests unitaires pour Pass 0.9 Global View Construction.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from knowbase.stratified.pass09 import (
    GlobalViewBuilder,
    SectionSummarizer,
    HierarchicalCompressor,
    SectionSummary,
    GlobalView,
    GlobalViewCoverage,
    Pass09Config,
)


class TestPass09Config:
    """Tests pour Pass09Config."""

    def test_default_config(self):
        """Vérifie les valeurs par défaut."""
        config = Pass09Config()

        assert config.section_summary_max_chars == 800
        assert config.section_min_chars_to_summarize == 200
        assert config.section_max_chars_for_verbatim == 500
        assert config.meta_document_target_chars == 20000
        assert config.min_coverage_ratio == 0.95


class TestSectionSummary:
    """Tests pour SectionSummary."""

    def test_compression_ratio_normal(self):
        """Test du ratio de compression normal."""
        summary = SectionSummary(
            section_id="sec_1",
            section_title="Test Section",
            level=1,
            summary="Short summary",
            char_count_original=1000,
            char_count_summary=100,
        )

        assert summary.compression_ratio == 0.1

    def test_compression_ratio_zero_original(self):
        """Test du ratio de compression avec original vide."""
        summary = SectionSummary(
            section_id="sec_1",
            section_title="Test",
            level=1,
            summary="",
            char_count_original=0,
            char_count_summary=0,
        )

        assert summary.compression_ratio == 0.0


class TestGlobalViewCoverage:
    """Tests pour GlobalViewCoverage."""

    def test_coverage_ratio(self):
        """Test du ratio de couverture."""
        coverage = GlobalViewCoverage(
            sections_total=100,
            sections_summarized=80,
            sections_verbatim=15,
            sections_skipped=5,
        )

        # (80 + 15) / 100 = 0.95
        assert coverage.coverage_ratio == 0.95

    def test_compression_ratio(self):
        """Test du ratio de compression."""
        coverage = GlobalViewCoverage(
            chars_original=100000,
            chars_meta_document=20000,
        )

        assert coverage.compression_ratio == 0.2


class TestGlobalView:
    """Tests pour GlobalView."""

    def test_is_valid_success(self):
        """Test validation réussie."""
        config = Pass09Config()

        view = GlobalView(
            tenant_id="default",
            doc_id="doc_123",
            meta_document="x" * 20000,  # Dans les limites
            coverage=GlobalViewCoverage(
                sections_total=100,
                sections_summarized=96,
                sections_verbatim=0,
                sections_skipped=4,
            )
        )

        assert view.is_valid(config)

    def test_is_valid_coverage_too_low(self):
        """Test validation échouée - couverture insuffisante."""
        config = Pass09Config()

        view = GlobalView(
            tenant_id="default",
            doc_id="doc_123",
            meta_document="x" * 20000,
            coverage=GlobalViewCoverage(
                sections_total=100,
                sections_summarized=50,  # 50% < 95%
                sections_verbatim=0,
                sections_skipped=50,
            )
        )

        assert not view.is_valid(config)

    def test_is_valid_meta_too_short(self):
        """Test validation échouée - meta-document trop court."""
        config = Pass09Config()

        view = GlobalView(
            tenant_id="default",
            doc_id="doc_123",
            meta_document="x" * 1000,  # < 5000
            coverage=GlobalViewCoverage(
                sections_total=10,
                sections_summarized=10,
            )
        )

        assert not view.is_valid(config)


class TestHierarchicalCompressor:
    """Tests pour HierarchicalCompressor."""

    def test_compress_basic(self):
        """Test compression basique."""
        compressor = HierarchicalCompressor()

        summaries = {
            "sec_1": SectionSummary(
                section_id="sec_1",
                section_title="Introduction",
                level=1,
                summary="This is the introduction.",
                concepts_mentioned=["concept1"],
                assertion_types=["definitional"],
                char_count_original=500,
                char_count_summary=25,
            ),
            "sec_2": SectionSummary(
                section_id="sec_2",
                section_title="Details",
                level=2,
                summary="Details about the topic.",
                concepts_mentioned=["concept2"],
                assertion_types=["prescriptive"],
                char_count_original=800,
                char_count_summary=24,
            ),
        }

        meta_doc, toc, coverage = compressor.compress(
            section_summaries=summaries,
            sections_order=["sec_1", "sec_2"],
            doc_title="Test Document",
        )

        # Vérifier le meta-document
        assert "# Document: Test Document" in meta_doc
        assert "Introduction" in meta_doc
        assert "Details" in meta_doc
        assert "This is the introduction." in meta_doc

        # Vérifier la TOC
        assert "Introduction" in toc
        assert "Details" in toc

        # Vérifier la couverture
        assert coverage.sections_total == 2

    def test_smart_truncate(self):
        """Test troncature intelligente."""
        compressor = HierarchicalCompressor()

        long_text = "# Header\n\n" + "x" * 50000

        result = compressor._smart_truncate(long_text, max_chars=1000)

        assert len(result) <= 1100  # Marge pour le message de troncature
        assert "# Header" in result  # Headers préservés
        assert "tronqué" in result  # Message de troncature


class TestSectionSummarizer:
    """Tests pour SectionSummarizer."""

    @pytest.mark.asyncio
    async def test_skip_short_section(self):
        """Test skip des sections trop courtes."""
        summarizer = SectionSummarizer(llm_client=None)

        sections = [
            {
                "id": "sec_1",
                "title": "Short Section",
                "level": 1,
            }
        ]
        section_texts = {
            "sec_1": "Short text."  # < 200 chars
        }

        summaries = await summarizer.summarize_sections(sections, section_texts)

        assert "sec_1" in summaries
        assert summaries["sec_1"].method == "skipped"
        assert summarizer.stats["sections_skipped"] == 1

    @pytest.mark.asyncio
    async def test_verbatim_medium_section(self):
        """Test copie verbatim des sections moyennes."""
        summarizer = SectionSummarizer(llm_client=None)

        text = "x" * 300  # Entre 200 et 500 chars

        sections = [{"id": "sec_1", "title": "Medium", "level": 1}]
        section_texts = {"sec_1": text}

        summaries = await summarizer.summarize_sections(sections, section_texts)

        assert summaries["sec_1"].method == "verbatim"
        assert summarizer.stats["sections_verbatim"] == 1


class TestGlobalViewBuilder:
    """Tests pour GlobalViewBuilder."""

    def test_create_sections_from_chunks_via_orchestrator(self):
        """Test création de sections artificielles via orchestrateur."""
        from knowbase.stratified.pass1.orchestrator import Pass1OrchestratorV2

        orchestrator = Pass1OrchestratorV2(llm_client=None, enable_pass09=False)

        chunks = {f"chunk_{i}": f"Text {i}" for i in range(12)}

        sections = orchestrator._create_sections_from_chunks(chunks)

        # 12 chunks / 5 par section = 3 sections (2 pleines + 1 partielle)
        assert len(sections) == 3
        assert sections[0]["title"] == "Section 1"
        assert len(sections[0]["chunk_ids"]) == 5
        assert len(sections[2]["chunk_ids"]) == 2  # Dernière section partielle

    def test_extract_section_texts_from_chunks(self):
        """Test extraction texte depuis chunk_ids."""
        builder = GlobalViewBuilder(llm_client=None)

        sections = [
            {"id": "sec_1", "chunk_ids": ["c1", "c2"]},
            {"id": "sec_2", "chunk_ids": ["c3"]},
        ]
        chunks = {
            "c1": "First chunk.",
            "c2": "Second chunk.",
            "c3": "Third chunk.",
        }

        texts = builder._extract_section_texts(sections, chunks, "")

        assert "First chunk." in texts["sec_1"]
        assert "Second chunk." in texts["sec_1"]
        assert texts["sec_2"] == "Third chunk."

    @pytest.mark.asyncio
    async def test_build_fallback(self):
        """Test construction en mode fallback (sans LLM)."""
        builder = GlobalViewBuilder(llm_client=None)

        sections = [
            {"id": "sec_1", "title": "Section 1", "level": 1, "chunk_ids": ["c1"]},
            {"id": "sec_2", "title": "Section 2", "level": 1, "chunk_ids": ["c2"]},
        ]
        chunks = {
            "c1": "Content for section 1 " * 50,  # ~1000 chars
            "c2": "Content for section 2 " * 50,
        }

        result = await builder.build(
            doc_id="test_doc",
            tenant_id="default",
            sections=sections,
            chunks=chunks,
            doc_title="Test Document",
        )

        assert result.is_fallback
        assert result.total_llm_calls == 0
        assert len(result.section_summaries) == 2
        assert "Section 1" in result.meta_document
        assert "Section 2" in result.meta_document


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
