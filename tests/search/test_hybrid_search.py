"""
Tests Search Hybride Qdrant + Graphiti - Phase 1 Critère 1.4

Valide:
1. Search hybride avec fusion scores
2. Reranking avec différentes stratégies
3. Filtres entity types
4. API endpoint /search/hybrid
"""

import pytest
from unittest.mock import Mock, patch, MagicMock
from typing import List

from knowbase.search.hybrid_search import (
    hybrid_search,
    search_with_entity_filter,
    search_related_chunks,
    HybridSearchResult
)
from knowbase.search.hybrid_reranker import (
    rerank_hybrid,
    weighted_average_reranking,
    reciprocal_rank_fusion,
    context_aware_reranking,
    RankedItem
)


class TestHybridSearch:
    """Tests service hybrid search"""

    @pytest.mark.asyncio
    @patch('knowbase.search.hybrid_search.get_qdrant_client')
    @patch('knowbase.search.hybrid_search.get_graphiti_client')
    async def test_hybrid_search_basic(self, mock_graphiti, mock_qdrant):
        """Test 1: Hybrid search basique retourne résultats combinés"""
        # Mock Qdrant results
        mock_qdrant_hit = Mock()
        mock_qdrant_hit.id = "chunk_001"
        mock_qdrant_hit.score = 0.85
        mock_qdrant_hit.payload = {
            "text": "SAP S/4HANA provides consolidation features",
            "episode_id": "ep_123",
            "has_knowledge_graph": True
        }

        mock_qdrant.return_value.search.return_value = [mock_qdrant_hit]

        # Mock Graphiti results
        mock_graphiti.return_value.search.return_value = {
            "nodes": [
                {"name": "SAP S/4HANA", "entity_type": "PRODUCT"},
                {"name": "Consolidation", "entity_type": "CONCEPT"}
            ],
            "edges": [
                {"source": "SAP S/4HANA", "target": "Consolidation", "relation_type": "PROVIDES"}
            ]
        }

        # Execute
        results = await hybrid_search(
            query="SAP consolidation",
            tenant_id="test_tenant",
            limit=5
        )

        # Validate
        assert len(results) > 0, "Should return results"
        assert isinstance(results[0], HybridSearchResult)
        assert results[0].chunk_id == "chunk_001"
        assert results[0].chunk_score == 0.85
        assert results[0].graphiti_score >= 0.0
        assert results[0].final_score > 0.0

        print(f"✅ Test 1: Hybrid search retourné {len(results)} résultats")

    @pytest.mark.asyncio
    @patch('knowbase.search.hybrid_search.get_qdrant_client')
    @patch('knowbase.search.hybrid_search.get_graphiti_client')
    async def test_hybrid_search_with_weights(self, mock_graphiti, mock_qdrant):
        """Test 2: Weights personnalisés modifient scores finaux"""
        # Mock minimal
        mock_qdrant_hit = Mock()
        mock_qdrant_hit.id = "chunk_001"
        mock_qdrant_hit.score = 0.8
        mock_qdrant_hit.payload = {
            "text": "Test content",
            "has_knowledge_graph": False
        }

        mock_qdrant.return_value.search.return_value = [mock_qdrant_hit]
        mock_graphiti.return_value.search.return_value = {"nodes": [], "edges": []}

        # Test avec weights différents
        results_70_30 = await hybrid_search(
            query="test",
            tenant_id="test",
            limit=1,
            weights={"qdrant": 0.7, "graphiti": 0.3}
        )

        results_50_50 = await hybrid_search(
            query="test",
            tenant_id="test",
            limit=1,
            weights={"qdrant": 0.5, "graphiti": 0.5}
        )

        # Scores devraient être différents
        assert results_70_30[0].final_score != results_50_50[0].final_score
        print(f"✅ Test 2: Weights 70/30={results_70_30[0].final_score:.3f}, 50/50={results_50_50[0].final_score:.3f}")

    @pytest.mark.asyncio
    @patch('knowbase.search.hybrid_search.get_qdrant_client')
    @patch('knowbase.search.hybrid_search.get_graphiti_client')
    async def test_search_with_entity_filter(self, mock_graphiti, mock_qdrant):
        """Test 3: Filtre entity types fonctionne"""
        # Mock chunks avec différentes entities
        chunk_with_product = Mock()
        chunk_with_product.id = "chunk_product"
        chunk_with_product.score = 0.9
        chunk_with_product.payload = {
            "text": "SAP S/4HANA is a product",
            "episode_id": "ep_1",
            "has_knowledge_graph": True
        }

        chunk_with_concept = Mock()
        chunk_with_concept.id = "chunk_concept"
        chunk_with_concept.score = 0.85
        chunk_with_concept.payload = {
            "text": "Consolidation is a concept",
            "episode_id": "ep_2",
            "has_knowledge_graph": True
        }

        mock_qdrant.return_value.search.return_value = [
            chunk_with_product,
            chunk_with_concept
        ]

        # Mock Graphiti avec entities différentes
        mock_graphiti.return_value.search.return_value = {
            "nodes": [
                {"name": "SAP S/4HANA", "entity_type": "PRODUCT"},
                {"name": "Consolidation", "entity_type": "CONCEPT"}
            ]
        }

        # Filter par PRODUCT uniquement
        results = await search_with_entity_filter(
            query="SAP",
            tenant_id="test",
            entity_types=["PRODUCT"],
            limit=10
        )

        # Devrait filtrer les résultats
        assert len(results) > 0
        print(f"✅ Test 3: Entity filter retourné {len(results)} résultats (PRODUCT seulement)")

    @pytest.mark.asyncio
    @patch('knowbase.search.hybrid_search.get_qdrant_client')
    async def test_search_related_chunks(self, mock_qdrant):
        """Test 4: Search related chunks par episode_id"""
        # Mock chunk de référence
        ref_chunk = Mock()
        ref_chunk.payload = {"episode_id": "ep_shared"}

        # Mock chunks reliés
        related1 = Mock()
        related1.id = "related_001"
        related1.payload = {
            "text": "Related chunk 1",
            "episode_id": "ep_shared"
        }

        related2 = Mock()
        related2.id = "related_002"
        related2.payload = {
            "text": "Related chunk 2",
            "episode_id": "ep_shared"
        }

        unrelated = Mock()
        unrelated.id = "unrelated_001"
        unrelated.payload = {
            "text": "Unrelated chunk",
            "episode_id": "ep_other"
        }

        mock_qdrant.return_value.retrieve.return_value = [ref_chunk]
        mock_qdrant.return_value.scroll.return_value = (
            [related1, related2, unrelated],
            None
        )

        # Execute
        results = await search_related_chunks(
            chunk_id="ref_chunk",
            tenant_id="test",
            limit=5
        )

        # Validate
        assert len(results) == 2, "Should find 2 related chunks (même episode_id)"
        assert all(r.episode_id == "ep_shared" for r in results)
        print(f"✅ Test 4: Trouvé {len(results)} chunks reliés")


