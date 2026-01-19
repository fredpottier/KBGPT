"""
Document Enrichment Tracker - Pass 1/Pass 2 State Management

Tracking de l'état d'enrichissement des documents selon ADR 2024-12-30.

Structure état:
┌─────────────┬──────────────┬────────────────┬─────────────────┐
│ document_id │ pass1_status │ pass2_status   │ last_enrichment │
├─────────────┼──────────────┼────────────────┼─────────────────┤
│ doc_001     │ COMPLETE     │ PENDING        │ NULL            │
│ doc_002     │ COMPLETE     │ IN_PROGRESS    │ 2024-12-30T10:00│
│ doc_003     │ COMPLETE     │ COMPLETE       │ 2024-12-30T11:00│
└─────────────┴──────────────┴────────────────┴─────────────────┘

Stocké dans Neo4j sur les noeuds Document.

Author: OSMOSE Phase 2
Date: 2024-12-30
"""

import logging
from datetime import datetime
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field
from enum import Enum

logger = logging.getLogger(__name__)


class EnrichmentStatus(str, Enum):
    """Status d'enrichissement d'un document."""

    # Pass 1 statuses
    PENDING = "PENDING"           # Pas encore traité
    IN_PROGRESS = "IN_PROGRESS"   # Traitement en cours
    COMPLETE = "COMPLETE"         # Traitement terminé avec succès
    FAILED = "FAILED"             # Traitement échoué
    SKIPPED = "SKIPPED"           # Intentionnellement ignoré

    # Pass 2 specific
    SCHEDULED = "SCHEDULED"       # Planifié pour Pass 2 background/batch
    PARTIAL = "PARTIAL"           # Partiellement enrichi (certaines phases seulement)


@dataclass
class DocumentEnrichmentState:
    """État d'enrichissement complet d'un document."""

    document_id: str
    tenant_id: str = "default"

    # Pass 1 state
    pass1_status: EnrichmentStatus = EnrichmentStatus.PENDING
    pass1_started_at: Optional[datetime] = None
    pass1_completed_at: Optional[datetime] = None
    pass1_error: Optional[str] = None

    # Métriques Pass 1
    pass1_concepts_extracted: int = 0
    pass1_concepts_promoted: int = 0
    pass1_chunks_created: int = 0

    # Pass 2 state
    pass2_status: EnrichmentStatus = EnrichmentStatus.PENDING
    pass2_scheduled_at: Optional[datetime] = None
    pass2_started_at: Optional[datetime] = None
    pass2_completed_at: Optional[datetime] = None
    pass2_error: Optional[str] = None

    # Métriques Pass 2
    pass2_relations_extracted: int = 0
    pass2_classifications_updated: int = 0
    pass2_cross_doc_links: int = 0

    # Phases Pass 2 complétées
    pass2_phases_completed: List[str] = field(default_factory=list)

    # Metadata
    last_enrichment: Optional[datetime] = None
    enrichment_version: str = "2.0.0"

    @property
    def is_pass1_complete(self) -> bool:
        """True si Pass 1 terminé avec succès."""
        return self.pass1_status == EnrichmentStatus.COMPLETE

    @property
    def is_pass2_complete(self) -> bool:
        """True si Pass 2 terminé avec succès."""
        return self.pass2_status == EnrichmentStatus.COMPLETE

    @property
    def is_fully_enriched(self) -> bool:
        """True si Pass 1 et Pass 2 terminés."""
        return self.is_pass1_complete and self.is_pass2_complete

    @property
    def needs_pass2(self) -> bool:
        """True si Pass 2 est nécessaire."""
        return (
            self.is_pass1_complete and
            self.pass2_status in [EnrichmentStatus.PENDING, EnrichmentStatus.SCHEDULED]
        )


