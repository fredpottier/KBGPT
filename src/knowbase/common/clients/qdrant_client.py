from __future__ import annotations

from functools import lru_cache
from typing import List, Dict, Any, Optional

from qdrant_client import QdrantClient
from qdrant_client.models import (
    Distance,
    VectorParams,
    PointStruct,
    Filter,
    FieldCondition,
    MatchValue
)

from knowbase.config.settings import get_settings
import logging

logger = logging.getLogger(__name__)


@lru_cache(maxsize=1)
def get_qdrant_client() -> QdrantClient:
    """
    Récupère instance singleton Qdrant client.

    Returns:
        QdrantClient instance
    """
    settings = get_settings()
    if settings.qdrant_api_key:
        return QdrantClient(url=settings.qdrant_url, api_key=settings.qdrant_api_key)
    return QdrantClient(url=settings.qdrant_url)


def ensure_qdrant_collection(
    collection_name: str,
    vector_size: int,
    distance: Distance = Distance.COSINE,
) -> None:
    client = get_qdrant_client()
    if client.collection_exists(collection_name):
        return
    client.create_collection(
        collection_name=collection_name,
        vectors_config=VectorParams(size=vector_size, distance=distance),
    )


def ensure_qa_collection(vector_size: int) -> None:
    """Initialise la collection dédiée aux Q/A RFP."""
    settings = get_settings()
    ensure_qdrant_collection(
        collection_name=settings.qdrant_qa_collection,
        vector_size=vector_size,
        distance=Distance.COSINE,
    )


# ============================================================================
# Multi-tenant Support Functions
# ============================================================================

def upsert_points_with_tenant(
    collection_name: str,
    points: List[PointStruct],
    tenant_id: str = "default"
) -> None:
    """
    Insère points Qdrant avec tenant_id dans payload.

    Args:
        collection_name: Nom collection Qdrant
        points: Liste points à insérer
        tenant_id: ID tenant pour isolation (default: "default")
    """
    client = get_qdrant_client()

    # Ajouter tenant_id à tous les payloads
    for point in points:
        if point.payload is None:
            point.payload = {}
        point.payload["tenant_id"] = tenant_id

    try:
        client.upsert(
            collection_name=collection_name,
            points=points
        )
        logger.debug(
            f"[QDRANT] Upserted {len(points)} points to {collection_name} "
            f"(tenant={tenant_id})"
        )
    except Exception as e:
        logger.error(f"[QDRANT] Error upserting points: {e}")


def search_with_tenant_filter(
    collection_name: str,
    query_vector: List[float],
    tenant_id: str = "default",
    limit: int = 10,
    score_threshold: Optional[float] = None,
    additional_filters: Optional[Filter] = None
) -> List[Dict[str, Any]]:
    """
    Recherche vectorielle avec filtre tenant_id.

    Args:
        collection_name: Nom collection Qdrant
        query_vector: Vecteur requête
        tenant_id: ID tenant pour filtrage (default: "default")
        limit: Nombre résultats max
        score_threshold: Score minimum (optionnel)
        additional_filters: Filtres additionnels (optionnel)

    Returns:
        Liste résultats avec scores
    """
    client = get_qdrant_client()

    # Créer filtre tenant_id
    tenant_filter = Filter(
        must=[
            FieldCondition(
                key="tenant_id",
                match=MatchValue(value=tenant_id)
            )
        ]
    )

    # Combiner avec filtres additionnels si fournis
    if additional_filters:
        if additional_filters.must:
            tenant_filter.must.extend(additional_filters.must)
        if additional_filters.should:
            tenant_filter.should = additional_filters.should
        if additional_filters.must_not:
            tenant_filter.must_not = additional_filters.must_not

    try:
        search_result = client.search(
            collection_name=collection_name,
            query_vector=query_vector,
            query_filter=tenant_filter,
            limit=limit,
            score_threshold=score_threshold
        )

        # Convertir en dict simple
        results = []
        for hit in search_result:
            results.append({
                "id": hit.id,
                "score": hit.score,
                "payload": hit.payload
            })

        logger.debug(
            f"[QDRANT] Search returned {len(results)} results "
            f"(tenant={tenant_id}, collection={collection_name})"
        )

        return results

    except Exception as e:
        logger.error(f"[QDRANT] Error searching: {e}")
        return []


def delete_tenant_data(
    collection_name: str,
    tenant_id: str
) -> bool:
    """
    Supprime tous les points d'un tenant (ADMIN uniquement).

    Args:
        collection_name: Nom collection Qdrant
        tenant_id: ID tenant à supprimer

    Returns:
        True si suppression OK
    """
    client = get_qdrant_client()

    # Créer filtre tenant_id
    tenant_filter = Filter(
        must=[
            FieldCondition(
                key="tenant_id",
                match=MatchValue(value=tenant_id)
            )
        ]
    )

    try:
        client.delete(
            collection_name=collection_name,
            points_selector=tenant_filter
        )
        logger.warning(
            f"[QDRANT:ADMIN] Deleted all data for tenant '{tenant_id}' "
            f"in collection '{collection_name}'"
        )
        return True

    except Exception as e:
        logger.error(f"[QDRANT] Error deleting tenant data: {e}")
        return False
