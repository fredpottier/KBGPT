"""
OSMOSE Retrieval Layer R — Gestion collection Qdrant knowbase_chunks_v2.

Responsabilités:
- Création/vérification de la collection Qdrant
- Upsert idempotent des sub-chunks avec embeddings
- Suppression par document (pour re-import)
- Recherche TEXT_ONLY (RAG fallback)

Spec: ADR_QDRANT_RETRIEVAL_PROJECTION_V2.md
"""

from __future__ import annotations

import logging
import os
from typing import Dict, List, Optional, Tuple

import numpy as np
from qdrant_client.models import (
    Distance,
    FieldCondition,
    Filter,
    MatchValue,
    PointStruct,
    VectorParams,
)

from knowbase.common.clients.qdrant_client import get_qdrant_client
from knowbase.retrieval.rechunker import SubChunk

logger = logging.getLogger(__name__)

# --- Constantes Layer R ---
COLLECTION_NAME = "knowbase_chunks_v2"
VECTOR_SIZE = 1024
DISTANCE = Distance.COSINE
SCHEMA_VERSION = "v2_layer_r_1"


def ensure_layer_r_collection() -> None:
    """Crée la collection knowbase_chunks_v2 si elle n'existe pas, + payload indexes."""
    client = get_qdrant_client()
    if client.collection_exists(COLLECTION_NAME):
        logger.debug(f"[OSMOSE:LayerR] Collection {COLLECTION_NAME} already exists")
        ensure_axis_indexes()
        return

    client.create_collection(
        collection_name=COLLECTION_NAME,
        vectors_config=VectorParams(size=VECTOR_SIZE, distance=DISTANCE),
    )
    logger.info(
        f"[OSMOSE:LayerR] Created collection {COLLECTION_NAME} "
        f"(size={VECTOR_SIZE}, distance={DISTANCE})"
    )
    ensure_axis_indexes()


def ensure_axis_indexes() -> None:
    """Crée les payload indexes keyword sur axis_release_id et axis_version."""
    from qdrant_client.models import PayloadSchemaType, TextIndexParams, TokenizerType

    client = get_qdrant_client()
    # `tenant_id` : index payload KEYWORD pour le filtrage multi-corpus efficace à
    # l'échelle (collection partagée + filtre tenant_id, cf CH_CORPUS_SWITCH.md).
    for field_name in ("tenant_id", "axis_release_id", "axis_version"):
        try:
            client.create_payload_index(
                collection_name=COLLECTION_NAME,
                field_name=field_name,
                field_schema=PayloadSchemaType.KEYWORD,
            )
        except Exception:
            pass

    # Text index sur le champ 'text' pour hybrid BM25+dense search
    try:
        client.create_payload_index(
            collection_name=COLLECTION_NAME,
            field_name="text",
            field_schema=TextIndexParams(
                type="text",
                tokenizer=TokenizerType.WORD,
                min_token_len=2,
                max_token_len=40,
                lowercase=True,
            ),
        )
        logger.info("[OSMOSE:LayerR] Created text index on 'text' field (hybrid BM25)")
    except Exception:
        pass


