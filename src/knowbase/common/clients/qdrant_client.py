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
    # Timeout 300s pour gros batch uploads
    if settings.qdrant_api_key:
        return QdrantClient(url=settings.qdrant_url, api_key=settings.qdrant_api_key, timeout=300)
    return QdrantClient(url=settings.qdrant_url, timeout=300)


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


# ==================================================
# Phase 1.6 - Cross-Référence Neo4j ↔ Qdrant
# ==================================================


def upsert_chunks(
    chunks: List[Dict[str, Any]],
    collection_name: str = "knowbase",
    tenant_id: str = "default"
) -> List[str]:
    """
    Insérer chunks dans Qdrant avec proto_concept_ids (cross-référence Neo4j).

    Args:
        chunks: Liste chunks avec embeddings et metadata
            [
                {
                    "id": "chunk-uuid",  # Optionnel, généré si absent
                    "text": "SAP S/4HANA est...",
                    "embedding": [0.123, ...],  # 1024D
                    "document_id": "doc-123",
                    "document_name": "SAP Overview.pdf",
                    "segment_id": "segment-1",
                    "chunk_index": 0,
                    "proto_concept_ids": ["proto-123"],
                    "canonical_concept_ids": [],  # Vide initialement
                    "tenant_id": "default",
                    "char_start": 0,
                    "char_end": 512
                }
            ]
        collection_name: Nom collection (default: "knowbase")
        tenant_id: ID tenant (isolation multi-tenant)

    Returns:
        Liste chunk_ids créés (UUIDs)
    """
    client = get_qdrant_client()

    # Vérifier/créer collection
    if not client.collection_exists(collection_name):
        logger.warning(f"[QDRANT:Chunks] Collection {collection_name} doesn't exist, creating...")
        ensure_qdrant_collection(collection_name, vector_size=1024)

    chunk_ids = []
    all_points = []

    for chunk in chunks:
        # Utiliser ID fourni ou générer nouveau UUID
        chunk_id = chunk.get("id") or str(__import__('uuid').uuid4())
        chunk_ids.append(chunk_id)

        # Construire payload (tout sauf embedding et id)
        # Phase 2 - Hybrid Anchor Model: anchored_concepts contient les concepts
        # liés à ce chunk avec payload minimal (concept_id, label, role, span)
        payload = {
            "text": chunk.get("text", ""),
            "document_id": chunk.get("document_id", ""),
            "document_name": chunk.get("document_name", ""),
            "segment_id": chunk.get("segment_id", ""),
            "chunk_index": chunk.get("chunk_index", 0),
            "chunk_type": chunk.get("chunk_type", "generic"),  # document_centric vs legacy
            "proto_concept_ids": chunk.get("proto_concept_ids", []),
            "canonical_concept_ids": chunk.get("canonical_concept_ids", []),
            "anchored_concepts": chunk.get("anchored_concepts", []),  # Hybrid Anchor Model (ADR)
            "tenant_id": tenant_id,
            "char_start": chunk.get("char_start", 0),
            "char_end": chunk.get("char_end", 0),
            "token_count": chunk.get("token_count", 0),
            "created_at": chunk.get("created_at", ""),
            # QW-2: Confidence scores (ADR_REDUCTO_PARSING_PRIMITIVES)
            "parse_confidence": chunk.get("parse_confidence", 0.5),
            "confidence_signals": chunk.get("confidence_signals", {}),
            # MT-1: Layout-aware chunking (ADR_REDUCTO_PARSING_PRIMITIVES)
            "is_atomic": chunk.get("is_atomic", False),
            "region_type": chunk.get("region_type", "unknown"),
        }

        # Créer point Qdrant
        point = PointStruct(
            id=chunk_id,
            vector=chunk["embedding"],
            payload=payload
        )
        all_points.append(point)

    try:
        # Batch upsert par lots de 1000 pour éviter timeouts
        BATCH_SIZE = 1000
        total_batches = (len(all_points) + BATCH_SIZE - 1) // BATCH_SIZE

        for batch_idx in range(total_batches):
            start_idx = batch_idx * BATCH_SIZE
            end_idx = min((batch_idx + 1) * BATCH_SIZE, len(all_points))
            batch_points = all_points[start_idx:end_idx]

            logger.info(
                f"[QDRANT:Chunks] Upserting batch {batch_idx + 1}/{total_batches} "
                f"({len(batch_points)} chunks)..."
            )

            client.upsert(
                collection_name=collection_name,
                points=batch_points,
                wait=True  # Attendre confirmation pour chaque batch
            )

        logger.info(
            f"[QDRANT:Chunks] ✅ Successfully upserted {len(all_points)} chunks in {total_batches} batches "
            f"(tenant={tenant_id}, collection={collection_name})"
        )

        return chunk_ids

    except Exception as e:
        logger.error(f"[QDRANT:Chunks] Error upserting chunks: {type(e).__name__}: {e}")
        logger.error(f"[QDRANT:Chunks] First chunk sample: {chunks[0] if chunks else 'N/A'}")
        import traceback
        logger.error(f"[QDRANT:Chunks] Traceback: {traceback.format_exc()}")
        return []


