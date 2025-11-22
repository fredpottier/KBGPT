"""
🌊 OSMOSE Semantic Intelligence V2.1 - Tests ConceptLinker

Tests du ConceptLinker (cross-document linking)
"""

import pytest
from unittest.mock import Mock, AsyncMock
from src.knowbase.semantic.linking.concept_linker import ConceptLinker
from src.knowbase.semantic.models import (
    CanonicalConcept,
    DocumentRole
)
from src.knowbase.semantic.config import get_semantic_config


@pytest.fixture
def config():
    """Fixture configuration"""
    return get_semantic_config()


@pytest.fixture
def mock_llm_router():
    """Fixture LLMRouter mocké"""
    return AsyncMock()


@pytest.fixture
def linker(config, mock_llm_router):
    """Fixture ConceptLinker"""
    return ConceptLinker(mock_llm_router, config)


@pytest.fixture
def sample_canonical_concepts():
    """Concepts canoniques sample"""
    return [
        CanonicalConcept(
            canonical_name="ISO 27001",
            aliases=["ISO27001", "ISO 27001 Standard"],
            languages=["en"],
            type="standard",
            definition="Information security management standard",
            hierarchy_parent=None,
            hierarchy_children=[],
            related_concepts=["GDPR", "SOC2"],
            source_concepts=[],
            support=3,
            confidence=0.90
        ),
        CanonicalConcept(
            canonical_name="Multi-Factor Authentication",
            aliases=["MFA", "2FA", "Two-Factor Authentication"],
            languages=["en"],
            type="practice",
            definition="Authentication using multiple verification factors",
            hierarchy_parent="Authentication",
            hierarchy_children=[],
            related_concepts=["SSO", "Biometric"],
            source_concepts=[],
            support=2,
            confidence=0.85
        )
    ]


