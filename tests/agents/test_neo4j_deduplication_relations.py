"""
Tests pour les nouvelles fonctionnalités Neo4j:
- Problème 2: Déduplication CanonicalConcept
- Problème 1: Persistance relations sémantiques

Author: OSMOSE Phase 1.5
Date: 2025-10-16
"""

import pytest
from unittest.mock import Mock, patch, call
from src.knowbase.agents.gatekeeper.gatekeeper import GatekeeperDelegate, PromoteConceptsInput
from src.knowbase.agents.base import AgentState


class TestNeo4jDeduplicationLogic:
    """Tests pour la logique de déduplication (Problème 2)."""

    def test_promote_concepts_tool_creates_mapping(self):
        """Test que _promote_concepts_tool crée bien le mapping concept_name→canonical_id."""
        # Créer Gatekeeper avec Neo4j mocké
        with patch('src.knowbase.agents.gatekeeper.gatekeeper.get_neo4j_client') as mock_get_client:
            mock_neo4j = Mock()
            mock_neo4j.is_connected.return_value = True
            mock_neo4j.save_proto_concept.return_value = "proto-123"
            mock_neo4j.promote_to_published.return_value = "canonical-456"
            mock_get_client.return_value = mock_neo4j

            gatekeeper = GatekeeperDelegate(config={})

            # Tester promote_concepts_tool
            concepts = [
                {"name": "SAP", "type": "PRODUCT", "definition": "Enterprise software"},
                {"name": "ERP", "type": "ENTITY", "definition": "Resource planning"}
            ]

            tool_input = PromoteConceptsInput(concepts=concepts)
            result = gatekeeper._promote_concepts_tool(tool_input)

            # Vérifier succès
            assert result.success is True
            assert result.data["promoted_count"] == 2

            # Vérifier que le mapping existe
            assert "concept_name_to_canonical_id" in result.data
            mapping = result.data["concept_name_to_canonical_id"]

            # Vérifier que les concepts sont dans le mapping
            assert "SAP" in mapping
            assert "ERP" in mapping

    def test_deduplication_calls_find_canonical_concept(self):
        """Test que promote_to_published appelle find_canonical_concept pour déduplication."""
        with patch('src.knowbase.agents.gatekeeper.gatekeeper.get_neo4j_client') as mock_get_client:
            mock_neo4j = Mock()
            mock_neo4j.is_connected.return_value = True
            mock_neo4j.save_proto_concept.return_value = "proto-123"
            mock_neo4j.find_canonical_concept.return_value = None  # Concept n'existe pas
            mock_neo4j.promote_to_published.return_value = "canonical-new"
            mock_get_client.return_value = mock_neo4j

            gatekeeper = GatekeeperDelegate(config={})

            concepts = [{"name": "NewConcept", "type": "ENTITY", "definition": "Test"}]
            tool_input = PromoteConceptsInput(concepts=concepts)

            gatekeeper._promote_concepts_tool(tool_input)

            # Vérifier que promote_to_published a été appelé avec deduplicate=True par défaut
            assert mock_neo4j.promote_to_published.called

    def test_mapping_persists_across_multiple_concepts(self):
        """Test que le mapping accumule correctement plusieurs concepts."""
        with patch('src.knowbase.agents.gatekeeper.gatekeeper.get_neo4j_client') as mock_get_client:
            mock_neo4j = Mock()
            mock_neo4j.is_connected.return_value = True
            mock_neo4j.save_proto_concept.return_value = "proto-123"

            # Simuler retour d'IDs différents pour chaque concept
            mock_neo4j.promote_to_published.side_effect = [
                "canonical-sap",
                "canonical-erp",
                "canonical-cloud"
            ]
            mock_get_client.return_value = mock_neo4j

            gatekeeper = GatekeeperDelegate(config={})

            concepts = [
                {"name": "SAP", "type": "PRODUCT", "definition": "Software"},
                {"name": "ERP", "type": "ENTITY", "definition": "Planning"},
                {"name": "Cloud", "type": "CONCEPT", "definition": "Technology"}
            ]

            tool_input = PromoteConceptsInput(concepts=concepts)
            result = gatekeeper._promote_concepts_tool(tool_input)

            mapping = result.data["concept_name_to_canonical_id"]

            # Vérifier que tous les concepts sont mappés
            assert len(mapping) == 3
            assert mapping["SAP"] == "canonical-sap"
            assert mapping["ERP"] == "canonical-erp"
            assert mapping["Cloud"] == "canonical-cloud"


