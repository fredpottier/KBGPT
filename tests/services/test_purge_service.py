"""
Tests pour PurgeService.

Vérifie que la purge préserve les ontologies Neo4j.
"""
import pytest
import asyncio
from neo4j import GraphDatabase
import os

from knowbase.api.services.purge_service import PurgeService


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
def purge_service():
    """Fixture PurgeService."""
    return PurgeService()


def test_purge_neo4j_preserves_ontologies(neo4j_driver, purge_service):
    """
    Test que la purge Neo4j préserve les OntologyEntity et OntologyAlias.

    Scénario:
    1. Créer des entités métier (Entity)
    2. Vérifier ontologies existantes
    3. Purger Neo4j
    4. Vérifier que ontologies sont toujours là
    5. Vérifier que entités métier sont supprimées
    """
    with neo4j_driver.session() as session:
        # ÉTAPE 1: Compter ontologies AVANT purge
        result_ont_before = session.run("""
            MATCH (ont:OntologyEntity)
            RETURN count(ont) AS ont_count
        """)
        ont_count_before = result_ont_before.single()["ont_count"]

        result_alias_before = session.run("""
            MATCH (alias:OntologyAlias)
            RETURN count(alias) AS alias_count
        """)
        alias_count_before = result_alias_before.single()["alias_count"]

        # Vérifier qu'il y a des ontologies (de la migration)
        assert ont_count_before > 0, "Aucune ontologie trouvée (migration non faite?)"
        assert alias_count_before > 0, "Aucun alias trouvé (migration non faite?)"

        # ÉTAPE 2: Créer des entités métier de test
        session.run("""
            CREATE (e1:Entity {
                uuid: 'test-entity-1',
                name: 'Test Entity 1',
                entity_type: 'TEST',
                tenant_id: 'test'
            })
            CREATE (e2:Entity {
                uuid: 'test-entity-2',
                name: 'Test Entity 2',
                entity_type: 'TEST',
                tenant_id: 'test'
            })
        """)

        # Vérifier entités créées
        result_entities_before = session.run("""
            MATCH (e:Entity {tenant_id: 'test'})
            RETURN count(e) AS entity_count
        """)
        entity_count_before = result_entities_before.single()["entity_count"]
        assert entity_count_before >= 2, "Entités test pas créées"

    # ÉTAPE 3: PURGER Neo4j
    purge_result = asyncio.run(purge_service._purge_neo4j())
    assert purge_result["success"] is True, f"Purge échouée: {purge_result['message']}"

    # ÉTAPE 4: Vérifier ontologies APRÈS purge
    with neo4j_driver.session() as session:
        result_ont_after = session.run("""
            MATCH (ont:OntologyEntity)
            RETURN count(ont) AS ont_count
        """)
        ont_count_after = result_ont_after.single()["ont_count"]

        result_alias_after = session.run("""
            MATCH (alias:OntologyAlias)
            RETURN count(alias) AS alias_count
        """)
        alias_count_after = result_alias_after.single()["alias_count"]

        # ✅ ASSERTIONS CRITIQUES : Ontologies PRÉSERVÉES
        assert ont_count_after == ont_count_before, \
            f"OntologyEntity supprimées ! Avant: {ont_count_before}, Après: {ont_count_after}"

        assert alias_count_after == alias_count_before, \
            f"OntologyAlias supprimés ! Avant: {alias_count_before}, Après: {alias_count_after}"

        # ✅ Vérifier que entités métier SUPPRIMÉES
        result_entities_after = session.run("""
            MATCH (e:Entity {tenant_id: 'test'})
            RETURN count(e) AS entity_count
        """)
        entity_count_after = result_entities_after.single()["entity_count"]

        assert entity_count_after == 0, \
            f"Entités métier pas supprimées ! Encore {entity_count_after} présentes"


def test_purge_neo4j_counts_only_business_nodes(neo4j_driver, purge_service):
    """
    Test que le compteur de purge ne compte QUE les nodes métier, pas les ontologies.
    """
    with neo4j_driver.session() as session:
        # Créer entités métier test
        session.run("""
            CREATE (e:Entity {
                uuid: 'test-count-1',
                name: 'Test Count',
                entity_type: 'TEST',
                tenant_id: 'test'
            })
        """)

        # Compter manuellement nodes métier
        result_manual = session.run("""
            MATCH (n)
            WHERE NOT n:OntologyEntity AND NOT n:OntologyAlias
            RETURN count(n) AS business_count
        """)
        business_count_manual = result_manual.single()["business_count"]

    # Purger
    purge_result = asyncio.run(purge_service._purge_neo4j())

    # ✅ Vérifier que nodes_deleted ne compte QUE les métier
    # (doit être >= notre entité test, mais pas inclure ontologies)
    assert purge_result["nodes_deleted"] >= 1, "Aucune entité supprimée"

    # Le nombre doit correspondre au comptage manuel
    assert purge_result["nodes_deleted"] == business_count_manual, \
        f"Comptage incorrect. Purge: {purge_result['nodes_deleted']}, Manuel: {business_count_manual}"
