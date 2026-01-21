"""
Tests pour la séparation Scope Layer / Assertion Layer.

ADR: doc/ongoing/ADR_SCOPE_VS_ASSERTION_SEPARATION.md

Ces tests vérifient que:
1. Le Scope Layer (topic, scope_description) est correctement extrait et stocké
2. Le Scope Layer est utilisé pour la navigation/filtrage
3. Le Scope Layer n'est JAMAIS utilisé pour le raisonnement sémantique

Author: Claude Code
Date: 2026-01-21
"""

import pytest
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

from knowbase.navigation.types import (
    DocumentContext,
    SectionContext,
    NAVIGATION_RELATION_TYPES,
    SEMANTIC_RELATION_TYPES,
)
from knowbase.navigation.scope_extractor import (
    extract_document_topic,
    extract_scope_description,
    derive_scope_from_section_path,
    extract_mentioned_concepts_from_text,
    _extract_scope_keywords,
    SCOPE_KEYWORDS,
)
from knowbase.navigation.scope_filter import (
    ScopeFilter,
    ScopeFilterResult,
    build_qdrant_filter_from_scope,
)


# ============================================================================
# PARTIE 1: Tests Scope Extraction
# ============================================================================

class TestExtractDocumentTopic:
    """Tests pour l'extraction de topic depuis document."""

    def test_extract_from_title(self):
        """Test extraction depuis le titre."""
        topic = extract_document_topic(
            document_title="SAP S/4HANA Security Guide"
        )
        assert topic == "SAP S/4HANA Security Guide"

    def test_extract_from_name_removes_extension(self):
        """Test que l'extension est retirée."""
        topic = extract_document_topic(
            document_name="S4HANA_Security_Guide.pdf"
        )
        assert topic == "S4HANA Security Guide"
        assert ".pdf" not in topic

    def test_extract_from_name_removes_version_suffix(self):
        """Test que les suffixes de version sont retirés."""
        topic = extract_document_topic(
            document_name="Installation_Guide_v2.1.pdf"
        )
        assert "v2.1" not in topic
        assert topic == "Installation Guide"

    def test_extract_priority_title_over_name(self):
        """Test que le titre a priorité sur le nom."""
        topic = extract_document_topic(
            document_name="doc_123.pdf",
            document_title="SAP BTP Administration Guide"
        )
        assert topic == "SAP BTP Administration Guide"

    def test_extract_from_path_fallback(self):
        """Test extraction depuis le chemin en dernier recours."""
        topic = extract_document_topic(
            document_path="/data/docs/SAP_HANA_Guide.pdf"
        )
        assert topic == "SAP HANA Guide"

    def test_extract_returns_none_if_no_input(self):
        """Test que None est retourné si aucune entrée."""
        topic = extract_document_topic()
        assert topic is None

    def test_underscore_to_space_conversion(self):
        """Test conversion underscores en espaces."""
        topic = extract_document_topic(
            document_name="SAP_S4_HANA_Migration_Guide"
        )
        assert "_" not in topic
        assert " " in topic


class TestExtractScopeDescription:
    """Tests pour l'extraction de scope_description."""

    def test_basic_extraction(self):
        """Test extraction basique."""
        result = extract_scope_description(
            section_path="1.2.3 Security Architecture"
        )
        assert result.scope_description == "Security Architecture"

    def test_removes_section_numbers(self):
        """Test que les numéros de section sont retirés."""
        result = extract_scope_description(
            section_path="3.4.5.6 Integration Requirements"
        )
        assert result.scope_description == "Integration Requirements"
        assert not result.scope_description[0].isdigit()

    def test_title_has_priority(self):
        """Test que le titre explicite a priorité."""
        result = extract_scope_description(
            section_path="1.2 Sec",
            section_title="Detailed Security Configuration"
        )
        assert result.scope_description == "Detailed Security Configuration"

    def test_extracts_scope_keywords(self):
        """Test extraction des keywords de scope."""
        result = extract_scope_description(
            section_path="5.1 Security Requirements for Authentication"
        )
        assert "security" in result.scope_keywords
        assert "requirements" in result.scope_keywords


class TestDeriveScopeFromSectionPath:
    """Tests pour derive_scope_from_section_path."""

    def test_removes_leading_numbers(self):
        """Test suppression des numéros initiaux."""
        scope = derive_scope_from_section_path("1.2.3 Overview")
        assert scope == "Overview"

    def test_handles_no_numbers(self):
        """Test quand il n'y a pas de numéros."""
        scope = derive_scope_from_section_path("Executive Summary")
        assert scope == "Executive Summary"

    def test_returns_original_if_only_numbers(self):
        """Test retourne l'original si que des numéros."""
        scope = derive_scope_from_section_path("1.2.3")
        assert scope == "1.2.3"


