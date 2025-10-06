"""
Tests unitaires pour entity_normalizer avec gestion status/is_cataloged.

Vérifie que la normalisation retourne correctement:
- is_cataloged=True pour entités trouvées dans ontologie
- is_cataloged=False pour entités non cataloguées
"""
import pytest
from pathlib import Path
import yaml
import tempfile
import shutil

from knowbase.common.entity_normalizer import EntityNormalizer


@pytest.fixture
def temp_ontology_dir():
    """Crée répertoire ontologies temporaire avec catalogues test."""
    temp_dir = Path(tempfile.mkdtemp())
    ontology_dir = temp_dir / "ontologies"
    ontology_dir.mkdir(parents=True)

    # Catalogue SOLUTION test
    solutions_data = {
        "SOLUTIONS": {
            "S4HANA_PCE": {
                "canonical_name": "SAP S/4HANA Cloud, Private Edition",
                "aliases": [
                    "S/4HANA PCE",
                    "Private Cloud Edition",
                    "S4 PCE"
                ],
                "category": "ERP",
                "vendor": "SAP"
            },
            "BTP": {
                "canonical_name": "SAP Business Technology Platform",
                "aliases": [
                    "BTP",
                    "SAP BTP",
                    "Business Technology Platform"
                ],
                "category": "Platform",
                "vendor": "SAP"
            }
        }
    }

    # Catalogue INFRASTRUCTURE test
    infrastructure_data = {
        "INFRASTRUCTURES": {
            "LOAD_BALANCER": {
                "canonical_name": "Load Balancer",
                "aliases": [
                    "Load Balancer",
                    "LB",
                    "Application Load Balancer"
                ],
                "category": "Networking",
                "vendor": "Generic"
            }
        }
    }

    # Écrire fichiers YAML
    with open(ontology_dir / "solutions.yaml", "w", encoding="utf-8") as f:
        yaml.dump(solutions_data, f)

    with open(ontology_dir / "infrastructures.yaml", "w", encoding="utf-8") as f:
        yaml.dump(infrastructure_data, f)

    yield ontology_dir

    # Cleanup
    shutil.rmtree(temp_dir)


