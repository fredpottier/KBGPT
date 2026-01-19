#!/usr/bin/env python3
"""
OSMOSE - Setup Charspan Contract v1 Schema

Crée les constraints et indexes Neo4j pour le contrat de charspans.
Référence: doc/ongoing/ADR_CHARSPAN_CONTRACT_V1.md

Usage:
    docker-compose exec app python app/scripts/setup_charspan_schema.py
    docker-compose exec app python app/scripts/setup_charspan_schema.py --dry-run
    docker-compose exec app python app/scripts/setup_charspan_schema.py --drop-existing
"""

from __future__ import annotations

import argparse
import logging
import sys
from typing import List, Tuple

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)


# ============================================
# SCHEMA DEFINITIONS (Charspan Contract v1)
# ============================================

# Constraints d'unicité
UNIQUENESS_CONSTRAINTS = [
    ("document_doc_id_unique", "Document", "d.doc_id"),
    ("docitem_item_id_unique", "DocItem", "di.item_id"),
    ("protoconcept_id_unique", "ProtoConcept", "p.concept_id"),
]

# Constraints d'existence - Nodes
# NOTE: Require Neo4j Enterprise Edition - skipped on Community
# Validation is done in anchor_validator.py at application level
NODE_EXISTENCE_CONSTRAINTS_ENTERPRISE = [
    # DocItem
    ("docitem_text_exists", "DocItem", "di.text"),
    ("docitem_doc_id_exists", "DocItem", "di.doc_id"),
    ("docitem_docwide_start_exists", "DocItem", "di.charspan_start_docwide"),
    ("docitem_docwide_end_exists", "DocItem", "di.charspan_end_docwide"),
    # ProtoConcept
    ("protoconcept_doc_id_exists", "ProtoConcept", "p.doc_id"),
    ("protoconcept_name_exists", "ProtoConcept", "p.concept_name"),
]

# Constraints d'existence - Relations
# NOTE: Require Neo4j Enterprise Edition - skipped on Community
REL_EXISTENCE_CONSTRAINTS_ENTERPRISE = [
    ("anchored_in_span_start_exists", "ANCHORED_IN", "r.span_start"),
    ("anchored_in_span_end_exists", "ANCHORED_IN", "r.span_end"),
    ("anchored_in_quality_exists", "ANCHORED_IN", "r.anchor_quality"),
    ("anchored_in_method_exists", "ANCHORED_IN", "r.anchor_method"),
    ("anchored_in_anchor_id_exists", "ANCHORED_IN", "r.anchor_id"),
]

# Active constraints (Community Edition compatible)
NODE_EXISTENCE_CONSTRAINTS: List[Tuple[str, str, str]] = []  # Enterprise only
REL_EXISTENCE_CONSTRAINTS: List[Tuple[str, str, str]] = []   # Enterprise only

# Indexes performance - Charspan Contract v1
NODE_INDEXES = [
    ("docitem_by_doc_id", "DocItem", "di.doc_id"),
    ("protoconcept_by_doc_id", "ProtoConcept", "p.doc_id"),
    ("protoconcept_by_name", "ProtoConcept", "p.concept_name"),
]

REL_INDEXES = [
    ("anchored_in_by_quality", "ANCHORED_IN", "r.anchor_quality"),
]

# ============================================
# CHAT/SEARCH PERFORMANCE INDEXES
# Tier 1: Critical for query performance
# ============================================

CHAT_PERFORMANCE_INDEXES = [
    # CanonicalConcept lookups (used in all graph queries)
    ("cc_canonical_id_tenant", "CanonicalConcept", ["canonical_id", "tenant_id"]),
    ("cc_canonical_name_tenant", "CanonicalConcept", ["canonical_name", "tenant_id"]),
    ("cc_type_tenant", "CanonicalConcept", ["type", "tenant_id"]),

    # SectionContext for evidence retrieval
    ("sc_tenant_section_id", "SectionContext", ["tenant_id", "section_id"]),
    ("sc_document_tenant", "SectionContext", ["doc_id", "tenant_id"]),

    # Document lookup
    ("doc_doc_id_tenant", "Document", ["doc_id", "tenant_id"]),

    # RawAssertion queries
    ("ra_subject_tenant", "RawAssertion", ["subject_concept_id", "tenant_id"]),
]

# Relationship property indexes for filtering
CHAT_REL_INDEXES = [
    ("mentioned_in_weight", "MENTIONED_IN", "weight"),
    ("cr_confidence", "CanonicalRelation", "confidence"),
    ("cr_maturity", "CanonicalRelation", "maturity"),
    ("cr_source_count", "CanonicalRelation", "source_count"),
]


