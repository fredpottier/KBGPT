"""
Router API pour gestion Document Types.

Phase 6 - Document Types Management

Endpoints:
- GET /document-types - Liste tous les types
- POST /document-types - Créer nouveau type (admin)
- GET /document-types/{id} - Détails type
- PUT /document-types/{id} - Modifier type
- DELETE /document-types/{id} - Supprimer type
- GET /document-types/{id}/entity-types - Liste entity types associés
- POST /document-types/{id}/entity-types - Ajouter entity types
- DELETE /document-types/{id}/entity-types/{name} - Retirer entity type
- GET /document-types/templates - Liste templates prédéfinis
- POST /document-types/analyze-sample - Analyser document sample (async)
"""
from typing import Optional, List
from pathlib import Path
from fastapi import APIRouter, HTTPException, Query, Depends, status, UploadFile, File, Form
from sqlalchemy.orm import Session

from knowbase.api.schemas.document_types import (
    DocumentTypeCreate,
    DocumentTypeUpdate,
    DocumentTypeResponse,
    DocumentTypeListResponse,
    AddEntityTypesRequest,
    RemoveEntityTypeRequest,
    DocumentTypeTemplateListResponse,
    DocumentTypeTemplate,
    EntityTypeAssociationResponse,
    AnalyzeSampleResult,
)
from knowbase.api.services.document_type_service import DocumentTypeService
from knowbase.api.dependencies import require_admin, get_tenant_id, get_current_user
from knowbase.api.utils.audit_helpers import log_audit
from knowbase.common.log_sanitizer import sanitize_for_log
from knowbase.db import get_db, DocumentTypeEntityType
from knowbase.common.logging import setup_logging
from knowbase.config.settings import get_settings

settings = get_settings()
logger = setup_logging(settings.logs_dir, "document_types_router.log")

router = APIRouter(prefix="/document-types", tags=["document-types"])


@router.get(
    "",
    response_model=DocumentTypeListResponse,
    summary="Liste tous les document types"
)
async def list_document_types(
    tenant_id: str = Depends(get_tenant_id),  # ✅ Phase 0 - JWT
    current_user: dict = Depends(get_current_user),  # ✅ Phase 0 - Auth
    is_active: Optional[bool] = Query(default=None, description="Filtrer par statut actif"),
    db: Session = Depends(get_db)
):
    """
    Liste tous les document types.

    Paramètres:
    - is_active: Filtrer par statut (None = tous, True = actifs, False = archivés)
    - tenant_id: Tenant ID

    Returns:
        Liste des document types avec métadonnées
    """
    service = DocumentTypeService(db)
    doc_types = service.list_all(tenant_id=tenant_id, is_active=is_active)

    # Enrichir avec entity_type_count et suggested_entity_types
    response_items = []
    for doc_type in doc_types:
        suggested_types = service.get_suggested_entity_types(doc_type.id, tenant_id)

        response_items.append(
            DocumentTypeResponse(
                id=doc_type.id,
                name=doc_type.name,
                slug=doc_type.slug,
                description=doc_type.description,
                context_prompt=doc_type.context_prompt,
                is_active=doc_type.is_active,
                usage_count=doc_type.usage_count,
                tenant_id=doc_type.tenant_id,
                created_at=doc_type.created_at,
                updated_at=doc_type.updated_at,
                suggested_entity_types=suggested_types,
                entity_type_count=len(suggested_types)
            )
        )

    return DocumentTypeListResponse(
        document_types=response_items,
        total=len(response_items)
    )


