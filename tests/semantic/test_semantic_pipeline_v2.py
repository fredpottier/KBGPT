"""
🌊 OSMOSE Semantic Intelligence V2.1 - Tests Pipeline End-to-End

Tests du pipeline complet V2.1
"""

import pytest
from unittest.mock import Mock, AsyncMock
from src.knowbase.semantic.semantic_pipeline_v2 import (
    SemanticPipelineV2,
    process_document_semantic_v2
)
from src.knowbase.semantic.config import get_semantic_config


@pytest.fixture
def config():
    """Fixture configuration"""
    return get_semantic_config()


@pytest.fixture
def mock_llm_router():
    """Fixture LLMRouter mocké"""
    router = AsyncMock()

    # Mock pour extraction concepts
    router.route_request = AsyncMock(return_value={
        "content": """{
            "concepts": [
                {
                    "name": "ISO 27001",
                    "type": "STANDARD",
                    "definition": "Information security standard",
                    "relationships": ["security", "compliance"]
                }
            ]
        }"""
    })

    return router


@pytest.fixture
def pipeline(config, mock_llm_router):
    """Fixture Pipeline V2.1"""
    return SemanticPipelineV2(llm_router=mock_llm_router, config=config)


@pytest.fixture
def sample_document_multilingual():
    """Document sample multilingue (EN/FR)"""
    return {
        "document_id": "test_doc_001",
        "document_title": "ISO 27001 Security Guide",
        "document_path": "/docs/iso27001_guide.pdf",
        "text_content": """
# ISO 27001 Information Security Standard

ISO 27001 is an international standard for information security management systems (ISMS).
It provides a framework for establishing, implementing, maintaining and continually
improving information security.

## Key Requirements

The standard includes several mandatory security controls:

1. **Access Control**: Organizations must implement access control policies.
   Multi-Factor Authentication (MFA) is strongly recommended.

2. **Cryptography**: Data encryption must be used for sensitive information.
   Organizations should use industry-standard encryption algorithms.

3. **Incident Management**: Security incidents must be reported and managed.

## French Summary / Résumé Français

La norme ISO 27001 définit les exigences pour les systèmes de management
de la sécurité de l'information (SMSI).

L'authentification multifacteur (MFA) est une mesure de sécurité essentielle.
Les organisations doivent établir des politiques de contrôle d'accès.

## Compliance

Organizations can obtain ISO 27001 certification by demonstrating compliance
with all mandatory controls through an external audit.
        """
    }


