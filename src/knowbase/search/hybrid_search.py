"""
Service Search Hybride Qdrant + Graphiti - Phase 1 Critère 1.4

Combine recherche vectorielle (Qdrant) et recherche graph (Graphiti)
pour obtenir résultats enrichis avec entities/relations.

Architecture:
1. Search dual: Qdrant chunks + Graphiti entities/relations
2. Reranking: Fusion scores avec pondération configurable
3. Enrichissement: Résultats combinés avec metadata complètes

Usage:
    from knowbase.search.hybrid_search import hybrid_search

    results = await hybrid_search(
        query="SAP S/4HANA consolidation process",
        tenant_id="acme_corp",
        limit=10
    )
"""

import logging
from typing import List, Dict, Any, Optional
from dataclasses import dataclass
from datetime import datetime

from knowbase.common.clients.qdrant_client import get_qdrant_client
from knowbase.graphiti.graphiti_factory import get_graphiti_service

logger = logging.getLogger(__name__)


@dataclass
class HybridSearchResult:
    """Résultat search hybride Qdrant + Graphiti"""
    # Données chunk Qdrant
    chunk_id: str
    chunk_text: str
    chunk_score: float
    chunk_metadata: Dict[str, Any]

    # Données Graphiti (si disponibles)
    graphiti_score: float
    entities: List[Dict[str, Any]]
    relations: List[Dict[str, Any]]
    episode_id: Optional[str] = None

    # Score final hybride
    final_score: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        """Convertir en dict pour API response"""
        return {
            "chunk_id": self.chunk_id,
            "text": self.chunk_text,
            "score": self.final_score,
            "metadata": self.chunk_metadata,
            "knowledge_graph": {
                "episode_id": self.episode_id,
                "entities": self.entities,
                "relations": self.relations,
                "graphiti_score": self.graphiti_score
            },
            "sources": {
                "qdrant_score": self.chunk_score,
                "graphiti_score": self.graphiti_score
            }
        }


