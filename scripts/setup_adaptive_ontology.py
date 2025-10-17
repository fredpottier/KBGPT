#!/usr/bin/env python3
"""
Setup AdaptiveOntology Infrastructure in Neo4j

Crée les constraints et indexes pour le node AdaptiveOntology
utilisé par le LLM Canonicalizer.

Usage:
    docker-compose exec app python scripts/setup_adaptive_ontology.py
"""

import sys
import logging
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from knowbase.common.clients.neo4j_client import get_neo4j_client

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)
logger = logging.getLogger(__name__)


def setup_adaptive_ontology_schema(neo4j_client):
    """
    Crée schema AdaptiveOntology dans Neo4j.

    - Constraints unicité
    - Indexes lookup rapide
    - Fulltext search
    """

    logger.info("=" * 60)
    logger.info("SETUP ADAPTIVE ONTOLOGY SCHEMA")
    logger.info("=" * 60)

    with neo4j_client.driver.session(database=neo4j_client.database) as session:

        # ═══════════════════════════════════════════════════
        # CONSTRAINTS
        # ═══════════════════════════════════════════════════

        logger.info("\n📋 Creating Constraints...")

        # Contrainte unicité: (tenant_id, canonical_name) unique
        try:
            session.run("""
                CREATE CONSTRAINT adaptive_ontology_unique_canonical IF NOT EXISTS
                FOR (o:AdaptiveOntology)
                REQUIRE (o.tenant_id, o.canonical_name) IS UNIQUE
            """)
            logger.info("✅ Created constraint: adaptive_ontology_unique_canonical")
        except Exception as e:
            logger.warning(f"⚠️  Constraint already exists or error: {e}")

        # ═══════════════════════════════════════════════════
        # INDEXES
        # ═══════════════════════════════════════════════════

        logger.info("\n📋 Creating Indexes...")

        # Index tenant_id (filter par tenant)
        try:
            session.run("""
                CREATE INDEX adaptive_ontology_tenant IF NOT EXISTS
                FOR (o:AdaptiveOntology)
                ON (o.tenant_id)
            """)
            logger.info("✅ Created index: adaptive_ontology_tenant")
        except Exception as e:
            logger.warning(f"⚠️  Index already exists or error: {e}")

        # Index domain (recherche par domaine)
        try:
            session.run("""
                CREATE INDEX adaptive_ontology_domain IF NOT EXISTS
                FOR (o:AdaptiveOntology)
                ON (o.domain)
            """)
            logger.info("✅ Created index: adaptive_ontology_domain")
        except Exception as e:
            logger.warning(f"⚠️  Index already exists or error: {e}")

        # Index concept_type
        try:
            session.run("""
                CREATE INDEX adaptive_ontology_type IF NOT EXISTS
                FOR (o:AdaptiveOntology)
                ON (o.concept_type)
            """)
            logger.info("✅ Created index: adaptive_ontology_type")
        except Exception as e:
            logger.warning(f"⚠️  Index already exists or error: {e}")

        # ═══════════════════════════════════════════════════
        # FULLTEXT INDEX (recherche fuzzy)
        # ═══════════════════════════════════════════════════

        logger.info("\n📋 Creating Fulltext Index...")

        try:
            # Note: Fulltext index syntax differs
            session.run("""
                CREATE FULLTEXT INDEX adaptive_ontology_fulltext IF NOT EXISTS
                FOR (o:AdaptiveOntology)
                ON EACH [o.canonical_name, o.aliases]
            """)
            logger.info("✅ Created fulltext index: adaptive_ontology_fulltext")
        except Exception as e:
            logger.warning(f"⚠️  Fulltext index already exists or error: {e}")

        # ═══════════════════════════════════════════════════
        # VERIFICATION
        # ═══════════════════════════════════════════════════

        logger.info("\n📊 Verifying Schema...")

        # List all indexes
        result = session.run("SHOW INDEXES")
        indexes = [record["name"] for record in result if "adaptive_ontology" in record["name"]]

        logger.info(f"\n✅ AdaptiveOntology Indexes Created ({len(indexes)}):")
        for idx in indexes:
            logger.info(f"   - {idx}")

        # Count existing ontology entries
        result = session.run("""
            MATCH (o:AdaptiveOntology)
            RETURN count(o) AS total
        """)

        total = result.single()["total"]
        logger.info(f"\n📈 Current AdaptiveOntology entries: {total}")

    logger.info("\n" + "=" * 60)
    logger.info("✅ ADAPTIVE ONTOLOGY SCHEMA SETUP COMPLETE")
    logger.info("=" * 60)


def main():
    """Main setup script."""

    logger.info("Connecting to Neo4j...")

    neo4j_client = get_neo4j_client(
        uri="bolt://neo4j:7687",
        user="neo4j",
        password="graphiti_neo4j_pass",
        database="neo4j"
    )

    if not neo4j_client.is_connected():
        logger.error("❌ Failed to connect to Neo4j")
        sys.exit(1)

    logger.info("✅ Connected to Neo4j")

    # Setup schema
    setup_adaptive_ontology_schema(neo4j_client)

    logger.info("\n🎉 Setup complete! AdaptiveOntology infrastructure ready.")
    logger.info("\nNext steps:")
    logger.info("  1. Implement LLMCanonicalizer service")
    logger.info("  2. Implement AdaptiveOntologyManager")
    logger.info("  3. Integrate with Gatekeeper")


if __name__ == "__main__":
    main()
