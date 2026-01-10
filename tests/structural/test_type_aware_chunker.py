"""
Tests for OSMOSE Structural Graph - Type-Aware Chunker

Tests du chunker conscient du type.
"""

import pytest

from knowbase.structural.type_aware_chunker import (
    TypeAwareChunker,
    get_narrative_chunks,
    get_table_chunks,
    get_figure_chunks,
    get_code_chunks,
    analyze_chunks,
    build_item_to_chunk_mapping,
    get_chunks_for_items,
)
from knowbase.structural.models import (
    ChunkKind,
    DocItem,
    DocItemType,
    SectionInfo,
    StructuralProfile,
    TypeAwareChunk,
)


class TestTypeAwareChunker:
    """Tests pour TypeAwareChunker."""

    def test_initialization(self):
        """Initialisation du chunker."""
        chunker = TypeAwareChunker(
            tenant_id="default",
            doc_id="doc1",
            doc_version_id="v1:abc",
        )
        assert chunker.tenant_id == "default"
        assert chunker.doc_id == "doc1"

    def test_create_chunks_empty(self):
        """Items vides → chunks vides."""
        chunker = TypeAwareChunker(
            tenant_id="t", doc_id="d", doc_version_id="v",
        )
        chunks = chunker.create_chunks([], [])
        assert chunks == []

    def test_create_narrative_chunk(self):
        """Création d'un chunk narratif depuis items texte."""
        items = [
            DocItem(
                tenant_id="t", doc_id="d", doc_version_id="v",
                item_id="t1", item_type=DocItemType.TEXT,
                text="First paragraph.", page_no=1, reading_order_index=0,
                section_id="sec1",
            ),
            DocItem(
                tenant_id="t", doc_id="d", doc_version_id="v",
                item_id="t2", item_type=DocItemType.TEXT,
                text="Second paragraph.", page_no=1, reading_order_index=1,
                section_id="sec1",
            ),
        ]

        sections = [
            SectionInfo(
                section_id="sec1", doc_id="d", doc_version_id="v", tenant_id="t",
                section_path="root", section_level=0,
                structural_profile=StructuralProfile.from_items(items),
            )
        ]

        chunker = TypeAwareChunker(
            tenant_id="t", doc_id="d", doc_version_id="v",
        )
        chunks = chunker.create_chunks(items, sections)

        assert len(chunks) == 1
        assert chunks[0].kind == ChunkKind.NARRATIVE_TEXT
        assert chunks[0].is_relation_bearing is True
        assert "First paragraph" in chunks[0].text
        assert "Second paragraph" in chunks[0].text
        assert len(chunks[0].item_ids) == 2

    def test_create_table_chunk(self):
        """Création d'un chunk dédié pour table."""
        items = [
            DocItem(
                tenant_id="t", doc_id="d", doc_version_id="v",
                item_id="tab1", item_type=DocItemType.TABLE,
                text="| A | B |\n|---|---|\n| 1 | 2 |",
                page_no=1, reading_order_index=0,
                section_id="sec1",
            ),
        ]

        sections = [
            SectionInfo(
                section_id="sec1", doc_id="d", doc_version_id="v", tenant_id="t",
                section_path="root", section_level=0,
                structural_profile=StructuralProfile.from_items(items),
            )
        ]

        chunker = TypeAwareChunker(
            tenant_id="t", doc_id="d", doc_version_id="v",
        )
        chunks = chunker.create_chunks(items, sections)

        assert len(chunks) == 1
        assert chunks[0].kind == ChunkKind.TABLE_TEXT
        assert chunks[0].is_relation_bearing is False
        assert len(chunks[0].item_ids) == 1

    def test_mixed_items_create_separate_chunks(self):
        """Items mixtes → chunks séparés par type."""
        items = [
            DocItem(
                tenant_id="t", doc_id="d", doc_version_id="v",
                item_id="t1", item_type=DocItemType.TEXT,
                text="Before table.", page_no=1, reading_order_index=0,
                section_id="sec1",
            ),
            DocItem(
                tenant_id="t", doc_id="d", doc_version_id="v",
                item_id="tab1", item_type=DocItemType.TABLE,
                text="| A | B |", page_no=1, reading_order_index=1,
                section_id="sec1",
            ),
            DocItem(
                tenant_id="t", doc_id="d", doc_version_id="v",
                item_id="t2", item_type=DocItemType.TEXT,
                text="After table.", page_no=1, reading_order_index=2,
                section_id="sec1",
            ),
        ]

        sections = [
            SectionInfo(
                section_id="sec1", doc_id="d", doc_version_id="v", tenant_id="t",
                section_path="root", section_level=0,
                structural_profile=StructuralProfile.from_items(items),
            )
        ]

        chunker = TypeAwareChunker(
            tenant_id="t", doc_id="d", doc_version_id="v",
        )
        chunks = chunker.create_chunks(items, sections)

        # 3 chunks: narrative, table, narrative
        assert len(chunks) == 3

        narrative_chunks = [c for c in chunks if c.kind == ChunkKind.NARRATIVE_TEXT]
        table_chunks = [c for c in chunks if c.kind == ChunkKind.TABLE_TEXT]

        assert len(narrative_chunks) == 2
        assert len(table_chunks) == 1

    def test_figure_chunk_empty_text_ok(self):
        """Figure sans texte → chunk avec texte vide (D11.4)."""
        items = [
            DocItem(
                tenant_id="t", doc_id="d", doc_version_id="v",
                item_id="fig1", item_type=DocItemType.FIGURE,
                text="",  # Pas de caption
                page_no=1, reading_order_index=0,
                section_id="sec1",
            ),
        ]

        sections = [
            SectionInfo(
                section_id="sec1", doc_id="d", doc_version_id="v", tenant_id="t",
                section_path="root", section_level=0,
                structural_profile=StructuralProfile.from_items(items),
            )
        ]

        chunker = TypeAwareChunker(
            tenant_id="t", doc_id="d", doc_version_id="v",
        )
        chunks = chunker.create_chunks(items, sections)

        assert len(chunks) == 1
        assert chunks[0].kind == ChunkKind.FIGURE_TEXT
        assert chunks[0].text == ""  # Texte vide OK

    def test_large_text_split(self):
        """Grand texte → split en plusieurs chunks."""
        # Créer items avec beaucoup de texte
        items = [
            DocItem(
                tenant_id="t", doc_id="d", doc_version_id="v",
                item_id=f"t{i}", item_type=DocItemType.TEXT,
                text=f"Paragraph {i} with some content. " * 50,  # ~2000 chars
                page_no=1, reading_order_index=i,
                section_id="sec1",
            )
            for i in range(10)
        ]

        sections = [
            SectionInfo(
                section_id="sec1", doc_id="d", doc_version_id="v", tenant_id="t",
                section_path="root", section_level=0,
                structural_profile=StructuralProfile.from_items(items),
            )
        ]

        chunker = TypeAwareChunker(
            tenant_id="t", doc_id="d", doc_version_id="v",
            max_chunk_size=3000,  # Split after ~3000 chars
        )
        chunks = chunker.create_chunks(items, sections)

        # Devrait avoir plusieurs chunks narratifs
        narrative_chunks = get_narrative_chunks(chunks)
        assert len(narrative_chunks) > 1


