"""
Hybrid Anchor Model - Hybrid Search Service (Phase 7)

Recherche hybride fusionnant chunks + concepts via anchors.

Pipeline:
1. Recherche Qdrant (chunks)
2. Recherche Concepts (embeddings Neo4j/Qdrant)
3. Fusion via anchors
4. Reranking unifié
5. Réponse avec citations (anchors)

ADR: doc/ongoing/ADR_HYBRID_ANCHOR_MODEL.md

Author: OSMOSE Phase 2
Date: 2024-12
"""

import logging
import asyncio
from typing import List, Dict, Any, Optional, Tuple
from dataclasses import dataclass, field
from enum import Enum
import time

from qdrant_client import QdrantClient
from qdrant_client.models import Filter, FieldCondition, MatchValue

from knowbase.config.feature_flags import get_hybrid_anchor_config

logger = logging.getLogger(__name__)


class SearchMode(str, Enum):
    """Modes de recherche hybride."""

    CHUNKS_ONLY = "chunks_only"        # Recherche chunks classique
    CONCEPTS_ONLY = "concepts_only"    # Recherche concepts uniquement
    HYBRID = "hybrid"                  # Fusion chunks + concepts (défaut)
    ANCHOR_FIRST = "anchor_first"      # Priorité aux chunks avec anchors


@dataclass
class AnchorCitation:
    """Citation via anchor pour explicabilité."""

    concept_id: str
    concept_label: str
    anchor_role: str
    quote: str
    span: Tuple[int, int]
    chunk_id: str
    confidence: float


@dataclass
class HybridSearchResult:
    """Résultat de recherche hybride."""

    chunk_id: str
    text: str
    score: float  # Score fusionné
    document_id: str
    document_name: str

    # Scores composants
    chunk_score: float = 0.0
    concept_score: float = 0.0

    # Citations via anchors
    citations: List[AnchorCitation] = field(default_factory=list)

    # Métadonnées
    slide_index: Optional[int] = None
    slide_image_url: Optional[str] = None
    source_file_url: Optional[str] = None


