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

# ============================================================================
# ADR_GRAPH_FIRST_ARCHITECTURE: Approche DENYLIST pour les relations
# ============================================================================
# POURQUOI DENYLIST au lieu de ALLOWLIST ?
# - Evite le bug ou de nouvelles relations sont ignorees (INTEGRATES_WITH, USES...)
# - Plus stable : on exclut les relations techniques/faibles
# - Tout le reste est semantique pour le pathfinding
# Ref: doc/ongoing/ANALYSE_ECHEC_KG_FIRST_TEST.md - Section 10.1

# Relations EXCLUES du pathfinding (techniques, navigation, faibles)
EXCLUDED_RELATION_TYPES = frozenset({
    # Relations techniques/internes
    "INSTANCE_OF", "MERGED_INTO", "COVERS", "HAS_TOPIC",
    # Relations navigation (evidence retrieval, pas pathfinding)
    "MENTIONED_IN", "HAS_SECTION", "CONTAINED_IN",
    # Relations faibles (co-occurrence)
    "CO_OCCURS", "APPEARS_WITH", "CO_OCCURS_IN_DOCUMENT", "CO_OCCURS_IN_CORPUS",
})


def is_semantic_relation(relation_type: str) -> bool:
    """True si relation semantique (utile pour pathfinding). Approche DENYLIST."""
    return relation_type not in EXCLUDED_RELATION_TYPES


# SEMANTIC_RELATION_TYPES etendu (indicatif - vraie logique dans is_semantic_relation)
SEMANTIC_RELATION_TYPES = frozenset({
    # Relations causales/dependances
    "REQUIRES", "ENABLES", "PREVENTS", "CAUSES",
    "APPLIES_TO", "DEPENDS_ON", "MITIGATES",
    # Relations structurelles
    "PART_OF", "DEFINES", "EXAMPLE_OF", "GOVERNED_BY", "CONFLICTS_WITH",
    # Relations integration (AJOUTEES - Fix bug KG-First 2026-01-07)
    "USES", "INTEGRATES_WITH", "COMPLIES_WITH",
    # Relations taxonomiques
    "RELATED_TO", "SUBTYPE_OF", "EXTENDS",
    # Relations temporelles/versioning
    "VERSION_OF", "PRECEDES", "REPLACES", "DEPRECATES", "ALTERNATIVE_TO",
    # Relations generiques
    "TRANSITIVE",
})

# ADR_GRAPH_FIRST_ARCHITECTURE: Relations navigation pour evidence retrieval
# MENTIONED_IN est utilisé pour récupérer les context_id des sections (Phase A)
NAVIGATION_RELATION_TYPES = frozenset({
    "MENTIONED_IN",  # Concept → SectionContext (avec salience, positions)
})

# Palier 2 - Semantic Search (importe depuis concept_embedding_service)
from knowbase.semantic.concept_embedding_service import (
    QDRANT_CONCEPTS_COLLECTION,
    get_concept_embedding_service,
    ConceptSemanticStatus,
)

# ============================================================================
# Phase 2.7 - Concept Matching Engine (Palier 1: Full-Text Neo4j)
# ============================================================================

# Stopwords multilingues via NLTK (32 langues supportées)
def _load_multilingual_stopwords() -> set:
    """
    Charge les stopwords de toutes les langues NLTK disponibles.

    Retourne l'union de tous les stopwords pour supporter
    les questions en n'importe quelle langue sans détection.
    """
    try:
        from nltk.corpus import stopwords as nltk_stopwords
        all_stopwords = set()
        for lang in nltk_stopwords.fileids():
            try:
                all_stopwords.update(nltk_stopwords.words(lang))
            except Exception:
                pass

        # Ajouter quelques stopwords supplémentaires courants
        # (fragments de mots interrogatifs, contractions, etc.)
        extras = {"qu", "ce", "cet", "d", "l", "n", "s", "t", "j", "m"}
        all_stopwords.update(extras)

        # Note: logger pas encore disponible ici, on log silencieusement
        return all_stopwords

    except Exception:
        # Fallback minimal FR/EN si NLTK indisponible
        return {
            "le", "la", "les", "de", "du", "des", "un", "une", "et", "ou",
            "the", "a", "an", "of", "to", "in", "for", "on", "with", "and", "or",
            "is", "are", "was", "were", "be", "been", "have", "has", "had",
            "ce", "cette", "qui", "que", "quoi", "est", "sont",
        }

# Cache des stopwords (chargés une seule fois)
STOPWORDS = _load_multilingual_stopwords()


