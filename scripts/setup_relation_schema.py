#!/usr/bin/env python3
"""
Phase 2.8 - Setup Neo4j Schema for RawAssertion + CanonicalRelation

Creates constraints and indexes required for the 2-layer relation architecture.
Run this script before ingesting documents with the new pipeline.

Usage:
    docker exec knowbase-app python /app/scripts/setup_relation_schema.py
    # or
    python scripts/setup_relation_schema.py

Author: Claude Code + ChatGPT collaboration
Date: 2025-12-21
"""

import logging
import sys
from typing import List, Tuple

from neo4j import GraphDatabase

# Configuration
NEO4J_URI = "bolt://neo4j:7687"
NEO4J_USER = "neo4j"
NEO4J_PASSWORD = "graphiti_neo4j_pass"

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)


# =============================================================================
# Schema Definitions (from Phase 2.8 spec)
# =============================================================================

CONSTRAINTS: List[Tuple[str, str]] = [
    # RawAssertion uniqueness
    (
        "raw_assertion_unique",
        """
        CREATE CONSTRAINT raw_assertion_unique IF NOT EXISTS
        FOR (ra:RawAssertion)
        REQUIRE (ra.tenant_id, ra.raw_assertion_id) IS UNIQUE
        """
    ),
    # CanonicalRelation uniqueness
    (
        "canonical_relation_unique",
        """
        CREATE CONSTRAINT canonical_relation_unique IF NOT EXISTS
        FOR (cr:CanonicalRelation)
        REQUIRE (cr.tenant_id, cr.canonical_relation_id) IS UNIQUE
        """
    ),
]

INDEXES: List[Tuple[str, str]] = [
    # Fingerprint index for dedup/idempotence
    (
        "ra_fingerprint_idx",
        """
        CREATE INDEX ra_fingerprint_idx IF NOT EXISTS
        FOR (ra:RawAssertion) ON (ra.tenant_id, ra.raw_fingerprint)
        """
    ),
    # Composite index for consolidation (CRITICAL for perf)
    (
        "ra_group_key_idx",
        """
        CREATE INDEX ra_group_key_idx IF NOT EXISTS
        FOR (ra:RawAssertion) ON (ra.tenant_id, ra.subject_concept_id, ra.object_concept_id, ra.predicate_norm)
        """
    ),
    # Search indexes
    (
        "ra_source_doc_idx",
        """
        CREATE INDEX ra_source_doc_idx IF NOT EXISTS
        FOR (ra:RawAssertion) ON (ra.tenant_id, ra.source_doc_id)
        """
    ),
    (
        "ra_predicate_idx",
        """
        CREATE INDEX ra_predicate_idx IF NOT EXISTS
        FOR (ra:RawAssertion) ON (ra.tenant_id, ra.predicate_norm)
        """
    ),
    # CanonicalRelation indexes
    (
        "cr_type_idx",
        """
        CREATE INDEX cr_type_idx IF NOT EXISTS
        FOR (cr:CanonicalRelation) ON (cr.tenant_id, cr.relation_type)
        """
    ),
    (
        "cr_maturity_idx",
        """
        CREATE INDEX cr_maturity_idx IF NOT EXISTS
        FOR (cr:CanonicalRelation) ON (cr.tenant_id, cr.maturity)
        """
    ),
    (
        "cr_concepts_idx",
        """
        CREATE INDEX cr_concepts_idx IF NOT EXISTS
        FOR (cr:CanonicalRelation) ON (cr.tenant_id, cr.subject_concept_id, cr.object_concept_id)
        """
    ),
]


def setup_schema(uri: str, user: str, password: str) -> bool:
    """
    Create all constraints and indexes for Phase 2.8 schema.

    Returns:
        True if successful, False otherwise
    """
    driver = None
    try:
        driver = GraphDatabase.driver(uri, auth=(user, password))

        with driver.session() as session:
            # Create constraints
            logger.info("Creating constraints...")
            for name, query in CONSTRAINTS:
                try:
                    session.run(query)
                    logger.info(f"  [OK] Constraint: {name}")
                except Exception as e:
                    if "already exists" in str(e).lower():
                        logger.info(f"  [SKIP] Constraint already exists: {name}")
                    else:
                        logger.error(f"  [FAIL] Constraint {name}: {e}")

            # Create indexes
            logger.info("Creating indexes...")
            for name, query in INDEXES:
                try:
                    session.run(query)
                    logger.info(f"  [OK] Index: {name}")
                except Exception as e:
                    if "already exists" in str(e).lower():
                        logger.info(f"  [SKIP] Index already exists: {name}")
                    else:
                        logger.error(f"  [FAIL] Index {name}: {e}")

            # Verify setup
            logger.info("Verifying schema...")
            result = session.run("SHOW CONSTRAINTS")
            constraints = [r["name"] for r in result]
            logger.info(f"  Constraints: {len(constraints)}")

            result = session.run("SHOW INDEXES")
            indexes = [r["name"] for r in result]
            logger.info(f"  Indexes: {len(indexes)}")

            logger.info("Schema setup complete!")
            return True

    except Exception as e:
        logger.error(f"Failed to setup schema: {e}")
        return False
    finally:
        if driver:
            driver.close()


def verify_schema(uri: str, user: str, password: str) -> None:
    """Print current schema state for verification."""
    driver = None
    try:
        driver = GraphDatabase.driver(uri, auth=(user, password))

        with driver.session() as session:
            print("\n=== Current Neo4j Schema ===\n")

            # Constraints
            print("CONSTRAINTS:")
            result = session.run("SHOW CONSTRAINTS")
            for r in result:
                print(f"  - {r['name']}: {r['type']} on {r['labelsOrTypes']}")

            # Indexes
            print("\nINDEXES:")
            result = session.run("SHOW INDEXES")
            for r in result:
                if r['type'] != 'LOOKUP':  # Skip internal indexes
                    print(f"  - {r['name']}: {r['type']} on {r['labelsOrTypes']} ({r['properties']})")

            # Node counts
            print("\nNODE COUNTS:")
            for label in ["RawAssertion", "CanonicalRelation", "CanonicalConcept"]:
                result = session.run(f"MATCH (n:{label}) RETURN count(n) as count")
                count = result.single()["count"]
                print(f"  - {label}: {count}")

    except Exception as e:
        print(f"Error verifying schema: {e}")
    finally:
        if driver:
            driver.close()


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Setup Neo4j schema for Phase 2.8")
    parser.add_argument("--verify", action="store_true", help="Only verify current schema, don't create")
    parser.add_argument("--uri", default=NEO4J_URI, help="Neo4j URI")
    parser.add_argument("--user", default=NEO4J_USER, help="Neo4j user")
    parser.add_argument("--password", default=NEO4J_PASSWORD, help="Neo4j password")

    args = parser.parse_args()

    if args.verify:
        verify_schema(args.uri, args.user, args.password)
    else:
        success = setup_schema(args.uri, args.user, args.password)
        if not success:
            sys.exit(1)

        # Also verify after setup
        verify_schema(args.uri, args.user, args.password)
