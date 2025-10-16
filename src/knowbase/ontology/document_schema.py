"""
Schéma Neo4j pour Document Backbone - Phase 1.

Gère le cycle de vie documentaire avec versioning, lineage et provenance.
"""
from neo4j import GraphDatabase
from typing import List, Dict
import logging

logger = logging.getLogger(__name__)


class DocumentSchema:
    """Gestion schéma Neo4j pour documents et versions."""

    def __init__(self, driver: GraphDatabase.driver):
        self.driver = driver

    def create_constraints(self) -> List[str]:
        """
        Crée toutes les contraintes nécessaires pour Document et DocumentVersion.

        Returns:
            Liste des contraintes créées
        """
        constraints = []

        with self.driver.session() as session:
            # 1. Contrainte unicité document_id
            try:
                session.run("""
                    CREATE CONSTRAINT doc_id_unique IF NOT EXISTS
                    FOR (d:Document)
                    REQUIRE d.document_id IS UNIQUE
                """)
                constraints.append("doc_id_unique")
                logger.info("✅ Contrainte doc_id_unique créée")
            except Exception as e:
                logger.warning(f"Contrainte doc_id_unique existe déjà: {e}")

            # 2. Contrainte unicité version_id
            try:
                session.run("""
                    CREATE CONSTRAINT doc_version_id_unique IF NOT EXISTS
                    FOR (v:DocumentVersion)
                    REQUIRE v.version_id IS UNIQUE
                """)
                constraints.append("doc_version_id_unique")
                logger.info("✅ Contrainte doc_version_id_unique créée")
            except Exception as e:
                logger.warning(f"Contrainte doc_version_id_unique existe déjà: {e}")

            # 3. Contrainte unicité checksum (anti-duplicatas)
            try:
                session.run("""
                    CREATE CONSTRAINT doc_version_checksum_unique IF NOT EXISTS
                    FOR (v:DocumentVersion)
                    REQUIRE v.checksum IS UNIQUE
                """)
                constraints.append("doc_version_checksum_unique")
                logger.info("✅ Contrainte doc_version_checksum_unique créée")
            except Exception as e:
                logger.warning(f"Contrainte doc_version_checksum_unique existe déjà: {e}")

            # 4. Contrainte unicité source_path (un document par source)
            try:
                session.run("""
                    CREATE CONSTRAINT doc_source_path_unique IF NOT EXISTS
                    FOR (d:Document)
                    REQUIRE d.source_path IS UNIQUE
                """)
                constraints.append("doc_source_path_unique")
                logger.info("✅ Contrainte doc_source_path_unique créée")
            except Exception as e:
                logger.warning(f"Contrainte doc_source_path_unique existe déjà: {e}")

        return constraints

    def create_indexes(self) -> List[str]:
        """
        Crée tous les index pour performance.

        Returns:
            Liste des index créés
        """
        indexes = []

        with self.driver.session() as session:
            # 1. Index sur source_path (lookup principal)
            try:
                session.run("""
                    CREATE INDEX doc_source_path_idx IF NOT EXISTS
                    FOR (d:Document)
                    ON (d.source_path)
                """)
                indexes.append("doc_source_path_idx")
                logger.info("✅ Index doc_source_path_idx créé")
            except Exception as e:
                logger.warning(f"Index doc_source_path_idx existe déjà: {e}")

            # 2. Index sur tenant_id (multi-tenancy)
            try:
                session.run("""
                    CREATE INDEX doc_tenant_idx IF NOT EXISTS
                    FOR (d:Document)
                    ON (d.tenant_id)
                """)
                indexes.append("doc_tenant_idx")
                logger.info("✅ Index doc_tenant_idx créé")
            except Exception as e:
                logger.warning(f"Index doc_tenant_idx existe déjà: {e}")

            # 3. Index sur version_label (ex: "v1.0", "v2.1")
            try:
                session.run("""
                    CREATE INDEX doc_version_label_idx IF NOT EXISTS
                    FOR (v:DocumentVersion)
                    ON (v.version_label)
                """)
                indexes.append("doc_version_label_idx")
                logger.info("✅ Index doc_version_label_idx créé")
            except Exception as e:
                logger.warning(f"Index doc_version_label_idx existe déjà: {e}")

            # 4. Index sur effective_date (queries temporelles)
            try:
                session.run("""
                    CREATE INDEX doc_version_effective_date_idx IF NOT EXISTS
                    FOR (v:DocumentVersion)
                    ON (v.effective_date)
                """)
                indexes.append("doc_version_effective_date_idx")
                logger.info("✅ Index doc_version_effective_date_idx créé")
            except Exception as e:
                logger.warning(f"Index doc_version_effective_date_idx existe déjà: {e}")

            # 5. Index sur checksum (détection duplicatas)
            try:
                session.run("""
                    CREATE INDEX doc_version_checksum_idx IF NOT EXISTS
                    FOR (v:DocumentVersion)
                    ON (v.checksum)
                """)
                indexes.append("doc_version_checksum_idx")
                logger.info("✅ Index doc_version_checksum_idx créé")
            except Exception as e:
                logger.warning(f"Index doc_version_checksum_idx existe déjà: {e}")

            # 6. Index sur is_latest (résolution version courante)
            try:
                session.run("""
                    CREATE INDEX doc_version_is_latest_idx IF NOT EXISTS
                    FOR (v:DocumentVersion)
                    ON (v.is_latest)
                """)
                indexes.append("doc_version_is_latest_idx")
                logger.info("✅ Index doc_version_is_latest_idx créé")
            except Exception as e:
                logger.warning(f"Index doc_version_is_latest_idx existe déjà: {e}")

            # 7. Index composite (document_id + effective_date) pour queries temporelles
            try:
                session.run("""
                    CREATE INDEX doc_version_composite_idx IF NOT EXISTS
                    FOR (v:DocumentVersion)
                    ON (v.document_id, v.effective_date)
                """)
                indexes.append("doc_version_composite_idx")
                logger.info("✅ Index doc_version_composite_idx créé")
            except Exception as e:
                logger.warning(f"Index doc_version_composite_idx existe déjà: {e}")

        return indexes

    def create_relationships_schema(self) -> List[str]:
        """
        Définit les relations attendues dans le schéma.

        Note: Neo4j ne supporte pas les contraintes sur relations,
        cette méthode est documentaire uniquement.

        Relations créées:
        - (Document)-[:HAS_VERSION]->(DocumentVersion)
        - (DocumentVersion)-[:SUPERSEDES]->(DocumentVersion)  # lineage
        - (DocumentVersion)-[:AUTHORED_BY]->(Person)
        - (DocumentVersion)-[:REVIEWED_BY]->(Person)
        - (Episode)-[:FROM_DOCUMENT]->(DocumentVersion)
        """
        relationships = [
            "HAS_VERSION",
            "SUPERSEDES",
            "AUTHORED_BY",
            "REVIEWED_BY",
            "FROM_DOCUMENT"
        ]

        logger.info(f"📋 Relations schéma Document: {relationships}")
        return relationships

    def validate_schema(self) -> Dict[str, any]:
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

            # Vérifier présence minimale requise
            required_constraints = [
                "doc_id_unique",
                "doc_version_id_unique",
                "doc_version_checksum_unique"
            ]

            required_indexes = [
                "doc_source_path_idx",
                "doc_version_label_idx"
            ]

            valid = (
                all(c in constraints for c in required_constraints) and
                all(i in indexes for i in required_indexes)
            )

            return {
                "constraints": constraints,
                "indexes": indexes,
                "relationships": self.create_relationships_schema(),
                "valid": valid,
                "missing_constraints": [c for c in required_constraints if c not in constraints],
                "missing_indexes": [i for i in required_indexes if i not in indexes]
            }


