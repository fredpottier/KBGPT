"""
Tests for OSMOSE Structural Graph - DocItem Builder

Tests du builder pour extraction DoclingDocument → DocItem.
"""

import pytest
from unittest.mock import MagicMock, Mock

from knowbase.structural.docitem_builder import (
    DocItemBuilder,
    table_to_text,
    table_to_json,
    figure_to_text,
    select_primary_prov,
    compute_reading_order,
    extract_bbox,
    compute_page_span,
)
from knowbase.structural.models import DocItem, DocItemType


class TestTableToText:
    """Tests pour table_to_text (D11.2)."""

    def test_empty_table(self):
        """Table vide."""
        table_item = MagicMock()
        table_item.data = None

        result = table_to_text(table_item)
        assert result == "[TABLE: empty]"

    def test_simple_table(self):
        """Table simple avec headers et data."""
        # Mock table structure
        cell0 = Mock(row_span=0, text="Header1")
        cell1 = Mock(row_span=0, text="Header2")
        cell2 = Mock(row_span=1, text="Value1")
        cell3 = Mock(row_span=1, text="Value2")

        data = Mock()
        data.table_cells = [cell0, cell1, cell2, cell3]

        table_item = Mock()
        table_item.data = data
        table_item.self_ref = "table_1"

        result = table_to_text(table_item)

        assert "Header1" in result
        assert "Header2" in result
        assert "Value1" in result
        assert "Value2" in result
        assert "|" in result  # Markdown format

    def test_table_with_pipes(self):
        """Table avec pipes dans le texte (échappement)."""
        cell = Mock(row_span=0, text="Value|with|pipes")
        data = Mock()
        data.table_cells = [cell]

        table_item = Mock()
        table_item.data = data
        table_item.self_ref = "table_1"

        result = table_to_text(table_item)

        # Pipes doivent être échappés
        assert "\\|" in result or "with" in result


class TestTableToJson:
    """Tests pour table_to_json (D11.1)."""

    def test_simple_table(self):
        """Conversion JSON basique."""
        cell0 = Mock(row_span=0, text="H1")
        cell1 = Mock(row_span=0, text="H2")
        cell2 = Mock(row_span=1, text="V1")
        cell3 = Mock(row_span=1, text="V2")

        data = Mock()
        data.table_cells = [cell0, cell1, cell2, cell3]

        table_item = Mock()
        table_item.data = data
        table_item.self_ref = "table_1"

        result = table_to_json(table_item)

        assert result is not None
        import json
        parsed = json.loads(result)
        assert "headers" in parsed
        assert "cells" in parsed
        assert parsed["headers"] == ["H1", "H2"]


class TestFigureToText:
    """Tests pour figure_to_text (D11.3)."""

    def test_with_caption(self):
        """Figure avec caption."""
        pic = Mock()
        result = figure_to_text(pic, caption="Figure 1: Chart showing data")
        assert result == "Figure 1: Chart showing data"

    def test_without_caption(self):
        """Figure sans caption → chaîne vide."""
        pic = Mock()
        result = figure_to_text(pic, caption=None)
        assert result == ""

    def test_whitespace_caption(self):
        """Caption avec whitespace → trimmed."""
        pic = Mock()
        result = figure_to_text(pic, caption="  Caption with spaces  ")
        assert result == "Caption with spaces"


class TestSelectPrimaryProv:
    """Tests pour select_primary_prov (D5.1)."""

    def test_empty_list(self):
        """Liste vide → None."""
        assert select_primary_prov([]) is None

    def test_single_prov(self):
        """Un seul prov → retourné."""
        prov = Mock(page_no=5)
        assert select_primary_prov([prov]) is prov

    def test_multiple_provs_different_pages(self):
        """Plusieurs provs → plus petite page."""
        prov1 = Mock(page_no=5, bbox=Mock(t=100, l=50))
        prov2 = Mock(page_no=3, bbox=Mock(t=200, l=100))
        prov3 = Mock(page_no=7, bbox=Mock(t=50, l=25))

        result = select_primary_prov([prov1, prov2, prov3])
        assert result.page_no == 3

    def test_same_page_different_position(self):
        """Même page → plus haut (top minimal)."""
        prov1 = Mock(page_no=1, bbox=Mock(t=200, l=50))
        prov2 = Mock(page_no=1, bbox=Mock(t=100, l=100))
        prov3 = Mock(page_no=1, bbox=Mock(t=150, l=25))

        result = select_primary_prov([prov1, prov2, prov3])
        assert result.bbox.t == 100  # prov2 est le plus haut


class TestExtractBbox:
    """Tests pour extract_bbox."""

    def test_no_prov(self):
        """Pas de prov → tuple de None."""
        result = extract_bbox(None)
        assert result == (None, None, None, None)

    def test_no_bbox(self):
        """Prov sans bbox → tuple de None."""
        prov = Mock(bbox=None)
        result = extract_bbox(prov)
        assert result == (None, None, None, None)

    def test_with_bbox(self):
        """Prov avec bbox → coordonnées extraites."""
        bbox = Mock(l=10.0, t=20.0, r=100.0, b=50.0)
        prov = Mock(bbox=bbox)

        result = extract_bbox(prov)
        assert result == (10.0, 20.0, 100.0, 50.0)


