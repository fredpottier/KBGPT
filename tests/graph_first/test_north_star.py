"""
ADR_GRAPH_FIRST_ARCHITECTURE Phase D - Tests North Star

Tests fonctionnels critiques pour valider l'architecture Graph-First:
1. Ambiguous Word: Question ambiguë → bons concepts trouvés
2. Path Recovery: Question sur relation connue → chemin identique au KG
"""

import pytest
import asyncio
from typing import List, Dict, Any, Optional
from unittest.mock import Mock, patch, AsyncMock

from knowbase.api.services.graph_first_search import (
    GraphFirstSearchService,
    GraphFirstPlan,
    SearchMode,
    SemanticPath,
    get_graph_first_service,
)


class TestNorthStarAmbiguousWord:
    """
    Test Ambiguous Word: Question avec mot ambigu.

    Critère: Le système doit trouver le bon contexte grâce au pathfinding.
    Exemple: "transformation" → "Quotation→Contract", pas "Digital Transformation"
    """

    @pytest.fixture
    def mock_neo4j_client(self):
        """Mock du client Neo4j avec données de test."""
        client = Mock()
        client.execute_query = Mock(return_value=[])
        return client

    @pytest.fixture
    def service(self, mock_neo4j_client):
        """Service avec mocks injectés."""
        svc = GraphFirstSearchService(tenant_id="test")
        svc._neo4j_client = mock_neo4j_client
        return svc

    @pytest.mark.asyncio
    async def test_ambiguous_word_finds_correct_context(self, service, mock_neo4j_client):
        """
        Test: Question "transformation" trouve le bon contexte.

        Scénario:
        - KG contient "Quotation" --[TRANSFORMS_TO]--> "Contract"
        - KG contient "Digital Transformation" (concept isolé)
        - Question: "What is the transformation process?"
        - Attendu: Mode REASONED avec path Quotation→Contract
        """
        # Setup: Mock extract_concepts pour retourner les seeds
        with patch.object(
            service.concept_service,
            'extract_concepts_from_query_v2',
            new_callable=AsyncMock
        ) as mock_extract:
            mock_extract.return_value = {
                "names": ["Quotation", "Contract", "Transformation"],
                "ids": ["cc_quotation", "cc_contract", "cc_transformation"],
                "semantic_status": None,
                "details": {},
            }

            # Setup: Mock pathfinding pour trouver un chemin Quotation→Contract
            mock_neo4j_client.execute_query.side_effect = [
                # Premier appel: allShortestPaths entre Quotation et Contract
                [{
                    "node_names": ["Quotation", "Contract"],
                    "node_ids": ["cc_quotation", "cc_contract"],
                    "rel_types": ["TRANSFORMS_TO"],
                    "path_length": 1,
                    "path_confidence": 0.85,
                }],
                # Deuxième appel: pas de chemin Quotation-Transformation
                [],
                # Troisième appel: pas de chemin Contract-Transformation
                [],
                # Evidence collection
                [
                    {"context_id": "sec:doc1:hash1", "salience": 0.9},
                    {"context_id": "sec:doc1:hash2", "salience": 0.7},
                ],
            ]

            # Execute
            plan = await service.build_search_plan(
                "What is the transformation process?"
            )

            # Assert: Mode REASONED avec le bon chemin
            assert plan.mode == SearchMode.REASONED
            assert len(plan.paths) >= 1

            # Le chemin principal doit être Quotation→Contract
            main_path = plan.paths[0]
            assert "Quotation" in main_path.nodes
            assert "Contract" in main_path.nodes
            assert main_path.confidence >= 0.8

    @pytest.mark.asyncio
    async def test_ambiguous_word_no_false_positive(self, service, mock_neo4j_client):
        """
        Test: Ne pas trouver de faux positifs.

        Scénario:
        - Question sur un terme vraiment ambigu sans contexte clair
        - Pas de paths sémantiques trouvés
        - Attendu: Mode ANCHORED ou TEXT_ONLY, pas REASONED avec chemin faux
        """
        with patch.object(
            service.concept_service,
            'extract_concepts_from_query_v2',
            new_callable=AsyncMock
        ) as mock_extract:
            mock_extract.return_value = {
                "names": ["Transformation"],
                "ids": ["cc_transformation"],
                "semantic_status": None,
                "details": {},
            }

            # Pas de chemins trouvés (un seul concept)
            mock_neo4j_client.execute_query.return_value = []

            plan = await service.build_search_plan("transformation")

            # Avec un seul concept, pas de pathfinding possible
            # Devrait être ANCHORED ou TEXT_ONLY
            assert plan.mode in (SearchMode.ANCHORED, SearchMode.TEXT_ONLY)


