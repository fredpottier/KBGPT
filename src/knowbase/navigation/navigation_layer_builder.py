"""
OSMOSE Navigation Layer Builder

Writer pour créer et gérer la couche de navigation non-sémantique.
ADR: doc/ongoing/ADR_NAVIGATION_LAYER.md

IMPORTANT: Cette couche est pour la NAVIGATION uniquement.
Elle ne doit JAMAIS être utilisée pour le raisonnement sémantique.

Author: Claude Code
Date: 2026-01-01
"""

import logging
from datetime import datetime
from typing import Dict, List, Optional, Any, Tuple
from collections import defaultdict

from knowbase.common.clients.neo4j_client import Neo4jClient, get_neo4j_client
from knowbase.common.context_id import make_context_id, make_section_hash
from knowbase.config.settings import get_settings

from .types import (
    ContextNodeKind,
    DocumentContext,
    SectionContext,
    WindowContext,
    MentionedIn,
    NavigationLayerConfig,
    NAVIGATION_RELATION_TYPES,
)

logger = logging.getLogger(__name__)


class NavigationLayerBuilder:
    """
    Builder pour la couche de navigation OSMOSE.

    Crée et gère les ContextNodes et relations MENTIONED_IN
    pour permettre la navigation corpus-level sans hallucination.

    IMPORTANT:
    - Cette couche est strictement NON-SÉMANTIQUE
    - Elle décrit le CORPUS, pas le MONDE
    - Le RAG ne doit JAMAIS utiliser ces liens pour le raisonnement
    """

    def __init__(
        self,
        neo4j_client: Optional[Neo4jClient] = None,
        config: Optional[NavigationLayerConfig] = None,
        tenant_id: str = "default"
    ):
        """
        Initialise le builder.

        Args:
            neo4j_client: Client Neo4j (default: singleton from env)
            config: Configuration (default: from feature_flags)
            tenant_id: Tenant ID pour isolation
        """
        if neo4j_client:
            self.neo4j = neo4j_client
        else:
            settings = get_settings()
            self.neo4j = get_neo4j_client(
                uri=settings.neo4j_uri,
                user=settings.neo4j_user,
                password=settings.neo4j_password
            )

        self.tenant_id = tenant_id
        self.config = config or NavigationLayerConfig(tenant_id=tenant_id)

        # Stats
        self._stats: Dict[str, int] = defaultdict(int)

        logger.info(
            f"[NavigationLayerBuilder] Initialized (tenant={tenant_id}, "
            f"doc_ctx={self.config.enable_document_context}, "
            f"sec_ctx={self.config.enable_section_context}, "
            f"win_ctx={self.config.enable_window_context})"
        )

    def _execute_query(
        self,
        query: str,
        params: Dict[str, Any]
    ) -> List[Dict[str, Any]]:
        """Exécute une requête Cypher."""
        if not self.neo4j.is_connected():
            logger.error("[NavigationLayerBuilder] Neo4j not connected")
            return []

        try:
            with self.neo4j.driver.session(database=self.neo4j.database) as session:
                result = session.run(query, params)
                return [dict(record) for record in result]
        except Exception as e:
            logger.error(f"[NavigationLayerBuilder] Query failed: {e}")
            return []

    # ========================================================================
    # DocumentContext
    # ========================================================================

    def create_document_context(
        self,
        document_id: str,
        document_name: Optional[str] = None,
        document_type: Optional[str] = None
    ) -> Optional[DocumentContext]:
        """
        Crée un DocumentContext pour un document.

        Args:
            document_id: ID du document
            document_name: Nom du document (optionnel)
            document_type: Type du document (optionnel)

        Returns:
            DocumentContext créé ou None si erreur
        """
        if not self.config.enable_document_context:
            logger.debug("[NavigationLayerBuilder] DocumentContext disabled")
            return None

        ctx = DocumentContext.create(
            document_id=document_id,
            tenant_id=self.tenant_id,
            document_name=document_name,
            document_type=document_type
        )

        query = """
        // Créer ou récupérer le Document
        MERGE (d:Document {document_id: $doc_id, tenant_id: $tenant_id})

        // Créer le DocumentContext
        MERGE (ctx:DocumentContext:ContextNode {context_id: $context_id})
        ON CREATE SET
            ctx.kind = $kind,
            ctx.tenant_id = $tenant_id,
            ctx.doc_id = $doc_id,
            ctx.created_at = datetime(),
            ctx.document_name = $document_name,
            ctx.document_type = $document_type

        // Lier au Document
        MERGE (ctx)-[:IN_DOCUMENT]->(d)

        RETURN ctx.context_id AS context_id
        """

        params = {
            "context_id": ctx.context_id,
            "kind": ctx.kind.value,
            "tenant_id": self.tenant_id,
            "doc_id": document_id,
            "document_name": document_name,
            "document_type": document_type,
        }

        result = self._execute_query(query, params)

        if result:
            self._stats["document_contexts_created"] += 1
            logger.debug(f"[NavigationLayerBuilder] Created DocumentContext: {ctx.context_id}")
            return ctx

        return None

    # ========================================================================
    # SectionContext
    # ========================================================================

    def create_section_context(
        self,
        document_id: str,
        section_path: str,
        section_level: int = 0
    ) -> Optional[SectionContext]:
        """
        Crée un SectionContext pour une section de document.

        Args:
            document_id: ID du document
            section_path: Chemin de la section (ex: "1.2.3 Security Architecture")
            section_level: Niveau hiérarchique (0 = root)

        Returns:
            SectionContext créé ou None si erreur
        """
        if not self.config.enable_section_context:
            logger.debug("[NavigationLayerBuilder] SectionContext disabled")
            return None

        ctx = SectionContext.create(
            document_id=document_id,
            section_path=section_path,
            tenant_id=self.tenant_id,
            section_level=section_level
        )

        query = """
        // Récupérer le Document
        MATCH (d:Document {document_id: $doc_id, tenant_id: $tenant_id})

        // Créer le SectionContext
        MERGE (ctx:SectionContext:ContextNode {context_id: $context_id})
        ON CREATE SET
            ctx.kind = $kind,
            ctx.tenant_id = $tenant_id,
            ctx.doc_id = $doc_id,
            ctx.section_path = $section_path,
            ctx.section_hash = $section_hash,
            ctx.section_level = $section_level,
            ctx.created_at = datetime()

        // Lier au Document
        MERGE (ctx)-[:IN_DOCUMENT]->(d)

        RETURN ctx.context_id AS context_id
        """

        params = {
            "context_id": ctx.context_id,
            "kind": ctx.kind.value,
            "tenant_id": self.tenant_id,
            "doc_id": document_id,
            "section_path": section_path,
            "section_hash": ctx.section_hash,
            "section_level": section_level,
        }

        result = self._execute_query(query, params)

        if result:
            self._stats["section_contexts_created"] += 1
            logger.debug(f"[NavigationLayerBuilder] Created SectionContext: {ctx.context_id}")
            return ctx

        return None

    # ========================================================================
    # WindowContext (optionnel, désactivé par défaut)
    # ========================================================================

    def create_window_context(
        self,
        chunk_id: str,
        document_id: str,
        window_index: int = 0
    ) -> Optional[WindowContext]:
        """
        Crée un WindowContext pour un chunk.

        ATTENTION: Cette méthode est désactivée par défaut (ADR).
        WindowContext a une cardinalité linéaire avec le corpus.

        Args:
            chunk_id: ID du chunk
            document_id: ID du document
            window_index: Index du chunk dans le document

        Returns:
            WindowContext créé ou None si désactivé/erreur
        """
        if not self.config.enable_window_context:
            logger.debug("[NavigationLayerBuilder] WindowContext disabled (ADR)")
            return None

        # Vérifier le cap par document
        existing_count = self._count_windows_for_document(document_id)
        if existing_count >= self.config.max_windows_per_document:
            logger.warning(
                f"[NavigationLayerBuilder] WindowContext cap reached for {document_id} "
                f"({existing_count}/{self.config.max_windows_per_document})"
            )
            self._stats["window_contexts_capped"] += 1
            return None

        ctx = WindowContext.create(
            chunk_id=chunk_id,
            document_id=document_id,
            tenant_id=self.tenant_id,
            window_index=window_index
        )

        query = """
        // Récupérer le Document et le Chunk
        MATCH (d:Document {document_id: $doc_id, tenant_id: $tenant_id})
        OPTIONAL MATCH (ch:DocumentChunk {chunk_id: $chunk_id, tenant_id: $tenant_id})

        // Créer le WindowContext
        MERGE (ctx:WindowContext:ContextNode {context_id: $context_id})
        ON CREATE SET
            ctx.kind = $kind,
            ctx.tenant_id = $tenant_id,
            ctx.doc_id = $doc_id,
            ctx.chunk_id = $chunk_id,
            ctx.window_index = $window_index,
            ctx.created_at = datetime()

        // Lier au Document
        MERGE (ctx)-[:IN_DOCUMENT]->(d)

        // Lier au Chunk si existe
        FOREACH (c IN CASE WHEN ch IS NOT NULL THEN [ch] ELSE [] END |
            MERGE (ctx)-[:CENTERED_ON]->(c)
        )

        RETURN ctx.context_id AS context_id
        """

        params = {
            "context_id": ctx.context_id,
            "kind": ctx.kind.value,
            "tenant_id": self.tenant_id,
            "doc_id": document_id,
            "chunk_id": chunk_id,
            "window_index": window_index,
        }

        result = self._execute_query(query, params)

        if result:
            self._stats["window_contexts_created"] += 1
            logger.debug(f"[NavigationLayerBuilder] Created WindowContext: {ctx.context_id}")
            return ctx

        return None

    def _count_windows_for_document(self, document_id: str) -> int:
        """Compte les WindowContext existants pour un document."""
        query = """
        MATCH (ctx:WindowContext:ContextNode {doc_id: $doc_id, tenant_id: $tenant_id})
        RETURN count(ctx) AS count
        """
        result = self._execute_query(query, {
            "doc_id": document_id,
            "tenant_id": self.tenant_id
        })
        return result[0]["count"] if result else 0

    # ========================================================================
    # MENTIONED_IN Relations
    # ========================================================================

    def link_concept_to_context(
        self,
        concept_id: str,
        context_id: str,
        count: int = 1
    ) -> bool:
        """
        Crée une relation MENTIONED_IN entre un concept et un contexte.

        Args:
            concept_id: canonical_id du CanonicalConcept
            context_id: context_id du ContextNode

        Returns:
            True si créé/mis à jour, False sinon
        """
        query = """
        MATCH (c:CanonicalConcept {canonical_id: $concept_id, tenant_id: $tenant_id})
        MATCH (ctx:ContextNode {context_id: $context_id, tenant_id: $tenant_id})

        MERGE (c)-[r:MENTIONED_IN]->(ctx)
        ON CREATE SET
            r.count = $count,
            r.weight = 0.0,
            r.first_seen = datetime()
        ON MATCH SET
            r.count = r.count + $count

        RETURN r.count AS total_count
        """

        result = self._execute_query(query, {
            "concept_id": concept_id,
            "context_id": context_id,
            "tenant_id": self.tenant_id,
            "count": count,
        })

        if result:
            self._stats["mentions_created"] += 1
            return True
        return False

    def link_concepts_to_document(
        self,
        document_id: str,
        concept_ids: List[str],
        concept_counts: Optional[Dict[str, int]] = None
    ) -> int:
        """
        Lie plusieurs concepts à un DocumentContext.

        Args:
            document_id: ID du document
            concept_ids: Liste des canonical_id des concepts
            concept_counts: Optionnel - comptage par concept

        Returns:
            Nombre de liens créés
        """
        if not concept_ids:
            return 0

        context_id = f"doc:{document_id}"
        counts = concept_counts or {}

        # Batch upsert
        query = """
        UNWIND $concepts AS concept_data
        MATCH (c:CanonicalConcept {canonical_id: concept_data.id, tenant_id: $tenant_id})
        MATCH (ctx:ContextNode {context_id: $context_id, tenant_id: $tenant_id})

        MERGE (c)-[r:MENTIONED_IN]->(ctx)
        ON CREATE SET
            r.count = concept_data.count,
            r.weight = 0.0,
            r.first_seen = datetime()
        ON MATCH SET
            r.count = r.count + concept_data.count

        RETURN count(r) AS links_created
        """

        concepts_data = [
            {"id": cid, "count": counts.get(cid, 1)}
            for cid in concept_ids
        ]

        result = self._execute_query(query, {
            "concepts": concepts_data,
            "context_id": context_id,
            "tenant_id": self.tenant_id,
        })

        links = result[0]["links_created"] if result else 0
        self._stats["mentions_created"] += links
        return links

    def link_concepts_to_section(
        self,
        document_id: str,
        section_path: str,
        concept_ids: List[str],
        concept_counts: Optional[Dict[str, int]] = None
    ) -> int:
        """
        Lie plusieurs concepts à un SectionContext.

        Args:
            document_id: ID du document
            section_path: Chemin de la section
            concept_ids: Liste des canonical_id des concepts
            concept_counts: Optionnel - comptage par concept

        Returns:
            Nombre de liens créés
        """
        if not concept_ids:
            return 0

        # Utilise helper partagé pour cohérence Neo4j ↔ Qdrant
        context_id = make_context_id(document_id, section_path)
        counts = concept_counts or {}

        # Batch upsert
        query = """
        UNWIND $concepts AS concept_data
        MATCH (c:CanonicalConcept {canonical_id: concept_data.id, tenant_id: $tenant_id})
        MATCH (ctx:ContextNode {context_id: $context_id, tenant_id: $tenant_id})

        MERGE (c)-[r:MENTIONED_IN]->(ctx)
        ON CREATE SET
            r.count = concept_data.count,
            r.weight = 0.0,
            r.first_seen = datetime()
        ON MATCH SET
            r.count = r.count + concept_data.count

        RETURN count(r) AS links_created
        """

        concepts_data = [
            {"id": cid, "count": counts.get(cid, 1)}
            for cid in concept_ids
        ]

        result = self._execute_query(query, {
            "concepts": concepts_data,
            "context_id": context_id,
            "tenant_id": self.tenant_id,
        })

        links = result[0]["links_created"] if result else 0
        self._stats["mentions_created"] += links
        return links

    # ========================================================================
    # Compute Weights
    # ========================================================================

    def compute_weights(self, document_id: Optional[str] = None) -> int:
        """
        Calcule les poids normalisés pour les relations MENTIONED_IN.

        Le poids est la fréquence normalisée par contexte:
        weight = count / max_count_in_context

        Args:
            document_id: Optionnel - limiter à un document

        Returns:
            Nombre de relations mises à jour
        """
        if document_id:
            where_clause = "WHERE ctx.doc_id = $doc_id"
            params = {"tenant_id": self.tenant_id, "doc_id": document_id}
        else:
            where_clause = ""
            params = {"tenant_id": self.tenant_id}

        query = f"""
        // Pour chaque ContextNode, calculer le max count
        MATCH (ctx:ContextNode {{tenant_id: $tenant_id}})
        {where_clause}
        MATCH (c:CanonicalConcept)-[r:MENTIONED_IN]->(ctx)

        WITH ctx, max(r.count) AS max_count

        // Mettre à jour les poids
        MATCH (c2:CanonicalConcept)-[r2:MENTIONED_IN]->(ctx)
        SET r2.weight = toFloat(r2.count) / toFloat(max_count)

        RETURN count(r2) AS updated
        """

        result = self._execute_query(query, params)
        updated = result[0]["updated"] if result else 0

        logger.info(f"[NavigationLayerBuilder] Computed weights for {updated} relations")
        return updated

    # ========================================================================
    # Build Navigation Layer for Document
    # ========================================================================

    def build_for_document(
        self,
        document_id: str,
        document_name: Optional[str] = None,
        document_type: Optional[str] = None,
        sections: Optional[List[Dict[str, Any]]] = None,
        concept_mentions: Optional[Dict[str, List[str]]] = None
    ) -> Dict[str, Any]:
        """
        Construit la Navigation Layer complète pour un document.

        Args:
            document_id: ID du document
            document_name: Nom du document
            document_type: Type du document
            sections: Liste de sections [{"path": "...", "level": 0, "concept_ids": [...]}]
            concept_mentions: Map context_id → [concept_ids]

        Returns:
            Stats de construction
        """
        logger.info(f"[NavigationLayerBuilder] Building navigation layer for {document_id}")

        # Reset stats
        self._stats = defaultdict(int)

        # 1. Créer DocumentContext
        doc_ctx = self.create_document_context(
            document_id=document_id,
            document_name=document_name,
            document_type=document_type
        )

        # 2. Créer SectionContexts
        if sections:
            for section in sections:
                sec_ctx = self.create_section_context(
                    document_id=document_id,
                    section_path=section.get("path", ""),
                    section_level=section.get("level", 0)
                )

                # Lier concepts à la section
                concept_ids = section.get("concept_ids", [])
                if concept_ids and sec_ctx:
                    self.link_concepts_to_section(
                        document_id=document_id,
                        section_path=section["path"],
                        concept_ids=concept_ids
                    )

        # 3. Lier concepts au DocumentContext
        if concept_mentions and doc_ctx:
            doc_concept_ids = concept_mentions.get(doc_ctx.context_id, [])
            if doc_concept_ids:
                self.link_concepts_to_document(
                    document_id=document_id,
                    concept_ids=doc_concept_ids
                )

        # 4. Calculer les poids
        self.compute_weights(document_id=document_id)

        # 5. Appliquer le budget top-N (supprimer mentions excédentaires)
        pruned = self._enforce_mention_budget(document_id=document_id)
        if pruned > 0:
            logger.info(
                f"[NavigationLayerBuilder] Pruned {pruned} excess mentions "
                f"(budget={self.config.max_mentions_per_concept})"
            )

        stats = dict(self._stats)
        logger.info(
            f"[NavigationLayerBuilder] Built navigation layer for {document_id}: "
            f"{stats}"
        )

        return stats

    def _enforce_mention_budget(self, document_id: Optional[str] = None) -> int:
        """
        Applique le budget max_mentions_per_concept.

        Pour chaque concept ayant plus de N mentions, supprime les moins
        pertinentes (weight le plus bas).

        ADR: Les budgets évitent l'explosion de la Navigation Layer.

        Args:
            document_id: Optionnel - limiter à un document

        Returns:
            Nombre de relations supprimées
        """
        max_mentions = self.config.max_mentions_per_concept

        # Construire le filtre optionnel par document
        if document_id:
            where_clause = "WHERE ctx.doc_id = $doc_id"
            params = {"tenant_id": self.tenant_id, "doc_id": document_id, "max_mentions": max_mentions}
        else:
            where_clause = ""
            params = {"tenant_id": self.tenant_id, "max_mentions": max_mentions}

        # Requête pour identifier et supprimer les mentions excédentaires
        # Garde les top-N par weight pour chaque concept
        query = f"""
        // Trouver concepts avec trop de mentions
        MATCH (c:CanonicalConcept {{tenant_id: $tenant_id}})-[r:MENTIONED_IN]->(ctx:ContextNode {{tenant_id: $tenant_id}})
        {where_clause}
        WITH c, count(r) AS mention_count
        WHERE mention_count > $max_mentions

        // Pour chaque concept, collecter ses mentions triées par weight
        MATCH (c)-[r:MENTIONED_IN]->(ctx:ContextNode {{tenant_id: $tenant_id}})
        {where_clause}
        WITH c, r, ctx
        ORDER BY r.weight DESC

        // Collecter toutes les mentions, garder les top-N
        WITH c, collect(r) AS all_mentions
        WITH c, all_mentions[$max_mentions..] AS to_delete

        // Supprimer les mentions excédentaires
        UNWIND to_delete AS rel
        DELETE rel

        RETURN count(*) AS deleted
        """

        result = self._execute_query(query, params)
        deleted = result[0]["deleted"] if result and result[0].get("deleted") else 0

        self._stats["mentions_pruned"] = deleted
        return deleted

    # ========================================================================
    # Stats & Info
    # ========================================================================

    def get_stats(self) -> Dict[str, int]:
        """Retourne les statistiques de construction."""
        return dict(self._stats)

    def reset_stats(self) -> None:
        """Reset les statistiques."""
        self._stats = defaultdict(int)

    def close(self) -> None:
        """Ferme la connexion Neo4j."""
        if self.neo4j:
            self.neo4j.close()


# ============================================================================
# Singleton
# ============================================================================

_builder_instance: Optional[NavigationLayerBuilder] = None


def get_navigation_layer_builder(
    tenant_id: str = "default",
    config: Optional[NavigationLayerConfig] = None
) -> NavigationLayerBuilder:
    """
    Récupère l'instance singleton du builder.

    Args:
        tenant_id: Tenant ID
        config: Configuration (optionnel)

    Returns:
        NavigationLayerBuilder instance
    """
    global _builder_instance

    if _builder_instance is None or _builder_instance.tenant_id != tenant_id:
        _builder_instance = NavigationLayerBuilder(
            tenant_id=tenant_id,
            config=config
        )

    return _builder_instance