@router.post(
    "",
    response_model=DocumentTypeResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Créer nouveau document type"
)
async def create_document_type(
    data: DocumentTypeCreate,
    admin: dict = Depends(require_admin),  # ✅ Phase 0 - Admin only
    db: Session = Depends(get_db)
):
    """
    Créer un nouveau document type.

    Requiert authentification admin.

    Body:
    - name: Nom du type
    - slug: Slug unique
    - description: Description (optionnel)
    - context_prompt: Prompt contextuel (optionnel)
    - entity_types: Liste entity_type_names à associer (optionnel)

    Returns:
        Document type créé
    """
    service = DocumentTypeService(db)

    # Vérifier si slug existe déjà
    existing = service.get_by_slug(data.slug, data.tenant_id)
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Document type with slug '{data.slug}' already exists"
        )

    # Créer
    doc_type = service.create(data, admin_email=admin.get("email"))

    # Audit logging (Phase 0 - Audit Trail)
    log_audit(
        action="CREATE",
        user=admin,
        resource_type="document_type",
        resource_id=doc_type.id,
        tenant_id=data.tenant_id,
        details=f"Document type '{doc_type.name}' (slug={doc_type.slug}) created"
    )

    # Récupérer suggested_entity_types
    suggested_types = service.get_suggested_entity_types(doc_type.id, data.tenant_id)

    return DocumentTypeResponse(
        id=doc_type.id,
        name=doc_type.name,
        slug=doc_type.slug,
        description=doc_type.description,
        context_prompt=doc_type.context_prompt,
        is_active=doc_type.is_active,
        usage_count=doc_type.usage_count,
        tenant_id=doc_type.tenant_id,
        created_at=doc_type.created_at,
        updated_at=doc_type.updated_at,
        suggested_entity_types=suggested_types,
        entity_type_count=len(suggested_types)
    )


@router.get(
    "/{document_type_id}",
    response_model=DocumentTypeResponse,
    summary="Détails d'un document type"
)
async def get_document_type(
    document_type_id: str,
    tenant_id: str = Depends(get_tenant_id),  # ✅ Phase 0 - JWT
    current_user: dict = Depends(get_current_user),  # ✅ Phase 0 - Auth
    db: Session = Depends(get_db)
):
    """
    Récupérer détails d'un document type.

    Args:
        document_type_id: ID du document type

    Returns:
        Document type avec métadonnées
    """
    service = DocumentTypeService(db)
    doc_type = service.get_by_id(document_type_id, tenant_id)

    if not doc_type:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Document type {document_type_id} not found"
        )

    suggested_types = service.get_suggested_entity_types(doc_type.id, tenant_id)

    return DocumentTypeResponse(
        id=doc_type.id,
        name=doc_type.name,
        slug=doc_type.slug,
        description=doc_type.description,
        context_prompt=doc_type.context_prompt,
        is_active=doc_type.is_active,
        usage_count=doc_type.usage_count,
        tenant_id=doc_type.tenant_id,
        created_at=doc_type.created_at,
        updated_at=doc_type.updated_at,
        suggested_entity_types=suggested_types,
        entity_type_count=len(suggested_types)
    )


@router.put(
    "/{document_type_id}",
    response_model=DocumentTypeResponse,
    summary="Mettre à jour document type"
)
async def update_document_type(
    document_type_id: str,
    data: DocumentTypeUpdate,
    tenant_id: str = Depends(get_tenant_id),  # ✅ Phase 0 - JWT
    admin: dict = Depends(require_admin),  # ✅ Phase 0 - Admin only
    db: Session = Depends(get_db)
):
    """
    Mettre à jour un document type.

    Requiert authentification admin.
    """
    service = DocumentTypeService(db)
    doc_type = service.update(document_type_id, data, tenant_id)

    if not doc_type:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Document type {document_type_id} not found"
        )

    # Audit logging (Phase 0 - Audit Trail)
    log_audit(
        action="UPDATE",
        user=admin,
        resource_type="document_type",
        resource_id=doc_type.id,
        tenant_id=tenant_id,
        details=f"Document type '{doc_type.name}' updated"
    )

    suggested_types = service.get_suggested_entity_types(doc_type.id, tenant_id)

    return DocumentTypeResponse(
        id=doc_type.id,
        name=doc_type.name,
        slug=doc_type.slug,
        description=doc_type.description,
        context_prompt=doc_type.context_prompt,
        is_active=doc_type.is_active,
        usage_count=doc_type.usage_count,
        tenant_id=doc_type.tenant_id,
        created_at=doc_type.created_at,
        updated_at=doc_type.updated_at,
        suggested_entity_types=suggested_types,
        entity_type_count=len(suggested_types)
    )


@router.delete(
    "/{document_type_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Supprimer document type"
)
async def delete_document_type(
    document_type_id: str,
    tenant_id: str = Depends(get_tenant_id),  # ✅ Phase 0 - JWT
    admin: dict = Depends(require_admin),  # ✅ Phase 0 - Admin only
    db: Session = Depends(get_db)
):
    """
    Supprimer un document type.

    Requiert authentification admin.
    Échoue si usage_count > 0.
    """
    service = DocumentTypeService(db)

    # Récupérer doc_type AVANT suppression pour audit log
    doc_type = service.get_by_id(document_type_id, tenant_id)
    if not doc_type:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Document type {document_type_id} not found"
        )

    doc_type_name = doc_type.name  # Sauvegarder pour audit log

    success = service.delete(document_type_id, tenant_id)

    if not success:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Cannot delete document type with usage_count={doc_type.usage_count}"
        )

    # Audit logging (Phase 0 - Audit Trail)
    log_audit(
        action="DELETE",
        user=admin,
        resource_type="document_type",
        resource_id=document_type_id,
        tenant_id=tenant_id,
        details=f"Document type '{doc_type_name}' deleted"
    )


