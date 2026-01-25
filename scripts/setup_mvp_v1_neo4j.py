#!/usr/bin/env python3
"""
Setup Neo4j schema for MVP V1.

Creates constraints and indexes for Information, ClaimKey, and Contradiction nodes.

Usage:
    docker-compose exec app python scripts/setup_mvp_v1_neo4j.py

Reference: SPEC_IMPLEMENTATION_CLASSES_MVP_V1.md
"""

import os
import sys

# Add src to path for imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from knowbase.common.clients.neo4j_client import get_neo4j_client
import logging

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


CONSTRAINTS = [
    # InformationMVP constraints
    ("information_mvp_id", "CREATE CONSTRAINT information_mvp_id IF NOT EXISTS FOR (i:InformationMVP) REQUIRE i.information_id IS UNIQUE"),

    # ClaimKey constraints
    ("claimkey_id", "CREATE CONSTRAINT claimkey_id IF NOT EXISTS FOR (ck:ClaimKey) REQUIRE ck.claimkey_id IS UNIQUE"),

    # Contradiction constraints
    ("contradiction_id", "CREATE CONSTRAINT contradiction_id IF NOT EXISTS FOR (c:Contradiction) REQUIRE c.contradiction_id IS UNIQUE"),
]

INDEXES = [
    # InformationMVP indexes
    ("information_tenant", "CREATE INDEX information_mvp_tenant IF NOT EXISTS FOR (i:InformationMVP) ON (i.tenant_id)"),
    ("information_status", "CREATE INDEX information_mvp_status IF NOT EXISTS FOR (i:InformationMVP) ON (i.promotion_status)"),
    ("information_fingerprint", "CREATE INDEX information_mvp_fingerprint IF NOT EXISTS FOR (i:InformationMVP) ON (i.fingerprint)"),
    ("information_document", "CREATE INDEX information_mvp_document IF NOT EXISTS FOR (i:InformationMVP) ON (i.document_id)"),

    # ClaimKey indexes
    ("claimkey_tenant", "CREATE INDEX claimkey_tenant IF NOT EXISTS FOR (ck:ClaimKey) ON (ck.tenant_id)"),
    ("claimkey_status", "CREATE INDEX claimkey_status IF NOT EXISTS FOR (ck:ClaimKey) ON (ck.status)"),
    ("claimkey_key", "CREATE INDEX claimkey_key IF NOT EXISTS FOR (ck:ClaimKey) ON (ck.key)"),
    ("claimkey_domain", "CREATE INDEX claimkey_domain IF NOT EXISTS FOR (ck:ClaimKey) ON (ck.domain)"),

    # Contradiction indexes
    ("contradiction_claimkey", "CREATE INDEX contradiction_claimkey IF NOT EXISTS FOR (c:Contradiction) ON (c.claimkey_id)"),
]


def setup_neo4j_schema():
    """Setup Neo4j constraints and indexes for MVP V1."""
    client = get_neo4j_client()

    if not client.is_connected():
        logger.error("❌ Neo4j non connecté")
        return False

    logger.info("🔧 Configuration du schéma Neo4j pour MVP V1...")

    with client.driver.session() as session:
        # Create constraints
        logger.info("\n📋 Création des contraintes...")
        for name, query in CONSTRAINTS:
            try:
                session.run(query)
                logger.info(f"  ✓ Constraint {name}")
            except Exception as e:
                logger.warning(f"  ⚠ Constraint {name}: {e}")

        # Create indexes
        logger.info("\n📋 Création des index...")
        for name, query in INDEXES:
            try:
                session.run(query)
                logger.info(f"  ✓ Index {name}")
            except Exception as e:
                logger.warning(f"  ⚠ Index {name}: {e}")

    logger.info("\n✅ Schéma Neo4j MVP V1 configuré")
    return True


def verify_schema():
    """Verify Neo4j schema is correctly configured."""
    client = get_neo4j_client()

    if not client.is_connected():
        logger.error("❌ Neo4j non connecté")
        return False

    logger.info("\n🔍 Vérification du schéma...")

    with client.driver.session() as session:
        # Check constraints
        result = session.run("SHOW CONSTRAINTS")
        constraints = [r["name"] for r in result]

        # Check indexes
        result = session.run("SHOW INDEXES")
        indexes = [r["name"] for r in result]

        logger.info(f"\n📊 Résumé:")
        logger.info(f"  - {len(constraints)} contraintes trouvées")
        logger.info(f"  - {len(indexes)} index trouvés")

        # Check for our specific constraints/indexes
        mvp_constraints = [c for c in constraints if 'information' in c.lower() or 'claimkey' in c.lower() or 'contradiction' in c.lower()]
        mvp_indexes = [i for i in indexes if 'information_mvp' in i.lower() or 'claimkey' in i.lower() or 'contradiction' in i.lower()]

        logger.info(f"\n📋 Éléments MVP V1:")
        logger.info(f"  - Contraintes MVP: {mvp_constraints}")
        logger.info(f"  - Index MVP: {mvp_indexes}")

    return True


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Setup Neo4j schema for MVP V1")
    parser.add_argument("--verify", action="store_true", help="Only verify schema, don't create")
    args = parser.parse_args()

    if args.verify:
        verify_schema()
    else:
        setup_neo4j_schema()
        verify_schema()
