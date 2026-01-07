"""
ADR_GRAPH_FIRST_ARCHITECTURE Phase D - Tests Performance

Benchmark performance du runtime Graph-First.
Target: < 500ms total pour une requête complète.

Décomposition attendue:
- Extraction concepts: ~50-100ms
- Pathfinding GDS: ~50-100ms
- Filtrage Qdrant: ~50-100ms
- Synthèse LLM: ~200-300ms (exclu de ce test)
"""

import pytest
import asyncio
import time
from typing import List, Dict, Any
from unittest.mock import Mock, patch, AsyncMock
from dataclasses import dataclass

from knowbase.api.services.graph_first_search import (
    GraphFirstSearchService,
    GraphFirstPlan,
    SearchMode,
    get_graph_first_service,
)


# Configuration des seuils de performance
PERFORMANCE_THRESHOLDS = {
    "build_search_plan_ms": 300,      # Plan complet sans Qdrant
    "concept_extraction_ms": 150,      # Extraction concepts seule
    "pathfinding_ms": 150,             # Pathfinding seul
    "qdrant_filtered_ms": 200,         # Recherche Qdrant filtrée
    "total_graph_first_ms": 500,       # Total sans synthèse LLM
}


@dataclass
class PerformanceResult:
    """Résultat d'un benchmark de performance."""
    operation: str
    duration_ms: float
    threshold_ms: float
    passed: bool
    details: Dict[str, Any] = None

    def __str__(self):
        status = "✅" if self.passed else "❌"
        return f"{status} {self.operation}: {self.duration_ms:.1f}ms (threshold: {self.threshold_ms}ms)"


class TestPerformanceBenchmarks:
    """
    Benchmarks de performance pour le runtime Graph-First.

    Ces tests vérifient que chaque composant respecte son budget temps.
    """

    @pytest.fixture
    def mock_neo4j_fast(self):
        """Mock Neo4j avec réponses rapides."""
        client = Mock()
        # Simuler des réponses quasi-instantanées
        client.execute_query = Mock(return_value=[])
        return client

    @pytest.fixture
    def service_with_mocks(self, mock_neo4j_fast):
        """Service avec mocks rapides pour isoler les composants."""
        svc = GraphFirstSearchService(tenant_id="test")
        svc._neo4j_client = mock_neo4j_fast
        return svc

    @pytest.mark.asyncio
    async def test_build_search_plan_performance(self, service_with_mocks, mock_neo4j_fast):
        """
        Test: build_search_plan() < 300ms

        Ce test mesure le temps total pour construire un plan de recherche,
        incluant extraction de concepts et pathfinding.
        """
        # Setup: Mock concept extraction rapide
        with patch.object(
            service_with_mocks.concept_service,
            'extract_concepts_from_query_v2',
            new_callable=AsyncMock
        ) as mock_extract:
            mock_extract.return_value = {
                "names": ["ConceptA", "ConceptB"],
                "ids": ["cc_a", "cc_b"],
                "semantic_status": None,
                "details": {},
            }

            # Mock pathfinding rapide
            mock_neo4j_fast.execute_query.side_effect = [
                [{  # Path trouvé
                    "node_names": ["ConceptA", "ConceptB"],
                    "node_ids": ["cc_a", "cc_b"],
                    "rel_types": ["REQUIRES"],
                    "path_length": 1,
                    "path_confidence": 0.85,
                }],
                [{"context_id": "sec:doc1:h1", "salience": 0.9}],  # Evidence
            ]

            # Mesurer
            start = time.perf_counter()
            plan = await service_with_mocks.build_search_plan(
                "Test query for performance"
            )
            duration_ms = (time.perf_counter() - start) * 1000

            # Vérifier
            threshold = PERFORMANCE_THRESHOLDS["build_search_plan_ms"]
            result = PerformanceResult(
                operation="build_search_plan",
                duration_ms=duration_ms,
                threshold_ms=threshold,
                passed=duration_ms < threshold,
                details={"mode": plan.mode.value}
            )
            print(result)

            assert result.passed, f"build_search_plan took {duration_ms:.1f}ms > {threshold}ms"

    @pytest.mark.asyncio
    async def test_plan_reports_processing_time(self, service_with_mocks, mock_neo4j_fast):
        """
        Test: Le plan retourne son temps de traitement.

        Le GraphFirstPlan doit inclure processing_time_ms pour observabilité.
        """
        with patch.object(
            service_with_mocks.concept_service,
            'extract_concepts_from_query_v2',
            new_callable=AsyncMock
        ) as mock_extract:
            mock_extract.return_value = {
                "names": [],
                "ids": [],
                "semantic_status": None,
                "details": {},
            }

            plan = await service_with_mocks.build_search_plan("Query")

            # Le plan doit reporter son temps de traitement
            assert plan.processing_time_ms > 0
            assert plan.processing_time_ms < PERFORMANCE_THRESHOLDS["build_search_plan_ms"]


