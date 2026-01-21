"""
OSMOSE Scope Layer - Scope Filter Service

Service de filtrage par scope pour le mode Anchored.
Interroge Neo4j pour trouver les documents/sections correspondant au scope demandé.

ADR: doc/ongoing/ADR_SCOPE_VS_ASSERTION_SEPARATION.md

Usage:
    filter = ScopeFilter(neo4j_client, tenant_id)
    doc_ids = await filter.get_documents_by_topic("S/4HANA")
    section_ids = await filter.get_sections_by_scope("security")

Author: Claude Code
Date: 2026-01-21
"""

import logging
from typing import List, Optional, Dict, Any
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class ScopeFilterResult:
    """Résultat d'un filtrage par scope."""
    document_ids: List[str] = field(default_factory=list)
    section_ids: List[str] = field(default_factory=list)
    topic_matched: Optional[str] = None
    scope_keywords_matched: List[str] = field(default_factory=list)
    total_documents: int = 0
    total_sections: int = 0


class ScopeFilter:
    """
    Service de filtrage par scope pour la recherche Anchored.

    Utilise la Scope Layer (DocumentContext.topic, SectionContext.scope_description)
    pour filtrer les résultats de recherche sans polluer le graphe d'assertions.
    """

    def __init__(self, neo4j_client: Any, tenant_id: str = "default"):
        """
        Initialise le service.

        Args:
            neo4j_client: Client Neo4j (async)
            tenant_id: ID tenant
        """
        self.neo4j_client = neo4j_client
        self.tenant_id = tenant_id

    async def filter_by_scope(
        self,
        topic: Optional[str] = None,
        scope_keywords: Optional[List[str]] = None,
        scope_description_contains: Optional[str] = None
    ) -> ScopeFilterResult:
        """
        Filtre les documents et sections par scope.

        Args:
            topic: Topic à rechercher (matching partiel sur DocumentContext.topic)
            scope_keywords: Keywords à rechercher dans scope_description
            scope_description_contains: Texte à rechercher dans scope_description

        Returns:
            ScopeFilterResult avec les IDs de documents et sections correspondants
        """
        result = ScopeFilterResult()

        # 1. Filtrer par topic si spécifié
        if topic:
            doc_ids = await self._get_documents_by_topic(topic)
            result.document_ids.extend(doc_ids)
            result.topic_matched = topic
            result.total_documents = len(doc_ids)
            logger.debug(f"[ScopeFilter] Topic '{topic}' matched {len(doc_ids)} documents")

        # 2. Filtrer par scope_description si spécifié
        if scope_keywords or scope_description_contains:
            section_ids = await self._get_sections_by_scope(
                keywords=scope_keywords,
                contains=scope_description_contains
            )
            result.section_ids.extend(section_ids)
            result.scope_keywords_matched = scope_keywords or []
            result.total_sections = len(section_ids)
            logger.debug(f"[ScopeFilter] Scope matched {len(section_ids)} sections")

        return result

    async def _get_documents_by_topic(self, topic: str) -> List[str]:
        """
        Récupère les document_ids correspondant à un topic.

        Matching: CONTAINS case-insensitive sur DocumentContext.topic
        """
        query = """
        MATCH (dc:DocumentContext)
        WHERE dc.tenant_id = $tenant_id
          AND dc.topic IS NOT NULL
          AND toLower(dc.topic) CONTAINS toLower($topic)
        RETURN DISTINCT dc.doc_id AS doc_id
        """

        try:
            async with self.neo4j_client.session() as session:
                result = await session.run(query, {
                    "tenant_id": self.tenant_id,
                    "topic": topic
                })
                records = await result.data()
                return [r["doc_id"] for r in records if r.get("doc_id")]
        except Exception as e:
            logger.error(f"[ScopeFilter] Failed to filter by topic: {e}")
            return []

    async def _get_sections_by_scope(
        self,
        keywords: Optional[List[str]] = None,
        contains: Optional[str] = None
    ) -> List[str]:
        """
        Récupère les section_ids correspondant au scope.

        Matching:
        - keywords: OR matching sur scope_description
        - contains: CONTAINS matching sur scope_description
        """
        conditions = ["sc.tenant_id = $tenant_id", "sc.scope_description IS NOT NULL"]
        params = {"tenant_id": self.tenant_id}

        if keywords:
            # OR matching pour les keywords
            keyword_conditions = []
            for i, kw in enumerate(keywords):
                param_name = f"kw_{i}"
                keyword_conditions.append(f"toLower(sc.scope_description) CONTAINS toLower(${param_name})")
                params[param_name] = kw
            if keyword_conditions:
                conditions.append(f"({' OR '.join(keyword_conditions)})")

        if contains:
            conditions.append("toLower(sc.scope_description) CONTAINS toLower($contains)")
            params["contains"] = contains

        query = f"""
        MATCH (sc:SectionContext)
        WHERE {' AND '.join(conditions)}
        RETURN DISTINCT sc.context_id AS section_id, sc.doc_id AS doc_id
        """

        try:
            async with self.neo4j_client.session() as session:
                result = await session.run(query, params)
                records = await result.data()
                return [r["section_id"] for r in records if r.get("section_id")]
        except Exception as e:
            logger.error(f"[ScopeFilter] Failed to filter by scope: {e}")
            return []

    async def get_scope_boosted_doc_ids(
        self,
        topic: Optional[str] = None,
        scope_keywords: Optional[List[str]] = None
    ) -> Dict[str, float]:
        """
        Retourne les document_ids avec un score de boost basé sur le scope.

        Utile pour le reranking : documents avec scope matching obtiennent un boost.

        Args:
            topic: Topic à rechercher
            scope_keywords: Keywords de scope

        Returns:
            Dict[doc_id, boost_score] où boost_score est entre 1.0 et 2.0
        """
        result = await self.filter_by_scope(
            topic=topic,
            scope_keywords=scope_keywords
        )

        # Calculer les boosts
        boosts: Dict[str, float] = {}

        # Documents avec topic match: boost 1.5
        for doc_id in result.document_ids:
            boosts[doc_id] = boosts.get(doc_id, 1.0) + 0.5

        # Sections avec scope match: récupérer les doc_ids et boost 1.3
        if result.section_ids:
            section_doc_ids = await self._get_doc_ids_for_sections(result.section_ids)
            for doc_id in section_doc_ids:
                boosts[doc_id] = boosts.get(doc_id, 1.0) + 0.3

        return boosts

    async def _get_doc_ids_for_sections(self, section_ids: List[str]) -> List[str]:
        """Récupère les doc_ids pour une liste de section_ids."""
        if not section_ids:
            return []

        query = """
        MATCH (sc:SectionContext)
        WHERE sc.context_id IN $section_ids
        RETURN DISTINCT sc.doc_id AS doc_id
        """

        try:
            async with self.neo4j_client.session() as session:
                result = await session.run(query, {"section_ids": section_ids})
                records = await result.data()
                return [r["doc_id"] for r in records if r.get("doc_id")]
        except Exception as e:
            logger.error(f"[ScopeFilter] Failed to get doc_ids for sections: {e}")
            return []


def build_qdrant_filter_from_scope(
    scope_result: ScopeFilterResult,
    existing_filter: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """
    Construit un filtre Qdrant à partir d'un résultat de scope.

    Args:
        scope_result: Résultat du filtrage par scope
        existing_filter: Filtre existant à fusionner

    Returns:
        Dict compatible avec filter_params de HybridAnchorSearchService
    """
    filter_params = dict(existing_filter) if existing_filter else {}

    # Ajouter filtre par document_ids si présents
    if scope_result.document_ids:
        # Note: Qdrant supporte le filtrage par liste via "any" match
        # Pour l'instant, on retourne le premier doc_id (simplification)
        # TODO: Implémenter filtrage multi-documents
        filter_params["doc_id"] = scope_result.document_ids[0] if len(scope_result.document_ids) == 1 else None

    return filter_params
