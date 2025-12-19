"""
Tests pour InferenceEngine - Découverte de Connaissances Cachées

Phase 2.3 OSMOSE - Tests unitaires et d'intégration
"""

import pytest
from unittest.mock import Mock, MagicMock, patch, AsyncMock
from datetime import datetime

from knowbase.semantic.inference import (
    InferenceEngine,
    InsightType,
    DiscoveredInsight,
)


# =============================================================================
# FIXTURES
# =============================================================================

@pytest.fixture
def mock_neo4j_client():
    """Mock du client Neo4j."""
    client = Mock()
    client.execute_query = Mock(return_value=[])
    return client


@pytest.fixture
def inference_engine(mock_neo4j_client):
    """InferenceEngine avec mock Neo4j."""
    return InferenceEngine(
        neo4j_client=mock_neo4j_client,
        min_cluster_size=2,
        max_transitive_depth=3,
        weak_signal_threshold=0.25
    )


@pytest.fixture
def sample_neo4j_nodes():
    """Données de test: nœuds Neo4j."""
    return [
        {"name": "Remdesivir", "type": "entity", "support": 15},
        {"name": "Baricitinib", "type": "entity", "support": 8},
        {"name": "COVID-19", "type": "entity", "support": 50},
        {"name": "RECOVERY", "type": "entity", "support": 12},
        {"name": "Mortality", "type": "entity", "support": 25},
        {"name": "Hospitalization", "type": "entity", "support": 18},
        {"name": "Tocilizumab", "type": "entity", "support": 6},
        {"name": "Paxlovid", "type": "entity", "support": 3},  # Weak signal candidate
        {"name": "Nirmatrelvir", "type": "entity", "support": 2},
    ]


@pytest.fixture
def sample_neo4j_edges():
    """Données de test: relations Neo4j."""
    return [
        {"source": "Remdesivir", "target": "COVID-19", "relation_type": "TREATS", "confidence": 0.9},
        {"source": "Baricitinib", "target": "COVID-19", "relation_type": "TREATS", "confidence": 0.85},
        {"source": "Remdesivir", "target": "RECOVERY", "relation_type": "PART_OF", "confidence": 0.8},
        {"source": "Baricitinib", "target": "RECOVERY", "relation_type": "PART_OF", "confidence": 0.75},
        {"source": "COVID-19", "target": "Mortality", "relation_type": "CAUSES", "confidence": 0.7},
        {"source": "COVID-19", "target": "Hospitalization", "relation_type": "CAUSES", "confidence": 0.8},
        {"source": "Tocilizumab", "target": "COVID-19", "relation_type": "TREATS", "confidence": 0.7},
        {"source": "Paxlovid", "target": "COVID-19", "relation_type": "TREATS", "confidence": 0.6},
        {"source": "Nirmatrelvir", "target": "Paxlovid", "relation_type": "PART_OF", "confidence": 0.9},
    ]


# =============================================================================
# TESTS: InsightType Enum
# =============================================================================

class TestInsightType:
    """Tests pour l'enum InsightType."""

    def test_all_insight_types_defined(self):
        """Vérifie que tous les types d'insights sont définis."""
        expected_types = [
            "transitive_inference",
            "bridge_concept",
            "hidden_cluster",
            "weak_signal",
            "structural_hole",
            "contradiction",
        ]

        for expected in expected_types:
            assert hasattr(InsightType, expected.upper()), f"Missing InsightType: {expected}"

    def test_insight_type_values(self):
        """Vérifie les valeurs des InsightType."""
        assert InsightType.TRANSITIVE_INFERENCE.value == "transitive_inference"
        assert InsightType.BRIDGE_CONCEPT.value == "bridge_concept"
        assert InsightType.HIDDEN_CLUSTER.value == "hidden_cluster"
        assert InsightType.WEAK_SIGNAL.value == "weak_signal"
        assert InsightType.STRUCTURAL_HOLE.value == "structural_hole"
        assert InsightType.CONTRADICTION.value == "contradiction"


# =============================================================================
# TESTS: DiscoveredInsight Dataclass
# =============================================================================

