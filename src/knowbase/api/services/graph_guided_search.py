"""
🌊 OSMOSE Phase 2.3 - Graph-Guided RAG Service

Service qui enrichit la recherche vectorielle avec des insights du Knowledge Graph.

Différenciation vs RAG classique:
- RAG classique: Question → Embedding → Top-K chunks → LLM → Réponse
- Graph-Guided RAG: Question → Embedding → Top-K chunks
                                        ↓
                          + Enrichissement KG:
                            - Concepts extraits de la question
                            - Relations transitives
                            - Concepts liés (même cluster)
                            - Bridge concepts pour élargir
                                        ↓
                          → Réponse enrichie + insights connexes
"""

from __future__ import annotations

import asyncio
import math
import re
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set, Tuple
from enum import Enum

from knowbase.common.logging import setup_logging
from knowbase.config.settings import get_settings
from knowbase.semantic.inference import InferenceEngine, InsightType

# Palier 2 - Semantic Search
QDRANT_CONCEPTS_COLLECTION = "knowwhere_concepts"

# ============================================================================
# Phase 2.7 - Concept Matching Engine (Palier 1: Full-Text Neo4j)
# ============================================================================

# Stopwords FR/EN pour tokenization
STOPWORDS_FR = {
    "le", "la", "les", "un", "une", "des", "du", "de", "d", "l",
    "et", "ou", "mais", "donc", "car", "ni", "que", "qui", "quoi",
    "ce", "cette", "ces", "mon", "ma", "mes", "ton", "ta", "tes",
    "son", "sa", "ses", "notre", "nos", "votre", "vos", "leur", "leurs",
    "je", "tu", "il", "elle", "on", "nous", "vous", "ils", "elles",
    "me", "te", "se", "lui", "y", "en",
    "est", "sont", "a", "ont", "fait", "faire", "être", "avoir",
    "pour", "par", "avec", "sans", "dans", "sur", "sous", "entre",
    "vers", "chez", "avant", "après", "pendant", "depuis",
    "quel", "quelle", "quels", "quelles", "comment", "pourquoi", "quand",
    "plus", "moins", "très", "bien", "aussi", "comme", "tout", "tous",
}

STOPWORDS_EN = {
    "the", "a", "an", "and", "or", "but", "if", "then", "else",
    "when", "where", "why", "how", "what", "which", "who", "whom",
    "this", "that", "these", "those", "is", "are", "was", "were",
    "be", "been", "being", "have", "has", "had", "do", "does", "did",
    "will", "would", "could", "should", "may", "might", "must", "shall",
    "can", "need", "dare", "ought", "used", "to", "of", "in", "for",
    "on", "with", "at", "by", "from", "up", "about", "into", "through",
    "during", "before", "after", "above", "below", "between", "under",
    "again", "further", "once", "here", "there", "all", "each", "few",
    "more", "most", "other", "some", "such", "no", "nor", "not", "only",
    "own", "same", "so", "than", "too", "very", "just", "also",
}

STOPWORDS = STOPWORDS_FR | STOPWORDS_EN


def tokenize_query(query: str, min_length: int = 2) -> List[str]:
    """
    Tokenize et normalise une requête utilisateur.

    - Lowercase
    - Supprime ponctuation sauf tirets internes
    - Filtre stopwords FR/EN
    - Garde les tokens courts (AI, NIS2, IoT) si min_length=2
    """
    # Lowercase et nettoyage basique
    query_clean = query.lower()

    # Remplacer ponctuation par espaces (garder tirets internes aux mots)
    query_clean = re.sub(r"[^\w\s\-]", " ", query_clean)

    # Split et filtrer
    tokens = []
    for token in query_clean.split():
        # Nettoyer tirets en début/fin
        token = token.strip("-")

        if len(token) < min_length:
            continue
        if token in STOPWORDS:
            continue

        tokens.append(token)

    return tokens


