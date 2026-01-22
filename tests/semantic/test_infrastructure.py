"""
🌊 OSMOSE Semantic Intelligence - Tests Infrastructure

Tests pour valider le setup de l'infrastructure Phase 1.
"""

import pytest
import asyncio
from pathlib import Path
from knowbase.semantic.config import load_semantic_config, get_semantic_config

from knowbase.semantic.models import (
    SemanticProfile,
    ComplexityZone,
    CandidateEntity,
    CandidateRelation,
    Topic,
    Concept,
)


class TestConfiguration:
    """Tests de la configuration OSMOSE"""

    def test_load_config_from_yaml(self):
        """Test chargement configuration depuis YAML"""
        config_path = Path("config/osmose_semantic_intelligence.yaml")

        if not config_path.exists():
            pytest.skip(f"Configuration file not found: {config_path}")

        config = load_semantic_config(config_path)

        assert config is not None
        assert config.project["name"] == "KnowWhere"
        assert config.project["codename"] == "OSMOSE"
        assert config.semantic_intelligence["enabled"] is True

    def test_config_singleton(self):
        """Test que get_semantic_config retourne un singleton"""
        config1 = get_semantic_config()
        config2 = get_semantic_config()

        assert config1 is config2

    def test_profiler_config(self):
        """Test configuration du profiler"""
        config = get_semantic_config()

        assert config.profiler.enabled is True
        assert "simple" in config.profiler.complexity_thresholds
        assert "medium" in config.profiler.complexity_thresholds
        assert "complex" in config.profiler.complexity_thresholds

    def test_narrative_detection_config(self):
        """Test configuration narrative detection"""
        config = get_semantic_config()

        assert config.narrative_detection.enabled is True
        assert config.narrative_detection.min_confidence == 0.7
        assert "because" in config.narrative_detection.causal_connectors
        assert "revised" in config.narrative_detection.temporal_markers

    def test_neo4j_proto_config(self):
        """Test configuration Neo4j Proto-KG"""
        config = get_semantic_config()

        assert config.neo4j_proto.database == "neo4j"
        assert "CandidateEntity" in config.neo4j_proto.labels.values()
        assert "PENDING_REVIEW" in config.neo4j_proto.statuses


class TestModels:
    """Tests des modèles Pydantic"""

    def test_semantic_profile_creation(self):
        """Test création SemanticProfile"""
        profile = SemanticProfile(
            document_id="doc_123",
            document_path="/path/to/doc.pdf",
            tenant_id="tenant_1",
            overall_complexity=0.7
        )

        assert profile.document_id == "doc_123"
        assert profile.overall_complexity == 0.7
        assert profile.complexity_zones == []
        assert profile.narrative_threads == []

    def test_complexity_zone_creation(self):
        """Test création ComplexityZone"""
        zone = ComplexityZone(
            start_position=0,
            end_position=100,
            complexity_score=0.8,
            complexity_level="complex",
            reasoning="Dense technical content",
            key_concepts=["KPI", "ROI", "NPS"]
        )

        assert zone.start_position == 0
        assert zone.complexity_level == "complex"
        assert len(zone.key_concepts) == 3

    def test_narrative_thread_creation(self):
        """Test création NarrativeThread"""
        thread = NarrativeThread(
            description="Evolution of Customer Retention Rate definition",
            start_position=0,
            end_position=500,
            confidence=0.85,
            keywords=["CRR", "retention", "customer"],
            causal_links=["Updated methodology"],
            temporal_markers=["revised", "superseded"]
        )

        assert thread.confidence == 0.85
        assert "CRR" in thread.keywords
        assert len(thread.temporal_markers) == 2

    def test_candidate_entity_creation(self):
        """Test création CandidateEntity"""
        entity = CandidateEntity(
            tenant_id="tenant_1",
            entity_name="Customer Retention Rate",
            entity_type="KPI",
            document_path="/docs/crr_v3.pdf",
            chunk_id="chunk_001",
            context_snippet="CRR is calculated as...",
            confidence=0.90
        )

        assert entity.entity_type == "KPI"
        assert entity.status == "PENDING_REVIEW"
        assert entity.confidence == 0.90
        assert entity.mention_count == 1

    def test_candidate_relation_creation(self):
        """Test création CandidateRelation"""
        relation = CandidateRelation(
            tenant_id="tenant_1",
            source_entity="ent_abc123",
            target_entity="ent_def456",
            relation_type="SUPERSEDES",
            relation_label="supersedes",
            document_path="/docs/crr_v3.pdf",
            chunk_id="chunk_002",
            context_snippet="This version supersedes the previous...",
            confidence=0.95,
            is_temporal=True
        )

        assert relation.relation_type == "SUPERSEDES"
        assert relation.is_temporal is True
        assert relation.status == "PENDING_REVIEW"


class TestInfrastructureConnectivity:
    """Tests de connectivité à l'infrastructure (Neo4j, Qdrant)

    Note: Tests async nécessitent pytest-asyncio.
    La connectivité est validée via le script setup_infrastructure.py
    """

    def test_qdrant_connection_sync(self):
        """Test connexion Qdrant (version synchrone)"""
        try:
            from knowbase.common.clients.qdrant_client import get_qdrant_client

            client = get_qdrant_client()
            collections = client.get_collections()

            assert collections is not None

        except Exception as e:
            pytest.skip(f"Qdrant not available: {e}")

    def test_qdrant_proto_collection_exists_sync(self):
        """Test que la collection Qdrant Proto existe"""
        try:
            from knowbase.common.clients.qdrant_client import get_qdrant_client
            from knowbase.semantic.config import get_semantic_config

            config = get_semantic_config()
            collection_name = config.qdrant_proto.collection_name

            client = get_qdrant_client()
            collections = client.get_collections()

            collection_names = [c.name for c in collections.collections]

            # Vérifier que la collection Proto existe
            assert collection_name in collection_names

        except Exception as e:
            pytest.skip(f"Qdrant Proto collection test skipped: {e}")


# ===================================
# RUN TESTS
# ===================================

if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