class TestPathfindingPerformance:
    """Tests de performance spécifiques au pathfinding."""

    @pytest.fixture
    def service(self):
        svc = GraphFirstSearchService(tenant_id="test")
        svc._neo4j_client = Mock()
        return svc

    @pytest.mark.asyncio
    async def test_cypher_pathfinding_performance(self, service):
        """
        Test: Pathfinding Cypher < 150ms pour une paire de concepts.
        """
        # Mock réponse rapide
        service._neo4j_client.execute_query.return_value = [{
            "node_names": ["A", "B", "C"],
            "node_ids": ["cc_a", "cc_b", "cc_c"],
            "rel_types": ["R1", "R2"],
            "path_length": 2,
            "path_confidence": 0.8,
        }]

        start = time.perf_counter()
        paths = await service._cypher_all_paths("cc_a", "cc_c")
        duration_ms = (time.perf_counter() - start) * 1000

        threshold = PERFORMANCE_THRESHOLDS["pathfinding_ms"]
        result = PerformanceResult(
            operation="cypher_pathfinding",
            duration_ms=duration_ms,
            threshold_ms=threshold,
            passed=duration_ms < threshold,
        )
        print(result)

        assert result.passed

    @pytest.mark.asyncio
    async def test_evidence_collection_performance(self, service):
        """
        Test: Collecte evidence < 100ms.
        """
        service._neo4j_client.execute_query.return_value = [
            {"context_id": f"sec:doc{i}:hash", "salience": 0.9 - i*0.1}
            for i in range(10)
        ]

        start = time.perf_counter()
        evidence = await service._collect_path_evidence(["cc_a", "cc_b", "cc_c"])
        duration_ms = (time.perf_counter() - start) * 1000

        threshold = 100  # 100ms
        assert duration_ms < threshold, f"Evidence collection took {duration_ms:.1f}ms"


class TestScalabilityBenchmarks:
    """Tests de scalabilité avec différentes tailles de données."""

    @pytest.fixture
    def service(self):
        svc = GraphFirstSearchService(tenant_id="test")
        svc._neo4j_client = Mock()
        return svc

    @pytest.mark.asyncio
    async def test_performance_with_many_concepts(self, service):
        """
        Test: Performance avec 10 concepts seeds (max typique).
        """
        with patch.object(
            service.concept_service,
            'extract_concepts_from_query_v2',
            new_callable=AsyncMock
        ) as mock_extract:
            # 10 concepts = jusqu'à 45 paires à explorer
            mock_extract.return_value = {
                "names": [f"Concept{i}" for i in range(10)],
                "ids": [f"cc_{i}" for i in range(10)],
                "semantic_status": None,
                "details": {},
            }

            # Mock pathfinding: pas de paths (fallback rapide)
            service._neo4j_client.execute_query.return_value = []

            start = time.perf_counter()
            plan = await service.build_search_plan("Complex query with many concepts")
            duration_ms = (time.perf_counter() - start) * 1000

            # Même avec 10 concepts, doit rester < 500ms
            threshold = PERFORMANCE_THRESHOLDS["total_graph_first_ms"]
            assert duration_ms < threshold, \
                f"10 concepts took {duration_ms:.1f}ms > {threshold}ms"

    @pytest.mark.asyncio
    async def test_performance_with_many_paths(self, service):
        """
        Test: Performance avec plusieurs chemins trouvés.
        """
        with patch.object(
            service.concept_service,
            'extract_concepts_from_query_v2',
            new_callable=AsyncMock
        ) as mock_extract:
            mock_extract.return_value = {
                "names": ["A", "B"],
                "ids": ["cc_a", "cc_b"],
                "semantic_status": None,
                "details": {},
            }

            # 5 chemins différents
            service._neo4j_client.execute_query.side_effect = [
                [
                    {
                        "node_names": ["A", f"X{i}", "B"],
                        "node_ids": ["cc_a", f"cc_x{i}", "cc_b"],
                        "rel_types": ["R1", "R2"],
                        "path_length": 2,
                        "path_confidence": 0.9 - i*0.1,
                    }
                    for i in range(5)
                ],
                # Evidence pour chaque chemin
                [{"context_id": f"sec:doc{i}:h", "salience": 0.8} for i in range(5)],
            ]

            start = time.perf_counter()
            plan = await service.build_search_plan("Query")
            duration_ms = (time.perf_counter() - start) * 1000

            threshold = PERFORMANCE_THRESHOLDS["build_search_plan_ms"]
            assert duration_ms < threshold