def normalize_scores(values: List[float]) -> List[float]:
    """Normalisation min-max des scores."""
    if not values:
        return []

    min_val = min(values)
    max_val = max(values)

    if max_val == min_val:
        return [0.5] * len(values)

    return [(v - min_val) / (max_val - min_val) for v in values]

settings = get_settings()
logger = setup_logging(settings.logs_dir, "graph_guided_search.log")


class EnrichmentLevel(str, Enum):
    """Niveau d'enrichissement KG pour la recherche."""
    NONE = "none"           # Pas d'enrichissement (RAG classique)
    LIGHT = "light"         # Concepts liés uniquement
    STANDARD = "standard"   # Concepts + relations transitives
    DEEP = "deep"           # Tout: concepts, transitives, clusters, bridges


@dataclass
class GraphContext:
    """Contexte KG extrait pour enrichir la recherche."""
    # Concepts identifiés dans la question
    query_concepts: List[str] = field(default_factory=list)

    # Concepts liés (voisins directs dans le KG)
    related_concepts: List[Dict[str, Any]] = field(default_factory=list)

    # Relations transitives découvertes
    transitive_relations: List[Dict[str, Any]] = field(default_factory=list)

    # Cluster thématique du concept principal
    thematic_cluster: Optional[Dict[str, Any]] = None

    # Bridge concepts (si pertinents)
    bridge_concepts: List[str] = field(default_factory=list)

    # Métadonnées
    enrichment_level: str = "none"
    processing_time_ms: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        """Convertit en dictionnaire pour la réponse API."""
        return {
            "query_concepts": self.query_concepts,
            "related_concepts": self.related_concepts,
            "transitive_relations": self.transitive_relations,
            "thematic_cluster": self.thematic_cluster,
            "bridge_concepts": self.bridge_concepts,
            "enrichment_level": self.enrichment_level,
            "processing_time_ms": self.processing_time_ms,
        }

    def get_expansion_terms(self) -> List[str]:
        """Retourne les termes d'expansion pour la recherche."""
        terms: Set[str] = set()

        # Ajouter les concepts liés
        for rel in self.related_concepts:
            if rel.get("concept"):
                terms.add(rel["concept"])

        # Ajouter les concepts des relations transitives
        for trans in self.transitive_relations:
            for concept in trans.get("concepts", []):
                terms.add(concept)

        # Ajouter les concepts du cluster
        if self.thematic_cluster:
            for concept in self.thematic_cluster.get("concepts", [])[:5]:
                terms.add(concept)

        # Ajouter les bridge concepts
        for bridge in self.bridge_concepts:
            terms.add(bridge)

        # Retirer les concepts de la question originale
        for qc in self.query_concepts:
            terms.discard(qc)

        return list(terms)[:10]  # Limiter à 10 termes d'expansion


