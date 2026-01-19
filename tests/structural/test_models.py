"""
Tests for OSMOSE Structural Graph - Models

Tests des modèles Pydantic pour Option C.
"""

import pytest
from datetime import datetime

from knowbase.structural.models import (
    BboxUnit,
    ChunkKind,
    DocItem,
    DocItemType,
    DocumentVersion,
    PageContext,
    SectionInfo,
    StructuralProfile,
    TypeAwareChunk,
    compute_doc_hash,
    map_docling_label,
    RELATION_BEARING_TYPES,
    STRUCTURE_BEARING_TYPES,
)


class TestDocItemType:
    """Tests pour DocItemType enum."""

    def test_relation_bearing_types(self):
        """Vérifie les types relation-bearing (D3.1)."""
        assert DocItemType.TEXT in RELATION_BEARING_TYPES
        assert DocItemType.HEADING in RELATION_BEARING_TYPES
        assert DocItemType.CAPTION in RELATION_BEARING_TYPES
        assert DocItemType.FOOTNOTE in RELATION_BEARING_TYPES

    def test_structure_bearing_types(self):
        """Vérifie les types structure-bearing (D3.2)."""
        assert DocItemType.TABLE in STRUCTURE_BEARING_TYPES
        assert DocItemType.FIGURE in STRUCTURE_BEARING_TYPES
        assert DocItemType.CODE in STRUCTURE_BEARING_TYPES
        assert DocItemType.FORMULA in STRUCTURE_BEARING_TYPES

    def test_list_item_not_in_either(self):
        """LIST_ITEM est contextuel, pas dans les sets fixes."""
        assert DocItemType.LIST_ITEM not in RELATION_BEARING_TYPES
        assert DocItemType.LIST_ITEM not in STRUCTURE_BEARING_TYPES


class TestMapDoclingLabel:
    """Tests pour map_docling_label."""

    def test_text_types(self):
        """Mappe les types texte."""
        assert map_docling_label("text") == DocItemType.TEXT
        assert map_docling_label("paragraph") == DocItemType.TEXT
        assert map_docling_label("TEXT") == DocItemType.TEXT

    def test_heading_types(self):
        """Mappe les types heading."""
        assert map_docling_label("title") == DocItemType.HEADING
        assert map_docling_label("section_header") == DocItemType.HEADING

    def test_table_types(self):
        """Mappe les types table."""
        assert map_docling_label("table") == DocItemType.TABLE
        assert map_docling_label("chart") == DocItemType.TABLE

    def test_unknown_fallback(self):
        """Types inconnus → OTHER."""
        assert map_docling_label("unknown_type") == DocItemType.OTHER
        assert map_docling_label("") == DocItemType.OTHER
        assert map_docling_label(None) == DocItemType.OTHER


class TestDocItem:
    """Tests pour DocItem model."""

    def test_basic_creation(self):
        """Création basique d'un DocItem."""
        item = DocItem(
            tenant_id="default",
            doc_id="doc1",
            doc_version_id="v1:abc123",
            item_id="item_001",
            item_type=DocItemType.TEXT,
            text="Hello world",
            page_no=1,
            reading_order_index=0,
        )
        assert item.tenant_id == "default"
        assert item.item_type == DocItemType.TEXT
        assert item.page_no == 1

    def test_has_bbox(self):
        """Vérifie has_bbox property."""
        item_no_bbox = DocItem(
            tenant_id="t", doc_id="d", doc_version_id="v",
            item_id="i", item_type=DocItemType.TEXT,
            page_no=1, reading_order_index=0,
        )
        assert item_no_bbox.has_bbox is False

        item_with_bbox = DocItem(
            tenant_id="t", doc_id="d", doc_version_id="v",
            item_id="i", item_type=DocItemType.TEXT,
            page_no=1, reading_order_index=0,
            bbox_x0=0.0, bbox_y0=0.0, bbox_x1=100.0, bbox_y1=50.0,
        )
        assert item_with_bbox.has_bbox is True

    def test_is_multi_page(self):
        """Vérifie is_multi_page property."""
        single_page = DocItem(
            tenant_id="t", doc_id="d", doc_version_id="v",
            item_id="i", item_type=DocItemType.TABLE,
            page_no=1, reading_order_index=0,
        )
        assert single_page.is_multi_page is False

        multi_page = DocItem(
            tenant_id="t", doc_id="d", doc_version_id="v",
            item_id="i", item_type=DocItemType.TABLE,
            page_no=1, reading_order_index=0,
            page_span_min=1, page_span_max=3,
        )
        assert multi_page.is_multi_page is True

    def test_to_neo4j_properties(self):
        """Conversion en properties Neo4j."""
        item = DocItem(
            tenant_id="default",
            doc_id="doc1",
            doc_version_id="v1:abc",
            item_id="item_001",
            item_type=DocItemType.HEADING,
            heading_level=2,
            text="Section Title",
            page_no=5,
            reading_order_index=10,
            bbox_x0=50.0, bbox_y0=100.0, bbox_x1=500.0, bbox_y1=120.0,
            bbox_unit=BboxUnit.POINTS,
        )
        props = item.to_neo4j_properties()

        assert props["tenant_id"] == "default"
        assert props["doc_id"] == "doc1"
        assert props["item_type"] == "HEADING"
        assert props["heading_level"] == 2
        assert props["bbox_x0"] == 50.0
        assert props["bbox_unit"] == "points"