class TestNorthStarPathRecovery:
    """
    Test Path Recovery: Question sur relation connue → retrouve le chemin exact.

    Critère: Le chemin retourné doit être identique à celui stocké dans Neo4j.
    """

    @pytest.fixture
    def mock_neo4j_client(self):
        """Mock Neo4j avec un chemin connu."""
        client = Mock()
        return client

    @pytest.fixture
    def service(self, mock_neo4j_client):
        svc = GraphFirstSearchService(tenant_id="test")
        svc._neo4j_client = mock_neo4j_client
        return svc

    @pytest.mark.asyncio
    async def test_path_recovery_exact_match(self, service, mock_neo4j_client):
        """
        Test: Le chemin retourné correspond exactement au KG.

        Scénario:
        - KG: "SAP S/4HANA" --[REQUIRES]--> "HANA Database" --[ENABLES]--> "Real-time Analytics"
        - Question: "How does S/4HANA enable real-time analytics?"
        - Attendu: Chemin exact [S/4HANA, HANA Database, Real-time Analytics]
        """
        with patch.object(
            service.concept_service,
            'extract_concepts_from_query_v2',
            new_callable=AsyncMock
        ) as mock_extract:
            mock_extract.return_value = {
                "names": ["SAP S/4HANA", "Real-time Analytics"],
                "ids": ["cc_s4hana", "cc_realtime"],
                "semantic_status": None,
                "details": {},
            }

            # Chemin exact dans le KG
            expected_path = {
                "node_names": ["SAP S/4HANA", "HANA Database", "Real-time Analytics"],
                "node_ids": ["cc_s4hana", "cc_hana", "cc_realtime"],
                "rel_types": ["REQUIRES", "ENABLES"],
                "path_length": 2,
                "path_confidence": 0.9,
            }

            mock_neo4j_client.execute_query.side_effect = [
                [expected_path],  # allShortestPaths
                [  # Evidence collection
                    {"context_id": "sec:doc1:hash1", "salience": 0.95},
                ],
            ]

            plan = await service.build_search_plan(
                "How does S/4HANA enable real-time analytics?"
            )

            # Vérifier le mode
            assert plan.mode == SearchMode.REASONED
            assert len(plan.paths) >= 1

            # Vérifier le chemin exact
            path = plan.paths[0]
            assert path.nodes == ["SAP S/4HANA", "HANA Database", "Real-time Analytics"]
            assert path.relations == ["REQUIRES", "ENABLES"]
            assert path.length == 2

    @pytest.mark.asyncio
    async def test_path_recovery_with_multiple_paths(self, service, mock_neo4j_client):
        """
        Test: Plusieurs chemins possibles → retourne les meilleurs par confiance.

        Scénario:
        - Path 1: A → B → C (confidence: 0.9)
        - Path 2: A → D → C (confidence: 0.7)
        - Attendu: Path 1 en premier
        """
        with patch.object(
            service.concept_service,
            'extract_concepts_from_query_v2',
            new_callable=AsyncMock
        ) as mock_extract:
            mock_extract.return_value = {
                "names": ["ConceptA", "ConceptC"],
                "ids": ["cc_a", "cc_c"],
                "semantic_status": None,
                "details": {},
            }

            mock_neo4j_client.execute_query.side_effect = [
                [
                    {
                        "node_names": ["ConceptA", "ConceptB", "ConceptC"],
                        "node_ids": ["cc_a", "cc_b", "cc_c"],
                        "rel_types": ["REQUIRES", "ENABLES"],
                        "path_length": 2,
                        "path_confidence": 0.9,
                    },
                    {
                        "node_names": ["ConceptA", "ConceptD", "ConceptC"],
                        "node_ids": ["cc_a", "cc_d", "cc_c"],
                        "rel_types": ["DEPENDS_ON", "PART_OF"],
                        "path_length": 2,
                        "path_confidence": 0.7,
                    },
                ],
                # Evidence collection
                [{"context_id": "sec:doc1:hash1", "salience": 0.9}],
            ]

            plan = await service.build_search_plan("How is A related to C?")

            assert plan.mode == SearchMode.REASONED
            assert len(plan.paths) >= 2

            # Le premier chemin doit avoir la meilleure confiance
            assert plan.paths[0].confidence >= plan.paths[1].confidence
            assert plan.paths[0].confidence == 0.9