class TestConceptLinker:
    """Tests du ConceptLinker"""

    def test_classify_document_role_defines(self, linker):
        """Test classification DEFINES (standards, guidelines)"""
        role = linker._classify_document_role(
            document_title="ISO 27001 Standard Specification",
            document_text="This standard defines requirements for information security...",
            concept_name="ISO 27001"
        )

        assert role == DocumentRole.DEFINES

        print(f"\n✅ Classification DEFINES working")

    def test_classify_document_role_implements(self, linker):
        """Test classification IMPLEMENTS (projects, solutions)"""
        role = linker._classify_document_role(
            document_title="Security Implementation Project",
            document_text="This project implements ISO 27001 controls in our infrastructure...",
            concept_name="ISO 27001"
        )

        assert role == DocumentRole.IMPLEMENTS

        print(f"\n✅ Classification IMPLEMENTS working")

    def test_classify_document_role_audits(self, linker):
        """Test classification AUDITS (audit reports)"""
        role = linker._classify_document_role(
            document_title="2024 Security Audit Report",
            document_text="Audit of ISO 27001 compliance...",
            concept_name="ISO 27001"
        )

        assert role == DocumentRole.AUDITS

        print(f"\n✅ Classification AUDITS working")

    def test_classify_document_role_proves(self, linker):
        """Test classification PROVES (certificates)"""
        role = linker._classify_document_role(
            document_title="ISO 27001 Certification",
            document_text="Certificate of ISO 27001 compliance...",
            concept_name="ISO 27001"
        )

        assert role == DocumentRole.PROVES

        print(f"\n✅ Classification PROVES working")

    def test_classify_document_role_references(self, linker):
        """Test classification REFERENCES (default)"""
        role = linker._classify_document_role(
            document_title="Security Meeting Notes",
            document_text="We discussed ISO 27001 requirements...",
            concept_name="ISO 27001"
        )

        assert role == DocumentRole.REFERENCES

        print(f"\n✅ Classification REFERENCES working (default)")

    def test_extract_context_mention(self, linker):
        """Test extraction contexte mention"""
        document_text = """
        ISO 27001 is an international standard for information security management.
        It provides a framework for establishing, implementing, maintaining and
        continually improving an information security management system (ISMS).
        """

        context = linker._extract_context_mention(
            document_text=document_text,
            concept_name="ISO 27001",
            aliases=["ISO27001"],
            context_window=100
        )

        # Devrait extraire contexte autour de "ISO 27001"
        assert context, "Should extract context"
        assert "ISO 27001" in context or "international standard" in context

        print(f"\n✅ Context extraction: {context[:100]}...")

    def test_extract_context_mention_with_aliases(self, linker):
        """Test extraction avec aliases"""
        document_text = """
        Multi-Factor Authentication (MFA) is essential for security.
        MFA provides additional protection beyond passwords.
        """

        context = linker._extract_context_mention(
            document_text=document_text,
            concept_name="Multi-Factor Authentication",
            aliases=["MFA", "2FA"],
            context_window=80
        )

        assert context
        assert "MFA" in context or "Multi-Factor" in context

        print(f"\n✅ Context with aliases: {context[:100]}...")

    def test_link_concepts_to_documents(self, linker, sample_canonical_concepts):
        """Test linking concepts to document"""
        document_text = """
        ISO 27001 Standard Implementation Guide

        This document provides guidelines for implementing ISO 27001 controls.
        Multi-Factor Authentication (MFA) is a mandatory security control.
        Organizations must establish policies for MFA deployment.
        """

        connections = linker.link_concepts_to_documents(
            canonical_concepts=sample_canonical_concepts,
            document_id="doc_001",
            document_title="ISO 27001 Implementation Guide",
            document_text=document_text
        )

        # Devrait créer connexions
        assert len(connections) > 0, "Should create connections"

        for conn in connections:
            assert conn.document_id == "doc_001"
            assert conn.canonical_concept_name in ["ISO 27001", "Multi-Factor Authentication"]
            assert 0.0 <= conn.similarity <= 1.0
            assert conn.document_role in DocumentRole

        print(f"\n✅ Linked {len(connections)} concepts to document")
        for conn in connections:
            print(f"   - {conn.canonical_concept_name} (role={conn.document_role.value}, similarity={conn.similarity:.2f})")

    def test_link_concepts_no_match(self, linker):
        """Test linking avec concepts non mentionnés"""
        concepts = [
            CanonicalConcept(
                canonical_name="Blockchain",
                aliases=["DLT", "Distributed Ledger"],
                languages=["en"],
                type="entity",
                definition="",
                hierarchy_parent=None,
                hierarchy_children=[],
                related_concepts=[],
                source_concepts=[],
                support=1,
                confidence=0.80
            )
        ]

        document_text = """
        ISO 27001 Standard Implementation.
        This document covers security controls.
        """

        connections = linker.link_concepts_to_documents(
            canonical_concepts=concepts,
            document_id="doc_002",
            document_title="Security Guide",
            document_text=document_text
        )

        # Ne devrait pas créer de connexions (Blockchain pas dans le texte)
        # (ou très faible similarité sous threshold)
        assert len(connections) == 0 or all(c.similarity < 0.70 for c in connections)

        print(f"\n✅ No connections for unrelated concepts")

    @pytest.mark.asyncio
    async def test_find_documents_for_concept(self, linker):
        """Test recherche documents pour un concept"""
        all_documents = [
            {
                "id": "doc_001",
                "title": "ISO 27001 Standard",
                "text": "ISO 27001 is an information security standard. It defines requirements for ISMS."
            },
            {
                "id": "doc_002",
                "title": "Security Implementation",
                "text": "This project implements ISO 27001 controls across the organization."
            },
            {
                "id": "doc_003",
                "title": "Blockchain Technology",
                "text": "Blockchain is a distributed ledger technology used in cryptocurrencies."
            }
        ]

        connections = await linker.find_documents_for_concept(
            concept_name="ISO 27001",
            all_documents=all_documents,
            min_similarity=0.30  # Threshold bas pour test
        )

        # Devrait trouver doc_001 et doc_002 (pas doc_003)
        assert len(connections) >= 1, "Should find at least 1 document"

        doc_ids = [c.document_id for c in connections]
        assert "doc_001" in doc_ids or "doc_002" in doc_ids

        # doc_003 ne devrait pas être dans les résultats
        if "doc_003" in doc_ids:
            # Vérifier que similarité est faible
            blockchain_conn = next(c for c in connections if c.document_id == "doc_003")
            assert blockchain_conn.similarity < 0.50

        print(f"\n✅ Found {len(connections)} documents for 'ISO 27001'")
        for conn in connections[:3]:
            print(f"   - {conn.document_title} (role={conn.document_role.value}, sim={conn.similarity:.2f})")

    def test_build_concept_document_graph(self, linker, sample_canonical_concepts):
        """Test construction graph concept ↔ documents"""
        from src.knowbase.semantic.models import ConceptConnection

        connections = [
            ConceptConnection(
                document_id="doc_001",
                document_title="ISO 27001 Standard",
                document_role=DocumentRole.DEFINES,
                canonical_concept_name="ISO 27001",
                similarity=0.95,
                context="ISO 27001 defines requirements..."
            ),
            ConceptConnection(
                document_id="doc_002",
                document_title="Security Implementation",
                document_role=DocumentRole.IMPLEMENTS,
                canonical_concept_name="ISO 27001",
                similarity=0.88,
                context="Implementing ISO 27001..."
            ),
            ConceptConnection(
                document_id="doc_002",
                document_title="Security Implementation",
                document_role=DocumentRole.IMPLEMENTS,
                canonical_concept_name="Multi-Factor Authentication",
                similarity=0.82,
                context="MFA deployment..."
            )
        ]

        graph = linker.build_concept_document_graph(
            canonical_concepts=sample_canonical_concepts,
            all_connections=connections
        )

        # Vérifications
        assert "concepts" in graph
        assert "documents" in graph

        # Concept ISO 27001 → 2 documents
        assert "ISO 27001" in graph["concepts"]
        iso_concept = graph["concepts"]["ISO 27001"]
        assert len(iso_concept["documents"]) == 2
        assert "doc_001" in iso_concept["documents"]
        assert "doc_002" in iso_concept["documents"]

        # Rôles
        assert "doc_001" in iso_concept["roles"]["defines"]
        assert "doc_002" in iso_concept["roles"]["implements"]

        # Document doc_002 → 2 concepts
        assert "doc_002" in graph["documents"]
        doc_002 = graph["documents"]["doc_002"]
        assert doc_002["concept_count"] == 2
        assert "ISO 27001" in doc_002["concepts"]
        assert "Multi-Factor Authentication" in doc_002["concepts"]

        print(f"\n✅ Graph built:")
        print(f"   Concepts: {len(graph['concepts'])}")
        print(f"   Documents: {len(graph['documents'])}")
        print(f"   ISO 27001 → {iso_concept['documents']}")

    def test_empty_concepts(self, linker):
        """Test avec concepts vides"""
        connections = linker.link_concepts_to_documents(
            canonical_concepts=[],
            document_id="doc_001",
            document_title="Test",
            document_text="Test content"
        )

        assert len(connections) == 0

        print("\n✅ Empty concepts handled")


if __name__ == "__main__":
    # Run tests avec pytest
    pytest.main([__file__, "-v", "-s"])
