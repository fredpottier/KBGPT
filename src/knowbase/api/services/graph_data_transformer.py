"""
🌊 OSMOSE Phase 3.5 - Graph Data Transformer pour D3.js

Transforme le GraphContext OSMOSE en format exploitable par D3.js (nodes/edges).
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Set
from dataclasses import dataclass, field
from enum import Enum

from knowbase.common.logging import setup_logging
from knowbase.config.settings import get_settings

settings = get_settings()
logger = setup_logging(settings.logs_dir, "graph_data_transformer.log")


class ConceptRole(str, Enum):
    """Rôle d'un concept dans le graphe (détermine la couleur)."""
    QUERY = "query"         # Concept identifié dans la question
    USED = "used"           # Concept utilisé dans la réponse
    SUGGESTED = "suggested" # Concept suggéré à explorer
    CONTEXT = "context"     # Concept de contexte


class ConceptType(str, Enum):
    """Type ontologique du concept."""
    PRODUCT = "PRODUCT"
    SERVICE = "SERVICE"
    TECHNOLOGY = "TECHNOLOGY"
    PRACTICE = "PRACTICE"
    ORGANIZATION = "ORGANIZATION"
    PERSON = "PERSON"
    LOCATION = "LOCATION"
    EVENT = "EVENT"
    CONCEPT = "CONCEPT"
    UNKNOWN = "UNKNOWN"


class GraphLayer(str, Enum):
    """Couche du graphe (ADR: ADR_NAVIGATION_LAYER.md)."""
    SEMANTIC = "semantic"      # Relations pour le raisonnement (REQUIRES, ENABLES, etc.)
    NAVIGATION = "navigation"  # Relations corpus-level (MENTIONED_IN, CO_OCCURS, etc.)


# Types de relations par couche
SEMANTIC_RELATION_TYPES = frozenset({
    "REQUIRES", "ENABLES", "PREVENTS", "CAUSES",
    "APPLIES_TO", "DEPENDS_ON", "PART_OF", "MITIGATES",
    "CONFLICTS_WITH", "DEFINES", "EXAMPLE_OF", "GOVERNED_BY",
    "RELATED_TO", "SUBTYPE_OF", "USES", "INTEGRATES_WITH",
    "EXTENDS", "VERSION_OF", "PRECEDES", "REPLACES",
    "DEPRECATES", "ALTERNATIVE_TO", "TRANSITIVE",
})

NAVIGATION_RELATION_TYPES = frozenset({
    "MENTIONED_IN", "HAS_SECTION", "CONTAINED_IN", "CO_OCCURS",
    "APPEARS_WITH", "CO_OCCURS_IN_DOCUMENT", "CO_OCCURS_IN_CORPUS",
})


def get_relation_layer(relation_type: str) -> GraphLayer:
    """Détermine la couche d'une relation basé sur son type."""
    if relation_type in NAVIGATION_RELATION_TYPES:
        return GraphLayer.NAVIGATION
    return GraphLayer.SEMANTIC


@dataclass
class GraphNode:
    """Noeud du graphe D3.js."""
    id: str
    name: str
    type: str  # ConceptType
    role: str  # ConceptRole
    confidence: float
    mention_count: int
    document_count: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "type": self.type,
            "role": self.role,
            "confidence": self.confidence,
            "mentionCount": self.mention_count,
            "documentCount": self.document_count,
        }


@dataclass
class GraphEdge:
    """Arête du graphe D3.js."""
    id: str
    source: str  # ID du noeud source
    target: str  # ID du noeud cible
    relation_type: str
    confidence: float
    is_used: bool = False    # Relation traversée dans le raisonnement
    is_inferred: bool = False  # Relation inférée vs explicite
    layer: str = "semantic"  # Couche: semantic ou navigation

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "source": self.source,
            "target": self.target,
            "relationType": self.relation_type,
            "confidence": self.confidence,
            "isUsed": self.is_used,
            "isInferred": self.is_inferred,
            "layer": self.layer,
        }


@dataclass
class GraphData:
    """Données complètes du graphe pour D3.js."""
    nodes: List[GraphNode] = field(default_factory=list)
    edges: List[GraphEdge] = field(default_factory=list)
    query_concept_ids: List[str] = field(default_factory=list)
    used_concept_ids: List[str] = field(default_factory=list)
    suggested_concept_ids: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "nodes": [n.to_dict() for n in self.nodes],
            "edges": [e.to_dict() for e in self.edges],
            "queryConceptIds": self.query_concept_ids,
            "usedConceptIds": self.used_concept_ids,
            "suggestedConceptIds": self.suggested_concept_ids,
        }