class GraphGuidedSearchService:
    """
    Service de recherche guidée par le Knowledge Graph.

    Enrichit les résultats de recherche vectorielle avec des insights
    du KG pour une meilleure compréhension contextuelle.

    ⚠️ PERFORMANCE WARNING:
    - EnrichmentLevel.NONE   : 0ms (pas d'enrichissement)
    - EnrichmentLevel.LIGHT  : ~100ms (concepts liés uniquement)
    - EnrichmentLevel.STANDARD : ~250ms (+ relations transitives) ✅ Recommandé temps-réel
    - EnrichmentLevel.DEEP   : ~3min (+ NetworkX betweenness/Louvain) ⚠️ OFFLINE ONLY

    Ne JAMAIS utiliser DEEP pour des requêtes temps-réel !
    DEEP utilise des algorithmes NetworkX (betweenness, Louvain) qui chargent
    tout le graphe (~12000 nœuds) en mémoire et calculent des métriques coûteuses.
    """

    def __init__(self):
        self._inference_engine: Optional[InferenceEngine] = None
        self._neo4j_client = None
        self._qdrant_client = None
        self._embedder = None

    @property
    def inference_engine(self) -> InferenceEngine:
        """Lazy loading de l'InferenceEngine."""
        if self._inference_engine is None:
            self._inference_engine = InferenceEngine()
        return self._inference_engine

    @property
    def neo4j_client(self):
        """Lazy loading du client Neo4j."""
        if self._neo4j_client is None:
            from knowbase.neo4j_custom.client import get_neo4j_client
            self._neo4j_client = get_neo4j_client()
        return self._neo4j_client

    @property
    def qdrant_client(self):
        """Lazy loading du client Qdrant pour Palier 2."""
        if self._qdrant_client is None:
            from qdrant_client import QdrantClient
            self._qdrant_client = QdrantClient(url=settings.qdrant_url)
        return self._qdrant_client

    @property
    def embedder(self):
        """Lazy loading de l'embedder multilingue pour Palier 2."""
        if self._embedder is None:
            from knowbase.semantic.config import get_semantic_config
            from knowbase.semantic.utils.embeddings import get_embedder
            config = get_semantic_config()
            self._embedder = get_embedder(config)
        return self._embedder

    async def search_concepts_semantic(
        self,
        query: str,
        tenant_id: str = "default",
        top_k: int = 20
    ) -> List[Dict[str, Any]]:
        """
        Phase 2.7 - Palier 2: Recherche sémantique des concepts.

        Utilise les embeddings multilingual-e5-large pour trouver
        les concepts sémantiquement similaires à la requête.

        Avantages:
        - Multilingue (FR→EN, EN→FR)
        - Synonymes et reformulations
        - Concepts connexes non-mentionnés explicitement

        Args:
            query: Question utilisateur
            tenant_id: Tenant ID
            top_k: Nombre de résultats max

        Returns:
            Liste de dicts avec concept_id, canonical_name, sem_score
        """
        import time
        start_time = time.time()

        try:
            # Vérifier que la collection existe
            collections = self.qdrant_client.get_collections().collections
            if not any(c.name == QDRANT_CONCEPTS_COLLECTION for c in collections):
                logger.warning(f"[OSMOSE] Collection {QDRANT_CONCEPTS_COLLECTION} not found")
                return []

            # Générer l'embedding de la requête (prefix "query" pour e5)
            query_embedding = self.embedder.encode([query], prefix_type="query")[0]

            # Recherche vectorielle
            from qdrant_client.models import Filter, FieldCondition, MatchValue

            search_filter = Filter(
                must=[
                    FieldCondition(
                        key="tenant_id",
                        match=MatchValue(value=tenant_id)
                    )
                ]
            )

            results = self.qdrant_client.search(
                collection_name=QDRANT_CONCEPTS_COLLECTION,
                query_vector=query_embedding.tolist(),
                query_filter=search_filter,
                limit=top_k,
                with_payload=True
            )

            # Formater les résultats
            concepts = []
            for hit in results:
                concepts.append({
                    "concept_id": hit.payload.get("concept_id"),
                    "canonical_name": hit.payload.get("canonical_name"),
                    "concept_type": hit.payload.get("concept_type"),
                    "quality_score": hit.payload.get("quality_score", 0.5),
                    "popularity": hit.payload.get("popularity", 0),
                    "sem_score": hit.score,
                })

            elapsed_ms = (time.time() - start_time) * 1000
            logger.info(
                f"[OSMOSE] Semantic search: {len(concepts)} concepts in {elapsed_ms:.1f}ms"
            )

            return concepts

        except Exception as e:
            logger.warning(f"[OSMOSE] Semantic search failed: {e}")
            return []

    async def _search_concepts_lexical(
        self,
        query: str,
        tenant_id: str = "default",
        top_k: int = 50
    ) -> List[Dict[str, Any]]:
        """
        Palier 1: Recherche lexicale full-text Neo4j.

        Retourne une liste de candidats avec lex_adj normalisé.
        """
        # Tokenization
        tokens = tokenize_query(query, min_length=2)

        if not tokens:
            logger.warning(f"[OSMOSE] No tokens after filtering: {query[:50]}...")
            return []

        # Construire la query full-text (OR entre tokens)
        fulltext_query = " OR ".join(tokens)

        # Recherche full-text Neo4j
        cypher = """
        CALL db.index.fulltext.queryNodes('concept_search', $query)
        YIELD node, score
        WHERE node.tenant_id = $tenant_id
        RETURN
            node.concept_id AS id,
            node.canonical_name AS name,
            node.concept_type AS type,
            coalesce(node.quality_score, 0.5) AS quality,
            coalesce(size(node.chunk_ids), 0) AS popularity,
            coalesce(node.summary, '') AS summary,
            coalesce(node.unified_definition, '') AS definition,
            score AS lex_score
        ORDER BY score DESC
        LIMIT $limit
        """

        try:
            results = self.neo4j_client.execute_query(cypher, {
                "query": fulltext_query,
                "tenant_id": tenant_id,
                "limit": top_k
            })

            if not results:
                return []

            # Calcul lex_adj (normalisation par longueur)
            candidates = []
            for record in results:
                name = record.get("name", "")
                if not name:
                    continue

                summary = record.get("summary", "") or ""
                definition = record.get("definition", "") or ""
                lex_score = record.get("lex_score", 0.0)

                # Longueur du texte indexé (plafonné)
                len_text = len(name) + min(len(summary), 400) + min(len(definition), 400)

                # Score ajusté par longueur (évite biais concepts "bavards")
                lex_adj = lex_score / math.log(20 + len_text)

                candidates.append({
                    "id": record.get("id"),
                    "name": name,
                    "type": record.get("type", "UNKNOWN"),
                    "quality": record.get("quality", 0.5),
                    "popularity": record.get("popularity", 0),
                    "lex_adj": lex_adj,
                })

            return candidates

        except Exception as e:
            logger.warning(f"[OSMOSE] Lexical search failed: {e}")
            return []

    async def extract_concepts_from_query(
        self,
        query: str,
        tenant_id: str = "default",
        top_k: int = 10,
        max_per_type: int = 4,
        use_semantic: bool = True
    ) -> List[str]:
        """
        Phase 2.7 - Concept Matching Engine (Palier 1 + 2: Fusion Lex-Sem)

        Extrait les concepts pertinents de la question via:
        - Palier 1: Recherche full-text Neo4j (mots exacts)
        - Palier 2: Recherche sémantique Qdrant (multilingual)

        Fusion: Reciprocal Rank Fusion (RRF) pour combiner les deux rankings.

        Args:
            query: Question utilisateur
            tenant_id: Tenant ID
            top_k: Nombre de concepts à retourner (default: 10)
            max_per_type: Max concepts par type pour diversité (default: 4)
            use_semantic: Activer Palier 2 (default: True)

        Returns:
            Liste des noms de concepts triés par pertinence
        """
        import time
        start_time = time.time()

        # =====================================================================
        # Étape 1: Exécuter Palier 1 + Palier 2 en parallèle
        # =====================================================================
        if use_semantic:
            lex_task = self._search_concepts_lexical(query, tenant_id, top_k=50)
            sem_task = self.search_concepts_semantic(query, tenant_id, top_k=30)

            lex_results, sem_results = await asyncio.gather(lex_task, sem_task)
        else:
            lex_results = await self._search_concepts_lexical(query, tenant_id, top_k=50)
            sem_results = []

        # =====================================================================
        # Étape 2: Fusion avec Reciprocal Rank Fusion (RRF)
        # =====================================================================
        # RRF: score(d) = sum( 1 / (k + rank(d)) ) pour chaque système
        # k=60 est la constante standard
        RRF_K = 60

        # Construire le dictionnaire de fusion
        concept_scores: Dict[str, Dict[str, Any]] = {}

        # Ajouter les résultats lexicaux (déjà triés par lex_adj)
        for rank, c in enumerate(lex_results, start=1):
            name = c["name"]
            if name not in concept_scores:
                concept_scores[name] = {
                    "name": name,
                    "type": c["type"],
                    "quality": c["quality"],
                    "popularity": c["popularity"],
                    "lex_rank": rank,
                    "sem_rank": None,
                    "rrf_score": 0.0,
                }
            concept_scores[name]["lex_rank"] = rank
            concept_scores[name]["rrf_score"] += 1.0 / (RRF_K + rank)

        # Ajouter les résultats sémantiques (triés par sem_score)
        for rank, c in enumerate(sem_results, start=1):
            name = c["canonical_name"]
            if name not in concept_scores:
                concept_scores[name] = {
                    "name": name,
                    "type": c["concept_type"],
                    "quality": c["quality_score"],
                    "popularity": c["popularity"],
                    "lex_rank": None,
                    "sem_rank": rank,
                    "rrf_score": 0.0,
                }
            concept_scores[name]["sem_rank"] = rank
            concept_scores[name]["rrf_score"] += 1.0 / (RRF_K + rank)

        # =====================================================================
        # Étape 3: Ranking final avec qualité + popularité
        # =====================================================================
        candidates = list(concept_scores.values())

        if not candidates:
            logger.info(f"[OSMOSE] No concepts found for: {query[:50]}...")
            return []

        # Normaliser RRF, popularity, quality
        rrf_values = [c["rrf_score"] for c in candidates]
        pop_values = [math.log(1 + c["popularity"]) for c in candidates]
        quality_values = [c["quality"] for c in candidates]

        rrf_norm = normalize_scores(rrf_values)
        pop_norm = normalize_scores(pop_values)
        quality_norm = normalize_scores(quality_values)

        # Score final: 70% RRF + 20% popularité + 10% qualité
        for i, c in enumerate(candidates):
            c["final_score"] = (
                0.70 * rrf_norm[i] +
                0.20 * pop_norm[i] +
                0.10 * quality_norm[i]
            )

        # Trier par score final
        candidates.sort(key=lambda x: x["final_score"], reverse=True)

        # =====================================================================
        # Étape 4: Diversity re-ranking
        # =====================================================================
        final_concepts = []
        type_counts: Dict[str, int] = defaultdict(int)

        for c in candidates:
            ctype = c["type"]
            if type_counts[ctype] < max_per_type:
                final_concepts.append(c["name"])
                type_counts[ctype] += 1

            if len(final_concepts) >= top_k:
                break

        elapsed_ms = (time.time() - start_time) * 1000
        logger.info(
            f"[OSMOSE] Concept matching (RRF): {len(final_concepts)} concepts in {elapsed_ms:.1f}ms "
            f"(lex={len(lex_results)}, sem={len(sem_results)}, fusion={len(candidates)})"
        )

        return final_concepts

    async def get_related_concepts(
        self,
        concept_names: List[str],
        tenant_id: str = "default",
        max_per_concept: int = 5
    ) -> List[Dict[str, Any]]:
        """
        Récupère les concepts directement liés dans le KG.
        """
        if not concept_names:
            return []

        cypher = """
        UNWIND $concepts AS concept_name
        MATCH (c:CanonicalConcept {canonical_name: concept_name, tenant_id: $tenant_id})
        MATCH (c)-[r]-(related:CanonicalConcept)
        WHERE related.tenant_id = $tenant_id
        RETURN DISTINCT
            concept_name AS source,
            related.canonical_name AS concept,
            type(r) AS relation_type,
            r.confidence AS confidence
        ORDER BY r.confidence DESC
        LIMIT $limit
        """

        try:
            results = self.neo4j_client.execute_query(cypher, {
                "concepts": concept_names,
                "tenant_id": tenant_id,
                "limit": len(concept_names) * max_per_concept
            })

            related = []
            for record in results:
                related.append({
                    "source": record.get("source"),
                    "concept": record.get("concept"),
                    "relation": record.get("relation_type"),
                    "confidence": record.get("confidence", 0.5)
                })

            return related

        except Exception as e:
            logger.warning(f"[OSMOSE] Failed to get related concepts: {e}")
            return []

    async def get_transitive_for_concepts(
        self,
        concept_names: List[str],
        tenant_id: str = "default",
        max_results: int = 5
    ) -> List[Dict[str, Any]]:
        """
        Découvre les relations transitives impliquant les concepts.
        """
        if not concept_names:
            return []

        try:
            # Utiliser l'InferenceEngine pour les relations transitives
            insights = await self.inference_engine.discover_transitive_relations(
                tenant_id=tenant_id,
                max_results=max_results * 2
            )

            # Filtrer celles qui impliquent nos concepts
            relevant = []
            for insight in insights:
                if any(c in insight.concepts_involved for c in concept_names):
                    relevant.append({
                        "title": insight.title,
                        "description": insight.description,
                        "concepts": insight.concepts_involved,
                        "confidence": insight.confidence,
                        "evidence": insight.evidence_path
                    })
                    if len(relevant) >= max_results:
                        break

            return relevant

        except Exception as e:
            logger.warning(f"[OSMOSE] Failed to get transitive relations: {e}")
            return []

    async def get_concept_cluster(
        self,
        concept_names: List[str],
        tenant_id: str = "default"
    ) -> Optional[Dict[str, Any]]:
        """
        Identifie le cluster thématique du concept principal.
        """
        if not concept_names:
            return None

        try:
            # Récupérer tous les clusters
            clusters = await self.inference_engine.discover_hidden_clusters(
                tenant_id=tenant_id,
                max_results=20
            )

            # Trouver le cluster qui contient le plus de nos concepts
            best_cluster = None
            best_overlap = 0

            for cluster in clusters:
                cluster_concepts = set(cluster.concepts_involved)
                overlap = len(set(concept_names) & cluster_concepts)

                if overlap > best_overlap:
                    best_overlap = overlap
                    best_cluster = cluster

            if best_cluster and best_overlap > 0:
                return {
                    "title": best_cluster.title,
                    "concepts": best_cluster.concepts_involved[:10],
                    "size": len(best_cluster.concepts_involved),
                    "confidence": best_cluster.confidence
                }

            return None

        except Exception as e:
            logger.warning(f"[OSMOSE] Failed to get concept cluster: {e}")
            return None

    async def get_bridge_concepts(
        self,
        tenant_id: str = "default",
        max_results: int = 3
    ) -> List[str]:
        """
        Récupère les bridge concepts principaux du KG.
        """
        try:
            bridges = await self.inference_engine.discover_bridge_concepts(
                tenant_id=tenant_id,
                min_betweenness=0.05,
                max_results=max_results
            )

            return [b.concepts_involved[0] for b in bridges if b.concepts_involved]

        except Exception as e:
            logger.warning(f"[OSMOSE] Failed to get bridge concepts: {e}")
            return []

    async def build_graph_context(
        self,
        query: str,
        tenant_id: str = "default",
        enrichment_level: EnrichmentLevel = EnrichmentLevel.STANDARD
    ) -> GraphContext:
        """
        Construit le contexte KG complet pour une requête.

        Args:
            query: Question de l'utilisateur
            tenant_id: Tenant ID
            enrichment_level: Niveau d'enrichissement souhaité

        Returns:
            GraphContext avec toutes les informations KG
        """
        import time
        start_time = time.time()

        context = GraphContext(enrichment_level=enrichment_level.value)

        if enrichment_level == EnrichmentLevel.NONE:
            return context

        # Étape 1: Extraire les concepts de la question
        context.query_concepts = await self.extract_concepts_from_query(
            query, tenant_id
        )

        if not context.query_concepts:
            logger.info(f"[OSMOSE] No concepts found in query: {query[:50]}...")
            context.processing_time_ms = (time.time() - start_time) * 1000
            return context

        logger.info(f"[OSMOSE] Query concepts: {context.query_concepts}")

        # Étape 2: Concepts liés (tous niveaux sauf NONE)
        context.related_concepts = await self.get_related_concepts(
            context.query_concepts, tenant_id
        )

        if enrichment_level == EnrichmentLevel.LIGHT:
            context.processing_time_ms = (time.time() - start_time) * 1000
            return context

        # Étape 3: Relations transitives (STANDARD et DEEP)
        context.transitive_relations = await self.get_transitive_for_concepts(
            context.query_concepts, tenant_id
        )

        if enrichment_level == EnrichmentLevel.STANDARD:
            context.processing_time_ms = (time.time() - start_time) * 1000
            return context

        # Étape 4: Cluster et bridges (DEEP uniquement)
        context.thematic_cluster = await self.get_concept_cluster(
            context.query_concepts, tenant_id
        )

        context.bridge_concepts = await self.get_bridge_concepts(
            tenant_id, max_results=3
        )

        context.processing_time_ms = (time.time() - start_time) * 1000

        logger.info(
            f"[OSMOSE] Graph context built in {context.processing_time_ms:.1f}ms: "
            f"{len(context.query_concepts)} query concepts, "
            f"{len(context.related_concepts)} related, "
            f"{len(context.transitive_relations)} transitive"
        )

        return context

    def format_context_for_synthesis(self, context: GraphContext) -> str:
        """
        Formate le contexte KG pour inclusion dans le prompt de synthèse.

        Returns:
            Texte formaté à ajouter au prompt LLM
        """
        if context.enrichment_level == "none":
            return ""

        if not context.query_concepts and not context.related_concepts:
            return ""

        lines = [
            "",
            "=" * 50,
            "CONTEXTE KNOWLEDGE GRAPH (OSMOSE)",
            "=" * 50,
        ]

        # Concepts identifiés
        if context.query_concepts:
            lines.append(f"\n📌 Concepts identifiés dans la question:")
            for concept in context.query_concepts:
                lines.append(f"   • {concept}")

        # Concepts liés
        if context.related_concepts:
            lines.append(f"\n🔗 Concepts liés dans le Knowledge Graph:")
            seen = set()
            for rel in context.related_concepts[:8]:
                concept = rel.get("concept", "")
                relation = rel.get("relation", "RELATED_TO")
                source = rel.get("source", "")
                if concept and concept not in seen:
                    lines.append(f"   • {source} --[{relation}]--> {concept}")
                    seen.add(concept)

        # Relations transitives
        if context.transitive_relations:
            lines.append(f"\n🔄 Relations transitives découvertes:")
            for trans in context.transitive_relations[:3]:
                lines.append(f"   • {trans.get('description', trans.get('title', ''))}")

        # Cluster thématique
        if context.thematic_cluster:
            cluster = context.thematic_cluster
            lines.append(f"\n🎯 Cluster thématique: {cluster.get('title', 'Cluster')}")
            concepts = cluster.get("concepts", [])[:5]
            if concepts:
                lines.append(f"   Concepts associés: {', '.join(concepts)}")

        # Bridge concepts
        if context.bridge_concepts:
            lines.append(f"\n🌉 Concepts clés (bridges): {', '.join(context.bridge_concepts)}")

        lines.append("")
        lines.append("Utilise ce contexte pour enrichir ta réponse avec des connexions")
        lines.append("pertinentes entre concepts, si cela apporte de la valeur.")
        lines.append("=" * 50)

        return "\n".join(lines)


# Singleton instance
_graph_guided_service: Optional[GraphGuidedSearchService] = None


def get_graph_guided_service() -> GraphGuidedSearchService:
    """Retourne l'instance singleton du service."""
    global _graph_guided_service
    if _graph_guided_service is None:
        _graph_guided_service = GraphGuidedSearchService()
    return _graph_guided_service


__all__ = [
    "GraphGuidedSearchService",
    "GraphContext",
    "EnrichmentLevel",
    "get_graph_guided_service",
]
