"""
Service Document Registry - Phase 1 Document Backbone.

Gère les documents et versions dans Neo4j avec support :
- CRUD documents et versions
- Versioning et lineage tracking
- Détection duplicatas (checksum)
- Résolution version latest/effective_at
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import List, Optional, Dict
import uuid
import hashlib

from neo4j import GraphDatabase

from knowbase.api.schemas.documents import (
    DocumentCreate,
    DocumentUpdate,
    DocumentResponse,
    DocumentVersionCreate,
    DocumentVersionUpdate,
    DocumentVersionResponse,
    DocumentLineageResponse,
    DocumentLineageNode,
    DocumentVersionComparison,
    DocumentStatus,
    DocumentType
)
from knowbase.common.logging import setup_logging
from knowbase.config.settings import get_settings

settings = get_settings()
logger = setup_logging(settings.logs_dir, "document_registry_service.log")


class DocumentRegistryService:
    """Service pour gestion documents et versions dans Neo4j."""

    def __init__(self, tenant_id: str = "default"):
        """
        Initialise le service Document Registry.

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

    # === DOCUMENTS ===

    def create_document(self, doc: DocumentCreate) -> DocumentResponse:
        """
        Crée un nouveau document.

        Args:
            doc: Données document à créer

        Returns:
            DocumentResponse: Document créé avec UUID
        """
        with self.driver.session() as session:
            result = session.execute_write(self._create_document_tx, doc, self.tenant_id)
            return result

    @staticmethod
    def _create_document_tx(tx, doc: DocumentCreate, tenant_id: str) -> DocumentResponse:
        """Transaction création document."""
        document_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc).isoformat()

        import json
        metadata_json = json.dumps(doc.metadata) if doc.metadata else "{}"

        query = """
        CREATE (d:Document {
            document_id: $document_id,
            title: $title,
            source_path: $source_path,
            document_type: $document_type,
            description: $description,
            status: $status,
            metadata: $metadata,
            tenant_id: $tenant_id,
            created_at: datetime($created_at),
            updated_at: datetime($updated_at)
        })
        RETURN d
        """

        result = tx.run(query, {
            "document_id": document_id,
            "title": doc.title,
            "source_path": doc.source_path,
            "document_type": doc.document_type.value,
            "description": doc.description or "",
            "status": DocumentStatus.ACTIVE.value,
            "metadata": metadata_json,
            "tenant_id": tenant_id,
            "created_at": now,
            "updated_at": now
        })

        record = result.single()
        node = record["d"]

        import json
        metadata_dict = json.loads(node["metadata"]) if node["metadata"] else {}

        return DocumentResponse(
            document_id=node["document_id"],
            title=node["title"],
            source_path=node["source_path"],
            document_type=DocumentType(node["document_type"]),
            description=node["description"],
            status=DocumentStatus(node["status"]),
            metadata=metadata_dict,
            tenant_id=node["tenant_id"],
            created_at=node["created_at"].to_native(),
            updated_at=node["updated_at"].to_native(),
            version_count=0
        )

    def get_document_by_id(self, document_id: str) -> Optional[DocumentResponse]:
        """
        Récupère un document par ID.

        Args:
            document_id: UUID du document

        Returns:
            DocumentResponse ou None si non trouvé
        """
        with self.driver.session() as session:
            result = session.execute_read(self._get_document_by_id_tx, document_id, self.tenant_id)
            return result

    @staticmethod
    def _get_document_by_id_tx(tx, document_id: str, tenant_id: str) -> Optional[DocumentResponse]:
        """Transaction récupération document."""
        query = """
        MATCH (d:Document {document_id: $document_id, tenant_id: $tenant_id})
        OPTIONAL MATCH (d)-[:HAS_VERSION]->(v:DocumentVersion)
        WITH d,
             COUNT(v) as version_count,
             HEAD([ver IN COLLECT(v) WHERE ver.is_latest = true | ver.version_id]) as latest_version_id
        RETURN d, version_count, latest_version_id
        """

        result = tx.run(query, {"document_id": document_id, "tenant_id": tenant_id})
        record = result.single()

        if not record:
            return None

        node = record["d"]
        version_count = record["version_count"] or 0
        latest_version_id = record["latest_version_id"]

        import json
        metadata_dict = json.loads(node["metadata"]) if node["metadata"] else {}

        return DocumentResponse(
            document_id=node["document_id"],
            title=node["title"],
            source_path=node["source_path"],
            document_type=DocumentType(node["document_type"]),
            description=node["description"],
            status=DocumentStatus(node["status"]),
            metadata=metadata_dict,
            tenant_id=node["tenant_id"],
            created_at=node["created_at"].to_native(),
            updated_at=node["updated_at"].to_native(),
            latest_version_id=latest_version_id,
            version_count=version_count
        )

    def get_document_by_source_path(self, source_path: str) -> Optional[DocumentResponse]:
        """
        Récupère un document par source_path.

        Args:
            source_path: Chemin source unique

        Returns:
            DocumentResponse ou None si non trouvé
        """
        with self.driver.session() as session:
            result = session.execute_read(self._get_document_by_source_path_tx, source_path, self.tenant_id)
            return result

    @staticmethod
    def _get_document_by_source_path_tx(tx, source_path: str, tenant_id: str) -> Optional[DocumentResponse]:
        """Transaction récupération document par source_path."""
        query = """
        MATCH (d:Document {source_path: $source_path, tenant_id: $tenant_id})
        OPTIONAL MATCH (d)-[:HAS_VERSION]->(v:DocumentVersion)
        WITH d,
             COUNT(v) as version_count,
             HEAD([ver IN COLLECT(v) WHERE ver.is_latest = true | ver.version_id]) as latest_version_id
        RETURN d, version_count, latest_version_id
        """

        result = tx.run(query, {"source_path": source_path, "tenant_id": tenant_id})
        record = result.single()

        if not record:
            return None

        node = record["d"]
        version_count = record["version_count"] or 0
        latest_version_id = record["latest_version_id"]

        import json
        metadata_dict = json.loads(node["metadata"]) if node["metadata"] else {}

        return DocumentResponse(
            document_id=node["document_id"],
            title=node["title"],
            source_path=node["source_path"],
            document_type=DocumentType(node["document_type"]),
            description=node["description"],
            status=DocumentStatus(node["status"]),
            metadata=metadata_dict,
            tenant_id=node["tenant_id"],
            created_at=node["created_at"].to_native(),
            updated_at=node["updated_at"].to_native(),
            latest_version_id=latest_version_id,
            version_count=version_count
        )

    def list_documents(
        self,
        status: Optional[DocumentStatus] = None,
        document_type: Optional[DocumentType] = None,
        limit: int = 100,
        offset: int = 0
    ) -> List[DocumentResponse]:
        """
        Liste les documents avec filtres optionnels.

        Args:
            status: Filtrer par statut
            document_type: Filtrer par type
            limit: Nombre max de résultats
            offset: Offset pour pagination

        Returns:
            Liste de DocumentResponse
        """
        with self.driver.session() as session:
            result = session.execute_read(
                self._list_documents_tx,
                self.tenant_id,
                status,
                document_type,
                limit,
                offset
            )
            return result

    @staticmethod
    def _list_documents_tx(
        tx,
        tenant_id: str,
        status: Optional[DocumentStatus],
        document_type: Optional[DocumentType],
        limit: int,
        offset: int
    ) -> List[DocumentResponse]:
        """Transaction liste documents."""
        # Construction query dynamique selon filtres
        where_clauses = ["d.tenant_id = $tenant_id"]
        params = {"tenant_id": tenant_id, "limit": limit, "offset": offset}

        if status:
            where_clauses.append("d.status = $status")
            params["status"] = status.value

        if document_type:
            where_clauses.append("d.document_type = $document_type")
            params["document_type"] = document_type.value

        where_clause = " AND ".join(where_clauses)

        query = f"""
        MATCH (d:Document)
        WHERE {where_clause}
        OPTIONAL MATCH (d)-[:HAS_VERSION]->(v:DocumentVersion)
        WITH d,
             COUNT(v) as version_count,
             HEAD([ver IN COLLECT(v) WHERE ver.is_latest = true | ver.version_id]) as latest_version_id
        RETURN d, version_count, latest_version_id
        ORDER BY d.created_at DESC
        SKIP $offset
        LIMIT $limit
        """

        result = tx.run(query, params)

        documents = []
        import json

        for record in result:
            node = record["d"]
            version_count = record["version_count"] or 0
            latest_version_id = record["latest_version_id"]

            metadata_dict = json.loads(node["metadata"]) if node["metadata"] else {}

            documents.append(DocumentResponse(
                document_id=node["document_id"],
                title=node["title"],
                source_path=node["source_path"],
                document_type=DocumentType(node["document_type"]),
                description=node["description"],
                status=DocumentStatus(node["status"]),
                metadata=metadata_dict,
                tenant_id=node["tenant_id"],
                created_at=node["created_at"].to_native(),
                updated_at=node["updated_at"].to_native(),
                latest_version_id=latest_version_id,
                version_count=version_count
            ))

        return documents

    # === DOCUMENT VERSIONS ===

    def create_version(self, version: DocumentVersionCreate) -> DocumentVersionResponse:
        """
        Crée une nouvelle version d'un document.

        Args:
            version: Données version à créer

        Returns:
            DocumentVersionResponse: Version créée avec UUID

        Raises:
            ValueError: Si checksum existe déjà (duplicata) ou document non trouvé
        """
        with self.driver.session() as session:
            # Vérifier que document existe
            doc = self.get_document_by_id(version.document_id)
            if not doc:
                raise ValueError(f"Document {version.document_id} non trouvé")

            # Vérifier duplicata checksum
            existing = self.get_version_by_checksum(version.checksum)
            if existing:
                raise ValueError(f"Version avec checksum {version.checksum} existe déjà (duplicata)")

            result = session.execute_write(self._create_version_tx, version, self.tenant_id)
            return result

    @staticmethod
    def _create_version_tx(tx, version: DocumentVersionCreate, tenant_id: str) -> DocumentVersionResponse:
        """Transaction création version."""
        version_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc).isoformat()

        import json
        metadata_json = json.dumps(version.metadata) if version.metadata else "{}"

        # 1. Marquer toutes les versions précédentes comme non-latest
        tx.run("""
            MATCH (d:Document {document_id: $document_id})-[:HAS_VERSION]->(v:DocumentVersion)
            SET v.is_latest = false
        """, {"document_id": version.document_id})

        # 2. Créer la nouvelle version
        query = """
        MATCH (d:Document {document_id: $document_id})
        CREATE (v:DocumentVersion {
            version_id: $version_id,
            document_id: $document_id,
            version_label: $version_label,
            effective_date: datetime($effective_date),
            checksum: $checksum,
            file_size: $file_size,
            page_count: $page_count,
            author_name: $author_name,
            author_email: $author_email,
            reviewer_name: $reviewer_name,
            is_latest: true,
            metadata: $metadata,
            created_at: datetime($created_at),
            ingested_at: datetime($ingested_at)
        })
        CREATE (d)-[:HAS_VERSION]->(v)
        RETURN v
        """

        result = tx.run(query, {
            "document_id": version.document_id,
            "version_id": version_id,
            "version_label": version.version_label,
            "effective_date": version.effective_date.isoformat(),
            "checksum": version.checksum,
            "file_size": version.file_size,
            "page_count": version.page_count,
            "author_name": version.author_name,
            "author_email": version.author_email,
            "reviewer_name": version.reviewer_name,
            "metadata": metadata_json,
            "created_at": now,
            "ingested_at": now
        })

        record = result.single()
        node = record["v"]

        # 3. Si supersedes_version_id fourni, créer relation SUPERSEDES
        if version.supersedes_version_id:
            tx.run("""
                MATCH (v_new:DocumentVersion {version_id: $new_version_id})
                MATCH (v_old:DocumentVersion {version_id: $old_version_id})
                CREATE (v_new)-[:SUPERSEDES]->(v_old)
            """, {
                "new_version_id": version_id,
                "old_version_id": version.supersedes_version_id
            })

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
            supersedes_version_id=version.supersedes_version_id,
            metadata=metadata_dict,
            created_at=node["created_at"].to_native(),
            ingested_at=node["ingested_at"].to_native() if node.get("ingested_at") else None
        )

    def get_version_by_checksum(self, checksum: str) -> Optional[DocumentVersionResponse]:
        """
        Récupère une version par checksum (détection duplicatas).

        Args:
            checksum: SHA256 checksum

        Returns:
            DocumentVersionResponse ou None si non trouvé
        """
        with self.driver.session() as session:
            result = session.execute_read(self._get_version_by_checksum_tx, checksum)
            return result

    @staticmethod
    def _get_version_by_checksum_tx(tx, checksum: str) -> Optional[DocumentVersionResponse]:
        """Transaction récupération version par checksum."""
        query = """
        MATCH (v:DocumentVersion {checksum: $checksum})
        OPTIONAL MATCH (v)-[:SUPERSEDES]->(prev:DocumentVersion)
        OPTIONAL MATCH (next:DocumentVersion)-[:SUPERSEDES]->(v)
        RETURN v, prev.version_id as supersedes_version_id, next.version_id as superseded_by_version_id
        """

        result = tx.run(query, {"checksum": checksum})
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

    def get_latest_version(self, document_id: str) -> Optional[DocumentVersionResponse]:
        """
        Récupère la dernière version d'un document.

        Args:
            document_id: UUID du document

        Returns:
            DocumentVersionResponse ou None si aucune version
        """
        with self.driver.session() as session:
            result = session.execute_read(self._get_latest_version_tx, document_id)
            return result

    @staticmethod
    def _get_latest_version_tx(tx, document_id: str) -> Optional[DocumentVersionResponse]:
        """Transaction récupération dernière version."""
        query = """
        MATCH (d:Document {document_id: $document_id})-[:HAS_VERSION]->(v:DocumentVersion {is_latest: true})
        OPTIONAL MATCH (v)-[:SUPERSEDES]->(prev:DocumentVersion)
        OPTIONAL MATCH (next:DocumentVersion)-[:SUPERSEDES]->(v)
        RETURN v, prev.version_id as supersedes_version_id, next.version_id as superseded_by_version_id
        """

        result = tx.run(query, {"document_id": document_id})
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

    def get_document_lineage(self, document_id: str) -> DocumentLineageResponse:
        """
        Récupère le lineage complet d'un document (historique versions).

        Args:
            document_id: UUID du document

        Returns:
            DocumentLineageResponse avec toutes les versions ordonnées
        """
        with self.driver.session() as session:
            result = session.execute_read(self._get_document_lineage_tx, document_id)
            return result

    @staticmethod
    def _get_document_lineage_tx(tx, document_id: str) -> DocumentLineageResponse:
        """Transaction récupération lineage."""
        # Récupérer document
        doc_query = "MATCH (d:Document {document_id: $document_id}) RETURN d.title as title"
        doc_result = tx.run(doc_query, {"document_id": document_id})
        doc_record = doc_result.single()

        if not doc_record:
            return DocumentLineageResponse(
                document_id=document_id,
                document_title="",
                versions=[],
                total_versions=0
            )

        document_title = doc_record["title"]

        # Récupérer toutes les versions ordonnées par effective_date
        versions_query = """
        MATCH (d:Document {document_id: $document_id})-[:HAS_VERSION]->(v:DocumentVersion)
        RETURN v.version_id as version_id,
               v.version_label as version_label,
               v.effective_date as effective_date,
               v.author_name as author_name,
               v.is_latest as is_latest
        ORDER BY v.effective_date DESC
        """

        versions_result = tx.run(versions_query, {"document_id": document_id})

        versions = []
        for record in versions_result:
            versions.append(DocumentLineageNode(
                version_id=record["version_id"],
                version_label=record["version_label"],
                effective_date=record["effective_date"].to_native(),
                author_name=record["author_name"],
                is_latest=record["is_latest"]
            ))

        return DocumentLineageResponse(
            document_id=document_id,
            document_title=document_title,
            versions=versions,
            total_versions=len(versions)
        )