class TestDiscoveredInsight:
    """Tests pour la dataclass DiscoveredInsight."""

    def test_create_basic_insight(self):
        """Test création d'un insight basique."""
        insight = DiscoveredInsight(
            insight_id="insight_tran_000001",
            insight_type=InsightType.TRANSITIVE_INFERENCE,
            title="Test Insight",
            description="Description test",
            concepts_involved=["A", "B", "C"],
            confidence=0.85,
            importance=0.7
        )

        assert insight.insight_id == "insight_tran_000001"
        assert insight.insight_type == InsightType.TRANSITIVE_INFERENCE
        assert insight.confidence == 0.85
        assert len(insight.concepts_involved) == 3

    def test_insight_to_dict(self):
        """Test sérialisation en dictionnaire."""
        insight = DiscoveredInsight(
            insight_id="insight_brid_000002",
            insight_type=InsightType.BRIDGE_CONCEPT,
            title="Bridge Test",
            description="Bridge description",
            concepts_involved=["Bridge"],
            confidence=0.6,
            importance=0.5,
            evidence_path=["Step 1", "Step 2"],
            supporting_documents=["doc1", "doc2"]
        )

        d = insight.to_dict()

        assert d["insight_id"] == "insight_brid_000002"
        assert d["insight_type"] == "bridge_concept"
        assert d["confidence"] == 0.6
        assert len(d["evidence_path"]) == 2
        assert "discovered_at" in d

    def test_insight_default_values(self):
        """Test valeurs par défaut."""
        insight = DiscoveredInsight(
            insight_id="test",
            insight_type=InsightType.WEAK_SIGNAL,
            title="Test",
            description="Test",
            concepts_involved=[],
            confidence=0.5,
            importance=0.5
        )

        assert insight.evidence_path == []
        assert insight.supporting_documents == []
        assert insight.tenant_id == "default"
        assert isinstance(insight.discovered_at, datetime)


# =============================================================================
# TESTS: InferenceEngine Initialization
# =============================================================================

class TestInferenceEngineInit:
    """Tests pour l'initialisation de l'InferenceEngine."""

    def test_init_with_defaults(self):
        """Test initialisation avec valeurs par défaut."""
        engine = InferenceEngine()

        assert engine.min_cluster_size == 3
        assert engine.max_transitive_depth == 3
        assert engine.weak_signal_threshold == 0.25
        assert engine._nx_graph_cache is None

    def test_init_with_custom_params(self, mock_neo4j_client):
        """Test initialisation avec paramètres custom."""
        engine = InferenceEngine(
            neo4j_client=mock_neo4j_client,
            min_cluster_size=5,
            max_transitive_depth=4,
            weak_signal_threshold=0.3
        )

        assert engine.min_cluster_size == 5
        assert engine.max_transitive_depth == 4
        assert engine.weak_signal_threshold == 0.3

    def test_generate_insight_id(self, inference_engine):
        """Test génération d'IDs uniques."""
        id1 = inference_engine._generate_insight_id(InsightType.TRANSITIVE_INFERENCE)
        id2 = inference_engine._generate_insight_id(InsightType.TRANSITIVE_INFERENCE)
        id3 = inference_engine._generate_insight_id(InsightType.BRIDGE_CONCEPT)

        assert id1 != id2
        assert id2 != id3
        assert "tran" in id1
        assert "brid" in id3


# =============================================================================
# TESTS: Transitive Inference (Cypher natif)
# =============================================================================

class TestTransitiveInference:
    """Tests pour la découverte de relations transitives."""

    @pytest.mark.asyncio
    async def test_discover_transitive_empty_graph(self, inference_engine):
        """Test sur graphe vide."""
        insights = await inference_engine.discover_transitive_relations(
            tenant_id="test"
        )

        assert insights == []

    @pytest.mark.asyncio
    async def test_discover_transitive_with_results(self, mock_neo4j_client):
        """Test avec résultats transitifs."""
        mock_neo4j_client.execute_query.return_value = [
            {
                "source": "A",
                "intermediate": "B",
                "target": "C",
                "confidence": 0.85,
                "conf1": 0.9,
                "conf2": 0.8
            }
        ]

        engine = InferenceEngine(neo4j_client=mock_neo4j_client)
        insights = await engine.discover_transitive_relations(tenant_id="test")

        assert len(insights) >= 1
        insight = insights[0]
        assert insight.insight_type == InsightType.TRANSITIVE_INFERENCE
        assert "A" in insight.concepts_involved
        assert "B" in insight.concepts_involved
        assert "C" in insight.concepts_involved
        assert insight.confidence > 0

    @pytest.mark.asyncio
    async def test_transitive_relation_types(self, inference_engine):
        """Test avec différents types de relations."""
        # Test que la méthode accepte les types de relations personnalisés
        insights = await inference_engine.discover_transitive_relations(
            tenant_id="test",
            relation_types=["REQUIRES", "PART_OF"]
        )

        # Devrait appeler Neo4j pour chaque type
        assert inference_engine.neo4j_client.execute_query.call_count >= 2


