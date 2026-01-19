"""
OSMOSE Evidence Bundle - Neo4j Schema (Pass 3.5)

Schéma Neo4j pour les Evidence Bundles et SemanticRelations.

Référence: ADR_MULTI_SPAN_EVIDENCE_BUNDLES.md v1.3

Exécution:
    python -m knowbase.relations.evidence_bundle_schema setup
    python -m knowbase.relations.evidence_bundle_schema verify
"""

from __future__ import annotations

import asyncio
import logging
import os
from typing import Optional

from neo4j import AsyncGraphDatabase

logger = logging.getLogger(__name__)


# ===================================
# SCHEMA QUERIES - Evidence Bundles
# ===================================

# Contraintes uniques
CONSTRAINT_QUERIES = [
    # EvidenceBundle unique par bundle_id
    (
        "evidence_bundle_unique",
        """
        CREATE CONSTRAINT evidence_bundle_unique IF NOT EXISTS
        FOR (eb:EvidenceBundle) REQUIRE eb.bundle_id IS UNIQUE
        """
    ),
    # SemanticRelation unique par relation_id
    (
        "semantic_relation_unique",
        """
        CREATE CONSTRAINT semantic_relation_unique IF NOT EXISTS
        FOR (sr:SemanticRelation) REQUIRE sr.relation_id IS UNIQUE
        """
    ),
]

# Indexes de performance
INDEX_QUERIES = [
    # EvidenceBundle par tenant + status (pour queries de review)
    (
        "bundle_tenant_status",
        """
        CREATE INDEX bundle_tenant_status IF NOT EXISTS
        FOR (eb:EvidenceBundle) ON (eb.tenant_id, eb.validation_status)
        """
    ),
    # EvidenceBundle par tenant + document (pour processing)
    (
        "bundle_tenant_document",
        """
        CREATE INDEX bundle_tenant_document IF NOT EXISTS
        FOR (eb:EvidenceBundle) ON (eb.tenant_id, eb.document_id)
        """
    ),
    # EvidenceBundle par confidence (pour promotion batch)
    (
        "bundle_confidence",
        """
        CREATE INDEX bundle_confidence IF NOT EXISTS
        FOR (eb:EvidenceBundle) ON (eb.tenant_id, eb.confidence)
        """
    ),
    # SemanticRelation par tenant + type
    (
        "relation_tenant_type",
        """
        CREATE INDEX relation_tenant_type IF NOT EXISTS
        FOR (sr:SemanticRelation) ON (sr.tenant_id, sr.relation_type)
        """
    ),
    # SemanticRelation par source bundle (pour traçabilité)
    (
        "relation_source_bundle",
        """
        CREATE INDEX relation_source_bundle IF NOT EXISTS
        FOR (sr:SemanticRelation) ON (sr.source_bundle_id)
        """
    ),
]


# ===================================
# SCHEMA SETUP
# ===================================

async def setup_evidence_bundle_schema(
    neo4j_uri: Optional[str] = None,
    neo4j_user: Optional[str] = None,
    neo4j_password: Optional[str] = None,
    database: str = "neo4j",
) -> None:
    """
    Configure le schéma Neo4j pour les Evidence Bundles.

    Crée:
    - Contrainte unicité bundle_id
    - Contrainte unicité relation_id
    - Index sur (tenant_id, validation_status)
    - Index sur (tenant_id, document_id)
    - Index sur (tenant_id, confidence)
    - Index sur (tenant_id, relation_type)
    - Index sur source_bundle_id

    Args:
        neo4j_uri: URI Neo4j (default: env NEO4J_URI)
        neo4j_user: User Neo4j (default: env NEO4J_USER)
        neo4j_password: Password Neo4j (default: env NEO4J_PASSWORD)
        database: Nom de la base (default: neo4j)
    """
    uri = neo4j_uri or os.environ.get("NEO4J_URI", "bolt://localhost:7687")
    user = neo4j_user or os.environ.get("NEO4J_USER", "neo4j")
    password = neo4j_password or os.environ.get("NEO4J_PASSWORD", "")

    logger.info("[OSMOSE:Pass3.5] Setup Evidence Bundle Neo4j Schema...")

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

            logger.info("[OSMOSE:Pass3.5] Evidence Bundle schema setup complete!")

    finally:
        await driver.close()


