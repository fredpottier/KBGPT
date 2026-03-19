#!/usr/bin/env python3
"""
Phase 4 — Setup Neo4j Schema for WikiArticle + WikiCategory

Creates constraints and indexes required for the Knowledge Atlas persistence layer.

Usage:
    docker exec knowbase-app python /app/scripts/setup_wiki_schema.py
    docker exec knowbase-app python /app/scripts/setup_wiki_schema.py --verify
"""

import logging
import sys
from typing import List, Tuple

from neo4j import GraphDatabase

NEO4J_URI = "bolt://neo4j:7687"
NEO4J_USER = "neo4j"
NEO4J_PASSWORD = "graphiti_neo4j_pass"

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

CONSTRAINTS: List[Tuple[str, str]] = [
    (
        "wiki_article_slug",
        """
        CREATE CONSTRAINT wiki_article_slug IF NOT EXISTS
        FOR (wa:WikiArticle)
        REQUIRE (wa.tenant_id, wa.slug) IS UNIQUE
        """,
    ),
    (
        "wiki_category_key",
        """
        CREATE CONSTRAINT wiki_category_key IF NOT EXISTS
        FOR (wc:WikiCategory)
        REQUIRE (wc.tenant_id, wc.category_key) IS UNIQUE
        """,
    ),
]

INDEXES: List[Tuple[str, str]] = [
    (
        "wa_tenant_status_idx",
        """
        CREATE INDEX wa_tenant_status_idx IF NOT EXISTS
        FOR (wa:WikiArticle) ON (wa.tenant_id, wa.status)
        """,
    ),
    (
        "wa_category_idx",
        """
        CREATE INDEX wa_category_idx IF NOT EXISTS
        FOR (wa:WikiArticle) ON (wa.tenant_id, wa.category_key)
        """,
    ),
    (
        "wa_importance_idx",
        """
        CREATE INDEX wa_importance_idx IF NOT EXISTS
        FOR (wa:WikiArticle) ON (wa.tenant_id, wa.importance_tier)
        """,
    ),
    (
        "wa_title_idx",
        """
        CREATE INDEX wa_title_idx IF NOT EXISTS
        FOR (wa:WikiArticle) ON (wa.tenant_id, wa.title)
        """,
    ),
]


def setup_schema(uri: str, user: str, password: str) -> bool:
    driver = None
    try:
        driver = GraphDatabase.driver(uri, auth=(user, password))

        with driver.session() as session:
            logger.info("Creating Wiki constraints...")
            for name, query in CONSTRAINTS:
                try:
                    session.run(query)
                    logger.info(f"  [OK] Constraint: {name}")
                except Exception as e:
                    if "already exists" in str(e).lower():
                        logger.info(f"  [SKIP] Constraint already exists: {name}")
                    else:
                        logger.error(f"  [FAIL] Constraint {name}: {e}")

            logger.info("Creating Wiki indexes...")
            for name, query in INDEXES:
                try:
                    session.run(query)
                    logger.info(f"  [OK] Index: {name}")
                except Exception as e:
                    if "already exists" in str(e).lower():
                        logger.info(f"  [SKIP] Index already exists: {name}")
                    else:
                        logger.error(f"  [FAIL] Index {name}: {e}")

            logger.info("Wiki schema setup complete!")
            return True

    except Exception as e:
        logger.error(f"Failed to setup wiki schema: {e}")
        return False
    finally:
        if driver:
            driver.close()


def verify_schema(uri: str, user: str, password: str) -> None:
    driver = None
    try:
        driver = GraphDatabase.driver(uri, auth=(user, password))

        with driver.session() as session:
            print("\n=== Wiki Neo4j Schema ===\n")

            print("CONSTRAINTS:")
            result = session.run("SHOW CONSTRAINTS")
            for r in result:
                if "wiki" in r["name"].lower():
                    print(f"  - {r['name']}: {r['type']} on {r['labelsOrTypes']}")

            print("\nINDEXES:")
            result = session.run("SHOW INDEXES")
            for r in result:
                if r["type"] != "LOOKUP" and "wa_" in r["name"]:
                    print(f"  - {r['name']}: {r['type']} on {r['labelsOrTypes']} ({r['properties']})")

            print("\nNODE COUNTS:")
            for label in ["WikiArticle", "WikiCategory"]:
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

    parser = argparse.ArgumentParser(description="Setup Neo4j schema for Wiki Atlas (Phase 4)")
    parser.add_argument("--verify", action="store_true", help="Only verify current schema")
    parser.add_argument("--uri", default=NEO4J_URI)
    parser.add_argument("--user", default=NEO4J_USER)
    parser.add_argument("--password", default=NEO4J_PASSWORD)

    args = parser.parse_args()

    if args.verify:
        verify_schema(args.uri, args.user, args.password)
    else:
        success = setup_schema(args.uri, args.user, args.password)
        if not success:
            sys.exit(1)
        verify_schema(args.uri, args.user, args.password)
