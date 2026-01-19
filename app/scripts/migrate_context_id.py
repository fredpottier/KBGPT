#!/usr/bin/env python3
"""
Migration: Add context_id to ProtoConcepts from CoverageChunks

ADR: doc/ongoing/ADR_STRUCTURAL_CONTEXT_ALIGNMENT.md

Ce script:
1. Pour les ProtoConcepts existants avec ANCHORED_IN vers CoverageChunk,
   récupère le context_id du chunk et le stocke sur le ProtoConcept
2. Crée l'index Neo4j sur (tenant_id, context_id)
3. Vérifie la cohérence des données

Usage:
    docker-compose exec app python scripts/migrate_context_id.py
    docker-compose exec app python scripts/migrate_context_id.py --dry-run
    docker-compose exec app python scripts/migrate_context_id.py --verify

Author: OSMOSE
Date: 2026-01-11
"""

import argparse
import logging
import sys

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
logger = logging.getLogger(__name__)


def migrate_context_ids(
    tenant_id: str = "default",
    dry_run: bool = False,
) -> dict:
    """
    Migre les ProtoConcepts existants pour ajouter context_id depuis CoverageChunks.

    Args:
        tenant_id: ID du tenant
        dry_run: Si True, n'applique pas les changements

    Returns:
        Dict avec statistiques de migration
    """
    from knowbase.common.clients.neo4j_client import Neo4jClient
    from knowbase.config.settings import get_settings

    settings = get_settings()
    neo4j = Neo4jClient(
        uri=settings.neo4j_uri,
        user=settings.neo4j_user,
        password=settings.neo4j_password
    )

    stats = {
        "protos_without_context_id": 0,
        "protos_updated": 0,
        "protos_no_chunk": 0,
        "index_created": False,
        "errors": []
    }

    logger.info(f"[OSMOSE:Migration] Starting context_id migration for tenant={tenant_id} (dry_run={dry_run})")

    with neo4j.driver.session(database="neo4j") as session:
        # 1. Compter les ProtoConcepts sans context_id
        count_query = """
        MATCH (p:ProtoConcept {tenant_id: $tenant_id})
        WHERE p.context_id IS NULL
        RETURN count(p) AS count
        """
        result = session.run(count_query, tenant_id=tenant_id)
        stats["protos_without_context_id"] = result.single()["count"]

        logger.info(f"[OSMOSE:Migration] Found {stats['protos_without_context_id']} ProtoConcepts without context_id")

        if stats["protos_without_context_id"] == 0:
            logger.info("[OSMOSE:Migration] No ProtoConcepts to migrate")
        else:
            # 2. Migrer via ANCHORED_IN → DocumentChunk.context_id
            migrate_query = """
            MATCH (p:ProtoConcept {tenant_id: $tenant_id})
            WHERE p.context_id IS NULL
            MATCH (p)-[:ANCHORED_IN]->(dc:DocumentChunk {tenant_id: $tenant_id})
            WHERE dc.context_id IS NOT NULL
            WITH p, dc.context_id AS ctx_id
            SET p.context_id = ctx_id
            RETURN count(p) AS updated
            """

            if not dry_run:
                result = session.run(migrate_query, tenant_id=tenant_id)
                stats["protos_updated"] = result.single()["updated"]
                logger.info(f"[OSMOSE:Migration] Updated {stats['protos_updated']} ProtoConcepts via ANCHORED_IN")
            else:
                # Dry run - compter combien seraient migrés
                count_migratable = """
                MATCH (p:ProtoConcept {tenant_id: $tenant_id})
                WHERE p.context_id IS NULL
                MATCH (p)-[:ANCHORED_IN]->(dc:DocumentChunk {tenant_id: $tenant_id})
                WHERE dc.context_id IS NOT NULL
                RETURN count(DISTINCT p) AS count
                """
                result = session.run(count_migratable, tenant_id=tenant_id)
                stats["protos_updated"] = result.single()["count"]
                logger.info(f"[OSMOSE:Migration] [DRY-RUN] Would update {stats['protos_updated']} ProtoConcepts")

            # 3. Compter les protos sans chunk avec context_id
            no_chunk_query = """
            MATCH (p:ProtoConcept {tenant_id: $tenant_id})
            WHERE p.context_id IS NULL
            AND NOT EXISTS {
                MATCH (p)-[:ANCHORED_IN]->(dc:DocumentChunk)
                WHERE dc.context_id IS NOT NULL
            }
            RETURN count(p) AS count
            """
            result = session.run(no_chunk_query, tenant_id=tenant_id)
            stats["protos_no_chunk"] = result.single()["count"]

            if stats["protos_no_chunk"] > 0:
                logger.warning(
                    f"[OSMOSE:Migration] {stats['protos_no_chunk']} ProtoConcepts cannot be migrated "
                    f"(no ANCHORED_IN to chunk with context_id)"
                )

        # 4. Créer l'index si pas dry_run
        if not dry_run:
            try:
                index_query = """
                CREATE INDEX proto_context_id IF NOT EXISTS
                FOR (p:ProtoConcept) ON (p.tenant_id, p.context_id)
                """
                session.run(index_query)
                stats["index_created"] = True
                logger.info("[OSMOSE:Migration] Created index proto_context_id")
            except Exception as e:
                logger.warning(f"[OSMOSE:Migration] Index creation failed (may already exist): {e}")

    # Résumé
    logger.info(
        f"[OSMOSE:Migration] Migration complete: "
        f"protos_updated={stats['protos_updated']}, "
        f"protos_no_chunk={stats['protos_no_chunk']}, "
        f"index_created={stats['index_created']}"
    )

    return stats