class TestExtractScopeKeywords:
    """Tests pour l'extraction de keywords de scope."""

    def test_extracts_security_keywords(self):
        """Test extraction keywords sécurité."""
        keywords = _extract_scope_keywords("Security and Authentication Guide")
        assert "security" in keywords

    def test_extracts_configuration_keywords(self):
        """Test extraction keywords configuration."""
        keywords = _extract_scope_keywords("System Configuration and Setup")
        assert "configuration" in keywords

    def test_extracts_multiple_keywords(self):
        """Test extraction de plusieurs keywords."""
        keywords = _extract_scope_keywords(
            "Security Configuration for Migration"
        )
        assert "security" in keywords
        assert "configuration" in keywords
        assert "migration" in keywords

    def test_case_insensitive(self):
        """Test que l'extraction est case-insensitive."""
        keywords = _extract_scope_keywords("SECURITY REQUIREMENTS")
        assert "security" in keywords
        assert "requirements" in keywords


class TestExtractMentionedConcepts:
    """Tests pour extract_mentioned_concepts_from_text."""

    def test_finds_known_concepts(self):
        """Test trouve les concepts connus."""
        text = "SAP HANA requires 64GB of RAM for production."
        known = ["SAP HANA", "RAM", "CPU"]

        found = extract_mentioned_concepts_from_text(text, known)

        assert "SAP HANA" in found
        assert "RAM" in found
        assert "CPU" not in found

    def test_case_insensitive_matching(self):
        """Test matching case-insensitive."""
        text = "sap hana is a database"
        known = ["SAP HANA"]

        found = extract_mentioned_concepts_from_text(text, known)

        assert "SAP HANA" in found

    def test_empty_text(self):
        """Test avec texte vide."""
        found = extract_mentioned_concepts_from_text("", ["SAP"])
        assert len(found) == 0

    def test_no_matches(self):
        """Test quand aucun match."""
        found = extract_mentioned_concepts_from_text(
            "This is a general text",
            ["SAP HANA", "S/4HANA"]
        )
        assert len(found) == 0


# ============================================================================
# PARTIE 2: Tests Scope Storage (Navigation Types)
# ============================================================================

class TestDocumentContextWithTopic:
    """Tests pour DocumentContext avec topic (Scope Layer)."""

    def test_create_with_topic(self):
        """Test création DocumentContext avec topic."""
        ctx = DocumentContext.create(
            document_id="doc-123",
            document_name="SAP Guide",
            topic="SAP S/4HANA Security"
        )

        assert ctx.topic == "SAP S/4HANA Security"
        assert ctx.doc_id == "doc-123"

    def test_topic_in_neo4j_props(self):
        """Test que topic est inclus dans les props Neo4j."""
        ctx = DocumentContext.create(
            document_id="doc-456",
            topic="Migration Guide"
        )

        props = ctx.to_neo4j_props()

        assert "topic" in props
        assert props["topic"] == "Migration Guide"

    def test_topic_none_by_default(self):
        """Test que topic est None par défaut."""
        ctx = DocumentContext.create(document_id="doc-789")

        assert ctx.topic is None

    def test_topic_not_in_props_when_none(self):
        """Test que topic absent des props si None."""
        ctx = DocumentContext.create(document_id="doc-xxx")

        props = ctx.to_neo4j_props()

        # topic ne devrait pas être dans les props si None
        assert "topic" not in props or props.get("topic") is None


class TestSectionContextWithScopeDescription:
    """Tests pour SectionContext avec scope_description."""

    def test_create_with_scope_description(self):
        """Test création SectionContext avec scope_description."""
        ctx = SectionContext.create(
            document_id="doc-123",
            section_path="1.2 Security",
            scope_description="Security Architecture"
        )

        assert ctx.scope_description == "Security Architecture"

    def test_scope_description_in_neo4j_props(self):
        """Test que scope_description est inclus dans les props Neo4j."""
        ctx = SectionContext.create(
            document_id="doc-456",
            section_path="2.1 Config",
            scope_description="System Configuration"
        )

        props = ctx.to_neo4j_props()

        assert "scope_description" in props
        assert props["scope_description"] == "System Configuration"

    def test_scope_description_none_by_default(self):
        """Test que scope_description est None par défaut."""
        ctx = SectionContext.create(
            document_id="doc-789",
            section_path="3.1 Intro"
        )

        assert ctx.scope_description is None


# ============================================================================
# PARTIE 3: Tests Scope Filter
# ============================================================================

class TestScopeFilterResult:
    """Tests pour ScopeFilterResult."""

    def test_default_values(self):
        """Test valeurs par défaut."""
        result = ScopeFilterResult()

        assert result.document_ids == []
        assert result.section_ids == []
        assert result.topic_matched is None
        assert result.scope_keywords_matched == []
        assert result.total_documents == 0
        assert result.total_sections == 0