class EnrichmentTracker:
    """
    Tracker d'état d'enrichissement des documents.

    Responsabilités:
    1. Persister/récupérer l'état dans Neo4j
    2. Mettre à jour les statuts Pass 1/Pass 2
    3. Fournir des vues pour le monitoring

    Stockage: Propriétés sur les noeuds Document dans Neo4j.
    """

    def __init__(self, tenant_id: str = "default"):
        """
        Initialise le tracker.

        Args:
            tenant_id: ID tenant
        """
        self.tenant_id = tenant_id
        self._neo4j_client = None

        logger.info(f"[OSMOSE:EnrichmentTracker] Initialized (tenant={tenant_id})")

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

    def get_state(self, document_id: str) -> Optional[DocumentEnrichmentState]:
        """
        Récupère l'état d'enrichissement d'un document.

        Args:
            document_id: ID du document

        Returns:
            DocumentEnrichmentState ou None si non trouvé
        """
        neo4j_client = self._get_neo4j_client()

        if not neo4j_client.is_connected():
            logger.warning("[OSMOSE:EnrichmentTracker] Neo4j not connected")
            return None

        try:
            query = """
            MATCH (d:Document {doc_id: $document_id, tenant_id: $tenant_id})
            RETURN d {
                .doc_id,
                .pass1_status, .pass1_started_at, .pass1_completed_at, .pass1_error,
                .pass1_concepts_extracted, .pass1_concepts_promoted, .pass1_chunks_created,
                .pass2_status, .pass2_scheduled_at, .pass2_started_at, .pass2_completed_at, .pass2_error,
                .pass2_relations_extracted, .pass2_classifications_updated, .pass2_cross_doc_links,
                .pass2_phases_completed,
                .last_enrichment, .enrichment_version
            } AS state
            """

            with neo4j_client.driver.session(database="neo4j") as session:
                result = session.run(
                    query,
                    document_id=document_id,
                    tenant_id=self.tenant_id
                )
                record = result.single()

                if not record:
                    return None

                data = record["state"]
                return self._dict_to_state(data)

        except Exception as e:
            logger.error(f"[OSMOSE:EnrichmentTracker] Failed to get state: {e}")
            return None

    def update_pass1_status(
        self,
        document_id: str,
        status: EnrichmentStatus,
        error: Optional[str] = None,
        concepts_extracted: int = 0,
        concepts_promoted: int = 0,
        chunks_created: int = 0
    ) -> bool:
        """
        Met à jour le statut Pass 1 d'un document.

        Args:
            document_id: ID du document
            status: Nouveau statut
            error: Message d'erreur si échec
            concepts_extracted: Nombre de concepts extraits
            concepts_promoted: Nombre de concepts promus
            chunks_created: Nombre de chunks créés

        Returns:
            True si succès
        """
        neo4j_client = self._get_neo4j_client()

        if not neo4j_client.is_connected():
            return False

        try:
            now = datetime.utcnow()

            # Déterminer les champs à mettre à jour
            set_clauses = [
                "d.pass1_status = $status",
                "d.pass1_concepts_extracted = $concepts_extracted",
                "d.pass1_concepts_promoted = $concepts_promoted",
                "d.pass1_chunks_created = $chunks_created",
            ]

            params = {
                "document_id": document_id,
                "tenant_id": self.tenant_id,
                "status": status.value,
                "concepts_extracted": concepts_extracted,
                "concepts_promoted": concepts_promoted,
                "chunks_created": chunks_created,
            }

            if status == EnrichmentStatus.IN_PROGRESS:
                set_clauses.append("d.pass1_started_at = $now")
                params["now"] = now
            elif status in [EnrichmentStatus.COMPLETE, EnrichmentStatus.FAILED]:
                set_clauses.append("d.pass1_completed_at = $now")
                set_clauses.append("d.last_enrichment = $now")
                params["now"] = now

            if error:
                set_clauses.append("d.pass1_error = $error")
                params["error"] = error

            query = f"""
            MERGE (d:Document {{doc_id: $document_id, tenant_id: $tenant_id}})
            ON CREATE SET d.created_at = datetime()
            SET {', '.join(set_clauses)}
            RETURN d.doc_id
            """

            with neo4j_client.driver.session(database="neo4j") as session:
                result = session.run(query, **params)
                record = result.single()

                if record:
                    logger.info(
                        f"[OSMOSE:EnrichmentTracker] Pass 1 status updated: "
                        f"{document_id} → {status.value}"
                    )
                    return True

            return False

        except Exception as e:
            logger.error(f"[OSMOSE:EnrichmentTracker] Failed to update Pass 1 status: {e}")
            return False

    def update_pass2_status(
        self,
        document_id: str,
        status: EnrichmentStatus,
        error: Optional[str] = None,
        relations_extracted: int = 0,
        classifications_updated: int = 0,
        cross_doc_links: int = 0,
        phases_completed: Optional[List[str]] = None
    ) -> bool:
        """
        Met à jour le statut Pass 2 d'un document.

        Args:
            document_id: ID du document
            status: Nouveau statut
            error: Message d'erreur si échec
            relations_extracted: Nombre de relations extraites
            classifications_updated: Nombre de classifications affinées
            cross_doc_links: Nombre de liens cross-document
            phases_completed: Phases Pass 2 terminées

        Returns:
            True si succès
        """
        neo4j_client = self._get_neo4j_client()

        if not neo4j_client.is_connected():
            return False

        try:
            now = datetime.utcnow()

            set_clauses = [
                "d.pass2_status = $status",
                "d.pass2_relations_extracted = $relations_extracted",
                "d.pass2_classifications_updated = $classifications_updated",
                "d.pass2_cross_doc_links = $cross_doc_links",
            ]

            params = {
                "document_id": document_id,
                "tenant_id": self.tenant_id,
                "status": status.value,
                "relations_extracted": relations_extracted,
                "classifications_updated": classifications_updated,
                "cross_doc_links": cross_doc_links,
            }

            if status == EnrichmentStatus.SCHEDULED:
                set_clauses.append("d.pass2_scheduled_at = $now")
                params["now"] = now
            elif status == EnrichmentStatus.IN_PROGRESS:
                set_clauses.append("d.pass2_started_at = $now")
                params["now"] = now
            elif status in [EnrichmentStatus.COMPLETE, EnrichmentStatus.FAILED, EnrichmentStatus.PARTIAL]:
                set_clauses.append("d.pass2_completed_at = $now")
                set_clauses.append("d.last_enrichment = $now")
                params["now"] = now

            if error:
                set_clauses.append("d.pass2_error = $error")
                params["error"] = error

            if phases_completed:
                set_clauses.append("d.pass2_phases_completed = $phases")
                params["phases"] = phases_completed

            query = f"""
            MATCH (d:Document {{doc_id: $document_id, tenant_id: $tenant_id}})
            SET {', '.join(set_clauses)}
            RETURN d.doc_id
            """

            with neo4j_client.driver.session(database="neo4j") as session:
                result = session.run(query, **params)
                record = result.single()

                if record:
                    logger.info(
                        f"[OSMOSE:EnrichmentTracker] Pass 2 status updated: "
                        f"{document_id} → {status.value}"
                    )
                    return True

            return False

        except Exception as e:
            logger.error(f"[OSMOSE:EnrichmentTracker] Failed to update Pass 2 status: {e}")
            return False

    def get_documents_needing_pass2(
        self,
        limit: int = 100
    ) -> List[DocumentEnrichmentState]:
        """
        Récupère les documents nécessitant Pass 2.

        Args:
            limit: Nombre max de documents à retourner

        Returns:
            Liste des états de documents
        """
        neo4j_client = self._get_neo4j_client()

        if not neo4j_client.is_connected():
            return []

        try:
            query = """
            MATCH (d:Document {tenant_id: $tenant_id})
            WHERE d.pass1_status = 'COMPLETE'
              AND (d.pass2_status IS NULL OR d.pass2_status IN ['PENDING', 'SCHEDULED'])
            RETURN d {
                .document_id,
                .pass1_status, .pass1_completed_at,
                .pass1_concepts_promoted,
                .pass2_status, .pass2_scheduled_at
            } AS state
            ORDER BY d.pass1_completed_at ASC
            LIMIT $limit
            """

            with neo4j_client.driver.session(database="neo4j") as session:
                result = session.run(
                    query,
                    tenant_id=self.tenant_id,
                    limit=limit
                )

                states = []
                for record in result:
                    state = self._dict_to_state(record["state"])
                    if state:
                        states.append(state)

                return states

        except Exception as e:
            logger.error(f"[OSMOSE:EnrichmentTracker] Failed to get documents needing Pass 2: {e}")
            return []

    def get_enrichment_stats(self) -> Dict[str, Any]:
        """
        Récupère les statistiques globales d'enrichissement.

        Returns:
            Dict avec statistiques
        """
        neo4j_client = self._get_neo4j_client()

        if not neo4j_client.is_connected():
            return {}

        try:
            query = """
            MATCH (d:Document {tenant_id: $tenant_id})
            RETURN
                count(d) AS total_documents,
                sum(CASE WHEN d.pass1_status = 'COMPLETE' THEN 1 ELSE 0 END) AS pass1_complete,
                sum(CASE WHEN d.pass1_status = 'IN_PROGRESS' THEN 1 ELSE 0 END) AS pass1_in_progress,
                sum(CASE WHEN d.pass1_status = 'FAILED' THEN 1 ELSE 0 END) AS pass1_failed,
                sum(CASE WHEN d.pass2_status = 'COMPLETE' THEN 1 ELSE 0 END) AS pass2_complete,
                sum(CASE WHEN d.pass2_status = 'IN_PROGRESS' THEN 1 ELSE 0 END) AS pass2_in_progress,
                sum(CASE WHEN d.pass2_status = 'SCHEDULED' THEN 1 ELSE 0 END) AS pass2_scheduled,
                sum(CASE WHEN d.pass2_status = 'PENDING' OR d.pass2_status IS NULL THEN 1 ELSE 0 END) AS pass2_pending,
                sum(COALESCE(d.pass1_concepts_promoted, 0)) AS total_concepts,
                sum(COALESCE(d.pass2_relations_extracted, 0)) AS total_relations
            """

            with neo4j_client.driver.session(database="neo4j") as session:
                result = session.run(query, tenant_id=self.tenant_id)
                record = result.single()

                if record:
                    return {
                        "total_documents": record["total_documents"],
                        "pass1": {
                            "complete": record["pass1_complete"],
                            "in_progress": record["pass1_in_progress"],
                            "failed": record["pass1_failed"],
                        },
                        "pass2": {
                            "complete": record["pass2_complete"],
                            "in_progress": record["pass2_in_progress"],
                            "scheduled": record["pass2_scheduled"],
                            "pending": record["pass2_pending"],
                        },
                        "totals": {
                            "concepts": record["total_concepts"],
                            "relations": record["total_relations"],
                        }
                    }

            return {}

        except Exception as e:
            logger.error(f"[OSMOSE:EnrichmentTracker] Failed to get stats: {e}")
            return {}

    def _dict_to_state(self, data: Dict[str, Any]) -> Optional[DocumentEnrichmentState]:
        """Convertit un dict Neo4j en DocumentEnrichmentState."""
        if not data:
            return None

        try:
            return DocumentEnrichmentState(
                document_id=data.get("document_id", ""),
                tenant_id=self.tenant_id,
                pass1_status=EnrichmentStatus(data.get("pass1_status", "PENDING")),
                pass1_started_at=data.get("pass1_started_at"),
                pass1_completed_at=data.get("pass1_completed_at"),
                pass1_error=data.get("pass1_error"),
                pass1_concepts_extracted=data.get("pass1_concepts_extracted", 0),
                pass1_concepts_promoted=data.get("pass1_concepts_promoted", 0),
                pass1_chunks_created=data.get("pass1_chunks_created", 0),
                pass2_status=EnrichmentStatus(data.get("pass2_status", "PENDING")) if data.get("pass2_status") else EnrichmentStatus.PENDING,
                pass2_scheduled_at=data.get("pass2_scheduled_at"),
                pass2_started_at=data.get("pass2_started_at"),
                pass2_completed_at=data.get("pass2_completed_at"),
                pass2_error=data.get("pass2_error"),
                pass2_relations_extracted=data.get("pass2_relations_extracted", 0),
                pass2_classifications_updated=data.get("pass2_classifications_updated", 0),
                pass2_cross_doc_links=data.get("pass2_cross_doc_links", 0),
                pass2_phases_completed=data.get("pass2_phases_completed", []),
                last_enrichment=data.get("last_enrichment"),
                enrichment_version=data.get("enrichment_version", "2.0.0"),
            )
        except Exception as e:
            logger.warning(f"[OSMOSE:EnrichmentTracker] Failed to parse state: {e}")
            return None


# =============================================================================
# Factory Pattern
# =============================================================================

_tracker_instances: Dict[str, EnrichmentTracker] = {}


def get_enrichment_tracker(tenant_id: str = "default") -> EnrichmentTracker:
    """
    Récupère l'instance singleton du tracker pour un tenant.

    Args:
        tenant_id: ID tenant

    Returns:
        EnrichmentTracker instance
    """
    global _tracker_instances

    if tenant_id not in _tracker_instances:
        _tracker_instances[tenant_id] = EnrichmentTracker(tenant_id=tenant_id)

    return _tracker_instances[tenant_id]
