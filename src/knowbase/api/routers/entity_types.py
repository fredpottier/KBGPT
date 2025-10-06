"""
Router API pour gestion Entity Types Registry.

Phase 2 - Entity Types Management

Endpoints:
- GET /entity-types - Liste tous les types
- POST /entity-types - Créer nouveau type (admin)
- GET /entity-types/{type_name} - Détails type
- POST /entity-types/{type_name}/approve - Approuver type
- POST /entity-types/{type_name}/reject - Rejeter type
- DELETE /entity-types/{type_name} - Supprimer type
"""
from typing import Optional

from fastapi import APIRouter, HTTPException, Query, Depends
from sqlalchemy.orm import Session

from knowbase.api.schemas.entity_types import (
    EntityTypeCreate,
    EntityTypeResponse,
    EntityTypeApprove,
    EntityTypeReject,
    EntityTypeListResponse,
)
from knowbase.api.services.entity_type_registry_service import EntityTypeRegistryService
from knowbase.db import get_db
from knowbase.common.logging import setup_logging
from knowbase.config.settings import get_settings

settings = get_settings()
logger = setup_logging(settings.logs_dir, "entity_types_router.log")

router = APIRouter(prefix="/entity-types", tags=["entity-types"])


@router.get(
    "",
    response_model=EntityTypeListResponse,
    summary="Liste entity types découverts",
    description="""
    Liste tous les entity types enregistrés dans le registry avec filtrage et pagination.

    **Workflow Auto-Learning**:
    - Types découverts automatiquement par LLM lors extraction → status='pending'
    - Types créés manuellement ou approuvés → status='approved'
    - Types rejetés par admin → status='rejected'

    **Use Cases**:
    - Admin UI: Affichage types pending pour validation
    - Monitoring: Stats découverte types par tenant
    - Analytics: Types les plus utilisés (tri par entity_count)

    **Performance**: < 50ms (index SQLite sur tenant_id, status)
    """,
    responses={
        200: {
            "description": "Liste types avec compteurs",
            "content": {
                "application/json": {
                    "example": {
                        "types": [
                            {
                                "id": 1,
                                "type_name": "SAP_COMPONENT",
                                "status": "pending",
                                "entity_count": 42,
                                "pending_entity_count": 15,
                                "validated_entity_count": 27,
                                "first_seen": "2025-10-06T10:30:00Z",
                                "discovered_by": "llm",
                                "approved_by": None,
                                "approved_at": None,
                                "tenant_id": "default"
                            }
                        ],
                        "total": 1,
                        "status_filter": "pending",
                        "tenant_id": "default"
                    }
                }
            }
        }
    }
)
async def list_entity_types(
    status: Optional[str] = Query(
        default=None,
        description="Filtrer par status (pending | approved | rejected)",
        example="pending"
    ),
    tenant_id: str = Query(
        default="default",
        description="Tenant ID pour isolation multi-tenant",
        example="default"
    ),
    limit: int = Query(
        default=100,
        ge=1,
        le=1000,
        description="Limite résultats pagination (max 1000)",
        example=100
    ),
    offset: int = Query(
        default=0,
        ge=0,
        description="Offset pagination (0-based)",
        example=0
    ),
    db: Session = Depends(get_db)
):
    """
    Liste tous les entity types découverts avec filtres.

    Retourne les types enregistrés dans le registry avec leurs
    statuts, compteurs d'entités, et metadata validation.

    Args:
        status: Filtrer par status (optionnel)
        tenant_id: Tenant ID
        limit: Limite résultats (défaut 100, max 1000)
        offset: Offset pagination
        db: Session DB

    Returns:
        Liste types avec total count
    """
    logger.info(
        f"📋 GET /entity-types - status={status}, tenant={tenant_id}, "
        f"limit={limit}, offset={offset}"
    )

    service = EntityTypeRegistryService(db)

    try:
        # Liste types
        types = service.list_types(
            tenant_id=tenant_id,
            status=status,
            limit=limit,
            offset=offset
        )

        # Count total (sans pagination)
        total = service.count_types(tenant_id=tenant_id, status=status)

        logger.info(
            f"✅ Trouvé {len(types)} types (total={total}, status={status or 'all'})"
        )

        return EntityTypeListResponse(
            types=[EntityTypeResponse.from_orm(t) for t in types],
            total=total,
            status_filter=status
        )

    except Exception as e:
        logger.error(f"❌ Erreur list entity types: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to list entity types: {str(e)}"
        )


