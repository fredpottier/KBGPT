#!/usr/bin/env python3
"""
Script de rattrapage Qdrant — ré-indexe les passages depuis Neo4j.

Usage (dans le container app) :
    python scripts/backfill_qdrant_from_neo4j.py [doc_id_prefix ...]

Exemples :
    # Re-indexer docs 029 et 027
    python scripts/backfill_qdrant_from_neo4j.py 029 027

    # Re-indexer TOUS les docs sans chunks Qdrant
    python scripts/backfill_qdrant_from_neo4j.py --all-missing

Le script :
1. Lit les passages uniques (passage_id, passage_text, page_no) depuis Neo4j
2. Les convertit en SubChunks
3. Les encode via le service embeddings (burst ou local)
4. Filtre les zero vectors (textes TEI-rejetés)
5. Upsert dans Qdrant Layer R
"""

import argparse
import logging
import sys
import time

import numpy as np

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s: %(message)s",
)
logger = logging.getLogger("backfill_qdrant")


def init_burst_from_redis():
    """
    Active le burst mode embeddings depuis l'état Redis.

    Le worker stocke l'état burst dans Redis (`osmose:burst:state`).
    Ce script tourne dans le container app — il doit activer le burst
    manuellement pour que les embeddings soient routés vers EC2.
    """
    from knowbase.ingestion.burst.provider_switch import get_burst_state_from_redis
    from knowbase.common.clients.embeddings import get_embedding_manager

    state = get_burst_state_from_redis()
    if not state or not state.get("active"):
        logger.error("Burst mode not active in Redis! Cannot route embeddings to EC2.")
        logger.error("Ensure the EC2 instance is running and burst is enabled.")
        sys.exit(1)

    embeddings_url = state.get("embeddings_url")
    if not embeddings_url:
        logger.error("No embeddings_url in Redis burst state!")
        sys.exit(1)

    manager = get_embedding_manager()
    manager.enable_burst_mode(embeddings_url, timeout=120)
    logger.info(f"Burst mode activated → {embeddings_url}")


def get_neo4j_driver():
    """Crée un driver Neo4j depuis la config applicative."""
    from neo4j import GraphDatabase
    from knowbase.config.settings import get_settings

    settings = get_settings()
    uri = settings.neo4j_uri
    user = settings.neo4j_user
    password = settings.neo4j_password
    return GraphDatabase.driver(uri, auth=(user, password))


def fetch_passages(driver, doc_id_prefix: str):
    """
    Récupère les passages uniques depuis les Claims Neo4j.

    Returns:
        list[dict] avec keys: passage_id, text, page_no, doc_id, tenant_id
    """
    query = """
    MATCH (c:Claim)
    WHERE c.doc_id STARTS WITH $prefix
    WITH DISTINCT c.passage_id AS passage_id,
                  c.passage_text AS text,
                  c.page_no AS page_no,
                  c.doc_id AS doc_id,
                  c.tenant_id AS tenant_id
    WHERE text IS NOT NULL AND size(text) >= 20
    RETURN passage_id, text, page_no, doc_id, tenant_id
    ORDER BY passage_id
    """
    with driver.session() as session:
        result = session.run(query, prefix=doc_id_prefix)
        passages = [dict(r) for r in result]
    return passages


def fetch_all_doc_ids(driver):
    """Liste tous les doc_ids présents dans Neo4j."""
    query = """
    MATCH (c:Claim)
    WITH DISTINCT c.doc_id AS doc_id, count(c) AS claim_count
    RETURN doc_id, claim_count
    ORDER BY doc_id
    """
    with driver.session() as session:
        result = session.run(query)
        return [(r["doc_id"], r["claim_count"]) for r in result]


def check_qdrant_coverage(doc_id: str, tenant_id: str = "default") -> int:
    """Retourne le nombre de points Qdrant pour un doc_id."""
    from qdrant_client.models import FieldCondition, Filter, MatchValue
    from knowbase.common.clients.qdrant_client import get_qdrant_client
    from knowbase.retrieval.qdrant_layer_r import COLLECTION_NAME

    client = get_qdrant_client()
    try:
        result = client.count(
            collection_name=COLLECTION_NAME,
            count_filter=Filter(
                must=[
                    FieldCondition(key="doc_id", match=MatchValue(value=doc_id)),
                    FieldCondition(key="tenant_id", match=MatchValue(value=tenant_id)),
                ]
            ),
        )
        return result.count
    except Exception:
        return 0


