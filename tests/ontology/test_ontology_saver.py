"""
Tests ontology_saver.
"""
import pytest
from neo4j import GraphDatabase
import os

from knowbase.ontology.ontology_saver import save_ontology_to_neo4j


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


def test_save_ontology_to_neo4j(neo4j_driver):
    """Test sauvegarde ontologie LLM dans Neo4j."""

    # Mock merge_groups (structure générée par LLM)
    merge_groups = [
        {
            "canonical_key": "TEST_PRODUCT_1",
            "canonical_name": "Test Product One",
            "confidence": 0.95,
            "entities": [
                {"name": "Test Product One"},
                {"name": "Product 1"},
                {"name": "Prod 1"}
            ]
        },
        {
            "canonical_key": "TEST_PRODUCT_2",
            "canonical_name": "Test Product Two",
            "confidence": 0.90,
            "entities": [
                {"name": "Test Product Two"},
                {"name": "Product 2"}
            ]
        }
    ]

    # Sauvegarder
    save_ontology_to_neo4j(
        merge_groups=merge_groups,
        entity_type="TEST_TYPE",
        tenant_id="test_tenant",
        source="llm_generated"
    )

    # Vérifier sauvegarde
    with neo4j_driver.session() as session:
        # Vérifier OntologyEntity créées
        result = session.run("""
            MATCH (ont:OntologyEntity {
                entity_type: 'TEST_TYPE',
                tenant_id: 'test_tenant'
            })
            RETURN count(ont) AS count
        """)
        count = result.single()["count"]
        assert count >= 2  # Au moins nos 2 entités

        # Vérifier alias créés
        result = session.run("""
            MATCH (ont:OntologyEntity {entity_id: 'TEST_PRODUCT_1'})
                  -[:HAS_ALIAS]->(alias:OntologyAlias)
            RETURN count(alias) AS alias_count
        """)
        alias_count = result.single()["alias_count"]
        assert alias_count >= 2  # "Product 1" et "Prod 1" (canonical exclu)

        # Vérifier normalisation lookup
        result = session.run("""
            MATCH (ont:OntologyEntity)-[:HAS_ALIAS]->(alias:OntologyAlias {
                normalized: 'product 1',
                entity_type: 'TEST_TYPE',
                tenant_id: 'test_tenant'
            })
            RETURN ont.canonical_name AS canonical
        """)
        record = result.single()
        assert record is not None
        assert record["canonical"] == "Test Product One"


def test_save_ontology_skip_canonical_duplicate(neo4j_driver):
    """Test que canonical_name n'est pas créé comme alias."""

    merge_groups = [
        {
            "canonical_key": "TEST_UNIQUE",
            "canonical_name": "Test Unique Product",
            "confidence": 0.95,
            "entities": [
                {"name": "Test Unique Product"},  # Même que canonical
                {"name": "Unique Prod"}
            ]
        }
    ]

    save_ontology_to_neo4j(
        merge_groups=merge_groups,
        entity_type="TEST_TYPE_2",
        tenant_id="test_tenant",
        source="llm_generated"
    )

    # Vérifier qu'un seul alias créé (pas le doublon canonical)
    with neo4j_driver.session() as session:
        result = session.run("""
            MATCH (ont:OntologyEntity {entity_id: 'TEST_UNIQUE'})
                  -[:HAS_ALIAS]->(alias:OntologyAlias)
            RETURN count(alias) AS alias_count
        """)
        alias_count = result.single()["alias_count"]
        assert alias_count == 1  # Seulement "Unique Prod", pas le canonical