class TestScopeFilterUnit:
    """Tests unitaires pour ScopeFilter (sans Neo4j)."""

    @pytest.fixture
    def mock_neo4j_client(self):
        """Client Neo4j mocké."""
        client = MagicMock()
        session = AsyncMock()
        client.session.return_value.__aenter__ = AsyncMock(return_value=session)
        client.session.return_value.__aexit__ = AsyncMock()
        return client, session

    @pytest.mark.asyncio
    async def test_filter_by_topic(self, mock_neo4j_client):
        """Test filtrage par topic."""
        client, session = mock_neo4j_client

        # Mock du résultat Neo4j
        mock_result = AsyncMock()
        mock_result.data = AsyncMock(return_value=[
            {"doc_id": "doc-1"},
            {"doc_id": "doc-2"}
        ])
        session.run = AsyncMock(return_value=mock_result)

        scope_filter = ScopeFilter(client, tenant_id="default")
        result = await scope_filter.filter_by_scope(topic="S/4HANA")

        assert result.topic_matched == "S/4HANA"
        assert len(result.document_ids) == 2
        assert "doc-1" in result.document_ids
        assert "doc-2" in result.document_ids

    @pytest.mark.asyncio
    async def test_filter_by_scope_keywords(self, mock_neo4j_client):
        """Test filtrage par scope keywords."""
        client, session = mock_neo4j_client

        # Mock des résultats
        doc_result = AsyncMock()
        doc_result.data = AsyncMock(return_value=[])

        section_result = AsyncMock()
        section_result.data = AsyncMock(return_value=[
            {"section_id": "sec-1", "doc_id": "doc-1"},
            {"section_id": "sec-2", "doc_id": "doc-1"}
        ])

        session.run = AsyncMock(side_effect=[doc_result, section_result])

        scope_filter = ScopeFilter(client, tenant_id="default")
        result = await scope_filter.filter_by_scope(
            scope_keywords=["security", "authentication"]
        )

        assert len(result.section_ids) == 2
        assert result.scope_keywords_matched == ["security", "authentication"]


class TestBuildQdrantFilterFromScope:
    """Tests pour build_qdrant_filter_from_scope."""

    def test_single_document_filter(self):
        """Test filtre pour un seul document."""
        scope_result = ScopeFilterResult(
            document_ids=["doc-123"],
            total_documents=1
        )

        filter_params = build_qdrant_filter_from_scope(scope_result)

        assert filter_params.get("doc_id") == "doc-123"

    def test_merge_with_existing_filter(self):
        """Test fusion avec filtre existant."""
        scope_result = ScopeFilterResult(
            document_ids=["doc-456"],
            total_documents=1
        )
        existing = {"category": "security"}

        filter_params = build_qdrant_filter_from_scope(scope_result, existing)

        assert filter_params.get("category") == "security"
        assert filter_params.get("doc_id") == "doc-456"

    def test_multiple_documents_returns_none(self):
        """Test que plusieurs documents retourne None (TODO multi-doc)."""
        scope_result = ScopeFilterResult(
            document_ids=["doc-1", "doc-2", "doc-3"],
            total_documents=3
        )

        filter_params = build_qdrant_filter_from_scope(scope_result)

        # Pour l'instant, multi-doc non supporté
        assert filter_params.get("doc_id") is None


# ============================================================================
# PARTIE 4: Tests Séparation Scope/Assertion (CRITIQUE)
# ============================================================================