def update_chunks_with_canonical_ids(
    chunk_ids: List[str],
    canonical_concept_id: str,
    collection_name: str = "knowbase"
) -> bool:
    """
    Mettre à jour chunks avec canonical_concept_id après promotion Gatekeeper.

    Appelé par Gatekeeper après promotion ProtoConcept → CanonicalConcept
    pour enrichir chunks Qdrant avec reference au concept publié.

    Args:
        chunk_ids: IDs des chunks à mettre à jour
        canonical_concept_id: ID du CanonicalConcept promu
        collection_name: Nom collection (default: "knowbase")

    Returns:
        True si mise à jour OK
    """
    client = get_qdrant_client()

    if not chunk_ids:
        logger.debug("[QDRANT:Chunks] No chunk_ids to update")
        return True

    try:
        # Récupérer chunks existants
        points = client.retrieve(
            collection_name=collection_name,
            ids=chunk_ids
        )

        updated_points = []
        for point in points:
            # Ajouter canonical_concept_id (sans doublon)
            canonical_ids = point.payload.get("canonical_concept_ids", [])
            if canonical_concept_id not in canonical_ids:
                canonical_ids.append(canonical_concept_id)

            # Mettre à jour payload
            updated_payload = point.payload
            updated_payload["canonical_concept_ids"] = canonical_ids

            updated_point = PointStruct(
                id=point.id,
                vector=point.vector,
                payload=updated_payload
            )
            updated_points.append(updated_point)

        # Upsert chunks mis à jour
        client.upsert(
            collection_name=collection_name,
            points=updated_points
        )

        logger.info(
            f"[QDRANT:Chunks] Updated {len(updated_points)} chunks with "
            f"canonical_id={canonical_concept_id[:8]}"
        )

        return True

    except Exception as e:
        logger.error(f"[QDRANT:Chunks] Error updating chunks: {e}")
        return False


def get_chunks_by_concept(
    canonical_concept_id: str,
    collection_name: str = "knowbase",
    tenant_id: Optional[str] = None,
    limit: int = 100
) -> List[Dict[str, Any]]:
    """
    Récupérer chunks associés à un concept (cross-référence Neo4j → Qdrant).

    Use case: Enrichir concept avec contexte textuel complet.

    Args:
        canonical_concept_id: ID CanonicalConcept Neo4j
        collection_name: Nom collection (default: "knowbase")
        tenant_id: Filtrer par tenant (optionnel)
        limit: Max chunks à retourner

    Returns:
        Liste chunks avec payload complet
    """
    client = get_qdrant_client()

    # Construire filtres
    must_conditions = [
        FieldCondition(
            key="canonical_concept_ids",
            match=MatchValue(value=canonical_concept_id)
        )
    ]

    if tenant_id:
        must_conditions.append(
            FieldCondition(
                key="tenant_id",
                match=MatchValue(value=tenant_id)
            )
        )

    query_filter = Filter(must=must_conditions)

    try:
        # Scroll pour récupérer tous chunks
        scroll_result = client.scroll(
            collection_name=collection_name,
            scroll_filter=query_filter,
            limit=limit,
            with_payload=True,
            with_vectors=False  # Pas besoin des vecteurs
        )

        chunks = []
        for point in scroll_result[0]:  # scroll_result = (points, next_page_offset)
            chunks.append({
                "id": point.id,
                "payload": point.payload
            })

        logger.debug(
            f"[QDRANT:Chunks] Found {len(chunks)} chunks for concept "
            f"{canonical_concept_id[:8]}"
        )

        return chunks

    except Exception as e:
        logger.error(f"[QDRANT:Chunks] Error retrieving chunks: {e}")
        return []
