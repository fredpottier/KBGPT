"""
Router API pour gestion du cycle de vie documentaire (Document Backbone).

Phase 1 - Semaine 4 : APIs REST Documents
- GET /documents : Liste documents avec filtres
- GET /documents/{id} : Détail document avec versions
- GET /documents/{id}/versions : Historique complet versions
- GET /documents/{id}/lineage : Graphe modifications (format D3.js)
- POST /documents/{id}/versions : Upload nouvelle version
"""
from typing import List, Optional
from datetime import datetime, timezone
from pathlib import Path
import hashlib
import tempfile
import shutil

from fastapi import APIRouter, HTTPException, Query, Depends, UploadFile, File
from pydantic import BaseModel, Field

from knowbase.api.schemas.documents import (
    DocumentResponse,
    DocumentVersionResponse,
    DocumentLineage,
    DocumentVersionCreate,
    DocumentStatus,
    DocumentType,
)
from knowbase.api.services.document_registry_service import DocumentRegistryService
from knowbase.api.services.version_resolution_service import VersionResolutionService
from knowbase.api.dependencies import get_current_user, require_admin, require_editor, get_tenant_id
from knowbase.api.utils.audit_helpers import log_audit
from knowbase.common.logging import setup_logging
from knowbase.config.settings import get_settings

settings = get_settings()
logger = setup_logging(settings.logs_dir, "documents_router.log")

router = APIRouter(prefix="/documents", tags=["documents"])


# ===================================
# RESPONSE MODELS
# ===================================

class DocumentsListResponse(BaseModel):
    """Réponse liste documents avec pagination."""

    documents: List[DocumentResponse] = Field(
        ...,
        description="Liste documents"
    )
    total: int = Field(
        ...,
        description="Nombre total documents"
    )
    filters_applied: dict = Field(
        default_factory=dict,
        description="Filtres appliqués"
    )


class DocumentDetailResponse(BaseModel):
    """Réponse détail document avec versions."""

    document: DocumentResponse = Field(
        ...,
        description="Document complet"
    )
    versions: List[DocumentVersionResponse] = Field(
        ...,
        description="Liste versions (ordre chronologique DESC)"
    )
    latest_version: Optional[DocumentVersionResponse] = Field(
        None,
        description="Version la plus récente active"
    )


class VersionsListResponse(BaseModel):
    """Réponse historique versions."""

    document_id: str = Field(..., description="ID du document parent")
    versions: List[DocumentVersionResponse] = Field(
        ...,
        description="Historique versions (ordre chronologique DESC)"
    )
    total: int = Field(..., description="Nombre total versions")


# ===================================
# ENDPOINTS
# ===================================