async def hybrid_search(
    query: str,
    tenant_id: str,
    limit: int = 10,
    weights: Optional[Dict[str, float]] = None,
    collection_name: str = "knowbase"
) -> List[HybridSearchResult]:
    """
    Recherche hybride Qdrant + Graphiti

    Args:
        query: Requête utilisateur
        tenant_id: ID tenant (pour isolation multi-tenant)
        limit: Nombre résultats max (défaut: 10)
        weights: Pondération scores {"qdrant": 0.6, "graphiti": 0.4}
        collection_name: Collection Qdrant (défaut: knowbase)

    Returns:
        Liste résultats hybrides triés par score final

    Example:
        results = await hybrid_search(
            query="SAP consolidation",
            tenant_id="acme",
            limit=5
        )
        for result in results:
            print(f"Score: {result.final_score}")
            print(f"Text: {result.chunk_text[:100]}")
            print(f"Entities: {len(result.entities)}")
    """
    # Pondération par défaut : 70% Qdrant (vector search), 30% Graphiti (graph search)
    if weights is None:
        weights = {"qdrant": 0.7, "graphiti": 0.3}

    logger.info(
        f"🔍 [HYBRID SEARCH] Query: '{query[:50]}...' | "
        f"Tenant: {tenant_id} | Limit: {limit} | "
        f"Weights: Qdrant={weights['qdrant']}, Graphiti={weights['graphiti']}"
    )

    # 1. SEARCH QDRANT (chunks similaires)
    logger.info(f"📊 [QDRANT] Recherche chunks similaires...")
    qdrant_client = get_qdrant_client()

    # Over-fetch pour reranking (2x limit)
    qdrant_results = qdrant_client.search(
        collection_name=collection_name,
        query_text=query,
        limit=limit * 2,
        query_filter=None  # TODO: Filtrer par tenant_id si implémenté
    )

    logger.info(f"   ✅ Trouvé {len(qdrant_results)} chunks Qdrant")

    # Filtrer chunks avec knowledge graph (priorité)
    chunks_with_kg = [
        r for r in qdrant_results
        if r.payload and r.payload.get("has_knowledge_graph") is True
    ]

    chunks_without_kg = [
        r for r in qdrant_results
        if r.payload and r.payload.get("has_knowledge_graph") is not True
    ]

    logger.info(
        f"   📊 Répartition: {len(chunks_with_kg)} avec KG, "
        f"{len(chunks_without_kg)} sans KG"
    )

    # 2. SEARCH GRAPHITI (entities/relations pertinentes)
    logger.info(f"🌐 [GRAPHITI] Recherche knowledge graph...")
    graphiti_client = get_graphiti_service()  # Utilise proxy ou client selon config

    try:
        graphiti_results = graphiti_client.search(
            group_id=tenant_id,
            query=query,
            num_results=limit
        )
        logger.info(f"   ✅ Graphiti search réussi")
        logger.debug(f"   Résultats Graphiti: {graphiti_results}")
    except Exception as e:
        logger.warning(f"   ⚠️ Graphiti search échoué: {e}")
        graphiti_results = {"nodes": [], "edges": [], "episodes": []}

    # 3. CONSTRUIRE RÉSULTATS HYBRIDES
    logger.info(f"🔀 [RERANKING] Fusion Qdrant + Graphiti...")
    hybrid_results = []

    # 3.1. Chunks AVEC knowledge graph (priorité haute)
    for qdrant_hit in chunks_with_kg:
        episode_id = qdrant_hit.payload.get("episode_id", "")
        chunk_text = qdrant_hit.payload.get("text", "")
        chunk_score = qdrant_hit.score

        # Tenter de trouver entities/relations liées depuis Graphiti
        # NOTE: Limitation API Graphiti - on ne peut pas requêter par episode_id
        # On utilise les résultats globaux de la recherche Graphiti
        graphiti_score = 0.0
        entities = []
        relations = []

        # Extraction entities depuis résultats Graphiti (si disponibles)
        if graphiti_results and "nodes" in graphiti_results:
            # Simplification: prendre les premières entities
            entities = graphiti_results.get("nodes", [])[:5]
            graphiti_score = 0.8 if entities else 0.0

        if graphiti_results and "edges" in graphiti_results:
            relations = graphiti_results.get("edges", [])[:5]

        # Calcul score final hybride
        final_score = (
            weights["qdrant"] * chunk_score +
            weights["graphiti"] * graphiti_score
        )

        result = HybridSearchResult(
            chunk_id=str(qdrant_hit.id),
            chunk_text=chunk_text,
            chunk_score=chunk_score,
            chunk_metadata=qdrant_hit.payload,
            graphiti_score=graphiti_score,
            entities=entities,
            relations=relations,
            episode_id=episode_id,
            final_score=final_score
        )

        hybrid_results.append(result)

    # 3.2. Chunks SANS knowledge graph (priorité basse)
    for qdrant_hit in chunks_without_kg:
        chunk_text = qdrant_hit.payload.get("text", "")
        chunk_score = qdrant_hit.score

        # Pas de Graphiti pour ces chunks
        final_score = weights["qdrant"] * chunk_score

        result = HybridSearchResult(
            chunk_id=str(qdrant_hit.id),
            chunk_text=chunk_text,
            chunk_score=chunk_score,
            chunk_metadata=qdrant_hit.payload,
            graphiti_score=0.0,
            entities=[],
            relations=[],
            episode_id=None,
            final_score=final_score
        )

        hybrid_results.append(result)

    # 4. TRIER PAR SCORE FINAL et LIMITER
    hybrid_results.sort(key=lambda x: x.final_score, reverse=True)
    top_results = hybrid_results[:limit]

    logger.info(
        f"✅ [HYBRID SEARCH] Retourné {len(top_results)} résultats "
        f"(scores: {top_results[0].final_score:.3f} - {top_results[-1].final_score:.3f})"
    )

    # Stats debug
    with_kg_count = sum(1 for r in top_results if r.episode_id)
    logger.debug(f"   📊 Top {limit}: {with_kg_count} avec KG, {limit - with_kg_count} sans KG")

    return top_results


