"""
🌊 OSMOSE Semantic Intelligence - Inference Engine

Phase 2.3: Découverte de Connaissances Cachées (Hidden Knowledge Discovery)

Killer Feature: Découvrir des insights que l'utilisateur n'aurait jamais trouvés
par recherche traditionnelle RAG.

Types d'insights découvrables:
1. Transitive Inference - Relations implicites via chaînes (A→B→C donc A→C)
2. Bridge Concepts - Concepts qui connectent des clusters sinon isolés
3. Hidden Clusters - Communautés thématiques non évidentes
4. Weak Signals - Concepts émergents à faible fréquence mais fort potentiel
5. Structural Holes - Relations manquantes prédites par patterns KG
6. Contradictions - Assertions contradictoires entre documents

Architecture:
- Neo4j Cypher natif pour Transitive Inference
- NetworkX pour PageRank, Betweenness, Louvain (fallback si GDS indisponible)
- PyKEEN (optionnel) pour Link Prediction
- LLM (gpt-4o-mini) pour validation Contradictions

Phase 2.3 - Semaine 22+
"""

from typing import List, Dict, Any, Optional, Tuple, Set
from dataclasses import dataclass, field
from enum import Enum
from datetime import datetime
import logging
import asyncio
from collections import defaultdict

logger = logging.getLogger(__name__)

# NetworkX pour fallback (si Neo4j GDS indisponible)
try:
    import networkx as nx
    from networkx.algorithms import community as nx_community
    NETWORKX_AVAILABLE = True
except ImportError:
    NETWORKX_AVAILABLE = False
    logger.warning("[OSMOSE] NetworkX not available - graph algorithms disabled")

# NumPy pour calculs
try:
    import numpy as np
    NUMPY_AVAILABLE = True
except ImportError:
    NUMPY_AVAILABLE = False


class InsightType(str, Enum):
    """Types d'insights découvrables par l'InferenceEngine."""

    # Niveau 1: Cypher natif (pas de dépendance externe)
    TRANSITIVE_INFERENCE = "transitive_inference"  # A→B→C donc A→C

    # Niveau 2: NetworkX (fallback GDS)
    BRIDGE_CONCEPT = "bridge_concept"              # Concept qui connecte clusters isolés
    HIDDEN_CLUSTER = "hidden_cluster"              # Communauté thématique cachée
    WEAK_SIGNAL = "weak_signal"                    # Concept émergent low-frequency high-potential

    # Niveau 3: Avancé (PyKEEN, LLM)
    STRUCTURAL_HOLE = "structural_hole"            # Relation manquante prédite
    CONTRADICTION = "contradiction"                # Assertions contradictoires


@dataclass
class DiscoveredInsight:
    """Structure représentant un insight découvert."""

    insight_id: str
    insight_type: InsightType

    # Contenu
    title: str                          # Ex: "Relation implicite REQUIRES"
    description: str                    # Description détaillée
    concepts_involved: List[str]        # Concepts impliqués

    # Métriques
    confidence: float                   # 0-1
    importance: float                   # 0-1 (impact potentiel)

    # Evidence
    evidence_path: List[str] = field(default_factory=list)  # Chemin de raisonnement
    supporting_documents: List[str] = field(default_factory=list)  # Doc IDs

    # Metadata
    discovered_at: datetime = field(default_factory=datetime.utcnow)
    tenant_id: str = "default"

    def to_dict(self) -> Dict[str, Any]:
        """Convertit en dictionnaire pour sérialisation."""
        return {
            "insight_id": self.insight_id,
            "insight_type": self.insight_type.value,
            "title": self.title,
            "description": self.description,
            "concepts_involved": self.concepts_involved,
            "confidence": self.confidence,
            "importance": self.importance,
            "evidence_path": self.evidence_path,
            "supporting_documents": self.supporting_documents,
            "discovered_at": self.discovered_at.isoformat(),
            "tenant_id": self.tenant_id
        }


