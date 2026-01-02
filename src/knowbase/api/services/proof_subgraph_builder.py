"""
🌊 OSMOSE Proof Subgraph Builder - Phase 3.5+

Construit un sous-graphe de preuve budgeté et hiérarchisé pour la visualisation.

Le Proof Graph montre UNIQUEMENT les relations qui justifient la réponse,
pas la totalité du KG. C'est l'USP visuelle d'OSMOSE.

Règles de construction (spec ChatGPT):
- R0: Exclure les weak links (CO_OCCURS, MENTIONED_IN)
- R1: CORE = query ∪ used concepts
- R2: Compléter avec chemins de preuve query→used
- R3: Budget MAX_NODES=60, MAX_EDGES=90
- R4: Context nodes seulement sur les chemins
- R5: Dédup et simplification

Author: Claude Code
Date: 2026-01-01
"""

from __future__ import annotations

import heapq
import logging
import math
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set, Tuple

logger = logging.getLogger(__name__)

# Configuration budgets
MAX_NODES = 15  # Réduit pour lisibilité du graphe
MAX_EDGES = 30
MAX_PATHS_PER_USED = 1  # Un seul meilleur chemin par concept "used"
MAX_TOTAL_PATHS = 5  # Limite globale de chemins (évite surcharge visuelle)
MAX_CONTEXT_RATIO = 0.20  # Max 20% context nodes

# Relations faibles (navigation layer) - exclues du Proof Graph
WEAK_LINK_TYPES = frozenset({
    "CO_OCCURS", "MENTIONED_IN", "HAS_SECTION", "CONTAINED_IN",
    "APPEARS_WITH", "CO_OCCURS_IN_DOCUMENT", "CO_OCCURS_IN_CORPUS",
})


@dataclass
class ProofNode:
    """Noeud dans le Proof Graph avec métadonnées enrichies."""
    id: str
    name: str
    type: str
    role: str  # query, used, context, bridge
    confidence: float
    mention_count: int
    document_count: int
    depth: int = 0  # Distance depuis la question (pour layout)
    is_on_path: bool = False  # Sur un chemin de preuve

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "type": self.type,
            "role": self.role,
            "confidence": self.confidence,
            "mentionCount": self.mention_count,
            "documentCount": self.document_count,
            "depth": self.depth,
            "isOnPath": self.is_on_path,
        }


@dataclass
class ProofEdge:
    """Arête dans le Proof Graph avec evidences."""
    id: str
    source: str
    target: str
    relation_type: str
    confidence: float
    is_used: bool = False
    is_on_path: bool = False
    evidence_count: int = 1
    evidences: List[Dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "source": self.source,
            "target": self.target,
            "relationType": self.relation_type,
            "confidence": self.confidence,
            "isUsed": self.is_used,
            "isOnPath": self.is_on_path,
            "evidenceCount": self.evidence_count,
            "evidences": self.evidences[:3],  # Top 3 max
        }


@dataclass
class ProofPath:
    """Chemin de preuve entre query et used concept."""
    path_id: str
    from_concept: str
    to_concept: str
    node_ids: List[str]
    edge_ids: List[str]
    total_confidence: float
    length: int

    def to_dict(self) -> Dict[str, Any]:
        return {
            "pathId": self.path_id,
            "fromConcept": self.from_concept,
            "toConcept": self.to_concept,
            "nodeIds": self.node_ids,
            "edgeIds": self.edge_ids,
            "totalConfidence": self.total_confidence,
            "length": self.length,
        }


@dataclass
class ProofGraph:
    """Proof Graph complet avec chemins et métadonnées."""
    nodes: List[ProofNode] = field(default_factory=list)
    edges: List[ProofEdge] = field(default_factory=list)
    paths: List[ProofPath] = field(default_factory=list)
    root_id: str = "question_root"
    query_concept_ids: List[str] = field(default_factory=list)
    used_concept_ids: List[str] = field(default_factory=list)
    stats: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "nodes": [n.to_dict() for n in self.nodes],
            "edges": [e.to_dict() for e in self.edges],
            "paths": [p.to_dict() for p in self.paths],
            "rootId": self.root_id,
            "queryConceptIds": self.query_concept_ids,
            "usedConceptIds": self.used_concept_ids,
            "stats": self.stats,
        }