def apply_document_schema(neo4j_uri: str, neo4j_user: str, neo4j_password: str) -> Dict[str, any]:
    """
    Point d'entrée : applique schéma complet Document Backbone.

    Args:
        neo4j_uri: URI Neo4j
        neo4j_user: Username
        neo4j_password: Password

    Returns:
        Dict avec résultat validation
    """
    driver = GraphDatabase.driver(neo4j_uri, auth=(neo4j_user, neo4j_password))

    try:
        schema = DocumentSchema(driver)

        logger.info("🚀 Application schéma Neo4j Document Backbone (Phase 1)...")

        # Créer contraintes
        constraints = schema.create_constraints()
        logger.info(f"✅ {len(constraints)} contraintes créées")

        # Créer index
        indexes = schema.create_indexes()
        logger.info(f"✅ {len(indexes)} index créés")

        # Définir relations
        relationships = schema.create_relationships_schema()
        logger.info(f"📋 {len(relationships)} types de relations définis")

        # Valider
        validation = schema.validate_schema()
        if validation["valid"]:
            logger.info("✅ Schéma Document Backbone validé avec succès")
        else:
            logger.error("❌ Schéma invalide")
            logger.error(f"Contraintes manquantes: {validation['missing_constraints']}")
            logger.error(f"Index manquants: {validation['missing_indexes']}")

        return validation

    finally:
        driver.close()


if __name__ == "__main__":
    import os
    from dotenv import load_dotenv

    load_dotenv()

    validation = apply_document_schema(
        neo4j_uri=os.getenv("NEO4J_URI", "bolt://localhost:7687"),
        neo4j_user=os.getenv("NEO4J_USER", "neo4j"),
        neo4j_password=os.getenv("NEO4J_PASSWORD", "password")
    )

    print("\n📊 Résultat validation schéma Document Backbone:")
    print(f"  - Contraintes: {len(validation['constraints'])}")
    print(f"  - Index: {len(validation['indexes'])}")
    print(f"  - Relations: {len(validation['relationships'])}")
    print(f"  - Valide: {'✅ OUI' if validation['valid'] else '❌ NON'}")

    if not validation['valid']:
        print(f"\n⚠️ Éléments manquants:")
        print(f"  - Contraintes: {validation['missing_constraints']}")
        print(f"  - Index: {validation['missing_indexes']}")
