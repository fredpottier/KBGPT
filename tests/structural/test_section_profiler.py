"""
Tests for OSMOSE Structural Graph - Section Profiler

Tests du profiler pour assignment DocItem → Section.
"""

import pytest

from knowbase.structural.section_profiler import (
    SectionProfiler,
    is_item_relation_bearing,
    filter_relation_bearing_items,
    analyze_document_structure,
    generate_section_id,
    build_section_path,
)
from knowbase.structural.models import (
    DocItem,
    DocItemType,
    SectionInfo,
    StructuralProfile,
)


class TestGenerateSectionId:
    """Tests pour generate_section_id."""

    def test_basic_id(self):
        """Génération d'ID basique."""
        item = DocItem(
            tenant_id="t", doc_id="d", doc_version_id="v",
            item_id="h1", item_type=DocItemType.HEADING,
            text="Introduction", page_no=1, reading_order_index=0,
        )
        section_id = generate_section_id(item)

        assert section_id.startswith("sec_")
        assert "introduction" in section_id.lower()

    def test_long_title_truncated(self):
        """Titres longs tronqués."""
        item = DocItem(
            tenant_id="t", doc_id="d", doc_version_id="v",
            item_id="h1", item_type=DocItemType.HEADING,
            text="This is a very long section title that should be truncated for the ID",
            page_no=1, reading_order_index=0,
        )
        section_id = generate_section_id(item)

        # L'ID ne doit pas être trop long
        assert len(section_id) < 50


class TestBuildSectionPath:
    """Tests pour build_section_path."""

    def test_empty_stack(self):
        """Stack vide → juste le titre courant."""
        path = build_section_path([], "Overview")
        assert path == "Overview"

    def test_with_parent(self):
        """Avec parent dans le stack."""
        stack = [(1, "sec_intro", "Introduction")]
        path = build_section_path(stack, "Overview")
        assert path == "Introduction / Overview"

    def test_deep_hierarchy(self):
        """Hiérarchie profonde."""
        stack = [
            (1, "sec_1", "Chapter 1"),
            (2, "sec_1_1", "Section 1.1"),
        ]
        path = build_section_path(stack, "Subsection 1.1.1")
        assert path == "Chapter 1 / Section 1.1 / Subsection 1.1.1"


class TestSectionProfiler:
    """Tests pour SectionProfiler."""

    def test_initialization(self):
        """Initialisation du profiler."""
        profiler = SectionProfiler(
            tenant_id="default",
            doc_id="doc1",
            doc_version_id="v1:abc",
        )
        assert profiler.tenant_id == "default"
        assert profiler.doc_id == "doc1"

    def test_assign_empty_items(self):
        """Items vides → sections vides."""
        profiler = SectionProfiler(
            tenant_id="t", doc_id="d", doc_version_id="v",
        )
        sections = profiler.assign_sections([])
        assert sections == []

    def test_assign_with_headings(self):
        """Assignment avec headings."""
        items = [
            DocItem(
                tenant_id="t", doc_id="d", doc_version_id="v",
                item_id="h1", item_type=DocItemType.HEADING,
                heading_level=1, text="Introduction",
                page_no=1, reading_order_index=0,
            ),
            DocItem(
                tenant_id="t", doc_id="d", doc_version_id="v",
                item_id="t1", item_type=DocItemType.TEXT,
                text="Some introductory text.",
                page_no=1, reading_order_index=1,
            ),
            DocItem(
                tenant_id="t", doc_id="d", doc_version_id="v",
                item_id="h2", item_type=DocItemType.HEADING,
                heading_level=1, text="Methods",
                page_no=2, reading_order_index=2,
            ),
            DocItem(
                tenant_id="t", doc_id="d", doc_version_id="v",
                item_id="t2", item_type=DocItemType.TEXT,
                text="Method description.",
                page_no=2, reading_order_index=3,
            ),
        ]

        profiler = SectionProfiler(
            tenant_id="t", doc_id="d", doc_version_id="v",
        )
        sections = profiler.assign_sections(items)

        # Au moins 2 sections (Introduction et Methods)
        assert len(sections) >= 2

        # Chaque item doit avoir un section_id
        for item in items:
            assert item.section_id is not None

    def test_assign_without_headings(self):
        """Assignment sans headings → sections par page."""
        items = [
            DocItem(
                tenant_id="t", doc_id="d", doc_version_id="v",
                item_id="t1", item_type=DocItemType.TEXT,
                text="Text on page 1.",
                page_no=1, reading_order_index=0,
            ),
            DocItem(
                tenant_id="t", doc_id="d", doc_version_id="v",
                item_id="t2", item_type=DocItemType.TEXT,
                text="More text on page 1.",
                page_no=1, reading_order_index=1,
            ),
            DocItem(
                tenant_id="t", doc_id="d", doc_version_id="v",
                item_id="t3", item_type=DocItemType.TEXT,
                text="Text on page 2.",
                page_no=2, reading_order_index=2,
            ),
        ]

        profiler = SectionProfiler(
            tenant_id="t", doc_id="d", doc_version_id="v",
        )
        sections = profiler.assign_sections(items)

        # Root + sections par page
        assert len(sections) >= 2

    def test_structural_profile_calculated(self):
        """Les profils structurels sont calculés."""
        items = [
            DocItem(
                tenant_id="t", doc_id="d", doc_version_id="v",
                item_id="h1", item_type=DocItemType.HEADING,
                heading_level=1, text="Section",
                page_no=1, reading_order_index=0,
            ),
            DocItem(
                tenant_id="t", doc_id="d", doc_version_id="v",
                item_id="t1", item_type=DocItemType.TEXT,
                text="Text 1", page_no=1, reading_order_index=1,
            ),
            DocItem(
                tenant_id="t", doc_id="d", doc_version_id="v",
                item_id="t2", item_type=DocItemType.TEXT,
                text="Text 2", page_no=1, reading_order_index=2,
            ),
        ]

        profiler = SectionProfiler(
            tenant_id="t", doc_id="d", doc_version_id="v",
        )
        sections = profiler.assign_sections(items)

        # Au moins une section doit avoir un profil
        sections_with_profile = [s for s in sections if s.structural_profile]
        assert len(sections_with_profile) > 0