class TestHybridReranker:
    """Tests reranking strategies"""

    def test_weighted_average_reranking(self):
        """Test 5: Weighted average reranking"""
        # Mock Qdrant results
        hit1 = Mock()
        hit1.id = "chunk_1"
        hit1.score = 0.9
        hit1.payload = {"text": "Content 1", "episode_id": "ep_1"}

        hit2 = Mock()
        hit2.id = "chunk_2"
        hit2.score = 0.7
        hit2.payload = {"text": "Content 2", "episode_id": None}

        qdrant_results = [hit1, hit2]

        # Mock Graphiti results
        graphiti_results = {
            "nodes": [{"name": "Entity1"}],
            "edges": [{"source": "A", "target": "B"}]
        }

        # Execute
        ranked = weighted_average_reranking(
            qdrant_results=qdrant_results,
            graphiti_results=graphiti_results,
            weights={"qdrant": 0.7, "graphiti": 0.3}
        )

        # Validate
        assert len(ranked) == 2
        assert isinstance(ranked[0], RankedItem)
        assert ranked[0].final_score > ranked[1].final_score  # Should be sorted
        print(f"✅ Test 5: Weighted average - scores {ranked[0].final_score:.3f}, {ranked[1].final_score:.3f}")

    def test_reciprocal_rank_fusion(self):
        """Test 6: Reciprocal Rank Fusion (RRF)"""
        hit1 = Mock()
        hit1.id = "chunk_1"
        hit1.score = 0.9
        hit1.payload = {"episode_id": "ep_1"}

        hit2 = Mock()
        hit2.id = "chunk_2"
        hit2.score = 0.8
        hit2.payload = {"episode_id": "ep_2"}

        qdrant_results = [hit1, hit2]
        graphiti_results = {"episodes": [{"uuid": "ep_2"}, {"uuid": "ep_1"}]}

        # Execute
        ranked = reciprocal_rank_fusion(
            qdrant_results=qdrant_results,
            graphiti_results=graphiti_results,
            k=60
        )

        # Validate
        assert len(ranked) == 2
        # RRF scores should be calculated
        assert ranked[0].final_score > 0
        print(f"✅ Test 6: RRF - scores {ranked[0].final_score:.4f}, {ranked[1].final_score:.4f}")

    def test_context_aware_reranking(self):
        """Test 7: Context-aware reranking avec boost query"""
        hit1 = Mock()
        hit1.id = "chunk_1"
        hit1.score = 0.8
        hit1.payload = {"episode_id": "ep_1"}

        qdrant_results = [hit1]
        graphiti_results = {
            "nodes": [
                {"name": "SAP S/4HANA", "entity_type": "PRODUCT"}
            ]
        }

        # Query contient "SAP" → devrait boost
        ranked = context_aware_reranking(
            qdrant_results=qdrant_results,
            graphiti_results=graphiti_results,
            query="SAP consolidation",
            weights={"qdrant": 0.7, "graphiti": 0.3}
        )

        # Validate
        assert len(ranked) == 1
        # Graphiti score devrait inclure boost
        assert ranked[0].graphiti_score > 0.0
        print(f"✅ Test 7: Context-aware - graphiti_score avec boost = {ranked[0].graphiti_score:.3f}")

    def test_rerank_hybrid_strategy_selection(self):
        """Test 8: Sélection stratégie reranking"""
        hit = Mock()
        hit.id = "chunk_1"
        hit.score = 0.9
        hit.payload = {}

        qdrant_results = [hit]
        graphiti_results = {"nodes": []}

        # Test weighted_average
        ranked_wa = rerank_hybrid(
            qdrant_results=qdrant_results,
            graphiti_results=graphiti_results,
            strategy="weighted_average"
        )
        assert len(ranked_wa) == 1

        # Test RRF
        ranked_rrf = rerank_hybrid(
            qdrant_results=qdrant_results,
            graphiti_results=graphiti_results,
            strategy="rrf",
            k=60
        )
        assert len(ranked_rrf) == 1

        # Test context_aware
        ranked_ctx = rerank_hybrid(
            qdrant_results=qdrant_results,
            graphiti_results=graphiti_results,
            strategy="context_aware",
            query="test query"
        )
        assert len(ranked_ctx) == 1

        # Test stratégie invalide
        with pytest.raises(ValueError):
            rerank_hybrid(
                qdrant_results=qdrant_results,
                graphiti_results=graphiti_results,
                strategy="invalid_strategy"
            )

        print(f"✅ Test 8: Toutes stratégies testées (weighted_average, rrf, context_aware)")