class GraphDataTransformer:
    """
    Transforme le GraphContext OSMOSE en GraphData pour D3.js.

    Cette transformation enrichit les données brutes du KG avec:
    - Classification des rôles (query, used, suggested, context)
    - IDs uniques pour les noeuds et arêtes
    - Métadonnées de confiance et comptage
    """

    def __init__(self, neo4j_client=None):
        self._neo4j_client = neo4j_client

    @property
    def neo4j_client(self):
        """Lazy loading du client Neo4j."""
        if self._neo4j_client is None:
            from knowbase.neo4j_custom.client import get_neo4j_client
            self._neo4j_client = get_neo4j_client()
        return self._neo4j_client

    def _generate_node_id(self, name: str) -> str:
        """Génère un ID unique pour un noeud basé sur son nom."""
        # Utiliser un hash simple pour générer des IDs stables
        import hashlib
        return hashlib.md5(name.encode()).hexdigest()[:12]

    def _generate_edge_id(self, source: str, target: str, relation: str) -> str:
        """Génère un ID unique pour une arête."""
        import hashlib
        key = f"{source}:{relation}:{target}"
        return hashlib.md5(key.encode()).hexdigest()[:12]

    def get_concept_metadata(
        self,
        concept_names: List[str],
        tenant_id: str = "default"
    ) -> Dict[str, Dict[str, Any]]:
        """
        Récupère les métadonnées des concepts depuis Neo4j.

        Returns:
            Dict mapping nom concept -> métadonnées (type, mention_count, etc.)
        """
        if not concept_names:
            return {}

        cypher = """
        UNWIND $names AS name
        MATCH (c:CanonicalConcept {canonical_name: name, tenant_id: $tenant_id})
        RETURN
            c.canonical_name AS name,
            c.concept_type AS type,
            c.mention_count AS mention_count,
            c.document_count AS document_count,
            c.confidence AS confidence
        """

        try:
            results = self.neo4j_client.execute_query(cypher, {
                "names": concept_names,
                "tenant_id": tenant_id
            })

            metadata = {}
            for record in results:
                name = record.get("name", "")
                if name:
                    metadata[name] = {
                        "type": record.get("type", "CONCEPT"),
                        "mention_count": record.get("mention_count", 1),
                        "document_count": record.get("document_count", 1),
                        "confidence": record.get("confidence", 0.5),
                    }

            return metadata

        except Exception as e:
            logger.warning(f"[GRAPH-DATA] Failed to get concept metadata: {e}")
            return {}

    def transform(
        self,
        graph_context: Dict[str, Any],
        used_in_synthesis: List[str] = None,
        tenant_id: str = "default"
    ) -> GraphData:
        """
        Transforme un GraphContext en GraphData pour D3.js.

        Args:
            graph_context: Dictionnaire du GraphContext (depuis to_dict())
            used_in_synthesis: Liste des concepts effectivement utilisés dans la réponse
            tenant_id: Tenant ID

        Returns:
            GraphData prêt pour D3.js
        """
        if not graph_context:
            return GraphData()

        used_in_synthesis = used_in_synthesis or []
        used_set = set(c.lower() for c in used_in_synthesis)

        # Collecter tous les noms de concepts
        all_concepts: Set[str] = set()

        query_concepts = graph_context.get("query_concepts", [])
        for c in query_concepts:
            # c peut être un dict ou une string
            if isinstance(c, dict):
                name = c.get("canonical_name") or c.get("name", "")
                if name:
                    all_concepts.add(name)
            elif isinstance(c, str):
                all_concepts.add(c)

        related_concepts = graph_context.get("related_concepts", [])
        for rel in related_concepts:
            if rel.get("concept"):
                all_concepts.add(rel["concept"])
            if rel.get("source"):
                all_concepts.add(rel["source"])

        transitive_relations = graph_context.get("transitive_relations", [])
        for trans in transitive_relations:
            for c in trans.get("concepts", []):
                all_concepts.add(c)

        thematic_cluster = graph_context.get("thematic_cluster")
        if thematic_cluster:
            for c in thematic_cluster.get("concepts", []):
                all_concepts.add(c)

        bridge_concepts = graph_context.get("bridge_concepts", [])
        for c in bridge_concepts:
            # c peut être un dict ou une string
            if isinstance(c, dict):
                name = c.get("canonical_name") or c.get("name", "")
                if name:
                    all_concepts.add(name)
            elif isinstance(c, str):
                all_concepts.add(c)

        # Récupérer les métadonnées de tous les concepts
        metadata = self.get_concept_metadata(list(all_concepts), tenant_id)

        # Créer les noeuds avec rôles
        nodes: Dict[str, GraphNode] = {}
        query_concept_ids = []
        used_concept_ids = []
        suggested_concept_ids = []

        for name in all_concepts:
            node_id = self._generate_node_id(name)
            meta = metadata.get(name, {})

            # Déterminer le rôle
            if name in query_concepts:
                role = ConceptRole.QUERY.value
                query_concept_ids.append(node_id)
            elif name.lower() in used_set:
                role = ConceptRole.USED.value
                used_concept_ids.append(node_id)
            elif name in bridge_concepts:
                role = ConceptRole.SUGGESTED.value
                suggested_concept_ids.append(node_id)
            else:
                role = ConceptRole.CONTEXT.value

            nodes[name] = GraphNode(
                id=node_id,
                name=name,
                type=meta.get("type", "CONCEPT"),
                role=role,
                confidence=meta.get("confidence", 0.5),
                mention_count=meta.get("mention_count", 1),
                document_count=meta.get("document_count", 0),
            )

        # Créer les arêtes
        edges: List[GraphEdge] = []
        edge_ids: Set[str] = set()  # Éviter les doublons

        # Arêtes des related_concepts
        for rel in related_concepts:
            source_name = rel.get("source", "")
            target_name = rel.get("concept", "")
            relation = rel.get("relation", "RELATED_TO")

            if source_name not in nodes or target_name not in nodes:
                continue

            source_id = nodes[source_name].id
            target_id = nodes[target_name].id
            edge_id = self._generate_edge_id(source_id, target_id, relation)

            if edge_id not in edge_ids:
                edge_ids.add(edge_id)

                # Déterminer si l'arête est "utilisée" (relie des concepts query/used)
                is_used = (
                    source_id in query_concept_ids or source_id in used_concept_ids
                ) and (
                    target_id in query_concept_ids or target_id in used_concept_ids
                )

                edges.append(GraphEdge(
                    id=edge_id,
                    source=source_id,
                    target=target_id,
                    relation_type=relation,
                    confidence=rel.get("confidence", 0.5),
                    is_used=is_used,
                    is_inferred=False,
                    layer=get_relation_layer(relation).value,
                ))

        # Arêtes des transitive_relations (marquées comme inferred)
        for trans in transitive_relations:
            concepts = trans.get("concepts", [])
            for i in range(len(concepts) - 1):
                source_name = concepts[i]
                target_name = concepts[i + 1]

                if source_name not in nodes or target_name not in nodes:
                    continue

                source_id = nodes[source_name].id
                target_id = nodes[target_name].id
                edge_id = self._generate_edge_id(source_id, target_id, "TRANSITIVE")

                if edge_id not in edge_ids:
                    edge_ids.add(edge_id)
                    edges.append(GraphEdge(
                        id=edge_id,
                        source=source_id,
                        target=target_id,
                        relation_type="TRANSITIVE",
                        confidence=trans.get("confidence", 0.3),
                        is_used=False,
                        is_inferred=True,
                        layer=GraphLayer.SEMANTIC.value,  # Transitive = toujours sémantique
                    ))

        graph_data = GraphData(
            nodes=list(nodes.values()),
            edges=edges,
            query_concept_ids=query_concept_ids,
            used_concept_ids=used_concept_ids,
            suggested_concept_ids=suggested_concept_ids,
        )

        logger.info(
            f"[GRAPH-DATA] Transformed: {len(graph_data.nodes)} nodes, "
            f"{len(graph_data.edges)} edges, "
            f"query={len(query_concept_ids)}, used={len(used_concept_ids)}, "
            f"suggested={len(suggested_concept_ids)}"
        )

        return graph_data

    def add_navigation_edges(
        self,
        graph_data: GraphData,
        tenant_id: str = "default",
        max_edges: int = 20
    ) -> GraphData:
        """
        Ajoute les relations de navigation (MENTIONED_IN) au graphe.

        Récupère les concepts qui co-apparaissent dans les mêmes documents
        et ajoute des edges "CO_OCCURS" pour la visualisation.

        ADR: ADR_NAVIGATION_LAYER.md

        Args:
            graph_data: GraphData existant
            tenant_id: Tenant ID
            max_edges: Nombre max d'edges navigation à ajouter

        Returns:
            GraphData enrichi avec les relations navigation
        """
        if not graph_data.nodes:
            return graph_data

        # Récupérer les canonical_ids des noeuds existants
        node_names = [n.name for n in graph_data.nodes]

        # Requête pour trouver les co-occurrences via MENTIONED_IN
        cypher = """
        // Trouver les concepts qui co-apparaissent dans le même document
        UNWIND $names AS name1
        MATCH (c1:CanonicalConcept {canonical_name: name1, tenant_id: $tenant_id})
              -[:MENTIONED_IN]->(ctx:ContextNode {tenant_id: $tenant_id, kind: 'document'})
              <-[:MENTIONED_IN]-(c2:CanonicalConcept {tenant_id: $tenant_id})
        WHERE c1.canonical_name IN $names
          AND c2.canonical_name IN $names
          AND c1.canonical_name < c2.canonical_name  // Éviter doublons

        WITH c1.canonical_name AS source, c2.canonical_name AS target,
             count(DISTINCT ctx) AS doc_count

        WHERE doc_count >= 1

        RETURN source, target, doc_count
        ORDER BY doc_count DESC
        LIMIT $limit
        """

        try:
            results = self.neo4j_client.execute_query(cypher, {
                "names": node_names,
                "tenant_id": tenant_id,
                "limit": max_edges
            })

            # Créer un mapping name -> node_id
            name_to_id = {n.name: n.id for n in graph_data.nodes}

            # Collecter les IDs d'edges existants
            existing_edge_ids = {e.id for e in graph_data.edges}

            # Ajouter les edges navigation
            nav_edges_added = 0
            for record in results:
                source_name = record.get("source")
                target_name = record.get("target")
                doc_count = record.get("doc_count", 1)

                if source_name not in name_to_id or target_name not in name_to_id:
                    continue

                source_id = name_to_id[source_name]
                target_id = name_to_id[target_name]
                edge_id = self._generate_edge_id(source_id, target_id, "CO_OCCURS")

                if edge_id not in existing_edge_ids:
                    existing_edge_ids.add(edge_id)
                    graph_data.edges.append(GraphEdge(
                        id=edge_id,
                        source=source_id,
                        target=target_id,
                        relation_type="CO_OCCURS",
                        confidence=min(1.0, doc_count / 5.0),  # Normaliser
                        is_used=False,
                        is_inferred=False,
                        layer=GraphLayer.NAVIGATION.value,
                    ))
                    nav_edges_added += 1

            if nav_edges_added > 0:
                logger.info(
                    f"[GRAPH-DATA] Added {nav_edges_added} navigation edges (CO_OCCURS)"
                )

        except Exception as e:
            logger.warning(f"[GRAPH-DATA] Failed to add navigation edges: {e}")

        return graph_data


