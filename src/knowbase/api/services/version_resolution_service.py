"""
Service Version Resolution - Phase 1 Document Backbone.

Gère les requêtes temporelles et la résolution de versions :
- Résolution version effective à une date donnée (point-in-time queries)
- Queries "latest as of date"
- Détection obsolescence
- Comparaison versions
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from neo4j import GraphDatabase

from knowbase.api.schemas.documents import (
    DocumentVersionResponse,
    DocumentVersionComparison
)
from knowbase.common.logging import setup_logging
from knowbase.config.settings import get_settings

settings = get_settings()
logger = setup_logging(settings.logs_dir, "version_resolution_service.log")


class VersionResolutionService:
    """Service pour résolution temporelle des versions."""

    def __init__(self, tenant_id: str = "default"):
        """
        Initialise le service Version Resolution.

        Args:
            tenant_id: ID du tenant pour isolation multi-tenant
        """
        self.tenant_id = tenant_id
        self.driver = GraphDatabase.driver(
            settings.neo4j_uri,
            auth=(settings.neo4j_user, settings.neo4j_password)
        )

    def close(self):
        """Ferme la connexion Neo4j."""
        if self.driver:
            self.driver.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()

    def get_effective_version_at(
        self,
        document_id: str,
        effective_at: datetime
    ) -> Optional[DocumentVersionResponse]:
        """
        Résout la version effective d'un document à une date donnée.

        Point-in-time query : retourne la version dont effective_date <= effective_at
        la plus récente.

        Args:
            document_id: UUID du document
            effective_at: Date de référence

        Returns:
            DocumentVersionResponse ou None si aucune version avant cette date

        Example:
            # Quel était la version du document au 1er janvier 2024 ?
            version = service.get_effective_version_at(doc_id, datetime(2024, 1, 1))
        """
        with self.driver.session() as session:
            result = session.execute_read(
                self._get_effective_version_at_tx,
                document_id,
                effective_at
            )
            return result

    @staticmethod
    def _get_effective_version_at_tx(
        tx,
        document_id: str,
        effective_at: datetime
    ) -> Optional[DocumentVersionResponse]:
        """Transaction résolution version effective."""
        query = """
        MATCH (d:Document {doc_id: $document_id})-[:HAS_VERSION]->(v:DocumentVersion)
        WHERE v.effective_date <= datetime($effective_at)
        WITH v
        ORDER BY v.effective_date DESC
        LIMIT 1
        OPTIONAL MATCH (v)-[:SUPERSEDES]->(prev:DocumentVersion)
        OPTIONAL MATCH (next:DocumentVersion)-[:SUPERSEDES]->(v)
        RETURN v, prev.version_id as supersedes_version_id, next.version_id as superseded_by_version_id
        """

        result = tx.run(query, {
            "document_id": document_id,
            "effective_at": effective_at.isoformat()
        })

        record = result.single()

        if not record:
            return None

        node = record["v"]
        supersedes_version_id = record["supersedes_version_id"]
        superseded_by_version_id = record["superseded_by_version_id"]

        import json
        metadata_dict = json.loads(node["metadata"]) if node["metadata"] else {}

        return DocumentVersionResponse(
            version_id=node["version_id"],
            document_id=node["document_id"],
            version_label=node["version_label"],
            effective_date=node["effective_date"].to_native(),
            checksum=node["checksum"],
            file_size=node["file_size"],
            page_count=node["page_count"],
            author_name=node["author_name"],
            author_email=node["author_email"],
            reviewer_name=node["reviewer_name"],
            is_latest=node["is_latest"],
            supersedes_version_id=supersedes_version_id,
            superseded_by_version_id=superseded_by_version_id,
            metadata=metadata_dict,
            created_at=node["created_at"].to_native(),
            ingested_at=node["ingested_at"].to_native() if node.get("ingested_at") else None
        )

    def get_latest_before_date(
        self,
        document_id: str,
        before_date: datetime
    ) -> Optional[DocumentVersionResponse]:
        """
        Alias pour get_effective_version_at (nom plus explicite).

        Retourne la dernière version AVANT une date donnée.

        Args:
            document_id: UUID du document
            before_date: Date limite

        Returns:
            DocumentVersionResponse ou None
        """
        return self.get_effective_version_at(document_id, before_date)

    def compare_versions(
        self,
        version_1_id: str,
        version_2_id: str
    ) -> DocumentVersionComparison:
        """
        Compare 2 versions d'un document.

        Args:
            version_1_id: UUID première version (ancienne)
            version_2_id: UUID deuxième version (nouvelle)

        Returns:
            DocumentVersionComparison avec différences

        Raises:
            ValueError: Si les versions ne sont pas du même document
        """
        with self.driver.session() as session:
            result = session.execute_read(
                self._compare_versions_tx,
                version_1_id,
                version_2_id
            )
            return result

    @staticmethod
    def _compare_versions_tx(
        tx,
        version_1_id: str,
        version_2_id: str
    ) -> DocumentVersionComparison:
        """Transaction comparaison versions."""
        query = """
        MATCH (v1:DocumentVersion {version_id: $version_1_id})
        MATCH (v2:DocumentVersion {version_id: $version_2_id})
        RETURN v1, v2
        """

        result = tx.run(query, {
            "version_1_id": version_1_id,
            "version_2_id": version_2_id
        })

        record = result.single()

        if not record:
            raise ValueError(f"Versions {version_1_id} ou {version_2_id} non trouvées")

        v1 = record["v1"]
        v2 = record["v2"]

        # Vérifier même document
        if v1["document_id"] != v2["document_id"]:
            raise ValueError(
                f"Les versions appartiennent à des documents différents : "
                f"{v1['document_id']} vs {v2['document_id']}"
            )

        # Analyser différences metadata
        import json
        metadata_1 = json.loads(v1["metadata"]) if v1["metadata"] else {}
        metadata_2 = json.loads(v2["metadata"]) if v2["metadata"] else {}

        metadata_changes = {}
        all_keys = set(metadata_1.keys()) | set(metadata_2.keys())

        for key in all_keys:
            val_1 = metadata_1.get(key)
            val_2 = metadata_2.get(key)
            if val_1 != val_2:
                metadata_changes[key] = {
                    "old": val_1,
                    "new": val_2
                }

        # Calculer différences
        checksum_differs = v1["checksum"] != v2["checksum"]
        author_changed = v1["author_name"] != v2["author_name"]

        # Calculer jours entre versions
        date_1 = v1["effective_date"].to_native()
        date_2 = v2["effective_date"].to_native()
        days_between = abs((date_2 - date_1).days)

        return DocumentVersionComparison(
            document_id=v1["document_id"],
            version_1_id=v1["version_id"],
            version_1_label=v1["version_label"],
            version_1_date=date_1,
            version_2_id=v2["version_id"],
            version_2_label=v2["version_label"],
            version_2_date=date_2,
            metadata_changes=metadata_changes,
            checksum_differs=checksum_differs,
            author_changed=author_changed,
            days_between=days_between
        )

    def is_version_obsolete(
        self,
        version_id: str,
        current_date: Optional[datetime] = None
    ) -> bool:
        """
        Détermine si une version est obsolète.

        Une version est obsolète si :
        1. Elle n'est pas is_latest
        2. ET il existe une version plus récente (effective_date > cette version)

        Args:
            version_id: UUID de la version à tester
            current_date: Date de référence (défaut: maintenant)

        Returns:
            True si obsolète, False sinon
        """
        if current_date is None:
            current_date = datetime.now(timezone.utc)

        with self.driver.session() as session:
            result = session.execute_read(
                self._is_version_obsolete_tx,
                version_id,
                current_date
            )
            return result

    @staticmethod
    def _is_version_obsolete_tx(
        tx,
        version_id: str,
        current_date: datetime
    ) -> bool:
        """Transaction vérification obsolescence."""
        query = """
        MATCH (v:DocumentVersion {version_id: $version_id})
        OPTIONAL MATCH (d:Document {doc_id: v.document_id})-[:HAS_VERSION]->(newer:DocumentVersion)
        WHERE newer.effective_date > v.effective_date
          AND newer.effective_date <= datetime($current_date)
        RETURN v.is_latest as is_latest, COUNT(newer) > 0 as has_newer_versions
        """

        result = tx.run(query, {
            "version_id": version_id,
            "current_date": current_date.isoformat()
        })

        record = result.single()

        if not record:
            return False

        is_latest = record["is_latest"]
        has_newer_versions = record["has_newer_versions"]

        # Obsolète si pas latest ET a des versions plus récentes
        return not is_latest and has_newer_versions

    def get_obsolete_versions_count(self, document_id: str) -> int:
        """
        Compte le nombre de versions obsolètes d'un document.

        Args:
            document_id: UUID du document

        Returns:
            Nombre de versions obsolètes
        """
        with self.driver.session() as session:
            result = session.execute_read(
                self._get_obsolete_versions_count_tx,
                document_id
            )
            return result

    @staticmethod
    def _get_obsolete_versions_count_tx(tx, document_id: str) -> int:
        """Transaction comptage versions obsolètes."""
        query = """
        MATCH (d:Document {doc_id: $document_id})-[:HAS_VERSION]->(v:DocumentVersion)
        WHERE v.is_latest = false
        RETURN COUNT(v) as obsolete_count
        """

        result = tx.run(query, {"document_id": document_id})
        record = result.single()

        return record["obsolete_count"] if record else 0