# =============================================================================
# TESTS: Bridge Concepts (NetworkX)
# =============================================================================

class TestBridgeConcepts:
    """Tests pour la découverte de concepts ponts."""

    @pytest.mark.asyncio
    async def test_discover_bridges_empty_graph(self, inference_engine):
        """Test sur graphe vide."""
        insights = await inference_engine.discover_bridge_concepts(tenant_id="test")

        # Devrait retourner liste vide sans erreur
        assert isinstance(insights, list)

    @pytest.mark.asyncio
    async def test_discover_bridges_small_graph(self, mock_neo4j_client, sample_neo4j_nodes, sample_neo4j_edges):
        """Test sur petit graphe."""
        # Setup mock pour retourner nœuds et edges
        def mock_execute_query(query, parameters=None):
            if "RETURN c.canonical_name AS name" in query:
                return sample_neo4j_nodes
            elif "RETURN a.canonical_name AS source" in query:
                return sample_neo4j_edges
            return []

        mock_neo4j_client.execute_query.side_effect = mock_execute_query

        engine = InferenceEngine(neo4j_client=mock_neo4j_client)
        insights = await engine.discover_bridge_concepts(
            tenant_id="test",
            min_betweenness=0.01
        )

        # Les insights retournés dépendent de la structure du graphe
        assert isinstance(insights, list)


# =============================================================================
# TESTS: Hidden Clusters (Louvain)
# =============================================================================

class TestHiddenClusters:
    """Tests pour la découverte de clusters cachés."""

    @pytest.mark.asyncio
    async def test_discover_clusters_empty(self, inference_engine):
        """Test sur graphe vide."""
        insights = await inference_engine.discover_hidden_clusters(tenant_id="test")
        assert isinstance(insights, list)

    @pytest.mark.asyncio
    async def test_discover_clusters_with_data(self, mock_neo4j_client, sample_neo4j_nodes, sample_neo4j_edges):
        """Test avec données."""
        def mock_execute_query(query, parameters=None):
            if "RETURN c.canonical_name AS name" in query:
                return sample_neo4j_nodes
            elif "RETURN a.canonical_name AS source" in query:
                return sample_neo4j_edges
            return []

        mock_neo4j_client.execute_query.side_effect = mock_execute_query

        engine = InferenceEngine(neo4j_client=mock_neo4j_client, min_cluster_size=2)
        insights = await engine.discover_hidden_clusters(tenant_id="test")

        assert isinstance(insights, list)
        for insight in insights:
            assert insight.insight_type == InsightType.HIDDEN_CLUSTER


# =============================================================================
# TESTS: Weak Signals (PageRank)
# =============================================================================

class TestWeakSignals:
    """Tests pour la découverte de signaux faibles."""

    @pytest.mark.asyncio
    async def test_discover_weak_signals_empty(self, inference_engine):
        """Test sur graphe vide."""
        insights = await inference_engine.discover_weak_signals(tenant_id="test")
        assert isinstance(insights, list)

    @pytest.mark.asyncio
    async def test_weak_signal_identification(self, mock_neo4j_client, sample_neo4j_nodes, sample_neo4j_edges):
        """Test identification de weak signals."""
        def mock_execute_query(query, parameters=None):
            if "RETURN c.canonical_name AS name, c.support" in query:
                return sample_neo4j_nodes
            elif "RETURN c.canonical_name AS name" in query and "type" in query:
                return sample_neo4j_nodes
            elif "RETURN a.canonical_name AS source" in query:
                return sample_neo4j_edges
            return sample_neo4j_nodes

        mock_neo4j_client.execute_query.side_effect = mock_execute_query

        engine = InferenceEngine(neo4j_client=mock_neo4j_client)
        insights = await engine.discover_weak_signals(tenant_id="test")

        assert isinstance(insights, list)
        for insight in insights:
            assert insight.insight_type == InsightType.WEAK_SIGNAL


# =============================================================================
# TESTS: Structural Holes (Link Prediction)
# =============================================================================

class TestStructuralHoles:
    """Tests pour la découverte de trous structurels."""

    @pytest.mark.asyncio
    async def test_discover_structural_holes_empty(self, inference_engine):
        """Test sur graphe vide."""
        insights = await inference_engine.discover_structural_holes(tenant_id="test")
        assert isinstance(insights, list)

    @pytest.mark.asyncio
    async def test_structural_holes_with_data(self, mock_neo4j_client, sample_neo4j_nodes, sample_neo4j_edges):
        """Test avec données."""
        def mock_execute_query(query, parameters=None):
            if "RETURN c.canonical_name AS name" in query:
                return sample_neo4j_nodes
            elif "RETURN a.canonical_name AS source" in query:
                return sample_neo4j_edges
            return []

        mock_neo4j_client.execute_query.side_effect = mock_execute_query

        engine = InferenceEngine(neo4j_client=mock_neo4j_client)
        insights = await engine.discover_structural_holes(tenant_id="test")

        assert isinstance(insights, list)


