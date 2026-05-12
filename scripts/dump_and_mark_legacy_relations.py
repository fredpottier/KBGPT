#!/usr/bin/env python3
"""
S0 — Dump + marquage des edges legacy V0 (CONTRADICTS/REFINES/QUALIFIES).

Stratégie en 2 temps (validée user + ChatGPT review) :
1. Dump JSONL complet des 12 503 edges legacy → data/forensics/legacy_relations_<ts>.jsonl
2. SET r.legacy = true sur toutes les edges CONTRADICTS/REFINES/QUALIFIES

PAS de suppression physique à ce stade. Les edges restent dans le KG mais le
runtime V3.3 les ignore via filtre `WHERE coalesce(r.legacy, false) = false`.

Suppression physique différée jusqu'à validation golden set en S3.F.

Idempotence :
- Si `r.legacy = true` est déjà set, l'edge est skippée (mais redumpée)
- Le timestamp dans le filename évite l'écrasement

Usage :
    docker exec knowbase-app python /app/scripts/dump_and_mark_legacy_relations.py

Estimé : ~30s sur 12 503 edges.
"""
from __future__ import annotations

import json
import logging
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

from neo4j import GraphDatabase

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

NEO4J_URI = os.getenv("NEO4J_URI", "bolt://neo4j:7687")
NEO4J_USER = os.getenv("NEO4J_USER", "neo4j")
NEO4J_PASSWORD = os.getenv("NEO4J_PASSWORD", "graphiti_neo4j_pass")
TENANT_ID = os.getenv("TENANT_ID", "default")
DRY_RUN = os.getenv("DRY_RUN", "false").lower() in ("1", "true", "yes")

LEGACY_RELATION_TYPES = ["CONTRADICTS", "REFINES", "QUALIFIES"]
BATCH_SIZE = 1000


def _serialize(value: Any) -> Any:
    if hasattr(value, "isoformat"):
        return value.isoformat()
    if isinstance(value, list):
        return [_serialize(v) for v in value]
    if isinstance(value, dict):
        return {k: _serialize(v) for k, v in value.items()}
    return value


def main() -> int:
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_dir = Path("/data/forensics") if Path("/data").exists() else Path("data/forensics")
    out_dir.mkdir(parents=True, exist_ok=True)
    dump_path = out_dir / f"legacy_relations_{ts}.jsonl"

    logger.info("=" * 70)
    logger.info("S0 step 2 — Dump + marquage legacy=true sur edges V0")
    logger.info("=" * 70)
    logger.info(f"Tenant : {TENANT_ID}")
    logger.info(f"Dump output : {dump_path}")
    logger.info(f"DRY_RUN : {DRY_RUN}")
    logger.info(f"Relation types : {LEGACY_RELATION_TYPES}")

    driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))

    summary: dict[str, dict] = {}

    try:
        with driver.session() as session:
            # === STEP 1 — Dump ===
            logger.info("\n--- STEP 1: Dump JSONL ---")
            total_dumped = 0
            with dump_path.open("w", encoding="utf-8") as f:
                for rel_type in LEGACY_RELATION_TYPES:
                    type_count = 0
                    type_already_legacy = 0
                    skip = 0
                    while True:
                        result = session.run(
                            f"MATCH (a:Claim)-[r:{rel_type}]->(b:Claim) "
                            f"WHERE coalesce(a.tenant_id, $tenant) = $tenant "
                            f"RETURN id(r) AS rel_id, "
                            f"       a.claim_id AS a_id, a.doc_id AS a_doc, "
                            f"       b.claim_id AS b_id, b.doc_id AS b_doc, "
                            f"       properties(r) AS props "
                            f"SKIP $skip LIMIT $limit",
                            tenant=TENANT_ID,
                            skip=skip,
                            limit=BATCH_SIZE,
                        )
                        rows = list(result)
                        if not rows:
                            break
                        for r in rows:
                            props = dict(r["props"])
                            if props.get("legacy") is True:
                                type_already_legacy += 1
                            record = {
                                "rel_id": r["rel_id"],
                                "type": rel_type,
                                "a_claim_id": r["a_id"],
                                "a_doc_id": r["a_doc"],
                                "b_claim_id": r["b_id"],
                                "b_doc_id": r["b_doc"],
                                "properties": _serialize(props),
                                "dumped_at": ts,
                            }
                            f.write(json.dumps(record, ensure_ascii=False) + "\n")
                            type_count += 1
                        skip += BATCH_SIZE
                    summary[rel_type] = {"dumped": type_count, "already_legacy": type_already_legacy}
                    total_dumped += type_count
                    logger.info(f"  {rel_type}: {type_count:,} dumped (déjà legacy : {type_already_legacy})")

            logger.info(f"\n  Total dumped : {total_dumped:,} relations → {dump_path.stat().st_size / 1024:.1f} KB")

            # === STEP 2 — Mark legacy=true ===
            logger.info("\n--- STEP 2: SET r.legacy = true ---")
            if DRY_RUN:
                logger.warning("DRY_RUN actif — pas de modification du KG")
                for rel_type in LEGACY_RELATION_TYPES:
                    result = session.run(
                        f"MATCH ()-[r:{rel_type}]->() "
                        f"WHERE coalesce(r.legacy, false) = false "
                        f"RETURN count(r) AS would_mark"
                    ).single()
                    logger.info(f"  [DRY_RUN] {rel_type}: would mark {result['would_mark']:,} relations")
            else:
                for rel_type in LEGACY_RELATION_TYPES:
                    result = session.run(
                        f"MATCH ()-[r:{rel_type}]->() "
                        f"WHERE coalesce(r.legacy, false) = false "
                        f"SET r.legacy = true, r.legacy_marked_at = $ts "
                        f"RETURN count(r) AS marked",
                        ts=ts,
                    ).single()
                    summary[rel_type]["marked"] = result["marked"]
                    logger.info(f"  {rel_type}: {result['marked']:,} marked legacy=true")

            # === Vérification ===
            logger.info("\n--- Vérification post-mark ---")
            for rel_type in LEGACY_RELATION_TYPES:
                result = session.run(
                    f"MATCH ()-[r:{rel_type}]->() "
                    f"RETURN sum(CASE WHEN coalesce(r.legacy, false) = true THEN 1 ELSE 0 END) AS legacy_count, "
                    f"       count(r) AS total"
                ).single()
                logger.info(f"  {rel_type}: {result['legacy_count']:,} / {result['total']:,} marked legacy")

        logger.info("\n--- Synthèse ---")
        for rel_type, stats in summary.items():
            logger.info(f"  {rel_type}: {stats}")

        if DRY_RUN:
            logger.info("\n⚠️ DRY_RUN — aucune modification appliquée. Re-run sans DRY_RUN=true pour appliquer.")
        else:
            logger.info("\n✅ Dump + marquage legacy réussi. Edges désormais filtrables via WHERE coalesce(r.legacy, false) = false.")
            logger.info(f"   Dump archivé : {dump_path}")

        return 0

    finally:
        driver.close()


if __name__ == "__main__":
    sys.exit(main())