def verify_migration(tenant_id: str = "default") -> dict:
    """
    Vérifie que la migration context_id a bien été appliquée.

    Returns:
        Dict avec statistiques de vérification
    """
    from knowbase.common.clients.neo4j_client import Neo4jClient
    from knowbase.config.settings import get_settings

    settings = get_settings()
    neo4j = Neo4jClient(
        uri=settings.neo4j_uri,
        user=settings.neo4j_user,
        password=settings.neo4j_password
    )

    stats = {
        "total_protos": 0,
        "protos_with_context_id": 0,
        "protos_without_context_id": 0,
        "mentioned_in_count": 0,
        "mentioned_in_per_concept_avg": 0.0,
        "index_exists": False
    }

    with neo4j.driver.session(database="neo4j") as session:
        # Comptage ProtoConcepts
        proto_query = """
        MATCH (p:ProtoConcept {tenant_id: $tenant_id})
        RETURN count(p) AS total,
               sum(CASE WHEN p.context_id IS NOT NULL THEN 1 ELSE 0 END) AS with_ctx,
               sum(CASE WHEN p.context_id IS NULL THEN 1 ELSE 0 END) AS without_ctx
        """
        result = session.run(proto_query, tenant_id=tenant_id)
        record = result.single()
        stats["total_protos"] = record["total"]
        stats["protos_with_context_id"] = record["with_ctx"]
        stats["protos_without_context_id"] = record["without_ctx"]

        # Comptage MENTIONED_IN
        mentioned_query = """
        MATCH (:CanonicalConcept {tenant_id: $tenant_id})-[r:MENTIONED_IN]->(:SectionContext)
        RETURN count(r) AS count
        """
        result = session.run(mentioned_query, tenant_id=tenant_id)
        stats["mentioned_in_count"] = result.single()["count"]

        # Moyenne MENTIONED_IN par concept
        avg_query = """
        MATCH (cc:CanonicalConcept {tenant_id: $tenant_id})
        OPTIONAL MATCH (cc)-[r:MENTIONED_IN]->(:SectionContext)
        WITH cc, count(r) AS rel_count
        RETURN avg(rel_count) AS avg_count
        """
        result = session.run(avg_query, tenant_id=tenant_id)
        avg = result.single()["avg_count"]
        stats["mentioned_in_per_concept_avg"] = float(avg) if avg else 0.0

        # Vérifier l'index
        index_query = """
        SHOW INDEXES
        YIELD name, labelsOrTypes, properties
        WHERE 'ProtoConcept' IN labelsOrTypes AND 'context_id' IN properties
        RETURN name
        """
        try:
            result = session.run(index_query)
            stats["index_exists"] = result.single() is not None
        except Exception:
            stats["index_exists"] = False

    # Calcul couverture
    coverage = (
        stats["protos_with_context_id"] / stats["total_protos"] * 100
        if stats["total_protos"] > 0 else 0
    )

    logger.info(
        f"[OSMOSE:Migration] Verification: "
        f"total_protos={stats['total_protos']}, "
        f"with_context_id={stats['protos_with_context_id']} ({coverage:.1f}%), "
        f"MENTIONED_IN={stats['mentioned_in_count']}, "
        f"avg_per_concept={stats['mentioned_in_per_concept_avg']:.1f}, "
        f"index_exists={stats['index_exists']}"
    )

    # Alertes
    if stats["mentioned_in_per_concept_avg"] > 100:
        logger.warning(
            f"[OSMOSE:Migration] ⚠️ MENTIONED_IN per concept is HIGH ({stats['mentioned_in_per_concept_avg']:.1f}). "
            f"Expected <10 after ADR fix. You may need to re-run Pass 2."
        )
    elif stats["mentioned_in_per_concept_avg"] < 10:
        logger.info(
            f"[OSMOSE:Migration] ✅ MENTIONED_IN per concept looks good ({stats['mentioned_in_per_concept_avg']:.1f})"
        )

    return stats


def main():
    parser = argparse.ArgumentParser(
        description="Migration: Add context_id to ProtoConcepts (ADR_STRUCTURAL_CONTEXT_ALIGNMENT)"
    )
    parser.add_argument(
        "--tenant-id",
        default="default",
        help="Tenant ID (default: 'default')"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Simulate migration without applying changes"
    )
    parser.add_argument(
        "--verify",
        action="store_true",
        help="Verify migration status only"
    )

    args = parser.parse_args()

    try:
        if args.verify:
            verify_migration(args.tenant_id)
        else:
            migrate_context_ids(
                tenant_id=args.tenant_id,
                dry_run=args.dry_run,
            )
            # Vérification automatique après migration
            if not args.dry_run:
                logger.info("[OSMOSE:Migration] Running verification...")
                verify_migration(args.tenant_id)

    except Exception as e:
        logger.error(f"[OSMOSE:Migration] Migration failed: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