@router.get(
    "",
    response_model=DocumentsListResponse,
    summary="Liste documents avec filtres",
    description="""
    Liste les documents du système avec filtres optionnels.

    **Filtres disponibles**:
    - `document_type` : Type document (pdf, pptx, docx, excel)
    - `status` : Statut (draft, active, obsolete, archived)
    - `created_after` / `created_before` : Plage dates création
    - `limit` / `offset` : Pagination

    **Authentification**: JWT token requis
    **RBAC**: admin, editor, viewer
    """,
    responses={
        200: {
            "description": "Liste documents avec pagination",
            "content": {
                "application/json": {
                    "example": {
                        "documents": [
                            {
                                "document_id": "doc_123",
                                "title": "SAP S/4HANA Budget 2024",
                                "document_type": "pptx",
                                "status": "active",
                                "version_count": 3,
                                "created_at": "2024-10-10T10:00:00Z"
                            }
                        ],
                        "total": 42,
                        "filters_applied": {
                            "document_type": "pptx",
                            "status": "active"
                        }
                    }
                }
            }
        },
        401: {"description": "Non authentifié"},
        403: {"description": "Accès refusé"}
    }
)
async def list_documents(
    document_type: Optional[str] = Query(None, description="Filtre par type (pdf, pptx, docx, excel)"),
    status: Optional[str] = Query(None, description="Filtre par statut (draft, active, obsolete, archived)"),
    limit: int = Query(50, ge=1, le=500, description="Nombre max documents"),
    offset: int = Query(0, ge=0, description="Offset pagination"),
    tenant_id: str = Depends(get_tenant_id),
    current_user: dict = Depends(get_current_user)
):
    """
    Liste documents avec filtres et pagination.

    Accessible par: admin, editor, viewer
    """
    logger.info(
        f"GET /documents - User: {current_user.get('user_id')}, "
        f"Tenant: {tenant_id}, Type: {document_type}, Status: {status}"
    )

    service = DocumentRegistryService(tenant_id=tenant_id)

    try:
        # Convertir strings en enums
        doc_type_enum = None
        if document_type:
            try:
                doc_type_enum = DocumentType(document_type.upper())
            except ValueError:
                raise HTTPException(
                    status_code=400,
                    detail=f"Type invalide: {document_type}. Valeurs acceptées: pdf, pptx, docx, excel"
                )

        status_enum = None
        if status:
            try:
                status_enum = DocumentStatus(status.lower())
            except ValueError:
                raise HTTPException(
                    status_code=400,
                    detail=f"Statut invalide: {status}. Valeurs acceptées: draft, active, obsolete, archived"
                )

        # Récupérer documents
        documents = service.list_documents(
            status=status_enum,
            document_type=doc_type_enum,
            limit=limit,
            offset=offset
        )

        # Count total (pour pagination)
        total = service.count_documents(
            status=status_enum,
            document_type=doc_type_enum
        )

        # Construire filters_applied pour response
        filters_applied = {}
        if document_type:
            filters_applied['document_type'] = document_type
        if status:
            filters_applied['status'] = status

        return DocumentsListResponse(
            documents=documents,
            total=total,
            filters_applied=filters_applied
        )

    except Exception as e:
        logger.error(f"Erreur liste documents: {e}")
        raise HTTPException(status_code=500, detail=f"Erreur serveur: {str(e)}")

    finally:
        service.close()