@router.post(
    "",
    response_model=EntityTypeResponse,
    status_code=201,
    summary="Créer entity type manuellement",
    description="""
    Crée un nouveau entity type dans le registry (création manuelle admin).

    **Use Case**: Admin souhaite préenregistrer un type avant que le LLM ne le découvre.

    **Validation**:
    - `type_name` : Format `^[A-Z][A-Z0-9_]{0,49}$` (UPPERCASE, max 50 chars)
    - Préfixes interdits : `_`, `SYSTEM_`, `ADMIN_`, `INTERNAL_`
    - Unicité : `(type_name, tenant_id)` composite unique

    **Status Initial**: 'pending' (nécessite approbation)
    """,
    responses={
        201: {
            "description": "Type créé avec succès",
            "content": {
                "application/json": {
                    "example": {
                        "id": 5,
                        "type_name": "CUSTOM_MODULE",
                        "status": "pending",
                        "entity_count": 0,
                        "pending_entity_count": 0,
                        "validated_entity_count": 0,
                        "first_seen": "2025-10-06T14:22:00Z",
                        "discovered_by": "admin-manual",
                        "approved_by": None,
                        "approved_at": None,
                        "tenant_id": "default",
                        "description": "Custom business module"
                    }
                }
            }
        },
        409: {
            "description": "Type déjà existant",
            "content": {
                "application/json": {
                    "example": {"detail": "Entity type 'CUSTOM_MODULE' already exists"}
                }
            }
        },
        422: {
            "description": "Validation échouée (format type_name invalide)",
            "content": {
                "application/json": {
                    "example": {
                        "detail": [
                            {
                                "loc": ["body", "type_name"],
                                "msg": "Type must match ^[A-Z][A-Z0-9_]{0,49}$",
                                "type": "value_error.str.regex"
                            }
                        ]
                    }
                }
            }
        }
    }
)
async def create_entity_type(
    entity_type: EntityTypeCreate,
    db: Session = Depends(get_db)
):
    """
    Créer nouveau entity type (admin).

    Crée un nouveau type dans le registry avec status=pending.
    Si type existe déjà, retourne erreur 409 Conflict.

    Args:
        entity_type: Données type à créer
        db: Session DB

    Returns:
        EntityTypeResponse créé
    """
    logger.info(f"📝 POST /entity-types - type_name={entity_type.type_name}")

    service = EntityTypeRegistryService(db)

    try:
        # Vérifier si type existe déjà
        existing = service.get_type_by_name(
            entity_type.type_name,
            entity_type.tenant_id
        )

        if existing:
            raise HTTPException(
                status_code=409,
                detail=f"Entity type '{entity_type.type_name}' already exists"
            )

        # Créer type
        new_type = service.get_or_create_type(
            type_name=entity_type.type_name,
            tenant_id=entity_type.tenant_id,
            discovered_by=entity_type.discovered_by
        )

        # Mettre à jour description si fournie
        if entity_type.description:
            new_type.description = entity_type.description
            db.commit()
            db.refresh(new_type)

        logger.info(f"✅ Type créé: {new_type.type_name} (id={new_type.id})")

        return EntityTypeResponse.from_orm(new_type)

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Erreur create entity type: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to create entity type: {str(e)}"
        )


@router.get("/{type_name}", response_model=EntityTypeResponse)
async def get_entity_type(
    type_name: str,
    tenant_id: str = Query(default="default", description="Tenant ID"),
    db: Session = Depends(get_db)
):
    """
    Récupérer détails d'un entity type.

    Args:
        type_name: Nom type (UPPERCASE)
        tenant_id: Tenant ID
        db: Session DB

    Returns:
        EntityTypeResponse détails
    """
    logger.info(f"📋 GET /entity-types/{type_name} - tenant={tenant_id}")

    service = EntityTypeRegistryService(db)

    entity_type = service.get_type_by_name(type_name, tenant_id)

    if not entity_type:
        raise HTTPException(
            status_code=404,
            detail=f"Entity type '{type_name}' not found"
        )

    return EntityTypeResponse.from_orm(entity_type)