class TestChunkFilters:
    """Tests pour les fonctions de filtrage de chunks."""

    def create_test_chunks(self):
        """Crée un set de test de chunks."""
        return [
            TypeAwareChunk(
                tenant_id="t", doc_id="d", doc_version_id="v",
                kind=ChunkKind.NARRATIVE_TEXT, text="Narrative 1",
                item_ids=["t1"], page_no=1,
            ),
            TypeAwareChunk(
                tenant_id="t", doc_id="d", doc_version_id="v",
                kind=ChunkKind.TABLE_TEXT, text="| A |",
                item_ids=["tab1"], page_no=1,
            ),
            TypeAwareChunk(
                tenant_id="t", doc_id="d", doc_version_id="v",
                kind=ChunkKind.NARRATIVE_TEXT, text="Narrative 2",
                item_ids=["t2"], page_no=2,
            ),
            TypeAwareChunk(
                tenant_id="t", doc_id="d", doc_version_id="v",
                kind=ChunkKind.FIGURE_TEXT, text="Caption",
                item_ids=["fig1"], page_no=2,
            ),
            TypeAwareChunk(
                tenant_id="t", doc_id="d", doc_version_id="v",
                kind=ChunkKind.CODE_TEXT, text="def foo():",
                item_ids=["code1"], page_no=3,
            ),
        ]

    def test_get_narrative_chunks(self):
        """Filtre les chunks narratifs."""
        chunks = self.create_test_chunks()
        result = get_narrative_chunks(chunks)

        assert len(result) == 2
        assert all(c.kind == ChunkKind.NARRATIVE_TEXT for c in result)

    def test_get_table_chunks(self):
        """Filtre les chunks de tables."""
        chunks = self.create_test_chunks()
        result = get_table_chunks(chunks)

        assert len(result) == 1
        assert result[0].kind == ChunkKind.TABLE_TEXT

    def test_get_figure_chunks(self):
        """Filtre les chunks de figures."""
        chunks = self.create_test_chunks()
        result = get_figure_chunks(chunks)

        assert len(result) == 1
        assert result[0].kind == ChunkKind.FIGURE_TEXT

    def test_get_code_chunks(self):
        """Filtre les chunks de code."""
        chunks = self.create_test_chunks()
        result = get_code_chunks(chunks)

        assert len(result) == 1
        assert result[0].kind == ChunkKind.CODE_TEXT


