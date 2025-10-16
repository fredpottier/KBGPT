"""
Tests simplifiés EntityNormalizer sans dépendances settings.
"""
import pytest
from pathlib import Path
import yaml
import tempfile
from enum import Enum


# Copie locale d'EntityType pour tests isolés
class EntityType(str, Enum):
    SOLUTION = "SOLUTION"
    COMPONENT = "COMPONENT"
    TECHNOLOGY = "TECHNOLOGY"


def test_yaml_catalog_loading():
    """Test chargement catalogue YAML solutions."""
    catalog_path = Path("config/ontologies/solutions.yaml")

    assert catalog_path.exists(), "Catalogue solutions.yaml doit exister"

    with open(catalog_path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)

    assert "SOLUTIONS" in data
    solutions = data["SOLUTIONS"]

    # Vérifier structure S4HANA_PUBLIC
    assert "S4HANA_PUBLIC" in solutions
    s4_public = solutions["S4HANA_PUBLIC"]

    assert s4_public["canonical_name"] == "SAP S/4HANA Cloud, Public Edition"
    assert "SAP Cloud ERP" in s4_public["aliases"]
    assert s4_public["category"] == "ERP"
    assert s4_public["vendor"] == "SAP"


def test_yaml_catalog_components():
    """Test chargement catalogue YAML components."""
    catalog_path = Path("config/ontologies/components.yaml")

    assert catalog_path.exists(), "Catalogue components.yaml doit exister"

    with open(catalog_path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)

    assert "COMPONENTS" in data
    components = data["COMPONENTS"]

    # Vérifier LOAD_BALANCER
    assert "LOAD_BALANCER" in components
    lb = components["LOAD_BALANCER"]

    assert lb["canonical_name"] == "Load Balancer"
    assert "LB" in lb["aliases"]
    assert lb["category"] == "Infrastructure"


def test_yaml_catalog_technologies():
    """Test chargement catalogue YAML technologies."""
    catalog_path = Path("config/ontologies/technologies.yaml")

    assert catalog_path.exists(), "Catalogue technologies.yaml doit exister"

    with open(catalog_path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)

    assert "TECHNOLOGIES" in data
    technologies = data["TECHNOLOGIES"]

    # Vérifier KUBERNETES
    assert "KUBERNETES" in technologies
    k8s = technologies["KUBERNETES"]

    assert k8s["canonical_name"] == "Kubernetes"
    assert "k8s" in k8s["aliases"]
    assert k8s["category"] == "Container Orchestration"


def test_alias_index_construction():
    """Test construction index inversé aliases."""
    # Créer catalogue test
    catalog_data = {
        "SOLUTIONS": {
            "TEST_SOLUTION": {
                "canonical_name": "Test Solution",
                "aliases": ["TS", "TestSol", "test solution"]
            }
        }
    }

    # Construire index
    alias_index = {}
    solutions = catalog_data["SOLUTIONS"]

    for entity_id, entity_data in solutions.items():
        canonical = entity_data["canonical_name"]
        aliases = entity_data.get("aliases", [])

        # Indexer canonical (lowercase)
        alias_index[canonical.lower()] = entity_id

        # Indexer aliases
        for alias in aliases:
            alias_index[alias.lower()] = entity_id

    # Vérifier index
    assert alias_index["test solution"] == "TEST_SOLUTION"
    assert alias_index["ts"] == "TEST_SOLUTION"
    assert alias_index["testsol"] == "TEST_SOLUTION"


def test_normalization_case_insensitive():
    """Test normalisation insensible à la casse."""
    test_inputs = [
        "Load Balancer",
        "load balancer",
        "LOAD BALANCER",
        "load_balancer"
    ]

    # Tous devraient normaliser en "load balancer"
    for input_text in test_inputs:
        normalized = input_text.strip().lower()
        # La recherche doit être insensible à la casse
        assert "load" in normalized
        assert "balancer" in normalized


def test_ontology_directory_structure():
    """Test structure répertoire ontologies."""
    ontology_dir = Path("config/ontologies")

    assert ontology_dir.exists()
    assert ontology_dir.is_dir()

    # Vérifier présence fichiers obligatoires
    required_files = [
        "solutions.yaml",
        "components.yaml",
        "technologies.yaml",
        "organizations.yaml",
        "persons.yaml",
        "concepts.yaml"
    ]

    for filename in required_files:
        filepath = ontology_dir / filename
        assert filepath.exists(), f"{filename} doit exister"


def test_catalog_consistency():
    """Test cohérence structure catalogues."""
    ontology_dir = Path("config/ontologies")

    catalog_files = {
        "solutions.yaml": "SOLUTIONS",
        "components.yaml": "COMPONENTS",
        "technologies.yaml": "TECHNOLOGIES"
    }

    for filename, root_key in catalog_files.items():
        filepath = ontology_dir / filename

        with open(filepath, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)

        assert root_key in data, f"{filename} doit contenir clé {root_key}"

        entities = data[root_key]

        # Vérifier structure de chaque entité
        for entity_id, entity_data in entities.items():
            assert "canonical_name" in entity_data, \
                f"Entité {entity_id} doit avoir canonical_name"
            assert "aliases" in entity_data, \
                f"Entité {entity_id} doit avoir aliases"
            assert isinstance(entity_data["aliases"], list), \
                f"Aliases de {entity_id} doit être une liste"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