async def search_with_entity_filter(
    query: str,
    tenant_id: str,
    entity_types: List[str],
    limit: int = 10,
    collection_name: str = "knowbase"
) -> List[HybridSearchResult]:
    """
    Recherche hybride avec filtre entity types

    Permet de filtrer résultats par types d'entities (PRODUCT, CONCEPT, etc.)

    Args:
        query: Requête utilisateur
        tenant_id: ID tenant
        entity_types: Liste types entities à filtrer (ex: ["PRODUCT", "TECHNOLOGY"])
        limit: Nombre résultats max
        collection_name: Collection Qdrant

    Returns:
        Résultats filtrés par entity types
    """
    logger.info(f"🔍 [ENTITY FILTER] Search avec filtre entities: {entity_types}")

    # 1. Search hybride standard
    all_results = await hybrid_search(
        query=query,
        tenant_id=tenant_id,
        limit=limit * 3,  # Over-fetch pour filtrage
        collection_name=collection_name
    )

    # 2. Filtrer résultats par entity types
    filtered_results = []
    for result in all_results:
        if not result.entities:
            continue

        # Vérifier si au moins une entity matche les types demandés
        entity_types_in_result = [
            e.get("entity_type", "UNKNOWN")
            for e in result.entities
        ]

        if any(et in entity_types for et in entity_types_in_result):
            filtered_results.append(result)

        if len(filtered_results) >= limit:
            break

    logger.info(
        f"   ✅ Filtré {len(all_results)} → {len(filtered_results)} résultats "
        f"(entity types: {entity_types})"
    )

    return filtered_results[:limit]


async def search_related_chunks(
    chunk_id: str,
    tenant_id: str,
    limit: int = 5,
    collection_name: str = "knowbase"
) -> List[HybridSearchResult]:
    """
    Trouver chunks reliés via knowledge graph

    Utilise episode_id pour trouver chunks du même document/contexte

    Args:
        chunk_id: ID chunk de référence
        tenant_id: ID tenant
        limit: Nombre chunks reliés max
        collection_name: Collection Qdrant

    Returns:
        Chunks reliés (même episode_id)
    """
    logger.info(f"🔗 [RELATED CHUNKS] Recherche chunks reliés à: {chunk_id}")

    qdrant_client = get_qdrant_client()

    # 1. Récupérer chunk de référence
    chunks = qdrant_client.retrieve(
        collection_name=collection_name,
        ids=[chunk_id]
    )

    if not chunks or not chunks[0].payload:
        logger.warning(f"   ⚠️ Chunk {chunk_id} non trouvé")
        return []

    ref_chunk = chunks[0]
    episode_id = ref_chunk.payload.get("episode_id")

    if not episode_id:
        logger.warning(f"   ⚠️ Chunk {chunk_id} sans episode_id")
        return []

    logger.info(f"   📍 Episode ID: {episode_id}")

    # 2. Récupérer tous chunks avec même episode_id
    # NOTE: Qdrant ne supporte pas de filtre direct sur metadata
    # On scroll et filtre manuellement
    all_chunks, _ = qdrant_client.scroll(
        collection_name=collection_name,
        limit=1000,
        with_payload=True
    )

    related_chunks = [
        c for c in all_chunks
        if c.payload and
        c.payload.get("episode_id") == episode_id and
        str(c.id) != chunk_id  # Exclure chunk de référence
    ]

    logger.info(f"   ✅ Trouvé {len(related_chunks)} chunks reliés")

    # 3. Convertir en HybridSearchResult
    results = []
    for chunk in related_chunks[:limit]:
        result = HybridSearchResult(
            chunk_id=str(chunk.id),
            chunk_text=chunk.payload.get("text", ""),
            chunk_score=1.0,  # Pas de score similarity
            chunk_metadata=chunk.payload,
            graphiti_score=0.0,
            entities=[],
            relations=[],
            episode_id=episode_id,
            final_score=1.0
        )
        results.append(result)

    return results
