"""Tests complets pour EntityNormalizer.

Tests unitaires couvrant:
- Normalisation d'entités avec catalogue
- Cas d'erreur (fichier manquant, format invalide)
- Lazy loading des catalogues
- Singleton pattern
- Logging des entités non cataloguées
"""

import pytest
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock
import yaml

from knowbase.common.entity_normalizer import (
    EntityNormalizer,
    get_entity_normalizer,
)


@pytest.fixture
def temp_ontology_dir():
    """Crée un répertoire temporaire pour les ontologies."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


@pytest.fixture
def sample_solutions_catalog():
    """Catalogue de solutions de test."""
    return {
        "SOLUTIONS": {
            "SAP_S4HANA": {
                "canonical_name": "SAP S/4HANA",
                "aliases": ["S/4HANA", "S4HANA", "SAP S4", "S/4"],
            },
            "SAP_BTP": {
                "canonical_name": "SAP Business Technology Platform",
                "aliases": ["BTP", "SAP BTP", "Business Technology Platform"],
            },
            "SALESFORCE_CRM": {
                "canonical_name": "Salesforce CRM",
                "aliases": ["Salesforce", "SFDC"],
            },
        }
    }


@pytest.fixture
def normalizer_with_catalog(temp_ontology_dir, sample_solutions_catalog):
    """EntityNormalizer avec catalogue de test."""
    # Créer fichier YAML
    catalog_file = temp_ontology_dir / "solutions.yaml"
    with open(catalog_file, "w", encoding="utf-8") as f:
        yaml.dump(sample_solutions_catalog, f)

    # Patcher settings pour utiliser le répertoire temporaire
    with patch("knowbase.common.entity_normalizer.settings") as mock_settings:
        mock_settings.config_dir = str(temp_ontology_dir.parent)
        mock_settings.logs_dir = str(temp_ontology_dir / "logs")
        (temp_ontology_dir / "logs").mkdir(exist_ok=True)

        # Créer le normalizer avec ontology_dir pointant vers temp
        normalizer = EntityNormalizer()
        normalizer.ontology_dir = temp_ontology_dir

        yield normalizer


class TestEntityNormalizerBasic:
    """Tests de base pour EntityNormalizer."""

    def test_normalize_exact_canonical_match(
        self, normalizer_with_catalog: EntityNormalizer
    ) -> None:
        """Test normalisation avec correspondance exacte sur canonical_name."""
        entity_id, canonical_name, is_cataloged = normalizer_with_catalog.normalize_entity_name(
            "SAP S/4HANA", "SOLUTION"
        )

        assert entity_id == "SAP_S4HANA"
        assert canonical_name == "SAP S/4HANA"
        assert is_cataloged is True

    def test_normalize_alias_match(
        self, normalizer_with_catalog: EntityNormalizer
    ) -> None:
        """Test normalisation avec correspondance via alias."""
        entity_id, canonical_name, is_cataloged = normalizer_with_catalog.normalize_entity_name(
            "S4HANA", "SOLUTION"
        )

        assert entity_id == "SAP_S4HANA"
        assert canonical_name == "SAP S/4HANA"
        assert is_cataloged is True

    def test_normalize_case_insensitive(
        self, normalizer_with_catalog: EntityNormalizer
    ) -> None:
        """Test normalisation case-insensitive."""
        entity_id, canonical_name, is_cataloged = normalizer_with_catalog.normalize_entity_name(
            "sap s/4hana", "SOLUTION"
        )

        assert entity_id == "SAP_S4HANA"
        assert canonical_name == "SAP S/4HANA"
        assert is_cataloged is True

    def test_normalize_with_whitespace(
        self, normalizer_with_catalog: EntityNormalizer
    ) -> None:
        """Test normalisation avec espaces supplémentaires."""
        entity_id, canonical_name, is_cataloged = normalizer_with_catalog.normalize_entity_name(
            "  SAP S/4HANA  ", "SOLUTION"
        )

        assert entity_id == "SAP_S4HANA"
        assert canonical_name == "SAP S/4HANA"
        assert is_cataloged is True

    def test_normalize_uncataloged_entity(
        self, normalizer_with_catalog: EntityNormalizer
    ) -> None:
        """Test normalisation d'une entité non cataloguée."""
        entity_id, canonical_name, is_cataloged = normalizer_with_catalog.normalize_entity_name(
            "Unknown Software", "SOLUTION"
        )

        assert entity_id is None
        assert canonical_name == "Unknown Software"
        assert is_cataloged is False