class TestStructuralProfile:
    """Tests pour StructuralProfile model."""

    def test_empty_profile(self):
        """Profil vide."""
        profile = StructuralProfile.empty()
        assert profile.total_items == 0
        assert profile.is_relation_bearing is False
        assert profile.is_structure_bearing is False

    def test_from_items_text_dominant(self):
        """Profil avec texte dominant → relation-bearing."""
        items = [
            DocItem(tenant_id="t", doc_id="d", doc_version_id="v",
                    item_id=f"i{i}", item_type=DocItemType.TEXT,
                    page_no=1, reading_order_index=i)
            for i in range(8)
        ] + [
            DocItem(tenant_id="t", doc_id="d", doc_version_id="v",
                    item_id="t1", item_type=DocItemType.TABLE,
                    page_no=1, reading_order_index=8),
            DocItem(tenant_id="t", doc_id="d", doc_version_id="v",
                    item_id="t2", item_type=DocItemType.TABLE,
                    page_no=1, reading_order_index=9),
        ]

        profile = StructuralProfile.from_items(items)
        assert profile.total_items == 10
        assert profile.text_ratio == 0.8
        assert profile.table_ratio == 0.2
        assert profile.is_relation_bearing is True
        assert profile.is_structure_bearing is False

    def test_from_items_table_dominant(self):
        """Profil avec tables dominantes → structure-bearing."""
        items = [
            DocItem(tenant_id="t", doc_id="d", doc_version_id="v",
                    item_id="txt", item_type=DocItemType.TEXT,
                    page_no=1, reading_order_index=0),
        ] + [
            DocItem(tenant_id="t", doc_id="d", doc_version_id="v",
                    item_id=f"t{i}", item_type=DocItemType.TABLE,
                    page_no=1, reading_order_index=i+1)
            for i in range(9)
        ]

        profile = StructuralProfile.from_items(items)
        assert profile.is_relation_bearing is False
        assert profile.is_structure_bearing is True

    def test_dominant_types(self):
        """Vérifie dominant_types (D10.5)."""
        items = [
            DocItem(tenant_id="t", doc_id="d", doc_version_id="v",
                    item_id="h1", item_type=DocItemType.HEADING,
                    page_no=1, reading_order_index=0),
            DocItem(tenant_id="t", doc_id="d", doc_version_id="v",
                    item_id="t1", item_type=DocItemType.TEXT,
                    page_no=1, reading_order_index=1),
            DocItem(tenant_id="t", doc_id="d", doc_version_id="v",
                    item_id="t2", item_type=DocItemType.TEXT,
                    page_no=1, reading_order_index=2),
            DocItem(tenant_id="t", doc_id="d", doc_version_id="v",
                    item_id="t3", item_type=DocItemType.TEXT,
                    page_no=1, reading_order_index=3),
        ]
        profile = StructuralProfile.from_items(items)
        assert "TEXT" in profile.dominant_types
        assert len(profile.dominant_types) <= 2