class TestEntityNormalizerStatus:
    """Tests normalisation avec status/is_cataloged."""

    def test_normalize_cataloged_entity_exact_match(self, temp_ontology_dir):
        """✅ Entité cataloguée - correspondance exacte nom canonique."""
        normalizer = EntityNormalizer()
        normalizer.ontology_dir = temp_ontology_dir

        entity_id, canonical_name, is_cataloged = normalizer.normalize_entity_name(
            raw_name="SAP S/4HANA Cloud, Private Edition",
            entity_type="SOLUTION"
        )

        assert is_cataloged is True
        assert entity_id == "S4HANA_PCE"
        assert canonical_name == "SAP S/4HANA Cloud, Private Edition"

    def test_normalize_cataloged_entity_alias_match(self, temp_ontology_dir):
        """✅ Entité cataloguée - correspondance via alias."""
        normalizer = EntityNormalizer()
        normalizer.ontology_dir = temp_ontology_dir

        entity_id, canonical_name, is_cataloged = normalizer.normalize_entity_name(
            raw_name="S/4HANA PCE",  # Alias
            entity_type="SOLUTION"
        )

        assert is_cataloged is True
        assert entity_id == "S4HANA_PCE"
        assert canonical_name == "SAP S/4HANA Cloud, Private Edition"

    def test_normalize_cataloged_entity_case_insensitive(self, temp_ontology_dir):
        """✅ Entité cataloguée - case insensitive."""
        normalizer = EntityNormalizer()
        normalizer.ontology_dir = temp_ontology_dir

        entity_id, canonical_name, is_cataloged = normalizer.normalize_entity_name(
            raw_name="s/4hana pce",  # Lowercase
            entity_type="SOLUTION"
        )

        assert is_cataloged is True
        assert entity_id == "S4HANA_PCE"
        assert canonical_name == "SAP S/4HANA Cloud, Private Edition"

    def test_normalize_uncataloged_entity(self, temp_ontology_dir):
        """❌ Entité non cataloguée → is_cataloged=False."""
        normalizer = EntityNormalizer()
        normalizer.ontology_dir = temp_ontology_dir

        entity_id, canonical_name, is_cataloged = normalizer.normalize_entity_name(
            raw_name="Azure Virtual Network",  # Pas dans catalogue
            entity_type="INFRASTRUCTURE"
        )

        assert is_cataloged is False
        assert entity_id is None
        assert canonical_name == "Azure Virtual Network"

    def test_normalize_entity_type_not_in_ontology(self, temp_ontology_dir):
        """❌ Type entité sans catalogue → is_cataloged=False."""
        normalizer = EntityNormalizer()
        normalizer.ontology_dir = temp_ontology_dir

        # Type NETWORK n'a pas de fichier networks.yaml
        entity_id, canonical_name, is_cataloged = normalizer.normalize_entity_name(
            raw_name="Internal Network",
            entity_type="NETWORK"
        )

        assert is_cataloged is False
        assert entity_id is None
        assert canonical_name == "Internal Network"

    def test_normalize_entity_whitespace_trimmed(self, temp_ontology_dir):
        """✅ Espaces début/fin trimés."""
        normalizer = EntityNormalizer()
        normalizer.ontology_dir = temp_ontology_dir

        # Cataloguée avec espaces
        entity_id, canonical_name, is_cataloged = normalizer.normalize_entity_name(
            raw_name="  BTP  ",
            entity_type="SOLUTION"
        )

        assert is_cataloged is True
        assert entity_id == "BTP"
        assert canonical_name == "SAP Business Technology Platform"

        # Non cataloguée avec espaces
        entity_id2, canonical_name2, is_cataloged2 = normalizer.normalize_entity_name(
            raw_name="  Unknown Solution  ",
            entity_type="SOLUTION"
        )

        assert is_cataloged2 is False
        assert entity_id2 is None
        assert canonical_name2 == "Unknown Solution"

    def test_normalize_multiple_types_independence(self, temp_ontology_dir):
        """✅ Catalogues multiples types chargés indépendamment."""
        normalizer = EntityNormalizer()
        normalizer.ontology_dir = temp_ontology_dir

        # Type SOLUTION
        entity_id1, canonical_name1, is_cataloged1 = normalizer.normalize_entity_name(
            raw_name="BTP",
            entity_type="SOLUTION"
        )

        # Type INFRASTRUCTURE
        entity_id2, canonical_name2, is_cataloged2 = normalizer.normalize_entity_name(
            raw_name="Load Balancer",
            entity_type="INFRASTRUCTURE"
        )

        assert is_cataloged1 is True
        assert entity_id1 == "BTP"

        assert is_cataloged2 is True
        assert entity_id2 == "LOAD_BALANCER"
        assert canonical_name2 == "Load Balancer"

    def test_normalize_lazy_loading_catalog(self, temp_ontology_dir):
        """✅ Lazy loading - catalogue chargé seulement si nécessaire."""
        normalizer = EntityNormalizer()
        normalizer.ontology_dir = temp_ontology_dir

        # Vérifier aucun catalogue chargé au départ
        assert len(normalizer._loaded_types) == 0

        # Premier appel → charge SOLUTION
        normalizer.normalize_entity_name("BTP", "SOLUTION")
        assert "SOLUTION" in normalizer._loaded_types
        assert "INFRASTRUCTURE" not in normalizer._loaded_types

        # Deuxième appel → charge INFRASTRUCTURE
        normalizer.normalize_entity_name("Load Balancer", "INFRASTRUCTURE")
        assert "INFRASTRUCTURE" in normalizer._loaded_types

    def test_normalize_metadata_enrichment(self, temp_ontology_dir):
        """✅ Métadonnées cataloguées disponibles via get_entity_metadata."""
        normalizer = EntityNormalizer()
        normalizer.ontology_dir = temp_ontology_dir

        entity_id, canonical_name, is_cataloged = normalizer.normalize_entity_name(
            raw_name="S4 PCE",
            entity_type="SOLUTION"
        )

        assert is_cataloged is True

        # Récupérer métadonnées complètes
        metadata = normalizer.get_entity_metadata(entity_id, "SOLUTION")

        assert metadata is not None
        assert metadata["canonical_name"] == "SAP S/4HANA Cloud, Private Edition"
        assert metadata["category"] == "ERP"
        assert metadata["vendor"] == "SAP"
        assert "S/4HANA PCE" in metadata["aliases"]

    def test_normalize_uncataloged_no_metadata(self, temp_ontology_dir):
        """❌ Entité non cataloguée → pas de métadonnées."""
        normalizer = EntityNormalizer()
        normalizer.ontology_dir = temp_ontology_dir

        entity_id, canonical_name, is_cataloged = normalizer.normalize_entity_name(
            raw_name="Unknown Product",
            entity_type="SOLUTION"
        )

        assert is_cataloged is False
        assert entity_id is None

        # get_entity_metadata devrait retourner None
        metadata = normalizer.get_entity_metadata("UNKNOWN_ID", "SOLUTION")
        assert metadata is None

    def test_status_derivation_cataloged(self, temp_ontology_dir):
        """
        ✅ Test intégration : entité cataloguée → status='validated'.

        Note: Ce test valide la logique que knowledge_graph_service
        utilisera pour définir status automatiquement.
        """
        normalizer = EntityNormalizer()
        normalizer.ontology_dir = temp_ontology_dir

        entity_id, canonical_name, is_cataloged = normalizer.normalize_entity_name(
            raw_name="BTP",
            entity_type="SOLUTION"
        )

        # Logique attendue dans knowledge_graph_service
        expected_status = "validated" if is_cataloged else "pending"
        expected_is_cataloged = is_cataloged

        assert expected_status == "validated"
        assert expected_is_cataloged is True

    def test_status_derivation_uncataloged(self, temp_ontology_dir):
        """
        ✅ Test intégration : entité non cataloguée → status='pending'.
        """
        normalizer = EntityNormalizer()
        normalizer.ontology_dir = temp_ontology_dir

        entity_id, canonical_name, is_cataloged = normalizer.normalize_entity_name(
            raw_name="Unknown Infrastructure",
            entity_type="INFRASTRUCTURE"
        )

        # Logique attendue dans knowledge_graph_service
        expected_status = "validated" if is_cataloged else "pending"
        expected_is_cataloged = is_cataloged

        assert expected_status == "pending"
        assert expected_is_cataloged is False