class TestEntityNormalizerLazyLoading:
    """Tests du lazy loading des catalogues."""

    def test_catalog_loaded_on_first_access(
        self, normalizer_with_catalog: EntityNormalizer
    ) -> None:
        """Test que le catalogue est chargé uniquement à la première utilisation."""
        # Initialement, aucun type chargé
        assert "SOLUTION" not in normalizer_with_catalog._loaded_types

        # Premier accès
        normalizer_with_catalog.normalize_entity_name("test", "SOLUTION")

        # Maintenant chargé
        assert "SOLUTION" in normalizer_with_catalog._loaded_types

    def test_catalog_cached_after_first_load(
        self, normalizer_with_catalog: EntityNormalizer
    ) -> None:
        """Test que le catalogue est mis en cache après le premier chargement."""
        # Premier accès
        normalizer_with_catalog.normalize_entity_name("SAP S/4HANA", "SOLUTION")

        # Vérifier cache
        assert "SOLUTION" in normalizer_with_catalog._catalogs
        assert "SOLUTION" in normalizer_with_catalog._alias_index


class TestEntityNormalizerMissingCatalog:
    """Tests avec catalogue manquant."""

    def test_missing_catalog_file(self, temp_ontology_dir: Path) -> None:
        """Test comportement avec fichier catalogue inexistant."""
        with patch("knowbase.common.entity_normalizer.settings") as mock_settings:
            mock_settings.config_dir = str(temp_ontology_dir.parent)
            mock_settings.logs_dir = str(temp_ontology_dir / "logs")
            (temp_ontology_dir / "logs").mkdir(exist_ok=True)

            normalizer = EntityNormalizer()
            normalizer.ontology_dir = temp_ontology_dir

            # Devrait retourner l'entité brute sans erreur
            entity_id, canonical_name, is_cataloged = normalizer.normalize_entity_name(
                "Test Entity", "UNKNOWN_TYPE"
            )

            assert entity_id is None
            assert canonical_name == "Test Entity"
            assert is_cataloged is False


class TestEntityNormalizerMetadata:
    """Tests pour get_entity_metadata."""

    def test_get_metadata_existing_entity(
        self, normalizer_with_catalog: EntityNormalizer
    ) -> None:
        """Test récupération métadonnées d'une entité existante."""
        # Charger d'abord le catalogue
        normalizer_with_catalog.normalize_entity_name("test", "SOLUTION")

        metadata = normalizer_with_catalog.get_entity_metadata("SAP_S4HANA", "SOLUTION")

        assert metadata is not None
        assert metadata["canonical_name"] == "SAP S/4HANA"
        assert "S/4HANA" in metadata["aliases"]

    def test_get_metadata_nonexistent_entity(
        self, normalizer_with_catalog: EntityNormalizer
    ) -> None:
        """Test récupération métadonnées d'une entité inexistante."""
        # Charger d'abord le catalogue
        normalizer_with_catalog.normalize_entity_name("test", "SOLUTION")

        metadata = normalizer_with_catalog.get_entity_metadata("NONEXISTENT", "SOLUTION")

        assert metadata is None


class TestEntityNormalizerLogging:
    """Tests pour log_uncataloged_entity."""

    def test_log_uncataloged_entity_creates_log(self, temp_ontology_dir: Path) -> None:
        """Test que log_uncataloged_entity écrit dans le fichier de log."""
        with patch("knowbase.common.entity_normalizer.settings") as mock_settings:
            mock_settings.config_dir = str(temp_ontology_dir.parent)
            mock_settings.logs_dir = str(temp_ontology_dir / "logs")
            (temp_ontology_dir / "logs").mkdir(exist_ok=True)

            normalizer = EntityNormalizer()
            normalizer.ontology_dir = temp_ontology_dir

            normalizer.log_uncataloged_entity(
                raw_name="New Entity",
                entity_type="SOLUTION",
                tenant_id="test_tenant",
            )

            log_file = temp_ontology_dir / "uncataloged_entities.log"
            assert log_file.exists()

            content = log_file.read_text()
            assert "New Entity" in content
            assert "SOLUTION" in content
            assert "test_tenant" in content