class InferenceEngine:
    """
    🌊 OSMOSE Inference Engine - Découverte de Connaissances Cachées

    Moteur principal pour découvrir des insights non triviaux dans le KG.

    Usage:
    ```python
    engine = InferenceEngine(neo4j_client)

    # Découvrir tous les insights
    insights = await engine.discover_all_insights(tenant_id="default")

    # Découvrir un type spécifique
    transitive = await engine.discover_transitive_relations(tenant_id="default")
    bridges = await engine.discover_bridge_concepts(tenant_id="default")
    clusters = await engine.discover_hidden_clusters(tenant_id="default")
    weak = await engine.discover_weak_signals(tenant_id="default")
    ```
    """

    # Seuils de confiance par type d'insight
    CONFIDENCE_THRESHOLDS = {
        InsightType.TRANSITIVE_INFERENCE: 0.6,
        InsightType.BRIDGE_CONCEPT: 0.5,
        InsightType.HIDDEN_CLUSTER: 0.4,
        InsightType.WEAK_SIGNAL: 0.3,
        InsightType.STRUCTURAL_HOLE: 0.5,
        InsightType.CONTRADICTION: 0.7,
    }

    def __init__(
        self,
        neo4j_client=None,
        llm_router=None,
        min_cluster_size: int = 3,
        max_transitive_depth: int = 3,
        weak_signal_threshold: float = 0.25,
    ):
        """
        Initialise l'InferenceEngine.

        Args:
            neo4j_client: Client Neo4j (lazy load si None)
            llm_router: LLMRouter pour validation LLM (lazy load si None)
            min_cluster_size: Taille min pour hidden clusters
            max_transitive_depth: Profondeur max chaînes transitives
            weak_signal_threshold: Seuil PageRank pour weak signals
        """
        self._neo4j_client = neo4j_client
        self._llm_router = llm_router
        self.min_cluster_size = min_cluster_size
        self.max_transitive_depth = max_transitive_depth
        self.weak_signal_threshold = weak_signal_threshold

        # Cache pour le graphe NetworkX (évite reconstruction répétée)
        self._nx_graph_cache: Optional[nx.DiGraph] = None
        self._cache_tenant_id: Optional[str] = None

        # Counter pour IDs uniques
        self._insight_counter = 0

        logger.info(f"[OSMOSE] InferenceEngine initialized (NetworkX: {NETWORKX_AVAILABLE})")

    @property
    def neo4j_client(self):
        """Lazy loading du client Neo4j."""
        if self._neo4j_client is None:
            from knowbase.neo4j_custom.client import get_neo4j_client
            self._neo4j_client = get_neo4j_client()
        return self._neo4j_client

    @property
    def llm_router(self):
        """Lazy loading du LLMRouter."""
        if self._llm_router is None:
            try:
                from knowbase.common.llm_router import LLMRouter
                self._llm_router = LLMRouter()
            except Exception as e:
                logger.warning(f"[OSMOSE] LLMRouter not available: {e}")
        return self._llm_router

    def _generate_insight_id(self, insight_type: InsightType) -> str:
        """Génère un ID unique pour un insight."""
        self._insight_counter += 1
        return f"insight_{insight_type.value[:4]}_{self._insight_counter:06d}"

    # =========================================================================
    # DISCOVER ALL - Point d'entrée principal
    # =========================================================================

    async def discover_all_insights(
        self,
        tenant_id: str = "default",
        insight_types: Optional[List[InsightType]] = None,
        max_insights_per_type: int = 50,
    ) -> List[DiscoveredInsight]:
        """
        Découvre tous les types d'insights dans le KG.

        Args:
            tenant_id: Tenant ID
            insight_types: Types à découvrir (None = tous)
            max_insights_per_type: Limite par type

        Returns:
            Liste de tous les insights découverts
        """
        if insight_types is None:
            insight_types = [
                InsightType.TRANSITIVE_INFERENCE,
                InsightType.BRIDGE_CONCEPT,
                InsightType.HIDDEN_CLUSTER,
                InsightType.WEAK_SIGNAL,
            ]

        all_insights: List[DiscoveredInsight] = []

        logger.info(f"[OSMOSE] Discovering insights for tenant={tenant_id}, types={[t.value for t in insight_types]}")

        # Exécuter chaque découverte
        for insight_type in insight_types:
            try:
                if insight_type == InsightType.TRANSITIVE_INFERENCE:
                    insights = await self.discover_transitive_relations(
                        tenant_id=tenant_id,
                        max_results=max_insights_per_type
                    )
                elif insight_type == InsightType.BRIDGE_CONCEPT:
                    insights = await self.discover_bridge_concepts(
                        tenant_id=tenant_id,
                        max_results=max_insights_per_type
                    )
                elif insight_type == InsightType.HIDDEN_CLUSTER:
                    insights = await self.discover_hidden_clusters(
                        tenant_id=tenant_id,
                        max_results=max_insights_per_type
                    )
                elif insight_type == InsightType.WEAK_SIGNAL:
                    insights = await self.discover_weak_signals(
                        tenant_id=tenant_id,
                        max_results=max_insights_per_type
                    )
                elif insight_type == InsightType.STRUCTURAL_HOLE:
                    insights = await self.discover_structural_holes(
                        tenant_id=tenant_id,
                        max_results=max_insights_per_type
                    )
                elif insight_type == InsightType.CONTRADICTION:
                    insights = await self.discover_contradictions(
                        tenant_id=tenant_id,
                        max_results=max_insights_per_type
                    )
                else:
                    insights = []

                all_insights.extend(insights)
                logger.info(f"[OSMOSE] {insight_type.value}: {len(insights)} insights discovered")

            except Exception as e:
                logger.error(f"[OSMOSE] Error discovering {insight_type.value}: {e}")

        # Trier par importance décroissante
        all_insights.sort(key=lambda x: x.importance, reverse=True)

        logger.info(f"[OSMOSE] Total insights discovered: {len(all_insights)}")
        return all_insights

    # =========================================================================
    # 1. TRANSITIVE INFERENCE (Cypher natif)
    # =========================================================================

    async def discover_transitive_relations(
        self,
        tenant_id: str = "default",
        relation_types: Optional[List[str]] = None,
        max_results: int = 50,
    ) -> List[DiscoveredInsight]:
        """
        Découvre des relations transitives implicites.

        Ex: Si A REQUIRES B et B REQUIRES C, alors A REQUIRES C (indirect)

        Relations transitives supportées:
        - REQUIRES (dépendances)
        - PART_OF (hiérarchies)
        - SUBTYPE_OF (taxonomies)

        Args:
            tenant_id: Tenant ID
            relation_types: Types de relations à analyser
            max_results: Limite résultats

        Returns:
            Liste d'insights transitifs
        """
        if relation_types is None:
            relation_types = ["REQUIRES", "PART_OF", "SUBTYPE_OF"]

        insights: List[DiscoveredInsight] = []

        for rel_type in relation_types:
            # Query Cypher pour trouver chaînes transitives qui n'ont pas de relation directe
            query = f"""
            MATCH (a:CanonicalConcept)-[r1:{rel_type}]->(b:CanonicalConcept)-[r2:{rel_type}]->(c:CanonicalConcept)
            WHERE a.tenant_id = $tenant_id
              AND NOT (a)-[:{rel_type}]->(c)
              AND a <> c
            WITH a, b, c, r1, r2,
                 (r1.confidence + r2.confidence) / 2.0 AS avg_confidence
            WHERE avg_confidence >= $min_confidence
            RETURN
                a.canonical_name AS source,
                b.canonical_name AS intermediate,
                c.canonical_name AS target,
                avg_confidence AS confidence,
                r1.confidence AS conf1,
                r2.confidence AS conf2
            ORDER BY avg_confidence DESC
            LIMIT $limit
            """

            try:
                records = self.neo4j_client.execute_query(
                    query,
                    parameters={
                        "tenant_id": tenant_id,
                        "min_confidence": self.CONFIDENCE_THRESHOLDS[InsightType.TRANSITIVE_INFERENCE],
                        "limit": max_results // len(relation_types)
                    }
                )

                for record in records:
                    insight = DiscoveredInsight(
                        insight_id=self._generate_insight_id(InsightType.TRANSITIVE_INFERENCE),
                        insight_type=InsightType.TRANSITIVE_INFERENCE,
                        title=f"Relation {rel_type} transitive découverte",
                        description=(
                            f"'{record['source']}' {rel_type.lower()} '{record['target']}' "
                            f"via '{record['intermediate']}'"
                        ),
                        concepts_involved=[record['source'], record['intermediate'], record['target']],
                        confidence=float(record['confidence']),
                        importance=self._calculate_transitive_importance(record),
                        evidence_path=[
                            f"{record['source']} → {record['intermediate']} (conf: {record['conf1']:.2f})",
                            f"{record['intermediate']} → {record['target']} (conf: {record['conf2']:.2f})"
                        ],
                        tenant_id=tenant_id
                    )
                    insights.append(insight)

            except Exception as e:
                logger.error(f"[OSMOSE] Transitive query failed for {rel_type}: {e}")

        return insights

    def _calculate_transitive_importance(self, record: Dict[str, Any]) -> float:
        """Calcule l'importance d'une relation transitive."""
        # Importance basée sur:
        # - Confidence des relations intermédiaires
        # - Longueur de la chaîne (plus court = plus important)
        base_importance = float(record['confidence'])

        # Bonus si les deux confidences sont élevées
        if record['conf1'] > 0.8 and record['conf2'] > 0.8:
            base_importance *= 1.2

        return min(1.0, base_importance)

    # =========================================================================
    # 2. BRIDGE CONCEPTS (Betweenness Centrality)
    # =========================================================================

    async def discover_bridge_concepts(
        self,
        tenant_id: str = "default",
        min_betweenness: float = 0.1,
        max_results: int = 20,
    ) -> List[DiscoveredInsight]:
        """
        Découvre les concepts "ponts" qui connectent des clusters sinon isolés.

        Utilise Betweenness Centrality: mesure combien de plus courts chemins
        passent par un nœud. Un score élevé = concept pont important.

        Args:
            tenant_id: Tenant ID
            min_betweenness: Seuil minimum de betweenness
            max_results: Limite résultats

        Returns:
            Liste de bridge concepts
        """
        if not NETWORKX_AVAILABLE:
            logger.warning("[OSMOSE] NetworkX not available, skipping bridge concept discovery")
            return []

        insights: List[DiscoveredInsight] = []

        # Construire graphe NetworkX
        G = await self._build_networkx_graph(tenant_id)

        if G.number_of_nodes() < 5:
            logger.info("[OSMOSE] Graph too small for bridge concept analysis")
            return []

        # Calculer betweenness centrality
        try:
            betweenness = nx.betweenness_centrality(G, normalized=True)
        except Exception as e:
            logger.error(f"[OSMOSE] Betweenness calculation failed: {e}")
            return []

        # Filtrer et trier par betweenness décroissant
        bridge_candidates = [
            (node, score) for node, score in betweenness.items()
            if score >= min_betweenness
        ]
        bridge_candidates.sort(key=lambda x: x[1], reverse=True)

        # Récupérer les clusters pour contexte
        communities = self._detect_communities(G)

        for node, score in bridge_candidates[:max_results]:
            # Trouver quels clusters ce concept connecte
            connected_clusters = self._find_connected_clusters(G, node, communities)

            if len(connected_clusters) >= 2:
                insight = DiscoveredInsight(
                    insight_id=self._generate_insight_id(InsightType.BRIDGE_CONCEPT),
                    insight_type=InsightType.BRIDGE_CONCEPT,
                    title=f"Concept pont: {node}",
                    description=(
                        f"'{node}' connecte {len(connected_clusters)} clusters thématiques. "
                        f"Score betweenness: {score:.3f}"
                    ),
                    concepts_involved=[node],
                    confidence=min(score * 2, 1.0),  # Normaliser score
                    importance=score,
                    evidence_path=[
                        f"Connecte clusters: {', '.join(str(c) for c in connected_clusters[:5])}"
                    ],
                    tenant_id=tenant_id
                )
                insights.append(insight)

        return insights

    # =========================================================================
    # 3. HIDDEN CLUSTERS (Louvain Community Detection)
    # =========================================================================

    async def discover_hidden_clusters(
        self,
        tenant_id: str = "default",
        max_results: int = 10,
    ) -> List[DiscoveredInsight]:
        """
        Découvre des communautés thématiques cachées dans le KG.

        Utilise l'algorithme Louvain pour détecter des groupes de concepts
        fortement interconnectés (communautés).

        Args:
            tenant_id: Tenant ID
            max_results: Limite résultats

        Returns:
            Liste de hidden clusters
        """
        if not NETWORKX_AVAILABLE:
            logger.warning("[OSMOSE] NetworkX not available, skipping cluster discovery")
            return []

        insights: List[DiscoveredInsight] = []

        # Construire graphe NetworkX
        G = await self._build_networkx_graph(tenant_id)

        if G.number_of_nodes() < self.min_cluster_size * 2:
            logger.info("[OSMOSE] Graph too small for cluster analysis")
            return []

        # Détecter communautés
        communities = self._detect_communities(G)

        # Filtrer clusters significatifs
        significant_clusters = [
            (cluster_id, members) for cluster_id, members in communities.items()
            if len(members) >= self.min_cluster_size
        ]

        # Trier par taille décroissante
        significant_clusters.sort(key=lambda x: len(x[1]), reverse=True)

        for cluster_id, members in significant_clusters[:max_results]:
            # Analyser le cluster
            cluster_theme = self._infer_cluster_theme(members, G)
            modularity = self._calculate_cluster_modularity(G, members)

            insight = DiscoveredInsight(
                insight_id=self._generate_insight_id(InsightType.HIDDEN_CLUSTER),
                insight_type=InsightType.HIDDEN_CLUSTER,
                title=f"Cluster thématique: {cluster_theme}",
                description=(
                    f"Groupe de {len(members)} concepts fortement interconnectés. "
                    f"Modularité: {modularity:.3f}"
                ),
                concepts_involved=list(members)[:20],  # Limiter affichage
                confidence=modularity,
                importance=len(members) / G.number_of_nodes(),  # Relative size
                evidence_path=[
                    f"Thème inféré: {cluster_theme}",
                    f"Taille: {len(members)} concepts",
                    f"Modularité locale: {modularity:.3f}"
                ],
                tenant_id=tenant_id
            )
            insights.append(insight)

        return insights

    def _detect_communities(self, G: "nx.Graph") -> Dict[int, Set[str]]:
        """Détecte les communautés avec Louvain."""
        if not NETWORKX_AVAILABLE:
            return {}

        try:
            # Utiliser l'algorithme de Louvain via greedy modularity
            communities_generator = nx_community.greedy_modularity_communities(G.to_undirected())

            communities = {}
            for i, community in enumerate(communities_generator):
                communities[i] = set(community)

            return communities

        except Exception as e:
            logger.error(f"[OSMOSE] Community detection failed: {e}")
            return {}

    def _infer_cluster_theme(self, members: Set[str], G: "nx.Graph") -> str:
        """Infère le thème d'un cluster à partir de ses membres."""
        # Trouver le concept le plus central dans le cluster
        subgraph = G.subgraph(members)

        if subgraph.number_of_nodes() == 0:
            return "Cluster inconnu"

        try:
            # PageRank local pour trouver le concept central
            pagerank = nx.pagerank(subgraph, max_iter=50)
            central_concept = max(pagerank, key=pagerank.get)
            return central_concept
        except:
            # Fallback: premier membre
            return list(members)[0] if members else "Cluster inconnu"

    def _calculate_cluster_modularity(self, G: "nx.Graph", members: Set[str]) -> float:
        """Calcule la modularité locale d'un cluster."""
        if not members or G.number_of_edges() == 0:
            return 0.0

        # Compter edges internes vs externes
        internal_edges = 0
        external_edges = 0

        for node in members:
            if node not in G:
                continue
            for neighbor in G.neighbors(node):
                if neighbor in members:
                    internal_edges += 1
                else:
                    external_edges += 1

        total_edges = internal_edges + external_edges
        if total_edges == 0:
            return 0.0

        return internal_edges / total_edges

    def _find_connected_clusters(
        self,
        G: "nx.Graph",
        node: str,
        communities: Dict[int, Set[str]]
    ) -> List[int]:
        """Trouve les clusters qu'un nœud connecte."""
        connected = set()

        if node not in G:
            return []

        for neighbor in G.neighbors(node):
            for cluster_id, members in communities.items():
                if neighbor in members:
                    connected.add(cluster_id)

        return list(connected)

    # =========================================================================
    # 4. WEAK SIGNALS (PageRank + Frequency)
    # =========================================================================

    async def discover_weak_signals(
        self,
        tenant_id: str = "default",
        max_results: int = 20,
    ) -> List[DiscoveredInsight]:
        """
        Découvre des concepts émergents (weak signals).

        Weak Signal = Concept avec:
        - Faible fréquence de mention (peu de documents sources)
        - MAIS PageRank élevé (bien connecté dans le graphe)

        Ces concepts sont potentiellement importants mais sous-représentés.

        Args:
            tenant_id: Tenant ID
            max_results: Limite résultats

        Returns:
            Liste de weak signals
        """
        if not NETWORKX_AVAILABLE:
            logger.warning("[OSMOSE] NetworkX not available, skipping weak signal discovery")
            return []

        insights: List[DiscoveredInsight] = []

        # Construire graphe NetworkX
        G = await self._build_networkx_graph(tenant_id)

        if G.number_of_nodes() < 10:
            logger.info("[OSMOSE] Graph too small for weak signal analysis")
            return []

        # Calculer PageRank avec tolérance plus élevée pour convergence
        try:
            pagerank = nx.pagerank(G, alpha=0.85, max_iter=200, tol=1e-4)
        except Exception as e:
            # Fallback: utiliser degree centrality si PageRank échoue
            logger.warning(f"[OSMOSE] PageRank failed, using degree centrality: {e}")
            try:
                # Degree centrality comme proxy
                pagerank = nx.degree_centrality(G)
            except Exception as e2:
                logger.error(f"[OSMOSE] Degree centrality also failed: {e2}")
                return []

        # Récupérer fréquences depuis Neo4j
        # Note: 'support' peut ne pas exister, on utilise le degree du graphe comme fallback
        query = """
        MATCH (c:CanonicalConcept)
        WHERE c.tenant_id = $tenant_id
        OPTIONAL MATCH (c)-[r]-()
        WITH c, count(r) AS degree
        RETURN c.canonical_name AS name, degree
        """

        try:
            records = self.neo4j_client.execute_query(
                query,
                parameters={"tenant_id": tenant_id}
            )
            # Utiliser le degré comme proxy de "support" (fréquence de mention)
            support_map = {r['name']: max(r.get('degree', 1), 1) for r in records}
        except Exception as e:
            logger.error(f"[OSMOSE] Frequency query failed: {e}")
            # Fallback: utiliser le degree du graphe NetworkX
            support_map = {node: max(G.degree(node), 1) for node in G.nodes()}

        # Calculer statistiques pour normalisation
        if not support_map:
            return []

        supports = list(support_map.values())
        mean_support = sum(supports) / len(supports)

        pageranks = list(pagerank.values())
        mean_pagerank = sum(pageranks) / len(pageranks)

        # Identifier weak signals: low support, high pagerank
        weak_signal_candidates = []

        for node, pr_score in pagerank.items():
            support = support_map.get(node, 1)

            # Weak signal: support < moyenne ET pagerank > moyenne
            if support < mean_support and pr_score > mean_pagerank:
                # Score = ratio pagerank/support (plus élevé = plus "weak signal")
                signal_strength = pr_score / (support / mean_support)
                weak_signal_candidates.append((node, pr_score, support, signal_strength))

        # Trier par signal strength
        weak_signal_candidates.sort(key=lambda x: x[3], reverse=True)

        for node, pr_score, support, signal_strength in weak_signal_candidates[:max_results]:
            insight = DiscoveredInsight(
                insight_id=self._generate_insight_id(InsightType.WEAK_SIGNAL),
                insight_type=InsightType.WEAK_SIGNAL,
                title=f"Signal émergent: {node}",
                description=(
                    f"'{node}' a une faible fréquence ({support} mentions) "
                    f"mais un PageRank élevé ({pr_score:.4f}). "
                    f"Concept potentiellement sous-exploré."
                ),
                concepts_involved=[node],
                confidence=min(signal_strength / 10, 1.0),
                importance=pr_score,
                evidence_path=[
                    f"Support: {support} (moyenne: {mean_support:.1f})",
                    f"PageRank: {pr_score:.4f} (moyenne: {mean_pagerank:.4f})",
                    f"Signal strength: {signal_strength:.2f}"
                ],
                tenant_id=tenant_id
            )
            insights.append(insight)

        return insights

    # =========================================================================
    # 5. STRUCTURAL HOLES (Link Prediction - Future)
    # =========================================================================

    async def discover_structural_holes(
        self,
        tenant_id: str = "default",
        max_results: int = 20,
    ) -> List[DiscoveredInsight]:
        """
        Découvre des relations manquantes prédites par les patterns du KG.

        Utilise des heuristiques de link prediction:
        - Common Neighbors
        - Jaccard Coefficient
        - Adamic-Adar Index

        PyKEEN (KG Embeddings) peut être utilisé pour des prédictions plus avancées.

        Args:
            tenant_id: Tenant ID
            max_results: Limite résultats

        Returns:
            Liste de structural holes
        """
        if not NETWORKX_AVAILABLE:
            logger.warning("[OSMOSE] NetworkX not available, skipping structural hole discovery")
            return []

        insights: List[DiscoveredInsight] = []

        # Construire graphe NetworkX
        G = await self._build_networkx_graph(tenant_id)

        if G.number_of_nodes() < 10:
            return []

        # Utiliser Adamic-Adar pour prédire les liens manquants
        # (fonctionne sur graphe non-dirigé)
        G_undirected = G.to_undirected()

        # Trouver paires non connectées avec score élevé
        predictions = []
        nodes = list(G_undirected.nodes())

        # Limiter pour performance
        sample_size = min(len(nodes), 100)
        sampled_nodes = nodes[:sample_size]

        for i, u in enumerate(sampled_nodes):
            for v in sampled_nodes[i+1:]:
                if not G_undirected.has_edge(u, v):
                    # Calculer Adamic-Adar
                    try:
                        aa_score = self._adamic_adar_score(G_undirected, u, v)
                        if aa_score > 0.5:  # Seuil minimal
                            predictions.append((u, v, aa_score))
                    except:
                        pass

        # Trier par score
        predictions.sort(key=lambda x: x[2], reverse=True)

        for u, v, score in predictions[:max_results]:
            # Trouver les voisins communs pour expliquer
            common = set(G_undirected.neighbors(u)) & set(G_undirected.neighbors(v))

            insight = DiscoveredInsight(
                insight_id=self._generate_insight_id(InsightType.STRUCTURAL_HOLE),
                insight_type=InsightType.STRUCTURAL_HOLE,
                title=f"Relation potentielle: {u} ↔ {v}",
                description=(
                    f"Une relation entre '{u}' et '{v}' est prédite avec un score "
                    f"Adamic-Adar de {score:.3f}. {len(common)} voisins communs."
                ),
                concepts_involved=[u, v],
                confidence=min(score / 5, 1.0),
                importance=score / 10,
                evidence_path=[
                    f"Score Adamic-Adar: {score:.3f}",
                    f"Voisins communs: {', '.join(list(common)[:5])}"
                ],
                tenant_id=tenant_id
            )
            insights.append(insight)

        return insights

    def _adamic_adar_score(self, G: "nx.Graph", u: str, v: str) -> float:
        """Calcule le score Adamic-Adar entre deux nœuds."""
        common_neighbors = set(G.neighbors(u)) & set(G.neighbors(v))

        score = 0.0
        for w in common_neighbors:
            degree = G.degree(w)
            if degree > 1:
                score += 1.0 / np.log(degree)

        return score

    # =========================================================================
    # 6. CONTRADICTIONS (LLM-based - Future)
    # =========================================================================

    async def discover_contradictions(
        self,
        tenant_id: str = "default",
        max_results: int = 10,
    ) -> List[DiscoveredInsight]:
        """
        Découvre des contradictions potentielles entre documents.

        Recherche des paires de concepts avec:
        - Relations contradictoires (A REPLACES B ET B REPLACES A)
        - Définitions conflictuelles

        Utilise LLM pour validation fine des contradictions.

        Args:
            tenant_id: Tenant ID
            max_results: Limite résultats

        Returns:
            Liste de contradictions
        """
        insights: List[DiscoveredInsight] = []

        # 1. Chercher contradictions structurelles (Cypher)
        query = """
        // Relations contradictoires: A→B et B→A pour REPLACES/DEPRECATES
        MATCH (a:CanonicalConcept)-[r1:REPLACES]->(b:CanonicalConcept),
              (b)-[r2:REPLACES]->(a)
        WHERE a.tenant_id = $tenant_id
        RETURN a.canonical_name AS concept_a,
               b.canonical_name AS concept_b,
               'REPLACES_MUTUAL' AS contradiction_type
        LIMIT $limit
        """

        try:
            records = self.neo4j_client.execute_query(
                query,
                parameters={"tenant_id": tenant_id, "limit": max_results}
            )

            for record in records:
                insight = DiscoveredInsight(
                    insight_id=self._generate_insight_id(InsightType.CONTRADICTION),
                    insight_type=InsightType.CONTRADICTION,
                    title=f"Contradiction: {record['concept_a']} ↔ {record['concept_b']}",
                    description=(
                        f"Contradiction détectée: '{record['concept_a']}' et "
                        f"'{record['concept_b']}' ont chacun une relation REPLACES "
                        f"vers l'autre, ce qui est logiquement incohérent."
                    ),
                    concepts_involved=[record['concept_a'], record['concept_b']],
                    confidence=0.9,
                    importance=0.8,
                    evidence_path=[
                        f"{record['concept_a']} REPLACES {record['concept_b']}",
                        f"{record['concept_b']} REPLACES {record['concept_a']}",
                        "Ces deux assertions sont mutuellement contradictoires"
                    ],
                    tenant_id=tenant_id
                )
                insights.append(insight)

        except Exception as e:
            logger.error(f"[OSMOSE] Contradiction query failed: {e}")

        return insights

    # =========================================================================
    # HELPERS - Construction Graphe NetworkX
    # =========================================================================

    async def _build_networkx_graph(self, tenant_id: str) -> "nx.DiGraph":
        """
        Construit un graphe NetworkX depuis Neo4j pour analyses.

        Cache le graphe pour éviter reconstructions répétées.
        """
        # Vérifier cache
        if (self._nx_graph_cache is not None and
            self._cache_tenant_id == tenant_id):
            return self._nx_graph_cache

        if not NETWORKX_AVAILABLE:
            return nx.DiGraph()

        G = nx.DiGraph()

        # Récupérer tous les concepts
        query_nodes = """
        MATCH (c:CanonicalConcept)
        WHERE c.tenant_id = $tenant_id
        RETURN c.canonical_name AS name, c.concept_type AS type, c.support AS support
        """

        # Récupérer toutes les relations
        query_edges = """
        MATCH (a:CanonicalConcept)-[r]->(b:CanonicalConcept)
        WHERE a.tenant_id = $tenant_id AND b.tenant_id = $tenant_id
        RETURN a.canonical_name AS source,
               b.canonical_name AS target,
               type(r) AS relation_type,
               r.confidence AS confidence
        """

        try:
            # Ajouter nœuds
            nodes = self.neo4j_client.execute_query(
                query_nodes,
                parameters={"tenant_id": tenant_id}
            )

            for node in nodes:
                G.add_node(
                    node['name'],
                    type=node.get('type', 'unknown'),
                    support=node.get('support', 1)
                )

            # Ajouter edges
            edges = self.neo4j_client.execute_query(
                query_edges,
                parameters={"tenant_id": tenant_id}
            )

            for edge in edges:
                G.add_edge(
                    edge['source'],
                    edge['target'],
                    relation_type=edge.get('relation_type', 'RELATED_TO'),
                    weight=edge.get('confidence', 0.5)
                )

            logger.info(
                f"[OSMOSE] NetworkX graph built: {G.number_of_nodes()} nodes, "
                f"{G.number_of_edges()} edges"
            )

        except Exception as e:
            logger.error(f"[OSMOSE] Failed to build NetworkX graph: {e}")

        # Mettre en cache
        self._nx_graph_cache = G
        self._cache_tenant_id = tenant_id

        return G

    def clear_cache(self):
        """Vide le cache du graphe NetworkX."""
        self._nx_graph_cache = None
        self._cache_tenant_id = None
        logger.info("[OSMOSE] NetworkX graph cache cleared")

    # =========================================================================
    # STATS & REPORTING
    # =========================================================================

    async def get_inference_stats(self, tenant_id: str = "default") -> Dict[str, Any]:
        """
        Retourne des statistiques sur le potentiel d'inférence du KG.

        Args:
            tenant_id: Tenant ID

        Returns:
            Dict avec statistiques
        """
        G = await self._build_networkx_graph(tenant_id)

        stats = {
            "tenant_id": tenant_id,
            "graph_stats": {
                "nodes": G.number_of_nodes(),
                "edges": G.number_of_edges(),
                "density": nx.density(G) if G.number_of_nodes() > 0 else 0,
            },
            "networkx_available": NETWORKX_AVAILABLE,
            "potential_insights": {}
        }

        if NETWORKX_AVAILABLE and G.number_of_nodes() > 5:
            # Estimer potentiel d'insights
            communities = self._detect_communities(G)
            stats["potential_insights"] = {
                "communities_detected": len(communities),
                "avg_community_size": sum(len(c) for c in communities.values()) / len(communities) if communities else 0,
            }

        return stats
