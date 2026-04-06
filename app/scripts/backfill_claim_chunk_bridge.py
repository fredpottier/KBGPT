#!/usr/bin/env python
"""
backfill_claim_chunk_bridge.py — Phase 2 du Claim↔Chunk Bridge.

Matche chaque claim à son/ses chunk(s) source(s) dans Qdrant via :
1. Filtre par doc_id (même document)
2. Substring match du verbatim_quote dans le chunk text
3. Fallback : similarité cosine embedding

Persiste chunk_ids sur les claims dans Neo4j.

Usage:
    docker compose exec app python scripts/backfill_claim_chunk_bridge.py
    docker compose exec app python scripts/backfill_claim_chunk_bridge.py --dry-run
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
import time
from typing import Dict, List, Optional, Tuple

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
logger = logging.getLogger("[OSMOSE] claim_chunk_bridge")


def normalize_text(text: str) -> str:
    """Normalise un texte pour la comparaison substring."""
    import re
    # Lowercase, supprime whitespace multiples, supprime ponctuation isolée
    t = text.lower().strip()
    t = re.sub(r'\s+', ' ', t)
    return t


def find_chunk_for_claim(
    verbatim: str,
    doc_id: str,
    chunks_by_doc: Dict[str, List[dict]],
    claim_text: str = "",
) -> Optional[str]:
    """
    Trouve le chunk_id qui contient le verbatim_quote ou le claim text.

    Algorithme 4 niveaux (conforme CLAIM_CHUNK_BRIDGE_PLAN.md) :
    1. Substring exact du verbatim dans le chunk
    2. Substring des premiers 80 chars du verbatim
    3. Overlap mot-à-mot verbatim → chunk (seuil 0.6)
    4. Overlap mot-à-mot claim_text → chunk (seuil 0.5, plus permissif)

    Returns:
        chunk_id ou None
    """
    doc_chunks = chunks_by_doc.get(doc_id, [])
    if not doc_chunks:
        return None

    # Essayer d'abord avec le verbatim
    if verbatim and len(verbatim) >= 20:
        verbatim_norm = normalize_text(verbatim)

        # 1. Substring match exact
        for chunk in doc_chunks:
            chunk_norm = normalize_text(chunk["text"])
            if verbatim_norm in chunk_norm:
                return chunk["chunk_id"]

        # 2. Substring premiers 80 chars (verbatim tronqué)
        verbatim_start = verbatim_norm[:80]
        if len(verbatim_start) >= 30:
            for chunk in doc_chunks:
                chunk_norm = normalize_text(chunk["text"])
                if verbatim_start in chunk_norm:
                    return chunk["chunk_id"]

        # 3. Overlap ratio verbatim → chunk (seuil 0.6)
        verbatim_words = set(verbatim_norm.split())
        if len(verbatim_words) >= 4:
            best_chunk_id = None
            best_overlap = 0.0
            for chunk in doc_chunks:
                chunk_words = set(normalize_text(chunk["text"]).split())
                if not chunk_words:
                    continue
                overlap = len(verbatim_words & chunk_words) / len(verbatim_words)
                if overlap > best_overlap:
                    best_overlap = overlap
                    best_chunk_id = chunk["chunk_id"]
            if best_overlap >= 0.6:
                return best_chunk_id

    # 4. Fallback : overlap claim_text → chunk (plus permissif)
    text_to_match = claim_text or verbatim or ""
    if len(text_to_match) < 15:
        return None

    text_norm = normalize_text(text_to_match)
    text_words = set(text_norm.split())
    if len(text_words) < 3:
        return None

    best_chunk_id = None
    best_overlap = 0.0
    for chunk in doc_chunks:
        chunk_words = set(normalize_text(chunk["text"]).split())
        if not chunk_words:
            continue
        overlap = len(text_words & chunk_words) / len(text_words)
        if overlap > best_overlap:
            best_overlap = overlap
            best_chunk_id = chunk["chunk_id"]

    if best_overlap >= 0.5:
        return best_chunk_id

    return None


def main():
    parser = argparse.ArgumentParser(description="Bridge claims ↔ chunks Qdrant")
    parser.add_argument("--dry-run", action="store_true", help="Compter sans persister")
    parser.add_argument("--tenant-id", default="default", help="Tenant ID")
    parser.add_argument("--batch-size", type=int, default=500, help="Batch size pour Neo4j")
    args = parser.parse_args()

    from neo4j import GraphDatabase

    uri = os.getenv("NEO4J_URI", "bolt://neo4j:7687")
    user = os.getenv("NEO4J_USER", "neo4j")
    password = os.getenv("NEO4J_PASSWORD", "graphiti_neo4j_pass")
    driver = GraphDatabase.driver(uri, auth=(user, password))

    # 1. Charger tous les chunks depuis Qdrant, groupés par doc_id
    logger.info("Chargement des chunks depuis Qdrant...")
    chunks_by_doc = _load_chunks_from_qdrant(args.tenant_id)
    total_chunks = sum(len(v) for v in chunks_by_doc.values())
    logger.info(f"  {total_chunks} chunks dans {len(chunks_by_doc)} documents")

    # 2. Charger les claims depuis Neo4j
    logger.info("Chargement des claims depuis Neo4j...")
    with driver.session() as session:
        result = session.run(
            """
            MATCH (c:Claim {tenant_id: $tid})
            RETURN c.claim_id as claim_id, c.doc_id as doc_id,
                   c.verbatim_quote as verbatim_quote, c.text as claim_text
            """,
            tid=args.tenant_id,
        )
        claims = [
            (r["claim_id"], r["doc_id"] or "", r["verbatim_quote"] or "", r["claim_text"] or "")
            for r in result
        ]
    logger.info(f"  {len(claims)} claims à traiter")

    # 3. Matcher
    logger.info("Matching claims → chunks...")
    start = time.time()
    matched = 0
    unmatched = 0
    bridge_data = []  # (claim_id, chunk_id)

    for claim_id, doc_id, verbatim, claim_text in claims:
        chunk_id = find_chunk_for_claim(verbatim, doc_id, chunks_by_doc, claim_text)
        if chunk_id:
            bridge_data.append({"claim_id": claim_id, "chunk_id": chunk_id})
            matched += 1
        else:
            unmatched += 1

    elapsed = time.time() - start
    coverage = matched / len(claims) * 100 if claims else 0

    logger.info(f"\n{'='*60}")
    logger.info(f"BRIDGE CLAIM↔CHUNK")
    logger.info(f"{'='*60}")
    logger.info(f"Claims traitées: {len(claims)}")
    logger.info(f"Matchées: {matched} ({coverage:.1f}%)")
    logger.info(f"Non matchées: {unmatched}")
    logger.info(f"Durée matching: {elapsed:.1f}s")

    if args.dry_run:
        logger.info("[DRY-RUN] Aucune persistance")
        driver.close()
        return

    # 4. Persister chunk_ids sur les claims dans Neo4j
    logger.info("\nPersistance des liens claim→chunk dans Neo4j...")
    persisted = 0

    for batch_start in range(0, len(bridge_data), args.batch_size):
        batch = bridge_data[batch_start:batch_start + args.batch_size]
        with driver.session() as session:
            session.run(
                """
                UNWIND $batch AS item
                MATCH (c:Claim {claim_id: item.claim_id})
                SET c.chunk_ids = [item.chunk_id]
                """,
                batch=batch,
            )
        persisted += len(batch)

    logger.info(f"  {persisted} liens persistés dans Neo4j")

    # 5. Mettre à jour les payloads Qdrant avec claim_ids
    logger.info("Mise à jour des payloads Qdrant avec claim_ids...")
    _update_qdrant_payloads(bridge_data, args.tenant_id)

    driver.close()
    logger.info("Bridge terminé")


def _load_chunks_from_qdrant(tenant_id: str) -> Dict[str, List[dict]]:
    """Charge tous les chunks Qdrant groupés par doc_id."""
    import requests

    qdrant_url = os.getenv("QDRANT_URL", "http://qdrant:6333")
    collection = "knowbase_chunks_v2"

    chunks_by_doc: Dict[str, List[dict]] = {}
    offset = None
    total = 0

    while True:
        body = {
            "limit": 1000,
            "with_payload": ["chunk_id", "doc_id", "text", "tenant_id"],
            "with_vector": False,
            "filter": {
                "must": [
                    {"key": "tenant_id", "match": {"value": tenant_id}}
                ]
            },
        }
        if offset:
            body["offset"] = offset

        resp = requests.post(
            f"{qdrant_url}/collections/{collection}/points/scroll",
            json=body,
            timeout=30,
        )
        data = resp.json().get("result", {})
        points = data.get("points", [])

        if not points:
            break

        for point in points:
            payload = point.get("payload", {})
            doc_id = payload.get("doc_id", "")
            chunk_id = payload.get("chunk_id", "")
            text = payload.get("text", "")

            if doc_id and text:
                if doc_id not in chunks_by_doc:
                    chunks_by_doc[doc_id] = []
                chunks_by_doc[doc_id].append({
                    "chunk_id": chunk_id or str(point.get("id", "")),
                    "text": text,
                    "point_id": point.get("id"),
                })
                total += 1

        offset = data.get("next_page_offset")
        if not offset:
            break

    return chunks_by_doc


def _update_qdrant_payloads(bridge_data: list, tenant_id: str):
    """Met à jour les payloads Qdrant avec les claim_ids."""
    import requests
    from collections import defaultdict

    qdrant_url = os.getenv("QDRANT_URL", "http://qdrant:6333")
    collection = "knowbase_chunks_v2"

    # Grouper par chunk_id
    claims_by_chunk: Dict[str, List[str]] = defaultdict(list)
    for item in bridge_data:
        claims_by_chunk[item["chunk_id"]].append(item["claim_id"])

    # On ne peut pas mettre à jour par chunk_id directement dans Qdrant
    # (il faut le point_id). Pour l'instant, on logge le résultat.
    logger.info(f"  {len(claims_by_chunk)} chunks à mettre à jour dans Qdrant")
    logger.info(f"  (Mise à jour Qdrant payloads différée — nécessite point_id mapping)")


if __name__ == "__main__":
    main()