def upsert_layer_r(
    sub_chunks_with_embeddings: List[Tuple[SubChunk, np.ndarray]],
    tenant_id: str,
    batch_size: int = 0,
    doc_axis_values: Optional[Dict[str, str]] = None,
    max_retries: int = 3,
) -> int:
    """
    Upsert idempotent des sub-chunks + embeddings dans Qdrant.

    Chaque point a un point_id déterministe (UUID5) → re-upsert = même points.
    Retry par batch avec backoff exponentiel pour resilience (incident 2026-04-27).

    Args:
        sub_chunks_with_embeddings: Liste de (SubChunk, embedding_vector)
        tenant_id: ID du tenant
        batch_size: Taille des batches d'upsert (0 = auto depuis env)
        max_retries: Nombre de tentatives par batch en cas d'erreur transitoire (defaut: 3)

    Returns:
        Nombre de points upsertés (peut être < total si certains batches ont échoué après retries)
    """
    import time as _time

    if not sub_chunks_with_embeddings:
        return 0

    # batch_size configurable via env var
    if batch_size <= 0:
        batch_size = int(os.environ.get("QDRANT_UPSERT_BATCH_SIZE", "500"))

    ensure_layer_r_collection()
    client = get_qdrant_client()

    total = len(sub_chunks_with_embeddings)
    upserted = 0
    failed_batches = 0
    n_batches = (total + batch_size - 1) // batch_size

    for batch_start in range(0, total, batch_size):
        batch = sub_chunks_with_embeddings[batch_start : batch_start + batch_size]
        batch_idx = batch_start // batch_size + 1

        points = []
        for sc, embedding in batch:
            payload = {
                # Identifiants
                "chunk_id": sc.chunk_id,
                "sub_index": sc.sub_index,
                "parent_chunk_id": sc.parent_chunk_id,
                "doc_id": sc.doc_id,
                "tenant_id": sc.tenant_id,
                "section_id": sc.section_id,
                # Contenu (pour affichage dans les résultats de recherche)
                "text": sc.text,
                # Metadata
                "kind": sc.kind,
                "page_no": sc.page_no,
                "page_span_min": sc.page_span_min,
                "page_span_max": sc.page_span_max,
                "item_ids": sc.item_ids,
                "text_origin": sc.text_origin,
                # Payload versionné (migrations futures)
                "schema_version": SCHEMA_VERSION,
                "point_type": "sub_chunk",
                # Axis values (B.1: filtrage par version/release)
                "axis_release_id": doc_axis_values.get("release_id") if doc_axis_values else None,
                "axis_version": doc_axis_values.get("version") if doc_axis_values else None,
            }

            points.append(PointStruct(
                id=sc.point_id(),
                vector=embedding.tolist() if hasattr(embedding, "tolist") else list(embedding),
                payload=payload,
            ))

        # Retry par batch (incident 2026-04-27 — gros docs causent des timeouts)
        last_err = None
        success = False
        for attempt in range(max_retries):
            try:
                client.upsert(
                    collection_name=COLLECTION_NAME,
                    points=points,
                    wait=True,  # Synchroniser pour detecter erreurs immediatement
                )
                upserted += len(points)
                success = True
                break
            except Exception as e:
                last_err = e
                wait = 2 ** attempt  # 1, 2, 4 sec
                logger.warning(
                    f"[OSMOSE:LayerR] Upsert batch {batch_idx}/{n_batches} attempt "
                    f"{attempt + 1}/{max_retries} failed ({len(points)} points): "
                    f"{type(e).__name__}: {e}. Retry in {wait}s",
                )
                _time.sleep(wait)

        if not success:
            failed_batches += 1
            logger.error(
                f"[OSMOSE:LayerR] Upsert batch {batch_idx}/{n_batches} GIVE UP after "
                f"{max_retries} retries ({len(points)} points lost): "
                f"{type(last_err).__name__ if last_err else '?'}: {last_err}",
                exc_info=last_err if last_err else None,
            )

        # Log progression : tous les 10 batches ou a la fin
        if batch_idx % 10 == 0 or batch_start + batch_size >= total:
            logger.info(
                f"[OSMOSE:LayerR] Upsert progress: {upserted}/{total} points "
                f"({100 * upserted // max(1, total)}%, failed_batches={failed_batches})"
            )

    if failed_batches:
        logger.error(
            f"[OSMOSE:LayerR] Upsert PARTIAL: {upserted}/{total} points persisted, "
            f"{failed_batches}/{n_batches} batches failed (tenant={tenant_id})"
        )
    else:
        logger.info(
            f"[OSMOSE:LayerR] Upserted {upserted} points in {COLLECTION_NAME} "
            f"(tenant={tenant_id}, {n_batches} batches)"
        )
    return upserted


def delete_doc_from_layer_r(doc_id: str, tenant_id: str) -> None:
    """
    Supprime tous les points d'un document dans Layer R.

    Utilisé avant un re-import pour éviter les doublons.

    Args:
        doc_id: ID du document à purger
        tenant_id: ID du tenant
    """
    client = get_qdrant_client()
    if not client.collection_exists(COLLECTION_NAME):
        return

    client.delete(
        collection_name=COLLECTION_NAME,
        points_selector=Filter(
            must=[
                FieldCondition(key="doc_id", match=MatchValue(value=doc_id)),
                FieldCondition(key="tenant_id", match=MatchValue(value=tenant_id)),
            ]
        ),
    )
    logger.info(
        f"[OSMOSE:LayerR] Deleted points for doc_id={doc_id}, tenant={tenant_id}"
    )


def search_layer_r(
    query_vector: List[float],
    tenant_id: str,
    doc_id: Optional[str] = None,
    limit: int = 10,
    score_threshold: float = 0.3,
) -> List[Dict]:
    """
    Recherche TEXT_ONLY dans Layer R.

    Args:
        query_vector: Vecteur de la requête (1024 dimensions)
        tenant_id: ID du tenant
        doc_id: Filtrer par document (optionnel)
        limit: Nombre max de résultats
        score_threshold: Score minimum (cosine similarity)

    Returns:
        Liste de dicts avec score, text, metadata
    """
    client = get_qdrant_client()
    if not client.collection_exists(COLLECTION_NAME):
        logger.warning(f"[OSMOSE:LayerR] Collection {COLLECTION_NAME} does not exist")
        return []

    # Construire le filtre
    must_conditions = [
        FieldCondition(key="tenant_id", match=MatchValue(value=tenant_id)),
    ]
    if doc_id:
        must_conditions.append(
            FieldCondition(key="doc_id", match=MatchValue(value=doc_id))
        )

    results = client.search(
        collection_name=COLLECTION_NAME,
        query_vector=query_vector,
        query_filter=Filter(must=must_conditions),
        limit=limit,
        score_threshold=score_threshold,
    )

    return [
        {
            "score": hit.score,
            "text": hit.payload.get("text", ""),
            "doc_id": hit.payload.get("doc_id"),
            "chunk_id": hit.payload.get("chunk_id"),
            "sub_index": hit.payload.get("sub_index"),
            "section_id": hit.payload.get("section_id"),
            "kind": hit.payload.get("kind"),
            "page_no": hit.payload.get("page_no"),
            "schema_version": hit.payload.get("schema_version"),
            "anchored_informations": hit.payload.get("anchored_informations", []),
            "axis_release_id": hit.payload.get("axis_release_id"),
            "axis_version": hit.payload.get("axis_version"),
        }
        for hit in results
    ]