class TestComputeDocHash:
    """Tests pour compute_doc_hash (D6)."""

    def test_basic_hash(self):
        """Hash basique."""
        doc_dict = {"texts": [{"text": "hello", "self_ref": "t1"}]}
        hash1 = compute_doc_hash(doc_dict)

        assert hash1.startswith("v1:")
        assert len(hash1) > 10

    def test_deterministic(self):
        """Hash doit être déterministe."""
        doc_dict = {"texts": [{"text": "hello", "self_ref": "t1"}]}
        hash1 = compute_doc_hash(doc_dict)
        hash2 = compute_doc_hash(doc_dict)

        assert hash1 == hash2

    def test_volatile_fields_excluded(self):
        """Champs volatiles exclus (D6.2)."""
        doc1 = {
            "texts": [{"text": "hello", "self_ref": "t1"}],
            "origin": {"mtime": 123456, "path": "/old/path"},
        }
        doc2 = {
            "texts": [{"text": "hello", "self_ref": "t1"}],
            "origin": {"mtime": 999999, "path": "/new/path"},
        }

        # Mêmes contenus → même hash malgré origin différent
        assert compute_doc_hash(doc1) == compute_doc_hash(doc2)

    def test_content_change_different_hash(self):
        """Changement de contenu → hash différent."""
        doc1 = {"texts": [{"text": "hello", "self_ref": "t1"}]}
        doc2 = {"texts": [{"text": "world", "self_ref": "t1"}]}

        assert compute_doc_hash(doc1) != compute_doc_hash(doc2)

    def test_float_rounding(self):
        """Floats arrondis (D6.3)."""
        doc1 = {"confidence": 0.123456789, "self_ref": "t1"}
        doc2 = {"confidence": 0.12, "self_ref": "t1"}

        # Avec arrondi à 2 décimales, devrait être égal
        assert compute_doc_hash(doc1) == compute_doc_hash(doc2)


class TestPageContext:
    """Tests pour PageContext model."""

    def test_creation(self):
        """Création basique."""
        page = PageContext(
            tenant_id="default",
            doc_id="doc1",
            doc_version_id="v1:abc",
            page_no=5,
            page_width=612.0,
            page_height=792.0,
            bbox_unit=BboxUnit.POINTS,
        )
        assert page.page_no == 5
        assert page.bbox_unit == BboxUnit.POINTS

    def test_to_neo4j_properties(self):
        """Conversion en properties Neo4j."""
        page = PageContext(
            tenant_id="default",
            doc_id="doc1",
            doc_version_id="v1:abc",
            page_no=1,
            page_width=612.0,
            page_height=792.0,
        )
        props = page.to_neo4j_properties()

        assert props["page_no"] == 1
        assert props["page_width"] == 612.0
        assert props["bbox_unit"] == "points"


class TestTypeAwareChunk:
    """Tests pour TypeAwareChunk model."""

    def test_narrative_chunk(self):
        """Création d'un chunk narratif."""
        chunk = TypeAwareChunk(
            tenant_id="default",
            doc_id="doc1",
            doc_version_id="v1:abc",
            kind=ChunkKind.NARRATIVE_TEXT,
            text="This is narrative text.",
            item_ids=["i1", "i2", "i3"],
            page_no=1,
            is_relation_bearing=True,
        )
        assert chunk.kind == ChunkKind.NARRATIVE_TEXT
        assert chunk.is_relation_bearing is True
        assert len(chunk.item_ids) == 3

    def test_table_chunk(self):
        """Création d'un chunk table."""
        chunk = TypeAwareChunk(
            tenant_id="default",
            doc_id="doc1",
            doc_version_id="v1:abc",
            kind=ChunkKind.TABLE_TEXT,
            text="| col1 | col2 |\n|---|---|\n| a | b |",
            item_ids=["table_1"],
            page_no=5,
            is_relation_bearing=False,
        )
        assert chunk.kind == ChunkKind.TABLE_TEXT
        assert chunk.is_relation_bearing is False