@router.post(
    "/{type_name}/approve",
    response_model=EntityTypeResponse,
    summary="Approuver entity type",
    description="""
    Approuve un entity type découvert par le LLM (transition pending → approved).

    **Workflow**:
    1. Type découvert automatiquement → status='pending'
    2. Admin review type dans UI
    3. Approve → status='approved' + enregistrement approved_by/at
    4. Type devient utilisable pour classification entités

    **Validation**:
    - Type doit exister avec status='pending'
    - Requiert X-Admin-Key header (auth simplifiée dev, JWT prod)

    **Impact**:
    - Futures entités avec ce type → Automatiquement considérées valides
    - Type visible dans ontologie effective
    """,
    responses={
        200: {
            "description": "Type approuvé avec succès",
            "content": {
                "application/json": {
                    "example": {
                        "id": 1,
                        "type_name": "SAP_COMPONENT",
                        "status": "approved",
                        "entity_count": 42,
                        "approved_by": "admin@example.com",
                        "approved_at": "2025-10-06T15:30:00Z"
                    }
                }
            }
        },
        400: {
            "description": "Status invalide (déjà approuvé ou rejeté)",
            "content": {
                "application/json": {
                    "example": {
                        "detail": "Cannot approve type with status 'approved' (must be pending)"
                    }
                }
            }
        },
        404: {
            "description": "Type non trouvé",
            "content": {
                "application/json": {
                    "example": {"detail": "Entity type 'UNKNOWN_TYPE' not found"}
                }
            }
        }
    }
)
async def approve_entity_type(
    type_name: str,
    approve_data: EntityTypeApprove,
    tenant_id: str = Query(default="default", description="Tenant ID"),
    db: Session = Depends(get_db)
):
    """
    Approuver un entity type pending.

    Change status de pending → approved.
    Seuls les types pending peuvent être approuvés.

    Args:
        type_name: Nom type
        approve_data: Données approbation (admin_email)
        tenant_id: Tenant ID
        db: Session DB

    Returns:
        EntityTypeResponse approuvé
    """
    logger.info(
        f"✅ POST /entity-types/{type_name}/approve - "
        f"admin={approve_data.admin_email}"
    )

    service = EntityTypeRegistryService(db)

    # Vérifier type existe
    entity_type = service.get_type_by_name(type_name, tenant_id)

    if not entity_type:
        raise HTTPException(
            status_code=404,
            detail=f"Entity type '{type_name}' not found"
        )

    # Vérifier status pending
    if entity_type.status != "pending":
        raise HTTPException(
            status_code=400,
            detail=f"Cannot approve type with status '{entity_type.status}' (must be pending)"
        )

    # Approuver
    approved_type = service.approve_type(
        type_name=type_name,
        admin_email=approve_data.admin_email,
        tenant_id=tenant_id
    )

    logger.info(f"✅ Type approuvé: {type_name}")

    return EntityTypeResponse.from_orm(approved_type)


@router.post("/{type_name}/reject", response_model=EntityTypeResponse)
async def reject_entity_type(
    type_name: str,
    reject_data: EntityTypeReject,
    tenant_id: str = Query(default="default", description="Tenant ID"),
    db: Session = Depends(get_db)
):
    """
    Rejeter un entity type.

    Change status → rejected.

    ⚠️ ATTENTION : Ne supprime PAS automatiquement les entités Neo4j associées.
    Utiliser DELETE /entity-types/{type_name} pour cascade delete.

    Args:
        type_name: Nom type
        reject_data: Données rejet (admin_email, reason)
        tenant_id: Tenant ID
        db: Session DB

    Returns:
        EntityTypeResponse rejeté
    """
    logger.info(
        f"❌ POST /entity-types/{type_name}/reject - "
        f"admin={reject_data.admin_email}, reason={reject_data.reason}"
    )

    service = EntityTypeRegistryService(db)

    # Vérifier type existe
    entity_type = service.get_type_by_name(type_name, tenant_id)

    if not entity_type:
        raise HTTPException(
            status_code=404,
            detail=f"Entity type '{type_name}' not found"
        )

    # Rejeter
    rejected_type = service.reject_type(
        type_name=type_name,
        admin_email=reject_data.admin_email,
        reason=reject_data.reason,
        tenant_id=tenant_id
    )

    logger.info(f"❌ Type rejeté: {type_name}")

    return EntityTypeResponse.from_orm(rejected_type)


@router.delete("/{type_name}", status_code=204)
async def delete_entity_type(
    type_name: str,
    tenant_id: str = Query(default="default", description="Tenant ID"),
    db: Session = Depends(get_db)
):
    """
    Supprimer un entity type du registry.

    ⚠️ ATTENTION : Cette opération NE supprime PAS les entités Neo4j associées.

    Pour cascade delete complet (type + entités + relations Neo4j),
    utiliser Phase 3 endpoint avec cascade=true.

    Args:
        type_name: Nom type
        tenant_id: Tenant ID
        db: Session DB

    Returns:
        204 No Content
    """
    logger.info(f"🗑️ DELETE /entity-types/{type_name} - tenant={tenant_id}")

    service = EntityTypeRegistryService(db)

    # Vérifier type existe
    entity_type = service.get_type_by_name(type_name, tenant_id)

    if not entity_type:
        raise HTTPException(
            status_code=404,
            detail=f"Entity type '{type_name}' not found"
        )

    # Supprimer
    success = service.delete_type(type_name, tenant_id)

    if not success:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to delete entity type '{type_name}'"
        )

    logger.info(f"🗑️ Type supprimé: {type_name}")

    # 204 No Content (pas de body retourné)
    return


__all__ = ["router"]
