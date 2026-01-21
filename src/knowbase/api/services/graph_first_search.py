"""
ADR_GRAPH_FIRST_ARCHITECTURE Phase C - Graph-First Search Service

Runtime Graph-First avec 3 modes:
- REASONED: Paths sémantiques trouvés → Evidence via arêtes du chemin
- ANCHORED: Pas de paths mais routing structural (HAS_TOPIC/COVERS)
- TEXT_ONLY: Fallback Qdrant classique

Pipeline:
1. extract_concepts_from_query_v2() → seed_concepts[]
2. Graph path search (GDS Yen k-shortest entre paires de seeds)
3. Mode decision: paths → Reasoned, structural → Anchored, else → Text-only
4. Qdrant search filtré par context_id du plan
5. Synthèse avec audit trail
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Set

from knowbase.common.logging import setup_logging
from knowbase.config.settings import get_settings
from knowbase.relations.types import DefensibilityTier, SemanticGrade

# Phase D - Tier Filtering
from .tier_filter import (
    TraversalPolicy,
    TierFilterConfig,
    TierFilterService,
    EscalationResult,
    get_tier_filter_service,
    validate_path_semantic_integrity,
    compute_path_tier,
)

settings = get_settings()
logger = setup_logging(settings.logs_dir, "graph_first_search.log")


class SearchMode(str, Enum):
    """Mode de recherche déterminé par le graphe."""
    REASONED = "reasoned"      # Paths sémantiques trouvés avec evidence
    ANCHORED = "anchored"      # Routing structural via Topics/COVERS
    TEXT_ONLY = "text_only"    # Fallback Qdrant classique


@dataclass
class SemanticPath:
    """Un chemin sémantique entre deux concepts."""
    nodes: List[str]               # canonical_names des concepts du chemin
    node_ids: List[str]            # canonical_ids
    relations: List[str]           # Types de relations (REQUIRES, ENABLES, etc.)
    confidence: float              # Produit des confiances des arêtes
    length: int                    # Nombre de hops
    evidence_context_ids: List[str] = field(default_factory=list)  # IDs pour filtrage Qdrant

    # Phase D - Tier information
    edge_tiers: List[DefensibilityTier] = field(default_factory=list)
    edge_grades: List[SemanticGrade] = field(default_factory=list)
    path_tier: DefensibilityTier = DefensibilityTier.STRICT
    semantic_integrity_warning: Optional[str] = None


@dataclass
class StructuralRoute:
    """Route structurelle via Topics/COVERS."""
    topic_name: str
    topic_id: str
    covered_concept_ids: List[str]
    document_ids: List[str]
    context_ids: List[str]


@dataclass
class GraphFirstPlan:
    """Plan de recherche généré par le graphe."""
    mode: SearchMode
    seed_concepts: List[str]           # Concepts extraits de la question
    seed_concept_ids: List[str]        # IDs correspondants

    # Mode REASONED
    paths: List[SemanticPath] = field(default_factory=list)
    path_evidence_context_ids: List[str] = field(default_factory=list)

    # Mode ANCHORED
    structural_routes: List[StructuralRoute] = field(default_factory=list)
    structural_context_ids: List[str] = field(default_factory=list)

    # Métadonnées
    processing_time_ms: float = 0.0
    fallback_reason: Optional[str] = None

    # Phase D - Tier filtering audit trail
    tier_policy: Optional[TraversalPolicy] = None
    allowed_tiers: Set[DefensibilityTier] = field(default_factory=lambda: {DefensibilityTier.STRICT})
    escalation_result: Optional[EscalationResult] = None

    def get_context_ids_for_qdrant(self) -> List[str]:
        """Retourne les context_ids à utiliser pour filtrer Qdrant."""
        if self.mode == SearchMode.REASONED:
            return self.path_evidence_context_ids
        elif self.mode == SearchMode.ANCHORED:
            return self.structural_context_ids
        return []  # TEXT_ONLY: pas de filtrage

    def to_dict(self) -> Dict[str, Any]:
        """Sérialisation pour la réponse API."""
        result = {
            "mode": self.mode.value,
            "seed_concepts": self.seed_concepts,
            "seed_concept_ids": self.seed_concept_ids,
            "paths": [
                {
                    "nodes": p.nodes,
                    "relations": p.relations,
                    "confidence": p.confidence,
                    "length": p.length,
                    "evidence_count": len(p.evidence_context_ids),
                    "path_tier": p.path_tier.value if p.path_tier else None,
                    "semantic_integrity_warning": p.semantic_integrity_warning,
                }
                for p in self.paths
            ],
            "structural_routes": [
                {
                    "topic": r.topic_name,
                    "covered_concepts": len(r.covered_concept_ids),
                    "documents": len(r.document_ids),
                }
                for r in self.structural_routes
            ],
            "context_ids_count": len(self.get_context_ids_for_qdrant()),
            "processing_time_ms": self.processing_time_ms,
            "fallback_reason": self.fallback_reason,
        }

        # Phase D - Tier filtering audit
        if self.tier_policy:
            result["tier_policy"] = self.tier_policy.value
        result["allowed_tiers"] = [t.value for t in self.allowed_tiers]
        if self.escalation_result:
            result["escalation_audit"] = self.escalation_result.to_audit_trail()

        return result


class GraphFirstSearchService:
    """
    ADR_GRAPH_FIRST_ARCHITECTURE Phase C - Service de recherche Graph-First.

    Différence avec GraphGuidedSearchService:
    - GraphGuided: Retrieval-first enrichi par KG (actuel)
    - GraphFirst: Graph-first avec evidence plan (cette implémentation)

    Le graphe détermine le MODE et le PLAN de recherche,
    pas juste un enrichissement post-retrieval.
    """

    # Configuration
    MIN_PATH_CONFIDENCE = 0.3      # Confiance minimum pour un chemin
    MAX_PATH_HOPS = 3              # Profondeur max des chemins
    MAX_PATHS = 5                  # Nombre max de chemins
    MIN_SEED_CONCEPTS = 1          # Minimum seeds pour tenter pathfinding
    MAX_SEED_PAIRS = 10            # Max paires de seeds à explorer

    def __init__(
        self,
        tenant_id: str = "default",
        tier_policy: TraversalPolicy = TraversalPolicy.STRICT,
    ):
        self.tenant_id = tenant_id
        self.tier_policy = tier_policy
        self._tier_filter = get_tier_filter_service(policy=tier_policy)
        self._neo4j_client = None
        self._qdrant_client = None
        self._concept_service = None
        self._gds_graph = None

    @property
    def neo4j_client(self):
        """Lazy loading du client Neo4j."""
        if self._neo4j_client is None:
            from knowbase.neo4j_custom.client import get_neo4j_client
            self._neo4j_client = get_neo4j_client()
        return self._neo4j_client

    @property
    def qdrant_client(self):
        """Lazy loading du client Qdrant."""
        if self._qdrant_client is None:
            from knowbase.common.clients.qdrant_client import get_qdrant_client
            self._qdrant_client = get_qdrant_client()
        return self._qdrant_client

    @property
    def concept_service(self):
        """Lazy loading du service d'extraction de concepts."""
        if self._concept_service is None:
            from .graph_guided_search import get_graph_guided_service
            self._concept_service = get_graph_guided_service()
        return self._concept_service

    @property
    def gds_graph(self):
        """Lazy loading du GDS SemanticGraph."""
        if self._gds_graph is None:
            from .graph_guided_search import get_gds_semantic_graph
            self._gds_graph = get_gds_semantic_graph()
        return self._gds_graph

    async def build_search_plan(
        self,
        query: str,
        tier_policy: Optional[TraversalPolicy] = None,
    ) -> GraphFirstPlan:
        """
        Construit le plan de recherche Graph-First.

        Détermine le mode (REASONED/ANCHORED/TEXT_ONLY) et prépare
        les context_ids pour le filtrage Qdrant.

        Phase D: Applique le filtrage par DefensibilityTier avec escalade.

        Args:
            query: Question de l'utilisateur
            tier_policy: Policy de traversée (override la policy par défaut)

        Returns:
            GraphFirstPlan avec mode et context_ids
        """
        start_time = time.time()

        # Phase D: Déterminer la policy de filtrage
        effective_policy = tier_policy or self.tier_policy
        tier_filter = get_tier_filter_service(policy=effective_policy)
        escalation = tier_filter.create_escalation_result()

        # Étape 1: Extraire les concepts seeds de la question
        extraction_result = await self.concept_service.extract_concepts_from_query_v2(
            query=query,
            tenant_id=self.tenant_id,
            top_k=10,
            use_semantic=True,
        )

        seed_concepts = extraction_result.get("names", [])
        seed_concept_ids = extraction_result.get("ids", [])

        if not seed_concepts:
            # Pas de concepts trouvés → TEXT_ONLY immédiat
            escalation.final_mode = "TEXT_ONLY"
            return GraphFirstPlan(
                mode=SearchMode.TEXT_ONLY,
                seed_concepts=[],
                seed_concept_ids=[],
                processing_time_ms=(time.time() - start_time) * 1000,
                fallback_reason="No concepts found in query",
                tier_policy=effective_policy,
                allowed_tiers=escalation.current_tiers,
                escalation_result=escalation,
            )

        logger.info(f"[GRAPH-FIRST] Seeds: {seed_concepts[:5]}...")

        # Étape 2: Tenter le mode REASONED avec escalade de tiers
        paths: List[SemanticPath] = []

        if len(seed_concept_ids) >= self.MIN_SEED_CONCEPTS:
            # Boucle d'escalade
            while True:
                paths = await self._find_semantic_paths(
                    seed_concept_ids,
                    allowed_tiers=escalation.current_tiers,
                )

                if paths:
                    escalation.found_results = True
                    break

                # Tenter l'escalade
                if tier_filter.should_escalate(len(paths), escalation.escalation_step):
                    next_tier = tier_filter.get_next_escalation_tier(escalation.current_tiers)
                    if next_tier:
                        logger.info(
                            f"[GRAPH-FIRST:ESCALADE] Step {escalation.escalation_step + 1}: "
                            f"Adding {next_tier.value}"
                        )
                        escalation.add_escalation(next_tier)
                        continue

                # Pas d'escalade possible
                break

        if paths:
            # Mode REASONED: on a trouvé des chemins sémantiques
            all_evidence_ids = set()
            for path in paths:
                all_evidence_ids.update(path.evidence_context_ids)

            logger.info(
                f"[GRAPH-FIRST] REASONED mode: {len(paths)} paths, "
                f"{len(all_evidence_ids)} evidence contexts, "
                f"tiers={[t.value for t in escalation.current_tiers]}"
            )

            escalation.final_mode = "REASONED"
            return GraphFirstPlan(
                mode=SearchMode.REASONED,
                seed_concepts=seed_concepts,
                seed_concept_ids=seed_concept_ids,
                paths=paths,
                path_evidence_context_ids=list(all_evidence_ids),
                processing_time_ms=(time.time() - start_time) * 1000,
                tier_policy=effective_policy,
                allowed_tiers=escalation.current_tiers,
                escalation_result=escalation,
            )

        # Étape 3: Tenter le mode ANCHORED (si fallback autorisé)
        if tier_filter.should_fallback_to_anchored(escalation) or not tier_filter.config.enable_escalation:
            routes = await self._find_structural_routes(seed_concept_ids)

            if routes:
                all_context_ids = set()
                for route in routes:
                    all_context_ids.update(route.context_ids)

                logger.info(
                    f"[GRAPH-FIRST] ANCHORED mode: {len(routes)} routes, "
                    f"{len(all_context_ids)} structural contexts"
                )

                escalation.final_mode = "ANCHORED"
                escalation.escalation_path.append("fallback_anchored")
                return GraphFirstPlan(
                    mode=SearchMode.ANCHORED,
                    seed_concepts=seed_concepts,
                    seed_concept_ids=seed_concept_ids,
                    structural_routes=routes,
                    structural_context_ids=list(all_context_ids),
                    processing_time_ms=(time.time() - start_time) * 1000,
                    tier_policy=effective_policy,
                    allowed_tiers=escalation.current_tiers,
                    escalation_result=escalation,
                )

        # Étape 4: Fallback TEXT_ONLY
        logger.info("[GRAPH-FIRST] TEXT_ONLY mode: no paths or routes found")

        escalation.final_mode = "TEXT_ONLY"
        return GraphFirstPlan(
            mode=SearchMode.TEXT_ONLY,
            seed_concepts=seed_concepts,
            seed_concept_ids=seed_concept_ids,
            processing_time_ms=(time.time() - start_time) * 1000,
            fallback_reason="No semantic paths or structural routes found",
            tier_policy=effective_policy,
            allowed_tiers=escalation.current_tiers,
            escalation_result=escalation,
        )

    async def _find_semantic_paths(
        self,
        concept_ids: List[str],
        allowed_tiers: Optional[Set[DefensibilityTier]] = None,
    ) -> List[SemanticPath]:
        """
        Trouve les chemins sémantiques entre paires de concepts.

        Stratégie (ADR_GRAPH_FIRST_ARCHITECTURE):
        1. Tenter GDS Yen k-shortest paths (si projection existe)
        2. Fallback sur Cypher natif allShortestPaths

        Phase D: Filtre par DefensibilityTier sur les arêtes.

        Args:
            concept_ids: IDs des concepts seeds
            allowed_tiers: Tiers autorisés pour la traversée
        """
        if len(concept_ids) < 2:
            return []

        # Utiliser les tiers par défaut si non spécifiés
        if allowed_tiers is None:
            allowed_tiers = {DefensibilityTier.STRICT}

        # Générer les paires de concepts à explorer
        pairs = []
        for i, src_id in enumerate(concept_ids):
            for tgt_id in concept_ids[i+1:]:
                pairs.append((src_id, tgt_id))
                if len(pairs) >= self.MAX_SEED_PAIRS:
                    break
            if len(pairs) >= self.MAX_SEED_PAIRS:
                break

        all_paths = []

        # Note: GDS ne supporte pas le filtrage par propriété de relation
        # On utilise directement Cypher avec filtrage tier
        for src_id, tgt_id in pairs:
            paths = await self._cypher_all_paths(src_id, tgt_id, allowed_tiers)
            all_paths.extend(paths)

        # Trier par confiance et limiter
        all_paths.sort(key=lambda p: p.confidence, reverse=True)
        top_paths = all_paths[:self.MAX_PATHS]

        # Enrichir avec les evidence_context_ids et valider l'intégrité sémantique
        for path in top_paths:
            path.evidence_context_ids = await self._collect_path_evidence(path.node_ids)

            # Phase D: Calculer le tier effectif du chemin
            if path.edge_tiers:
                path.path_tier = compute_path_tier(path.edge_tiers)

            # Phase D: Valider l'intégrité sémantique (anti-contamination)
            if path.edge_grades:
                _, warning = validate_path_semantic_integrity(path.edge_grades)
                path.semantic_integrity_warning = warning

        return top_paths

    async def _cypher_all_paths(
        self,
        source_id: str,
        target_id: str,
        allowed_tiers: Optional[Set[DefensibilityTier]] = None,
    ) -> List[SemanticPath]:
        """
        Trouve tous les chemins entre deux concepts via Cypher natif.

        Phase D: Filtre les chemins par DefensibilityTier sur chaque arête.

        Note: Pour k-shortest paths avec scoring, Yen via GDS serait meilleur,
        mais allShortestPaths est plus stable pour notre cas d'usage.

        Args:
            source_id: ID du concept source
            target_id: ID du concept cible
            allowed_tiers: Tiers autorisés pour les arêtes
        """
        # ADR_GRAPH_FIRST_ARCHITECTURE: Relations sémantiques uniquement
        from .graph_guided_search import SEMANTIC_RELATION_TYPES
        relation_types = "|".join(SEMANTIC_RELATION_TYPES)

        # Phase D: Générer la clause de filtrage par tier
        if allowed_tiers is None:
            allowed_tiers = {DefensibilityTier.STRICT}

        tier_values = [t.value for t in allowed_tiers]

        # Requête avec filtrage tier sur chaque arête
        # Note: On utilise ALL() pour vérifier que TOUTES les arêtes du chemin
        # respectent le filtre tier (pas de contamination)
        query = f"""
        MATCH (source:CanonicalConcept {{canonical_id: $source_id, tenant_id: $tenant_id}})
        MATCH (target:CanonicalConcept {{canonical_id: $target_id, tenant_id: $tenant_id}})
        MATCH path = allShortestPaths((source)-[:{relation_types}*1..{self.MAX_PATH_HOPS}]-(target))

        // Phase D: Filtrer par DefensibilityTier sur chaque arête
        WHERE ALL(rel IN relationships(path) WHERE
            rel.defensibility_tier IS NULL OR
            rel.defensibility_tier IN $allowed_tiers
        )

        WITH path,
             [node IN nodes(path) | node.canonical_name] AS node_names,
             [node IN nodes(path) | node.canonical_id] AS node_ids,
             [rel IN relationships(path) | type(rel)] AS rel_types,
             [rel IN relationships(path) | coalesce(rel.confidence, 0.5)] AS confidences,
             [rel IN relationships(path) | coalesce(rel.defensibility_tier, 'STRICT')] AS edge_tiers,
             [rel IN relationships(path) | coalesce(rel.semantic_grade, 'EXPLICIT')] AS edge_grades,
             length(path) AS path_length

        WITH path, node_names, node_ids, rel_types, path_length, edge_tiers, edge_grades,
             reduce(conf = 1.0, c IN confidences | conf * c) AS path_confidence
        WHERE path_confidence >= $min_confidence
        ORDER BY path_confidence DESC
        LIMIT $max_paths

        RETURN node_names, node_ids, rel_types, path_length, path_confidence, edge_tiers, edge_grades
        """

        try:
            result = self.neo4j_client.execute_query(query, {
                "source_id": source_id,
                "target_id": target_id,
                "tenant_id": self.tenant_id,
                "min_confidence": self.MIN_PATH_CONFIDENCE,
                "max_paths": self.MAX_PATHS,
                "allowed_tiers": tier_values,
            })

            paths = []
            for record in result:
                # Convertir les strings en enums
                edge_tiers_raw = record.get("edge_tiers", [])
                edge_grades_raw = record.get("edge_grades", [])

                edge_tiers = []
                for t in edge_tiers_raw:
                    try:
                        edge_tiers.append(DefensibilityTier(t))
                    except ValueError:
                        edge_tiers.append(DefensibilityTier.STRICT)

                edge_grades = []
                for g in edge_grades_raw:
                    try:
                        edge_grades.append(SemanticGrade(g))
                    except ValueError:
                        edge_grades.append(SemanticGrade.EXPLICIT)

                paths.append(SemanticPath(
                    nodes=record.get("node_names", []),
                    node_ids=record.get("node_ids", []),
                    relations=record.get("rel_types", []),
                    confidence=record.get("path_confidence", 0.0),
                    length=record.get("path_length", 0),
                    edge_tiers=edge_tiers,
                    edge_grades=edge_grades,
                ))

            if paths:
                logger.debug(
                    f"[GRAPH-FIRST] Found {len(paths)} paths with tiers {tier_values}"
                )

            return paths

        except Exception as e:
            logger.warning(f"[GRAPH-FIRST] Path search failed: {e}")
            return []

    async def _ensure_gds_projection(self) -> bool:
        """
        S'assure que la projection GDS SemanticGraph existe.

        Returns:
            True si la projection est disponible
        """
        try:
            # Vérifier si GDS est installé
            check_gds = """
            CALL gds.list() YIELD name RETURN count(name) AS count LIMIT 1
            """
            result = self.neo4j_client.execute_query(check_gds)
            if not result:
                return False

            # Vérifier/créer la projection
            projection_name = f"SemanticGraph_{self.tenant_id}"

            check_exists = """
            CALL gds.graph.exists($name) YIELD exists
            RETURN exists
            """
            exists_result = self.neo4j_client.execute_query(
                check_exists, {"name": projection_name}
            )

            if exists_result and exists_result[0].get("exists"):
                return True

            # Créer la projection si elle n'existe pas
            from .graph_guided_search import SEMANTIC_RELATION_TYPES

            # Construction de la configuration des relations
            rel_config = ", ".join([
                f"{rt}: {{orientation: 'UNDIRECTED', properties: ['confidence']}}"
                for rt in SEMANTIC_RELATION_TYPES
            ])

            create_query = f"""
            CALL gds.graph.project(
                $name,
                {{
                    CanonicalConcept: {{
                        properties: ['quality_score']
                    }}
                }},
                {{
                    {rel_config}
                }}
            )
            YIELD graphName, nodeCount, relationshipCount
            RETURN graphName, nodeCount, relationshipCount
            """

            create_result = self.neo4j_client.execute_query(
                create_query, {"name": projection_name}
            )

            if create_result:
                stats = create_result[0]
                logger.info(
                    f"[GRAPH-FIRST:GDS] Created projection {projection_name}: "
                    f"{stats.get('nodeCount', 0)} nodes, "
                    f"{stats.get('relationshipCount', 0)} relations"
                )
                return True

            return False

        except Exception as e:
            logger.debug(f"[GRAPH-FIRST:GDS] Projection setup failed: {e}")
            return False

    async def _gds_yen_paths(
        self,
        source_id: str,
        target_id: str
    ) -> List[SemanticPath]:
        """
        Trouve les k meilleurs chemins via GDS Yen k-shortest paths.

        ADR_GRAPH_FIRST_ARCHITECTURE: Yen's k-shortest paths pour Top-K auditables.
        Note: Dijkstra = 1 seul chemin, Yen = k meilleurs chemins.
        """
        projection_name = f"SemanticGraph_{self.tenant_id}"

        # GDS Yen k-shortest paths
        query = """
        MATCH (source:CanonicalConcept {canonical_id: $source_id, tenant_id: $tenant_id})
        MATCH (target:CanonicalConcept {canonical_id: $target_id, tenant_id: $tenant_id})
        CALL gds.shortestPath.yens.stream($projection_name, {
            sourceNode: source,
            targetNode: target,
            k: $k,
            relationshipWeightProperty: 'confidence'
        })
        YIELD index, sourceNode, targetNode, totalCost, nodeIds, costs, path
        WITH index, totalCost, nodeIds,
             [nodeId IN nodeIds | gds.util.asNode(nodeId).canonical_name] AS node_names,
             [nodeId IN nodeIds | gds.util.asNode(nodeId).canonical_id] AS node_ids_list,
             size(nodeIds) - 1 AS path_length
        WHERE totalCost <= $max_cost
        RETURN node_names, node_ids_list, path_length, totalCost AS total_cost
        ORDER BY total_cost ASC
        LIMIT $max_paths
        """

        try:
            result = self.neo4j_client.execute_query(query, {
                "source_id": source_id,
                "target_id": target_id,
                "tenant_id": self.tenant_id,
                "projection_name": projection_name,
                "k": self.MAX_PATHS,
                "max_cost": 1.0 / self.MIN_PATH_CONFIDENCE,  # Inverse car weight=confidence
                "max_paths": self.MAX_PATHS,
            })

            paths = []
            for record in result:
                # Convertir le cost en confidence (inverse)
                total_cost = record.get("total_cost", 1.0)
                confidence = 1.0 / max(total_cost, 0.1)
                confidence = min(confidence, 1.0)  # Cap à 1.0

                paths.append(SemanticPath(
                    nodes=record.get("node_names", []),
                    node_ids=record.get("node_ids_list", []),
                    relations=[],  # GDS ne retourne pas les types de relations directement
                    confidence=confidence,
                    length=record.get("path_length", 0),
                ))

            if paths:
                logger.debug(
                    f"[GRAPH-FIRST:GDS] Yen found {len(paths)} paths between "
                    f"{source_id[:8]}...→{target_id[:8]}..."
                )

            return paths

        except Exception as e:
            logger.debug(f"[GRAPH-FIRST:GDS] Yen pathfinding failed: {e}")
            return []

    async def _collect_path_evidence(
        self,
        concept_ids: List[str]
    ) -> List[str]:
        """
        Collecte les context_ids des evidence pour les concepts d'un chemin.

        Utilise MENTIONED_IN pour récupérer les sections où les concepts
        sont mentionnés (avec leur salience).
        """
        if not concept_ids:
            return []

        # ADR: Evidence Collection via MENTIONED_IN
        query = """
        UNWIND $concept_ids AS cid
        MATCH (c:CanonicalConcept {canonical_id: cid, tenant_id: $tenant_id})
        MATCH (c)-[m:MENTIONED_IN]->(ctx:SectionContext)
        WHERE ctx.tenant_id = $tenant_id
        RETURN DISTINCT ctx.context_id AS context_id, m.weight AS salience
        ORDER BY salience DESC
        LIMIT 50
        """

        try:
            result = self.neo4j_client.execute_query(query, {
                "concept_ids": concept_ids,
                "tenant_id": self.tenant_id,
            })

            context_ids = [r.get("context_id") for r in result if r.get("context_id")]
            return context_ids

        except Exception as e:
            logger.warning(f"[GRAPH-FIRST] Evidence collection failed: {e}")
            return []

    async def _find_structural_routes(
        self,
        concept_ids: List[str]
    ) -> List[StructuralRoute]:
        """
        Trouve les routes structurelles via HAS_TOPIC et COVERS.

        Mode ANCHORED: pas de chemin sémantique, mais on peut router
        via la structure documentaire (Topics).
        """
        if not concept_ids:
            return []

        # Trouver les Topics qui COVERS les concepts seeds
        query = """
        UNWIND $concept_ids AS cid
        MATCH (c:CanonicalConcept {canonical_id: cid, tenant_id: $tenant_id})
        MATCH (topic:CanonicalConcept {concept_type: 'TOPIC', tenant_id: $tenant_id})-[:COVERS]->(c)
        WITH topic, collect(DISTINCT cid) AS covered_ids

        // Récupérer les documents ayant ce topic
        MATCH (doc:Document {tenant_id: $tenant_id})-[:HAS_TOPIC]->(topic)

        // Récupérer les context_ids via MENTIONED_IN
        OPTIONAL MATCH (topic)-[:MENTIONED_IN]->(ctx:SectionContext {tenant_id: $tenant_id})

        RETURN
            topic.canonical_name AS topic_name,
            topic.canonical_id AS topic_id,
            covered_ids,
            collect(DISTINCT doc.document_id) AS document_ids,
            collect(DISTINCT ctx.context_id) AS context_ids
        ORDER BY size(covered_ids) DESC
        LIMIT 5
        """

        try:
            result = self.neo4j_client.execute_query(query, {
                "concept_ids": concept_ids,
                "tenant_id": self.tenant_id,
            })

            routes = []
            for record in result:
                route = StructuralRoute(
                    topic_name=record.get("topic_name", ""),
                    topic_id=record.get("topic_id", ""),
                    covered_concept_ids=record.get("covered_ids", []),
                    document_ids=record.get("document_ids", []),
                    context_ids=[cid for cid in record.get("context_ids", []) if cid],
                )
                if route.context_ids:  # Ne garder que les routes avec context
                    routes.append(route)

            return routes

        except Exception as e:
            logger.warning(f"[GRAPH-FIRST] Structural routing failed: {e}")
            return []

    async def search_qdrant_filtered(
        self,
        query: str,
        context_ids: List[str],
        collection_name: str = "knowbase",
        top_k: int = 10,
    ) -> List[Dict[str, Any]]:
        """
        Recherche Qdrant filtrée par context_ids.

        ADR Phase C.4: Filtrage par context_id pour récupérer
        uniquement les chunks des sections pertinentes.
        """
        from qdrant_client.models import Filter, FieldCondition, MatchAny

        # Construire le filtre
        filter_conditions = [
            FieldCondition(
                key="tenant_id",
                match=MatchAny(any=[self.tenant_id])
            )
        ]

        if context_ids:
            filter_conditions.append(
                FieldCondition(
                    key="context_id",
                    match=MatchAny(any=context_ids)
                )
            )

        query_filter = Filter(must=filter_conditions)

        # Générer l'embedding de la requête
        from knowbase.common.clients.openai_client import get_openai_client
        openai_client = get_openai_client()

        embedding_response = await openai_client.embeddings.create(
            model="text-embedding-3-small",
            input=query,
        )
        query_vector = embedding_response.data[0].embedding

        # Recherche
        try:
            results = self.qdrant_client.search(
                collection_name=collection_name,
                query_vector=query_vector,
                query_filter=query_filter,
                limit=top_k,
                with_payload=True,
            )

            chunks = []
            for hit in results:
                payload = hit.payload or {}
                chunks.append({
                    "text": payload.get("text", ""),
                    "document_id": payload.get("document_id", ""),
                    "context_id": payload.get("context_id", ""),
                    "section_path": payload.get("section_path", ""),
                    "score": hit.score,
                    "source_file": payload.get("document_name", ""),
                })

            logger.info(
                f"[GRAPH-FIRST] Qdrant filtered search: {len(chunks)} chunks "
                f"(filter: {len(context_ids)} context_ids)"
            )

            return chunks

        except Exception as e:
            logger.warning(f"[GRAPH-FIRST] Qdrant search failed: {e}")
            return []


# Singleton
_graph_first_service: Optional[Dict[str, GraphFirstSearchService]] = {}


def get_graph_first_service(
    tenant_id: str = "default",
    tier_policy: TraversalPolicy = TraversalPolicy.STRICT,
) -> GraphFirstSearchService:
    """
    Retourne l'instance singleton du service pour un tenant.

    Args:
        tenant_id: ID du tenant
        tier_policy: Policy de filtrage par défaut

    Returns:
        GraphFirstSearchService configuré
    """
    global _graph_first_service
    cache_key = f"{tenant_id}_{tier_policy.value}"
    if cache_key not in _graph_first_service:
        _graph_first_service[cache_key] = GraphFirstSearchService(
            tenant_id=tenant_id,
            tier_policy=tier_policy,
        )
    return _graph_first_service[cache_key]


__all__ = [
    "GraphFirstSearchService",
    "GraphFirstPlan",
    "SearchMode",
    "SemanticPath",
    "StructuralRoute",
    "get_graph_first_service",
    # Phase D - Tier Filtering
    "TraversalPolicy",
    "TierFilterConfig",
    "EscalationResult",
    "TierFilterService",
    "get_tier_filter_service",
]
