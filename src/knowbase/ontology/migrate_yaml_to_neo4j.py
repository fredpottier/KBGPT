"""
Migration ontologies YAML vers Neo4j.

Migre tous les fichiers config/ontologies/*.yaml vers :OntologyEntity + :OntologyAlias.
"""
from pathlib import Path
from typing import Dict, List
import yaml
import uuid
from datetime import datetime, timezone
from neo4j import GraphDatabase
import logging

logger = logging.getLogger(__name__)


class YAMLToNeo4jMigrator:
    """Migre ontologies YAML vers Neo4j."""

    def __init__(self, driver: GraphDatabase.driver, ontology_dir: Path):
        self.driver = driver
        self.ontology_dir = ontology_dir

    def migrate_all(self, tenant_id: str = "default") -> dict:
        """
        Migre tous les fichiers YAML vers Neo4j.

        Args:
            tenant_id: Tenant ID pour multi-tenancy

        Returns:
            Dict avec statistiques migration
        """
        stats = {
            "files_processed": 0,
            "entities_created": 0,
            "aliases_created": 0,
            "errors": []
        }

        yaml_files = list(self.ontology_dir.glob("*.yaml"))
        logger.info(f"🔍 Trouvé {len(yaml_files)} fichiers YAML à migrer")

        for yaml_file in yaml_files:
            # Skip fichiers spéciaux
            if yaml_file.name in ["uncataloged_entities.log", "README.md"]:
                continue

            try:
                logger.info(f"📄 Migration {yaml_file.name}...")
                file_stats = self._migrate_file(yaml_file, tenant_id)

                stats["files_processed"] += 1
                stats["entities_created"] += file_stats["entities"]
                stats["aliases_created"] += file_stats["aliases"]

                logger.info(
                    f"✅ {yaml_file.name}: {file_stats['entities']} entités, "
                    f"{file_stats['aliases']} aliases"
                )

            except Exception as e:
                error_msg = f"Erreur migration {yaml_file.name}: {e}"
                logger.error(error_msg)
                stats["errors"].append(error_msg)

        return stats

    def _migrate_file(self, yaml_file: Path, tenant_id: str) -> dict:
        """
        Migre un fichier YAML vers Neo4j.

        Args:
            yaml_file: Chemin fichier YAML
            tenant_id: Tenant ID

        Returns:
            Dict avec stats fichier
        """
        with open(yaml_file, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)

        stats = {"entities": 0, "aliases": 0}

        # Structure attendue: {ENTITY_TYPE: {ENTITY_ID: {...}}}
        for entity_type_key, entities in data.items():
            if not isinstance(entities, dict):
                continue

            # entity_type_key peut être "SOLUTION", "SOLUTIONS", etc.
            # Normaliser vers singulier UPPERCASE
            entity_type = entity_type_key.rstrip('S').upper()

            for entity_id, entity_data in entities.items():
                # Créer OntologyEntity
                self._create_ontology_entity(
                    entity_id=entity_id,
                    canonical_name=entity_data["canonical_name"],
                    entity_type=entity_type,
                    category=entity_data.get("category"),
                    vendor=entity_data.get("vendor"),
                    description=entity_data.get("description"),
                    tenant_id=tenant_id
                )
                stats["entities"] += 1

                # Créer aliases
                aliases = entity_data.get("aliases", [])
                # Ajouter canonical_name comme alias aussi
                aliases.append(entity_data["canonical_name"])

                for alias in set(aliases):  # set() pour éviter doublons
                    self._create_alias(
                        entity_id=entity_id,
                        alias=alias,
                        entity_type=entity_type,
                        tenant_id=tenant_id
                    )
                    stats["aliases"] += 1

        return stats

    def _create_ontology_entity(
        self,
        entity_id: str,
        canonical_name: str,
        entity_type: str,
        category: str = None,
        vendor: str = None,
        description: str = None,
        tenant_id: str = "default"
    ):
        """Crée OntologyEntity dans Neo4j."""

        with self.driver.session() as session:
            session.run("""
                MERGE (ont:OntologyEntity {entity_id: $entity_id})
                SET ont.canonical_name = $canonical_name,
                    ont.entity_type = $entity_type,
                    ont.category = $category,
                    ont.vendor = $vendor,
                    ont.description = $description,
                    ont.source = 'yaml_migrated',
                    ont.version = '1.0.0',
                    ont.tenant_id = $tenant_id,
                    ont.created_at = coalesce(ont.created_at, datetime()),
                    ont.updated_at = datetime()
            """, {
                "entity_id": entity_id,
                "canonical_name": canonical_name,
                "entity_type": entity_type,
                "category": category,
                "vendor": vendor,
                "description": description,
                "tenant_id": tenant_id
            })

    def _create_alias(
        self,
        entity_id: str,
        alias: str,
        entity_type: str,
        tenant_id: str = "default"
    ):
        """Crée OntologyAlias et relation avec OntologyEntity."""

        alias_id = str(uuid.uuid4())
        normalized = alias.lower().strip()

        with self.driver.session() as session:
            session.run("""
                MATCH (ont:OntologyEntity {entity_id: $entity_id})
                MERGE (alias:OntologyAlias {
                    normalized: $normalized,
                    entity_type: $entity_type,
                    tenant_id: $tenant_id
                })
                ON CREATE SET
                    alias.alias_id = $alias_id,
                    alias.alias = $alias
                MERGE (ont)-[:HAS_ALIAS]->(alias)
            """, {
                "entity_id": entity_id,
                "alias_id": alias_id,
                "alias": alias,
                "normalized": normalized,
                "entity_type": entity_type,
                "tenant_id": tenant_id
            })

    def validate_migration(self) -> dict:
        """
        Valide que la migration est complète.

        Returns:
            Dict avec statistiques validation
        """
        with self.driver.session() as session:
            # Compter entités
            result = session.run("""
                MATCH (ont:OntologyEntity)
                RETURN count(ont) AS entities_count
            """)
            entities_count = result.single()["entities_count"]

            # Compter aliases
            result = session.run("""
                MATCH (alias:OntologyAlias)
                RETURN count(alias) AS aliases_count
            """)
            aliases_count = result.single()["aliases_count"]

            # Vérifier relations
            result = session.run("""
                MATCH (ont:OntologyEntity)-[:HAS_ALIAS]->(alias:OntologyAlias)
                RETURN count(*) AS relations_count
            """)
            relations_count = result.single()["relations_count"]

            # Entités sans alias (problème)
            result = session.run("""
                MATCH (ont:OntologyEntity)
                WHERE NOT (ont)-[:HAS_ALIAS]->()
                RETURN count(ont) AS orphan_count
            """)
            orphan_count = result.single()["orphan_count"]

            return {
                "entities": entities_count,
                "aliases": aliases_count,
                "relations": relations_count,
                "orphans": orphan_count,
                "valid": orphan_count == 0
            }