def backfill_doc(driver, doc_id_prefix: str):
    """Re-indexe un document dans Qdrant depuis ses passages Neo4j."""
    from knowbase.retrieval.qdrant_layer_r import (
        delete_doc_from_layer_r,
        ensure_layer_r_collection,
        upsert_layer_r,
    )
    from knowbase.retrieval.rechunker import SubChunk
    from knowbase.common.clients.embeddings import get_embedding_manager

    # 1. Récupérer les passages
    logger.info(f"Fetching passages for doc prefix '{doc_id_prefix}'...")
    passages = fetch_passages(driver, doc_id_prefix)
    if not passages:
        logger.warning(f"No passages found for prefix '{doc_id_prefix}'")
        return 0

    doc_id = passages[0]["doc_id"]
    tenant_id = passages[0]["tenant_id"] or "default"
    logger.info(f"  doc_id: {doc_id}")
    logger.info(f"  {len(passages)} unique passages")

    # 2. Supprimer les anciens points (idempotence)
    ensure_layer_r_collection()
    try:
        delete_doc_from_layer_r(doc_id, tenant_id)
        logger.info(f"  Deleted old Qdrant points for {doc_id}")
    except Exception as e:
        logger.debug(f"  Delete skipped: {e}")

    # 3. Convertir en SubChunks
    sub_chunks = []
    for p in passages:
        sc = SubChunk(
            chunk_id=p["passage_id"],
            sub_index=0,
            text=p["text"],
            parent_chunk_id=p["passage_id"],
            section_id=None,
            doc_id=doc_id,
            tenant_id=tenant_id,
            kind="NARRATIVE_TEXT",
            page_no=p["page_no"] or 0,
            page_span_min=p["page_no"],
            page_span_max=p["page_no"],
            item_ids=[],
            text_origin=f"claimfirst:{p['passage_id']}",
        )
        sub_chunks.append(sc)

    # 4. Encoder les embeddings
    logger.info(f"  Encoding {len(sub_chunks)} passages...")
    start = time.time()
    texts = [sc.text for sc in sub_chunks]
    manager = get_embedding_manager()
    embeddings = manager.encode(texts)
    elapsed = time.time() - start
    logger.info(f"  Encoding done in {elapsed:.1f}s")

    # 5. Filtrer les zero vectors
    pairs = []
    skipped = 0
    for sc, emb in zip(sub_chunks, embeddings):
        if np.any(emb != 0):
            pairs.append((sc, emb))
        else:
            skipped += 1

    if skipped > 0:
        logger.warning(f"  {skipped} passages skipped (zero vectors from TEI 413)")

    # 6. Upsert
    if pairs:
        n = upsert_layer_r(pairs, tenant_id=tenant_id)
        logger.info(f"  Upserted {n} points to Qdrant Layer R")
        return n
    else:
        logger.warning(f"  No valid embeddings — nothing upserted")
        return 0


def main():
    parser = argparse.ArgumentParser(
        description="Backfill Qdrant from Neo4j passages"
    )
    parser.add_argument(
        "doc_prefixes",
        nargs="*",
        help="Doc ID prefixes to re-index (e.g. '029' '027')",
    )
    parser.add_argument(
        "--all-missing",
        action="store_true",
        help="Find and re-index all docs with 0 Qdrant points",
    )
    args = parser.parse_args()

    if not args.doc_prefixes and not args.all_missing:
        parser.error("Specify doc prefixes or --all-missing")

    # Activer burst mode pour router les embeddings vers EC2
    init_burst_from_redis()

    driver = get_neo4j_driver()

    if args.all_missing:
        # Trouver tous les docs sans couverture Qdrant
        all_docs = fetch_all_doc_ids(driver)
        logger.info(f"Found {len(all_docs)} documents in Neo4j")

        targets = []
        for doc_id, claim_count in all_docs:
            qdrant_count = check_qdrant_coverage(doc_id)
            if qdrant_count == 0:
                targets.append(doc_id)
                logger.info(f"  MISSING: {doc_id} ({claim_count} claims, 0 Qdrant points)")
            else:
                logger.info(f"  OK: {doc_id} ({claim_count} claims, {qdrant_count} Qdrant points)")

        if not targets:
            logger.info("All documents have Qdrant coverage!")
            return

        logger.info(f"\n{len(targets)} documents to backfill:")
        for doc_id in targets:
            # Utiliser le doc_id complet comme prefix (pas juste 3 chars)
            backfill_doc(driver, doc_id)
    else:
        for prefix in args.doc_prefixes:
            backfill_doc(driver, prefix)

    driver.close()
    logger.info("Done.")


if __name__ == "__main__":
    main()
