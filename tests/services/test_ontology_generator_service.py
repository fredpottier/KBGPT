"""
Tests pour OntologyGeneratorService.

Phase 5B - Step 2
"""
import pytest
from unittest.mock import AsyncMock, MagicMock
from knowbase.api.services.ontology_generator_service import OntologyGeneratorService


class TestOntologyGeneratorService:
    """Tests génération ontologie via LLM."""

    @pytest.fixture
    def service(self):
        """Fixture service avec LLM mocké."""
        llm_router = MagicMock()
        return OntologyGeneratorService(llm_router=llm_router)

    @pytest.mark.asyncio
    async def test_generate_ontology_success(self, service):
        """✅ Génération ontologie réussie."""
        entities = [
            {"uuid": "1", "name": "SAP S/4HANA PCE", "description": "Private cloud"},
            {"uuid": "2", "name": "SAP S/4HANA Private Cloud", "description": "ERP"},
            {"uuid": "3", "name": "SAP Business One", "description": "SME"},
        ]

        # Mock réponse LLM
        llm_response = """
        {
            "SAP_S4HANA_PRIVATE_CLOUD": {
                "canonical_name": "SAP S/4HANA Private Cloud Edition",
                "aliases": ["SAP S/4HANA PCE", "SAP S/4HANA Private Cloud"],
                "confidence": 0.95,
                "entities_merged": ["1", "2"],
                "description": "Private cloud ERP"
            },
            "SAP_BUSINESS_ONE": {
                "canonical_name": "SAP Business One",
                "aliases": [],
                "confidence": 1.0,
                "entities_merged": ["3"],
                "description": "SME ERP"
            }
        }
        """

        service.llm_router.complete = AsyncMock(return_value=llm_response)

        result = await service.generate_ontology_from_entities(
            entity_type="SOLUTION",
            entities=entities
        )

        assert result["entity_type"] == "SOLUTION"
        assert result["entities_analyzed"] == 3
        assert result["groups_proposed"] == 2
        assert "SAP_S4HANA_PRIVATE_CLOUD" in result["ontology"]
        assert "SAP_BUSINESS_ONE" in result["ontology"]

    @pytest.mark.asyncio
    async def test_generate_ontology_empty_entities(self, service):
        """✅ Ontologie vide si aucune entité."""
        result = await service.generate_ontology_from_entities(
            entity_type="SOLUTION",
            entities=[]
        )

        assert result["entities_analyzed"] == 0
        assert result["groups_proposed"] == 0
        assert result["ontology"] == {}

    def test_parse_llm_response_with_markdown(self, service):
        """✅ Parse JSON même avec markdown code blocks."""
        llm_response = """```json
        {
            "TEST_TYPE": {
                "canonical_name": "Test",
                "aliases": ["test"],
                "confidence": 0.9,
                "entities_merged": ["uuid-1"]
            }
        }
        ```"""

        entities = [{"uuid": "uuid-1", "name": "test"}]

        ontology = service._parse_llm_response(llm_response, entities)

        assert "TEST_TYPE" in ontology
        assert ontology["TEST_TYPE"]["canonical_name"] == "Test"

    def test_parse_llm_response_invalid_json(self, service):
        """❌ Erreur si JSON invalide."""
        llm_response = "not a valid json {"

        entities = []

        with pytest.raises(ValueError, match="not valid JSON"):
            service._parse_llm_response(llm_response, entities)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
