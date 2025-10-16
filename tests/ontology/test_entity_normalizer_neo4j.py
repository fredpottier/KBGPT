"""
Tests EntityNormalizerNeo4j.
"""
import pytest
from neo4j import GraphDatabase
import os

from knowbase.ontology.entity_normalizer_neo4j import EntityNormalizerNeo4j


@pytest.fixture
def neo4j_driver():
    """Fixture Neo4j driver pour tests."""
    neo4j_uri = os.getenv("NEO4J_URI", "bolt://graphiti-neo4j:7687")
    neo4j_user = os.getenv("NEO4J_USER", "neo4j")
    neo4j_password = os.getenv("NEO4J_PASSWORD", "graphiti_neo4j_pass")

    driver = GraphDatabase.driver(
        neo4j_uri,
        auth=(neo4j_user, neo4j_password)
    )
    yield driver
    driver.close()


@pytest.fixture
def normalizer(neo4j_driver):
    """Fixture normalizer."""
    return EntityNormalizerNeo4j(neo4j_driver)


def test_normalize_alias(normalizer):
    """Test normalisation via alias."""
    entity_id, canonical, entity_type, is_cataloged = normalizer.normalize_entity_name(
        "SuccessFactors",
        entity_type_hint="SOLUTION"
    )

    assert is_cataloged is True
    assert canonical == "SAP SuccessFactors"
    assert entity_type == "SOLUTION"
    assert entity_id == "SUCCESSFACTORS"


def test_normalize_case_insensitive(normalizer):
    """Test normalisation case insensitive."""
    entity_id, canonical, entity_type, is_cataloged = normalizer.normalize_entity_name(
        "successfactors",  # Lowercase
        entity_type_hint="SOLUTION"
    )

    assert is_cataloged is True
    assert canonical == "SAP SuccessFactors"
    assert entity_id == "SUCCESSFACTORS"


def test_normalize_wrong_type_correction(normalizer):
    """Test correction type si LLM se trompe."""
    entity_id, canonical, entity_type, is_cataloged = normalizer.normalize_entity_name(
        "SuccessFactors",
        entity_type_hint="SOFTWARE"  # Mauvais type
    )

    # Devrait trouver quand même et corriger le type
    assert is_cataloged is True
    assert canonical == "SAP SuccessFactors"
    assert entity_type == "SOLUTION"  # Type corrigé


def test_normalize_not_found(normalizer):
    """Test entité non cataloguée."""
    entity_id, canonical, entity_type, is_cataloged = normalizer.normalize_entity_name(
        "Unknown Product XYZ 999",
        entity_type_hint="PRODUCT"
    )

    assert is_cataloged is False
    assert canonical == "Unknown Product XYZ 999"  # Retourné brut
    assert entity_type == "PRODUCT"
    assert entity_id is None


def test_get_entity_metadata(normalizer):
    """Test récupération metadata."""
    metadata = normalizer.get_entity_metadata("SUCCESSFACTORS")

    assert metadata is not None
    assert metadata["canonical_name"] == "SAP SuccessFactors"
    assert metadata["entity_type"] == "SOLUTION"
    assert metadata["source"] == "yaml_migrated"


def test_get_entity_metadata_not_found(normalizer):
    """Test metadata entité inexistante."""
    metadata = normalizer.get_entity_metadata("NONEXISTENT_ENTITY_12345")

    assert metadata is None


def test_normalize_with_spaces(normalizer):
    """Test normalisation avec espaces."""
    entity_id, canonical, entity_type, is_cataloged = normalizer.normalize_entity_name(
        "  SuccessFactors  ",  # Espaces avant/après
        entity_type_hint="SOLUTION"
    )

    assert is_cataloged is True
    assert canonical == "SAP SuccessFactors"


def test_normalize_no_type_hint(normalizer):
    """Test normalisation sans hint de type."""
    entity_id, canonical, entity_type, is_cataloged = normalizer.normalize_entity_name(
        "SuccessFactors",
        entity_type_hint=None  # Pas de hint
    )

    assert is_cataloged is True
    assert canonical == "SAP SuccessFactors"
    assert entity_type == "SOLUTION"  # Découvert automatiquement