@router.get(
    "/{document_id}",
    response_model=DocumentDetailResponse,
    summary="Détail document avec versions",
    description="""
    Récupère un document par ID avec toutes ses versions.

    **Retourne**:
    - Document complet
    - Liste versions (ordre chronologique DESC)
    - Version la plus récente active

    **Authentification**: JWT token requis
    **RBAC**: admin, editor, viewer
    """,
    responses={
        200: {"description": "Document trouvé"},
        401: {"description": "Non authentifié"},
        403: {"description": "Accès refusé"},
        404: {"description": "Document non trouvé"}
    }
)
async def get_document(
    document_id: str,
    tenant_id: str = Depends(get_tenant_id),
    current_user: dict = Depends(get_current_user)
):
    """
    Récupère détail document + versions.

    Accessible par: admin, editor, viewer
    """
    logger.info(
        f"GET /documents/{document_id} - User: {current_user.get('user_id')}, "
        f"Tenant: {tenant_id}"
    )

    doc_service = DocumentRegistryService(tenant_id=tenant_id)
    version_service = VersionResolutionService(tenant_id=tenant_id)

    try:
        # Récupérer document
        document = doc_service.get_document(document_id)

        if not document:
            raise HTTPException(
                status_code=404,
                detail=f"Document {document_id} non trouvé"
            )

        # Récupérer versions
        versions = doc_service.get_document_versions(document_id)

        # Récupérer latest version
        latest_version = version_service.resolve_latest(document_id)

        return DocumentDetailResponse(
            document=document,
            versions=versions,
            latest_version=latest_version
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Erreur récupération document {document_id}: {e}")
        raise HTTPException(status_code=500, detail=f"Erreur serveur: {str(e)}")

    finally:
        doc_service.close()
        version_service.close()


@router.get(
    "/{document_id}/versions",
    response_model=VersionsListResponse,
    summary="Historique versions document",
    description="""
    Récupère l'historique complet des versions d'un document.

    **Ordre**: Chronologique descendant (plus récent en premier)
    **Include**: Metadata complète, author, checksum, file_size
    **Marker**: Indique version active

    **Authentification**: JWT token requis
    **RBAC**: admin, editor, viewer
    """,
    responses={
        200: {"description": "Historique versions"},
        401: {"description": "Non authentifié"},
        403: {"description": "Accès refusé"},
        404: {"description": "Document non trouvé"}
    }
)
async def get_document_versions(
    document_id: str,
    tenant_id: str = Depends(get_tenant_id),
    current_user: dict = Depends(get_current_user)
):
    """
    Récupère historique versions document.

    Accessible par: admin, editor, viewer
    """
    logger.info(
        f"GET /documents/{document_id}/versions - User: {current_user.get('user_id')}"
    )

    service = DocumentRegistryService(tenant_id=tenant_id)

    try:
        # Vérifier existence document
        document = service.get_document(document_id)
        if not document:
            raise HTTPException(
                status_code=404,
                detail=f"Document {document_id} non trouvé"
            )

        # Récupérer versions
        versions = service.get_document_versions(document_id)

        return VersionsListResponse(
            document_id=document_id,
            versions=versions,
            total=len(versions)
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Erreur récupération versions {document_id}: {e}")
        raise HTTPException(status_code=500, detail=f"Erreur serveur: {str(e)}")

    finally:
        service.close()


@router.get(
    "/{document_id}/lineage",
    response_model=DocumentLineage,
    summary="Graphe modifications document",
    description="""
    Récupère le graphe de modifications (lineage) d'un document.

    **Format**: Compatible D3.js (nodes + edges)
    **Relations**: SUPERSEDES entre versions
    **Use Case**: Visualisation timeline modifications

    **Authentification**: JWT token requis
    **RBAC**: admin, editor, viewer
    """,
    responses={
        200: {
            "description": "Graphe lineage",
            "content": {
                "application/json": {
                    "example": {
                        "document_id": "doc_123",
                        "nodes": [
                            {
                                "version_id": "v1",
                                "version_label": "v1.0",
                                "created_at": "2024-01-01T10:00:00Z",
                                "author_name": "John Doe"
                            },
                            {
                                "version_id": "v2",
                                "version_label": "v2.0",
                                "created_at": "2024-02-01T10:00:00Z",
                                "author_name": "Jane Smith"
                            }
                        ],
                        "edges": [
                            {
                                "from": "v1",
                                "to": "v2",
                                "relationship": "SUPERSEDES"
                            }
                        ]
                    }
                }
            }
        },
        401: {"description": "Non authentifié"},
        403: {"description": "Accès refusé"},
        404: {"description": "Document non trouvé"}
    }
)
async def get_document_lineage(
    document_id: str,
    tenant_id: str = Depends(get_tenant_id),
    current_user: dict = Depends(get_current_user)
):
    """
    Récupère graphe lineage document.

    Accessible par: admin, editor, viewer
    """
    logger.info(
        f"GET /documents/{document_id}/lineage - User: {current_user.get('user_id')}"
    )

    service = VersionResolutionService(tenant_id=tenant_id)

    try:
        # Récupérer lineage
        lineage = service.get_version_lineage(document_id)

        if not lineage:
            raise HTTPException(
                status_code=404,
                detail=f"Document {document_id} non trouvé ou aucune version"
            )

        return lineage

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Erreur récupération lineage {document_id}: {e}")
        raise HTTPException(status_code=500, detail=f"Erreur serveur: {str(e)}")

    finally:
        service.close()


@router.post(
    "/{document_id}/versions",
    response_model=DocumentVersionResponse,
    summary="Upload nouvelle version",
    description="""
    Upload une nouvelle version d'un document existant.

    **Process**:
    1. Upload fichier
    2. Calcul checksum SHA256
    3. Création DocumentVersion
    4. Link SUPERSEDES vers version précédente

    **Authentification**: JWT token requis
    **RBAC**: admin, editor (viewer interdit)
    """,
    responses={
        201: {"description": "Version créée"},
        400: {"description": "Données invalides"},
        401: {"description": "Non authentifié"},
        403: {"description": "Accès refusé (viewer)"},
        404: {"description": "Document non trouvé"}
    }
)
async def create_document_version(
    document_id: str,
    file: UploadFile = File(..., description="Fichier nouvelle version"),
    version_label: str = Query(..., description="Label version (ex: v2.0)"),
    effective_date: Optional[datetime] = Query(None, description="Date effective version"),
    author_name: Optional[str] = Query(None, description="Nom auteur"),
    tenant_id: str = Depends(get_tenant_id),
    current_user: dict = Depends(require_editor)  # Editor ou Admin uniquement
):
    """
    Upload nouvelle version document.

    Accessible par: admin, editor (viewer INTERDIT)
    """
    logger.info(
        f"POST /documents/{document_id}/versions - User: {current_user.get('user_id')}, "
        f"Version: {version_label}, File: {file.filename}"
    )

    service = DocumentRegistryService(tenant_id=tenant_id)

    try:
        # Vérifier existence document
        document = service.get_document(document_id)
        if not document:
            raise HTTPException(
                status_code=404,
                detail=f"Document {document_id} non trouvé"
            )

        # Sauvegarder fichier uploadé temporairement
        temp_file = None
        try:
            # Créer fichier temporaire
            with tempfile.NamedTemporaryFile(delete=False, suffix=Path(file.filename).suffix) as tmp:
                temp_file = Path(tmp.name)
                # Copier contenu uploadé
                shutil.copyfileobj(file.file, tmp)

            logger.info(f"Fichier uploadé sauvegardé: {temp_file}")

            # Calculer checksum SHA256
            logger.info(f"Calcul checksum SHA256...")
            sha256_hash = hashlib.sha256()

            with open(temp_file, "rb") as f:
                for byte_block in iter(lambda: f.read(4096), b""):
                    sha256_hash.update(byte_block)

            checksum = sha256_hash.hexdigest()
            file_size = temp_file.stat().st_size

            logger.info(f"Checksum calculé: {checksum[:16]}... ({file_size} bytes)")

            # Vérifier si checksum déjà existe (duplicata)
            existing_version = service.get_version_by_checksum(checksum)
            if existing_version:
                logger.warning(f"Version avec checksum identique déjà existe: {existing_version.version_id}")
                raise HTTPException(
                    status_code=409,
                    detail=f"Une version avec le même contenu existe déjà: {existing_version.version_label}"
                )

            # Récupérer version actuelle (is_latest = true) pour créer relation SUPERSEDES
            version_resolver = VersionResolutionService(tenant_id=tenant_id)
            try:
                current_latest_version = version_resolver.resolve_latest(document_id)
                supersedes_version_id = current_latest_version.version_id if current_latest_version else None

                if supersedes_version_id:
                    logger.info(f"Nouvelle version va superseder: {current_latest_version.version_label} ({supersedes_version_id})")
                else:
                    logger.info("Première version du document - Aucune version à superseder")

            finally:
                version_resolver.close()

            # Créer DocumentVersion
            version_create = DocumentVersionCreate(
                document_id=document_id,
                version_label=version_label,
                effective_date=effective_date or datetime.now(timezone.utc),
                checksum=checksum,
                file_size=file_size,
                author_name=author_name or current_user.get('user_id', 'Unknown'),
                supersedes_version_id=supersedes_version_id,  # Relation SUPERSEDES automatique
                metadata={
                    'original_filename': file.filename,
                    'uploaded_by': current_user.get('user_id'),
                    'uploaded_at': datetime.now(timezone.utc).isoformat(),
                }
            )

            # Le service create_version gère automatiquement:
            # 1. Création du node DocumentVersion
            # 2. Relation HAS_VERSION vers Document
            # 3. Relation SUPERSEDES vers version précédente
            # 4. Mise à jour is_latest (ancienne → false, nouvelle → true)
            version_response = service.create_version(version_create)

            logger.info(
                f"✅ Version créée: {version_response.version_id} - "
                f"{version_label} (checksum: {checksum[:16]}...)"
            )

            # Log audit
            await log_audit(
                action="create_document_version",
                resource_type="document_version",
                resource_id=version_response.version_id,
                user_id=current_user.get('user_id'),
                tenant_id=tenant_id,
                metadata={
                    "document_id": document_id,
                    "version_label": version_label,
                    "filename": file.filename,
                    "checksum": checksum,
                    "file_size": file_size
                }
            )

            return version_response

        finally:
            # Nettoyer fichier temporaire
            if temp_file and temp_file.exists():
                temp_file.unlink()
                logger.debug(f"Fichier temporaire supprimé: {temp_file}")

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Erreur création version {document_id}: {e}")
        raise HTTPException(status_code=500, detail=f"Erreur serveur: {str(e)}")

    finally:
        service.close()
