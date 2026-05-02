#!/usr/bin/env python3
"""
Backfill CH-02.1 — `lifecycle_status` sur DocumentContext.

Conformément à VISION_RECENTREE_OSMOSIS_2026-04-30 §1bis (séparation KG/runtime) :
- Le `lifecycle_status` reflète un **fait observable du KG** : si un autre doc a
  une déclaration textuelle explicite l'abrogeant (LIFECYCLE_RELATION SUPERSEDES
  entrante), il est DEPRECATED. Sinon ACTIVE.
- Pas d'inférence runtime : on s'appuie strictement sur les LIFECYCLE_RELATION
  déjà persistées par CH-V2-S1 (extraction sémantique LLM evidence-locked).
- EVOLVES_FROM entrant ne déclenche PAS DEPRECATED : c'est un lien de filiation
  (ex: les actes délégués 2023/66 EVOLVES_FROM 2021/821 ne déprécient pas le
  règlement de base — ils en amendent l'annexe).

Règle déterministe :
- DEPRECATED ⇔ il existe ≥1 in-edge `LIFECYCLE_RELATION {type: 'SUPERSEDES'}`
- ACTIVE sinon

Usage :
  docker exec knowbase-app python scripts/backfill_doc_lifecycle_status.py [--dry-run]
"""
from __future__ import annotations

import argparse
import logging
import os
import sys
from datetime import datetime

sys.path.insert(0, "/app/src")

from neo4j import GraphDatabase

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("backfill_doc_lifecycle_status")


NEO4J_URI = os.getenv("NEO4J_URI", "bolt://neo4j:7687")
NEO4J_USER = os.getenv("NEO4J_USER", "neo4j")
NEO4J_PASSWORD = os.getenv("NEO4J_PASSWORD", "graphiti_neo4j_pass")
TENANT_ID = os.getenv("TENANT_ID", "default")

SOURCE_TAG = "derived_from_supersedes_ch02_1_2026-05-02"


def audit_current_state(driver) -> dict:
    cypher = """
    MATCH (dc:DocumentContext) WHERE dc.tenant_id = $tid
    RETURN
      count(dc) AS total,
      count(dc.lifecycle_status) AS with_status,
      collect(DISTINCT dc.lifecycle_status) AS distinct_values
    """
    with driver.session() as session:
        return session.run(cypher, tid=TENANT_ID).single().data()


def compute_target_states(driver) -> list[dict]:
    """Calcule l'état cible pour chaque DC.

    DEPRECATED si ≥1 in-edge SUPERSEDES, ACTIVE sinon.
    """
    cypher = """
    MATCH (dc:DocumentContext) WHERE dc.tenant_id = $tid
    OPTIONAL MATCH (successor:DocumentContext)-[r:LIFECYCLE_RELATION {type: 'SUPERSEDES'}]->(dc)
    WITH dc, count(r) AS n_super_in
    RETURN
      dc.doc_id AS doc_id,
      coalesce(dc.lifecycle_status, '(null)') AS current_status,
      CASE WHEN n_super_in > 0 THEN 'DEPRECATED' ELSE 'ACTIVE' END AS target_status,
      n_super_in
    ORDER BY doc_id
    """
    with driver.session() as session:
        return session.run(cypher, tid=TENANT_ID).data()


def apply_states(driver, rows: list[dict]) -> int:
    """Persiste lifecycle_status + lifecycle_status_source. Idempotent."""
    cypher = """
    MATCH (dc:DocumentContext {doc_id: $doc_id, tenant_id: $tid})
    SET
      dc.lifecycle_status = $status,
      dc.lifecycle_status_source = $source,
      dc.lifecycle_status_set_at = $set_at
    RETURN dc.doc_id AS doc_id
    """
    set_at = datetime.utcnow().isoformat() + "Z"
    n = 0
    with driver.session() as session:
        for row in rows:
            r = session.run(
                cypher,
                doc_id=row["doc_id"],
                tid=TENANT_ID,
                status=row["target_status"],
                source=SOURCE_TAG,
                set_at=set_at,
            ).single()
            if r:
                n += 1
    return n


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="Affiche l'état cible sans persister")
    args = parser.parse_args()

    driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))
    try:
        before = audit_current_state(driver)
        logger.info(
            f"[CH-02.1] Avant : {before['total']} DC, "
            f"{before['with_status']} avec lifecycle_status, "
            f"valeurs distinctes={before['distinct_values']}"
        )

        rows = compute_target_states(driver)
        deprecated = [r for r in rows if r["target_status"] == "DEPRECATED"]
        active = [r for r in rows if r["target_status"] == "ACTIVE"]

        logger.info(f"[CH-02.1] Cible : {len(deprecated)} DEPRECATED, {len(active)} ACTIVE")
        for r in deprecated:
            logger.info(
                f"  → DEPRECATED : {r['doc_id']} "
                f"(current={r['current_status']}, n_super_in={r['n_super_in']})"
            )
        for r in active[:5]:
            logger.info(f"  · ACTIVE    : {r['doc_id']} (current={r['current_status']})")
        if len(active) > 5:
            logger.info(f"  · ... +{len(active) - 5} autres ACTIVE")

        if args.dry_run:
            logger.info("[CH-02.1] DRY-RUN — aucune persistence")
            return 0

        n = apply_states(driver, rows)
        logger.info(f"[CH-02.1] Persisté : {n}/{len(rows)} DC mis à jour")

        after = audit_current_state(driver)
        logger.info(
            f"[CH-02.1] Après : {after['with_status']}/{after['total']} avec lifecycle_status, "
            f"valeurs distinctes={after['distinct_values']}"
        )
        return 0
    finally:
        driver.close()


if __name__ == "__main__":
    sys.exit(main())