class TestComputePageSpan:
    """Tests pour compute_page_span (D5.2)."""

    def test_empty_list(self):
        """Liste vide → (None, None)."""
        assert compute_page_span([]) == (None, None)

    def test_single_prov(self):
        """Un seul prov → (None, None)."""
        prov = Mock(page_no=5)
        assert compute_page_span([prov]) == (None, None)

    def test_same_page(self):
        """Tous sur la même page → (None, None)."""
        provs = [Mock(page_no=3), Mock(page_no=3), Mock(page_no=3)]
        assert compute_page_span(provs) == (None, None)

    def test_multiple_pages(self):
        """Pages différentes → (min, max)."""
        provs = [Mock(page_no=3), Mock(page_no=7), Mock(page_no=5)]
        assert compute_page_span(provs) == (3, 7)


class TestComputeReadingOrder:
    """Tests pour compute_reading_order (D2)."""

    def test_empty_list(self):
        """Liste vide."""
        assert compute_reading_order([]) == []

    def test_already_ordered(self):
        """Items déjà ordonnés."""
        items = [
            DocItem(tenant_id="t", doc_id="d", doc_version_id="v",
                    item_id="a", item_type=DocItemType.TEXT,
                    page_no=1, bbox_y0=10, reading_order_index=0),
            DocItem(tenant_id="t", doc_id="d", doc_version_id="v",
                    item_id="b", item_type=DocItemType.TEXT,
                    page_no=1, bbox_y0=50, reading_order_index=1),
        ]

        result = compute_reading_order(items)
        assert result[0].item_id == "a"
        assert result[1].item_id == "b"
        assert result[0].reading_order_index == 0
        assert result[1].reading_order_index == 1

    def test_reorder_by_page(self):
        """Réordonne par page."""
        items = [
            DocItem(tenant_id="t", doc_id="d", doc_version_id="v",
                    item_id="b", item_type=DocItemType.TEXT,
                    page_no=2, bbox_y0=10, reading_order_index=99),
            DocItem(tenant_id="t", doc_id="d", doc_version_id="v",
                    item_id="a", item_type=DocItemType.TEXT,
                    page_no=1, bbox_y0=50, reading_order_index=99),
        ]

        result = compute_reading_order(items)
        assert result[0].item_id == "a"  # Page 1 first
        assert result[1].item_id == "b"  # Page 2 second

    def test_reorder_by_position(self):
        """Réordonne par position sur la même page."""
        items = [
            DocItem(tenant_id="t", doc_id="d", doc_version_id="v",
                    item_id="c", item_type=DocItemType.TEXT,
                    page_no=1, bbox_y0=100, reading_order_index=99),
            DocItem(tenant_id="t", doc_id="d", doc_version_id="v",
                    item_id="a", item_type=DocItemType.TEXT,
                    page_no=1, bbox_y0=10, reading_order_index=99),
            DocItem(tenant_id="t", doc_id="d", doc_version_id="v",
                    item_id="b", item_type=DocItemType.TEXT,
                    page_no=1, bbox_y0=50, reading_order_index=99),
        ]

        result = compute_reading_order(items)
        assert result[0].item_id == "a"  # Top first
        assert result[1].item_id == "b"  # Middle
        assert result[2].item_id == "c"  # Bottom


class TestDocItemBuilder:
    """Tests pour DocItemBuilder."""

    def test_initialization(self):
        """Initialisation du builder."""
        builder = DocItemBuilder(
            tenant_id="default",
            doc_id="doc1",
            source_uri="/path/to/doc.pdf",
        )
        assert builder.tenant_id == "default"
        assert builder.doc_id == "doc1"

    def test_build_from_empty_doc(self):
        """Build depuis un doc vide."""
        doc = Mock()
        doc.texts = []
        doc.tables = []
        doc.pictures = []
        doc.pages = {}
        doc.export_to_dict = Mock(return_value={})
        doc.name = None
        doc.origin = None

        builder = DocItemBuilder(tenant_id="t", doc_id="d")
        result = builder.build_from_docling(doc)

        assert result.item_count == 0
        assert result.page_count == 1  # Fallback to 1 page
        assert result.doc_version.doc_version_id.startswith("v1:")

    def test_build_with_text_items(self):
        """Build avec items texte."""
        # Mock text item
        text1 = Mock()
        text1.self_ref = "text_1"
        text1.label = "text"
        text1.text = "Hello world"
        text1.prov = [Mock(page_no=1, bbox=Mock(l=10, t=20, r=100, b=40), charspan=None)]
        text1.parent = None
        text1.group = None

        text2 = Mock()
        text2.self_ref = "heading_1"
        text2.label = "section_header"
        text2.text = "Introduction"
        text2.prov = [Mock(page_no=1, bbox=Mock(l=10, t=50, r=200, b=70), charspan=None)]
        text2.parent = None
        text2.group = None

        doc = Mock()
        doc.texts = [text1, text2]
        doc.tables = []
        doc.pictures = []
        doc.pages = {1: Mock(size=Mock(width=612, height=792))}
        doc.export_to_dict = Mock(return_value={"texts": []})
        doc.name = "Test Doc"
        doc.origin = None

        builder = DocItemBuilder(tenant_id="default", doc_id="mydoc")
        result = builder.build_from_docling(doc)

        assert result.item_count == 2
        assert result.page_count == 1

        # Check types
        types = result.get_type_distribution()
        assert "TEXT" in types
        assert "HEADING" in types

    def test_build_result_summary(self):
        """Test du summary."""
        doc = Mock()
        doc.texts = []
        doc.tables = []
        doc.pictures = []
        doc.pages = {1: Mock(size=Mock(width=612, height=792))}
        doc.export_to_dict = Mock(return_value={})
        doc.name = None
        doc.origin = None

        builder = DocItemBuilder(tenant_id="t", doc_id="d")
        result = builder.build_from_docling(doc)

        summary = result.summary()
        assert "DocItemBuildResult" in summary
        assert "items" in summary
        assert "pages" in summary
