#!/usr/bin/env python3
"""
Backfill axis_values (release_id, version) dans les chunks Qdrant knowbase_chunks_v2.

Lit les axis_values depuis les nœuds DocumentContext dans Neo4j,
puis met à jour les payloads Qdrant correspondants.

Usage:
    python app/scripts/backfill_chunk_axis_values.py --dry-run   # Prévisualisation
    python app/scripts/backfill_chunk_axis_values.py              # Exécution réelle
"""

from __future__ import annotations

import argparse
import logging
import sys
from typing import Dict, Optional

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

COLLECTION = "knowbase_chunks_v2"
BATCH_SIZE = 100


def _get_axis_map_from_neo4j(tenant_id: str) -> Dict[str, Dict[str, str]]:
    """Lit les axis_values de chaque DocumentContext dans Neo4j.

    Returns:
        {doc_id: {axis_key: scalar_value, ...}}
    """
    from neo4j import GraphDatabase
    from knowbase.config.settings import get_settings

    settings = get_settings()
    driver = GraphDatabase.driver(
        settings.neo4j_uri,
        auth=(settings.neo4j_user, settings.neo4j_password),
    )

    cypher = """
    MATCH (dc:DocumentContext {tenant_id: $tid})
    WHERE dc.axis_values IS NOT NULL
    RETURN dc.doc_id AS doc_id, dc.axis_values AS axis_values
    """

    result_map: Dict[str, Dict[str, str]] = {}
    try:
        with driver.session() as session:
            records = session.run(cypher, tid=tenant_id)
            for rec in records:
                doc_id = rec["doc_id"]
                raw = rec["axis_values"]
                if not raw:
                    continue

                # axis_values est stocké comme JSON string ou dict dans Neo4j
                import json
                if isinstance(raw, str):
                    try:
                        raw = json.loads(raw)
                    except json.JSONDecodeError:
                        continue

                axis_map: Dict[str, str] = {}
                for k, v in raw.items():
                    if isinstance(v, dict) and v.get("scalar_value"):
                        axis_map[k] = v["scalar_value"]
                    elif isinstance(v, str):
                        axis_map[k] = v

                if axis_map:
                    result_map[doc_id] = axis_map
    finally:
        driver.close()

    return result_map


def backfill(tenant_id: str = "default", dry_run: bool = True) -> None:
    """Backfill les axis_values dans les chunks Qdrant."""
    from qdrant_client.models import (
        FieldCondition,
        Filter,
        MatchValue,
        SetPayload,
    )
    from knowbase.common.clients.qdrant_client import get_qdrant_client

    # 1. Lire axis_values depuis Neo4j
    logger.info("[Backfill] Lecture des axis_values depuis Neo4j...")
    axis_data = _get_axis_map_from_neo4j(tenant_id)
    logger.info(f"[Backfill] {len(axis_data)} documents avec axis_values trouvés")

    if not axis_data:
        logger.info("[Backfill] Rien à faire.")
        return

    client = get_qdrant_client()
    if not client.collection_exists(COLLECTION):
        logger.error(f"[Backfill] Collection {COLLECTION} n'existe pas !")
        return

    # 2. Pour chaque doc_id avec axis_values, mettre à jour les chunks
    updated_docs = 0
    updated_points = 0
    skipped = 0

    for doc_id, axis_map in axis_data.items():
        payload_update = {}
        if "release_id" in axis_map:
            payload_update["axis_release_id"] = axis_map["release_id"]
        if "version" in axis_map:
            payload_update["axis_version"] = axis_map["version"]

        if not payload_update:
            skipped += 1
            continue

        if dry_run:
            logger.info(f"  [DRY-RUN] {doc_id} → {payload_update}")
            updated_docs += 1
            continue

        # Mise à jour effective via set_payload avec filtre
        try:
            client.set_payload(
                collection_name=COLLECTION,
                payload=payload_update,
                points=Filter(
                    must=[
                        FieldCondition(key="doc_id", match=MatchValue(value=doc_id)),
                        FieldCondition(key="tenant_id", match=MatchValue(value=tenant_id)),
                    ]
                ),
            )
            updated_docs += 1
            logger.debug(f"  Updated {doc_id} → {payload_update}")
        except Exception as e:
            logger.warning(f"  Failed for {doc_id}: {e}")

    mode = "DRY-RUN" if dry_run else "LIVE"
    logger.info(
        f"[Backfill] [{mode}] Terminé: {updated_docs} docs mis à jour, "
        f"{skipped} skipped (pas de release_id/version)"
    )


def main():
    parser = argparse.ArgumentParser(description="Backfill axis_values dans Qdrant chunks")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        default=False,
        help="Mode prévisualisation (pas de modification)",
    )
    parser.add_argument(
        "--tenant-id",
        default="default",
        help="Tenant ID (default: 'default')",
    )
    args = parser.parse_args()

    backfill(tenant_id=args.tenant_id, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
