#!/usr/bin/env python3
"""
Script de migration : Ajouter name et summary aux CanonicalConcepts existants.

Problème identifié : Les CanonicalConcepts créés avant Phase 2 POC n'ont pas
les propriétés `name` et `summary`, causant des erreurs dans l'API Concept Explainer.

Solution :
- name = canonical_name (si name manquant)
- summary = unified_definition (si summary manquant)

Usage:
    python scripts/migrate_canonical_concepts_names.py [--dry-run] [--tenant-id default]
"""

import argparse
import logging
import sys
from pathlib import Path

# Ajouter le répertoire src au PYTHONPATH
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from neo4j import GraphDatabase
from knowbase.config.settings import get_settings

# Configuration logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def migrate_canonical_concepts(
    neo4j_uri: str,
    neo4j_user: str,
    neo4j_password: str,
    neo4j_database: str = "neo4j",
    tenant_id: str = "default",
    dry_run: bool = False
):
    """
    Migrer les CanonicalConcepts existants pour ajouter name et summary.

    Args:
        neo4j_uri: URI Neo4j
        neo4j_user: Utilisateur Neo4j
        neo4j_password: Mot de passe Neo4j
        neo4j_database: Base de données Neo4j
        tenant_id: ID tenant (default: "default")
        dry_run: Si True, affiche seulement ce qui serait fait sans modifier
    """
    driver = GraphDatabase.driver(neo4j_uri, auth=(neo4j_user, neo4j_password))

    try:
        with driver.session(database=neo4j_database) as session:
            # Étape 1: Compter concepts à migrer
            count_query = """
            MATCH (c:CanonicalConcept {tenant_id: $tenant_id})
            WHERE c.name IS NULL OR c.summary IS NULL
            RETURN COUNT(c) AS total_to_migrate
            """

            result = session.run(count_query, tenant_id=tenant_id)
            record = result.single()
            total_to_migrate = record["total_to_migrate"] if record else 0

            logger.info(f"🔍 Trouvé {total_to_migrate} CanonicalConcepts à migrer (tenant={tenant_id})")

            if total_to_migrate == 0:
                logger.info("✅ Tous les CanonicalConcepts ont déjà name et summary")
                return

            # Étape 2: Récupérer échantillon pour affichage
            sample_query = """
            MATCH (c:CanonicalConcept {tenant_id: $tenant_id})
            WHERE c.name IS NULL OR c.summary IS NULL
            RETURN c.canonical_id AS id,
                   c.canonical_name AS canonical_name,
                   c.unified_definition AS unified_definition,
                   c.name AS current_name,
                   c.summary AS current_summary
            LIMIT 5
            """

            result = session.run(sample_query, tenant_id=tenant_id)

            logger.info("\n📋 Échantillon de concepts à migrer :")
            for i, record in enumerate(result, 1):
                logger.info(
                    f"  {i}. ID: {record['id'][:8]}...\n"
                    f"     canonical_name: {record['canonical_name']}\n"
                    f"     unified_definition: {record['unified_definition'][:80] if record['unified_definition'] else 'None'}...\n"
                    f"     current name: {record['current_name']}\n"
                    f"     current summary: {record['current_summary']}\n"
                )

            if dry_run:
                logger.info("\n🔍 DRY-RUN MODE : Aucune modification effectuée")
                logger.info(f"   Exécuter sans --dry-run pour migrer {total_to_migrate} concepts")
                return

            # Étape 3: Migration
            migration_query = """
            MATCH (c:CanonicalConcept {tenant_id: $tenant_id})
            WHERE c.name IS NULL OR c.summary IS NULL

            SET c.name = COALESCE(c.name, c.canonical_name),
                c.summary = COALESCE(c.summary, c.unified_definition)

            RETURN COUNT(c) AS migrated_count
            """

            logger.info(f"\n🔄 Migration en cours de {total_to_migrate} concepts...")

            result = session.run(migration_query, tenant_id=tenant_id)
            record = result.single()
            migrated_count = record["migrated_count"] if record else 0

            logger.info(f"✅ Migration terminée : {migrated_count} CanonicalConcepts mis à jour")

            # Étape 4: Vérification
            verify_query = """
            MATCH (c:CanonicalConcept {tenant_id: $tenant_id})
            WHERE c.name IS NULL OR c.summary IS NULL
            RETURN COUNT(c) AS remaining
            """

            result = session.run(verify_query, tenant_id=tenant_id)
            record = result.single()
            remaining = record["remaining"] if record else 0

            if remaining == 0:
                logger.info("✅ Vérification : Tous les concepts ont maintenant name et summary")
            else:
                logger.warning(f"⚠️ Vérification : {remaining} concepts n'ont toujours pas name/summary")

            # Étape 5: Afficher échantillon après migration
            sample_after_query = """
            MATCH (c:CanonicalConcept {tenant_id: $tenant_id})
            RETURN c.canonical_id AS id,
                   c.name AS name,
                   c.summary AS summary
            LIMIT 3
            """

            result = session.run(sample_after_query, tenant_id=tenant_id)

            logger.info("\n📋 Échantillon après migration :")
            for i, record in enumerate(result, 1):
                logger.info(
                    f"  {i}. ID: {record['id'][:8]}...\n"
                    f"     name: {record['name']}\n"
                    f"     summary: {record['summary'][:80] if record['summary'] else 'None'}...\n"
                )

    finally:
        driver.close()


def main():
    """Point d'entrée principal."""
    parser = argparse.ArgumentParser(
        description="Migrer CanonicalConcepts pour ajouter name et summary"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Afficher ce qui serait fait sans modifier la base"
    )
    parser.add_argument(
        "--tenant-id",
        default="default",
        help="ID du tenant à migrer (default: 'default')"
    )

    args = parser.parse_args()

    # Charger configuration
    settings = get_settings()

    logger.info("=" * 80)
    logger.info("Migration CanonicalConcepts : Ajout name et summary")
    logger.info("=" * 80)
    logger.info(f"Neo4j URI: {settings.neo4j_uri}")
    logger.info(f"Tenant ID: {args.tenant_id}")
    logger.info(f"Mode: {'DRY-RUN (aucune modification)' if args.dry_run else 'MIGRATION (modifications actives)'}")
    logger.info("=" * 80)

    try:
        migrate_canonical_concepts(
            neo4j_uri=settings.neo4j_uri,
            neo4j_user=settings.neo4j_user,
            neo4j_password=settings.neo4j_password,
            neo4j_database="neo4j",
            tenant_id=args.tenant_id,
            dry_run=args.dry_run
        )

        logger.info("\n" + "=" * 80)
        logger.info("✅ Migration terminée avec succès !")
        logger.info("=" * 80)

    except Exception as e:
        logger.error(f"\n❌ Erreur durant la migration : {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
