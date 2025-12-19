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
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set
from enum import Enum

from knowbase.common.logging import setup_logging
from knowbase.config.settings import get_settings
from knowbase.semantic.inference import InferenceEngine, InsightType

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
    """

    def __init__(self):
        self._inference_engine: Optional[InferenceEngine] = None
        self._neo4j_client = None

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

    async def extract_concepts_from_query(
        self,
        query: str,
        tenant_id: str = "default"
    ) -> List[str]:
        """
        Extrait les concepts pertinents de la question.

        Utilise une recherche fuzzy dans le KG pour identifier
        les concepts mentionnés dans la question.
        """
        # Normaliser la query
        query_lower = query.lower()
        words = set(query_lower.split())

        # Chercher les concepts qui matchent des mots de la query
        cypher = """
        MATCH (c:CanonicalConcept)
        WHERE c.tenant_id = $tenant_id
        RETURN c.canonical_name AS name, c.concept_type AS type
        LIMIT 500
        """

        try:
            results = self.neo4j_client.execute_query(cypher, {"tenant_id": tenant_id})

            matched_concepts = []
            for record in results:
                concept_name = record.get("name", "")
                if not concept_name:
                    continue

                concept_lower = concept_name.lower()

                # Match exact ou partiel
                if concept_lower in query_lower:
                    matched_concepts.append(concept_name)
                elif any(word in concept_lower for word in words if len(word) > 3):
                    matched_concepts.append(concept_name)

            logger.debug(f"[OSMOSE] Query concepts extracted: {matched_concepts[:5]}")
            return matched_concepts[:5]  # Top 5 concepts

        except Exception as e:
            logger.warning(f"[OSMOSE] Failed to extract query concepts: {e}")
            return []

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
