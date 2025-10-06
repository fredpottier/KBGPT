"""
Tests unitaires pour EntityNormalizer.
"""
import pytest
import sys
from pathlib import Path

# Import direct sans passer par l'API pour éviter dépendances lourdes
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

from knowbase.common.entity_types import EntityType
from knowbase.common.entity_normalizer import EntityNormalizer


@pytest.fixture
def normalizer():
    """Fixture normalizer pour tests."""
    return EntityNormalizer()


class TestEntityNormalizer:
    """Tests du service de normalisation d'entités."""

    def test_normalize_solution_sap_exact_match(self, normalizer):
        """Test normalisation solution SAP - correspondance exacte."""
        entity_id, canonical = normalizer.normalize_entity_name(
            "SAP S/4HANA Cloud, Public Edition",
            EntityType.SOLUTION
        )
        assert entity_id == "S4HANA_PUBLIC"
        assert canonical == "SAP S/4HANA Cloud, Public Edition"

    def test_normalize_solution_sap_alias_match(self, normalizer):
        """Test normalisation solution SAP - via alias."""
        entity_id, canonical = normalizer.normalize_entity_name(
            "SAP Cloud ERP",
            EntityType.SOLUTION
        )
        assert entity_id == "S4HANA_PUBLIC"
        assert canonical == "SAP S/4HANA Cloud, Public Edition"

    def test_normalize_solution_case_insensitive(self, normalizer):
        """Test normalisation insensible à la casse."""
        entity_id, canonical = normalizer.normalize_entity_name(
            "sap cloud erp",
            EntityType.SOLUTION
        )
        assert entity_id == "S4HANA_PUBLIC"
        assert canonical == "SAP S/4HANA Cloud, Public Edition"

    def test_normalize_component_load_balancer(self, normalizer):
        """Test normalisation component - Load Balancer."""
        entity_id, canonical = normalizer.normalize_entity_name(
            "LB",
            EntityType.COMPONENT
        )
        assert entity_id == "LOAD_BALANCER"
        assert canonical == "Load Balancer"

    def test_normalize_component_api_gateway(self, normalizer):
        """Test normalisation component - API Gateway."""
        entity_id, canonical = normalizer.normalize_entity_name(
            "APIGW",
            EntityType.COMPONENT
        )
        assert entity_id == "API_GATEWAY"
        assert canonical == "API Gateway"

    def test_normalize_technology_kubernetes(self, normalizer):
        """Test normalisation technology - Kubernetes."""
        entity_id, canonical = normalizer.normalize_entity_name(
            "k8s",
            EntityType.TECHNOLOGY
        )
        assert entity_id == "KUBERNETES"
        assert canonical == "Kubernetes"

    def test_normalize_uncataloged_entity(self, normalizer):
        """Test normalisation entité non cataloguée."""
        entity_id, canonical = normalizer.normalize_entity_name(
            "Custom Solution XYZ",
            EntityType.SOLUTION
        )
        assert entity_id is None
        assert canonical == "Custom Solution XYZ"

    def test_normalize_whitespace_handling(self, normalizer):
        """Test normalisation avec espaces."""
        entity_id, canonical = normalizer.normalize_entity_name(
            "  Load Balancer  ",
            EntityType.COMPONENT
        )
        assert entity_id == "LOAD_BALANCER"
        assert canonical == "Load Balancer"

    def test_get_entity_metadata_solution(self, normalizer):
        """Test récupération métadonnées solution."""
        metadata = normalizer.get_entity_metadata(
            "S4HANA_PUBLIC",
            EntityType.SOLUTION
        )
        assert metadata is not None
        assert metadata["canonical_name"] == "SAP S/4HANA Cloud, Public Edition"
        assert metadata["category"] == "ERP"
        assert metadata["vendor"] == "SAP"
        assert "SAP Cloud ERP" in metadata["aliases"]

    def test_get_entity_metadata_component(self, normalizer):
        """Test récupération métadonnées component."""
        metadata = normalizer.get_entity_metadata(
            "LOAD_BALANCER",
            EntityType.COMPONENT
        )
        assert metadata is not None
        assert metadata["canonical_name"] == "Load Balancer"
        assert metadata["category"] == "Infrastructure"

    def test_get_entity_metadata_not_found(self, normalizer):
        """Test métadonnées entité inexistante."""
        metadata = normalizer.get_entity_metadata(
            "NONEXISTENT_ID",
            EntityType.SOLUTION
        )
        assert metadata is None

    def test_lazy_loading(self, normalizer):
        """Test chargement lazy des catalogues."""
        # Avant premier accès, aucun catalogue chargé
        assert EntityType.SOLUTION not in normalizer._loaded_types

        # Premier accès déclenche le chargement
        normalizer.normalize_entity_name("SAP BTP", EntityType.SOLUTION)
        assert EntityType.SOLUTION in normalizer._loaded_types

        # Component pas encore chargé
        assert EntityType.COMPONENT not in normalizer._loaded_types

        # Accès component déclenche son chargement
        normalizer.normalize_entity_name("Load Balancer", EntityType.COMPONENT)
        assert EntityType.COMPONENT in normalizer._loaded_types

    def test_log_uncataloged_entity(self, normalizer, tmp_path):
        """Test logging entités non cataloguées."""
        # Changer temporairement le répertoire ontologies pour tests
        normalizer.ontology_dir = tmp_path

        normalizer.log_uncataloged_entity(
            "Custom Component ABC",
            EntityType.COMPONENT,
            "test_tenant"
        )

        log_file = tmp_path / "uncataloged_entities.log"
        assert log_file.exists()

        content = log_file.read_text(encoding="utf-8")
        assert "COMPONENT" in content
        assert "Custom Component ABC" in content
        assert "test_tenant" in content

    def test_multiple_aliases_same_entity(self, normalizer):
        """Test plusieurs aliases pointant vers même entité."""
        aliases = ["K8s", "k8s", "Kube", "kubernetes"]

        for alias in aliases:
            entity_id, canonical = normalizer.normalize_entity_name(
                alias,
                EntityType.TECHNOLOGY
            )
            assert entity_id == "KUBERNETES"
            assert canonical == "Kubernetes"
