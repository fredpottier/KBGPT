#!/usr/bin/env python3
"""
Phase 2.9.2 - Script de migration: Backfill occurrence_count

Ce script calcule et met à jour le champ occurrence_count pour tous les
CanonicalConcepts existants en se basant sur:
1. Le nombre de ProtoConcepts liés (PROMOTED_TO)
2. Le nombre de chunk_ids associés

Usage:
    docker exec knowbase-app python /app/scripts/backfill_occurrence_count.py [--dry-run] [--tenant-id default]

Auteur: Claude Code
Date: 2025-12-21
"""

import argparse
import logging
import sys

sys.path.insert(0, "/app/src")

from neo4j import GraphDatabase

logging.basicConfig(
    level=logging.INFO,
    format="[MIGRATION] %(asctime)s - %(levelname)s - %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
logger = logging.getLogger(__name__)

NEO4J_URI = "bolt://neo4j:7687"
NEO4J_USER = "neo4j"
NEO4J_PASSWORD = "graphiti_neo4j_pass"


def get_driver():
    return GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))


def backfill_occurrence_count(session, tenant_id: str, dry_run: bool = False):
    """
    Calcule et met à jour occurrence_count pour tous les CanonicalConcepts.

    Stratégie:
    - occurrence_count = nombre de ProtoConcepts liés via PROMOTED_TO
    - Si 0 protos, utilise SIZE(chunk_ids) comme fallback
    """

    # Requête pour calculer les occurrences
    count_query = """
    MATCH (c:CanonicalConcept {tenant_id: $tenant_id})
    OPTIONAL MATCH (proto:ProtoConcept)-[:PROMOTED_TO]->(c)
    WITH c,
         COUNT(proto) AS proto_count,
         COALESCE(SIZE(c.chunk_ids), 0) AS chunk_count
    WITH c,
         CASE WHEN proto_count > 0 THEN proto_count ELSE chunk_count END AS occurrence
    RETURN c.canonical_id AS canonical_id,
           c.canonical_name AS canonical_name,
           occurrence,
           COALESCE(c.occurrence_count, 0) AS current_count
    ORDER BY occurrence DESC
    """

    result = session.run(count_query, tenant_id=tenant_id)
    records = [dict(record) for record in result]

    logger.info(f"Found {len(records)} CanonicalConcepts to process")

    if not records:
        logger.info("No concepts to update")
        return

    # Stats
    updated_count = 0
    skipped_count = 0
    total_occurrence = 0

    for record in records:
        canonical_id = record["canonical_id"]
        canonical_name = record["canonical_name"]
        new_occurrence = record["occurrence"]
        current_count = record["current_count"]
        total_occurrence += new_occurrence

        # Skip si déjà à jour
        if current_count == new_occurrence and new_occurrence > 0:
            skipped_count += 1
            continue

        if dry_run:
            logger.info(
                f"[DRY-RUN] Would update '{canonical_name}': "
                f"occurrence_count {current_count} -> {new_occurrence}"
            )
            updated_count += 1
        else:
            # Mettre à jour
            update_query = """
            MATCH (c:CanonicalConcept {tenant_id: $tenant_id, canonical_id: $canonical_id})
            SET c.occurrence_count = $occurrence,
                c.updated_at = datetime()
            RETURN c.canonical_id AS id
            """
            update_result = session.run(
                update_query,
                tenant_id=tenant_id,
                canonical_id=canonical_id,
                occurrence=new_occurrence
            )

            if update_result.single():
                updated_count += 1
                if updated_count <= 10:  # Log les 10 premiers
                    logger.info(
                        f"Updated '{canonical_name}': occurrence_count = {new_occurrence}"
                    )

    # Résumé
    logger.info("=" * 60)
    logger.info("SUMMARY")
    logger.info("=" * 60)
    logger.info(f"Total concepts: {len(records)}")
    logger.info(f"Updated: {updated_count}")
    logger.info(f"Skipped (already up to date): {skipped_count}")
    logger.info(f"Total occurrences: {total_occurrence}")
    logger.info(f"Average occurrence: {total_occurrence / len(records):.1f}")


def create_index_if_not_exists(session, tenant_id: str):
    """Crée un index sur occurrence_count pour optimiser les requêtes."""

    # Vérifier si l'index existe
    check_query = """
    SHOW INDEXES
    YIELD name, labelsOrTypes, properties
    WHERE 'CanonicalConcept' IN labelsOrTypes
    AND 'occurrence_count' IN properties
    RETURN name
    """

    result = session.run(check_query)
    existing = result.single()

    if existing:
        logger.info(f"Index already exists: {existing['name']}")
        return

    # Créer l'index
    create_query = """
    CREATE INDEX canonical_occurrence_count IF NOT EXISTS
    FOR (c:CanonicalConcept)
    ON (c.tenant_id, c.occurrence_count)
    """

    try:
        session.run(create_query)
        logger.info("Created index on (tenant_id, occurrence_count)")
    except Exception as e:
        logger.warning(f"Could not create index: {e}")


def main():
    parser = argparse.ArgumentParser(
        description="Backfill occurrence_count for CanonicalConcepts (Phase 2.9.2)"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be done without executing"
    )
    parser.add_argument(
        "--tenant-id",
        default="default",
        help="Tenant ID"
    )
    parser.add_argument(
        "--create-index",
        action="store_true",
        help="Create index on occurrence_count"
    )
    args = parser.parse_args()

    logger.info("=" * 60)
    logger.info("BACKFILL OCCURRENCE_COUNT - Phase 2.9.2")
    logger.info("=" * 60)
    logger.info(f"Tenant: {args.tenant_id}")
    logger.info(f"Mode: {'DRY-RUN' if args.dry_run else 'EXECUTION'}")

    driver = get_driver()

    try:
        with driver.session() as session:
            # Créer index si demandé
            if args.create_index:
                create_index_if_not_exists(session, args.tenant_id)

            # Backfill occurrence_count
            backfill_occurrence_count(session, args.tenant_id, args.dry_run)

    except Exception as e:
        logger.error(f"Error during migration: {e}")
        raise
    finally:
        driver.close()


if __name__ == "__main__":
    main()
