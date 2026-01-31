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
    """Crée la collection knowbase_chunks_v2 si elle n'existe pas."""
    client = get_qdrant_client()
    if client.collection_exists(COLLECTION_NAME):
        logger.debug(f"[OSMOSE:LayerR] Collection {COLLECTION_NAME} already exists")
        return

    client.create_collection(
        collection_name=COLLECTION_NAME,
        vectors_config=VectorParams(size=VECTOR_SIZE, distance=DISTANCE),
    )
    logger.info(
        f"[OSMOSE:LayerR] Created collection {COLLECTION_NAME} "
        f"(size={VECTOR_SIZE}, distance={DISTANCE})"
    )


def upsert_layer_r(
    sub_chunks_with_embeddings: List[Tuple[SubChunk, np.ndarray]],
    tenant_id: str,
    batch_size: int = 0,
) -> int:
    """
    Upsert idempotent des sub-chunks + embeddings dans Qdrant.

    Chaque point a un point_id déterministe (UUID5) → re-upsert = même points.

    Args:
        sub_chunks_with_embeddings: Liste de (SubChunk, embedding_vector)
        tenant_id: ID du tenant
        batch_size: Taille des batches d'upsert (0 = auto depuis env)

    Returns:
        Nombre de points upsertés
    """
    if not sub_chunks_with_embeddings:
        return 0

    # batch_size configurable via env var
    if batch_size <= 0:
        batch_size = int(os.environ.get("QDRANT_UPSERT_BATCH_SIZE", "500"))

    ensure_layer_r_collection()
    client = get_qdrant_client()

    total = len(sub_chunks_with_embeddings)
    upserted = 0

    for batch_start in range(0, total, batch_size):
        batch = sub_chunks_with_embeddings[batch_start : batch_start + batch_size]

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
            }

            points.append(PointStruct(
                id=sc.point_id(),
                vector=embedding.tolist(),
                payload=payload,
            ))

        client.upsert(
            collection_name=COLLECTION_NAME,
            points=points,
        )
        upserted += len(points)

        if total > batch_size:
            logger.debug(
                f"[OSMOSE:LayerR] Upserted batch {batch_start // batch_size + 1} "
                f"({upserted}/{total})"
            )

    logger.info(
        f"[OSMOSE:LayerR] Upserted {upserted} points in {COLLECTION_NAME} "
        f"(tenant={tenant_id})"
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
        }
        for hit in results
    ]
