"""
OSMOSE Structural Graph - Neo4j Schema (Option C)

Schéma Neo4j pour le Structural Graph: constraints et indexes.

Spec: ADR D9 - Indexes Neo4j (Production)

Exécution:
    python -m knowbase.structural.neo4j_schema
"""

from __future__ import annotations

import asyncio
import logging
import os
from typing import Optional

from neo4j import AsyncGraphDatabase

logger = logging.getLogger(__name__)


# ===================================
# SCHEMA QUERIES (D9)
# ===================================

# Contraintes uniques (D9.1-D9.4)
CONSTRAINT_QUERIES = [
    # D9.1 - DocumentContext unique
    (
        "doc_context_unique",
        """
        CREATE CONSTRAINT doc_context_unique IF NOT EXISTS
        FOR (d:DocumentContext) REQUIRE (d.tenant_id, d.doc_id) IS UNIQUE
        """
    ),
    # D9.2 - DocumentVersion unique
    (
        "doc_version_unique",
        """
        CREATE CONSTRAINT doc_version_unique IF NOT EXISTS
        FOR (v:DocumentVersion) REQUIRE (v.tenant_id, v.doc_id, v.doc_version_id) IS UNIQUE
        """
    ),
    # D9.3 - DocItem unique
    (
        "docitem_unique",
        """
        CREATE CONSTRAINT docitem_unique IF NOT EXISTS
        FOR (i:DocItem) REQUIRE (i.tenant_id, i.doc_id, i.doc_version_id, i.item_id) IS UNIQUE
        """
    ),
    # D9.4 - PageContext unique
    (
        "page_unique",
        """
        CREATE CONSTRAINT page_unique IF NOT EXISTS
        FOR (p:PageContext) REQUIRE (p.tenant_id, p.doc_version_id, p.page_no) IS UNIQUE
        """
    ),
    # SectionContext unique (extension de D9.6)
    (
        "section_unique",
        """
        CREATE CONSTRAINT section_unique IF NOT EXISTS
        FOR (s:SectionContext) REQUIRE (s.tenant_id, s.doc_version_id, s.section_id) IS UNIQUE
        """
    ),
    # TypeAwareChunk unique
    (
        "chunk_unique",
        """
        CREATE CONSTRAINT chunk_unique IF NOT EXISTS
        FOR (c:TypeAwareChunk) REQUIRE (c.tenant_id, c.chunk_id) IS UNIQUE
        """
    ),
]

# Indexes de performance (D9.5-D9.7)
INDEX_QUERIES = [
    # D9.5 - DocItem par ordre de lecture
    (
        "docitem_order",
        """
        CREATE INDEX docitem_order IF NOT EXISTS
        FOR (i:DocItem) ON (i.tenant_id, i.doc_version_id, i.reading_order_index)
        """
    ),
    # D9.6 - SectionContext par version
    (
        "section_version",
        """
        CREATE INDEX section_version IF NOT EXISTS
        FOR (s:SectionContext) ON (s.tenant_id, s.doc_version_id)
        """
    ),
    # D9.7 - DocItem par type
    (
        "docitem_type",
        """
        CREATE INDEX docitem_type IF NOT EXISTS
        FOR (i:DocItem) ON (i.tenant_id, i.item_type)
        """
    ),
    # Version courante d'un document
    (
        "doc_version_current",
        """
        CREATE INDEX doc_version_current IF NOT EXISTS
        FOR (v:DocumentVersion) ON (v.tenant_id, v.doc_id, v.is_current)
        """
    ),
    # TypeAwareChunk par kind
    (
        "chunk_kind",
        """
        CREATE INDEX chunk_kind IF NOT EXISTS
        FOR (c:TypeAwareChunk) ON (c.tenant_id, c.kind)
        """
    ),
    # TypeAwareChunk par doc
    (
        "chunk_doc",
        """
        CREATE INDEX chunk_doc IF NOT EXISTS
        FOR (c:TypeAwareChunk) ON (c.tenant_id, c.doc_id, c.doc_version_id)
        """
    ),
    # DocItem par section
    (
        "docitem_section",
        """
        CREATE INDEX docitem_section IF NOT EXISTS
        FOR (i:DocItem) ON (i.tenant_id, i.section_id)
        """
    ),
]


