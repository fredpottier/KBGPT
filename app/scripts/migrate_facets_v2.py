#!/usr/bin/env python3
"""
migrate_facets_v2.py — Migration Neo4j pour le Facet Registry émergent.

1. Met à jour les nœuds Facet existants (lifecycle, facet_family, nouveaux champs)
2. Migre les relations HAS_FACET → BELONGS_TO_FACET
3. (Optionnel) Supprime les anciennes relations HAS_FACET

Usage :
    docker compose exec app python app/scripts/migrate_facets_v2.py --dry-run
    docker compose exec app python app/scripts/migrate_facets_v2.py --execute
    docker compose exec app python app/scripts/migrate_facets_v2.py --execute --drop-old
"""

from __future__ import annotations

import argparse
import logging
import os
from datetime import datetime, timezone

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
logger = logging.getLogger("[OSMOSE] migrate_facets_v2")

# Mapping facet_kind → facet_family (même logique que facet.py)
KIND_TO_FAMILY = {
    "domain": "thematic",
    "risk": "normative",
    "obligation": "normative",
    "limitation": "operational",
    "capability": "operational",
    "procedure": "operational",
}


def get_neo4j_driver():
    from neo4j import GraphDatabase
    uri = os.getenv("NEO4J_URI", "bolt://neo4j:7687")
    user = os.getenv("NEO4J_USER", "neo4j")
    password = os.getenv("NEO4J_PASSWORD", "graphiti_neo4j_pass")
    return GraphDatabase.driver(uri, auth=(user, password))


def diagnose(session) -> dict:
    """État actuel des Facets et relations."""
    stats = {}

    # Nombre de Facets
    r = session.run("MATCH (f:Facet) RETURN count(f) AS c").single()
    stats["facet_count"] = r["c"]

    # Facets sans lifecycle
    r = session.run(
        "MATCH (f:Facet) WHERE f.lifecycle IS NULL RETURN count(f) AS c"
    ).single()
    stats["facets_no_lifecycle"] = r["c"]

    # Relations HAS_FACET
    r = session.run(
        "MATCH ()-[r:HAS_FACET]->() RETURN count(r) AS c"
    ).single()
    stats["has_facet_count"] = r["c"]

    # Relations BELONGS_TO_FACET
    r = session.run(
        "MATCH ()-[r:BELONGS_TO_FACET]->() RETURN count(r) AS c"
    ).single()
    stats["belongs_to_facet_count"] = r["c"]

    # Détail facet_kind
    result = session.run(
        "MATCH (f:Facet) RETURN f.facet_kind AS kind, count(f) AS c ORDER BY c DESC"
    )
    stats["facet_kinds"] = {r["kind"]: r["c"] for r in result}

    return stats