class TestEntityNormalizerPerformance:
    """Tests performance normalisation."""

    def test_normalize_1000_entities_performance(self, temp_ontology_dir):
        """✅ Normalisation 1000 entités < 1s."""
        import time

        normalizer = EntityNormalizer()
        normalizer.ontology_dir = temp_ontology_dir

        start = time.time()

        for i in range(1000):
            # Mix catalogued/uncataloged
            if i % 2 == 0:
                normalizer.normalize_entity_name("BTP", "SOLUTION")
            else:
                normalizer.normalize_entity_name(f"Unknown {i}", "SOLUTION")

        elapsed = time.time() - start

        assert elapsed < 1.0, f"Normalisation trop lente: {elapsed:.2f}s pour 1000 entités"

    def test_catalog_caching(self, temp_ontology_dir):
        """✅ Catalogue mis en cache après premier chargement."""
        normalizer = EntityNormalizer()
        normalizer.ontology_dir = temp_ontology_dir

        # Premier appel → charge catalogue
        import time
        start1 = time.time()
        normalizer.normalize_entity_name("BTP", "SOLUTION")
        first_call = time.time() - start1

        # Deuxième appel → utilise cache
        start2 = time.time()
        normalizer.normalize_entity_name("S4 PCE", "SOLUTION")
        second_call = time.time() - start2

        # Cache devrait être significativement plus rapide
        # (au moins 10x plus rapide car pas de lecture fichier)
        assert second_call < first_call / 5, \
            f"Cache pas efficace: 1er={first_call:.4f}s, 2ème={second_call:.4f}s"


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