# ===================================
# SCHEMA SETUP
# ===================================

async def setup_structural_graph_schema(
    neo4j_uri: Optional[str] = None,
    neo4j_user: Optional[str] = None,
    neo4j_password: Optional[str] = None,
    database: str = "neo4j",
) -> None:
    """
    Configure le schéma Neo4j pour le Structural Graph.

    Crée:
    - Constraints unicité (D9.1-D9.4)
    - Indexes de performance (D9.5-D9.7)

    Args:
        neo4j_uri: URI Neo4j (default: env NEO4J_URI)
        neo4j_user: User Neo4j (default: env NEO4J_USER)
        neo4j_password: Password Neo4j (default: env NEO4J_PASSWORD)
        database: Nom de la base (default: neo4j)
    """
    # Récupérer config depuis env si non fournie
    uri = neo4j_uri or os.environ.get("NEO4J_URI", "bolt://localhost:7687")
    user = neo4j_user or os.environ.get("NEO4J_USER", "neo4j")
    password = neo4j_password or os.environ.get("NEO4J_PASSWORD", "")

    logger.info("[OSMOSE] Setup Structural Graph Neo4j Schema (Option C)...")

    driver = AsyncGraphDatabase.driver(uri, auth=(user, password))

    try:
        async with driver.session(database=database) as session:
            # Créer les constraints
            logger.info("Creating constraints...")
            for name, query in CONSTRAINT_QUERIES:
                try:
                    await session.run(query)
                    logger.info(f"  ✅ Constraint {name} created")
                except Exception as e:
                    if "already exists" in str(e).lower():
                        logger.info(f"  ℹ️ Constraint {name} already exists")
                    else:
                        logger.warning(f"  ⚠️ Constraint {name} failed: {e}")

            # Créer les indexes
            logger.info("Creating indexes...")
            for name, query in INDEX_QUERIES:
                try:
                    await session.run(query)
                    logger.info(f"  ✅ Index {name} created")
                except Exception as e:
                    if "already exists" in str(e).lower():
                        logger.info(f"  ℹ️ Index {name} already exists")
                    else:
                        logger.warning(f"  ⚠️ Index {name} failed: {e}")

            logger.info("[OSMOSE] Structural Graph schema setup complete!")

    finally:
        await driver.close()


async def verify_structural_graph_schema(
    neo4j_uri: Optional[str] = None,
    neo4j_user: Optional[str] = None,
    neo4j_password: Optional[str] = None,
    database: str = "neo4j",
) -> dict:
    """
    Vérifie que le schéma Structural Graph est correctement configuré.

    Returns:
        Dict avec status des constraints et indexes
    """
    uri = neo4j_uri or os.environ.get("NEO4J_URI", "bolt://localhost:7687")
    user = neo4j_user or os.environ.get("NEO4J_USER", "neo4j")
    password = neo4j_password or os.environ.get("NEO4J_PASSWORD", "")

    driver = AsyncGraphDatabase.driver(uri, auth=(user, password))

    result = {
        "constraints": {},
        "indexes": {},
        "all_ok": True,
    }

    try:
        async with driver.session(database=database) as session:
            # Vérifier les constraints
            constraints_result = await session.run("SHOW CONSTRAINTS")
            existing_constraints = set()
            async for record in constraints_result:
                existing_constraints.add(record["name"])

            for name, _ in CONSTRAINT_QUERIES:
                exists = name in existing_constraints
                result["constraints"][name] = exists
                if not exists:
                    result["all_ok"] = False

            # Vérifier les indexes
            indexes_result = await session.run("SHOW INDEXES")
            existing_indexes = set()
            async for record in indexes_result:
                existing_indexes.add(record["name"])

            for name, _ in INDEX_QUERIES:
                exists = name in existing_indexes
                result["indexes"][name] = exists
                if not exists:
                    result["all_ok"] = False

    finally:
        await driver.close()

    return result