def run_migration(
    neo4j_uri: str,
    neo4j_user: str,
    neo4j_password: str,
    ontology_dir: Path,
    tenant_id: str = "default"
):
    """
    Point d'entrée migration.

    Args:
        neo4j_uri: URI Neo4j
        neo4j_user: Username
        neo4j_password: Password
        ontology_dir: Chemin répertoire ontologies YAML
        tenant_id: Tenant ID
    """
    driver = GraphDatabase.driver(neo4j_uri, auth=(neo4j_user, neo4j_password))

    try:
        migrator = YAMLToNeo4jMigrator(driver, ontology_dir)

        logger.info("🚀 Démarrage migration YAML → Neo4j...")

        # Exécuter migration
        stats = migrator.migrate_all(tenant_id)

        logger.info("=" * 60)
        logger.info("📊 STATISTIQUES MIGRATION")
        logger.info(f"Fichiers traités   : {stats['files_processed']}")
        logger.info(f"Entités créées     : {stats['entities_created']}")
        logger.info(f"Aliases créés      : {stats['aliases_created']}")
        logger.info(f"Erreurs            : {len(stats['errors'])}")
        if stats['errors']:
            for error in stats['errors']:
                logger.error(f"  - {error}")
        logger.info("=" * 60)

        # Validation
        logger.info("🔍 Validation migration...")
        validation = migrator.validate_migration()

        logger.info("📊 VALIDATION")
        logger.info(f"Entités totales    : {validation['entities']}")
        logger.info(f"Aliases totaux     : {validation['aliases']}")
        logger.info(f"Relations          : {validation['relations']}")
        logger.info(f"Orphelins (erreur) : {validation['orphans']}")

        if validation["valid"]:
            logger.info("✅ Migration validée avec succès !")
        else:
            logger.error("❌ Migration incomplète (entités orphelines)")

        return stats, validation

    finally:
        driver.close()


if __name__ == "__main__":
    import os
    from dotenv import load_dotenv

    load_dotenv()

    run_migration(
        neo4j_uri=os.getenv("NEO4J_URI", "bolt://localhost:7687"),
        neo4j_user=os.getenv("NEO4J_USER", "neo4j"),
        neo4j_password=os.getenv("NEO4J_PASSWORD", "password"),
        ontology_dir=Path("config/ontologies"),
        tenant_id="default"
    )
