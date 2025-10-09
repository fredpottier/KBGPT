"""
Schéma Neo4j pour Ontologies.

Contraintes, index et structure données.
"""
from neo4j import GraphDatabase
from typing import List
import logging

logger = logging.getLogger(__name__)


class OntologySchema:
    """Gestion schéma Neo4j ontologies."""

    def __init__(self, driver: GraphDatabase.driver):
        self.driver = driver

    def create_constraints(self) -> List[str]:
        """
        Crée toutes les contraintes nécessaires.

        Returns:
            Liste des contraintes créées
        """
        constraints = []

        with self.driver.session() as session:
            # 1. Contrainte unicité entity_id
            try:
                session.run("""
                    CREATE CONSTRAINT ont_entity_id_unique IF NOT EXISTS
                    FOR (ont:OntologyEntity)
                    REQUIRE ont.entity_id IS UNIQUE
                """)
                constraints.append("ont_entity_id_unique")
                logger.info("✅ Contrainte ont_entity_id_unique créée")
            except Exception as e:
                logger.warning(f"Contrainte ont_entity_id_unique existe déjà: {e}")

            # 2. Contrainte unicité alias_id
            try:
                session.run("""
                    CREATE CONSTRAINT ont_alias_id_unique IF NOT EXISTS
                    FOR (alias:OntologyAlias)
                    REQUIRE alias.alias_id IS UNIQUE
                """)
                constraints.append("ont_alias_id_unique")
                logger.info("✅ Contrainte ont_alias_id_unique créée")
            except Exception as e:
                logger.warning(f"Contrainte ont_alias_id_unique existe déjà: {e}")

            # 3. Contrainte unicité composite (normalized, entity_type, tenant_id)
            try:
                session.run("""
                    CREATE CONSTRAINT ont_alias_normalized_unique IF NOT EXISTS
                    FOR (alias:OntologyAlias)
                    REQUIRE (alias.normalized, alias.entity_type, alias.tenant_id) IS UNIQUE
                """)
                constraints.append("ont_alias_normalized_unique")
                logger.info("✅ Contrainte ont_alias_normalized_unique créée")
            except Exception as e:
                logger.warning(f"Contrainte ont_alias_normalized_unique existe déjà: {e}")

        return constraints

    def create_indexes(self) -> List[str]:
        """
        Crée tous les index pour performance.

        Returns:
            Liste des index créés
        """
        indexes = []

        with self.driver.session() as session:
            # 1. Index sur normalized (lookup principal)
            try:
                session.run("""
                    CREATE INDEX ont_alias_normalized_idx IF NOT EXISTS
                    FOR (alias:OntologyAlias)
                    ON (alias.normalized)
                """)
                indexes.append("ont_alias_normalized_idx")
                logger.info("✅ Index ont_alias_normalized_idx créé")
            except Exception as e:
                logger.warning(f"Index ont_alias_normalized_idx existe déjà: {e}")

            # 2. Index sur entity_type (filtrage)
            try:
                session.run("""
                    CREATE INDEX ont_entity_type_idx IF NOT EXISTS
                    FOR (ont:OntologyEntity)
                    ON (ont.entity_type)
                """)
                indexes.append("ont_entity_type_idx")
                logger.info("✅ Index ont_entity_type_idx créé")
            except Exception as e:
                logger.warning(f"Index ont_entity_type_idx existe déjà: {e}")

            # 3. Index sur canonical_name (lowercase pour search)
            try:
                session.run("""
                    CREATE INDEX ont_canonical_lower_idx IF NOT EXISTS
                    FOR (ont:OntologyEntity)
                    ON (ont.canonical_name)
                """)
                indexes.append("ont_canonical_lower_idx")
                logger.info("✅ Index ont_canonical_lower_idx créé")
            except Exception as e:
                logger.warning(f"Index ont_canonical_lower_idx existe déjà: {e}")

            # 4. Index sur tenant_id (multi-tenancy)
            try:
                session.run("""
                    CREATE INDEX ont_tenant_idx IF NOT EXISTS
                    FOR (ont:OntologyEntity)
                    ON (ont.tenant_id)
                """)
                indexes.append("ont_tenant_idx")
                logger.info("✅ Index ont_tenant_idx créé")
            except Exception as e:
                logger.warning(f"Index ont_tenant_idx existe déjà: {e}")

        return indexes

    def validate_schema(self) -> dict:
        """
        Valide que le schéma est correctement créé.

        Returns:
            Dict avec statut validation
        """
        with self.driver.session() as session:
            # Vérifier contraintes
            result = session.run("SHOW CONSTRAINTS")
            constraints = [record["name"] for record in result]

            # Vérifier index
            result = session.run("SHOW INDEXES")
            indexes = [record["name"] for record in result]

            return {
                "constraints": constraints,
                "indexes": indexes,
                "valid": (
                    "ont_entity_id_unique" in constraints and
                    "ont_alias_normalized_idx" in indexes
                )
            }


def apply_ontology_schema(neo4j_uri: str, neo4j_user: str, neo4j_password: str):
    """
    Point d'entrée : applique schéma complet.

    Args:
        neo4j_uri: URI Neo4j
        neo4j_user: Username
        neo4j_password: Password
    """
    driver = GraphDatabase.driver(neo4j_uri, auth=(neo4j_user, neo4j_password))

    try:
        schema = OntologySchema(driver)

        logger.info("🚀 Application schéma Neo4j ontologies...")

        # Créer contraintes
        constraints = schema.create_constraints()
        logger.info(f"✅ {len(constraints)} contraintes créées")

        # Créer index
        indexes = schema.create_indexes()
        logger.info(f"✅ {len(indexes)} index créés")

        # Valider
        validation = schema.validate_schema()
        if validation["valid"]:
            logger.info("✅ Schéma validé avec succès")
        else:
            logger.error("❌ Schéma invalide")
            logger.error(f"Contraintes: {validation['constraints']}")
            logger.error(f"Index: {validation['indexes']}")

        return validation

    finally:
        driver.close()


if __name__ == "__main__":
    import os
    from dotenv import load_dotenv

    load_dotenv()

    apply_ontology_schema(
        neo4j_uri=os.getenv("NEO4J_URI", "bolt://localhost:7687"),
        neo4j_user=os.getenv("NEO4J_USER", "neo4j"),
        neo4j_password=os.getenv("NEO4J_PASSWORD", "password")
    )