class TestAnalyzeChunks:
    """Tests pour analyze_chunks."""

    def test_basic_analysis(self):
        """Analyse basique des chunks."""
        chunks = [
            TypeAwareChunk(
                tenant_id="t", doc_id="d", doc_version_id="v",
                kind=ChunkKind.NARRATIVE_TEXT, text="Hello world",
                item_ids=["t1", "t2"], page_no=1,
            ),
            TypeAwareChunk(
                tenant_id="t", doc_id="d", doc_version_id="v",
                kind=ChunkKind.TABLE_TEXT, text="| A | B |",
                item_ids=["tab1"], page_no=1,
            ),
        ]

        analysis = analyze_chunks(chunks)

        assert analysis["total_chunks"] == 2
        assert analysis["narrative_chunks"] == 1
        assert "NARRATIVE_TEXT" in analysis["kind_distribution"]
        assert "TABLE_TEXT" in analysis["kind_distribution"]
        assert analysis["narrative_ratio"] == 0.5

    def test_empty_chunks(self):
        """Analyse de chunks vides."""
        analysis = analyze_chunks([])

        assert analysis["total_chunks"] == 0
        assert analysis["narrative_chunks"] == 0
        assert analysis["avg_chunk_size"] == 0


class TestBuildItemToChunkMapping:
    """Tests pour build_item_to_chunk_mapping."""

    def test_basic_mapping(self):
        """Mapping basique items → chunks."""
        chunks = [
            TypeAwareChunk(
                chunk_id="chunk1",
                tenant_id="t", doc_id="d", doc_version_id="v",
                kind=ChunkKind.NARRATIVE_TEXT, text="Text",
                item_ids=["t1", "t2"], page_no=1,
            ),
            TypeAwareChunk(
                chunk_id="chunk2",
                tenant_id="t", doc_id="d", doc_version_id="v",
                kind=ChunkKind.TABLE_TEXT, text="Table",
                item_ids=["tab1"], page_no=1,
            ),
        ]

        mapping = build_item_to_chunk_mapping(chunks)

        assert mapping["t1"] == "chunk1"
        assert mapping["t2"] == "chunk1"
        assert mapping["tab1"] == "chunk2"


class TestGetChunksForItems:
    """Tests pour get_chunks_for_items."""

    def test_find_chunks(self):
        """Trouve les chunks contenant des items."""
        chunks = [
            TypeAwareChunk(
                chunk_id="chunk1",
                tenant_id="t", doc_id="d", doc_version_id="v",
                kind=ChunkKind.NARRATIVE_TEXT, text="Text",
                item_ids=["t1", "t2"], page_no=1,
            ),
            TypeAwareChunk(
                chunk_id="chunk2",
                tenant_id="t", doc_id="d", doc_version_id="v",
                kind=ChunkKind.TABLE_TEXT, text="Table",
                item_ids=["tab1"], page_no=1,
            ),
            TypeAwareChunk(
                chunk_id="chunk3",
                tenant_id="t", doc_id="d", doc_version_id="v",
                kind=ChunkKind.NARRATIVE_TEXT, text="More",
                item_ids=["t3", "t4"], page_no=2,
            ),
        ]

        result = get_chunks_for_items(chunks, ["t1", "tab1"])

        assert len(result) == 2
        chunk_ids = {c.chunk_id for c in result}
        assert "chunk1" in chunk_ids
        assert "chunk2" in chunk_ids

    def test_no_matching_items(self):
        """Pas d'items correspondants → liste vide."""
        chunks = [
            TypeAwareChunk(
                chunk_id="chunk1",
                tenant_id="t", doc_id="d", doc_version_id="v",
                kind=ChunkKind.NARRATIVE_TEXT, text="Text",
                item_ids=["t1"], page_no=1,
            ),
        ]

        result = get_chunks_for_items(chunks, ["unknown"])

        assert result == []