class ProofSubgraphBuilder:
    """
    Construit le Proof Subgraph à partir du GraphContext OSMOSE.

    Le Proof Graph est un sous-ensemble du KG complet, optimisé pour:
    1. Montrer les chemins de preuve (query → used)
    2. Être lisible (budget contrôlé)
    3. Être hiérarchisé (depth pour layout)
    """

    def __init__(
        self,
        max_nodes: int = MAX_NODES,
        max_edges: int = MAX_EDGES,
        max_paths_per_used: int = MAX_PATHS_PER_USED,
    ):
        self.max_nodes = max_nodes
        self.max_edges = max_edges
        self.max_paths_per_used = max_paths_per_used
        self._neo4j_client = None

    @property
    def neo4j_client(self):
        """Lazy loading du client Neo4j."""
        if self._neo4j_client is None:
            from knowbase.common.clients.neo4j_client import get_neo4j_client
            from knowbase.config.settings import get_settings
            settings = get_settings()
            self._neo4j_client = get_neo4j_client(
                uri=settings.neo4j_uri,
                user=settings.neo4j_user,
                password=settings.neo4j_password
            )
        return self._neo4j_client

    def build_proof_graph(
        self,
        graph_data: Dict[str, Any],
        query_concept_ids: List[str],
        used_concept_ids: List[str],
        tenant_id: str = "default",
    ) -> ProofGraph:
        """
        Construit le Proof Graph à partir des données brutes.

        Args:
            graph_data: Données brutes du graphe (nodes, edges)
            query_concept_ids: IDs des concepts de la question
            used_concept_ids: IDs des concepts utilisés dans la réponse
            tenant_id: Tenant ID

        Returns:
            ProofGraph budgeté et hiérarchisé
        """
        logger.info(
            f"[ProofSubgraph] Building proof graph: "
            f"{len(query_concept_ids)} query, {len(used_concept_ids)} used"
        )

        # Extraire nodes et edges du graph_data
        logger.debug(f"[ProofSubgraph] graph_data type: {type(graph_data)}")
        logger.debug(f"[ProofSubgraph] graph_data keys: {graph_data.keys() if isinstance(graph_data, dict) else 'N/A'}")

        raw_nodes = graph_data.get("nodes", [])
        raw_edges = graph_data.get("edges", [])

        logger.debug(f"[ProofSubgraph] raw_nodes: {len(raw_nodes)} items, first type: {type(raw_nodes[0]) if raw_nodes else 'empty'}")
        logger.debug(f"[ProofSubgraph] raw_edges: {len(raw_edges)} items, first type: {type(raw_edges[0]) if raw_edges else 'empty'}")

        # Debug: vérifier le type des éléments
        if raw_nodes and not isinstance(raw_nodes[0], dict):
            logger.error(f"[ProofSubgraph] raw_nodes[0] is {type(raw_nodes[0])}, expected dict")
            return ProofGraph(stats={"total_nodes": 0, "total_edges": 0, "total_paths": 0})

        if raw_edges and not isinstance(raw_edges[0], dict):
            logger.error(f"[ProofSubgraph] raw_edges[0] is {type(raw_edges[0])}, expected dict")
            return ProofGraph(stats={"total_nodes": 0, "total_edges": 0, "total_paths": 0})

        # R0: Filtrer les weak links
        semantic_edges = [
            e for e in raw_edges
            if isinstance(e, dict) and e.get("relationType", e.get("relation_type", "")) not in WEAK_LINK_TYPES
        ]

        logger.debug(
            f"[ProofSubgraph] After weak link filter: "
            f"{len(semantic_edges)}/{len(raw_edges)} edges"
        )

        # Construire les index (avec protection contre les non-dicts)
        nodes_by_id = {
            n.get("id"): n for n in raw_nodes
            if isinstance(n, dict) and n.get("id")
        }

        # Adjacency list pour pathfinding
        adj_list = self._build_adjacency_list(semantic_edges)

        # R1: CORE = query ∪ used
        core_ids = set(query_concept_ids) | set(used_concept_ids)

        # R2: Trouver les chemins de preuve query → used
        paths = []
        path_node_ids: Set[str] = set()
        path_edge_ids: Set[str] = set()

        for used_id in used_concept_ids:
            if used_id in query_concept_ids:
                continue  # Skip si déjà dans query

            # Limite globale de chemins atteinte
            if len(paths) >= MAX_TOTAL_PATHS:
                logger.debug(f"[ProofSubgraph] Reached MAX_TOTAL_PATHS={MAX_TOTAL_PATHS}, stopping")
                break

            # Trouver les meilleurs chemins depuis les query concepts
            best_paths = self._find_best_paths(
                query_concept_ids,
                used_id,
                adj_list,
                nodes_by_id,
                max_paths=self.max_paths_per_used,
            )

            for path_info in best_paths:
                if len(paths) >= MAX_TOTAL_PATHS:
                    break
                path = ProofPath(
                    path_id=f"path_{len(paths):03d}",
                    from_concept=path_info["from"],
                    to_concept=used_id,
                    node_ids=path_info["nodes"],
                    edge_ids=path_info["edges"],
                    total_confidence=path_info["confidence"],
                    length=len(path_info["nodes"]),
                )
                paths.append(path)
                path_node_ids.update(path_info["nodes"])
                path_edge_ids.update(path_info["edges"])

        # Log path lengths distribution
        path_lengths = [p.length for p in paths]
        logger.info(f"[ProofSubgraph] Found {len(paths)} proof paths, lengths: {path_lengths[:10]}...")

        # R3 & R4: Sélectionner les noeuds et arêtes avec budget
        selected_node_ids = self._select_nodes_with_budget(
            core_ids=core_ids,
            path_node_ids=path_node_ids,
            nodes_by_id=nodes_by_id,
        )

        selected_edge_ids = self._select_edges_with_budget(
            selected_node_ids=selected_node_ids,
            path_edge_ids=path_edge_ids,
            edges=semantic_edges,
        )

        # Calculer les depths (BFS depuis query concepts)
        depths = self._compute_depths(
            query_concept_ids,
            selected_node_ids,
            adj_list,
        )

        # Construire les ProofNodes
        proof_nodes = []
        for node_id in selected_node_ids:
            raw_node = nodes_by_id.get(node_id, {})

            # Déterminer le rôle
            if node_id in query_concept_ids:
                role = "query"
            elif node_id in used_concept_ids:
                role = "used"
            elif node_id in path_node_ids:
                role = "bridge"
            else:
                role = "context"

            proof_nodes.append(ProofNode(
                id=node_id,
                name=raw_node.get("name", node_id),
                type=raw_node.get("type", "UNKNOWN"),
                role=role,
                confidence=raw_node.get("confidence", 0.5),
                mention_count=raw_node.get("mentionCount", raw_node.get("mention_count", 0)),
                document_count=raw_node.get("documentCount", raw_node.get("document_count", 0)),
                depth=depths.get(node_id, 99),
                is_on_path=node_id in path_node_ids,
            ))

        # Construire les ProofEdges
        proof_edges = []
        edges_by_id = {e.get("id"): e for e in semantic_edges}

        for edge_id in selected_edge_ids:
            raw_edge = edges_by_id.get(edge_id)
            if not raw_edge:
                continue

            # Récupérer les evidences si disponibles
            evidences = raw_edge.get("evidences", [])
            if not evidences:
                # Construire une evidence basique depuis les métadonnées
                evidences = [{
                    "source_doc": raw_edge.get("source_doc_id", ""),
                    "confidence": raw_edge.get("confidence", 0.5),
                }]

            proof_edges.append(ProofEdge(
                id=edge_id,
                source=raw_edge.get("source"),
                target=raw_edge.get("target"),
                relation_type=raw_edge.get("relationType", raw_edge.get("relation_type", "RELATED_TO")),
                confidence=raw_edge.get("confidence", 0.5),
                is_used=raw_edge.get("isUsed", raw_edge.get("is_used", False)),
                is_on_path=edge_id in path_edge_ids,
                evidence_count=len(evidences),
                evidences=evidences,
            ))

        # Construire le résultat
        proof_graph = ProofGraph(
            nodes=proof_nodes,
            edges=proof_edges,
            paths=paths,
            root_id="question_root",
            query_concept_ids=query_concept_ids,
            used_concept_ids=used_concept_ids,
            stats={
                "total_nodes": len(proof_nodes),
                "total_edges": len(proof_edges),
                "total_paths": len(paths),
                "query_count": len(query_concept_ids),
                "used_count": len(used_concept_ids),
                "bridge_count": sum(1 for n in proof_nodes if n.role == "bridge"),
                "context_count": sum(1 for n in proof_nodes if n.role == "context"),
                "max_depth": max((n.depth for n in proof_nodes), default=0),
            },
        )

        logger.info(
            f"[ProofSubgraph] Built proof graph: "
            f"{len(proof_nodes)} nodes, {len(proof_edges)} edges, {len(paths)} paths"
        )

        return proof_graph

    def _build_adjacency_list(
        self,
        edges: List[Dict[str, Any]],
    ) -> Dict[str, List[Tuple[str, str, float]]]:
        """
        Construit la liste d'adjacence pour le pathfinding.

        Returns:
            Dict[node_id, List[(neighbor_id, edge_id, cost)]]
        """
        adj: Dict[str, List[Tuple[str, str, float]]] = defaultdict(list)

        for edge in edges:
            # Protection: s'assurer que edge est un dict
            if not isinstance(edge, dict):
                logger.warning(f"[ProofSubgraph] Skipping non-dict edge: {type(edge)}")
                continue

            source = edge.get("source")
            target = edge.get("target")
            edge_id = edge.get("id", f"{source}_{target}")
            confidence = edge.get("confidence", 0.5)

            # Coût = -log(confidence) : plus confiant = moins cher
            cost = -math.log(max(confidence, 0.01))

            # Bidirectionnel pour le pathfinding
            adj[source].append((target, edge_id, cost))
            adj[target].append((source, edge_id, cost))

        return adj

    def _find_best_paths(
        self,
        from_ids: List[str],
        to_id: str,
        adj_list: Dict[str, List[Tuple[str, str, float]]],
        nodes_by_id: Dict[str, Dict],
        max_paths: int = 2,
    ) -> List[Dict[str, Any]]:
        """
        Trouve les meilleurs chemins de from_ids vers to_id.

        Utilise Dijkstra avec coût = -log(confidence).
        """
        best_paths = []

        for from_id in from_ids:
            path = self._dijkstra(from_id, to_id, adj_list)
            if path:
                # Calculer la confiance totale du chemin
                total_conf = 1.0
                for edge_id in path["edges"]:
                    # Approximation : on n'a pas accès aux edges ici
                    total_conf *= 0.8  # Placeholder

                best_paths.append({
                    "from": from_id,
                    "nodes": path["nodes"],
                    "edges": path["edges"],
                    "confidence": total_conf,
                    "cost": path["cost"],
                })

        # Trier par coût croissant et prendre les meilleurs
        best_paths.sort(key=lambda p: p["cost"])
        return best_paths[:max_paths]

    def _dijkstra(
        self,
        start: str,
        end: str,
        adj_list: Dict[str, List[Tuple[str, str, float]]],
    ) -> Optional[Dict[str, Any]]:
        """
        Dijkstra pour trouver le chemin le moins coûteux.
        """
        if start == end:
            return {"nodes": [start], "edges": [], "cost": 0}

        # (cost, node, path_nodes, path_edges)
        heap = [(0, start, [start], [])]
        visited = set()

        while heap:
            cost, node, path_nodes, path_edges = heapq.heappop(heap)

            if node in visited:
                continue
            visited.add(node)

            if node == end:
                return {
                    "nodes": path_nodes,
                    "edges": path_edges,
                    "cost": cost,
                }

            for neighbor, edge_id, edge_cost in adj_list.get(node, []):
                if neighbor not in visited:
                    heapq.heappush(heap, (
                        cost + edge_cost,
                        neighbor,
                        path_nodes + [neighbor],
                        path_edges + [edge_id],
                    ))

        return None  # Pas de chemin trouvé

    def _select_nodes_with_budget(
        self,
        core_ids: Set[str],
        path_node_ids: Set[str],
        nodes_by_id: Dict[str, Dict],
    ) -> Set[str]:
        """
        Sélectionne les noeuds avec respect du budget.

        Priorité:
        1. Core (query + used)
        2. Noeuds sur les chemins
        3. Context (limité à 30%)
        """
        selected = set()

        # 1. Core obligatoire
        selected.update(core_ids)

        # 2. Noeuds sur les chemins
        remaining_budget = self.max_nodes - len(selected)
        path_only = path_node_ids - core_ids

        if len(path_only) <= remaining_budget:
            selected.update(path_only)
        else:
            # Trier par confiance et prendre les meilleurs
            sorted_path = sorted(
                path_only,
                key=lambda nid: nodes_by_id.get(nid, {}).get("confidence", 0),
                reverse=True
            )
            selected.update(sorted_path[:remaining_budget])

        # 3. Limiter les context nodes
        max_context = int(self.max_nodes * MAX_CONTEXT_RATIO)
        context_count = len(selected) - len(core_ids)

        if context_count > max_context:
            # Retirer les context les moins confiants
            context_nodes = selected - core_ids
            sorted_context = sorted(
                context_nodes,
                key=lambda nid: nodes_by_id.get(nid, {}).get("confidence", 0),
                reverse=True
            )
            to_keep = set(sorted_context[:max_context])
            selected = core_ids | to_keep

        logger.debug(f"[ProofSubgraph] Selected {len(selected)} nodes (budget: {self.max_nodes})")
        return selected

    def _select_edges_with_budget(
        self,
        selected_node_ids: Set[str],
        path_edge_ids: Set[str],
        edges: List[Dict[str, Any]],
    ) -> Set[str]:
        """
        Sélectionne les arêtes avec respect du budget.

        Priorité:
        1. Arêtes sur les chemins de preuve
        2. Arêtes entre noeuds sélectionnés (par confiance)
        """
        selected = set()

        # 1. Arêtes sur les chemins (priorité absolue)
        selected.update(path_edge_ids)

        # 2. Autres arêtes entre noeuds sélectionnés
        remaining_budget = self.max_edges - len(selected)

        candidate_edges = []
        for edge in edges:
            edge_id = edge.get("id")
            if edge_id in selected:
                continue

            source = edge.get("source")
            target = edge.get("target")

            if source in selected_node_ids and target in selected_node_ids:
                candidate_edges.append((edge_id, edge.get("confidence", 0)))

        # Trier par confiance décroissante
        candidate_edges.sort(key=lambda x: x[1], reverse=True)

        for edge_id, _ in candidate_edges[:remaining_budget]:
            selected.add(edge_id)

        logger.debug(f"[ProofSubgraph] Selected {len(selected)} edges (budget: {self.max_edges})")
        return selected

    def _compute_depths(
        self,
        root_ids: List[str],
        node_ids: Set[str],
        adj_list: Dict[str, List[Tuple[str, str, float]]],
    ) -> Dict[str, int]:
        """
        Calcule la profondeur de chaque noeud depuis les roots (BFS).

        Utilisé pour le layout hiérarchique.
        """
        depths: Dict[str, int] = {}

        # BFS depuis tous les roots
        queue = [(root_id, 0) for root_id in root_ids]
        visited = set()

        while queue:
            node, depth = queue.pop(0)

            if node in visited:
                continue
            if node not in node_ids:
                continue

            visited.add(node)
            depths[node] = depth

            for neighbor, _, _ in adj_list.get(node, []):
                if neighbor not in visited and neighbor in node_ids:
                    queue.append((neighbor, depth + 1))

        # Noeuds non atteignables : depth = 99
        for node_id in node_ids:
            if node_id not in depths:
                depths[node_id] = 99

        return depths