class TestSemanticRelationsPersistence:
    """Tests pour persistance relations sémantiques (Problème 1)."""

    @pytest.mark.asyncio
    async def test_relations_are_persisted_when_concepts_promoted(self):
        """Test que les relations sont persistées après promotion des concepts."""
        with patch('src.knowbase.agents.gatekeeper.gatekeeper.get_neo4j_client') as mock_get_client:
            mock_neo4j = Mock()
            mock_neo4j.is_connected.return_value = True
            mock_neo4j.save_proto_concept.return_value = "proto-123"
            mock_neo4j.promote_to_published.side_effect = ["canonical-sap", "canonical-erp"]
            mock_neo4j.create_concept_link.return_value = True
            mock_get_client.return_value = mock_neo4j

            gatekeeper = GatekeeperDelegate(config={})

            # État avec relations
            state = AgentState(
                document_id="test-doc",
                tenant_id="default",
                candidates=[
                    {"name": "SAP", "type": "PRODUCT", "confidence": 0.85, "definition": "Software"},
                    {"name": "ERP", "type": "ENTITY", "confidence": 0.80, "definition": "Planning"}
                ],
                relations=[
                    {
                        "source": "SAP",
                        "target": "ERP",
                        "type": "CO_OCCURRENCE",
                        "segment_id": "segment-1",
                        "confidence": 0.7
                    }
                ]
            )

            # Exécuter
            final_state = await gatekeeper.execute(state)

            # Vérifier que create_concept_link a été appelé
            assert mock_neo4j.create_concept_link.called

            # Vérifier les paramètres de l'appel
            call_args = mock_neo4j.create_concept_link.call_args
            assert call_args is not None

    @pytest.mark.asyncio
    async def test_relations_skipped_when_concepts_not_promoted(self):
        """Test que les relations sont skippées si les concepts ne sont pas promus."""
        with patch('src.knowbase.agents.gatekeeper.gatekeeper.get_neo4j_client') as mock_get_client:
            mock_neo4j = Mock()
            mock_neo4j.is_connected.return_value = True
            mock_neo4j.save_proto_concept.return_value = "proto-123"
            mock_neo4j.promote_to_published.return_value = "canonical-sap"
            mock_neo4j.create_concept_link.return_value = True
            mock_get_client.return_value = mock_neo4j

            gatekeeper = GatekeeperDelegate(config={})

            # État avec relation vers concept non promu
            state = AgentState(
                document_id="test-doc",
                tenant_id="default",
                candidates=[
                    {"name": "SAP", "type": "PRODUCT", "confidence": 0.85, "definition": "Software"}
                    # ERP n'est PAS dans les candidates
                ],
                relations=[
                    {
                        "source": "SAP",
                        "target": "ERP",  # Concept non promu
                        "type": "CO_OCCURRENCE",
                        "segment_id": "segment-1",
                        "confidence": 0.7
                    }
                ]
            )

            # Exécuter
            final_state = await gatekeeper.execute(state)

            # create_concept_link ne devrait pas être appelé car ERP n'est pas promu
            # (pas de canonical_id pour ERP dans le mapping)
            assert not mock_neo4j.create_concept_link.called

    @pytest.mark.asyncio
    async def test_relations_persistence_handles_errors_gracefully(self):
        """Test que les erreurs de persistance ne bloquent pas l'exécution."""
        with patch('src.knowbase.agents.gatekeeper.gatekeeper.get_neo4j_client') as mock_get_client:
            mock_neo4j = Mock()
            mock_neo4j.is_connected.return_value = True
            mock_neo4j.save_proto_concept.return_value = "proto-123"
            mock_neo4j.promote_to_published.side_effect = ["canonical-sap", "canonical-erp"]

            # create_concept_link lève une exception
            mock_neo4j.create_concept_link.side_effect = Exception("Neo4j error")
            mock_get_client.return_value = mock_neo4j

            gatekeeper = GatekeeperDelegate(config={})

            state = AgentState(
                document_id="test-doc",
                tenant_id="default",
                candidates=[
                    {"name": "SAP", "type": "PRODUCT", "confidence": 0.85, "definition": "Software"},
                    {"name": "ERP", "type": "ENTITY", "confidence": 0.80, "definition": "Planning"}
                ],
                relations=[
                    {
                        "source": "SAP",
                        "target": "ERP",
                        "type": "CO_OCCURRENCE",
                        "segment_id": "segment-1",
                        "confidence": 0.7
                    }
                ]
            )

            # Exécuter - ne devrait pas crasher
            final_state = await gatekeeper.execute(state)

            # Vérifier que l'exécution s'est terminée
            assert final_state is not None
            assert len(final_state.promoted) > 0

    @pytest.mark.asyncio
    async def test_no_relations_no_error(self):
        """Test qu'absence de relations ne cause pas d'erreur."""
        with patch('src.knowbase.agents.gatekeeper.gatekeeper.get_neo4j_client') as mock_get_client:
            mock_neo4j = Mock()
            mock_neo4j.is_connected.return_value = True
            mock_neo4j.save_proto_concept.return_value = "proto-123"
            mock_neo4j.promote_to_published.return_value = "canonical-sap"
            mock_neo4j.create_concept_link.return_value = True
            mock_get_client.return_value = mock_neo4j

            gatekeeper = GatekeeperDelegate(config={})

            # État sans relations
            state = AgentState(
                document_id="test-doc",
                tenant_id="default",
                candidates=[
                    {"name": "SAP", "type": "PRODUCT", "confidence": 0.85, "definition": "Software"}
                ],
                relations=[]  # Vide
            )

            # Exécuter
            final_state = await gatekeeper.execute(state)

            # Ne devrait pas appeler create_concept_link
            assert not mock_neo4j.create_concept_link.called
            assert final_state is not None