def tokenize_query(query: str, min_length: int = 2) -> List[str]:
    """
    Tokenize et normalise une requête utilisateur.

    - Lowercase
    - Supprime ponctuation
    - Sépare les mots composés (tirets)
    - Filtre stopwords FR/EN
    - Garde les tokens courts (AI, NIS2, IoT) si min_length=2
    """
    # Lowercase et nettoyage basique
    query_clean = query.lower()

    # Remplacer ponctuation ET tirets par espaces (sépare "est-ce" en "est" "ce")
    query_clean = re.sub(r"[^\w\s]", " ", query_clean)

    # Split et filtrer
    tokens = []
    for token in query_clean.split():
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
    # Concepts identifiés dans la question (avec canonical_id)
    query_concepts: List[str] = field(default_factory=list)
    query_concept_ids: List[str] = field(default_factory=list)  # canonical_ids

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

    # 🌊 Phase 2.12: Métadonnées de visibilité (Couche 3)
    visibility_profile: str = "balanced"
    visibility_filtered_count: int = 0

    # 🌊 Phase 2.13: Statut semantic pour observabilité
    concept_semantic_status: Optional[ConceptSemanticStatus] = None


    # P1 Fallback: Mappings concept isole -> variante connectee
    fallback_mappings: List[Dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        """Convertit en dictionnaire pour la réponse API."""
        result = {
            "query_concepts": self.query_concepts,
            "query_concept_ids": self.query_concept_ids,
            "related_concepts": self.related_concepts,
            "transitive_relations": self.transitive_relations,
            "thematic_cluster": self.thematic_cluster,
            "bridge_concepts": self.bridge_concepts,
            "enrichment_level": self.enrichment_level,
            "processing_time_ms": self.processing_time_ms,
            # 🌊 Phase 2.12: Info profil visibilité
            "visibility_profile": self.visibility_profile,
            "visibility_filtered_count": self.visibility_filtered_count,
            "fallback_mappings": self.fallback_mappings,
        }
        # 🌊 Phase 2.13: Statut semantic
        if self.concept_semantic_status:
            result["concept_semantic_status"] = self.concept_semantic_status.to_dict()
        return result

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

    🌊 Phase 2.12: Intègre le VisibilityService pour filtrer les relations
    selon le profil de visibilité du tenant (Couche 3 de l'architecture agnostique).

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
        self._visibility_service = None

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

    def get_visibility_service(self, tenant_id: str = "default"):
        """Lazy loading du VisibilityService pour un tenant."""
        from knowbase.api.services.visibility_service import get_visibility_service
        return get_visibility_service(tenant_id=tenant_id)

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
        # Note: canonical_id est l'identifiant unique (concept_id est deprecated/None)
        cypher = """
        CALL db.index.fulltext.queryNodes('concept_search', $query)
        YIELD node, score
        WHERE node.tenant_id = $tenant_id
        RETURN
            node.canonical_id AS id,
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

    async def _search_topics_lexical(
        self,
        query: str,
        tenant_id: str = "default",
        top_k: int = 10
    ) -> List[Dict[str, Any]]:
        """
        Phase 2.13b - Recherche lexicale spécifique aux Topics.

        Utilisé pour le "seed mixing" : garantir que les Topics pertinents
        sont inclus dans les seeds même si leur score fulltext est inférieur
        aux concepts génériques.

        Fix 2026-01-22: Implémentation Priority 2 ChatGPT analysis.
        """
        tokens = tokenize_query(query, min_length=2)

        if not tokens:
            return []

        fulltext_query = " OR ".join(tokens)

        # Recherche full-text filtrée sur concept_type='TOPIC'
        # Note: canonical_id est l'identifiant unique (concept_id est deprecated/None)
        cypher = """
        CALL db.index.fulltext.queryNodes('concept_search', $query)
        YIELD node, score
        WHERE node.tenant_id = $tenant_id AND node.concept_type = 'TOPIC'
        RETURN
            node.canonical_id AS id,
            node.canonical_name AS name,
            node.concept_type AS type,
            coalesce(node.quality_score, 0.5) AS quality,
            coalesce(size(node.chunk_ids), 0) AS popularity,
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

            candidates = []
            for record in results:
                name = record.get("name", "")
                if not name:
                    continue

                candidates.append({
                    "id": record.get("id"),
                    "name": name,
                    "type": "TOPIC",
                    "quality": record.get("quality", 0.5),
                    "popularity": record.get("popularity", 0),
                    "lex_score": record.get("lex_score", 0.0),
                })

            logger.debug(
                f"[OSMOSE:SeedMix] Found {len(candidates)} Topics for query: {query[:50]}..."
            )
            return candidates

        except Exception as e:
            logger.warning(f"[OSMOSE:SeedMix] Topic search failed: {e}")
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

        Wrapper pour compatibilité - retourne uniquement les noms.
        Utiliser extract_concepts_from_query_v2() pour avoir les IDs.
        """
        result = await self.extract_concepts_from_query_v2(
            query=query,
            tenant_id=tenant_id,
            top_k=top_k,
            max_per_type=max_per_type,
            use_semantic=use_semantic,
        )
        return result["names"]

    async def extract_concepts_from_query_v2(
        self,
        query: str,
        tenant_id: str = "default",
        top_k: int = 10,
        max_per_type: int = 4,
        use_semantic: bool = True
    ) -> Dict[str, Any]:
        """
        Phase 2.13 - Concept Matching Engine v2 (avec IDs et observabilité)

        Extrait les concepts pertinents de la question via:
        - Palier 1: Recherche full-text Neo4j (mots exacts)
        - Palier 2: Recherche sémantique Qdrant (multilingual cross-lingual)

        Fusion: Reciprocal Rank Fusion (RRF) avec garde-fous sémantiques.

        Args:
            query: Question utilisateur
            tenant_id: Tenant ID
            top_k: Nombre de concepts à retourner (default: 10)
            max_per_type: Max concepts par type pour diversité (default: 4)
            use_semantic: Activer Palier 2 (default: True)

        Returns:
            Dict avec:
            - names: Liste des noms de concepts
            - ids: Liste des canonical_ids correspondants
            - semantic_status: ConceptSemanticStatus
            - details: Info détaillées pour debug
        """
        import time
        start_time = time.time()

        # =====================================================================
        # Étape 0: Vérifier le statut semantic (mode dégradé)
        # =====================================================================
        semantic_status = None
        semantic_available = False

        if use_semantic:
            try:
                service = get_concept_embedding_service()
                semantic_status = service.get_status(tenant_id)
                semantic_available = semantic_status.available

                if not semantic_available:
                    logger.warning(
                        f"[OSMOSE] Semantic search unavailable: {semantic_status.message}. "
                        f"Falling back to lexical-only mode (cross-lingual matching disabled)"
                    )
            except Exception as e:
                logger.warning(f"[OSMOSE] Failed to check semantic status: {e}")
                semantic_status = ConceptSemanticStatus(
                    available=False,
                    message=f"Service error: {str(e)}"
                )

        # =====================================================================
        # Étape 1: Exécuter Palier 1 + Palier 2 en parallèle
        # =====================================================================
        if use_semantic and semantic_available:
            lex_task = self._search_concepts_lexical(query, tenant_id, top_k=50)
            sem_task = self.search_concepts_semantic(query, tenant_id, top_k=30)

            lex_results, sem_results = await asyncio.gather(lex_task, sem_task)
        else:
            lex_results = await self._search_concepts_lexical(query, tenant_id, top_k=50)
            sem_results = []

        # =====================================================================
        # Étape 2: Fusion par canonical_id avec RRF + garde-fous
        # =====================================================================
        RRF_K = 60

        # Garde-fous sémantiques
        MIN_SEMANTIC_SCORE = 0.78  # Seuil minimum pour considérer un résultat pertinent
        MIN_SEMANTIC_HITS = 3  # Minimum de hits sémantiques pour considérer le boost
        SEMANTIC_BOOST = 1.2  # Boost si concept trouvé par les 2 paliers

        # Filtrer les résultats sémantiques sous le seuil de pertinence
        # (évite d'afficher des concepts hors-sujet pour des questions hors-scope)
        sem_results_filtered = [
            r for r in sem_results if r.get("sem_score", 0) >= MIN_SEMANTIC_SCORE
        ]
        filtered_count = len(sem_results) - len(sem_results_filtered)
        if filtered_count > 0:
            logger.debug(
                f"[OSMOSE] Filtered {filtered_count} low-score semantic results "
                f"(threshold={MIN_SEMANTIC_SCORE})"
            )
        sem_results = sem_results_filtered

        # Dictionnaire de fusion par canonical_id
        concept_scores: Dict[str, Dict[str, Any]] = {}

        # Ajouter les résultats lexicaux (par id si disponible, sinon par nom)
        for rank, c in enumerate(lex_results, start=1):
            concept_id = c.get("id") or c["name"]  # Fallback sur nom si pas d'ID
            name = c["name"]

            if concept_id not in concept_scores:
                concept_scores[concept_id] = {
                    "id": concept_id,
                    "name": name,
                    "type": c["type"],
                    "quality": c["quality"],
                    "popularity": c["popularity"],
                    "lex_rank": None,
                    "sem_rank": None,
                    "rrf_score": 0.0,
                    "has_lex": False,
                    "has_sem": False,
                }
            concept_scores[concept_id]["lex_rank"] = rank
            concept_scores[concept_id]["has_lex"] = True
            concept_scores[concept_id]["rrf_score"] += 1.0 / (RRF_K + rank)

        # Ajouter les résultats sémantiques (par concept_id)
        for rank, c in enumerate(sem_results, start=1):
            concept_id = c.get("concept_id") or c["canonical_name"]
            name = c["canonical_name"]

            if concept_id not in concept_scores:
                concept_scores[concept_id] = {
                    "id": concept_id,
                    "name": name,
                    "type": c["concept_type"],
                    "quality": c["quality_score"],
                    "popularity": c["popularity"],
                    "lex_rank": None,
                    "sem_rank": None,
                    "rrf_score": 0.0,
                    "has_lex": False,
                    "has_sem": False,
                }
            concept_scores[concept_id]["sem_rank"] = rank
            concept_scores[concept_id]["has_sem"] = True
            concept_scores[concept_id]["rrf_score"] += 1.0 / (RRF_K + rank)

        # =====================================================================
        # Étape 2b: Seed Mixing - Garantir l'inclusion de Topics (fix 2026-01-22)
        # Priority 2 ChatGPT analysis: top-N tous types + top-M Topics
        # =====================================================================
        MIN_TOPICS_IN_SEEDS = 3  # Garantir au moins 3 Topics dans les seeds
        TOPIC_SEARCH_K = 10  # Nombre de Topics à chercher si besoin
        TOPIC_INJECT_BONUS = 0.012  # Bonus RRF pour Topics injectés (équivalent rank ~25)

        # Compter les Topics déjà présents
        existing_topics = [
            cid for cid, c in concept_scores.items()
            if c.get("type") == "TOPIC"
        ]
        topics_needed = MIN_TOPICS_IN_SEEDS - len(existing_topics)

        if topics_needed > 0:
            # Recherche spécifique Topics
            topic_results = await self._search_topics_lexical(
                query, tenant_id, top_k=TOPIC_SEARCH_K
            )

            topics_injected = 0
            for t in topic_results:
                topic_id = t.get("id") or t["name"]

                if topic_id not in concept_scores:
                    # Nouveau Topic à injecter
                    concept_scores[topic_id] = {
                        "id": topic_id,
                        "name": t["name"],
                        "type": "TOPIC",
                        "quality": t.get("quality", 0.5),
                        "popularity": t.get("popularity", 0),
                        "lex_rank": None,
                        "sem_rank": None,
                        "rrf_score": TOPIC_INJECT_BONUS,  # Bonus pour visibilité
                        "has_lex": True,
                        "has_sem": False,
                        "topic_injected": True,  # Flag pour observabilité
                    }
                    topics_injected += 1

                    if topics_injected >= topics_needed:
                        break

            if topics_injected > 0:
                logger.info(
                    f"[OSMOSE:SeedMix] Injected {topics_injected} Topics into seeds "
                    f"(had {len(existing_topics)}, now {len(existing_topics) + topics_injected})"
                )

        # =====================================================================
        # Étape 3: Appliquer le boost sémantique si assez de hits
        # =====================================================================
        candidates = list(concept_scores.values())

        if not candidates:
            elapsed_ms = (time.time() - start_time) * 1000
            logger.info(f"[OSMOSE] No concepts found for: {query[:50]}...")
            return {
                "names": [],
                "ids": [],
                "semantic_status": semantic_status,
                "details": {
                    "lex_count": 0,
                    "sem_count": 0,
                    "fusion_count": 0,
                    "elapsed_ms": elapsed_ms,
                },
            }

        # Appliquer le boost sémantique si garde-fou respecté
        sem_only_count = sum(1 for c in candidates if c["has_sem"] and not c["has_lex"])
        if len(sem_results) >= MIN_SEMANTIC_HITS:
            for c in candidates:
                if c["has_lex"] and c["has_sem"]:
                    # Concept trouvé par les deux systèmes = boost
                    c["rrf_score"] *= SEMANTIC_BOOST


        # =====================================================================
        # P1 Connectivity-First Reranking
        # Favoriser les concepts qui ont des relations sémantiques dans le KG
        # =====================================================================
        CONNECTIVITY_BOOST = 1.3

        try:
            candidate_names = [c["name"] for c in candidates[:20]]
            if candidate_names:
                cypher = """
                UNWIND $names AS cname
                MATCH (c:CanonicalConcept {canonical_name: cname, tenant_id: $tid})
                OPTIONAL MATCH (c)-[r]-(other:CanonicalConcept)
                WHERE type(r) IN $sem_types
                RETURN cname AS name, count(r) AS rel_count
                """
                counts = self.neo4j_client.execute_query(cypher, {
                    "names": candidate_names,
                    "tid": tenant_id,
                    "sem_types": list(SEMANTIC_RELATION_TYPES)
                })
                count_map = {r["name"]: r["rel_count"] for r in counts}

                connected_count = 0
                for c in candidates:
                    rel_count = count_map.get(c["name"], 0)
                    c["kg_relations"] = rel_count
                    if rel_count > 0:
                        c["rrf_score"] *= CONNECTIVITY_BOOST
                        connected_count += 1

                if connected_count > 0:
                    logger.debug(
                        f"[OSMOSE:Connectivity] {connected_count}/{len(candidates)} "
                        f"concepts have KG relations"
                    )
        except Exception as e:
            logger.warning(f"[OSMOSE:Connectivity] Check failed: {e}")

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
        final_ids = []
        type_counts: Dict[str, int] = defaultdict(int)

        for c in candidates:
            ctype = c["type"]
            if type_counts[ctype] < max_per_type:
                final_concepts.append(c["name"])
                final_ids.append(c["id"])
                type_counts[ctype] += 1

            if len(final_concepts) >= top_k:
                break

        elapsed_ms = (time.time() - start_time) * 1000
        logger.info(
            f"[OSMOSE] Concept matching (RRF): {len(final_concepts)} concepts in {elapsed_ms:.1f}ms "
            f"(lex={len(lex_results)}, sem={len(sem_results)}, fusion={len(candidates)}, "
            f"sem_only={sem_only_count}, semantic_available={semantic_available})"
        )

        return {
            "names": final_concepts,
            "ids": final_ids,
            "semantic_status": semantic_status,
            "details": {
                "lex_count": len(lex_results),
                "sem_count": len(sem_results),
                "fusion_count": len(candidates),
                "sem_only_count": sem_only_count,
                "semantic_available": semantic_available,
                "elapsed_ms": elapsed_ms,
            },
        }

    async def get_related_concepts(
        self,
        concept_names: List[str],
        tenant_id: str = "default",
        max_per_concept: int = 5
    ) -> List[Dict[str, Any]]:
        """
        Récupère les concepts directement liés dans le KG.

        🌊 Phase 2.12: Les relations sont filtrées selon le profil de visibilité
        du tenant (Couche 3 de l'architecture agnostique KG).
        """
        if not concept_names:
            return []

        # 🌊 Phase 2.12: Récupérer les paramètres du profil de visibilité
        try:
            visibility_service = self.get_visibility_service(tenant_id)
            profile_id = visibility_service.get_profile_for_tenant(tenant_id)
            profile = visibility_service.get_profile(profile_id)
            profile_settings = profile.settings

            min_confidence = profile_settings.min_confidence
            min_source_count = profile_settings.min_source_count
            allowed_maturities = profile_settings.allowed_maturities

            logger.debug(
                f"[OSMOSE] Visibility profile '{profile_id}': "
                f"min_confidence={min_confidence}, min_source_count={min_source_count}"
            )
        except Exception as e:
            logger.warning(f"[OSMOSE] Could not load visibility profile, using defaults: {e}")
            min_confidence = 0.5
            min_source_count = 1
            allowed_maturities = ["VALIDATED", "CANDIDATE"]

        # Requête avec filtres de visibilité
        # ADR_GRAPH_FIRST_ARCHITECTURE: Relations sémantiques uniquement pour pathfinding
        # MENTIONED_IN est utilisé séparément pour evidence retrieval (voir get_evidence_context_ids)
        # 🌊 OSMOSE: Récupère aussi evidence_quote pour affichage dans le hover
        cypher = """
        UNWIND $concepts AS concept_name
        MATCH (c:CanonicalConcept {canonical_name: concept_name, tenant_id: $tenant_id})
        MATCH (c)-[r]-(related:CanonicalConcept)
        WHERE related.tenant_id = $tenant_id
          AND type(r) IN $semantic_relation_types
          AND coalesce(r.confidence, 0.5) >= $min_confidence
          AND coalesce(r.source_count, 1) >= $min_source_count
          AND coalesce(r.maturity, 'CANDIDATE') IN $allowed_maturities
        RETURN DISTINCT
            concept_name AS source,
            related.canonical_name AS concept,
            type(r) AS relation_type,
            r.confidence AS confidence,
            r.maturity AS maturity,
            r.source_count AS source_count,
            r.evidence_quote AS evidence_quote,
            r.evidence_count AS evidence_count,
            r.document_id AS document_id
        ORDER BY r.confidence DESC
        LIMIT $limit
        """

        try:
            results = self.neo4j_client.execute_query(cypher, {
                "concepts": concept_names,
                "tenant_id": tenant_id,
                "semantic_relation_types": list(SEMANTIC_RELATION_TYPES),
                "min_confidence": min_confidence,
                "min_source_count": min_source_count,
                "allowed_maturities": allowed_maturities,
                "limit": len(concept_names) * max_per_concept
            })

            related = []
            for record in results:
                related.append({
                    "source": record.get("source"),
                    "concept": record.get("concept"),
                    "relation": record.get("relation_type"),
                    "confidence": record.get("confidence", 0.5),
                    "maturity": record.get("maturity", "CANDIDATE"),
                    "source_count": record.get("source_count", 1),
                    # 🌊 OSMOSE: Evidence pour affichage dans le hover
                    "evidence_quote": record.get("evidence_quote"),
                    "evidence_count": record.get("evidence_count", 0),
                    "document_id": record.get("document_id"),
                })

            logger.info(
                f"[OSMOSE] Related concepts: {len(related)} (profile={profile_id})"
            )

            return related

        except Exception as e:
            logger.warning(f"[OSMOSE] Failed to get related concepts: {e}")
            return []


    # =========================================================================
    # P1 FALLBACK: Variantes connectées pour concepts isolés
    # Ref: doc/ongoing/ANALYSE_ECHEC_KG_FIRST_TEST.md - Section 12.4
    # =========================================================================

    async def find_connected_variants(
        self,
        isolated_concepts: List[str],
        tenant_id: str = "default",
        embedding_threshold: float = 0.80,
        max_variants: int = 3
    ) -> Dict[str, List[Dict[str, Any]]]:
        """
        Pour concepts sans relations, chercher variantes embedding-similaires
        qui ONT des relations sémantiques.
        """
        if not isolated_concepts:
            return {}

        results = {}
        for concept_name in isolated_concepts:
            try:
                similar = await self.search_concepts_semantic(concept_name, tenant_id, top_k=10)
                candidates = [
                    c for c in similar
                    if c.get("sem_score", 0) >= embedding_threshold
                    and c.get("canonical_name") != concept_name
                ]
                if not candidates:
                    continue

                candidate_names = [c["canonical_name"] for c in candidates[:5]]
                cypher = """
                UNWIND $names AS cname
                MATCH (c:CanonicalConcept {canonical_name: cname, tenant_id: $tid})
                MATCH (c)-[r]-(other:CanonicalConcept)
                WHERE type(r) IN $sem_types
                RETURN cname AS name, count(r) AS rel_count
                """
                counts = self.neo4j_client.execute_query(cypher, {
                    "names": candidate_names, "tid": tenant_id,
                    "sem_types": list(SEMANTIC_RELATION_TYPES)
                })
                count_map = {r["name"]: r["rel_count"] for r in counts}

                connected = []
                for c in candidates:
                    cname = c["canonical_name"]
                    if count_map.get(cname, 0) > 0:
                        connected.append({
                            "original": concept_name, "variant": cname,
                            "similarity": c.get("sem_score", 0),
                            "relation_count": count_map[cname],
                            "concept_id": c.get("concept_id"),
                        })
                if connected:
                    connected.sort(key=lambda x: (x["relation_count"], x["similarity"]), reverse=True)
                    results[concept_name] = connected[:max_variants]
                    logger.info(f"[OSMOSE:Fallback] '{concept_name}' -> {[v['variant'] for v in results[concept_name]]}")
            except Exception as e:
                logger.warning(f"[OSMOSE:Fallback] Error for '{concept_name}': {e}")
        return results

    async def enrich_with_connected_variants(
        self,
        query_concepts: List[str],
        related_concepts: List[Dict[str, Any]],
        tenant_id: str = "default"
    ) -> Tuple[List[str], List[Dict[str, Any]], List[Dict[str, Any]]]:
        """Enrichit les concepts avec variantes connectées si isolés."""
        with_relations = {r["source"] for r in related_concepts}
        isolated = [c for c in query_concepts if c not in with_relations]
        if not isolated:
            return query_concepts, related_concepts, []

        logger.info(f"[OSMOSE:Fallback] {len(isolated)} isolated: {isolated}")
        variants_map = await self.find_connected_variants(isolated, tenant_id)
        if not variants_map:
            return query_concepts, related_concepts, []

        enriched_concepts = list(query_concepts)
        fallback_mappings = []
        for original, variants in variants_map.items():
            if variants:
                best = variants[0]
                if best["variant"] not in enriched_concepts:
                    enriched_concepts.append(best["variant"])
                    fallback_mappings.append({
                        "original": original, "fallback": best["variant"],
                        "similarity": best["similarity"], "relation_count": best["relation_count"]
                    })

        if fallback_mappings:
            new_variants = [m["fallback"] for m in fallback_mappings]
            additional = await self.get_related_concepts(new_variants, tenant_id)
            related_concepts = related_concepts + additional
            logger.info(f"[OSMOSE:Fallback] +{len(fallback_mappings)} variants, +{len(additional)} relations")

        return enriched_concepts, related_concepts, fallback_mappings

    async def get_evidence_context_ids(
        self,
        concept_ids: List[str],
        tenant_id: str = "default",
        min_salience: float = 0.0,
        max_per_concept: int = 10
    ) -> Dict[str, List[str]]:
        """
        ADR_GRAPH_FIRST_ARCHITECTURE Phase A: Evidence Retrieval via MENTIONED_IN.

        Récupère les context_id des sections où les concepts sont mentionnés.
        Ces context_id peuvent être utilisés pour filtrer Qdrant.

        Args:
            concept_ids: Liste des canonical_id des concepts
            tenant_id: Tenant ID
            min_salience: Salience minimum (0.0-1.0)
            max_per_concept: Max sections par concept

        Returns:
            Dict mapping concept_id → [context_id, ...]

        Example:
            >>> context_map = await engine.get_evidence_context_ids(
            ...     ["cc_abc123", "cc_def456"],
            ...     min_salience=0.3
            ... )
            >>> # {"cc_abc123": ["sec:doc1:hash1", "sec:doc1:hash2"], ...}
        """
        if not concept_ids:
            return {}

        cypher = """
        UNWIND $concept_ids AS cid
        MATCH (c:CanonicalConcept {canonical_id: cid, tenant_id: $tenant_id})
        MATCH (c)-[m:MENTIONED_IN]->(ctx:SectionContext)
        WHERE ctx.tenant_id = $tenant_id
          AND coalesce(m.weight, 0.0) >= $min_salience
        WITH cid, ctx.context_id AS context_id, m.weight AS salience
        ORDER BY salience DESC
        WITH cid, collect(context_id)[0..$max_per_concept] AS context_ids
        RETURN cid AS concept_id, context_ids
        """

        try:
            result = await self.neo4j_client.execute_read(
                cypher,
                {
                    "concept_ids": concept_ids,
                    "tenant_id": tenant_id,
                    "min_salience": min_salience,
                    "max_per_concept": max_per_concept,
                }
            )

            context_map = {}
            for record in result:
                concept_id = record.get("concept_id")
                context_ids = record.get("context_ids", [])
                if concept_id and context_ids:
                    context_map[concept_id] = context_ids

            total_contexts = sum(len(v) for v in context_map.values())
            logger.debug(
                f"[OSMOSE:Evidence] Retrieved {total_contexts} context_ids "
                f"for {len(context_map)} concepts"
            )

            return context_map

        except Exception as e:
            logger.warning(f"[OSMOSE:Evidence] Failed to get context_ids: {e}")
            return {}

    async def get_all_evidence_context_ids(
        self,
        concept_ids: List[str],
        tenant_id: str = "default",
        min_salience: float = 0.0
    ) -> List[str]:
        """
        Convenience method: récupère tous les context_id uniques pour une liste de concepts.

        Args:
            concept_ids: Liste des canonical_id
            tenant_id: Tenant ID
            min_salience: Salience minimum

        Returns:
            Liste unique de context_id (pour filtrage Qdrant)
        """
        context_map = await self.get_evidence_context_ids(
            concept_ids, tenant_id, min_salience
        )
        # Flatten et déduplique
        all_contexts = set()
        for contexts in context_map.values():
            all_contexts.update(contexts)
        return list(all_contexts)

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

        🌊 Phase 2.12: Le contexte respecte le profil de visibilité du tenant.

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

        # 🌊 Phase 2.12: Récupérer le profil de visibilité actif
        try:
            visibility_service = self.get_visibility_service(tenant_id)
            context.visibility_profile = visibility_service.get_profile_for_tenant(tenant_id)
        except Exception as e:
            logger.warning(f"[OSMOSE] Could not get visibility profile: {e}")
            context.visibility_profile = "balanced"

        if enrichment_level == EnrichmentLevel.NONE:
            return context

        # Étape 1: Extraire les concepts de la question (avec IDs et statut semantic)
        extraction_result = await self.extract_concepts_from_query_v2(
            query, tenant_id
        )

        context.query_concepts = extraction_result["names"]
        context.query_concept_ids = extraction_result["ids"]
        context.concept_semantic_status = extraction_result.get("semantic_status")

        if not context.query_concepts:
            logger.info(f"[OSMOSE] No concepts found in query: {query[:50]}...")
            context.processing_time_ms = (time.time() - start_time) * 1000
            return context

        # Log avec info semantic
        details = extraction_result.get("details", {})
        logger.info(
            f"[OSMOSE] Query concepts: {context.query_concepts} "
            f"(semantic={'ON' if details.get('semantic_available') else 'OFF'}, "
            f"sem_only={details.get('sem_only_count', 0)})"
        )

        # Étape 2: Concepts liés (tous niveaux sauf NONE)
        context.related_concepts = await self.get_related_concepts(
            context.query_concepts, tenant_id
        )


        # P3: Logging explicite des concepts isoles (avant fallback)
        concepts_with_rels = {r["source"] for r in context.related_concepts}
        isolated_before = [c for c in context.query_concepts if c not in concepts_with_rels]
        if isolated_before:
            logger.warning(
                f"[OSMOSE:ISOLATED] {len(isolated_before)} concepts sans relations: "
                f"{isolated_before}. Consider Entity Resolution."
            )

        # P1 Fallback: Enrichir avec variantes connectees si concepts isoles
        (
            context.query_concepts,
            context.related_concepts,
            context.fallback_mappings
        ) = await self.enrich_with_connected_variants(
            context.query_concepts, context.related_concepts, tenant_id
        )

        # P3: Log résumé après fallback
        if context.fallback_mappings:
            for mapping in context.fallback_mappings:
                logger.info(
                    f"[OSMOSE:FALLBACK] '{mapping['original']}' -> '{mapping['fallback']}' "
                    f"(sim={mapping['similarity']:.2f}, rels={mapping['relation_count']})"
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


# ============================================================================
# ADR_GRAPH_FIRST_ARCHITECTURE Phase A.4: GDS Pathfinding
# ============================================================================

class GDSSemanticGraph:
    """
    ADR_GRAPH_FIRST_ARCHITECTURE Phase A: Projection GDS pour pathfinding sémantique.

    Crée et gère une projection Graph Data Science du graphe sémantique
    pour découvrir les chemins entre concepts.

    Note: Nécessite le plugin GDS Community installé dans Neo4j.
    Voir docker-compose.infra.yml pour la configuration.
    """

    PROJECTION_NAME = "SemanticGraph"

    def __init__(self, neo4j_client=None):
        self._neo4j_client = neo4j_client
        self._projection_exists = False

    @property
    def neo4j_client(self):
        """Lazy loading du client Neo4j."""
        if self._neo4j_client is None:
            from knowbase.neo4j_custom.client import get_neo4j_client
            self._neo4j_client = get_neo4j_client()
        return self._neo4j_client

    async def check_gds_available(self) -> bool:
        """Vérifie si GDS est disponible."""
        try:
            result = self.neo4j_client.execute_query(
                "CALL gds.list() YIELD name RETURN count(name) AS count"
            )
            return True
        except Exception as e:
            logger.warning(f"[OSMOSE:GDS] GDS not available: {e}")
            return False

    async def create_projection(
        self,
        tenant_id: str = "default",
        force_recreate: bool = False
    ) -> bool:
        """
        Crée ou recrée la projection GDS SemanticGraph.

        Args:
            tenant_id: Tenant ID pour filtrer les concepts
            force_recreate: Si True, supprime et recrée la projection

        Returns:
            True si la projection a été créée/existe
        """
        projection_name = f"{self.PROJECTION_NAME}_{tenant_id}"

        # Vérifier si la projection existe déjà
        if not force_recreate:
            try:
                check_query = """
                CALL gds.graph.exists($name) YIELD exists
                RETURN exists
                """
                result = self.neo4j_client.execute_query(
                    check_query, {"name": projection_name}
                )
                if result and result[0].get("exists"):
                    logger.info(f"[OSMOSE:GDS] Projection {projection_name} already exists")
                    self._projection_exists = True
                    return True
            except Exception as e:
                logger.debug(f"[OSMOSE:GDS] Check failed: {e}")

        # Supprimer si existante et force_recreate
        if force_recreate:
            try:
                self.neo4j_client.execute_query(
                    "CALL gds.graph.drop($name, false)",
                    {"name": projection_name}
                )
                logger.info(f"[OSMOSE:GDS] Dropped existing projection {projection_name}")
            except Exception:
                pass  # Projection n'existait pas

        # Créer la projection avec les relations sémantiques
        # Configuration: nœuds CanonicalConcept, relations sémantiques (undirected pour pathfinding)
        relation_types_str = "|".join(SEMANTIC_RELATION_TYPES)

        create_query = f"""
        CALL gds.graph.project(
            $name,
            {{
                CanonicalConcept: {{
                    properties: ['quality_score']
                }}
            }},
            {{
                {', '.join(f'{rt}: {{orientation: "UNDIRECTED"}}' for rt in SEMANTIC_RELATION_TYPES)}
            }}
        )
        YIELD graphName, nodeCount, relationshipCount
        RETURN graphName, nodeCount, relationshipCount
        """

        try:
            result = self.neo4j_client.execute_query(
                create_query, {"name": projection_name}
            )

            if result:
                stats = result[0]
                logger.info(
                    f"[OSMOSE:GDS] Created projection {projection_name}: "
                    f"{stats.get('nodeCount', 0)} nodes, "
                    f"{stats.get('relationshipCount', 0)} relationships"
                )
                self._projection_exists = True
                return True

            return False

        except Exception as e:
            logger.error(f"[OSMOSE:GDS] Failed to create projection: {e}")
            return False

    async def find_shortest_path(
        self,
        source_concept_id: str,
        target_concept_id: str,
        tenant_id: str = "default",
        max_depth: int = 5
    ) -> Optional[Dict[str, Any]]:
        """
        Trouve le plus court chemin entre deux concepts via GDS.

        Args:
            source_concept_id: canonical_id du concept source
            target_concept_id: canonical_id du concept cible
            tenant_id: Tenant ID
            max_depth: Profondeur max du chemin

        Returns:
            Dict avec path, cost, nodes si trouvé, None sinon
        """
        projection_name = f"{self.PROJECTION_NAME}_{tenant_id}"

        # S'assurer que la projection existe
        if not self._projection_exists:
            await self.create_projection(tenant_id)

        # Utiliser Dijkstra pour le shortest path
        query = """
        MATCH (source:CanonicalConcept {canonical_id: $source_id, tenant_id: $tenant_id})
        MATCH (target:CanonicalConcept {canonical_id: $target_id, tenant_id: $tenant_id})
        CALL gds.shortestPath.dijkstra.stream($projection_name, {
            sourceNode: source,
            targetNode: target
        })
        YIELD index, sourceNode, targetNode, totalCost, nodeIds, costs, path
        WITH nodeIds, totalCost, [nodeId IN nodeIds |
            gds.util.asNode(nodeId).canonical_name
        ] AS nodeNames
        RETURN nodeNames AS path, totalCost AS cost, size(nodeNames) AS length
        """

        try:
            result = self.neo4j_client.execute_query(query, {
                "source_id": source_concept_id,
                "target_id": target_concept_id,
                "tenant_id": tenant_id,
                "projection_name": projection_name
            })

            if result:
                path_data = result[0]
                return {
                    "path": path_data.get("path", []),
                    "cost": path_data.get("cost", 0.0),
                    "length": path_data.get("length", 0),
                    "source": source_concept_id,
                    "target": target_concept_id
                }

            return None

        except Exception as e:
            logger.warning(f"[OSMOSE:GDS] Shortest path failed: {e}")
            return None

    async def find_all_paths(
        self,
        source_concept_id: str,
        target_concept_id: str,
        tenant_id: str = "default",
        max_depth: int = 4,
        max_paths: int = 5
    ) -> List[Dict[str, Any]]:
        """
        Trouve tous les chemins entre deux concepts (jusqu'à max_paths).

        Args:
            source_concept_id: canonical_id du concept source
            target_concept_id: canonical_id du concept cible
            tenant_id: Tenant ID
            max_depth: Profondeur max des chemins
            max_paths: Nombre max de chemins à retourner

        Returns:
            Liste de chemins avec path, relations, length
        """
        # Utiliser Cypher natif pour allShortestPaths (plus flexible que GDS pour multi-paths)
        relation_types = "|".join(SEMANTIC_RELATION_TYPES)

        query = f"""
        MATCH (source:CanonicalConcept {{canonical_id: $source_id, tenant_id: $tenant_id}})
        MATCH (target:CanonicalConcept {{canonical_id: $target_id, tenant_id: $tenant_id}})
        MATCH path = allShortestPaths((source)-[:{relation_types}*1..{max_depth}]-(target))
        WITH path,
             [node IN nodes(path) | node.canonical_name] AS node_names,
             [rel IN relationships(path) | type(rel)] AS rel_types,
             length(path) AS path_length
        ORDER BY path_length
        LIMIT $max_paths
        RETURN node_names AS path, rel_types AS relations, path_length AS length
        """

        try:
            result = self.neo4j_client.execute_query(query, {
                "source_id": source_concept_id,
                "target_id": target_concept_id,
                "tenant_id": tenant_id,
                "max_paths": max_paths
            })

            paths = []
            for record in result:
                paths.append({
                    "path": record.get("path", []),
                    "relations": record.get("relations", []),
                    "length": record.get("length", 0)
                })

            logger.debug(
                f"[OSMOSE:GDS] Found {len(paths)} paths between "
                f"{source_concept_id[:8]}... and {target_concept_id[:8]}..."
            )

            return paths

        except Exception as e:
            logger.warning(f"[OSMOSE:GDS] All paths failed: {e}")
            return []

    async def drop_projection(self, tenant_id: str = "default") -> bool:
        """Supprime la projection GDS."""
        projection_name = f"{self.PROJECTION_NAME}_{tenant_id}"

        try:
            self.neo4j_client.execute_query(
                "CALL gds.graph.drop($name)",
                {"name": projection_name}
            )
            self._projection_exists = False
            logger.info(f"[OSMOSE:GDS] Dropped projection {projection_name}")
            return True

        except Exception as e:
            logger.warning(f"[OSMOSE:GDS] Failed to drop projection: {e}")
            return False


# Singleton GDS instance
_gds_semantic_graph: Optional[GDSSemanticGraph] = None


def get_gds_semantic_graph() -> GDSSemanticGraph:
    """Retourne l'instance singleton du GDS SemanticGraph."""
    global _gds_semantic_graph
    if _gds_semantic_graph is None:
        _gds_semantic_graph = GDSSemanticGraph()
    return _gds_semantic_graph


__all__ = [
    "GraphGuidedSearchService",
    "GraphContext",
    "EnrichmentLevel",
    "get_graph_guided_service",
    # ADR_GRAPH_FIRST_ARCHITECTURE Phase A
    "GDSSemanticGraph",
    "get_gds_semantic_graph",
    "SEMANTIC_RELATION_TYPES",
    "NAVIGATION_RELATION_TYPES",
]
