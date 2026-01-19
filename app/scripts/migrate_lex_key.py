#!/usr/bin/env python3
"""
Migration: Add lex_key to ProtoConcepts

ADR: doc/ongoing/ADR_CORPUS_AWARE_LEX_KEY_NORMALIZATION.md

Ce script:
1. Ajoute lex_key aux ProtoConcepts existants (via compute_lex_key)
2. Crée l'index Neo4j sur (tenant_id, lex_key)
3. Optionnellement: met à jour les CanonicalConcepts sans lex_key

Usage:
    docker-compose exec app python scripts/migrate_lex_key.py
    docker-compose exec app python scripts/migrate_lex_key.py --dry-run
    docker-compose exec app python scripts/migrate_lex_key.py --tenant-id my_tenant

Author: OSMOSE
Date: 2026-01-11
"""

import argparse
import logging
import sys
from typing import Optional

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
logger = logging.getLogger(__name__)


def migrate_lex_keys(
    tenant_id: str = "default",
    dry_run: bool = False,
    batch_size: int = 500
) -> dict:
    """
    Migre les ProtoConcepts existants pour ajouter lex_key.

    Args:
        tenant_id: ID du tenant
        dry_run: Si True, n'applique pas les changements
        batch_size: Taille des batches pour les updates

    Returns:
        Dict avec statistiques de migration
    """
    from knowbase.common.clients.neo4j_client import Neo4jClient
    from knowbase.consolidation.lex_utils import compute_lex_key
    from knowbase.config.settings import get_settings

    settings = get_settings()
    neo4j = Neo4jClient(
        uri=settings.neo4j_uri,
        user=settings.neo4j_user,
        password=settings.neo4j_password
    )

    stats = {
        "protos_without_lex_key": 0,
        "protos_updated": 0,
        "protos_skipped": 0,
        "canonicals_without_lex_key": 0,
        "canonicals_updated": 0,
        "index_created": False,
        "errors": []
    }

    logger.info(f"[OSMOSE:Migration] Starting lex_key migration for tenant={tenant_id} (dry_run={dry_run})")

    with neo4j.driver.session(database="neo4j") as session:
        # 1. Compter les ProtoConcepts sans lex_key
        count_query = """
        MATCH (p:ProtoConcept {tenant_id: $tenant_id})
        WHERE p.lex_key IS NULL
        RETURN count(p) AS count
        """
        result = session.run(count_query, tenant_id=tenant_id)
        stats["protos_without_lex_key"] = result.single()["count"]

        logger.info(f"[OSMOSE:Migration] Found {stats['protos_without_lex_key']} ProtoConcepts without lex_key")

        if stats["protos_without_lex_key"] == 0:
            logger.info("[OSMOSE:Migration] No ProtoConcepts to migrate")
        else:
            # 2. Charger par batch et migrer
            offset = 0
            while True:
                # Charger un batch
                load_query = """
                MATCH (p:ProtoConcept {tenant_id: $tenant_id})
                WHERE p.lex_key IS NULL
                RETURN p.concept_id AS id, p.concept_name AS name
                ORDER BY p.concept_id
                SKIP $offset
                LIMIT $batch_size
                """

                result = session.run(
                    load_query,
                    tenant_id=tenant_id,
                    offset=offset,
                    batch_size=batch_size
                )
                records = list(result)

                if not records:
                    break

                logger.info(f"[OSMOSE:Migration] Processing batch at offset {offset} ({len(records)} records)")

                # Calculer lex_key et préparer updates
                updates = []
                for record in records:
                    concept_id = record["id"]
                    concept_name = record["name"]

                    if not concept_name:
                        stats["protos_skipped"] += 1
                        continue

                    try:
                        lex_key = compute_lex_key(concept_name)
                        updates.append({
                            "id": concept_id,
                            "lex_key": lex_key
                        })
                    except Exception as e:
                        stats["errors"].append(f"Proto {concept_id}: {e}")
                        stats["protos_skipped"] += 1

                # Appliquer les updates (si pas dry_run)
                if updates and not dry_run:
                    update_query = """
                    UNWIND $updates AS upd
                    MATCH (p:ProtoConcept {concept_id: upd.id, tenant_id: $tenant_id})
                    SET p.lex_key = upd.lex_key
                    RETURN count(p) AS updated
                    """

                    result = session.run(
                        update_query,
                        updates=updates,
                        tenant_id=tenant_id
                    )
                    updated = result.single()["updated"]
                    stats["protos_updated"] += updated

                    logger.info(f"[OSMOSE:Migration] Updated {updated} ProtoConcepts in this batch")
                elif updates:
                    # Dry run - juste compter
                    stats["protos_updated"] += len(updates)
                    logger.info(f"[OSMOSE:Migration] [DRY-RUN] Would update {len(updates)} ProtoConcepts")

                offset += batch_size

        # 3. Vérifier les CanonicalConcepts sans lex_key
        cc_count_query = """
        MATCH (cc:CanonicalConcept {tenant_id: $tenant_id})
        WHERE cc.lex_key IS NULL
        RETURN count(cc) AS count
        """
        result = session.run(cc_count_query, tenant_id=tenant_id)
        stats["canonicals_without_lex_key"] = result.single()["count"]

        if stats["canonicals_without_lex_key"] > 0:
            logger.info(f"[OSMOSE:Migration] Found {stats['canonicals_without_lex_key']} CanonicalConcepts without lex_key")

            # Migrer les CanonicalConcepts aussi
            if not dry_run:
                cc_update_query = """
                MATCH (cc:CanonicalConcept {tenant_id: $tenant_id})
                WHERE cc.lex_key IS NULL
                RETURN cc.canonical_id AS id, cc.canonical_name AS name
                """
                result = session.run(cc_update_query, tenant_id=tenant_id)
                cc_records = list(result)

                cc_updates = []
                for record in cc_records:
                    cc_id = record["id"]
                    label = record["name"]
                    if label:
                        try:
                            lex_key = compute_lex_key(label)
                            cc_updates.append({"id": cc_id, "lex_key": lex_key})
                        except Exception as e:
                            stats["errors"].append(f"CC {cc_id}: {e}")

                if cc_updates:
                    cc_apply_query = """
                    UNWIND $updates AS upd
                    MATCH (cc:CanonicalConcept {canonical_id: upd.id, tenant_id: $tenant_id})
                    SET cc.lex_key = upd.lex_key
                    RETURN count(cc) AS updated
                    """
                    result = session.run(cc_apply_query, updates=cc_updates, tenant_id=tenant_id)
                    stats["canonicals_updated"] = result.single()["updated"]
                    logger.info(f"[OSMOSE:Migration] Updated {stats['canonicals_updated']} CanonicalConcepts")

        # 4. Créer l'index si pas dry_run
        if not dry_run:
            try:
                index_query = """
                CREATE INDEX proto_lex_key IF NOT EXISTS
                FOR (p:ProtoConcept) ON (p.tenant_id, p.lex_key)
                """
                session.run(index_query)
                stats["index_created"] = True
                logger.info("[OSMOSE:Migration] Created index proto_lex_key")
            except Exception as e:
                logger.warning(f"[OSMOSE:Migration] Index creation failed (may already exist): {e}")

    # Résumé
    logger.info(
        f"[OSMOSE:Migration] Migration complete: "
        f"protos_updated={stats['protos_updated']}, "
        f"protos_skipped={stats['protos_skipped']}, "
        f"canonicals_updated={stats['canonicals_updated']}, "
        f"index_created={stats['index_created']}"
    )

    if stats["errors"]:
        logger.warning(f"[OSMOSE:Migration] {len(stats['errors'])} errors: {stats['errors'][:5]}")

    return stats