@router.get(
    "/{document_type_id}/entity-types",
    response_model=List[EntityTypeAssociationResponse],
    summary="Liste entity types associés"
)
async def list_entity_types_associations(
    document_type_id: str,
    tenant_id: str = Depends(get_tenant_id),  # ✅ Phase 0 - JWT
    current_user: dict = Depends(get_current_user),  # ✅ Phase 0 - Auth
    db: Session = Depends(get_db)
):
    """
    Liste les entity types associés à un document type.
    """
    service = DocumentTypeService(db)
    doc_type = service.get_by_id(document_type_id, tenant_id)

    if not doc_type:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Document type {document_type_id} not found"
        )

    associations = db.query(DocumentTypeEntityType).filter(
        DocumentTypeEntityType.document_type_id == document_type_id,
        DocumentTypeEntityType.tenant_id == tenant_id
    ).all()

    return [
        EntityTypeAssociationResponse(
            id=assoc.id,
            document_type_id=assoc.document_type_id,
            entity_type_name=assoc.entity_type_name,
            source=assoc.source,
            confidence=assoc.confidence,
            examples=assoc.examples.split(",") if assoc.examples else None,
            validated_by=assoc.validated_by,
            validated_at=assoc.validated_at,
            created_at=assoc.created_at
        )
        for assoc in associations
    ]


@router.post(
    "/{document_type_id}/entity-types",
    status_code=status.HTTP_201_CREATED,
    summary="Ajouter entity types"
)
async def add_entity_types(
    document_type_id: str,
    data: AddEntityTypesRequest,
    tenant_id: str = Depends(get_tenant_id),  # ✅ Phase 0 - JWT
    admin: dict = Depends(require_admin),  # ✅ Phase 0 - Admin only
    db: Session = Depends(get_db)
):
    """
    Ajouter entity types à un document type.

    Requiert authentification admin.
    """
    service = DocumentTypeService(db)
    doc_type = service.get_by_id(document_type_id, tenant_id)

    if not doc_type:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Document type {document_type_id} not found"
        )

    added_count = service.add_entity_types(
        document_type_id=document_type_id,
        entity_type_names=data.entity_type_names,
        source=data.source,
        validated_by=data.validated_by or admin.get("email"),
        tenant_id=tenant_id
    )

    # Audit logging (Phase 0 - Audit Trail)
    log_audit(
        action="ADD",
        user=admin,
        resource_type="document_type_entity_types",
        resource_id=document_type_id,
        tenant_id=tenant_id,
        details=f"Added {added_count} entity types to document type {document_type_id}: {', '.join(data.entity_type_names)}"
    )

    return {
        "message": f"{added_count} entity types added",
        "added_count": added_count
    }


@router.delete(
    "/{document_type_id}/entity-types/{entity_type_name}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Retirer entity type"
)
async def remove_entity_type(
    document_type_id: str,
    entity_type_name: str,
    tenant_id: str = Depends(get_tenant_id),  # ✅ Phase 0 - JWT
    admin: dict = Depends(require_admin),  # ✅ Phase 0 - Admin only
    db: Session = Depends(get_db)
):
    """
    Retirer entity type d'un document type.

    Requiert authentification admin.
    """
    service = DocumentTypeService(db)
    success = service.remove_entity_type(document_type_id, entity_type_name, tenant_id)

    if not success:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Association not found"
        )

    # Audit logging (Phase 0 - Audit Trail)
    log_audit(
        action="REMOVE",
        user=admin,
        resource_type="document_type_entity_types",
        resource_id=document_type_id,
        tenant_id=tenant_id,
        details=f"Removed entity type '{entity_type_name}' from document type {document_type_id}"
    )