def build_uniqueness_constraint_query(name: str, label: str, prop: str) -> str:
    """Construit une requête CREATE CONSTRAINT pour unicité."""
    var = prop.split(".")[0]
    prop_name = prop.split(".")[1]
    return f"""
CREATE CONSTRAINT {name} IF NOT EXISTS
FOR ({var}:{label})
REQUIRE {var}.{prop_name} IS UNIQUE
"""


def build_node_existence_constraint_query(name: str, label: str, prop: str) -> str:
    """Construit une requête CREATE CONSTRAINT pour existence sur node."""
    var = prop.split(".")[0]
    prop_name = prop.split(".")[1]
    return f"""
CREATE CONSTRAINT {name} IF NOT EXISTS
FOR ({var}:{label})
REQUIRE {var}.{prop_name} IS NOT NULL
"""


def build_rel_existence_constraint_query(name: str, rel_type: str, prop: str) -> str:
    """Construit une requête CREATE CONSTRAINT pour existence sur relation."""
    prop_name = prop.split(".")[1]
    return f"""
CREATE CONSTRAINT {name} IF NOT EXISTS
FOR ()-[r:{rel_type}]-()
REQUIRE r.{prop_name} IS NOT NULL
"""


def build_node_index_query(name: str, label: str, prop: str) -> str:
    """Construit une requête CREATE INDEX pour node."""
    var = prop.split(".")[0]
    prop_name = prop.split(".")[1]
    return f"""
CREATE INDEX {name} IF NOT EXISTS
FOR ({var}:{label})
ON ({var}.{prop_name})
"""


def build_rel_index_query(name: str, rel_type: str, prop: str) -> str:
    """Construit une requête CREATE INDEX pour relation."""
    prop_name = prop.split(".")[1] if "." in prop else prop
    return f"""
CREATE INDEX {name} IF NOT EXISTS
FOR ()-[r:{rel_type}]-()
ON (r.{prop_name})
"""


def build_composite_index_query(name: str, label: str, props: list) -> str:
    """Construit une requête CREATE INDEX composite (multi-property)."""
    var = "n"
    props_str = ", ".join(f"{var}.{p}" for p in props)
    return f"""
CREATE INDEX {name} IF NOT EXISTS
FOR ({var}:{label})
ON ({props_str})
"""


def get_all_schema_queries() -> List[Tuple[str, str]]:
    """Retourne toutes les requêtes de création de schéma."""
    queries = []

    # Uniqueness constraints
    for name, label, prop in UNIQUENESS_CONSTRAINTS:
        queries.append((name, build_uniqueness_constraint_query(name, label, prop)))

    # Node existence constraints
    for name, label, prop in NODE_EXISTENCE_CONSTRAINTS:
        queries.append((name, build_node_existence_constraint_query(name, label, prop)))

    # Relation existence constraints
    for name, rel_type, prop in REL_EXISTENCE_CONSTRAINTS:
        queries.append((name, build_rel_existence_constraint_query(name, rel_type, prop)))

    # Node indexes
    for name, label, prop in NODE_INDEXES:
        queries.append((name, build_node_index_query(name, label, prop)))

    # Relation indexes
    for name, rel_type, prop in REL_INDEXES:
        queries.append((name, build_rel_index_query(name, rel_type, prop)))

    # Chat performance composite indexes
    for name, label, props in CHAT_PERFORMANCE_INDEXES:
        queries.append((name, build_composite_index_query(name, label, props)))

    # Chat relationship indexes
    for name, rel_type, prop in CHAT_REL_INDEXES:
        queries.append((name, build_rel_index_query(name, rel_type, prop)))

    return queries


def drop_existing_schema(neo4j_client) -> int:
    """Supprime les constraints et indexes existants du contrat v1."""
    dropped = 0

    all_names = (
        [name for name, _, _ in UNIQUENESS_CONSTRAINTS]
        + [name for name, _, _ in NODE_EXISTENCE_CONSTRAINTS]
        + [name for name, _, _ in REL_EXISTENCE_CONSTRAINTS]
        + [name for name, _, _ in NODE_INDEXES]
        + [name for name, _, _ in REL_INDEXES]
        + [name for name, _, _ in CHAT_PERFORMANCE_INDEXES]
        + [name for name, _, _ in CHAT_REL_INDEXES]
    )

    with neo4j_client.driver.session(database=neo4j_client.database) as session:
        for name in all_names:
            try:
                # Essayer de drop comme constraint
                session.run(f"DROP CONSTRAINT {name} IF EXISTS")
                dropped += 1
                logger.info(f"  Dropped constraint: {name}")
            except Exception:
                pass

            try:
                # Essayer de drop comme index
                session.run(f"DROP INDEX {name} IF EXISTS")
                dropped += 1
                logger.info(f"  Dropped index: {name}")
            except Exception:
                pass

    return dropped


