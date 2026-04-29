#!/usr/bin/env python3
"""
S0 — Migration schema Neo4j vers V3.3 (idempotent, additif uniquement).

Applique les nouvelles contraintes/indexes V3.3 ajoutés à `neo4j_schema.py`
sans toucher aux données existantes. La fonction `setup_claimfirst_schema()`
est idempotente (CREATE CONSTRAINT/INDEX IF NOT EXISTS) — peut être rejouée
sans risque.

Nouveaux indexes ajoutés en V3.3 (additifs) :
- claim_lifecycle_status
- claim_publication_date
- claim_validity_start
- claim_validity_end
- doccontext_publication_date

Ajoute aussi `LOGICAL_RELATION` à la liste des RELATION_TYPES déclarés
(impact zéro côté Neo4j puisque les types de relations ne sont pas
formellement déclarés, c'est juste de la documentation).

Usage :
    docker exec knowbase-app python /app/scripts/migrate_kg_v33_schema.py

Vérification post-migration :
    docker exec knowbase-neo4j cypher-shell -u neo4j -p graphiti_neo4j_pass \\
        "SHOW INDEXES YIELD name WHERE name STARTS WITH 'claim_validity' RETURN name"
"""
from __future__ import annotations

import logging
import os
import sys
from datetime import datetime

from neo4j import GraphDatabase

# Path setup pour importer depuis src/
sys.path.insert(0, "/app/src")

from knowbase.claimfirst.persistence.neo4j_schema import (  # noqa: E402
    ClaimFirstSchema,
    setup_claimfirst_schema,
    verify_claimfirst_schema,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)


def main() -> int:
    neo4j_uri = os.getenv("NEO4J_URI", "bolt://neo4j:7687")
    neo4j_user = os.getenv("NEO4J_USER", "neo4j")
    neo4j_password = os.getenv("NEO4J_PASSWORD", "graphiti_neo4j_pass")

    logger.info("=" * 70)
    logger.info("S0 — Migration KG schema vers V3.3 (idempotent)")
    logger.info("=" * 70)
    logger.info(f"Neo4j URI : {neo4j_uri}")
    logger.info(f"Timestamp : {datetime.now().isoformat()}")

    schema = ClaimFirstSchema()
    logger.info(f"Total constraints à vérifier : {len(schema.constraints)}")
    logger.info(f"Total indexes à vérifier : {len(schema.indexes)}")

    # Lister les nouveaux indexes V3.3 attendus
    v33_new_indexes = [
        "claim_lifecycle_status",
        "claim_publication_date",
        "claim_validity_start",
        "claim_validity_end",
        "doccontext_publication_date",
    ]
    logger.info(f"Nouveaux indexes V3.3 attendus : {v33_new_indexes}")

    driver = GraphDatabase.driver(neo4j_uri, auth=(neo4j_user, neo4j_password))
    try:
        # 1. Etat avant migration
        logger.info("\n--- État schema AVANT migration ---")
        before = verify_claimfirst_schema(driver)
        existing_idx_before = set(before["existing_indexes"])
        missing_idx_before = set(before["missing_indexes"])
        logger.info(f"  Constraints existantes : {len(before['existing_constraints'])}")
        logger.info(f"  Indexes existants : {len(existing_idx_before)}")
        logger.info(f"  Indexes manquants : {len(missing_idx_before)} → {sorted(missing_idx_before)}")

        # 2. Migration (idempotente)
        logger.info("\n--- Application migration V3.3 ---")
        stats = setup_claimfirst_schema(driver, drop_existing=False)
        logger.info(f"  Constraints créées : {stats['constraints_created']}")
        logger.info(f"  Constraints skippées (déjà existantes) : {stats['constraints_skipped']}")
        logger.info(f"  Indexes créés : {stats['indexes_created']}")
        logger.info(f"  Indexes skippés (déjà existants) : {stats['indexes_skipped']}")
        if stats["errors"]:
            logger.error(f"  Erreurs : {stats['errors']}")
            return 1

        # 3. Vérification post-migration
        logger.info("\n--- État schema APRÈS migration ---")
        after = verify_claimfirst_schema(driver)
        existing_idx_after = set(after["existing_indexes"])
        missing_idx_after = set(after["missing_indexes"])
        newly_created = existing_idx_after - existing_idx_before
        logger.info(f"  Indexes existants : {len(existing_idx_after)}")
        logger.info(f"  Indexes manquants : {len(missing_idx_after)} → {sorted(missing_idx_after)}")
        logger.info(f"  Indexes nouvellement créés : {sorted(newly_created)}")

        # 4. Validation des nouveaux indexes V3.3
        logger.info("\n--- Validation indexes V3.3 ---")
        all_v33_present = True
        for idx_name in v33_new_indexes:
            if idx_name in existing_idx_after:
                logger.info(f"  ✅ {idx_name}")
            else:
                logger.error(f"  ❌ {idx_name} MANQUANT")
                all_v33_present = False

        if not all_v33_present:
            logger.error("Migration INCOMPLÈTE — certains indexes V3.3 manquent")
            return 2

        # 5. Stats finales
        with driver.session() as s:
            count = s.run("MATCH (c:Claim) WHERE c.tenant_id='default' RETURN count(c) AS n").single()["n"]
            logger.info(f"\n--- Stats finales ---")
            logger.info(f"  Total claims : {count:,}")

        logger.info("\n✅ Migration V3.3 schema réussie (idempotente)")
        return 0

    finally:
        driver.close()


if __name__ == "__main__":
    sys.exit(main())