class TestEntityNormalizerSingleton:
    """Tests pour le pattern singleton."""

    def test_get_entity_normalizer_returns_same_instance(self) -> None:
        """Test que get_entity_normalizer retourne la même instance."""
        # Reset singleton pour test isolé
        import knowbase.common.entity_normalizer as module
        module._normalizer = None

        with patch("knowbase.common.entity_normalizer.settings") as mock_settings:
            mock_settings.config_dir = "/tmp"
            mock_settings.logs_dir = "/tmp/logs"

            normalizer1 = get_entity_normalizer()
            normalizer2 = get_entity_normalizer()

            assert normalizer1 is normalizer2

        # Cleanup
        module._normalizer = None


class TestEntityNormalizerEdgeCases:
    """Tests des cas limites."""

    def test_normalize_empty_string(
        self, normalizer_with_catalog: EntityNormalizer
    ) -> None:
        """Test normalisation d'une chaîne vide."""
        entity_id, canonical_name, is_cataloged = normalizer_with_catalog.normalize_entity_name(
            "", "SOLUTION"
        )

        assert entity_id is None
        assert canonical_name == ""
        assert is_cataloged is False

    def test_normalize_special_characters(
        self, normalizer_with_catalog: EntityNormalizer
    ) -> None:
        """Test normalisation avec caractères spéciaux."""
        # S/4 est un alias valide
        entity_id, canonical_name, is_cataloged = normalizer_with_catalog.normalize_entity_name(
            "S/4", "SOLUTION"
        )

        assert entity_id == "SAP_S4HANA"
        assert is_cataloged is True

    def test_normalize_unicode_characters(
        self, normalizer_with_catalog: EntityNormalizer
    ) -> None:
        """Test normalisation avec caractères Unicode."""
        entity_id, canonical_name, is_cataloged = normalizer_with_catalog.normalize_entity_name(
            "Système métier", "SOLUTION"
        )

        assert entity_id is None
        assert canonical_name == "Système métier"
        assert is_cataloged is False

    def test_normalize_multiple_entity_types(
        self, temp_ontology_dir: Path, sample_solutions_catalog: dict
    ) -> None:
        """Test normalisation avec plusieurs types d'entités."""
        # Créer deux catalogues
        solutions_file = temp_ontology_dir / "solutions.yaml"
        with open(solutions_file, "w", encoding="utf-8") as f:
            yaml.dump(sample_solutions_catalog, f)

        components_catalog = {
            "COMPONENTS": {
                "HANA_DB": {
                    "canonical_name": "SAP HANA Database",
                    "aliases": ["HANA", "SAP HANA"],
                }
            }
        }
        components_file = temp_ontology_dir / "components.yaml"
        with open(components_file, "w", encoding="utf-8") as f:
            yaml.dump(components_catalog, f)

        with patch("knowbase.common.entity_normalizer.settings") as mock_settings:
            mock_settings.config_dir = str(temp_ontology_dir.parent)
            mock_settings.logs_dir = str(temp_ontology_dir / "logs")
            (temp_ontology_dir / "logs").mkdir(exist_ok=True)

            normalizer = EntityNormalizer()
            normalizer.ontology_dir = temp_ontology_dir

            # Normaliser solution
            entity_id_sol, name_sol, _ = normalizer.normalize_entity_name(
                "SAP S/4HANA", "SOLUTION"
            )
            assert entity_id_sol == "SAP_S4HANA"

            # Normaliser component
            entity_id_comp, name_comp, _ = normalizer.normalize_entity_name(
                "HANA", "COMPONENT"
            )
            assert entity_id_comp == "HANA_DB"
            assert name_comp == "SAP HANA Database"
