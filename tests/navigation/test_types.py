"""
Tests pour les types de la Navigation Layer.

ADR: doc/ongoing/ADR_NAVIGATION_LAYER.md
"""

import pytest
from datetime import datetime

from knowbase.navigation.types import (
    ContextNodeKind,
    ContextNode,
    DocumentContext,
    SectionContext,
    WindowContext,
    MentionedIn,
    NavigationLayerConfig,
    NAVIGATION_RELATION_TYPES,
    SEMANTIC_RELATION_TYPES,
)


class TestContextNodeKind:
    """Tests pour l'enum ContextNodeKind."""

    def test_enum_values(self):
        """Test que les valeurs de l'enum sont correctes."""
        assert ContextNodeKind.DOCUMENT == "document"
        assert ContextNodeKind.SECTION == "section"
        assert ContextNodeKind.WINDOW == "window"

    def test_enum_from_string(self):
        """Test conversion depuis string."""
        assert ContextNodeKind("document") == ContextNodeKind.DOCUMENT
        assert ContextNodeKind("section") == ContextNodeKind.SECTION


class TestDocumentContext:
    """Tests pour DocumentContext."""

    def test_create_document_context(self):
        """Test création d'un DocumentContext."""
        ctx = DocumentContext.create(
            document_id="doc-123",
            tenant_id="default",
            document_name="Test Document",
            document_type="pdf"
        )

        assert ctx.context_id == "doc:doc-123"
        assert ctx.kind == ContextNodeKind.DOCUMENT
        assert ctx.doc_id == "doc-123"
        assert ctx.tenant_id == "default"
        assert ctx.document_name == "Test Document"
        assert ctx.document_type == "pdf"

    def test_to_neo4j_props(self):
        """Test conversion en propriétés Neo4j."""
        ctx = DocumentContext.create(
            document_id="doc-456",
            document_name="Sample Doc"
        )

        props = ctx.to_neo4j_props()

        assert props["context_id"] == "doc:doc-456"
        assert props["kind"] == "document"
        assert props["doc_id"] == "doc-456"
        assert props["document_name"] == "Sample Doc"
        assert "created_at" in props


class TestSectionContext:
    """Tests pour SectionContext."""

    def test_create_section_context(self):
        """Test création d'un SectionContext."""
        ctx = SectionContext.create(
            document_id="doc-123",
            section_path="1.2.3 Security Architecture",
            tenant_id="default"
        )

        assert ctx.kind == ContextNodeKind.SECTION
        assert ctx.doc_id == "doc-123"
        assert ctx.section_path == "1.2.3 Security Architecture"
        assert ctx.context_id.startswith("sec:doc-123:")

    def test_section_context_id_uniqueness(self):
        """Test que le context_id est unique par section_path."""
        ctx1 = SectionContext.create("doc-1", "Section A")
        ctx2 = SectionContext.create("doc-1", "Section B")
        ctx3 = SectionContext.create("doc-1", "Section A")

        # Différentes sections = différents IDs
        assert ctx1.context_id != ctx2.context_id

        # Même section = même ID
        assert ctx1.context_id == ctx3.context_id


class TestWindowContext:
    """Tests pour WindowContext (désactivé par défaut)."""

    def test_create_window_context(self):
        """Test création d'un WindowContext."""
        ctx = WindowContext.create(
            chunk_id="chunk-789",
            document_id="doc-123"
        )

        assert ctx.kind == ContextNodeKind.WINDOW
        assert ctx.context_id == "win:chunk-789"
        assert ctx.chunk_id == "chunk-789"
        assert ctx.doc_id == "doc-123"


class TestMentionedIn:
    """Tests pour la relation MentionedIn."""

    def test_create_mentioned_in(self):
        """Test création d'une relation MentionedIn."""
        mention = MentionedIn(
            concept_id="cc_123",
            context_id="doc:doc-456",
            count=5,
            weight=0.8
        )

        assert mention.concept_id == "cc_123"
        assert mention.context_id == "doc:doc-456"
        assert mention.count == 5
        assert mention.weight == 0.8
        assert mention.first_seen is not None

    def test_to_neo4j_props(self):
        """Test conversion en propriétés Neo4j."""
        mention = MentionedIn(
            concept_id="cc_1",
            context_id="sec:doc:hash",
            count=3,
            weight=0.5
        )

        props = mention.to_neo4j_props()

        assert props["count"] == 3
        assert props["weight"] == 0.5
        assert "first_seen" in props


class TestNavigationLayerConfig:
    """Tests pour la configuration."""

    def test_default_config(self):
        """Test configuration par défaut."""
        config = NavigationLayerConfig()

        # Document et Section activés, Window désactivé (ADR)
        assert config.enable_document_context is True
        assert config.enable_section_context is True
        assert config.enable_window_context is False

        # Budgets
        assert config.max_windows_per_document == 50
        assert config.max_mentions_per_concept == 100

    def test_from_feature_flags(self):
        """Test chargement depuis feature_flags."""
        config = NavigationLayerConfig.from_feature_flags(tenant_id="test")

        # Devrait charger sans erreur
        assert config.tenant_id == "test"


class TestRelationTypeSets:
    """Tests pour les sets de types de relations."""

    def test_navigation_types(self):
        """Test que les types de navigation sont définis."""
        assert "MENTIONED_IN" in NAVIGATION_RELATION_TYPES
        assert "HAS_SECTION" in NAVIGATION_RELATION_TYPES
        assert "CONTAINED_IN" in NAVIGATION_RELATION_TYPES

    def test_semantic_types(self):
        """Test que les types sémantiques sont définis."""
        expected_types = [
            "REQUIRES", "ENABLES", "PREVENTS", "CAUSES",
            "APPLIES_TO", "DEPENDS_ON", "PART_OF", "MITIGATES",
            "CONFLICTS_WITH", "DEFINES", "EXAMPLE_OF", "GOVERNED_BY",
        ]

        for t in expected_types:
            assert t in SEMANTIC_RELATION_TYPES

    def test_no_overlap(self):
        """Test qu'il n'y a pas de chevauchement entre navigation et sémantique."""
        overlap = NAVIGATION_RELATION_TYPES & SEMANTIC_RELATION_TYPES
        assert len(overlap) == 0, f"Overlap found: {overlap}"
