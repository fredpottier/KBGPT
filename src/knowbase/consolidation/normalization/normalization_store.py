"""
NormalizationStore - Gestion Neo4j pour MarkerMention et CanonicalMarker.

ADR: doc/ongoing/ADR_MARKER_NORMALIZATION_LAYER.md

Schéma Neo4j:
- (:MarkerMention) - Mentions brutes extraites des documents
- (:CanonicalMarker) - Formes normalisées
- (:MarkerMention)-[:CANONICALIZES_TO]->(:CanonicalMarker)
- (:Document)-[:HAS_MARKER_MENTION]->(:MarkerMention)
"""

from __future__ import annotations
from typing import Any, Dict, List, Optional, Tuple
import logging

from knowbase.consolidation.normalization.models import (
    MarkerMention,
    CanonicalMarker,
    NormalizationStatus,
    LexicalShape,
)

logger = logging.getLogger(__name__)


class NormalizationStore:
    """
    Gestionnaire Neo4j pour la Marker Normalization Layer.

    Gère:
    - Création/récupération de MarkerMention nodes
    - Création/récupération de CanonicalMarker nodes
    - Relations CANONICALIZES_TO entre mentions et canoniques
    - Requêtes de recherche et statistiques
    """

    def __init__(self, tenant_id: str = "default"):
        self.tenant_id = tenant_id
        self._neo4j_client = None

    def _get_neo4j_client(self):
        """Lazy init du client Neo4j."""
        if self._neo4j_client is None:
            from knowbase.common.clients.neo4j_client import get_neo4j_client
            from knowbase.config.settings import get_settings

            settings = get_settings()
            self._neo4j_client = get_neo4j_client(
                uri=settings.neo4j_uri,
                user=settings.neo4j_user,
                password=settings.neo4j_password,
                database="neo4j"
            )
        return self._neo4j_client

    # =========================================================================
    # Schema & Index Management
    # =========================================================================

    async def ensure_schema(self) -> None:
        """
        Crée les indexes et constraints nécessaires.
        """
        client = self._get_neo4j_client()

        queries = [
            # Index sur MarkerMention
            """
            CREATE INDEX mm_raw_text IF NOT EXISTS
            FOR (mm:MarkerMention) ON (mm.raw_text, mm.tenant_id)
            """,
            """
            CREATE INDEX mm_doc_id IF NOT EXISTS
            FOR (mm:MarkerMention) ON (mm.doc_id)
            """,
            """
            CREATE INDEX mm_status IF NOT EXISTS
            FOR (mm:MarkerMention) ON (mm.normalization_status)
            """,
            # Index sur CanonicalMarker
            """
            CREATE INDEX cm_canonical_form IF NOT EXISTS
            FOR (cm:CanonicalMarker) ON (cm.canonical_form, cm.tenant_id)
            """,
            """
            CREATE INDEX cm_entity_anchor IF NOT EXISTS
            FOR (cm:CanonicalMarker) ON (cm.entity_anchor)
            """,
            # Constraint d'unicité sur canonical_form par tenant
            """
            CREATE CONSTRAINT cm_unique IF NOT EXISTS
            FOR (cm:CanonicalMarker) REQUIRE (cm.canonical_form, cm.tenant_id) IS UNIQUE
            """,
        ]

        try:
            with client.driver.session(database="neo4j") as session:
                for query in queries:
                    try:
                        session.run(query)
                    except Exception as e:
                        # Ignorer si index/constraint existe déjà
                        if "already exists" not in str(e).lower():
                            logger.warning(f"[NormalizationStore] Schema query warning: {e}")
            logger.info("[NormalizationStore] Schema indexes created/verified")
        except Exception as e:
            logger.error(f"[NormalizationStore] Schema creation failed: {e}")

    # =========================================================================
    # MarkerMention Operations
    # =========================================================================

    async def create_mention(self, mention: MarkerMention) -> MarkerMention:
        """
        Crée un nouveau noeud MarkerMention.

        Args:
            mention: MarkerMention à créer

        Returns:
            MarkerMention créé avec ID
        """
        client = self._get_neo4j_client()

        query = """
        CREATE (mm:MarkerMention {
            id: $id,
            raw_text: $raw_text,
            lexical_shape: $lexical_shape,
            doc_id: $doc_id,
            source_location: $source_location,
            evidence_text: $evidence_text,
            page_index: $page_index,
            zone: $zone,
            confidence_extraction: $confidence_extraction,
            extracted_by: $extracted_by,
            normalization_status: $normalization_status,
            canonical_id: $canonical_id,
            tenant_id: $tenant_id,
            created_at: datetime()
        })
        RETURN mm
        """

        try:
            data = mention.to_dict()
            with client.driver.session(database="neo4j") as session:
                session.run(query, **data)
                logger.debug(f"[NormalizationStore] Created mention: {mention.raw_text}")
                return mention
        except Exception as e:
            logger.error(f"[NormalizationStore] Failed to create mention: {e}")
            raise

    async def create_mentions_batch(
        self,
        mentions: List[MarkerMention],
    ) -> int:
        """
        Crée plusieurs MarkerMention en batch.

        Args:
            mentions: Liste de mentions à créer

        Returns:
            Nombre de mentions créées
        """
        if not mentions:
            return 0

        client = self._get_neo4j_client()

        query = """
        UNWIND $mentions AS m
        CREATE (mm:MarkerMention {
            id: m.id,
            raw_text: m.raw_text,
            lexical_shape: m.lexical_shape,
            doc_id: m.doc_id,
            source_location: m.source_location,
            evidence_text: m.evidence_text,
            page_index: m.page_index,
            zone: m.zone,
            confidence_extraction: m.confidence_extraction,
            extracted_by: m.extracted_by,
            normalization_status: m.normalization_status,
            canonical_id: m.canonical_id,
            tenant_id: m.tenant_id,
            created_at: datetime()
        })
        RETURN count(mm) AS created
        """

        try:
            mentions_data = [m.to_dict() for m in mentions]
            with client.driver.session(database="neo4j") as session:
                result = session.run(query, mentions=mentions_data)
                record = result.single()
                count = record["created"] if record else 0
                logger.info(f"[NormalizationStore] Created {count} mentions in batch")
                return count
        except Exception as e:
            logger.error(f"[NormalizationStore] Batch mention creation failed: {e}")
            return 0

    async def get_mentions_by_doc(
        self,
        doc_id: str,
    ) -> List[MarkerMention]:
        """
        Récupère toutes les mentions d'un document.

        Args:
            doc_id: ID du document

        Returns:
            Liste de MarkerMention
        """
        client = self._get_neo4j_client()

        query = """
        MATCH (mm:MarkerMention {doc_id: $doc_id, tenant_id: $tenant_id})
        RETURN mm
        ORDER BY mm.page_index, mm.raw_text
        """

        try:
            with client.driver.session(database="neo4j") as session:
                result = session.run(query, doc_id=doc_id, tenant_id=self.tenant_id)
                mentions = []
                for record in result:
                    mm_data = dict(record["mm"])
                    mentions.append(MarkerMention.from_dict(mm_data))
                return mentions
        except Exception as e:
            logger.error(f"[NormalizationStore] Failed to get mentions for doc {doc_id}: {e}")
            return []

    async def get_unresolved_mentions(
        self,
        limit: int = 100,
    ) -> List[MarkerMention]:
        """
        Récupère les mentions non résolues (en attente de normalisation).

        Args:
            limit: Nombre max de mentions

        Returns:
            Liste de MarkerMention non résolues
        """
        client = self._get_neo4j_client()

        query = """
        MATCH (mm:MarkerMention {
            normalization_status: 'unresolved',
            tenant_id: $tenant_id
        })
        RETURN mm
        ORDER BY mm.created_at DESC
        LIMIT $limit
        """

        try:
            with client.driver.session(database="neo4j") as session:
                result = session.run(query, tenant_id=self.tenant_id, limit=limit)
                mentions = []
                for record in result:
                    mm_data = dict(record["mm"])
                    mentions.append(MarkerMention.from_dict(mm_data))
                return mentions
        except Exception as e:
            logger.error(f"[NormalizationStore] Failed to get unresolved mentions: {e}")
            return []

    async def get_mention_by_id(
        self,
        mention_id: str,
    ) -> Optional[MarkerMention]:
        """
        Récupère une mention par son ID.

        Args:
            mention_id: ID de la mention

        Returns:
            MarkerMention ou None
        """
        client = self._get_neo4j_client()

        query = """
        MATCH (mm:MarkerMention {id: $mention_id, tenant_id: $tenant_id})
        RETURN mm
        """

        try:
            with client.driver.session(database="neo4j") as session:
                result = session.run(query, mention_id=mention_id, tenant_id=self.tenant_id)
                record = result.single()
                if record:
                    return MarkerMention.from_dict(dict(record["mm"]))
                return None
        except Exception as e:
            logger.error(f"[NormalizationStore] Failed to get mention {mention_id}: {e}")
            return None

    # =========================================================================
    # CanonicalMarker Operations
    # =========================================================================

    async def ensure_canonical_marker(
        self,
        canonical_form: str,
        marker_type: str = "",
        entity_anchor: str = "",
        created_by: str = "system",
        confidence: float = 1.0,
        dimensions: Optional[Dict[str, str]] = None,
    ) -> CanonicalMarker:
        """
        Crée ou récupère un CanonicalMarker.

        MERGE sur canonical_form + tenant_id.

        Args:
            canonical_form: Forme normalisée
            marker_type: Type de marker
            entity_anchor: Entité parente
            created_by: Source de création
            confidence: Confiance
            dimensions: Dimensions additionnelles

        Returns:
            CanonicalMarker créé ou existant
        """
        client = self._get_neo4j_client()

        query = """
        MERGE (cm:CanonicalMarker {
            canonical_form: $canonical_form,
            tenant_id: $tenant_id
        })
        ON CREATE SET
            cm.id = $id,
            cm.marker_type = $marker_type,
            cm.entity_anchor = $entity_anchor,
            cm.created_by = $created_by,
            cm.confidence = $confidence,
            cm.dimensions = $dimensions,
            cm.mention_count = 0,
            cm.document_count = 0,
            cm.created_at = datetime()
        ON MATCH SET
            cm.updated_at = datetime()
        RETURN cm
        """

        import uuid
        cm_id = f"cm_{uuid.uuid4().hex[:12]}"

        try:
            with client.driver.session(database="neo4j") as session:
                result = session.run(
                    query,
                    id=cm_id,
                    canonical_form=canonical_form,
                    tenant_id=self.tenant_id,
                    marker_type=marker_type,
                    entity_anchor=entity_anchor,
                    created_by=created_by,
                    confidence=confidence,
                    dimensions=dimensions or {},
                )
                record = result.single()
                if record:
                    cm_data = dict(record["cm"])
                    return CanonicalMarker.from_dict(cm_data)

        except Exception as e:
            logger.error(f"[NormalizationStore] Failed to ensure canonical: {e}")

        # Fallback
        return CanonicalMarker(
            id=cm_id,
            canonical_form=canonical_form,
            tenant_id=self.tenant_id,
        )

    async def get_canonical_by_form(
        self,
        canonical_form: str,
    ) -> Optional[CanonicalMarker]:
        """
        Récupère un CanonicalMarker par sa forme.

        Args:
            canonical_form: Forme normalisée

        Returns:
            CanonicalMarker ou None
        """
        client = self._get_neo4j_client()

        query = """
        MATCH (cm:CanonicalMarker {
            canonical_form: $canonical_form,
            tenant_id: $tenant_id
        })
        RETURN cm
        """

        try:
            with client.driver.session(database="neo4j") as session:
                result = session.run(
                    query,
                    canonical_form=canonical_form,
                    tenant_id=self.tenant_id
                )
                record = result.single()
                if record:
                    return CanonicalMarker.from_dict(dict(record["cm"]))
                return None
        except Exception as e:
            logger.error(f"[NormalizationStore] Failed to get canonical: {e}")
            return None

    async def list_canonical_markers(
        self,
        entity_anchor: Optional[str] = None,
        limit: int = 100,
    ) -> List[CanonicalMarker]:
        """
        Liste les CanonicalMarkers.

        Args:
            entity_anchor: Filtre par entity anchor
            limit: Nombre max

        Returns:
            Liste de CanonicalMarker
        """
        client = self._get_neo4j_client()

        if entity_anchor:
            query = """
            MATCH (cm:CanonicalMarker {tenant_id: $tenant_id})
            WHERE cm.entity_anchor = $entity_anchor
            RETURN cm
            ORDER BY cm.mention_count DESC
            LIMIT $limit
            """
            params = {"tenant_id": self.tenant_id, "entity_anchor": entity_anchor, "limit": limit}
        else:
            query = """
            MATCH (cm:CanonicalMarker {tenant_id: $tenant_id})
            RETURN cm
            ORDER BY cm.mention_count DESC
            LIMIT $limit
            """
            params = {"tenant_id": self.tenant_id, "limit": limit}

        try:
            with client.driver.session(database="neo4j") as session:
                result = session.run(query, **params)
                canonicals = []
                for record in result:
                    cm_data = dict(record["cm"])
                    canonicals.append(CanonicalMarker.from_dict(cm_data))
                return canonicals
        except Exception as e:
            logger.error(f"[NormalizationStore] Failed to list canonicals: {e}")
            return []

    # =========================================================================
    # Normalization Link Operations
    # =========================================================================

    async def link_mention_to_canonical(
        self,
        mention_id: str,
        canonical_id: str,
        rule_id: str = "",
        confidence: float = 1.0,
    ) -> bool:
        """
        Crée la relation CANONICALIZES_TO entre une mention et un canonical.

        Args:
            mention_id: ID de la MarkerMention
            canonical_id: ID du CanonicalMarker
            rule_id: ID de la règle appliquée
            confidence: Confiance dans la normalisation

        Returns:
            True si succès
        """
        client = self._get_neo4j_client()

        query = """
        MATCH (mm:MarkerMention {id: $mention_id, tenant_id: $tenant_id})
        MATCH (cm:CanonicalMarker {id: $canonical_id, tenant_id: $tenant_id})
        MERGE (mm)-[r:CANONICALIZES_TO]->(cm)
        ON CREATE SET
            r.rule_id = $rule_id,
            r.confidence = $confidence,
            r.applied_at = datetime()
        SET mm.normalization_status = 'resolved',
            mm.canonical_id = cm.id,
            cm.mention_count = cm.mention_count + 1
        RETURN r IS NOT NULL AS created
        """

        try:
            with client.driver.session(database="neo4j") as session:
                result = session.run(
                    query,
                    mention_id=mention_id,
                    canonical_id=canonical_id,
                    rule_id=rule_id,
                    confidence=confidence,
                    tenant_id=self.tenant_id
                )
                record = result.single()
                return record["created"] if record else False
        except Exception as e:
            logger.error(f"[NormalizationStore] Failed to link mention to canonical: {e}")
            return False

    async def update_mention_status(
        self,
        mention_id: str,
        status: NormalizationStatus,
        reason: str = "",
    ) -> bool:
        """
        Met à jour le statut d'une mention.

        Args:
            mention_id: ID de la mention
            status: Nouveau statut
            reason: Raison du changement

        Returns:
            True si succès
        """
        client = self._get_neo4j_client()

        query = """
        MATCH (mm:MarkerMention {id: $mention_id, tenant_id: $tenant_id})
        SET mm.normalization_status = $status,
            mm.status_reason = $reason,
            mm.updated_at = datetime()
        RETURN mm.id AS id
        """

        try:
            with client.driver.session(database="neo4j") as session:
                result = session.run(
                    query,
                    mention_id=mention_id,
                    status=status.value,
                    reason=reason,
                    tenant_id=self.tenant_id
                )
                record = result.single()
                return record is not None
        except Exception as e:
            logger.error(f"[NormalizationStore] Failed to update mention status: {e}")
            return False

    # =========================================================================
    # Clustering & Suggestions (Phase 5)
    # =========================================================================

    async def get_marker_clusters(
        self,
        min_documents: int = 2,
        limit: int = 20,
    ) -> List[Dict[str, Any]]:
        """
        Récupère les clusters de markers non résolus.

        Identifie les markers qui co-occurrent fréquemment dans les mêmes
        documents et pourraient partager une forme canonique.

        Args:
            min_documents: Nombre minimum de documents pour un cluster
            limit: Nombre max de clusters

        Returns:
            Liste de clusters avec raw_markers, document_count, common_entity
        """
        client = self._get_neo4j_client()

        query = """
        // Trouver les mentions non résolues groupées par raw_text
        MATCH (mm:MarkerMention {
            normalization_status: 'unresolved',
            tenant_id: $tenant_id
        })
        WITH mm.raw_text AS raw_marker, collect(DISTINCT mm.doc_id) AS doc_ids
        WHERE size(doc_ids) >= $min_documents

        // Chercher un entity anchor commun dans ces documents
        OPTIONAL MATCH (pc:ProtoConcept)-[:EXTRACTED_FROM]->(d:Document)
        WHERE d.doc_id IN doc_ids
          AND pc.tenant_id = $tenant_id
          AND pc.role IN ['primary', 'subject']
        WITH raw_marker, doc_ids,
             collect(DISTINCT pc.concept_name)[0] AS common_entity

        RETURN {
            raw_markers: collect(raw_marker),
            document_count: size(doc_ids),
            common_entity: common_entity
        } AS cluster
        ORDER BY size(doc_ids) DESC
        LIMIT $limit
        """

        try:
            with client.driver.session(database="neo4j") as session:
                result = session.run(
                    query,
                    tenant_id=self.tenant_id,
                    min_documents=min_documents,
                    limit=limit
                )
                clusters = []
                for record in result:
                    cluster_data = dict(record["cluster"])
                    clusters.append(cluster_data)
                return clusters
        except Exception as e:
            logger.error(f"[NormalizationStore] Failed to get clusters: {e}")
            return []

    # =========================================================================
    # Statistics & Queries
    # =========================================================================

    async def get_normalization_stats(self) -> Dict[str, Any]:
        """
        Récupère les statistiques de normalisation.

        Returns:
            Dict avec statistiques (total, resolved, unresolved, etc.)
        """
        client = self._get_neo4j_client()

        query = """
        // Compter les mentions par statut
        OPTIONAL MATCH (mm:MarkerMention {tenant_id: $tenant_id})
        WITH
            count(mm) AS total_mentions,
            count(CASE WHEN mm.normalization_status = 'resolved' THEN 1 END) AS resolved,
            count(CASE WHEN mm.normalization_status = 'unresolved' THEN 1 END) AS unresolved,
            count(CASE WHEN mm.normalization_status = 'blacklisted' THEN 1 END) AS blacklisted,
            count(CASE WHEN mm.normalization_status = 'pending' THEN 1 END) AS pending

        // Compter les canonical markers
        OPTIONAL MATCH (cm:CanonicalMarker {tenant_id: $tenant_id})
        WITH total_mentions, resolved, unresolved, blacklisted, pending,
             count(DISTINCT cm) AS unique_canonicals

        RETURN {
            total: total_mentions,
            resolved: resolved,
            unresolved: unresolved,
            blacklisted: blacklisted,
            pending: pending,
            unique_canonicals: unique_canonicals
        } AS stats
        """

        try:
            with client.driver.session(database="neo4j") as session:
                result = session.run(query, tenant_id=self.tenant_id)
                record = result.single()
                if record:
                    return dict(record["stats"])
                return {
                    "total": 0,
                    "resolved": 0,
                    "unresolved": 0,
                    "blacklisted": 0,
                    "pending": 0,
                    "unique_canonicals": 0,
                }
        except Exception as e:
            logger.error(f"[NormalizationStore] Failed to get stats: {e}")
            return {
                "total": 0,
                "resolved": 0,
                "unresolved": 0,
                "blacklisted": 0,
                "pending": 0,
                "unique_canonicals": 0,
            }


# =============================================================================
# Singleton
# =============================================================================

_store_instances: Dict[str, NormalizationStore] = {}


def get_normalization_store(tenant_id: str = "default") -> NormalizationStore:
    """Retourne l'instance singleton du NormalizationStore pour un tenant."""
    global _store_instances
    if tenant_id not in _store_instances:
        _store_instances[tenant_id] = NormalizationStore(tenant_id=tenant_id)
    return _store_instances[tenant_id]


__all__ = [
    "NormalizationStore",
    "get_normalization_store",
]