# Singleton
_builder_instance: Optional[ProofSubgraphBuilder] = None


def get_proof_subgraph_builder() -> ProofSubgraphBuilder:
    """Retourne l'instance singleton du ProofSubgraphBuilder."""
    global _builder_instance
    if _builder_instance is None:
        _builder_instance = ProofSubgraphBuilder()
    return _builder_instance


def build_proof_graph(
    graph_data: Dict[str, Any],
    query_concept_ids: List[str],
    used_concept_ids: List[str],
    tenant_id: str = "default",
) -> Dict[str, Any]:
    """
    Fonction utilitaire pour construire le Proof Graph.

    Usage:
        proof_graph = build_proof_graph(
            graph_data=response["graph_data"],
            query_concept_ids=["concept_1", "concept_2"],
            used_concept_ids=["concept_3"],
        )
    """
    builder = get_proof_subgraph_builder()
    proof = builder.build_proof_graph(
        graph_data=graph_data,
        query_concept_ids=query_concept_ids,
        used_concept_ids=used_concept_ids,
        tenant_id=tenant_id,
    )
    return proof.to_dict()


__all__ = [
    "ProofSubgraphBuilder",
    "ProofGraph",
    "ProofNode",
    "ProofEdge",
    "ProofPath",
    "get_proof_subgraph_builder",
    "build_proof_graph",
]