def verify_migration(tenant_id: str = "default") -> dict:
    """
    Vérifie que la migration a bien été appliquée.

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
        "protos_with_lex_key": 0,
        "protos_without_lex_key": 0,
        "unique_lex_keys": 0,
        "index_exists": False
    }

    with neo4j.driver.session(database="neo4j") as session:
        # Comptage total
        total_query = """
        MATCH (p:ProtoConcept {tenant_id: $tenant_id})
        RETURN count(p) AS total,
               sum(CASE WHEN p.lex_key IS NOT NULL THEN 1 ELSE 0 END) AS with_key,
               sum(CASE WHEN p.lex_key IS NULL THEN 1 ELSE 0 END) AS without_key
        """
        result = session.run(total_query, tenant_id=tenant_id)
        record = result.single()
        stats["total_protos"] = record["total"]
        stats["protos_with_lex_key"] = record["with_key"]
        stats["protos_without_lex_key"] = record["without_key"]

        # Unique lex_keys
        unique_query = """
        MATCH (p:ProtoConcept {tenant_id: $tenant_id})
        WHERE p.lex_key IS NOT NULL
        RETURN count(DISTINCT p.lex_key) AS unique_keys
        """
        result = session.run(unique_query, tenant_id=tenant_id)
        stats["unique_lex_keys"] = result.single()["unique_keys"]

        # Vérifier l'index
        index_query = """
        SHOW INDEXES
        YIELD name, labelsOrTypes, properties
        WHERE 'ProtoConcept' IN labelsOrTypes AND 'lex_key' IN properties
        RETURN name
        """
        try:
            result = session.run(index_query)
            stats["index_exists"] = result.single() is not None
        except Exception:
            stats["index_exists"] = False

    # Calcul couverture
    coverage = (
        stats["protos_with_lex_key"] / stats["total_protos"] * 100
        if stats["total_protos"] > 0 else 0
    )

    logger.info(
        f"[OSMOSE:Migration] Verification: "
        f"total={stats['total_protos']}, "
        f"with_lex_key={stats['protos_with_lex_key']} ({coverage:.1f}%), "
        f"unique_keys={stats['unique_lex_keys']}, "
        f"index_exists={stats['index_exists']}"
    )

    return stats


def show_sample_lex_keys(tenant_id: str = "default", limit: int = 20) -> None:
    """
    Affiche un échantillon de lex_keys calculés pour vérification visuelle.
    """
    from knowbase.common.clients.neo4j_client import Neo4jClient
    from knowbase.consolidation.lex_utils import compute_lex_key
    from knowbase.config.settings import get_settings

    settings = get_settings()
    neo4j = Neo4jClient(
        uri=settings.neo4j_uri,
        user=settings.neo4j_user,
        password=settings.neo4j_password
    )

    query = """
    MATCH (p:ProtoConcept {tenant_id: $tenant_id})
    WHERE p.lex_key IS NOT NULL
    RETURN p.concept_name AS name, p.lex_key AS lex_key
    ORDER BY rand()
    LIMIT $limit
    """

    with neo4j.driver.session(database="neo4j") as session:
        result = session.run(query, tenant_id=tenant_id, limit=limit)
        records = list(result)

    logger.info(f"[OSMOSE:Migration] Sample lex_keys (limit={limit}):")
    for record in records:
        name = record["name"]
        stored_key = record["lex_key"]
        computed_key = compute_lex_key(name) if name else ""
        match = "✓" if stored_key == computed_key else "✗"
        logger.info(f"  {match} '{name}' → '{stored_key}'")


def main():
    parser = argparse.ArgumentParser(
        description="Migration: Add lex_key to ProtoConcepts"
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
    parser.add_argument(
        "--sample",
        action="store_true",
        help="Show sample lex_keys for verification"
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=500,
        help="Batch size for updates (default: 500)"
    )

    args = parser.parse_args()

    try:
        if args.verify:
            verify_migration(args.tenant_id)
        elif args.sample:
            show_sample_lex_keys(args.tenant_id)
        else:
            migrate_lex_keys(
                tenant_id=args.tenant_id,
                dry_run=args.dry_run,
                batch_size=args.batch_size
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