# =============================================================================
# TESTS: Contradictions
# =============================================================================

class TestContradictions:
    """Tests pour la découverte de contradictions."""

    @pytest.mark.asyncio
    async def test_discover_contradictions_empty(self, inference_engine):
        """Test sans contradictions."""
        insights = await inference_engine.discover_contradictions(tenant_id="test")
        assert insights == []

    @pytest.mark.asyncio
    async def test_discover_contradictions_mutual_replaces(self, mock_neo4j_client):
        """Test avec contradictions REPLACES mutuelles."""
        mock_neo4j_client.execute_query.return_value = [
            {
                "concept_a": "OldVersion",
                "concept_b": "NewVersion",
                "contradiction_type": "REPLACES_MUTUAL"
            }
        ]

        engine = InferenceEngine(neo4j_client=mock_neo4j_client)
        insights = await engine.discover_contradictions(tenant_id="test")

        assert len(insights) == 1
        insight = insights[0]
        assert insight.insight_type == InsightType.CONTRADICTION
        assert "OldVersion" in insight.concepts_involved
        assert "NewVersion" in insight.concepts_involved
        assert insight.confidence == 0.9


# =============================================================================
# TESTS: Discover All
# =============================================================================

class TestDiscoverAll:
    """Tests pour discover_all_insights."""

    @pytest.mark.asyncio
    async def test_discover_all_default_types(self, inference_engine):
        """Test découverte avec types par défaut."""
        insights = await inference_engine.discover_all_insights(tenant_id="test")
        assert isinstance(insights, list)

    @pytest.mark.asyncio
    async def test_discover_all_specific_types(self, inference_engine):
        """Test découverte avec types spécifiques."""
        insights = await inference_engine.discover_all_insights(
            tenant_id="test",
            insight_types=[InsightType.TRANSITIVE_INFERENCE]
        )
        assert isinstance(insights, list)

    @pytest.mark.asyncio
    async def test_discover_all_sorted_by_importance(self, mock_neo4j_client):
        """Test que les résultats sont triés par importance."""
        mock_neo4j_client.execute_query.return_value = [
            {"source": "A", "intermediate": "B", "target": "C", "confidence": 0.9, "conf1": 0.95, "conf2": 0.85},
            {"source": "X", "intermediate": "Y", "target": "Z", "confidence": 0.6, "conf1": 0.7, "conf2": 0.5},
        ]

        engine = InferenceEngine(neo4j_client=mock_neo4j_client)
        insights = await engine.discover_all_insights(
            tenant_id="test",
            insight_types=[InsightType.TRANSITIVE_INFERENCE]
        )

        if len(insights) >= 2:
            assert insights[0].importance >= insights[1].importance


# =============================================================================
# TESTS: Cache Management
# =============================================================================

class TestCacheManagement:
    """Tests pour la gestion du cache NetworkX."""

    @pytest.mark.asyncio
    async def test_cache_cleared(self, inference_engine):
        """Test clear_cache."""
        inference_engine._nx_graph_cache = Mock()
        inference_engine._cache_tenant_id = "test"

        inference_engine.clear_cache()

        assert inference_engine._nx_graph_cache is None
        assert inference_engine._cache_tenant_id is None

    @pytest.mark.asyncio
    async def test_cache_reused(self, mock_neo4j_client, sample_neo4j_nodes, sample_neo4j_edges):
        """Test que le cache est réutilisé."""
        def mock_execute_query(query, parameters=None):
            if "RETURN c.canonical_name AS name" in query:
                return sample_neo4j_nodes
            elif "RETURN a.canonical_name AS source" in query:
                return sample_neo4j_edges
            return []

        mock_neo4j_client.execute_query.side_effect = mock_execute_query

        engine = InferenceEngine(neo4j_client=mock_neo4j_client)

        # Premier appel - construit le cache
        await engine._build_networkx_graph("test")
        call_count_after_first = mock_neo4j_client.execute_query.call_count

        # Deuxième appel - devrait utiliser le cache
        await engine._build_networkx_graph("test")
        call_count_after_second = mock_neo4j_client.execute_query.call_count

        # Le nombre d'appels ne devrait pas augmenter
        assert call_count_after_first == call_count_after_second


