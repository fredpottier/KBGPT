#!/usr/bin/env python
"""
backfill_claim_embeddings.py — Phase 1 du Claim↔Chunk Bridge.

Génère les embeddings pour toutes les claims dans Neo4j et crée le vector index.
Utilise le même modèle que Qdrant (intfloat/multilingual-e5-large, 1024d).

Usage:
    docker compose exec app python scripts/backfill_claim_embeddings.py
    docker compose exec app python scripts/backfill_claim_embeddings.py --batch-size 256
    docker compose exec app python scripts/backfill_claim_embeddings.py --dry-run
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
import time
from typing import List

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
logger = logging.getLogger("[OSMOSE] claim_embeddings")

EMBEDDING_MODEL = "intfloat/multilingual-e5-large"
EMBEDDING_VERSION = "v1.0"
EMBEDDING_DIM = 1024


def main():
    parser = argparse.ArgumentParser(description="Backfill claim embeddings dans Neo4j")
    parser.add_argument("--batch-size", type=int, default=256, help="Taille des batches")
    parser.add_argument("--dry-run", action="store_true", help="Compter sans exécuter")
    parser.add_argument("--tenant-id", default="default", help="Tenant ID")
    parser.add_argument("--force", action="store_true", help="Re-générer même si embedding existe")
    args = parser.parse_args()

    from neo4j import GraphDatabase

    uri = os.getenv("NEO4J_URI", "bolt://neo4j:7687")
    user = os.getenv("NEO4J_USER", "neo4j")
    password = os.getenv("NEO4J_PASSWORD", "graphiti_neo4j_pass")
    driver = GraphDatabase.driver(uri, auth=(user, password))

    # Compter les claims à traiter
    with driver.session() as session:
        if args.force:
            total = session.run(
                "MATCH (c:Claim {tenant_id: $tid}) RETURN count(c) as cnt",
                tid=args.tenant_id,
            ).single()["cnt"]
        else:
            total = session.run(
                "MATCH (c:Claim {tenant_id: $tid}) "
                "WHERE c.embedding IS NULL "
                "RETURN count(c) as cnt",
                tid=args.tenant_id,
            ).single()["cnt"]

    logger.info(f"Claims à traiter: {total}")

    if args.dry_run:
        logger.info(f"[DRY-RUN] {total} claims × {EMBEDDING_DIM}d = ~{total * EMBEDDING_DIM * 4 / 1024 / 1024:.0f} MB")
        driver.close()
        return

    if total == 0:
        logger.info("Aucune claim à traiter")
        driver.close()
        return

    # Charger le modèle d'embeddings
    logger.info(f"Chargement du modèle {EMBEDDING_MODEL}...")
    from knowbase.common.clients.embeddings import EmbeddingModelManager
    emb_manager = EmbeddingModelManager()
    model = emb_manager.get_model()
    dim = model.get_sentence_embedding_dimension()
    logger.info(f"Modèle chargé: {dim}d")

    # Traiter par batches
    processed = 0
    start_time = time.time()
    offset = 0

    while offset < total:
        with driver.session() as session:
            # Charger un batch de claims
            if args.force:
                result = session.run(
                    """
                    MATCH (c:Claim {tenant_id: $tid})
                    RETURN c.claim_id as claim_id, c.text as text
                    ORDER BY c.claim_id
                    SKIP $offset LIMIT $limit
                    """,
                    tid=args.tenant_id,
                    offset=offset,
                    limit=args.batch_size,
                )
            else:
                result = session.run(
                    """
                    MATCH (c:Claim {tenant_id: $tid})
                    WHERE c.embedding IS NULL
                    RETURN c.claim_id as claim_id, c.text as text
                    ORDER BY c.claim_id
                    SKIP $offset LIMIT $limit
                    """,
                    tid=args.tenant_id,
                    offset=offset,
                    limit=args.batch_size,
                )

            claims = [(r["claim_id"], r["text"] or "") for r in result]

        if not claims:
            break

        # Générer les embeddings en batch
        texts = [f"passage: {text}" for _, text in claims]  # e5 prefix
        embeddings = model.encode(texts, normalize_embeddings=True, batch_size=64)

        # Persister dans Neo4j
        batch_data = []
        for i, (claim_id, _) in enumerate(claims):
            batch_data.append({
                "claim_id": claim_id,
                "embedding": embeddings[i].tolist(),
            })

        with driver.session() as session:
            session.run(
                """
                UNWIND $batch AS item
                MATCH (c:Claim {claim_id: item.claim_id})
                SET c.embedding = item.embedding,
                    c.embedding_model = $model,
                    c.embedding_version = $version,
                    c.embedded_at = datetime()
                """,
                batch=batch_data,
                model=EMBEDDING_MODEL,
                version=EMBEDDING_VERSION,
            )

        processed += len(claims)
        elapsed = time.time() - start_time
        rate = processed / elapsed if elapsed > 0 else 0

        if processed % (args.batch_size * 4) == 0 or processed >= total:
            logger.info(
                f"  [{processed}/{total}] {rate:.0f} claims/s "
                f"({elapsed:.0f}s écoulées)"
            )

        offset += args.batch_size

    elapsed = time.time() - start_time
    logger.info(f"\n{'='*60}")
    logger.info(f"BACKFILL EMBEDDINGS TERMINÉ")
    logger.info(f"{'='*60}")
    logger.info(f"Claims traitées: {processed}")
    logger.info(f"Modèle: {EMBEDDING_MODEL} ({dim}d)")
    logger.info(f"Durée: {elapsed:.0f}s ({processed/elapsed:.0f} claims/s)")

    # Vérifier l'index
    with driver.session() as session:
        indexed = session.run(
            "MATCH (c:Claim {tenant_id: $tid}) "
            "WHERE c.embedding IS NOT NULL "
            "RETURN count(c) as cnt",
            tid=args.tenant_id,
        ).single()["cnt"]
    logger.info(f"Claims avec embedding: {indexed}/{total}")

    driver.close()


if __name__ == "__main__":
    main()