def step1_update_facet_nodes(session, dry_run: bool) -> int:
    """Met à jour les Facets existants avec les nouveaux champs."""
    now_iso = datetime.now(timezone.utc).isoformat()

    if dry_run:
        result = session.run(
            """
            MATCH (f:Facet) WHERE f.lifecycle IS NULL
            RETURN f.facet_id AS fid, f.facet_kind AS kind, f.domain AS domain
            """
        )
        count = 0
        for r in result:
            kind = r["kind"] or "domain"
            family = KIND_TO_FAMILY.get(kind, "thematic")
            logger.info(
                f"  [DRY] {r['domain']}: kind={kind} → family={family}, "
                f"lifecycle=validated"
            )
            count += 1
        return count

    # Exécution réelle — une requête par facet_kind pour le mapping
    total = 0
    for kind, family in KIND_TO_FAMILY.items():
        result = session.run(
            """
            MATCH (f:Facet)
            WHERE f.lifecycle IS NULL AND f.facet_kind = $kind
            SET f.lifecycle = 'validated',
                f.facet_family = $family,
                f.source_doc_count = COALESCE(f.source_doc_count, 0),
                f.source_doc_ids = COALESCE(f.source_doc_ids, []),
                f.created_at = COALESCE(f.created_at, $now),
                f.promoted_at = $now,
                f.promotion_reason = 'migrated_from_predefined',
                f.keywords = COALESCE(f.keywords, []),
                f.aliases = COALESCE(f.aliases, []),
                f.example_claim_ids = COALESCE(f.example_claim_ids, [])
            RETURN count(f) AS c
            """,
            kind=kind,
            family=family,
            now=now_iso,
        )
        c = result.single()["c"]
        if c > 0:
            logger.info(f"  Mis à jour {c} facettes kind={kind} → family={family}")
        total += c

    # Facettes sans facet_kind (fallback → thematic)
    result = session.run(
        """
        MATCH (f:Facet)
        WHERE f.lifecycle IS NULL
        SET f.lifecycle = 'validated',
            f.facet_family = 'thematic',
            f.source_doc_count = COALESCE(f.source_doc_count, 0),
            f.source_doc_ids = COALESCE(f.source_doc_ids, []),
            f.created_at = COALESCE(f.created_at, $now),
            f.promoted_at = $now,
            f.promotion_reason = 'migrated_from_predefined',
            f.keywords = COALESCE(f.keywords, []),
            f.aliases = COALESCE(f.aliases, []),
            f.example_claim_ids = COALESCE(f.example_claim_ids, [])
        RETURN count(f) AS c
        """,
        now=now_iso,
    )
    c = result.single()["c"]
    if c > 0:
        logger.info(f"  Mis à jour {c} facettes sans kind → family=thematic")
    total += c

    return total


def step2_migrate_relations(session, dry_run: bool) -> int:
    """Copie HAS_FACET → BELONGS_TO_FACET."""
    now_iso = datetime.now(timezone.utc).isoformat()

    if dry_run:
        result = session.run(
            """
            MATCH (c:Claim)-[r:HAS_FACET]->(f:Facet)
            WHERE NOT (c)-[:BELONGS_TO_FACET]->(f)
            RETURN count(r) AS c
            """
        )
        count = result.single()["c"]
        logger.info(f"  [DRY] {count} relations HAS_FACET à migrer")
        return count

    # Exécution réelle — batch par 500
    total = 0
    while True:
        result = session.run(
            """
            MATCH (c:Claim)-[r:HAS_FACET]->(f:Facet)
            WHERE NOT (c)-[:BELONGS_TO_FACET]->(f)
            WITH c, f, r LIMIT 500
            CREATE (c)-[r2:BELONGS_TO_FACET]->(f)
            SET r2.score = COALESCE(r.score, 0.5),
                r2.assignment_signals = 'migrated_from_has_facet',
                r2.assigned_at = $now,
                r2.method = 'migrated_v1'
            RETURN count(r2) AS c
            """,
            now=now_iso,
        )
        c = result.single()["c"]
        if c == 0:
            break
        total += c
        logger.info(f"  Migré {total} relations...")

    return total


def step2b_update_facet_doc_counts(session, dry_run: bool) -> int:
    """Calcule source_doc_count depuis les relations BELONGS_TO_FACET."""
    if dry_run:
        result = session.run(
            """
            MATCH (c:Claim)-[:BELONGS_TO_FACET]->(f:Facet)
            WITH f, collect(DISTINCT c.doc_id) AS doc_ids
            RETURN f.domain AS domain, size(doc_ids) AS doc_count
            ORDER BY doc_count DESC
            """
        )
        count = 0
        for r in result:
            logger.info(f"  [DRY] {r['domain']}: {r['doc_count']} docs distincts")
            count += 1
        return count

    result = session.run(
        """
        MATCH (c:Claim)-[:BELONGS_TO_FACET]->(f:Facet)
        WITH f, collect(DISTINCT c.doc_id) AS doc_ids
        SET f.source_doc_ids = doc_ids,
            f.source_doc_count = size(doc_ids)
        RETURN count(f) AS c
        """
    )
    return result.single()["c"]