async def drop_structural_graph_schema(
    neo4j_uri: Optional[str] = None,
    neo4j_user: Optional[str] = None,
    neo4j_password: Optional[str] = None,
    database: str = "neo4j",
) -> None:
    """
    Supprime le schéma Structural Graph (pour reset/migration).

    ⚠️ DANGER: Ceci supprime les constraints et indexes!
    """
    uri = neo4j_uri or os.environ.get("NEO4J_URI", "bolt://localhost:7687")
    user = neo4j_user or os.environ.get("NEO4J_USER", "neo4j")
    password = neo4j_password or os.environ.get("NEO4J_PASSWORD", "")

    logger.warning("[OSMOSE] Dropping Structural Graph Neo4j Schema...")

    driver = AsyncGraphDatabase.driver(uri, auth=(user, password))

    try:
        async with driver.session(database=database) as session:
            # Supprimer les constraints
            for name, _ in CONSTRAINT_QUERIES:
                try:
                    await session.run(f"DROP CONSTRAINT {name} IF EXISTS")
                    logger.info(f"  ✅ Constraint {name} dropped")
                except Exception as e:
                    logger.warning(f"  ⚠️ Drop constraint {name} failed: {e}")

            # Supprimer les indexes
            for name, _ in INDEX_QUERIES:
                try:
                    await session.run(f"DROP INDEX {name} IF EXISTS")
                    logger.info(f"  ✅ Index {name} dropped")
                except Exception as e:
                    logger.warning(f"  ⚠️ Drop index {name} failed: {e}")

            logger.info("[OSMOSE] Structural Graph schema dropped!")

    finally:
        await driver.close()


# ===================================
# CLI ENTRY POINT
# ===================================

def main():
    """Entry point pour python -m knowbase.structural.neo4j_schema"""
    import argparse

    parser = argparse.ArgumentParser(
        description="OSMOSE Structural Graph Neo4j Schema Management"
    )
    parser.add_argument(
        "action",
        choices=["setup", "verify", "drop"],
        help="Action to perform"
    )
    parser.add_argument(
        "--uri",
        default=None,
        help="Neo4j URI (default: env NEO4J_URI)"
    )
    parser.add_argument(
        "--user",
        default=None,
        help="Neo4j user (default: env NEO4J_USER)"
    )
    parser.add_argument(
        "--password",
        default=None,
        help="Neo4j password (default: env NEO4J_PASSWORD)"
    )
    parser.add_argument(
        "--database",
        default="neo4j",
        help="Neo4j database name"
    )

    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO)

    if args.action == "setup":
        asyncio.run(setup_structural_graph_schema(
            neo4j_uri=args.uri,
            neo4j_user=args.user,
            neo4j_password=args.password,
            database=args.database,
        ))
    elif args.action == "verify":
        result = asyncio.run(verify_structural_graph_schema(
            neo4j_uri=args.uri,
            neo4j_user=args.user,
            neo4j_password=args.password,
            database=args.database,
        ))
        print("\n=== Structural Graph Schema Status ===")
        print("\nConstraints:")
        for name, exists in result["constraints"].items():
            status = "✅" if exists else "❌"
            print(f"  {status} {name}")
        print("\nIndexes:")
        for name, exists in result["indexes"].items():
            status = "✅" if exists else "❌"
            print(f"  {status} {name}")
        print(f"\nOverall: {'✅ All OK' if result['all_ok'] else '❌ Missing items'}")
    elif args.action == "drop":
        confirm = input("⚠️ This will drop all structural graph constraints and indexes. Type 'yes' to confirm: ")
        if confirm.lower() == "yes":
            asyncio.run(drop_structural_graph_schema(
                neo4j_uri=args.uri,
                neo4j_user=args.user,
                neo4j_password=args.password,
                database=args.database,
            ))
        else:
            print("Cancelled.")


if __name__ == "__main__":
    main()
