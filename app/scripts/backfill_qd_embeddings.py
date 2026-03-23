#!/usr/bin/env python3
"""
Backfill QuestionDimension embeddings dans Neo4j.

Embed les canonical_question des 382 QD via TEI (multilingual-e5-large)
et cree l'index vectoriel qd_embedding pour la recherche Phase B.

Usage:
    docker exec knowbase-app python scripts/backfill_qd_embeddings.py
    # Ou avec TEI burst explicite :
    docker exec knowbase-app python scripts/backfill_qd_embeddings.py --tei-url http://54.93.245.241:8001
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time

import requests

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
logger = logging.getLogger("backfill-qd")


def get_tei_url() -> str:
    """Determine l'URL TEI (burst ou local)."""
    url = os.environ.get("TEI_URL", "")
    if url:
        return url
    # Lire depuis Redis burst state
    try:
        import redis
        r = redis.from_url(os.environ.get("REDIS_URL", "redis://redis:6379/0"))
        state = r.get("osmose:burst:state")
        if state:
            return json.loads(state).get("embeddings_url", "")
    except Exception:
        pass
    return ""


def embed_batch(tei_url: str, texts: list[str], batch_size: int = 32) -> list[list[float]]:
    """Embed une liste de textes via TEI en batches."""
    all_embeddings = []
    for i in range(0, len(texts), batch_size):
        batch = texts[i:i + batch_size]
        resp = requests.post(
            f"{tei_url}/embed",
            json={"inputs": [f"query: {t}" for t in batch]},
            timeout=30,
        )
        if resp.status_code != 200:
            raise RuntimeError(f"TEI error {resp.status_code}: {resp.text[:200]}")
        all_embeddings.extend(resp.json())
        logger.info(f"  Embedded batch {i//batch_size + 1}: {len(batch)} texts")
    return all_embeddings


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--tei-url", default=None)
    parser.add_argument("--tenant-id", default="default")
    args = parser.parse_args()

    tei_url = args.tei_url or get_tei_url()
    if not tei_url:
        logger.error("No TEI URL found. Use --tei-url or set TEI_URL env var.")
        sys.exit(1)

    # Tester TEI
    try:
        resp = requests.post(f"{tei_url}/embed", json={"inputs": "test"}, timeout=5)
        dim = len(resp.json()[0])
        logger.info(f"TEI OK at {tei_url}, dimension={dim}")
    except Exception as e:
        logger.error(f"TEI unreachable at {tei_url}: {e}")
        sys.exit(1)

    # Charger les QD depuis Neo4j
    from knowbase.common.clients.neo4j_client import get_neo4j_client
    client = get_neo4j_client()

    with client.driver.session(database=client.database) as session:
        result = session.run(
            """
            MATCH (qd:QuestionDimension {tenant_id: $tid})
            WHERE qd.canonical_question IS NOT NULL
            RETURN qd.dimension_id AS dimension_id, qd.canonical_question AS question
            """,
            tid=args.tenant_id,
        )
        qds = [dict(r) for r in result]

    logger.info(f"Found {len(qds)} QuestionDimensions to embed")
    if not qds:
        return

    # Embed toutes les canonical_questions
    questions = [qd["question"] for qd in qds]
    embeddings = embed_batch(tei_url, questions)
    logger.info(f"Embedded {len(embeddings)} questions, dim={len(embeddings[0])}")

    # Stocker dans Neo4j
    with client.driver.session(database=client.database) as session:
        for qd, emb in zip(qds, embeddings):
            session.run(
                """
                MATCH (qd:QuestionDimension {dimension_id: $dim_id})
                SET qd.embedding = $embedding
                """,
                dim_id=qd["dimension_id"],
                embedding=emb,
            )
        logger.info(f"Stored {len(qds)} embeddings in Neo4j")

        # Creer l'index vectoriel
        try:
            session.run(
                f"""
                CREATE VECTOR INDEX qd_embedding IF NOT EXISTS
                FOR (qd:QuestionDimension) ON (qd.embedding)
                OPTIONS {{indexConfig: {{
                    `vector.dimensions`: {dim},
                    `vector.similarity_function`: 'cosine'
                }}}}
                """
            )
            logger.info(f"Created vector index qd_embedding (dim={dim})")
        except Exception as e:
            logger.warning(f"Index creation failed (may already exist): {e}")

    # Verifier
    with client.driver.session(database=client.database) as session:
        result = session.run(
            "MATCH (qd:QuestionDimension) WHERE qd.embedding IS NOT NULL RETURN count(qd) AS count"
        )
        count = result.single()["count"]
        logger.info(f"Verification: {count} QDs with embeddings")

    logger.info("Done!")


if __name__ == "__main__":
    main()
