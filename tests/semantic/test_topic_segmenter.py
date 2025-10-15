"""
🌊 OSMOSE Semantic Intelligence V2.1 - Tests TopicSegmenter

Tests du segmenteur de topics sémantiques
"""

import pytest
import asyncio
from src.knowbase.semantic.segmentation.topic_segmenter import TopicSegmenter
from src.knowbase.semantic.config import get_semantic_config


@pytest.fixture
def config():
    """Fixture configuration"""
    return get_semantic_config()


@pytest.fixture
def segmenter(config):
    """Fixture TopicSegmenter"""
    return TopicSegmenter(config)


class TestTopicSegmenter:
    """Tests du TopicSegmenter"""

    @pytest.mark.asyncio
    async def test_segment_simple_document(self, segmenter):
        """Test segmentation document simple anglais"""
        text = """
# ISO 27001 Security Standard

The ISO 27001 standard defines requirements for information security management systems.
It includes controls for access management, cryptography, and incident response.
Organizations must implement policies to protect information assets.

## Implementation Guidelines

Organizations must implement policies, procedures, and technical controls.
This includes access control mechanisms, encryption standards, and monitoring systems.
Regular audits ensure compliance with the standard requirements.

## Risk Management

Risk assessment is a critical component of ISO 27001 implementation.
Organizations must identify, analyze, and evaluate information security risks.
Treatment plans must be developed for all identified risks.
        """

        topics = await segmenter.segment_document("doc_test_001", text)

        # Assertions
        assert len(topics) >= 1, "Should find at least 1 topic"

        for topic in topics:
            assert topic.cohesion_score > 0.5, f"Cohesion too low: {topic.cohesion_score}"
            assert len(topic.anchors) > 0, "Should have anchors"
            assert topic.document_id == "doc_test_001"
            assert len(topic.windows) > 0, "Should have windows"

        print(f"\n✅ Found {len(topics)} topics")
        for i, topic in enumerate(topics):
            print(f"   Topic {i+1}: {len(topic.windows)} windows, cohesion={topic.cohesion_score:.2f}")
            print(f"   Anchors: {topic.anchors[:5]}")

    @pytest.mark.asyncio
    async def test_segment_multilingual_french(self, segmenter):
        """Test segmentation document français"""
        text_fr = """
# Norme ISO 27001

La norme ISO 27001 définit les exigences pour les systèmes de management de la sécurité de l'information.
Elle comprend des contrôles pour la gestion des accès, la cryptographie et la réponse aux incidents.
Les organisations doivent mettre en œuvre des politiques pour protéger les actifs informationnels.

## Mise en œuvre

Les organisations doivent implémenter des politiques, des procédures et des contrôles techniques.
Cela inclut des mécanismes de contrôle d'accès, des normes de chiffrement et des systèmes de surveillance.
Des audits réguliers garantissent la conformité aux exigences de la norme.
        """

        topics = await segmenter.segment_document("doc_test_002_fr", text_fr)

        assert len(topics) >= 1, "Should segment French document"

        for topic in topics:
            assert topic.cohesion_score > 0.5
            assert len(topic.anchors) > 0, "Should extract French anchors"

        # Vérifier détection entités françaises
        all_anchors = [a for t in topics for a in t.anchors]
        print(f"\n✅ French document: {len(topics)} topics, anchors: {all_anchors[:10]}")

    @pytest.mark.asyncio
    async def test_windowing(self, segmenter):
        """Test création fenêtres sliding"""
        text = "A" * 5000  # Texte 5000 chars

        from src.knowbase.semantic.models import Window
        windows = segmenter._create_windows(text, size=3000, overlap=0.25)

        assert len(windows) > 1, "Should create multiple windows"

        # Vérifier overlap
        for i in range(len(windows) - 1):
            w1 = windows[i]
            w2 = windows[i + 1]
            # Windows doivent se chevaucher
            assert w2.start < w1.end, "Windows should overlap"

        print(f"\n✅ Created {len(windows)} windows with 25% overlap")

    @pytest.mark.asyncio
    async def test_clustering_small_document(self, segmenter):
        """Test clustering sur petit document (fallback 1 cluster)"""
        text = "This is a very short document with minimal content."

        topics = await segmenter.segment_document("doc_test_003_short", text)

        # Petit document → probablement 1 topic ou 0 (si trop court)
        assert len(topics) <= 1, "Small document should have at most 1 topic"

        print(f"\n✅ Small document: {len(topics)} topics")

    @pytest.mark.asyncio
    async def test_section_extraction(self, segmenter):
        """Test extraction sections structurelles"""
        text = """
# Header 1
Content of section 1.

## Header 2
Content of section 2.

### Header 3
Content of section 3.

1. Numbered Section
Content numbered.
        """

        sections = segmenter._extract_sections(text)

        assert len(sections) >= 3, f"Should extract at least 3 sections, got {len(sections)}"

        # Vérifier chemins
        paths = [s["path"] for s in sections]
        print(f"\n✅ Extracted {len(sections)} sections:")
        for path in paths:
            print(f"   - {path}")

    @pytest.mark.asyncio
    async def test_anchor_extraction(self, segmenter):
        """Test extraction anchors (NER + TF-IDF)"""
        from src.knowbase.semantic.models import Window

        windows = [
            Window(text="ISO 27001 is a security standard for information security.", start=0, end=60),
            Window(text="The standard includes controls for access management and cryptography.", start=60, end=130)
        ]

        anchors = segmenter._extract_anchors_multilingual(windows, language="en")

        assert len(anchors) > 0, "Should extract anchors"

        # Au moins 1 entité pertinente détectée
        print(f"\n✅ Extracted {len(anchors)} anchors: {anchors}")

    def test_cohesion_calculation(self, segmenter):
        """Test calcul cohésion cluster"""
        import numpy as np

        # Embeddings très similaires (haute cohésion)
        embeddings_high = np.array([
            [1.0, 0.0, 0.0],
            [0.9, 0.1, 0.0],
            [0.8, 0.2, 0.0]
        ])

        cohesion_high = segmenter._calculate_cohesion(embeddings_high)
        assert cohesion_high > 0.8, f"High cohesion expected, got {cohesion_high}"

        # Embeddings dissimilaires (basse cohésion)
        embeddings_low = np.array([
            [1.0, 0.0, 0.0],
            [0.0, 1.0, 0.0],
            [0.0, 0.0, 1.0]
        ])

        cohesion_low = segmenter._calculate_cohesion(embeddings_low)
        assert cohesion_low < 0.5, f"Low cohesion expected, got {cohesion_low}"

        print(f"\n✅ Cohesion high={cohesion_high:.2f}, low={cohesion_low:.2f}")

    @pytest.mark.asyncio
    async def test_long_document_multiple_topics(self, segmenter):
        """Test document long avec multiples topics"""
        text = """
# Security Architecture

Security architecture defines the overall structure of security controls in an organization.
It includes network security, application security, and data security components.
The architecture must align with business objectives and risk tolerance.

# Access Control

Access control mechanisms restrict who can access what resources in the system.
This includes authentication, authorization, and accounting (AAA) frameworks.
Role-based access control (RBAC) is commonly used in enterprise environments.

# Encryption Standards

Encryption protects data confidentiality through cryptographic algorithms.
AES-256 is the gold standard for symmetric encryption in most organizations.
Public key infrastructure (PKI) enables secure key distribution and management.

# Incident Response

Incident response procedures define how to handle security incidents.
This includes detection, containment, eradication, and recovery phases.
Regular drills ensure the team is prepared for real incidents.
        """

        topics = await segmenter.segment_document("doc_test_004_long", text)

        # Document long avec sections distinctes → multiples topics attendus
        assert len(topics) >= 2, f"Should find multiple topics, got {len(topics)}"

        print(f"\n✅ Long document: {len(topics)} topics found")
        for i, topic in enumerate(topics):
            print(f"   Topic {i+1}: section='{topic.section_path}', cohesion={topic.cohesion_score:.2f}")


if __name__ == "__main__":
    # Run tests avec pytest
    pytest.main([__file__, "-v", "-s"])
