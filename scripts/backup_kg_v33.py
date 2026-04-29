#!/usr/bin/env python3
"""
S0 — Backup KG complet avant migration V3.3 (read-only export).

Dump tous les nodes + relations du tenant en JSONL. Aucune modification
sur le KG. Restauration possible via script de réimport (à écrire séparément
si besoin).

Output structure :
    /data/forensics/kg_pre_v33_<ts>/
        nodes_<label>.jsonl       (1 fichier par label)
        relations_<type>.jsonl    (1 fichier par type de relation)
        manifest.json             (counts + metadata)

Le tout est read-only sur le KG. Utilise APOC si disponible pour streaming,
sinon batch Cypher manuel par label/type.

Usage :
    docker exec knowbase-app python /app/scripts/backup_kg_v33.py

Estimé : ~2-5 min sur 40K claims + 12.5K edges legacy + nodes auxiliaires.
"""
from __future__ import annotations

import json
import logging
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Iterator

from neo4j import GraphDatabase

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

NEO4J_URI = os.getenv("NEO4J_URI", "bolt://neo4j:7687")
NEO4J_USER = os.getenv("NEO4J_USER", "neo4j")
NEO4J_PASSWORD = os.getenv("NEO4J_PASSWORD", "graphiti_neo4j_pass")
TENANT_ID = os.getenv("TENANT_ID", "default")

LABELS_TO_BACKUP = [
    "Claim",
    "Entity",
    "CanonicalEntity",
    "Facet",
    "ClaimCluster",
    "DocumentContext",
    "SubjectAnchor",
    "ApplicabilityAxis",
    "ComparableSubject",
    "Perspective",
    "QuestionSignature",
]

RELATION_TYPES_TO_BACKUP = [
    "ABOUT",
    "BELONGS_TO_FACET",
    "IN_CLUSTER",
    "IN_DOCUMENT",
    "CONTRADICTS",          # legacy V0 — à dump puis marker en S0 step 2
    "REFINES",              # legacy V0
    "QUALIFIES",            # legacy V0
    "CHAINS_TO",
    "HAS_CONTEXT",
    "ABOUT_SUBJECT",
    "ABOUT_COMPARABLE",
    "POSSIBLE_EQUIVALENT",
    "HAS_AXIS_VALUE",
    "SIMILAR_TO",
    "SAME_CANON_AS",
    "EXTRACTED_FROM",
    "INCLUDES_CLAIM",
    "TOUCHES_SUBJECT",
    "HAS_PERSPECTIVE",
    "SPANS_FACET",
]

BATCH_SIZE = 5000


def _serialize(value: Any) -> Any:
    """JSON-serializable conversion for Neo4j types."""
    if hasattr(value, "isoformat"):  # datetime, date
        return value.isoformat()
    if isinstance(value, list):
        return [_serialize(v) for v in value]
    if isinstance(value, dict):
        return {k: _serialize(v) for k, v in value.items()}
    return value


def stream_nodes_by_label(session, label: str, tenant_id: str) -> Iterator[dict]:
    """Stream all nodes of a given label, batched."""
    skip = 0
    while True:
        result = session.run(
            f"MATCH (n:{label}) "
            f"WHERE coalesce(n.tenant_id, $tenant) = $tenant "
            f"RETURN id(n) AS internal_id, labels(n) AS labels, properties(n) AS props "
            f"SKIP $skip LIMIT $limit",
            tenant=tenant_id,
            skip=skip,
            limit=BATCH_SIZE,
        )
        rows = list(result)
        if not rows:
            return
        for r in rows:
            yield {
                "internal_id": r["internal_id"],
                "labels": r["labels"],
                "properties": _serialize(dict(r["props"])),
            }
        skip += BATCH_SIZE