def step3_drop_old_relations(session, dry_run: bool) -> int:
    """Supprime les relations HAS_FACET (seulement si --drop-old)."""
    if dry_run:
        result = session.run(
            "MATCH ()-[r:HAS_FACET]->() RETURN count(r) AS c"
        )
        count = result.single()["c"]
        logger.info(f"  [DRY] {count} relations HAS_FACET à supprimer")
        return count

    total = 0
    while True:
        result = session.run(
            """
            MATCH ()-[r:HAS_FACET]->()
            WITH r LIMIT 500
            DELETE r
            RETURN count(r) AS c
            """
        )
        c = result.single()["c"]
        if c == 0:
            break
        total += c
        logger.info(f"  Supprimé {total} relations HAS_FACET...")

    return total


def main():
    parser = argparse.ArgumentParser(description="Migration Facets v2")
    parser.add_argument(
        "--execute", action="store_true",
        help="Exécuter réellement (défaut: dry-run)",
    )
    parser.add_argument(
        "--drop-old", action="store_true",
        help="Supprimer les relations HAS_FACET après migration",
    )
    args = parser.parse_args()

    dry_run = not args.execute

    logger.info(f"Mode: {'DRY-RUN' if dry_run else 'EXECUTE'}")

    driver = get_neo4j_driver()

    with driver.session() as session:
        # Diagnostic initial
        logger.info("=== DIAGNOSTIC ===")
        stats = diagnose(session)
        logger.info(f"  Facets: {stats['facet_count']}")
        logger.info(f"  Facets sans lifecycle: {stats['facets_no_lifecycle']}")
        logger.info(f"  Relations HAS_FACET: {stats['has_facet_count']}")
        logger.info(f"  Relations BELONGS_TO_FACET: {stats['belongs_to_facet_count']}")
        logger.info(f"  Facet kinds: {stats['facet_kinds']}")

        if stats["facets_no_lifecycle"] == 0 and stats["has_facet_count"] == 0:
            logger.info("Rien à migrer — tout est déjà à jour.")
            driver.close()
            return

        # Étape 1 : Mettre à jour les nœuds Facet
        logger.info("\n=== ÉTAPE 1 : Mise à jour nœuds Facet ===")
        n1 = step1_update_facet_nodes(session, dry_run)
        logger.info(f"  → {n1} facettes mises à jour")

        # Étape 2 : Migrer HAS_FACET → BELONGS_TO_FACET
        logger.info("\n=== ÉTAPE 2 : Migration relations ===")
        n2 = step2_migrate_relations(session, dry_run)
        logger.info(f"  → {n2} relations migrées")

        # Étape 2b : Calculer source_doc_count
        logger.info("\n=== ÉTAPE 2b : Calcul source_doc_count ===")
        n2b = step2b_update_facet_doc_counts(session, dry_run)
        logger.info(f"  → {n2b} facettes avec doc_count calculé")

        # Étape 3 : Supprimer HAS_FACET (si demandé)
        if args.drop_old:
            logger.info("\n=== ÉTAPE 3 : Suppression HAS_FACET ===")
            n3 = step3_drop_old_relations(session, dry_run)
            logger.info(f"  → {n3} relations supprimées")
        else:
            logger.info(
                "\n=== ÉTAPE 3 : SKIP (utiliser --drop-old pour supprimer HAS_FACET) ==="
            )

        # Diagnostic final
        if not dry_run:
            logger.info("\n=== DIAGNOSTIC POST-MIGRATION ===")
            stats2 = diagnose(session)
            logger.info(f"  Facets: {stats2['facet_count']}")
            logger.info(f"  Facets sans lifecycle: {stats2['facets_no_lifecycle']}")
            logger.info(f"  Relations HAS_FACET: {stats2['has_facet_count']}")
            logger.info(f"  Relations BELONGS_TO_FACET: {stats2['belongs_to_facet_count']}")

    driver.close()
    logger.info("Migration terminée.")


if __name__ == "__main__":
    main()