class TestIsItemRelationBearing:
    """Tests pour is_item_relation_bearing (D3.3)."""

    def test_text_always_relation_bearing(self):
        """TEXT est toujours relation-bearing."""
        item = DocItem(
            tenant_id="t", doc_id="d", doc_version_id="v",
            item_id="t1", item_type=DocItemType.TEXT,
            page_no=1, reading_order_index=0,
        )
        profile = StructuralProfile.empty()

        assert is_item_relation_bearing(item, profile) is True

    def test_table_never_relation_bearing(self):
        """TABLE n'est jamais relation-bearing."""
        item = DocItem(
            tenant_id="t", doc_id="d", doc_version_id="v",
            item_id="t1", item_type=DocItemType.TABLE,
            page_no=1, reading_order_index=0,
        )
        profile = StructuralProfile(is_relation_bearing=True)

        assert is_item_relation_bearing(item, profile) is False

    def test_list_item_contextual(self):
        """LIST_ITEM dépend du contexte section."""
        item = DocItem(
            tenant_id="t", doc_id="d", doc_version_id="v",
            item_id="l1", item_type=DocItemType.LIST_ITEM,
            page_no=1, reading_order_index=0,
        )

        # Section relation-bearing avec peu de listes → oui
        profile_low_list = StructuralProfile(
            is_relation_bearing=True,
            list_ratio=0.3,
        )
        assert is_item_relation_bearing(item, profile_low_list) is True

        # Section structure-bearing → non
        profile_structure = StructuralProfile(
            is_relation_bearing=False,
            list_ratio=0.3,
        )
        assert is_item_relation_bearing(item, profile_structure) is False

        # Section avec beaucoup de listes → non
        profile_high_list = StructuralProfile(
            is_relation_bearing=True,
            list_ratio=0.7,
        )
        assert is_item_relation_bearing(item, profile_high_list) is False


class TestFilterRelationBearingItems:
    """Tests pour filter_relation_bearing_items."""

    def test_filter_mixed_items(self):
        """Filtre un mix d'items."""
        items = [
            DocItem(
                tenant_id="t", doc_id="d", doc_version_id="v",
                item_id="t1", item_type=DocItemType.TEXT,
                page_no=1, reading_order_index=0, section_id="sec1",
            ),
            DocItem(
                tenant_id="t", doc_id="d", doc_version_id="v",
                item_id="tab1", item_type=DocItemType.TABLE,
                page_no=1, reading_order_index=1, section_id="sec1",
            ),
            DocItem(
                tenant_id="t", doc_id="d", doc_version_id="v",
                item_id="h1", item_type=DocItemType.HEADING,
                page_no=1, reading_order_index=2, section_id="sec1",
            ),
            DocItem(
                tenant_id="t", doc_id="d", doc_version_id="v",
                item_id="fig1", item_type=DocItemType.FIGURE,
                page_no=1, reading_order_index=3, section_id="sec1",
            ),
        ]

        sections = [
            SectionInfo(
                section_id="sec1", doc_id="d", doc_version_id="v", tenant_id="t",
                section_path="root", section_level=0,
                structural_profile=StructuralProfile(is_relation_bearing=True),
            )
        ]

        result = filter_relation_bearing_items(items, sections)

        # Seuls TEXT et HEADING sont relation-bearing
        assert len(result) == 2
        assert all(i.item_type in {DocItemType.TEXT, DocItemType.HEADING} for i in result)


class TestAnalyzeDocumentStructure:
    """Tests pour analyze_document_structure."""

    def test_basic_analysis(self):
        """Analyse basique."""
        items = [
            DocItem(
                tenant_id="t", doc_id="d", doc_version_id="v",
                item_id="t1", item_type=DocItemType.TEXT,
                page_no=1, reading_order_index=0, section_id="sec1",
            ),
            DocItem(
                tenant_id="t", doc_id="d", doc_version_id="v",
                item_id="tab1", item_type=DocItemType.TABLE,
                page_no=1, reading_order_index=1, section_id="sec1",
            ),
        ]

        sections = [
            SectionInfo(
                section_id="sec1", doc_id="d", doc_version_id="v", tenant_id="t",
                section_path="root", section_level=0,
                structural_profile=StructuralProfile.from_items(items),
            )
        ]

        analysis = analyze_document_structure(items, sections)

        assert analysis["total_items"] == 2
        assert analysis["total_sections"] == 1
        assert "TEXT" in analysis["type_distribution"]
        assert "TABLE" in analysis["type_distribution"]
        assert analysis["relation_bearing_items"] == 1
        assert "sections" in analysis