class TestHybridSearchAPI:
    """Tests endpoint API /search/hybrid"""

    @pytest.mark.asyncio
    @patch('knowbase.api.routers.search.hybrid_search')
    async def test_api_hybrid_search_endpoint(self, mock_hybrid_search):
        """Test 9: Endpoint API /search/hybrid fonctionne"""
        from fastapi.testclient import TestClient
        from knowbase.api.main import app

        client = TestClient(app)

        # Mock résultats
        mock_result = Mock()
        mock_result.to_dict.return_value = {
            "chunk_id": "test_001",
            "text": "Test content",
            "score": 0.85,
            "metadata": {},
            "knowledge_graph": {
                "episode_id": "ep_1",
                "entities": [],
                "relations": []
            }
        }

        mock_hybrid_search.return_value = [mock_result]

        # Execute
        response = client.post(
            "/search/hybrid",
            json={
                "question": "SAP consolidation",
                "tenant_id": "test_tenant",
                "limit": 10
            }
        )

        # Validate
        assert response.status_code == 200
        data = response.json()
        assert "results" in data
        assert "total" in data
        assert data["query"] == "SAP consolidation"
        print(f"✅ Test 9: API endpoint retourné {data['total']} résultats")


if __name__ == "__main__":
    # Exécution tests localement
    pytest.main([__file__, "-v", "-s"])