@dataclass
class HybridSearchResponse:
    """Réponse complète de recherche hybride."""

    results: List[HybridSearchResult] = field(default_factory=list)
    total_chunks_searched: int = 0
    total_concepts_matched: int = 0
    mode: SearchMode = SearchMode.HYBRID
    processing_time_ms: float = 0.0

    # Concepts pertinents pour la query
    query_concepts: List[Dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        """Convertit en dict pour sérialisation JSON."""
        return {
            "results": [
                {
                    "chunk_id": r.chunk_id,
                    "text": r.text,
                    "score": r.score,
                    "document_id": r.document_id,
                    "document_name": r.document_name,
                    "chunk_score": r.chunk_score,
                    "concept_score": r.concept_score,
                    "citations": [
                        {
                            "concept_id": c.concept_id,
                            "concept_label": c.concept_label,
                            "anchor_role": c.anchor_role,
                            "quote": c.quote,
                            "span": list(c.span),
                            "confidence": c.confidence,
                        }
                        for c in r.citations
                    ],
                    "slide_index": r.slide_index,
                    "slide_image_url": r.slide_image_url,
                    "source_file_url": r.source_file_url,
                }
                for r in self.results
            ],
            "total_chunks_searched": self.total_chunks_searched,
            "total_concepts_matched": self.total_concepts_matched,
            "mode": self.mode.value,
            "processing_time_ms": self.processing_time_ms,
            "query_concepts": self.query_concepts,
        }


class HybridAnchorSearchService:
    """
    Service de recherche hybride pour le Hybrid Anchor Model.

    Architecture:
    1. Recherche chunks (Qdrant) → top_k chunks par score vectoriel
    2. Recherche concepts (embeddings) → concepts pertinents
    3. Expansion via anchors → chunks additionnels via concepts
    4. Fusion & Reranking → score unifié
    5. Enrichissement citations → anchors comme preuves
    """

    def __init__(
        self,
        qdrant_client: QdrantClient,
        embedding_model: Any,
        tenant_id: str = "default"
    ):
        """
        Initialise le service.

        Args:
            qdrant_client: Client Qdrant
            embedding_model: Modèle d'embedding
            tenant_id: ID tenant
        """
        self.qdrant_client = qdrant_client
        self.embedding_model = embedding_model
        self.tenant_id = tenant_id

        # Configuration
        config = get_hybrid_anchor_config("search_config", tenant_id) or {}
        self.chunk_weight = config.get("chunk_weight", 0.6)
        self.concept_weight = config.get("concept_weight", 0.4)
        self.min_score = config.get("min_score", 0.5)
        self.max_anchor_expansion = config.get("max_anchor_expansion", 5)

        logger.info(
            f"[OSMOSE:HybridSearch] Initialized "
            f"(chunk_weight={self.chunk_weight}, concept_weight={self.concept_weight})"
        )

    async def search_async(
        self,
        query: str,
        collection_name: str,
        top_k: int = 10,
        mode: SearchMode = SearchMode.HYBRID,
        filter_params: Optional[Dict[str, Any]] = None
    ) -> HybridSearchResponse:
        """
        Exécute une recherche hybride.

        Args:
            query: Requête utilisateur
            collection_name: Collection Qdrant
            top_k: Nombre de résultats
            mode: Mode de recherche
            filter_params: Filtres Qdrant optionnels

        Returns:
            HybridSearchResponse
        """
        start_time = time.time()

        # 1. Encoder la query
        query_vector = self._encode_query(query)

        # 2. Recherche chunks (toujours sauf CONCEPTS_ONLY)
        chunk_results = []
        if mode != SearchMode.CONCEPTS_ONLY:
            chunk_results = await self._search_chunks(
                query_vector, collection_name, top_k * 2, filter_params
            )

        # 3. Recherche concepts (sauf CHUNKS_ONLY)
        concept_results = []
        if mode != SearchMode.CHUNKS_ONLY:
            concept_results = await self._search_concepts(
                query_vector, top_k
            )

        # 4. Expansion via anchors
        anchor_expanded_chunks = []
        if mode in [SearchMode.HYBRID, SearchMode.ANCHOR_FIRST] and concept_results:
            anchor_expanded_chunks = await self._expand_via_anchors(
                concept_results, collection_name, filter_params
            )

        # 5. Fusion & Reranking
        fused_results = self._fuse_and_rerank(
            chunk_results,
            anchor_expanded_chunks,
            concept_results,
            mode,
            top_k
        )

        # 6. Enrichir avec citations
        enriched_results = self._enrich_with_citations(fused_results)

        processing_time = (time.time() - start_time) * 1000

        response = HybridSearchResponse(
            results=enriched_results,
            total_chunks_searched=len(chunk_results) + len(anchor_expanded_chunks),
            total_concepts_matched=len(concept_results),
            mode=mode,
            processing_time_ms=processing_time,
            query_concepts=[
                {
                    "id": c.get("id"),
                    "label": c.get("label"),
                    "score": c.get("score", 0),
                }
                for c in concept_results[:5]
            ]
        )

        logger.info(
            f"[OSMOSE:HybridSearch] Query completed: "
            f"{len(enriched_results)} results, "
            f"{len(concept_results)} concepts matched, "
            f"{processing_time:.1f}ms"
        )

        return response

    def _encode_query(self, query: str) -> List[float]:
        """Encode la query en vecteur."""
        vector = self.embedding_model.encode(query)

        if hasattr(vector, "tolist"):
            return vector.tolist()
        elif hasattr(vector, "numpy"):
            return vector.numpy().tolist()

        return [float(x) for x in vector]

    async def _search_chunks(
        self,
        query_vector: List[float],
        collection_name: str,
        limit: int,
        filter_params: Optional[Dict[str, Any]] = None
    ) -> List[Dict[str, Any]]:
        """Recherche vectorielle dans les chunks."""

        try:
            # Construire filtre
            qdrant_filter = None
            if filter_params:
                must_conditions = []
                for key, value in filter_params.items():
                    must_conditions.append(
                        FieldCondition(key=key, match=MatchValue(value=value))
                    )
                qdrant_filter = Filter(must=must_conditions)

            results = self.qdrant_client.search(
                collection_name=collection_name,
                query_vector=query_vector,
                limit=limit,
                with_payload=True,
                query_filter=qdrant_filter,
            )

            return [
                {
                    "id": str(r.id),
                    "score": r.score,
                    "payload": r.payload or {},
                }
                for r in results
                if r.score >= self.min_score
            ]

        except Exception as e:
            logger.error(f"[OSMOSE:HybridSearch] Chunk search failed: {e}")
            return []

    async def _search_concepts(
        self,
        query_vector: List[float],
        limit: int
    ) -> List[Dict[str, Any]]:
        """
        Recherche concepts via embeddings.

        Stratégie: Utiliser la collection Qdrant 'knowwhere_concepts' si elle existe,
        sinon fallback sur recherche Neo4j.
        """
        try:
            # Essayer collection Qdrant concepts
            try:
                results = self.qdrant_client.search(
                    collection_name="knowwhere_concepts",
                    query_vector=query_vector,
                    limit=limit,
                    with_payload=True,
                )

                return [
                    {
                        "id": str(r.id),
                        "label": r.payload.get("label", "") if r.payload else "",
                        "type": r.payload.get("type", "abstract") if r.payload else "abstract",
                        "score": r.score,
                    }
                    for r in results
                    if r.score >= self.min_score
                ]

            except Exception:
                # Collection n'existe pas, utiliser Neo4j
                pass

            # Fallback: Chercher via Neo4j avec correspondance textuelle
            # (Les embeddings concepts seront ajoutés plus tard)
            from knowbase.common.clients.neo4j_client import get_neo4j_client
            from knowbase.config.settings import get_settings

            settings = get_settings()
            neo4j_client = get_neo4j_client(
                uri=settings.neo4j_uri,
                user=settings.neo4j_user,
                password=settings.neo4j_password,
                database="neo4j"
            )

            if not neo4j_client.is_connected():
                return []

            # Extraction mots-clés de la query pour matching
            # TODO: Améliorer avec vraie recherche sémantique
            query = """
            MATCH (c:CanonicalConcept {tenant_id: $tenant_id})
            WHERE c.status = 'HYBRID_ANCHOR' OR c.status = 'PUBLISHED'
            RETURN c.canonical_id AS id,
                   c.canonical_name AS label,
                   c.type_fine AS type,
                   1.0 AS score
            LIMIT $limit
            """

            with neo4j_client.driver.session(database="neo4j") as session:
                result = session.run(query, tenant_id=self.tenant_id, limit=limit)
                return [
                    {
                        "id": r["id"],
                        "label": r["label"],
                        "type": r["type"] or "abstract",
                        "score": r["score"],
                    }
                    for r in result
                ]

        except Exception as e:
            logger.warning(f"[OSMOSE:HybridSearch] Concept search failed: {e}")
            return []

    async def _expand_via_anchors(
        self,
        concept_results: List[Dict[str, Any]],
        collection_name: str,
        filter_params: Optional[Dict[str, Any]] = None
    ) -> List[Dict[str, Any]]:
        """
        Trouve chunks additionnels via les anchors des concepts.

        Les concepts ont des anchors qui pointent vers des DocumentChunks via
        les ProtoConcepts (INSTANCE_OF → ANCHORED_IN).
        """
        if not concept_results:
            return []

        concept_ids = [c.get("id") for c in concept_results[:self.max_anchor_expansion]]
        if not concept_ids:
            return []

        try:
            from knowbase.common.clients.neo4j_client import get_neo4j_client
            from knowbase.config.settings import get_settings

            settings = get_settings()
            neo4j_client = get_neo4j_client(
                uri=settings.neo4j_uri,
                user=settings.neo4j_user,
                password=settings.neo4j_password,
                database="neo4j"
            )

            if not neo4j_client.is_connected():
                return []

            # Query Neo4j pour récupérer chunks via anchors
            # ADR_COVERAGE_PROPERTY_NOT_NODE: Support DocItem (Option C) + DocumentChunk (legacy)
            query = """
            MATCH (cc:CanonicalConcept {tenant_id: $tenant_id})
            WHERE cc.canonical_id IN $concept_ids
            MATCH (cc)<-[:INSTANCE_OF]-(pc:ProtoConcept)-[:ANCHORED_IN]->(target)
            WHERE target:DocItem OR target:DocumentChunk
            WITH target, cc, pc, count(DISTINCT pc) AS anchor_count,
                 COALESCE(target.item_id, target.chunk_id) AS target_id,
                 COALESCE(target.doc_id, target.document_id) AS doc_id,
                 COALESCE(target.text, target.text_preview) AS text_content,
                 COALESCE(target.charspan_start_docwide, target.charspan_start, target.start_char) AS start_char,
                 COALESCE(target.charspan_end_docwide, target.charspan_end, target.end_char) AS end_char
            RETURN target_id AS chunk_id,
                   doc_id AS document_id,
                   text_content AS text_preview,
                   start_char,
                   end_char,
                   collect(DISTINCT cc.canonical_name)[0..3] AS concept_labels,
                   anchor_count,
                   CASE WHEN anchor_count > 2 THEN 0.9
                        WHEN anchor_count > 1 THEN 0.8
                        ELSE 0.7 END AS score
            ORDER BY anchor_count DESC
            LIMIT 20
            """

            expanded_chunks = []

            with neo4j_client.driver.session(database="neo4j") as session:
                results = session.run(
                    query,
                    tenant_id=self.tenant_id,
                    concept_ids=concept_ids
                )

                for r in results:
                    chunk_id = r["chunk_id"]

                    # Récupérer le chunk complet depuis Qdrant si disponible
                    try:
                        qdrant_results = self.qdrant_client.retrieve(
                            collection_name=collection_name,
                            ids=[chunk_id],
                            with_payload=True
                        )

                        if qdrant_results:
                            point = qdrant_results[0]
                            expanded_chunks.append({
                                "id": chunk_id,
                                "score": r["score"],
                                "payload": point.payload or {},
                                "concept_labels": r["concept_labels"],
                                "anchor_count": r["anchor_count"],
                            })
                        else:
                            # Chunk pas dans Qdrant, utiliser les infos Neo4j
                            expanded_chunks.append({
                                "id": chunk_id,
                                "score": r["score"],
                                "payload": {
                                    "text": r["text_preview"] or "",
                                    "document_id": r["document_id"],
                                },
                                "concept_labels": r["concept_labels"],
                                "anchor_count": r["anchor_count"],
                            })

                    except Exception:
                        # Continuer même si Qdrant échoue
                        expanded_chunks.append({
                            "id": chunk_id,
                            "score": r["score"],
                            "payload": {
                                "text": r["text_preview"] or "",
                                "document_id": r["document_id"],
                            },
                            "concept_labels": r["concept_labels"],
                            "anchor_count": r["anchor_count"],
                        })

            logger.info(
                f"[OSMOSE:HybridSearch] Anchor expansion: "
                f"{len(expanded_chunks)} chunks from {len(concept_ids)} concepts"
            )

            return expanded_chunks

        except Exception as e:
            logger.warning(f"[OSMOSE:HybridSearch] Anchor expansion failed: {e}")
            return []

    def _fuse_and_rerank(
        self,
        chunk_results: List[Dict[str, Any]],
        anchor_chunks: List[Dict[str, Any]],
        concept_results: List[Dict[str, Any]],
        mode: SearchMode,
        top_k: int
    ) -> List[Dict[str, Any]]:
        """
        Fusionne et re-ranke les résultats.

        Stratégie:
        - Score fusionné = chunk_weight * chunk_score + concept_weight * concept_score
        - Bonus pour chunks avec anchors de concepts pertinents
        """
        # Créer map id → résultat
        result_map: Dict[str, Dict[str, Any]] = {}

        # Ajouter chunk results
        for chunk in chunk_results:
            chunk_id = chunk.get("id")
            result_map[chunk_id] = {
                "id": chunk_id,
                "chunk_score": chunk.get("score", 0),
                "concept_score": 0.0,
                "payload": chunk.get("payload", {}),
                "source": "chunk",
            }

        # Ajouter anchor-expanded chunks
        for chunk in anchor_chunks:
            chunk_id = chunk.get("id")
            if chunk_id in result_map:
                # Boost concept score si déjà présent
                result_map[chunk_id]["concept_score"] += 0.3
            else:
                result_map[chunk_id] = {
                    "id": chunk_id,
                    "chunk_score": chunk.get("score", 0) * 0.8,  # Légèrement moins prioritaire
                    "concept_score": 0.3,
                    "payload": chunk.get("payload", {}),
                    "source": "anchor_expansion",
                }

        # Calculer score fusionné
        for chunk_id, data in result_map.items():
            # Bonus pour chunks avec anchored_concepts
            anchored_concepts = data.get("payload", {}).get("anchored_concepts", [])
            concept_boost = min(0.2, len(anchored_concepts) * 0.05)

            data["fused_score"] = (
                self.chunk_weight * data["chunk_score"] +
                self.concept_weight * data["concept_score"] +
                concept_boost
            )

        # Trier par score fusionné
        sorted_results = sorted(
            result_map.values(),
            key=lambda x: x.get("fused_score", 0),
            reverse=True
        )

        return sorted_results[:top_k]

    def _enrich_with_citations(
        self,
        fused_results: List[Dict[str, Any]]
    ) -> List[HybridSearchResult]:
        """
        Enrichit les résultats avec citations via anchors.

        Les anchors dans le payload sont transformés en AnchorCitation.
        """
        enriched = []

        for result in fused_results:
            payload = result.get("payload", {})

            # Extraire citations depuis anchored_concepts
            citations = []
            for ac in payload.get("anchored_concepts", []):
                span = ac.get("span", [0, 0])
                citations.append(AnchorCitation(
                    concept_id=ac.get("concept_id", ""),
                    concept_label=ac.get("label", ""),
                    anchor_role=ac.get("role", "context"),
                    quote=self._extract_quote(payload.get("text", ""), span),
                    span=tuple(span) if len(span) == 2 else (0, 0),
                    chunk_id=result.get("id", ""),
                    confidence=ac.get("confidence", 0.8),
                ))

            # Créer résultat enrichi
            hybrid_result = HybridSearchResult(
                chunk_id=result.get("id", ""),
                text=payload.get("text", ""),
                score=result.get("fused_score", 0),
                document_id=payload.get("document_id", ""),
                document_name=payload.get("document_name", ""),
                chunk_score=result.get("chunk_score", 0),
                concept_score=result.get("concept_score", 0),
                citations=citations,
                slide_index=payload.get("slide_index"),
                slide_image_url=payload.get("slide_image_url"),
                source_file_url=payload.get("source_file_url"),
            )

            enriched.append(hybrid_result)

        return enriched

    def _extract_quote(self, text: str, span: List[int]) -> str:
        """Extrait la quote du texte selon le span."""
        if len(span) != 2 or not text:
            return ""

        start, end = span
        if start < 0 or end > len(text) or start >= end:
            return ""

        return text[start:end]

    def search_sync(
        self,
        query: str,
        collection_name: str,
        top_k: int = 10,
        mode: SearchMode = SearchMode.HYBRID,
        filter_params: Optional[Dict[str, Any]] = None
    ) -> HybridSearchResponse:
        """
        Version synchrone pour compatibilité.

        Args:
            query: Requête utilisateur
            collection_name: Collection Qdrant
            top_k: Nombre de résultats
            mode: Mode de recherche
            filter_params: Filtres optionnels

        Returns:
            HybridSearchResponse
        """
        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(
                self.search_async(query, collection_name, top_k, mode, filter_params)
            )
        finally:
            loop.close()


# =============================================================================
# Unified Reranker
# =============================================================================

class UnifiedReranker:
    """
    Reranker unifié pour recherche hybride.

    Combine plusieurs signaux:
    - Score vectoriel chunk
    - Score concept matching
    - Anchor density (nombre d'anchors)
    - Rôles anchors (boost pour definition, requirement)
    """

    def __init__(self, tenant_id: str = "default"):
        """Initialise le reranker."""
        self.tenant_id = tenant_id

        # Poids des composants
        self.weights = {
            "vector_score": 0.4,
            "concept_score": 0.25,
            "anchor_density": 0.15,
            "role_boost": 0.1,
            "recency": 0.1,
        }

        # Boost par rôle d'anchor
        self.role_boosts = {
            "definition": 0.3,
            "requirement": 0.25,
            "prohibition": 0.25,
            "procedure": 0.15,
            "example": 0.1,
            "context": 0.0,
        }

    def rerank(
        self,
        results: List[HybridSearchResult],
        query: str = ""
    ) -> List[HybridSearchResult]:
        """
        Re-ranke les résultats selon signaux multiples.

        Args:
            results: Résultats à re-ranker
            query: Requête originale (pour future utilisation)

        Returns:
            Résultats re-rankés
        """
        if not results:
            return []

        scored_results = []

        for result in results:
            # Score vectoriel normalisé
            vector_score = result.chunk_score

            # Score concept
            concept_score = result.concept_score

            # Anchor density (normalisé sur max 5)
            anchor_density = min(1.0, len(result.citations) / 5.0)

            # Role boost (max parmi les citations)
            role_boost = 0.0
            for citation in result.citations:
                role = citation.anchor_role.lower()
                role_boost = max(role_boost, self.role_boosts.get(role, 0))

            # Score final
            final_score = (
                self.weights["vector_score"] * vector_score +
                self.weights["concept_score"] * concept_score +
                self.weights["anchor_density"] * anchor_density +
                self.weights["role_boost"] * role_boost
            )

            result.score = final_score
            scored_results.append(result)

        # Trier par score final
        scored_results.sort(key=lambda x: x.score, reverse=True)

        return scored_results


# =============================================================================
# Factory Pattern
# =============================================================================

_service_instance: Optional[HybridAnchorSearchService] = None


def get_hybrid_anchor_search_service(
    qdrant_client: QdrantClient,
    embedding_model: Any,
    tenant_id: str = "default"
) -> HybridAnchorSearchService:
    """
    Récupère l'instance du service de recherche hybride.

    Args:
        qdrant_client: Client Qdrant
        embedding_model: Modèle d'embedding
        tenant_id: ID tenant

    Returns:
        HybridAnchorSearchService instance
    """
    global _service_instance

    if _service_instance is None:
        _service_instance = HybridAnchorSearchService(
            qdrant_client=qdrant_client,
            embedding_model=embedding_model,
            tenant_id=tenant_id
        )

    return _service_instance