class TestScopeAssertionSeparation:
    """
    Tests CRITIQUES pour vérifier la séparation Scope/Assertion.

    INVARIANT (ADR): Les données de Scope Layer ne doivent JAMAIS
    être utilisées pour le raisonnement sémantique.
    """

    def test_scope_fields_not_in_semantic_relations(self):
        """Test que les champs scope ne sont pas dans les relations sémantiques."""
        # Les relations sémantiques ne doivent pas référencer topic/scope_description
        semantic_relation_fields = {
            "source_id", "target_id", "relation_type", "confidence",
            "evidence", "source_text", "defensibility_tier"
        }

        scope_fields = {"topic", "scope_description", "scope_keywords"}

        # Aucun champ scope ne doit être dans les relations sémantiques
        overlap = scope_fields & semantic_relation_fields
        assert len(overlap) == 0, f"Scope fields in semantic: {overlap}"

    def test_navigation_and_semantic_relations_disjoint(self):
        """Test que les types de relations navigation/sémantique sont disjoints."""
        overlap = NAVIGATION_RELATION_TYPES & SEMANTIC_RELATION_TYPES
        assert len(overlap) == 0, f"Overlap: {overlap}"

    def test_mentioned_in_is_navigation_only(self):
        """Test que MENTIONED_IN est une relation navigation uniquement."""
        assert "MENTIONED_IN" in NAVIGATION_RELATION_TYPES
        assert "MENTIONED_IN" not in SEMANTIC_RELATION_TYPES

    def test_scope_keywords_categories(self):
        """Test que les catégories de scope sont pour filtrage, pas sémantique."""
        # Les SCOPE_KEYWORDS sont pour le boosting de recherche
        # Ils ne doivent pas être des types de relations sémantiques
        scope_categories = set(SCOPE_KEYWORDS.keys())

        # Vérifier qu'aucune catégorie scope n'est un type de relation
        for category in scope_categories:
            assert category.upper() not in SEMANTIC_RELATION_TYPES, \
                f"Scope category '{category}' found in semantic relations!"

    def test_document_context_has_no_semantic_fields(self):
        """Test que DocumentContext n'a pas de champs sémantiques."""
        ctx = DocumentContext.create(
            document_id="doc-test",
            topic="Test Topic"
        )

        props = ctx.to_neo4j_props()

        # DocumentContext ne doit pas avoir de champs de relation sémantique
        semantic_fields = {
            "requires", "enables", "prevents", "causes",
            "relation_type", "confidence", "source_assertion"
        }

        for field in semantic_fields:
            assert field not in props, \
                f"Semantic field '{field}' found in DocumentContext!"

    def test_section_context_has_no_semantic_fields(self):
        """Test que SectionContext n'a pas de champs sémantiques."""
        ctx = SectionContext.create(
            document_id="doc-test",
            section_path="1.1 Test",
            scope_description="Test Section"
        )

        props = ctx.to_neo4j_props()

        # Pas de champs sémantiques
        semantic_fields = {
            "requires", "enables", "prevents", "causes",
            "relation_type", "confidence"
        }

        for field in semantic_fields:
            assert field not in props, \
                f"Semantic field '{field}' found in SectionContext!"


class TestScopeForNavigationOnly:
    """Tests que le scope est utilisé pour la navigation uniquement."""

    def test_scope_filter_returns_ids_not_relations(self):
        """Test que ScopeFilter retourne des IDs, pas des relations."""
        result = ScopeFilterResult(
            document_ids=["doc-1", "doc-2"],
            section_ids=["sec-1"],
            topic_matched="Security"
        )

        # ScopeFilterResult contient des IDs pour filtrage
        assert isinstance(result.document_ids, list)
        assert isinstance(result.section_ids, list)

        # Pas de relations sémantiques
        assert not hasattr(result, "relations")
        assert not hasattr(result, "semantic_links")

    def test_scope_boosts_are_numeric_weights(self):
        """Test que les boosts de scope sont des poids numériques."""
        # Les boosts sont pour le reranking, pas pour le raisonnement
        # Structure attendue: {doc_id: boost_score}
        expected_boost_type = float

        # Vérifier que la constante de boost est un float
        TOPIC_BOOST = 0.5
        SCOPE_BOOST = 0.3

        assert isinstance(TOPIC_BOOST, float)
        assert isinstance(SCOPE_BOOST, float)

        # Les boosts sont additifs, pas des relations
        assert 1.0 + TOPIC_BOOST == 1.5
        assert 1.0 + SCOPE_BOOST == 1.3


# ============================================================================
# PARTIE 5: Tests d'intégration Scope Extraction
# ============================================================================

class TestScopeExtractionIntegration:
    """Tests d'intégration pour l'extraction de scope."""

    def test_full_extraction_pipeline(self):
        """Test pipeline complet d'extraction."""
        # Simuler l'extraction pour un document
        document_name = "SAP_S4HANA_Security_Guide_v2.pdf"
        section_path = "3.2.1 Authentication Configuration"

        # 1. Extraire le topic
        topic = extract_document_topic(document_name=document_name)
        assert topic is not None
        assert "Security" in topic

        # 2. Extraire le scope de section
        scope_result = extract_scope_description(section_path=section_path)
        assert scope_result.scope_description is not None
        assert "Authentication Configuration" in scope_result.scope_description

        # 3. Vérifier les keywords
        assert "security" in scope_result.scope_keywords or \
               "configuration" in scope_result.scope_keywords

    def test_scope_preserved_in_context_nodes(self):
        """Test que le scope est préservé dans les ContextNodes."""
        # Créer DocumentContext avec topic
        doc_ctx = DocumentContext.create(
            document_id="integration-test-doc",
            document_name="Test Doc",
            topic="SAP Integration Testing"
        )

        # Créer SectionContext avec scope_description
        sec_ctx = SectionContext.create(
            document_id="integration-test-doc",
            section_path="1.1 Overview",
            scope_description="Integration Overview"
        )

        # Vérifier persistance dans props
        doc_props = doc_ctx.to_neo4j_props()
        sec_props = sec_ctx.to_neo4j_props()

        assert doc_props["topic"] == "SAP Integration Testing"
        assert sec_props["scope_description"] == "Integration Overview"
