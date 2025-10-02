"""
Hybrid Reranker - Phase 1 Critère 1.4

Algorithmes de reranking pour fusion scores Qdrant + Graphiti.

Stratégies disponibles:
1. Weighted Average (défaut): Moyenne pondérée simple
2. RRF (Reciprocal Rank Fusion): Combine rangs au lieu de scores
3. Contexte-aware: Boost si entities pertinentes détectées

Usage:
    from knowbase.search.hybrid_reranker import rerank_hybrid

    reranked = rerank_hybrid(
        qdrant_results=qdrant_hits,
        graphiti_results=graphiti_data,
        strategy="weighted_average",
        weights={"qdrant": 0.7, "graphiti": 0.3}
    )
"""

import logging
from typing import List, Dict, Any, Optional
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class RankedItem:
    """Item avec score hybride calculé"""
    chunk_id: str
    qdrant_score: float
    qdrant_rank: int
    graphiti_score: float
    graphiti_rank: int
    final_score: float
    data: Dict[str, Any]


def weighted_average_reranking(
    qdrant_results: List[Any],
    graphiti_results: Dict[str, Any],
    weights: Dict[str, float]
) -> List[RankedItem]:
    """
    Reranking par moyenne pondérée (stratégie par défaut)

    Score final = w_qdrant * score_qdrant + w_graphiti * score_graphiti

    Args:
        qdrant_results: Résultats Qdrant avec scores
        graphiti_results: Résultats Graphiti (dict avec nodes/edges)
        weights: Pondération {"qdrant": 0.7, "graphiti": 0.3}

    Returns:
        Items reranked triés par score final
    """
    logger.info(f"📊 [RERANKER] Weighted Average | Weights: {weights}")

    ranked_items = []

    for rank, qdrant_hit in enumerate(qdrant_results, start=1):
        chunk_id = str(qdrant_hit.id)
        qdrant_score = qdrant_hit.score

        # Calculer score Graphiti (basé sur présence entities/relations)
        episode_id = qdrant_hit.payload.get("episode_id")
        graphiti_score = 0.0

        if episode_id and graphiti_results:
            # Score simple: +0.5 si entities trouvées, +0.3 si relations trouvées
            has_entities = len(graphiti_results.get("nodes", [])) > 0
            has_relations = len(graphiti_results.get("edges", [])) > 0

            if has_entities:
                graphiti_score += 0.5
            if has_relations:
                graphiti_score += 0.3

            # Normaliser sur [0, 1]
            graphiti_score = min(graphiti_score, 1.0)

        # Score final pondéré
        final_score = (
            weights.get("qdrant", 0.7) * qdrant_score +
            weights.get("graphiti", 0.3) * graphiti_score
        )

        item = RankedItem(
            chunk_id=chunk_id,
            qdrant_score=qdrant_score,
            qdrant_rank=rank,
            graphiti_score=graphiti_score,
            graphiti_rank=0,  # Non utilisé pour weighted average
            final_score=final_score,
            data=qdrant_hit.payload
        )

        ranked_items.append(item)

    # Trier par score final
    ranked_items.sort(key=lambda x: x.final_score, reverse=True)

    logger.info(
        f"   ✅ Reranked {len(ranked_items)} items "
        f"(scores: {ranked_items[0].final_score:.3f} - {ranked_items[-1].final_score:.3f})"
    )

    return ranked_items


def reciprocal_rank_fusion(
    qdrant_results: List[Any],
    graphiti_results: Dict[str, Any],
    k: int = 60
) -> List[RankedItem]:
    """
    Reciprocal Rank Fusion (RRF)

    RRF score = 1 / (k + rank_qdrant) + 1 / (k + rank_graphiti)

    Plus robuste que weighted average car indépendant des échelles de scores.

    Args:
        qdrant_results: Résultats Qdrant
        graphiti_results: Résultats Graphiti
        k: Constante RRF (défaut: 60)

    Returns:
        Items reranked par RRF
    """
    logger.info(f"🔀 [RERANKER] Reciprocal Rank Fusion (k={k})")

    ranked_items = []

    # Map chunk_id → graphiti_rank
    graphiti_ranks = {}
    if graphiti_results and "episodes" in graphiti_results:
        for rank, episode in enumerate(graphiti_results["episodes"], start=1):
            # Simplification: utiliser episode comme proxy
            graphiti_ranks[episode.get("uuid", "")] = rank

    for qdrant_rank, qdrant_hit in enumerate(qdrant_results, start=1):
        chunk_id = str(qdrant_hit.id)
        episode_id = qdrant_hit.payload.get("episode_id", "")

        # Rank Graphiti (ou max si pas trouvé)
        graphiti_rank = graphiti_ranks.get(episode_id, len(qdrant_results) + 1)

        # RRF score
        rrf_score = (
            1.0 / (k + qdrant_rank) +
            1.0 / (k + graphiti_rank)
        )

        item = RankedItem(
            chunk_id=chunk_id,
            qdrant_score=qdrant_hit.score,
            qdrant_rank=qdrant_rank,
            graphiti_score=0.0,  # Pas utilisé dans RRF
            graphiti_rank=graphiti_rank,
            final_score=rrf_score,
            data=qdrant_hit.payload
        )

        ranked_items.append(item)

    # Trier par RRF score
    ranked_items.sort(key=lambda x: x.final_score, reverse=True)

    logger.info(
        f"   ✅ RRF reranked {len(ranked_items)} items "
        f"(RRF scores: {ranked_items[0].final_score:.4f} - {ranked_items[-1].final_score:.4f})"
    )

    return ranked_items