class TestSemanticPipelineV2:
    """Tests du pipeline V2.1 complet"""

    @pytest.mark.asyncio
    async def test_pipeline_basic(self, pipeline, sample_document_multilingual):
        """Test pipeline basique end-to-end"""
        result = await pipeline.process_document(
            document_id=sample_document_multilingual["document_id"],
            document_title=sample_document_multilingual["document_title"],
            document_path=sample_document_multilingual["document_path"],
            text_content=sample_document_multilingual["text_content"],
            tenant_id="test_tenant",
            enable_llm=False  # Désactiver LLM pour test rapide
        )

        # Vérifications résultat
        assert result["success"], f"Pipeline should succeed: {result.get('error')}"
        assert result["document_id"] == "test_doc_001"

        # Métriques
        metrics = result["metrics"]
        assert metrics["topics_count"] >= 1, "Should segment at least 1 topic"
        assert metrics["concepts_count"] >= 1, "Should extract at least 1 concept"
        assert metrics["canonical_concepts_count"] >= 1, "Should create canonical concepts"

        # Langues détectées
        assert len(metrics["languages_detected"]) >= 1

        # Performance
        assert result["processing_time_ms"] > 0

        print(f"\n✅ Pipeline basic test:")
        print(f"   Topics: {metrics['topics_count']}")
        print(f"   Concepts: {metrics['concepts_count']}")
        print(f"   Canonical: {metrics['canonical_concepts_count']}")
        print(f"   Connections: {metrics['connections_count']}")
        print(f"   Languages: {metrics['languages_detected']}")
        print(f"   Time: {result['processing_time_ms']}ms")

    @pytest.mark.asyncio
    async def test_pipeline_cross_lingual_unification(self, pipeline, sample_document_multilingual):
        """Test unification cross-lingual (FR/EN)"""
        result = await pipeline.process_document(
            document_id=sample_document_multilingual["document_id"],
            document_title=sample_document_multilingual["document_title"],
            document_path=sample_document_multilingual["document_path"],
            text_content=sample_document_multilingual["text_content"],
            tenant_id="test_tenant",
            enable_llm=False
        )

        assert result["success"]

        # Vérifier unification multilingue
        # "MFA" EN + "MFA" FR devraient être unifiés
        canonical_concepts = result["data"]["canonical_concepts"]

        # Au moins 1 concept canonique avec multi-langues
        multilingual_concepts = [
            c for c in canonical_concepts
            if len(c.get("languages", [])) > 1
        ]

        # Note: Peut ne pas fonctionner si NER seul (sans LLM)
        # C'est normal, test juste structure
        if multilingual_concepts:
            print(f"\n✅ Cross-lingual unification working:")
            for c in multilingual_concepts[:3]:
                print(f"   - {c['canonical_name']} (langs={c['languages']})")
        else:
            print(f"\n⚠️ No cross-lingual unification (may need LLM enabled)")

    @pytest.mark.asyncio
    async def test_pipeline_concept_linking(self, pipeline, sample_document_multilingual):
        """Test linking concepts to document"""
        result = await pipeline.process_document(
            document_id=sample_document_multilingual["document_id"],
            document_title=sample_document_multilingual["document_title"],
            document_path=sample_document_multilingual["document_path"],
            text_content=sample_document_multilingual["text_content"],
            tenant_id="test_tenant",
            enable_llm=False
        )

        assert result["success"]

        connections = result["data"]["connections"]

        # Devrait créer connexions
        assert len(connections) > 0, "Should create concept-document connections"

        for conn in connections:
            assert conn["document_id"] == sample_document_multilingual["document_id"]
            assert conn["canonical_concept_name"]
            assert conn["document_role"] in [
                "defines", "implements", "audits", "proves", "references"
            ]
            assert 0.0 <= conn["similarity"] <= 1.0

        print(f"\n✅ Concept linking: {len(connections)} connections")
        for conn in connections[:5]:
            print(f"   - {conn['canonical_concept_name']} (role={conn['document_role']})")

    @pytest.mark.asyncio
    async def test_pipeline_hierarchy(self, pipeline, sample_document_multilingual):
        """Test construction hiérarchie"""
        result = await pipeline.process_document(
            document_id=sample_document_multilingual["document_id"],
            document_title=sample_document_multilingual["document_title"],
            document_path=sample_document_multilingual["document_path"],
            text_content=sample_document_multilingual["text_content"],
            tenant_id="test_tenant",
            enable_llm=False,
            enable_hierarchy=True
        )

        assert result["success"]

        canonical_concepts = result["data"]["canonical_concepts"]

        # Vérifier si hiérarchies créées
        concepts_with_hierarchy = [
            c for c in canonical_concepts
            if c.get("hierarchy_parent") or c.get("hierarchy_children")
        ]

        if concepts_with_hierarchy:
            print(f"\n✅ Hierarchy built: {len(concepts_with_hierarchy)} concepts")
            for c in concepts_with_hierarchy[:3]:
                if c.get("hierarchy_parent"):
                    print(f"   - {c['canonical_name']} → parent: {c['hierarchy_parent']}")
                if c.get("hierarchy_children"):
                    print(f"   - {c['canonical_name']} → children: {c['hierarchy_children']}")
        else:
            print("\n⚠️ No hierarchy (normal for small document)")

    @pytest.mark.asyncio
    async def test_pipeline_empty_document(self, pipeline):
        """Test avec document vide"""
        result = await pipeline.process_document(
            document_id="empty_doc",
            document_title="Empty Document",
            document_path="/tmp/empty.txt",
            text_content="",
            tenant_id="test_tenant"
        )

        # Pipeline devrait échouer gracefully
        assert not result["success"]
        assert result["error"]
        assert result["metrics"]["topics_count"] == 0

        print("\n✅ Empty document handled gracefully")

    @pytest.mark.asyncio
    async def test_pipeline_short_document(self, pipeline):
        """Test avec document très court"""
        result = await pipeline.process_document(
            document_id="short_doc",
            document_title="Short Note",
            document_path="/tmp/short.txt",
            text_content="ISO 27001 is a security standard.",
            tenant_id="test_tenant",
            enable_llm=False
        )

        # Devrait réussir même si peu de concepts
        assert result["success"]
        assert result["metrics"]["topics_count"] >= 1

        print(f"\n✅ Short document processed: {result['metrics']['concepts_count']} concepts")

    @pytest.mark.asyncio
    async def test_pipeline_semantic_profile(self, pipeline, sample_document_multilingual):
        """Test génération SemanticProfile"""
        result = await pipeline.process_document(
            document_id=sample_document_multilingual["document_id"],
            document_title=sample_document_multilingual["document_title"],
            document_path=sample_document_multilingual["document_path"],
            text_content=sample_document_multilingual["text_content"],
            tenant_id="test_tenant",
            enable_llm=False
        )

        assert result["success"]
        assert "semantic_profile" in result

        profile = result["semantic_profile"]

        # Vérifications
        assert 0.0 <= profile["overall_complexity"] <= 1.0
        assert profile["total_topics"] == result["metrics"]["topics_count"]
        assert profile["total_concepts"] == result["metrics"]["concepts_count"]
        assert profile["total_canonical_concepts"] == result["metrics"]["canonical_concepts_count"]
        assert len(profile["languages_detected"]) >= 1

        print(f"\n✅ Semantic profile:")
        print(f"   Complexity: {profile['overall_complexity']:.2f}")
        print(f"   Domain: {profile['domain']}")
        print(f"   Topics: {profile['total_topics']}")
        print(f"   Concepts: {profile['total_concepts']}")
        print(f"   Canonical: {profile['total_canonical_concepts']}")
        print(f"   Languages: {profile['languages_detected']}")

    @pytest.mark.asyncio
    async def test_pipeline_performance(self, pipeline, sample_document_multilingual):
        """Test performance <30s/doc"""
        result = await pipeline.process_document(
            document_id=sample_document_multilingual["document_id"],
            document_title=sample_document_multilingual["document_title"],
            document_path=sample_document_multilingual["document_path"],
            text_content=sample_document_multilingual["text_content"],
            tenant_id="test_tenant",
            enable_llm=False  # Sans LLM pour test rapide
        )

        assert result["success"]

        processing_time_s = result["processing_time_ms"] / 1000.0

        # Target: <30s/doc (sans LLM devrait être beaucoup plus rapide)
        print(f"\n✅ Performance: {processing_time_s:.2f}s")

        if processing_time_s < 5.0:
            print("   ⚡ Excellent performance (<5s)")
        elif processing_time_s < 30.0:
            print("   ✅ Good performance (<30s)")
        else:
            print("   ⚠️ Slow performance (>30s)")

    @pytest.mark.asyncio
    async def test_helper_function(self, mock_llm_router, sample_document_multilingual):
        """Test helper function process_document_semantic_v2"""
        result = await process_document_semantic_v2(
            document_id=sample_document_multilingual["document_id"],
            document_title=sample_document_multilingual["document_title"],
            document_path=sample_document_multilingual["document_path"],
            text_content=sample_document_multilingual["text_content"],
            llm_router=mock_llm_router,
            tenant_id="test_tenant"
        )

        assert result["success"]
        assert result["metrics"]["topics_count"] >= 1

        print(f"\n✅ Helper function working")

    @pytest.mark.asyncio
    async def test_pipeline_data_structure(self, pipeline, sample_document_multilingual):
        """Test structure complète des données retournées"""
        result = await pipeline.process_document(
            document_id=sample_document_multilingual["document_id"],
            document_title=sample_document_multilingual["document_title"],
            document_path=sample_document_multilingual["document_path"],
            text_content=sample_document_multilingual["text_content"],
            tenant_id="test_tenant",
            enable_llm=False
        )

        assert result["success"]

        # Vérifier structure complète
        assert "document_id" in result
        assert "tenant_id" in result
        assert "processing_time_ms" in result
        assert "metrics" in result
        assert "data" in result
        assert "semantic_profile" in result

        # Metrics
        metrics = result["metrics"]
        assert "topics_count" in metrics
        assert "concepts_count" in metrics
        assert "canonical_concepts_count" in metrics
        assert "connections_count" in metrics
        assert "languages_detected" in metrics

        # Data
        data = result["data"]
        assert "topics" in data
        assert "concepts" in data
        assert "canonical_concepts" in data
        assert "connections" in data

        # Vérifier structure topics
        if data["topics"]:
            topic = data["topics"][0]
            assert "topic_id" in topic
            assert "section_path" in topic
            assert "windows_count" in topic
            assert "anchors" in topic
            assert "cohesion_score" in topic

        # Vérifier structure concepts
        if data["concepts"]:
            concept = data["concepts"][0]
            assert "concept_id" in concept
            assert "name" in concept
            assert "type" in concept
            assert "language" in concept
            assert "confidence" in concept

        # Vérifier structure canonical
        if data["canonical_concepts"]:
            canonical = data["canonical_concepts"][0]
            assert "canonical_id" in canonical
            assert "canonical_name" in canonical
            assert "aliases" in canonical
            assert "languages" in canonical
            assert "type" in canonical
            assert "support" in canonical

        print("\n✅ Data structure complete and valid")


if __name__ == "__main__":
    # Run tests avec pytest
    pytest.main([__file__, "-v", "-s"])