def stream_relations_by_type(session, rel_type: str, tenant_id: str) -> Iterator[dict]:
    """Stream all relations of a given type."""
    skip = 0
    while True:
        # Filtre tenant via les endpoints
        result = session.run(
            f"MATCH (a)-[r:{rel_type}]->(b) "
            f"WHERE coalesce(a.tenant_id, $tenant) = $tenant "
            f"   OR coalesce(b.tenant_id, $tenant) = $tenant "
            f"RETURN id(r) AS rel_id, "
            f"       id(a) AS start_id, labels(a) AS start_labels, a.claim_id AS start_claim_id, a.doc_id AS start_doc_id, "
            f"       id(b) AS end_id, labels(b) AS end_labels, b.claim_id AS end_claim_id, b.doc_id AS end_doc_id, "
            f"       properties(r) AS props "
            f"SKIP $skip LIMIT $limit",
            tenant=tenant_id,
            skip=skip,
            limit=BATCH_SIZE,
        )
        rows = list(result)
        if not rows:
            return
        for r in rows:
            yield {
                "rel_id": r["rel_id"],
                "type": rel_type,
                "start": {
                    "id": r["start_id"],
                    "labels": r["start_labels"],
                    "claim_id": r["start_claim_id"],
                    "doc_id": r["start_doc_id"],
                },
                "end": {
                    "id": r["end_id"],
                    "labels": r["end_labels"],
                    "claim_id": r["end_claim_id"],
                    "doc_id": r["end_doc_id"],
                },
                "properties": _serialize(dict(r["props"])),
            }
        skip += BATCH_SIZE


def main() -> int:
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_root = Path("/data/forensics") if Path("/data").exists() else Path("data/forensics")
    out_dir = out_root / f"kg_pre_v33_{ts}"
    out_dir.mkdir(parents=True, exist_ok=True)

    logger.info("=" * 70)
    logger.info("S0 — Backup KG complet (pre-V3.3 migration)")
    logger.info("=" * 70)
    logger.info(f"Output : {out_dir}")
    logger.info(f"Tenant : {TENANT_ID}")

    driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))

    manifest: dict[str, Any] = {
        "metadata": {
            "timestamp": ts,
            "tenant_id": TENANT_ID,
            "neo4j_uri": NEO4J_URI,
            "purpose": "Backup before V3.3 schema migration (S0)",
        },
        "node_counts": {},
        "relation_counts": {},
    }

    try:
        with driver.session() as session:
            # === Backup nodes ===
            logger.info("\n--- Backup nodes ---")
            for label in LABELS_TO_BACKUP:
                out_file = out_dir / f"nodes_{label}.jsonl"
                count = 0
                with out_file.open("w", encoding="utf-8") as f:
                    for node in stream_nodes_by_label(session, label, TENANT_ID):
                        f.write(json.dumps(node, ensure_ascii=False) + "\n")
                        count += 1
                manifest["node_counts"][label] = count
                logger.info(f"  {label}: {count:,} nodes → {out_file.name}")

            # === Backup relations ===
            logger.info("\n--- Backup relations ---")
            for rel_type in RELATION_TYPES_TO_BACKUP:
                out_file = out_dir / f"relations_{rel_type}.jsonl"
                count = 0
                with out_file.open("w", encoding="utf-8") as f:
                    for rel in stream_relations_by_type(session, rel_type, TENANT_ID):
                        f.write(json.dumps(rel, ensure_ascii=False) + "\n")
                        count += 1
                manifest["relation_counts"][rel_type] = count
                logger.info(f"  {rel_type}: {count:,} relations → {out_file.name}")

        # === Manifest ===
        total_nodes = sum(manifest["node_counts"].values())
        total_rels = sum(manifest["relation_counts"].values())
        manifest["totals"] = {
            "nodes": total_nodes,
            "relations": total_rels,
        }

        manifest_path = out_dir / "manifest.json"
        manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")

        logger.info("\n--- Synthèse ---")
        logger.info(f"  Total nodes : {total_nodes:,}")
        logger.info(f"  Total relations : {total_rels:,}")
        logger.info(f"  Fichiers : {len(LABELS_TO_BACKUP) + len(RELATION_TYPES_TO_BACKUP)} JSONL + 1 manifest")
        logger.info(f"  Output : {out_dir}")

        # Tailles approximatives
        total_bytes = sum(f.stat().st_size for f in out_dir.iterdir() if f.is_file())
        logger.info(f"  Taille totale : {total_bytes / 1024 / 1024:.1f} MB")

        logger.info("\n✅ Backup pre-V3.3 réussi")
        return 0

    finally:
        driver.close()


if __name__ == "__main__":
    sys.exit(main())