class TestSearchModeSelection:
    """Tests pour la sélection du mode de recherche."""

    @pytest.fixture
    def service(self):
        svc = GraphFirstSearchService(tenant_id="test")
        svc._neo4j_client = Mock()
        return svc

    @pytest.mark.asyncio
    async def test_reasoned_mode_when_paths_found(self, service):
        """Mode REASONED quand des chemins sémantiques existent."""
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

            service._neo4j_client.execute_query.side_effect = [
                [{  # Path trouvé
                    "node_names": ["A", "B"],
                    "node_ids": ["cc_a", "cc_b"],
                    "rel_types": ["REQUIRES"],
                    "path_length": 1,
                    "path_confidence": 0.8,
                }],
                [{"context_id": "sec:doc:hash", "salience": 0.9}],
            ]

            plan = await service.build_search_plan("Query about A and B")
            assert plan.mode == SearchMode.REASONED

    @pytest.mark.asyncio
    async def test_anchored_mode_when_structural_routes(self, service):
        """Mode ANCHORED quand pas de paths mais routes structurelles."""
        with patch.object(
            service.concept_service,
            'extract_concepts_from_query_v2',
            new_callable=AsyncMock
        ) as mock_extract:
            mock_extract.return_value = {
                "names": ["Concept"],
                "ids": ["cc_concept"],
                "semantic_status": None,
                "details": {},
            }

            # Pas de paths (un seul concept), mais routes structurelles
            service._neo4j_client.execute_query.side_effect = [
                [{  # Route structurelle trouvée
                    "topic_name": "Security Topic",
                    "topic_id": "cc_topic_security",
                    "covered_ids": ["cc_concept"],
                    "document_ids": ["doc1"],
                    "context_ids": ["sec:doc1:hash1"],
                }],
            ]

            plan = await service.build_search_plan("Query about Concept")
            assert plan.mode == SearchMode.ANCHORED

    @pytest.mark.asyncio
    async def test_text_only_mode_as_fallback(self, service):
        """Mode TEXT_ONLY quand rien n'est trouvé."""
        with patch.object(
            service.concept_service,
            'extract_concepts_from_query_v2',
            new_callable=AsyncMock
        ) as mock_extract:
            mock_extract.return_value = {
                "names": [],
                "ids": [],
                "semantic_status": None,
                "details": {},
            }

            plan = await service.build_search_plan("Random query with no concepts")
            assert plan.mode == SearchMode.TEXT_ONLY
            assert plan.fallback_reason is not None


# Integration tests (nécessitent Neo4j réel)
@pytest.mark.integration
class TestNorthStarIntegration:
    """
    Tests d'intégration avec Neo4j réel.

    Ces tests ne s'exécutent que si Neo4j est disponible.
    Marqués avec @pytest.mark.integration.
    """

    @pytest.fixture
    def real_service(self):
        """Service avec vraie connexion Neo4j."""
        try:
            svc = get_graph_first_service(tenant_id="default")
            # Vérifier connexion
            svc.neo4j_client.execute_query("RETURN 1 AS test")
            return svc
        except Exception:
            pytest.skip("Neo4j not available")

    @pytest.mark.asyncio
    async def test_real_path_recovery(self, real_service):
        """
        Test avec données réelles.

        Note: Ce test dépend des données présentes dans Neo4j.
        Il vérifie que le service fonctionne end-to-end.
        """
        # Ce test vérifie juste que le service fonctionne
        plan = await real_service.build_search_plan(
            "What are the security requirements?"
        )

        # Doit retourner un plan valide (quel que soit le mode)
        assert plan is not None
        assert plan.mode in (SearchMode.REASONED, SearchMode.ANCHORED, SearchMode.TEXT_ONLY)
        assert plan.processing_time_ms > 0