# Singleton instance
_transformer: Optional[GraphDataTransformer] = None


def get_graph_data_transformer() -> GraphDataTransformer:
    """Retourne l'instance singleton du transformer."""
    global _transformer
    if _transformer is None:
        _transformer = GraphDataTransformer()
    return _transformer


def transform_graph_context(
    graph_context: Dict[str, Any],
    used_in_synthesis: List[str] = None,
    tenant_id: str = "default",
    include_navigation: bool = True,
    max_navigation_edges: int = 20
) -> Dict[str, Any]:
    """
    Fonction utilitaire pour transformer un GraphContext en format D3.js.

    Args:
        graph_context: GraphContext.to_dict()
        used_in_synthesis: Concepts utilisés dans la synthèse
        tenant_id: Tenant ID
        include_navigation: Inclure les relations de navigation (CO_OCCURS)
        max_navigation_edges: Nombre max d'edges navigation

    Returns:
        GraphData.to_dict() prêt pour le frontend
    """
    transformer = get_graph_data_transformer()
    graph_data = transformer.transform(
        graph_context,
        used_in_synthesis,
        tenant_id
    )

    # Ajouter les relations de navigation si demandé
    if include_navigation:
        graph_data = transformer.add_navigation_edges(
            graph_data,
            tenant_id=tenant_id,
            max_edges=max_navigation_edges
        )

    return graph_data.to_dict()


__all__ = [
    "GraphDataTransformer",
    "GraphData",
    "GraphNode",
    "GraphEdge",
    "ConceptRole",
    "ConceptType",
    "get_graph_data_transformer",
    "transform_graph_context",
]