def setup_schema(neo4j_client, dry_run: bool = False) -> dict:
    """
    Configure le schéma Neo4j pour le Charspan Contract v1.

    Args:
        neo4j_client: Instance Neo4jClient
        dry_run: Si True, affiche les requêtes sans les exécuter

    Returns:
        dict avec statistiques
    """
    queries = get_all_schema_queries()

    stats = {
        "total": len(queries),
        "created": 0,
        "skipped": 0,
        "errors": 0,
    }

    logger.info(f"[OSMOSE:Schema] Setting up Charspan Contract v1 ({len(queries)} items)")

    if dry_run:
        logger.info("[OSMOSE:Schema] DRY-RUN mode - queries will not be executed")
        for name, query in queries:
            print(f"\n-- {name}")
            print(query.strip())
        return stats

    with neo4j_client.driver.session(database=neo4j_client.database) as session:
        for name, query in queries:
            try:
                session.run(query)
                stats["created"] += 1
                logger.info(f"  Created: {name}")
            except Exception as e:
                error_msg = str(e)
                if "already exists" in error_msg.lower():
                    stats["skipped"] += 1
                    logger.debug(f"  Skipped (exists): {name}")
                else:
                    stats["errors"] += 1
                    logger.error(f"  Error creating {name}: {e}")

    logger.info(
        f"[OSMOSE:Schema] Done: {stats['created']} created, "
        f"{stats['skipped']} skipped, {stats['errors']} errors"
    )

    return stats


def verify_schema(neo4j_client) -> dict:
    """
    Vérifie que le schéma est correctement configuré.

    Returns:
        dict avec les résultats de vérification
    """
    results = {
        "constraints": [],
        "indexes": [],
        "missing": [],
    }

    expected_names = set(
        [name for name, _, _ in UNIQUENESS_CONSTRAINTS]
        + [name for name, _, _ in NODE_EXISTENCE_CONSTRAINTS]
        + [name for name, _, _ in REL_EXISTENCE_CONSTRAINTS]
        + [name for name, _, _ in NODE_INDEXES]
        + [name for name, _, _ in REL_INDEXES]
        + [name for name, _, _ in CHAT_PERFORMANCE_INDEXES]
        + [name for name, _, _ in CHAT_REL_INDEXES]
    )

    with neo4j_client.driver.session(database=neo4j_client.database) as session:
        # Vérifier constraints
        result = session.run("SHOW CONSTRAINTS")
        for record in result:
            name = record.get("name")
            if name in expected_names:
                results["constraints"].append(name)
                expected_names.discard(name)

        # Vérifier indexes
        result = session.run("SHOW INDEXES")
        for record in result:
            name = record.get("name")
            if name in expected_names:
                results["indexes"].append(name)
                expected_names.discard(name)

    results["missing"] = list(expected_names)

    return results


def main():
    parser = argparse.ArgumentParser(
        description="Setup Charspan Contract v1 Schema in Neo4j"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Affiche les requêtes sans les exécuter",
    )
    parser.add_argument(
        "--drop-existing",
        action="store_true",
        help="Supprime les constraints/indexes existants avant de créer",
    )
    parser.add_argument(
        "--verify-only",
        action="store_true",
        help="Vérifie uniquement le schéma existant",
    )

    args = parser.parse_args()

    # Import Neo4j client
    try:
        from knowbase.common.clients.neo4j_client import Neo4jClient
        neo4j_client = Neo4jClient()
    except Exception as e:
        logger.error(f"Failed to connect to Neo4j: {e}")
        sys.exit(1)

    try:
        if args.verify_only:
            logger.info("[OSMOSE:Schema] Verifying existing schema...")
            results = verify_schema(neo4j_client)
            print(f"\nConstraints found: {len(results['constraints'])}")
            for name in results["constraints"]:
                print(f"  - {name}")
            print(f"\nIndexes found: {len(results['indexes'])}")
            for name in results["indexes"]:
                print(f"  - {name}")
            if results["missing"]:
                print(f"\nMissing ({len(results['missing'])}):")
                for name in results["missing"]:
                    print(f"  - {name}")
            sys.exit(0 if not results["missing"] else 1)

        if args.drop_existing:
            logger.info("[OSMOSE:Schema] Dropping existing schema elements...")
            dropped = drop_existing_schema(neo4j_client)
            logger.info(f"[OSMOSE:Schema] Dropped {dropped} elements")

        stats = setup_schema(neo4j_client, dry_run=args.dry_run)

        if stats["errors"] > 0:
            sys.exit(1)

    finally:
        neo4j_client.close()


if __name__ == "__main__":
    main()