def context_aware_reranking(
    qdrant_results: List[Any],
    graphiti_results: Dict[str, Any],
    query: str,
    weights: Dict[str, float]
) -> List[RankedItem]:
    """
    Reranking context-aware avec boost entities pertinentes

    Améliore weighted average en boostant chunks avec entities
    mentionnées dans la query.

    Args:
        qdrant_results: Résultats Qdrant
        graphiti_results: Résultats Graphiti
        query: Requête utilisateur (pour matching entities)
        weights: Pondération base

    Returns:
        Items reranked avec boost contextuel
    """
    logger.info(f"🎯 [RERANKER] Context-Aware | Query: '{query[:50]}...'")

    # Extraire entities depuis query (simplification: mots clés en majuscule)
    query_keywords = set(query.upper().split())

    ranked_items = []

    for rank, qdrant_hit in enumerate(qdrant_results, start=1):
        chunk_id = str(qdrant_hit.id)
        qdrant_score = qdrant_hit.score

        # Score Graphiti de base
        episode_id = qdrant_hit.payload.get("episode_id")
        graphiti_score = 0.0
        context_boost = 0.0

        if episode_id and graphiti_results:
            # Vérifier entities dans Graphiti results
            entities = graphiti_results.get("nodes", [])

            if entities:
                graphiti_score = 0.5

                # Context boost: +0.2 si entity matche query
                for entity in entities:
                    entity_name = entity.get("name", "").upper()
                    if any(keyword in entity_name for keyword in query_keywords):
                        context_boost += 0.2
                        logger.debug(f"   🎯 Boost entity match: {entity['name']}")

            # Limiter boost total
            context_boost = min(context_boost, 0.5)

        # Score final avec boost
        final_score = (
            weights.get("qdrant", 0.7) * qdrant_score +
            weights.get("graphiti", 0.3) * (graphiti_score + context_boost)
        )

        item = RankedItem(
            chunk_id=chunk_id,
            qdrant_score=qdrant_score,
            qdrant_rank=rank,
            graphiti_score=graphiti_score + context_boost,
            graphiti_rank=0,
            final_score=final_score,
            data=qdrant_hit.payload
        )

        ranked_items.append(item)

    # Trier par score final
    ranked_items.sort(key=lambda x: x.final_score, reverse=True)

    logger.info(
        f"   ✅ Context-aware reranked {len(ranked_items)} items "
        f"(with context boosts applied)"
    )

    return ranked_items


def rerank_hybrid(
    qdrant_results: List[Any],
    graphiti_results: Dict[str, Any],
    strategy: str = "weighted_average",
    weights: Optional[Dict[str, float]] = None,
    query: Optional[str] = None,
    **kwargs
) -> List[RankedItem]:
    """
    Reranking hybride avec stratégie configurable

    Args:
        qdrant_results: Résultats Qdrant
        graphiti_results: Résultats Graphiti
        strategy: Stratégie reranking ("weighted_average", "rrf", "context_aware")
        weights: Pondération pour weighted_average/context_aware
        query: Query pour context_aware
        **kwargs: Arguments additionnels (ex: k pour RRF)

    Returns:
        Items reranked selon stratégie choisie

    Raises:
        ValueError: Si stratégie inconnue
    """
    if weights is None:
        weights = {"qdrant": 0.7, "graphiti": 0.3}

    logger.info(f"🔀 [RERANK] Stratégie: {strategy}")

    if strategy == "weighted_average":
        return weighted_average_reranking(
            qdrant_results=qdrant_results,
            graphiti_results=graphiti_results,
            weights=weights
        )

    elif strategy == "rrf":
        k = kwargs.get("k", 60)
        return reciprocal_rank_fusion(
            qdrant_results=qdrant_results,
            graphiti_results=graphiti_results,
            k=k
        )

    elif strategy == "context_aware":
        if not query:
            logger.warning("⚠️ Context-aware requires query, fallback to weighted_average")
            return weighted_average_reranking(qdrant_results, graphiti_results, weights)

        return context_aware_reranking(
            qdrant_results=qdrant_results,
            graphiti_results=graphiti_results,
            query=query,
            weights=weights
        )

    else:
        raise ValueError(
            f"Unknown reranking strategy: {strategy}. "
            f"Supported: weighted_average, rrf, context_aware"
        )


def explain_scores(item: RankedItem) -> str:
    """
    Expliquer composition score final (pour debug/transparency)

    Args:
        item: Item ranké

    Returns:
        Explication textuelle du score
    """
    explanation = (
        f"Final Score: {item.final_score:.3f}\n"
        f"  - Qdrant Score: {item.qdrant_score:.3f} (rank #{item.qdrant_rank})\n"
        f"  - Graphiti Score: {item.graphiti_score:.3f}"
    )

    if item.graphiti_rank > 0:
        explanation += f" (rank #{item.graphiti_rank})"

    return explanation