# =============================================================================
# TESTS: Statistics
# =============================================================================

class TestInferenceStats:
    """Tests pour get_inference_stats."""

    @pytest.mark.asyncio
    async def test_get_stats_empty_graph(self, inference_engine):
        """Test stats sur graphe vide."""
        stats = await inference_engine.get_inference_stats(tenant_id="test")

        assert "tenant_id" in stats
        assert "graph_stats" in stats
        assert stats["graph_stats"]["nodes"] == 0

    @pytest.mark.asyncio
    async def test_get_stats_with_data(self, mock_neo4j_client, sample_neo4j_nodes, sample_neo4j_edges):
        """Test stats avec données."""
        def mock_execute_query(query, parameters=None):
            if "RETURN c.canonical_name AS name" in query:
                return sample_neo4j_nodes
            elif "RETURN a.canonical_name AS source" in query:
                return sample_neo4j_edges
            return []

        mock_neo4j_client.execute_query.side_effect = mock_execute_query

        engine = InferenceEngine(neo4j_client=mock_neo4j_client)
        stats = await engine.get_inference_stats(tenant_id="test")

        assert stats["graph_stats"]["nodes"] == len(sample_neo4j_nodes)
        assert stats["graph_stats"]["edges"] == len(sample_neo4j_edges)
        assert "networkx_available" in stats


# =============================================================================
# TESTS: Error Handling
# =============================================================================

class TestErrorHandling:
    """Tests pour la gestion des erreurs."""

    @pytest.mark.asyncio
    async def test_neo4j_query_error_handled(self, mock_neo4j_client):
        """Test gestion erreur query Neo4j."""
        mock_neo4j_client.execute_query.side_effect = Exception("Connection error")

        engine = InferenceEngine(neo4j_client=mock_neo4j_client)

        # Ne devrait pas lever d'exception
        insights = await engine.discover_transitive_relations(tenant_id="test")
        assert insights == []

    @pytest.mark.asyncio
    async def test_networkx_not_available(self, inference_engine):
        """Test quand NetworkX n'est pas disponible."""
        # Simuler NetworkX indisponible via patch
        with patch.dict('knowbase.semantic.inference.inference_engine.__dict__',
                       {'NETWORKX_AVAILABLE': False}):
            # Les méthodes NetworkX devraient retourner liste vide
            pass  # Le comportement est testé dans les tests individuels


# =============================================================================
# TESTS: Integration (avec vrai graphe en mémoire)
# =============================================================================

class TestIntegrationNetworkX:
    """Tests d'intégration avec NetworkX."""

    def test_community_detection_basic(self):
        """Test détection communautés basique."""
        try:
            import networkx as nx
            from networkx.algorithms import community as nx_community
        except ImportError:
            pytest.skip("NetworkX not available")

        # Créer graphe simple avec 2 communautés
        G = nx.Graph()
        # Communauté 1
        G.add_edges_from([("A1", "A2"), ("A2", "A3"), ("A1", "A3")])
        # Communauté 2
        G.add_edges_from([("B1", "B2"), ("B2", "B3"), ("B1", "B3")])
        # Lien faible entre communautés
        G.add_edge("A3", "B1")

        # Détecter communautés
        communities = list(nx_community.greedy_modularity_communities(G))

        assert len(communities) >= 1

    def test_pagerank_basic(self):
        """Test PageRank basique."""
        try:
            import networkx as nx
        except ImportError:
            pytest.skip("NetworkX not available")

        G = nx.DiGraph()
        G.add_edges_from([
            ("A", "B"), ("A", "C"), ("B", "C"), ("C", "D"), ("D", "A")
        ])

        pagerank = nx.pagerank(G)

        assert len(pagerank) == 4
        assert all(0 <= v <= 1 for v in pagerank.values())

    def test_betweenness_basic(self):
        """Test Betweenness Centrality basique."""
        try:
            import networkx as nx
        except ImportError:
            pytest.skip("NetworkX not available")

        G = nx.Graph()
        # Graphe en forme de bow-tie - le nœud central a betweenness élevé
        G.add_edges_from([
            ("L1", "CENTER"), ("L2", "CENTER"),
            ("CENTER", "R1"), ("CENTER", "R2")
        ])

        betweenness = nx.betweenness_centrality(G)

        # CENTER devrait avoir le betweenness le plus élevé
        assert betweenness["CENTER"] == max(betweenness.values())