# Tests d'intégration (avec vraies connexions)
@pytest.mark.integration
@pytest.mark.slow
class TestPerformanceIntegration:
    """
    Tests de performance avec infrastructure réelle.

    Ces tests nécessitent Neo4j et Qdrant disponibles.
    """

    @pytest.fixture
    def real_service(self):
        try:
            svc = get_graph_first_service(tenant_id="default")
            svc.neo4j_client.execute_query("RETURN 1")
            return svc
        except Exception:
            pytest.skip("Neo4j not available")

    @pytest.mark.asyncio
    async def test_real_search_plan_performance(self, real_service):
        """
        Test end-to-end avec données réelles.

        Target: < 500ms pour build_search_plan
        """
        queries = [
            "What are the security requirements?",
            "How does SAP integrate with cloud?",
            "What is GDPR compliance?",
        ]

        results = []
        for query in queries:
            start = time.perf_counter()
            plan = await real_service.build_search_plan(query)
            duration_ms = (time.perf_counter() - start) * 1000

            results.append(PerformanceResult(
                operation=f"search_plan: {query[:30]}...",
                duration_ms=duration_ms,
                threshold_ms=PERFORMANCE_THRESHOLDS["total_graph_first_ms"],
                passed=duration_ms < PERFORMANCE_THRESHOLDS["total_graph_first_ms"],
                details={
                    "mode": plan.mode.value,
                    "reported_time": plan.processing_time_ms,
                }
            ))

        # Afficher les résultats
        print("\n=== Performance Results ===")
        for r in results:
            print(r)

        # Tous doivent passer
        failed = [r for r in results if not r.passed]
        assert len(failed) == 0, f"{len(failed)} queries exceeded threshold"

    @pytest.mark.asyncio
    async def test_performance_consistency(self, real_service):
        """
        Test: Performance consistante sur plusieurs exécutions.

        La variance ne doit pas être trop élevée.
        """
        query = "What are the security requirements?"
        durations = []

        for _ in range(5):
            start = time.perf_counter()
            await real_service.build_search_plan(query)
            durations.append((time.perf_counter() - start) * 1000)

        avg = sum(durations) / len(durations)
        max_duration = max(durations)
        min_duration = min(durations)
        variance = max_duration - min_duration

        print(f"\nPerformance consistency:")
        print(f"  Average: {avg:.1f}ms")
        print(f"  Min: {min_duration:.1f}ms")
        print(f"  Max: {max_duration:.1f}ms")
        print(f"  Variance: {variance:.1f}ms")

        # Variance acceptable: < 50% de la moyenne
        assert variance < avg * 0.5, f"High variance: {variance:.1f}ms"


class TestPerformanceRegression:
    """Tests de régression de performance."""

    def test_thresholds_are_reasonable(self):
        """
        Test: Les seuils de performance sont raisonnables.

        Vérifie que la configuration des seuils est cohérente.
        """
        # Total doit être >= somme des composants
        component_sum = (
            PERFORMANCE_THRESHOLDS["concept_extraction_ms"] +
            PERFORMANCE_THRESHOLDS["pathfinding_ms"]
        )

        assert PERFORMANCE_THRESHOLDS["build_search_plan_ms"] >= component_sum * 0.5, \
            "build_search_plan threshold seems too low"

        # Total < 1 seconde (UX acceptable)
        assert PERFORMANCE_THRESHOLDS["total_graph_first_ms"] < 1000, \
            "Total threshold > 1s is too slow for UX"

    def test_performance_budget_documented(self):
        """
        Test: Le budget performance est documenté.
        """
        expected_keys = [
            "build_search_plan_ms",
            "total_graph_first_ms",
        ]

        for key in expected_keys:
            assert key in PERFORMANCE_THRESHOLDS, f"Missing threshold: {key}"
            assert isinstance(PERFORMANCE_THRESHOLDS[key], (int, float))
            assert PERFORMANCE_THRESHOLDS[key] > 0