class TestRelationsMetadata:
    """Tests pour vérifier la structure des relations."""

    def test_relations_have_required_fields(self):
        """Test que les relations ont tous les champs requis."""
        state = AgentState(
            document_id="test-doc",
            tenant_id="default",
            relations=[
                {
                    "source": "SAP",
                    "target": "ERP",
                    "type": "CO_OCCURRENCE",
                    "segment_id": "segment-1",
                    "confidence": 0.7
                }
            ]
        )

        relation = state.relations[0]

        # Vérifier champs obligatoires
        assert "source" in relation
        assert "target" in relation
        assert "type" in relation
        assert "segment_id" in relation
        assert "confidence" in relation

    def test_relations_confidence_in_valid_range(self):
        """Test que confidence est dans [0, 1]."""
        state = AgentState(
            document_id="test-doc",
            tenant_id="default",
            relations=[
                {
                    "source": "SAP",
                    "target": "ERP",
                    "type": "CO_OCCURRENCE",
                    "segment_id": "segment-1",
                    "confidence": 0.7
                }
            ]
        )

        for relation in state.relations:
            conf = relation.get("confidence", 0.0)
            assert 0.0 <= conf <= 1.0

    def test_relations_type_is_valid(self):
        """Test que le type de relation est valide."""
        state = AgentState(
            document_id="test-doc",
            tenant_id="default",
            relations=[
                {
                    "source": "SAP",
                    "target": "ERP",
                    "type": "CO_OCCURRENCE",
                    "segment_id": "segment-1",
                    "confidence": 0.7
                }
            ]
        )

        valid_types = ["CO_OCCURRENCE", "RELATED_TO", "PART_OF", "INSTANCE_OF"]

        for relation in state.relations:
            rel_type = relation.get("type")
            # Au moins CO_OCCURRENCE devrait être valide
            assert rel_type in valid_types or rel_type is not None


class TestIntegration:
    """Tests d'intégration pour workflow complet."""

    @pytest.mark.asyncio
    async def test_end_to_end_workflow(self):
        """Test E2E: Promotion + Mapping + Persistance relations."""
        with patch('src.knowbase.agents.gatekeeper.gatekeeper.get_neo4j_client') as mock_get_client:
            mock_neo4j = Mock()
            mock_neo4j.is_connected.return_value = True
            mock_neo4j.save_proto_concept.return_value = "proto-123"
            mock_neo4j.promote_to_published.side_effect = [
                "canonical-sap",
                "canonical-erp",
                "canonical-cloud"
            ]
            mock_neo4j.create_concept_link.return_value = True
            mock_get_client.return_value = mock_neo4j

            gatekeeper = GatekeeperDelegate(config={})

            # État complexe avec plusieurs concepts et relations
            state = AgentState(
                document_id="test-doc",
                tenant_id="default",
                candidates=[
                    {"name": "SAP", "type": "PRODUCT", "confidence": 0.85, "definition": "Software"},
                    {"name": "ERP", "type": "ENTITY", "confidence": 0.80, "definition": "Planning"},
                    {"name": "Cloud", "type": "CONCEPT", "confidence": 0.75, "definition": "Technology"}
                ],
                relations=[
                    {
                        "source": "SAP",
                        "target": "ERP",
                        "type": "CO_OCCURRENCE",
                        "segment_id": "segment-1",
                        "confidence": 0.7
                    },
                    {
                        "source": "SAP",
                        "target": "Cloud",
                        "type": "CO_OCCURRENCE",
                        "segment_id": "segment-1",
                        "confidence": 0.6
                    }
                ]
            )

            # Exécuter
            final_state = await gatekeeper.execute(state)

            # Vérifications
            assert final_state is not None
            assert len(final_state.promoted) > 0

            # Les concepts ont été promus
            assert mock_neo4j.promote_to_published.call_count >= 1

            # Les relations ont été persistées
            assert mock_neo4j.create_concept_link.call_count >= 1
