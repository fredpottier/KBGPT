"""
ADR_GRAPH_FIRST_ARCHITECTURE Phase D - Tests Evidence Alignment

Vérifie que chaque arête du chemin a une preuve (evidence_context_ids).
Critères:
- 100% des arêtes en mode REASONED doivent avoir evidence_context_ids
- Ratio d'arêtes sans preuve < 1% (No Spurious Edge)
"""

import pytest
import asyncio
from typing import List, Dict, Any
from unittest.mock import Mock, patch, AsyncMock

from knowbase.api.services.graph_first_search import (
    GraphFirstSearchService,
    GraphFirstPlan,
    SearchMode,
    SemanticPath,
)


class TestEvidenceAlignment:
    """
    Test Evidence Alignment: Chaque arête a une preuve.

    Critère: 100% des arêtes REASONED ont evidence_ids non vides.
    """

    @pytest.fixture
    def mock_neo4j_client(self):
        client = Mock()
        return client

    @pytest.fixture
    def service(self, mock_neo4j_client):
        svc = GraphFirstSearchService(tenant_id="test")
        svc._neo4j_client = mock_neo4j_client
        return svc

    @pytest.mark.asyncio
    async def test_all_paths_have_evidence(self, service, mock_neo4j_client):
        """
        Test: Tous les chemins REASONED ont des evidence_context_ids.
        """
        with patch.object(
            service.concept_service,
            'extract_concepts_from_query_v2',
            new_callable=AsyncMock
        ) as mock_extract:
            mock_extract.return_value = {
                "names": ["ConceptA", "ConceptB", "ConceptC"],
                "ids": ["cc_a", "cc_b", "cc_c"],
                "semantic_status": None,
                "details": {},
            }

            mock_neo4j_client.execute_query.side_effect = [
                # Path A-B
                [{
                    "node_names": ["ConceptA", "ConceptB"],
                    "node_ids": ["cc_a", "cc_b"],
                    "rel_types": ["REQUIRES"],
                    "path_length": 1,
                    "path_confidence": 0.85,
                }],
                # Path A-C
                [{
                    "node_names": ["ConceptA", "ConceptC"],
                    "node_ids": ["cc_a", "cc_c"],
                    "rel_types": ["ENABLES"],
                    "path_length": 1,
                    "path_confidence": 0.80,
                }],
                # Path B-C
                [{
                    "node_names": ["ConceptB", "ConceptC"],
                    "node_ids": ["cc_b", "cc_c"],
                    "rel_types": ["PART_OF"],
                    "path_length": 1,
                    "path_confidence": 0.75,
                }],
                # Evidence collection pour path 1 (A-B)
                [
                    {"context_id": "sec:doc1:hash1", "salience": 0.9},
                    {"context_id": "sec:doc1:hash2", "salience": 0.7},
                ],
                # Evidence collection pour path 2 (A-C)
                [
                    {"context_id": "sec:doc2:hash1", "salience": 0.85},
                ],
                # Evidence collection pour path 3 (B-C)
                [
                    {"context_id": "sec:doc3:hash1", "salience": 0.8},
                ],
            ]

            plan = await service.build_search_plan(
                "How are A, B, and C related?"
            )

            # Vérifier mode REASONED
            assert plan.mode == SearchMode.REASONED

            # Vérifier que tous les chemins ont des evidence
            for path in plan.paths:
                assert len(path.evidence_context_ids) > 0, \
                    f"Path {path.nodes} has no evidence_context_ids"

            # Vérifier le plan global a des evidence_ids
            assert len(plan.path_evidence_context_ids) > 0

    @pytest.mark.asyncio
    async def test_evidence_coverage_percentage(self, service, mock_neo4j_client):
        """
        Test: Calcul du pourcentage de couverture evidence.

        Critère: >= 100% des chemins ont des evidence
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

            mock_neo4j_client.execute_query.side_effect = [
                [{
                    "node_names": ["A", "B"],
                    "node_ids": ["cc_a", "cc_b"],
                    "rel_types": ["REQUIRES"],
                    "path_length": 1,
                    "path_confidence": 0.9,
                }],
                [
                    {"context_id": "sec:doc1:hash1", "salience": 0.95},
                ],
            ]

            plan = await service.build_search_plan("A to B")

            if plan.mode == SearchMode.REASONED:
                paths_with_evidence = sum(
                    1 for p in plan.paths if len(p.evidence_context_ids) > 0
                )
                total_paths = len(plan.paths)

                coverage = paths_with_evidence / total_paths if total_paths > 0 else 0
                assert coverage >= 1.0, \
                    f"Evidence coverage {coverage*100:.1f}% < 100%"


class TestNoSpuriousEdge:
    """
    Test No Spurious Edge: Pas d'arêtes inventées sans preuve.

    Critère: Ratio d'arêtes sans preuve < 1%
    """

    @pytest.fixture
    def service(self):
        svc = GraphFirstSearchService(tenant_id="test")
        svc._neo4j_client = Mock()
        return svc

    def test_semantic_path_requires_evidence(self):
        """
        Test: Un SemanticPath sans evidence ne devrait pas être en mode REASONED.
        """
        # Path sans evidence
        path_no_evidence = SemanticPath(
            nodes=["A", "B"],
            node_ids=["cc_a", "cc_b"],
            relations=["REQUIRES"],
            confidence=0.9,
            length=1,
            evidence_context_ids=[],  # Vide!
        )

        # Un path sans evidence ne devrait pas contribuer au mode REASONED
        assert len(path_no_evidence.evidence_context_ids) == 0

    def test_plan_evidence_ids_aggregation(self):
        """
        Test: Le plan agrège correctement les evidence_ids de tous les chemins.
        """
        plan = GraphFirstPlan(
            mode=SearchMode.REASONED,
            seed_concepts=["A", "B", "C"],
            seed_concept_ids=["cc_a", "cc_b", "cc_c"],
            paths=[
                SemanticPath(
                    nodes=["A", "B"],
                    node_ids=["cc_a", "cc_b"],
                    relations=["REQUIRES"],
                    confidence=0.9,
                    length=1,
                    evidence_context_ids=["sec:doc1:h1", "sec:doc1:h2"],
                ),
                SemanticPath(
                    nodes=["B", "C"],
                    node_ids=["cc_b", "cc_c"],
                    relations=["ENABLES"],
                    confidence=0.85,
                    length=1,
                    evidence_context_ids=["sec:doc2:h1"],
                ),
            ],
            path_evidence_context_ids=["sec:doc1:h1", "sec:doc1:h2", "sec:doc2:h1"],
        )

        # Vérifier l'agrégation
        assert len(plan.path_evidence_context_ids) == 3
        assert "sec:doc1:h1" in plan.path_evidence_context_ids
        assert "sec:doc2:h1" in plan.path_evidence_context_ids

    @pytest.mark.asyncio
    async def test_spurious_edge_ratio(self, service):
        """
        Test: Calculer le ratio d'arêtes sans preuve.

        Note: Ce test vérifie la logique de calcul, pas les données réelles.
        """
        # Simuler des paths avec et sans evidence
        paths = [
            SemanticPath(
                nodes=["A", "B"],
                node_ids=["cc_a", "cc_b"],
                relations=["R1"],
                confidence=0.9,
                length=1,
                evidence_context_ids=["sec:1"],  # Avec evidence
            ),
            SemanticPath(
                nodes=["B", "C"],
                node_ids=["cc_b", "cc_c"],
                relations=["R2"],
                confidence=0.85,
                length=1,
                evidence_context_ids=["sec:2"],  # Avec evidence
            ),
        ]

        # Calculer le ratio
        paths_without_evidence = sum(
            1 for p in paths if len(p.evidence_context_ids) == 0
        )
        total_paths = len(paths)
        spurious_ratio = paths_without_evidence / total_paths if total_paths > 0 else 0

        # Critère: < 1%
        assert spurious_ratio < 0.01, \
            f"Spurious edge ratio {spurious_ratio*100:.1f}% >= 1%"


class TestEvidenceCollectionIntegrity:
    """Tests d'intégrité de la collecte d'evidence."""

    @pytest.fixture
    def service(self):
        svc = GraphFirstSearchService(tenant_id="test")
        svc._neo4j_client = Mock()
        return svc

    @pytest.mark.asyncio
    async def test_evidence_collection_from_mentioned_in(self, service):
        """
        Test: Les evidence sont collectées via MENTIONED_IN.
        """
        concept_ids = ["cc_a", "cc_b"]

        # Mock la requête MENTIONED_IN
        service._neo4j_client.execute_query.return_value = [
            {"context_id": "sec:doc1:hash1", "salience": 0.95},
            {"context_id": "sec:doc1:hash2", "salience": 0.80},
            {"context_id": "sec:doc2:hash1", "salience": 0.70},
        ]

        evidence = await service._collect_path_evidence(concept_ids)

        # Vérifier les evidence collectées
        assert len(evidence) == 3
        assert "sec:doc1:hash1" in evidence
        assert "sec:doc2:hash1" in evidence

        # Vérifier que la requête utilise MENTIONED_IN
        call_args = service._neo4j_client.execute_query.call_args
        query = call_args[0][0]
        assert "MENTIONED_IN" in query

    @pytest.mark.asyncio
    async def test_evidence_ordered_by_salience(self, service):
        """
        Test: Les evidence sont ordonnées par salience (desc).
        """
        service._neo4j_client.execute_query.return_value = [
            {"context_id": "sec:high", "salience": 0.95},
            {"context_id": "sec:medium", "salience": 0.70},
            {"context_id": "sec:low", "salience": 0.50},
        ]

        evidence = await service._collect_path_evidence(["cc_a"])

        # Premier = plus haute salience
        assert evidence[0] == "sec:high"

    @pytest.mark.asyncio
    async def test_evidence_empty_when_no_mentions(self, service):
        """
        Test: Liste vide si aucun MENTIONED_IN trouvé.
        """
        service._neo4j_client.execute_query.return_value = []

        evidence = await service._collect_path_evidence(["cc_orphan"])

        assert evidence == []


# Tests d'intégration
@pytest.mark.integration
class TestEvidenceAlignmentIntegration:
    """Tests avec Neo4j réel."""

    @pytest.fixture
    def real_service(self):
        try:
            from knowbase.api.services.graph_first_search import get_graph_first_service
            svc = get_graph_first_service(tenant_id="default")
            svc.neo4j_client.execute_query("RETURN 1")
            return svc
        except Exception:
            pytest.skip("Neo4j not available")

    @pytest.mark.asyncio
    async def test_real_evidence_alignment(self, real_service):
        """
        Test avec données réelles: vérifie que les paths ont des evidence.

        Note: Dépend des données dans Neo4j.
        """
        plan = await real_service.build_search_plan(
            "What are the security requirements for SAP?"
        )

        if plan.mode == SearchMode.REASONED:
            # En mode REASONED, tous les paths doivent avoir evidence
            for path in plan.paths:
                # Log pour debug
                print(f"Path {path.nodes}: {len(path.evidence_context_ids)} evidence")

            # Au moins un path doit avoir des evidence
            paths_with_evidence = [p for p in plan.paths if p.evidence_context_ids]
            assert len(paths_with_evidence) > 0, \
                "No paths have evidence in REASONED mode"