@router.get(
    "/templates/list",
    response_model=DocumentTypeTemplateListResponse,
    summary="Liste templates prédéfinis"
)
async def list_templates():
    """
    Liste les templates de document types prédéfinis.

    Permet d'importer rapidement des configurations types.
    """
    templates = [
        DocumentTypeTemplate(
            name="Technical Documentation",
            slug="technical",
            description="Documentation technique détaillant architectures, API, et implémentations",
            context_prompt="Document technique présentant des solutions technologiques avec focus sur l'architecture, les composants système, et les intégrations.",
            suggested_entity_types=["SOLUTION", "INFRASTRUCTURE", "DATABASE", "API", "PROTOCOL", "TECHNOLOGY"],
            icon="⚙️"
        ),
        DocumentTypeTemplate(
            name="Functional Documentation",
            slug="functional",
            description="Documentation fonctionnelle décrivant processus métier et cas d'usage",
            context_prompt="Document fonctionnel décrivant les processus métier, workflows, et fonctionnalités utilisateur.",
            suggested_entity_types=["PROCESS", "FEATURE", "MODULE", "ROLE", "WORKFLOW"],
            icon="📋"
        ),
        DocumentTypeTemplate(
            name="Marketing Material",
            slug="marketing",
            description="Matériel marketing : brochures, présentations produits, cas clients",
            context_prompt="Matériel marketing présentant des produits, leurs avantages, et témoignages clients.",
            suggested_entity_types=["PRODUCT", "SOLUTION", "BENEFIT", "CUSTOMER", "USE_CASE", "INDUSTRY"],
            icon="📢"
        ),
        DocumentTypeTemplate(
            name="Product Catalog",
            slug="product_catalog",
            description="Catalogue produits avec fiches techniques et références",
            context_prompt="Catalogue de produits avec caractéristiques techniques, références, prix, et disponibilité.",
            suggested_entity_types=["PRODUCT", "SKU", "CATEGORY", "SPECIFICATION", "PRICE", "SUPPLIER"],
            icon="🛍️"
        ),
        DocumentTypeTemplate(
            name="Training Material",
            slug="training",
            description="Supports de formation et guides utilisateurs",
            context_prompt="Support de formation expliquant comment utiliser des systèmes ou réaliser des tâches spécifiques.",
            suggested_entity_types=["MODULE", "FEATURE", "STEP", "TIP", "BEST_PRACTICE", "SCENARIO"],
            icon="🎓"
        ),
    ]

    return DocumentTypeTemplateListResponse(templates=templates)


@router.post(
    "/analyze-sample",
    response_model=AnalyzeSampleResult,
    status_code=status.HTTP_200_OK,
    summary="Analyser document sample PDF (synchrone)"
)
async def analyze_document_sample(
    file: UploadFile = File(..., description="Document PDF à analyser"),
    context_prompt: Optional[str] = Form(None, description="Contexte additionnel"),
    model_preference: str = Form(default="claude-sonnet", description="Modèle LLM (Claude uniquement)"),
    tenant_id: str = Form(default="default", description="Tenant ID"),
    admin: dict = Depends(require_admin),  # ✅ Phase 0 - Admin only
    db: Session = Depends(get_db)
):
    """
    Analyser un document sample PDF pour suggérer entity types.

    Traitement synchrone avec Claude (PDF natif, inclut texte + images + mise en page).

    Args:
        file: Fichier PDF uniquement
        context_prompt: Contexte additionnel pour guider le LLM
        model_preference: Modèle LLM à utiliser (Claude uniquement)
        tenant_id: Tenant ID

    Returns:
        Résultat de l'analyse avec types suggérés
    """
    # Valider extension
    file_ext = Path(file.filename).suffix.lower()
    if file_ext != ".pdf":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Format non supporté: {file_ext}. Seul le format PDF est accepté."
        )

    logger.info(f"📤 Upload document sample pour analyse: {file.filename}")

    # Analyser directement (synchrone)
    try:
        from knowbase.api.services.document_sample_analyzer_service import DocumentSampleAnalyzerService

        service = DocumentSampleAnalyzerService(db_session=db)
        result = await service.analyze_document_sample(
            file=file,
            context_prompt=context_prompt,
            model_preference=model_preference,
            tenant_id=tenant_id
        )

        logger.info(f"✅ Analyse terminée: {len(result['suggested_types'])} types suggérés")

        return AnalyzeSampleResult(**result)

    except Exception as e:
        logger.error(f"❌ Erreur analyse: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to create analysis job: {str(e)}"
        )


__all__ = ["router"]
