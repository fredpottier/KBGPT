from __future__ import annotations

import os
from typing import Any

from qdrant_client import QdrantClient
from qdrant_client.models import FieldCondition, Filter, MatchValue, HasIdCondition
from sentence_transformers import SentenceTransformer

from knowbase.config.settings import Settings
from knowbase.common.clients import rerank_chunks
from .synthesis import synthesize_response

TOP_K = 10
SCORE_THRESHOLD = 0.5
PUBLIC_URL = os.getenv("PUBLIC_URL", "knowbase.ngrok.app")


def build_response_payload(result, public_url: str) -> dict[str, Any]:
    payload = result.payload or {}

    # Nouvelle structure: document et chunk sous-objets
    document = payload.get("document", {})
    chunk = payload.get("chunk", {})

    # Gestion des URLs avec fallback vers l'ancienne structure
    source_file_url = document.get("source_file_url") or payload.get("source_file_url", "")
    slide_image_url = document.get("slide_image_url") or payload.get("slide_image_url", "")
    slide_index = chunk.get("slide_index") or payload.get("slide_index", "")

    # Construction de l'URL thumbnail complète
    if slide_image_url and not slide_image_url.startswith("http"):
        slide_image_url = f"https://{public_url}/static/thumbnails/{os.path.basename(slide_image_url)}"
    elif slide_image_url and slide_image_url.startswith(f"https://{public_url}"):
        # URL déjà complète, pas besoin de modification
        pass

    return {
        "text": payload.get("text", ""),
        "source_file": source_file_url,
        "slide_index": slide_index,
        "score": result.score,
        "slide_image_url": slide_image_url,
    }


def search_documents(
    *,
    question: str,
    qdrant_client: QdrantClient,
    embedding_model: SentenceTransformer,
    settings: Settings,
    solution: str | None = None,
) -> dict[str, Any]:
    query = question.strip()
    query_vector = embedding_model.encode(query)
    if hasattr(query_vector, "tolist"):
        query_vector = query_vector.tolist()
    elif hasattr(query_vector, "numpy"):
        query_vector = query_vector.numpy().tolist()
    query_vector = [float(x) for x in query_vector]

    # Construction du filtre de base
    filter_conditions = [FieldCondition(key="type", match=MatchValue(value="rfp_qa"))]

    # Ajouter le filtre par solution si spécifié
    must_conditions = []
    if solution:
        must_conditions.append(
            FieldCondition(key="solution.main", match=MatchValue(value=solution))
        )

    query_filter = Filter(
        must_not=filter_conditions,
        must=must_conditions if must_conditions else None
    )
    results = qdrant_client.search(
        collection_name=settings.qdrant_collection,
        query_vector=query_vector,
        limit=TOP_K,
        with_payload=True,
        query_filter=query_filter,
    )
    filtered = [r for r in results if r.score >= SCORE_THRESHOLD]
    if not filtered:
        return {
            "status": "no_results",
            "results": [],
            "message": "Aucune information pertinente n'a été trouvée dans la base de connaissance.",
        }

    public_url = PUBLIC_URL
    response_chunks = [build_response_payload(r, public_url) for r in filtered]

    # Apply reranking to improve relevance ordering
    reranked_chunks = rerank_chunks(query, response_chunks, top_k=TOP_K)

    # Generate synthesized response using LLM
    synthesis_result = synthesize_response(query, reranked_chunks)

    return {
        "status": "success",
        "results": reranked_chunks,
        "synthesis": synthesis_result
    }


def get_available_solutions(
    *,
    qdrant_client: QdrantClient,
    settings: Settings,
) -> list[str]:
    """Récupère la liste des solutions disponibles dans la base Qdrant."""
    # Récupération de tous les points avec la propriété main_solution
    solutions = set()

    # Utilisation de scroll pour récupérer tous les points avec solution.main
    scroll_result = qdrant_client.scroll(
        collection_name=settings.qdrant_collection,
        limit=1000,  # Limite élevée pour récupérer beaucoup de points
        with_payload=["solution"],
    )

    points, next_page_offset = scroll_result

    # Traitement de la première page
    for point in points:
        payload = point.payload or {}
        solution_data = payload.get("solution", {})
        main_solution = solution_data.get("main")
        if isinstance(main_solution, str) and main_solution.strip():
            solutions.add(main_solution.strip())

    # Continuer la pagination si nécessaire
    while next_page_offset is not None:
        scroll_result = qdrant_client.scroll(
            collection_name=settings.qdrant_collection,
            limit=1000,
            with_payload=["solution"],
            offset=next_page_offset
        )
        points, next_page_offset = scroll_result

        for point in points:
            payload = point.payload or {}
            solution_data = payload.get("solution", {})
            main_solution = solution_data.get("main")
            if isinstance(main_solution, str) and main_solution.strip():
                solutions.add(main_solution.strip())

    # Retourner la liste triée
    return sorted(list(solutions))


__all__ = ["search_documents", "get_available_solutions", "TOP_K", "SCORE_THRESHOLD"]