async def verify_evidence_bundle_schema(
    neo4j_uri: Optional[str] = None,
    neo4j_user: Optional[str] = None,
    neo4j_password: Optional[str] = None,
    database: str = "neo4j",
) -> dict:
    """
    Vérifie que le schéma Evidence Bundle est correctement configuré.

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


async def drop_evidence_bundle_schema(
    neo4j_uri: Optional[str] = None,
    neo4j_user: Optional[str] = None,
    neo4j_password: Optional[str] = None,
    database: str = "neo4j",
) -> None:
    """
    Supprime le schéma Evidence Bundle (pour reset/migration).

    ⚠️ DANGER: Ceci supprime les constraints et indexes!
    """
    uri = neo4j_uri or os.environ.get("NEO4J_URI", "bolt://localhost:7687")
    user = neo4j_user or os.environ.get("NEO4J_USER", "neo4j")
    password = neo4j_password or os.environ.get("NEO4J_PASSWORD", "")

    logger.warning("[OSMOSE:Pass3.5] Dropping Evidence Bundle Neo4j Schema...")

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

            logger.info("[OSMOSE:Pass3.5] Evidence Bundle schema dropped!")

    finally:
        await driver.close()


# ===================================
# SYNC WRAPPERS (pour usage non-async)
# ===================================

def setup_evidence_bundle_schema_sync(
    neo4j_uri: Optional[str] = None,
    neo4j_user: Optional[str] = None,
    neo4j_password: Optional[str] = None,
    database: str = "neo4j",
) -> None:
    """Wrapper synchrone pour setup_evidence_bundle_schema."""
    asyncio.run(setup_evidence_bundle_schema(
        neo4j_uri=neo4j_uri,
        neo4j_user=neo4j_user,
        neo4j_password=neo4j_password,
        database=database,
    ))


def verify_evidence_bundle_schema_sync(
    neo4j_uri: Optional[str] = None,
    neo4j_user: Optional[str] = None,
    neo4j_password: Optional[str] = None,
    database: str = "neo4j",
) -> dict:
    """Wrapper synchrone pour verify_evidence_bundle_schema."""
    return asyncio.run(verify_evidence_bundle_schema(
        neo4j_uri=neo4j_uri,
        neo4j_user=neo4j_user,
        neo4j_password=neo4j_password,
        database=database,
    ))


# ===================================
# CLI ENTRY POINT
# ===================================

def main():
    """Entry point pour python -m knowbase.relations.evidence_bundle_schema"""
    import argparse

    parser = argparse.ArgumentParser(
        description="OSMOSE Evidence Bundle Neo4j Schema Management (Pass 3.5)"
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
        asyncio.run(setup_evidence_bundle_schema(
            neo4j_uri=args.uri,
            neo4j_user=args.user,
            neo4j_password=args.password,
            database=args.database,
        ))
    elif args.action == "verify":
        result = asyncio.run(verify_evidence_bundle_schema(
            neo4j_uri=args.uri,
            neo4j_user=args.user,
            neo4j_password=args.password,
            database=args.database,
        ))
        print("\n=== Evidence Bundle Schema Status ===")
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
        confirm = input("⚠️ This will drop all Evidence Bundle constraints and indexes. Type 'yes' to confirm: ")
        if confirm.lower() == "yes":
            asyncio.run(drop_evidence_bundle_schema(
                neo4j_uri=args.uri,
                neo4j_user=args.user,
                neo4j_password=args.password,
                database=args.database,
            ))
        else:
            print("Cancelled.")


if __name__ == "__main__":
    main()
