"""
Router API pour gestion Entity Types Registry.

Phase 2 - Entity Types Management
Phase 5B - Ontology Generation & Normalization

Endpoints:
- GET /entity-types - Liste tous les types
- POST /entity-types - Créer nouveau type (admin)
- GET /entity-types/{type_name} - Détails type
- POST /entity-types/{type_name}/approve - Approuver type
- POST /entity-types/{type_name}/reject - Rejeter type
- DELETE /entity-types/{type_name} - Supprimer type
- POST /entity-types/import-yaml - Import bulk depuis fichier YAML
- GET /entity-types/export-yaml - Export types en YAML
- POST /entity-types/{type_name}/generate-ontology - Génération ontologie LLM (async)
- GET /entity-types/{type_name}/ontology-proposal - Récupérer proposition ontologie
"""
from typing import Optional, Dict, List
from datetime import datetime, timedelta
import yaml
from io import StringIO

from fastapi import APIRouter, HTTPException, Query, Depends, UploadFile, File, BackgroundTasks, Body
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from redis import Redis
from rq import Queue
from rq.job import Job

from knowbase.api.schemas.entity_types import (
    EntityTypeCreate,
    EntityTypeResponse,
    EntityTypeApprove,
    EntityTypeReject,
    EntityTypeListResponse,
)
from knowbase.api.services.entity_type_registry_service import EntityTypeRegistryService
from knowbase.api.dependencies import require_admin, require_editor, get_tenant_id, get_current_user
from knowbase.api.validators import validate_entity_type
from knowbase.api.utils.audit_helpers import log_audit
from knowbase.common.log_sanitizer import sanitize_for_log
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
    tenant_id: str = Depends(get_tenant_id),  # ✅ Phase 0 - JWT
    current_user: dict = Depends(get_current_user),  # ✅ Phase 0 - Auth
    status: Optional[str] = Query(
        default=None,
        description="Filtrer par status (pending | approved | rejected)",
        example="pending"
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
        f"📋 GET /entity-types - status={sanitize_for_log(status)}, "
        f"tenant={tenant_id}, user={current_user.get('email')}, "
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

        # ✨ Enrichir avec compteurs dynamiques depuis Neo4j
        from knowbase.api.services.knowledge_graph_service import KnowledgeGraphService
        kg_service = KnowledgeGraphService()

        for entity_type in types:
            # Compter entités dans Neo4j
            counts = kg_service.count_entities_by_type(
                entity_type=entity_type.type_name,
                tenant_id=tenant_id
            )

            # Mettre à jour les compteurs
            entity_type.entity_count = counts.get('total', 0)
            entity_type.pending_entity_count = counts.get('pending', 0)
            # Calculer validées = total - pending
            entity_type.validated_entity_count = counts.get('total', 0) - counts.get('pending', 0)

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
    tenant_id: str = Depends(get_tenant_id),  # ✅ Phase 0 - JWT tenant_id
    current_user: dict = Depends(require_editor),  # ✅ Phase 0 - Editor role required
    db: Session = Depends(get_db)
):
    """
    Créer nouveau entity type (admin).

    Crée un nouveau type dans le registry avec status=pending.
    Si type existe déjà, retourne erreur 409 Conflict.

    Args:
        entity_type: Données type à créer
        tenant_id: Tenant ID (depuis JWT)
        db: Session DB

    Returns:
        EntityTypeResponse créé
    """
    logger.info(
        f"📝 POST /entity-types - type_name={sanitize_for_log(entity_type.type_name)}, "
        f"user={current_user.get('email')}"
    )

    service = EntityTypeRegistryService(db)

    try:
        # Vérifier si type existe déjà (utilise tenant_id du JWT)
        existing = service.get_type_by_name(
            entity_type.type_name,
            tenant_id
        )

        if existing:
            raise HTTPException(
                status_code=409,
                detail=f"Entity type '{entity_type.type_name}' already exists"
            )

        # Créer type (utilise tenant_id du JWT)
        new_type = service.get_or_create_type(
            type_name=entity_type.type_name,
            tenant_id=tenant_id,
            discovered_by=entity_type.discovered_by
        )

        # Mettre à jour description si fournie
        if entity_type.description:
            new_type.description = entity_type.description
            db.commit()
            db.refresh(new_type)

        logger.info(f"✅ Type créé: {new_type.type_name} (id={new_type.id})")

        # Audit logging (Phase 0 - Audit Trail)
        log_audit(
            action="CREATE",
            user=current_user,
            resource_type="entity_type",
            resource_id=str(new_type.id),
            tenant_id=tenant_id,
            details=f"Entity type '{new_type.type_name}' created, status={new_type.status}"
        )

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
    tenant_id: str = Depends(get_tenant_id),  # ✅ Phase 0 - JWT
    current_user: dict = Depends(get_current_user),  # ✅ Phase 0 - Auth
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
    # Validation type_name (Phase 0 - Input Validation)
    try:
        type_name = validate_entity_type(type_name)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    logger.info(
        f"📋 GET /entity-types/{sanitize_for_log(type_name)} - "
        f"tenant={tenant_id}, user={current_user.get('email')}"
    )

    service = EntityTypeRegistryService(db)

    entity_type = service.get_type_by_name(type_name, tenant_id)

    if not entity_type:
        raise HTTPException(
            status_code=404,
            detail=f"Entity type '{type_name}' not found"
        )

    # ✨ Enrichir avec compteurs dynamiques depuis Neo4j
    from knowbase.api.services.knowledge_graph_service import KnowledgeGraphService
    kg_service = KnowledgeGraphService()

    counts = kg_service.count_entities_by_type(
        entity_type=entity_type.type_name,
        tenant_id=tenant_id
    )

    # Construire la réponse avec les compteurs mis à jour
    return EntityTypeResponse(
        id=entity_type.id,
        type_name=entity_type.type_name,
        description=entity_type.description,
        status=entity_type.status,
        first_seen=entity_type.first_seen,
        discovered_by=entity_type.discovered_by,
        entity_count=counts.get('total', 0),
        pending_entity_count=counts.get('pending', 0),
        approved_by=entity_type.approved_by,
        approved_at=entity_type.approved_at,
        rejected_by=entity_type.rejected_by,
        rejected_at=entity_type.rejected_at,
        rejection_reason=entity_type.rejection_reason,
        normalization_status=entity_type.normalization_status,
        normalization_job_id=entity_type.normalization_job_id,
        normalization_started_at=entity_type.normalization_started_at,
        tenant_id=entity_type.tenant_id,
        created_at=entity_type.created_at,
        updated_at=entity_type.updated_at
    )


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
    tenant_id: str = Depends(get_tenant_id),  # ✅ Phase 0 - JWT
    admin: dict = Depends(require_admin),  # ✅ Phase 0 - Admin only
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
    # Validation type_name (Phase 0 - Input Validation)
    try:
        type_name = validate_entity_type(type_name)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    logger.info(
        f"✅ POST /entity-types/{sanitize_for_log(type_name)}/approve - "
        f"admin={admin.get('email')}"
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

    # Audit logging (Phase 0 - Audit Trail)
    log_audit(
        action="APPROVE",
        user=admin,
        resource_type="entity_type",
        resource_id=str(approved_type.id),
        tenant_id=tenant_id,
        details=f"Entity type '{type_name}' approved"
    )

    return EntityTypeResponse.from_orm(approved_type)


@router.post("/{type_name}/reject", response_model=EntityTypeResponse)
async def reject_entity_type(
    type_name: str,
    reject_data: EntityTypeReject,
    tenant_id: str = Depends(get_tenant_id),  # ✅ Phase 0 - JWT
    admin: dict = Depends(require_admin),  # ✅ Phase 0 - Admin only
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
    # Validation type_name (Phase 0 - Input Validation)
    try:
        type_name = validate_entity_type(type_name)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    logger.info(
        f"❌ POST /entity-types/{sanitize_for_log(type_name)}/reject - "
        f"admin={admin.get('email')}, reason={sanitize_for_log(reject_data.reason)}"
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

    # Audit logging (Phase 0 - Audit Trail)
    log_audit(
        action="REJECT",
        user=admin,
        resource_type="entity_type",
        resource_id=str(rejected_type.id),
        tenant_id=tenant_id,
        details=f"Entity type '{type_name}' rejected, reason={reject_data.reason}"
    )

    return EntityTypeResponse.from_orm(rejected_type)


@router.delete("/{type_name}", status_code=204)
async def delete_entity_type(
    type_name: str,
    tenant_id: str = Depends(get_tenant_id),  # ✅ Phase 0 - JWT
    admin: dict = Depends(require_admin),  # ✅ Phase 0 - Admin only
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
    # Validation type_name (Phase 0 - Input Validation)
    try:
        type_name = validate_entity_type(type_name)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    logger.info(
        f"🗑️ DELETE /entity-types/{sanitize_for_log(type_name)} - "
        f"tenant={tenant_id}, admin={admin.get('email')}"
    )

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

    # Audit logging (Phase 0 - Audit Trail)
    log_audit(
        action="DELETE",
        user=admin,
        resource_type="entity_type",
        resource_id=str(entity_type.id),
        tenant_id=tenant_id,
        details=f"Entity type '{type_name}' deleted from registry"
    )

    # 204 No Content (pas de body retourné)
    return


@router.post(
    "/import-yaml",
    summary="Import bulk entity types depuis YAML",
    description="""
    Importe entity types depuis fichier YAML (format ontologies).

    **Format YAML attendu**:
    ```yaml
    ENTITY_TYPE_NAME:
      canonical_name: "Display Name"
      aliases:
        - "Alias1"
        - "Alias2"
      category: "Category Name"
      vendor: "Vendor Name"
      description: "Type description"
    ```

    **Options**:
    - `auto_approve=true`: Types créés directement en status='approved'
    - `auto_approve=false`: Types créés en status='pending' (validation manuelle)
    - `skip_existing=true`: Ignore types déjà existants
    - `skip_existing=false`: Retourne erreur si type existe

    **Use Cases**:
    - Bootstrap rapide environnement avec ontologies prédéfinies
    - Migration types entre environnements
    - Réinitialisation système avec types métier

    **Returns**:
    - `created`: Nombre types créés
    - `skipped`: Nombre types ignorés (déjà existants)
    - `errors`: Liste erreurs rencontrées
    """,
    responses={
        200: {
            "description": "Import réussi",
            "content": {
                "application/json": {
                    "example": {
                        "created": 15,
                        "skipped": 3,
                        "errors": [],
                        "types": ["TECHNOLOGY", "COMPONENT", "SOLUTION"]
                    }
                }
            }
        },
        400: {
            "description": "Format YAML invalide",
            "content": {
                "application/json": {
                    "example": {"detail": "Invalid YAML format"}
                }
            }
        }
    }
)
async def import_entity_types_yaml(
    file: UploadFile = File(..., description="Fichier YAML à importer"),
    tenant_id: str = Depends(get_tenant_id),  # ✅ Phase 0 - JWT
    admin: dict = Depends(require_admin),  # ✅ Phase 0 - Admin only (bulk create)
    auto_approve: bool = Query(default=True, description="Auto-approuver types importés"),
    skip_existing: bool = Query(default=True, description="Ignorer types existants"),
    db: Session = Depends(get_db)
):
    """
    Import bulk entity types depuis fichier YAML.

    Parse fichier YAML format ontologies et crée types dans registry.
    """
    logger.info(
        f"📤 POST /entity-types/import-yaml - "
        f"file={sanitize_for_log(file.filename)}, auto_approve={auto_approve}, "
        f"skip_existing={skip_existing}, admin={admin.get('email')}"
    )

    # Vérifier extension fichier
    if not file.filename.endswith(('.yaml', '.yml')):
        raise HTTPException(
            status_code=400,
            detail="File must be .yaml or .yml"
        )

    # Lire contenu fichier
    try:
        content = await file.read()
        yaml_data = yaml.safe_load(content.decode('utf-8'))
    except yaml.YAMLError as e:
        logger.error(f"❌ YAML parse error: {e}")
        raise HTTPException(
            status_code=400,
            detail=f"Invalid YAML format: {str(e)}"
        )
    except Exception as e:
        logger.error(f"❌ File read error: {e}")
        raise HTTPException(
            status_code=400,
            detail=f"Failed to read file: {str(e)}"
        )

    if not isinstance(yaml_data, dict):
        raise HTTPException(
            status_code=400,
            detail="YAML root must be dictionary"
        )

    service = EntityTypeRegistryService(db)

    created = 0
    skipped = 0
    errors = []
    created_types = []

    # Traiter chaque type du YAML
    for type_name, type_data in yaml_data.items():
        # Valider format type_name (doit matcher ^[A-Z][A-Z0-9_]{0,49}$)
        if not type_name.isupper() or not type_name.replace('_', '').isalnum():
            errors.append(f"Invalid type_name format: {type_name}")
            continue

        # Vérifier si type existe déjà
        existing = service.get_type_by_name(type_name, tenant_id)

        if existing:
            if skip_existing:
                skipped += 1
                logger.info(f"⏭️ Skipped existing type: {type_name}")
                continue
            else:
                errors.append(f"Type already exists: {type_name}")
                continue

        # Extraire description du YAML
        description = None
        if isinstance(type_data, dict):
            description = type_data.get('description') or type_data.get('canonical_name')

        # Créer type
        try:
            status = "approved" if auto_approve else "pending"
            approved_by = "yaml-import" if auto_approve else None

            new_type = service.create_type(
                type_name=type_name,
                description=description,
                discovered_by="yaml-import",
                tenant_id=tenant_id,
                status=status,
                approved_by=approved_by
            )

            created += 1
            created_types.append(type_name)
            logger.info(f"✅ Created type: {type_name} (status={status})")

        except Exception as e:
            errors.append(f"Failed to create {type_name}: {str(e)}")
            logger.error(f"❌ Failed to create type {type_name}: {e}")

    logger.info(
        f"📤 Import YAML terminé - created={created}, skipped={skipped}, errors={len(errors)}"
    )

    return {
        "created": created,
        "skipped": skipped,
        "errors": errors,
        "types": created_types
    }


@router.get(
    "/export-yaml",
    summary="Export entity types en YAML",
    description="""
    Exporte tous les entity types (ou filtrés) au format YAML ontologie.

    **Filtres disponibles**:
    - `status`: Filtrer par status (pending/approved/rejected)
    - `tenant_id`: Tenant ID

    **Format retourné**:
    ```yaml
    ENTITY_TYPE_NAME:
      canonical_name: "Type Name"
      description: "Type description"
      status: "approved"
      entity_count: 42
    ```

    **Use Cases**:
    - Backup types approuvés
    - Migration types vers autre environnement
    - Documentation ontologie effective
    - Réimport après réinitialisation système
    """,
    responses={
        200: {
            "description": "Export YAML réussi",
            "content": {
                "application/x-yaml": {
                    "example": "TECHNOLOGY:\n  canonical_name: Technology\n  status: approved\n"
                }
            }
        }
    }
)
async def export_entity_types_yaml(
    tenant_id: str = Depends(get_tenant_id),  # ✅ Phase 0 - JWT
    current_user: dict = Depends(get_current_user),  # ✅ Phase 0 - Auth
    status: Optional[str] = Query(default=None, description="Filtrer par status"),
    db: Session = Depends(get_db)
):
    """
    Export entity types en fichier YAML.

    Retourne fichier YAML téléchargeable format ontologies.
    """
    logger.info(
        f"📥 GET /entity-types/export-yaml - status={status}, tenant_id={tenant_id}"
    )

    service = EntityTypeRegistryService(db)

    # Récupérer types
    types = service.list_types(
        status=status,
        tenant_id=tenant_id,
        limit=1000,
        offset=0
    )

    # Construire structure YAML
    yaml_data = {}

    for entity_type in types:
        yaml_data[entity_type.type_name] = {
            "canonical_name": entity_type.type_name.replace('_', ' ').title(),
            "description": entity_type.description or f"{entity_type.type_name} entities",
            "status": entity_type.status,
            "entity_count": entity_type.entity_count,
            "discovered_by": entity_type.discovered_by,
        }

        # Ajouter infos approbation si applicable
        if entity_type.approved_by:
            yaml_data[entity_type.type_name]["approved_by"] = entity_type.approved_by
            yaml_data[entity_type.type_name]["approved_at"] = entity_type.approved_at.isoformat() if entity_type.approved_at else None

    # Convertir en YAML
    yaml_output = yaml.dump(yaml_data, default_flow_style=False, allow_unicode=True, sort_keys=True)

    # Créer stream pour download
    yaml_stream = StringIO(yaml_output)

    filename = f"entity_types_{status or 'all'}_{tenant_id}.yaml"

    logger.info(f"📥 Export YAML généré - {len(types)} types, filename={filename}")

    return StreamingResponse(
        iter([yaml_stream.getvalue()]),
        media_type="application/x-yaml",
        headers={
            "Content-Disposition": f"attachment; filename={filename}"
        }
    )


@router.post(
    "/{type_name}/generate-ontology",
    summary="Génère ontologie depuis entités (LLM async)",
    description="""
    Déclenche job async de génération d'ontologie via LLM.

    **Workflow**:
    1. Récupère toutes entités du type
    2. Lance job RQ avec OntologyGeneratorService
    3. LLM (Claude Sonnet) analyse et propose groupes + aliases
    4. Résultat stocké en Redis (clé: ontology_proposal:{type_name})

    **Prérequis**:
    - Type doit exister
    - Au moins 1 entité du type

    **Returns**:
    - `job_id`: ID job RQ pour suivi
    - `status_url`: URL pour vérifier progression
    """,
    responses={
        202: {
            "description": "Job lancé",
            "content": {
                "application/json": {
                    "example": {
                        "job_id": "abc-123",
                        "status": "queued",
                        "status_url": "/api/jobs/abc-123/status"
                    }
                }
            }
        }
    }
)
async def generate_ontology(
    type_name: str,
    tenant_id: str = Depends(get_tenant_id),  # ✅ Phase 0 - JWT
    admin: dict = Depends(require_admin),  # ✅ Phase 0 - Admin only (ontology generation)
    model_preference: str = Query(default="claude-sonnet", description="Modèle LLM"),
    include_validated: bool = Query(default=False, description="Inclure entités validées (⚠️ peut re-proposer merges existants)"),
    db: Session = Depends(get_db)
):
    """
    Génère ontologie pour type via job async LLM.

    Args:
        type_name: Nom type
        model_preference: Modèle LLM (default: claude-sonnet)
        include_validated: Si False (défaut), analyse seulement entités pending. Si True, inclut aussi validated.
        tenant_id: Tenant ID
        db: Session DB

    Returns:
        Dict avec job_id et status_url
    """
    from knowbase.api.services.knowledge_graph_service import KnowledgeGraphService
    import os

    logger.info(f"🤖 POST /entity-types/{type_name}/generate-ontology - model={model_preference}")

    # Vérifier type existe
    service = EntityTypeRegistryService(db)
    entity_type = service.get_type_by_name(type_name, tenant_id)

    if not entity_type:
        raise HTTPException(
            status_code=404,
            detail=f"Entity type '{type_name}' not found"
        )

    # Récupérer entités Neo4j
    kg_service = KnowledgeGraphService()
    entities_raw = kg_service.get_entities_by_type(type_name, tenant_id)

    # Filtrer selon include_validated
    if include_validated:
        # Inclure toutes les entités (pending + validated)
        entities_filtered = entities_raw
        logger.info(f"⚠️ include_validated=True : analyse de TOUTES les entités (peut re-proposer merges)")
    else:
        # Par défaut : seulement les pending (protection entités validées)
        entities_filtered = [e for e in entities_raw if e.get("status") == "pending"]
        logger.info(f"✅ include_validated=False : analyse seulement entités pending (protection validées)")

    if len(entities_filtered) == 0:
        status_hint = " (Astuce : activez 'include_validated' si vous voulez analyser les entités validées)" if not include_validated else ""
        raise HTTPException(
            status_code=400,
            detail=f"No pending entities found for type '{type_name}'.{status_hint}"
        )

    # Formater entités pour OntologyGenerator
    entities = [
        {
            "uuid": e.get("uuid"),
            "name": e.get("name"),
            "description": e.get("description", ""),
            "status": e.get("status", "pending")
        }
        for e in entities_filtered
    ]

    logger.info(f"📊 {len(entities)} entités récupérées pour génération ontologie")

    # Limiter à 50 entités max pour éviter erreurs JSON trop long
    MAX_ENTITIES = 50
    if len(entities) > MAX_ENTITIES:
        logger.warning(f"⚠️ {len(entities)} entités trouvées, limitation à {MAX_ENTITIES} pour éviter timeout LLM")
        entities = entities[:MAX_ENTITIES]

    # Enqueue job RQ dans queue "ingestion" (même queue que worker)
    redis_conn = Redis(
        host=os.getenv("REDIS_HOST", "redis"),
        port=int(os.getenv("REDIS_PORT", "6379")), password=os.getenv("REDIS_PASSWORD") or None,
        db=0  # Même DB que worker ingestion
    )
    queue = Queue("ingestion", connection=redis_conn)

    job = queue.enqueue(
        "knowbase.api.workers.ontology_worker.generate_ontology_task",
        type_name=type_name,
        entities=entities,
        model_preference=model_preference,
        tenant_id=tenant_id,
        job_timeout="10m"
    )

    logger.info(f"✅ Job ontology generation enqueued: {job.id}")

    # Mettre à jour statut normalisation dans registry
    from datetime import datetime, timezone
    entity_type.normalization_status = 'generating'
    entity_type.normalization_job_id = job.id
    entity_type.normalization_started_at = datetime.now(timezone.utc)
    db.commit()
    logger.info(f"📝 Statut normalisation mis à jour: generating (job={job.id})")

    return {
        "job_id": job.id,
        "status": "queued",
        "status_url": f"/api/jobs/{job.id}/status",
        "entities_count": len(entities)
    }


@router.get(
    "/{type_name}/ontology-proposal",
    summary="Récupère proposition ontologie générée",
    description="""
    Récupère ontologie proposée par LLM (après génération async).

    **Returns**:
    - Ontologie au format JSON éditable
    - null si génération pas encore lancée ou en cours
    """,
    responses={
        200: {
            "description": "Ontologie disponible",
            "content": {
                "application/json": {
                    "example": {
                        "entity_type": "SOLUTION",
                        "generated_at": "2025-10-06T...",
                        "groups_proposed": 12,
                        "ontology": {
                            "SAP_S4HANA_PRIVATE_CLOUD": {
                                "canonical_name": "SAP S/4HANA Private Cloud Edition",
                                "aliases": ["SAP S/4HANA PCE"],
                                "confidence": 0.95,
                                "entities_merged": ["uuid-1", "uuid-2"]
                            }
                        }
                    }
                }
            }
        },
        404: {
            "description": "Ontologie pas encore générée"
        }
    }
)
async def get_ontology_proposal(
    type_name: str,
    tenant_id: str = Depends(get_tenant_id),  # ✅ Phase 0 - JWT
    current_user: dict = Depends(get_current_user)  # ✅ Phase 0 - Auth
):
    """
    Récupère ontologie proposée depuis Redis.

    Args:
        type_name: Nom type
        tenant_id: Tenant ID

    Returns:
        Dict ontologie ou 404
    """
    import os
    import json

    logger.info(f"📥 GET /entity-types/{type_name}/ontology-proposal")

    redis_conn = Redis(
        host=os.getenv("REDIS_HOST", "redis"),
        port=int(os.getenv("REDIS_PORT", "6379")), password=os.getenv("REDIS_PASSWORD") or None,
        db=1
    )

    # Clé Redis pour proposition ontologie
    redis_key = f"ontology_proposal:{type_name}:{tenant_id}"

    ontology_json = redis_conn.get(redis_key)

    if not ontology_json:
        raise HTTPException(
            status_code=404,
            detail=f"No ontology proposal found for type '{type_name}'. Generate one first."
        )

    ontology_data = json.loads(ontology_json)

    logger.info(f"✅ Ontologie trouvée: {ontology_data.get('groups_proposed', 0)} groupes")

    return ontology_data


@router.delete(
    "/{type_name}/ontology-proposal",
    summary="Annuler normalisation en cours",
    description="""
    Annule processus de normalisation pour un type:
    - Supprime ontologie en cache Redis
    - Réinitialise statut normalisation dans registry

    **Use case**: Utilisateur décide de ne pas valider les propositions.
    """,
    responses={
        200: {
            "description": "Normalisation annulée",
            "content": {
                "application/json": {
                    "example": {
                        "message": "Normalisation annulée",
                        "type_name": "SOLUTION"
                    }
                }
            }
        }
    }
)
async def cancel_normalization(
    type_name: str,
    tenant_id: str = Depends(get_tenant_id),  # ✅ Phase 0 - JWT
    admin: dict = Depends(require_admin),  # ✅ Phase 0 - Admin only
    db: Session = Depends(get_db)
):
    """
    Annule normalisation en cours.

    Args:
        type_name: Nom type
        tenant_id: Tenant ID
        db: Session DB

    Returns:
        Dict confirmation
    """
    import os
    import json

    logger.info(f"🗑️ DELETE /entity-types/{type_name}/ontology-proposal - Annulation normalisation")

    # Supprimer cache Redis
    redis_conn = Redis(
        host=os.getenv("REDIS_HOST", "redis"),
        port=int(os.getenv("REDIS_PORT", "6379")), password=os.getenv("REDIS_PASSWORD") or None,
        db=1
    )

    redis_key = f"ontology_proposal:{type_name}:{tenant_id}"
    deleted_count = redis_conn.delete(redis_key)

    if deleted_count > 0:
        logger.info(f"✅ Cache Redis supprimé: {redis_key}")
    else:
        logger.info(f"ℹ️ Pas de cache Redis à supprimer")

    # Réinitialiser statut dans registry
    service = EntityTypeRegistryService(db)
    entity_type = service.get_type_by_name(type_name, tenant_id)

    if entity_type:
        entity_type.normalization_status = None
        entity_type.normalization_job_id = None
        entity_type.normalization_started_at = None
        db.commit()
        logger.info(f"📝 Statut normalisation réinitialisé pour {type_name}")
    else:
        logger.warning(f"⚠️ Type {type_name} non trouvé dans registry")

    return {
        "message": "Normalisation annulée",
        "type_name": type_name,
        "cache_deleted": deleted_count > 0
    }


@router.post(
    "/{type_name}/preview-normalization",
    summary="Preview normalisation entités avec ontologie",
    description="""
    Calcule preview des merges entre entités et ontologie (fuzzy matching).

    **Workflow**:
    1. Récupère entités du type depuis Neo4j
    2. Applique fuzzy matching avec ontologie fournie
    3. Retourne groupes proposés avec scores

    **Seuils fuzzy matching**:
    - >= 90% : Auto-coché (haute confiance)
    - 75-89% : Suggéré mais décoché (confirmation manuelle)
    - < 75% : Pas de match

    **Returns**:
    - `merge_groups`: Groupes proposés avec entités matchées
    - `summary`: Statistiques (total, matchées, auto, manuelles)
    """,
    responses={
        200: {
            "description": "Preview calculé",
            "content": {
                "application/json": {
                    "example": {
                        "merge_groups": [
                            {
                                "canonical_key": "SAP_S4HANA_PRIVATE_CLOUD",
                                "canonical_name": "SAP S/4HANA Private Cloud Edition",
                                "entities": [
                                    {
                                        "uuid": "...",
                                        "name": "SAP S/4HANA PCE",
                                        "score": 92,
                                        "auto_match": True,
                                        "selected": True
                                    }
                                ],
                                "master_uuid": "..."
                            }
                        ],
                        "summary": {
                            "total_entities": 47,
                            "entities_matched": 35,
                            "groups_proposed": 12
                        }
                    }
                }
            }
        }
    }
)
async def preview_normalization(
    type_name: str,
    ontology: Dict = Body(..., description="Ontologie fournie (depuis LLM ou manuelle)"),
    tenant_id: str = Depends(get_tenant_id),  # ✅ Phase 0 - JWT
    current_user: dict = Depends(get_current_user)  # ✅ Phase 0 - Auth
):
    """
    Calcule preview normalisation avec fuzzy matching.

    Args:
        type_name: Nom type
        ontology: Dict ontologie (format OntologyGenerator)
        tenant_id: Tenant ID

    Returns:
        Dict avec merge_groups et summary
    """
    from knowbase.api.services.knowledge_graph_service import KnowledgeGraphService
    from knowbase.api.services.fuzzy_matcher_service import FuzzyMatcherService

    logger.info(f"🔍 POST /entity-types/{type_name}/preview-normalization")

    # Récupérer entités Neo4j
    kg_service = KnowledgeGraphService()
    entities_raw = kg_service.get_entities_by_type(type_name, tenant_id)

    entities = [
        {
            "uuid": e.get("uuid"),
            "name": e.get("name"),
            "description": e.get("description", ""),
            "status": e.get("status", "pending")
        }
        for e in entities_raw
    ]

    logger.info(f"📊 {len(entities)} entités récupérées pour preview")

    # Extraire ontologie si wrappée dans {"ontology": ...}
    if "ontology" in ontology and len(ontology) == 1:
        ontology = ontology["ontology"]

    logger.info(f"🔍 Ontologie reçue: {list(ontology.keys()) if ontology else 'None'}")

    # Calculer preview avec fuzzy matching
    fuzzy_service = FuzzyMatcherService()
    preview = fuzzy_service.compute_merge_preview(entities, ontology)

    logger.info(
        f"✅ Preview généré: {preview['summary']['groups_proposed']} groupes, "
        f"{preview['summary']['entities_matched']}/{preview['summary']['total_entities']} matchées"
    )

    return preview


@router.post(
    "/{type_name}/normalize-entities",
    summary="Lance normalisation entités (merge + job async)",
    description="""
    Déclenche job async de normalisation (merge) des entités.

    **Workflow**:
    1. Reçoit sélections utilisateur (groupes + entités cochées)
    2. Lance job RQ EntityMergeService
    3. Batch merge tous les groupes sélectionnés
    4. Snapshot pré-normalisation pour undo (24h)

    **Body**:
    ```json
    {
        "merge_groups": [...],  // Preview filtré par user
        "create_snapshot": true  // Activer undo (default: true)
    }
    ```

    **Returns**:
    - `job_id`: ID job RQ
    - `status_url`: URL monitoring
    """,
    responses={
        202: {
            "description": "Job lancé",
            "content": {
                "application/json": {
                    "example": {
                        "job_id": "xyz-789",
                        "status": "queued",
                        "status_url": "/api/jobs/xyz-789/status",
                        "groups_count": 12,
                        "entities_count": 35
                    }
                }
            }
        }
    }
)
async def normalize_entities(
    type_name: str,
    merge_groups: List[Dict] = Body(..., description="Groupes validés par user"),
    create_snapshot: bool = Body(default=True, description="Créer snapshot pour undo"),
    tenant_id: str = Depends(get_tenant_id),  # ✅ Phase 0 - JWT
    admin: dict = Depends(require_admin),  # ✅ Phase 0 - Admin only (normalization)
    db: Session = Depends(get_db)
):
    """
    Lance normalisation async.

    Args:
        type_name: Nom type
        merge_groups: Groupes depuis preview (filtrés par user)
        create_snapshot: Créer snapshot pour undo
        tenant_id: Tenant ID
        db: Session DB

    Returns:
        Dict job info
    """
    import os

    logger.info(
        f"🚀 POST /entity-types/{type_name}/normalize-entities - "
        f"{len(merge_groups)} groupes"
    )

    # Enqueue job RQ
    redis_conn = Redis(
        host=os.getenv("REDIS_HOST", "redis"),
        port=int(os.getenv("REDIS_PORT", "6379")), password=os.getenv("REDIS_PASSWORD") or None,
        db=0  # Même DB que worker ingestion
    )
    queue = Queue("ingestion", connection=redis_conn)

    job = queue.enqueue(
        "knowbase.api.workers.normalization_worker.normalize_entities_task",
        type_name=type_name,
        merge_groups=merge_groups,
        tenant_id=tenant_id,
        create_snapshot=create_snapshot,
        job_timeout="30m"
    )

    entities_count = sum(len(g["entities"]) for g in merge_groups)

    logger.info(f"✅ Job normalisation enqueued: {job.id}")

    # Réinitialiser statut normalisation (validation appliquée)
    service = EntityTypeRegistryService(db)
    entity_type = service.get_type_by_name(type_name, tenant_id)

    if entity_type:
        entity_type.normalization_status = None
        entity_type.normalization_job_id = None
        entity_type.normalization_started_at = None
        db.commit()
        logger.info(f"📝 Statut normalisation réinitialisé (validation appliquée)")

    # Supprimer cache Redis aussi
    redis_conn_cache = Redis(
        host=os.getenv("REDIS_HOST", "redis"),
        port=int(os.getenv("REDIS_PORT", "6379")), password=os.getenv("REDIS_PASSWORD") or None,
        db=1
    )
    redis_key = f"ontology_proposal:{type_name}:{tenant_id}"
    redis_conn_cache.delete(redis_key)
    logger.info(f"🗑️ Cache ontologie supprimé après validation")

    return {
        "job_id": job.id,
        "status": "queued",
        "status_url": f"/api/jobs/{job.id}/status",
        "groups_count": len(merge_groups),
        "entities_count": entities_count
    }


@router.post(
    "/{type_name}/undo-normalization/{snapshot_id}",
    summary="Annule normalisation (undo via snapshot)",
    description="""
    Restaure état pré-normalisation depuis snapshot.

    **Workflow**:
    1. Récupère snapshot depuis SQLite
    2. Vérifie TTL (24h)
    3. Lance job RQ de restauration
    4. Recrée entités mergées + supprime master

    **⚠️ ATTENTION**: Cette opération est irréversible.

    **Returns**:
    - `job_id`: ID job restauration
    """,
    responses={
        202: {
            "description": "Undo lancé",
            "content": {
                "application/json": {
                    "example": {
                        "job_id": "undo-123",
                        "status": "queued",
                        "snapshot_id": "abc-456"
                    }
                }
            }
        },
        404: {
            "description": "Snapshot non trouvé ou expiré"
        }
    }
)
async def undo_normalization(
    type_name: str,
    snapshot_id: str,
    tenant_id: str = Depends(get_tenant_id),  # ✅ Phase 0 - JWT
    admin: dict = Depends(require_admin)  # ✅ Phase 0 - Admin only (undo)
):
    """
    Lance undo normalisation.

    Args:
        type_name: Nom type
        snapshot_id: ID snapshot
        tenant_id: Tenant ID

    Returns:
        Dict job info
    """
    from sqlalchemy import create_engine, text
    from sqlalchemy.orm import sessionmaker
    from datetime import datetime
    import os
    import json

    logger.info(f"↩️ POST /entity-types/{type_name}/undo-normalization/{snapshot_id}")

    # Récupérer snapshot depuis SQLite
    engine = create_engine('sqlite:////data/entity_types_registry.db')
    Session = sessionmaker(bind=engine)
    session = Session()

    try:
        result = session.execute(
            text("""
            SELECT snapshot_id, type_name, tenant_id, merge_groups_json, expires_at, restored
            FROM normalization_snapshots
            WHERE snapshot_id = :snapshot_id AND type_name = :type_name AND tenant_id = :tenant_id
            """),
            {"snapshot_id": snapshot_id, "type_name": type_name, "tenant_id": tenant_id}
        ).fetchone()

        if not result:
            raise HTTPException(
                status_code=404,
                detail=f"Snapshot '{snapshot_id}' not found"
            )

        snap_id, snap_type, snap_tenant, merge_groups_json, expires_at, restored = result

        # Vérifier expiration
        expires_dt = datetime.fromisoformat(expires_at)
        if datetime.utcnow() > expires_dt:
            raise HTTPException(
                status_code=410,
                detail=f"Snapshot expired (TTL 24h)"
            )

        # Vérifier si déjà restauré
        if restored:
            raise HTTPException(
                status_code=400,
                detail="Snapshot already restored"
            )

        merge_groups = json.loads(merge_groups_json)

    finally:
        session.close()

    # Enqueue job RQ undo
    redis_conn = Redis(
        host=os.getenv("REDIS_HOST", "redis"),
        port=int(os.getenv("REDIS_PORT", "6379")), password=os.getenv("REDIS_PASSWORD") or None,
        db=0  # Même DB que worker ingestion
    )
    queue = Queue("ingestion", connection=redis_conn)

    job = queue.enqueue(
        "knowbase.api.workers.normalization_worker.undo_normalization_task",
        snapshot_id=snapshot_id,
        type_name=type_name,
        merge_groups=merge_groups,
        tenant_id=tenant_id,
        job_timeout="30m"
    )

    logger.info(f"✅ Job undo enqueued: {job.id}")

    return {
        "job_id": job.id,
        "status": "queued",
        "status_url": f"/api/jobs/{job.id}/status",
        "snapshot_id": snapshot_id
    }


@router.post("/{source_type}/merge-into/{target_type}")
async def merge_entity_types(
    source_type: str,
    target_type: str,
    tenant_id: str = Depends(get_tenant_id),  # ✅ Phase 0 - JWT
    admin: dict = Depends(require_admin),  # ✅ Phase 0 - Admin only
    db: Session = Depends(get_db)
):
    """
    Merge TYPE_SOURCE dans TYPE_TARGET.

    Actions:
    1. Transférer toutes les entités de SOURCE vers TARGET
    2. Mettre à jour entity_type dans Neo4j
    3. Supprimer TYPE_SOURCE du registry
    4. Créer snapshot pour rollback

    Args:
        source_type: Type source (sera supprimé)
        target_type: Type cible (recevra les entités)
        tenant_id: Tenant ID
        admin: Admin authentifié
        db: Session DB

    Returns:
        Résultat du merge
    """
    from neo4j import GraphDatabase
    import os
    import uuid

    # Validation type_names (Phase 0 - Input Validation)
    try:
        source_type = validate_entity_type(source_type)
        target_type = validate_entity_type(target_type)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    logger.info(
        f"🔀 Merge types: {sanitize_for_log(source_type)} → {sanitize_for_log(target_type)}, "
        f"admin={admin.get('email')}"
    )

    # Vérifier que les deux types existent
    service = EntityTypeRegistryService(db)
    source_entity_type = service.get_type_by_name(source_type, tenant_id)
    target_entity_type = service.get_type_by_name(target_type, tenant_id)

    if not source_entity_type:
        raise HTTPException(status_code=404, detail=f"Source type '{source_type}' not found")

    if not target_entity_type:
        raise HTTPException(status_code=404, detail=f"Target type '{target_type}' not found")

    if source_type == target_type:
        raise HTTPException(status_code=400, detail="Source and target types cannot be the same")

    # Créer snapshot avant merge
    snapshot_id = str(uuid.uuid4())
    merge_info = {
        "source_type": source_type,
        "target_type": target_type,
        "source_entity_count": source_entity_type.entity_count
    }

    from sqlalchemy import create_engine, text as sql_text
    from sqlalchemy.orm import sessionmaker
    from datetime import timedelta

    engine = create_engine('sqlite:////data/entity_types_registry.db')
    Session = sessionmaker(bind=engine)
    session = Session()

    try:
        # Créer snapshot
        expires_at = datetime.utcnow() + timedelta(hours=24)
        session.execute(
            sql_text("""
            INSERT INTO normalization_snapshots
            (snapshot_id, type_name, tenant_id, merge_groups_json, expires_at)
            VALUES (:snapshot_id, :type_name, :tenant_id, :merge_info, :expires_at)
            """),
            {
                "snapshot_id": snapshot_id,
                "type_name": f"TYPE_MERGE_{source_type}_TO_{target_type}",
                "tenant_id": tenant_id,
                "merge_info": json.dumps(merge_info),
                "expires_at": expires_at
            }
        )
        session.commit()
    finally:
        session.close()

    # Transférer entités dans Neo4j
    neo4j_uri = os.getenv("NEO4J_URI", "bolt://neo4j:7687")
    neo4j_user = os.getenv("NEO4J_USER", "neo4j")
    neo4j_password = os.getenv("NEO4J_PASSWORD", "password")

    driver = GraphDatabase.driver(neo4j_uri, auth=(neo4j_user, neo4j_password))

    try:
        with driver.session() as neo_session:
            # Transférer toutes les entités
            query = """
            MATCH (e:Entity {entity_type: $source_type, tenant_id: $tenant_id})
            SET e.entity_type = $target_type,
                e.updated_at = datetime(),
                e.merged_from_type = $source_type
            RETURN count(e) AS transferred_count
            """

            result = neo_session.run(
                query,
                source_type=source_type,
                target_type=target_type,
                tenant_id=tenant_id
            )

            record = result.single()
            transferred_count = record["transferred_count"] if record else 0

        driver.close()

        logger.info(f"✅ {transferred_count} entités transférées de {source_type} → {target_type}")

        # Supprimer le type source du registry
        service.delete_type(source_entity_type.id)

        # Audit logging (Phase 0 - Audit Trail)
        log_audit(
            action="MERGE",
            user=admin,
            resource_type="entity_type",
            resource_id=f"{source_entity_type.id}→{target_entity_type.id}",
            tenant_id=tenant_id,
            details=f"Merged {source_type} into {target_type}, {transferred_count} entities transferred"
        )

        return {
            "success": True,
            "source_type": source_type,
            "target_type": target_type,
            "entities_transferred": transferred_count,
            "snapshot_id": snapshot_id,
            "message": f"{transferred_count} entités transférées de {source_type} vers {target_type}"
        }

    except Exception as e:
        driver.close()
        logger.error(f"❌ Erreur merge types: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{type_name}/snapshots")
async def list_snapshots(
    type_name: str,
    tenant_id: str = Depends(get_tenant_id),  # ✅ Phase 0 - JWT
    current_user: dict = Depends(get_current_user)  # ✅ Phase 0 - Auth
):
    """
    Liste les snapshots disponibles pour rollback.

    Args:
        type_name: Nom du type
        tenant_id: Tenant ID

    Returns:
        Liste des snapshots avec TTL
    """
    from sqlalchemy import create_engine, text
    from sqlalchemy.orm import sessionmaker

    engine = create_engine('sqlite:////data/entity_types_registry.db')
    Session = sessionmaker(bind=engine)
    session = Session()

    try:
        result = session.execute(
            text("""
            SELECT snapshot_id, type_name, created_at, expires_at, restored, merge_groups_json
            FROM normalization_snapshots
            WHERE type_name = :type_name AND tenant_id = :tenant_id
            ORDER BY created_at DESC
            """),
            {"type_name": type_name, "tenant_id": tenant_id}
        ).fetchall()

        snapshots = []
        for row in result:
            snap_id, snap_type, created_at, expires_at, restored, merge_groups_json = row

            # Parser dates
            created_dt = datetime.fromisoformat(created_at)
            expires_dt = datetime.fromisoformat(expires_at)
            now = datetime.utcnow()

            is_expired = now > expires_dt
            ttl_hours = (expires_dt - now).total_seconds() / 3600 if not is_expired else 0

            # Compter entités dans le snapshot
            import json
            entities_count = 0
            if merge_groups_json:
                try:
                    merge_groups = json.loads(merge_groups_json)
                    for group in merge_groups:
                        # Essayer plusieurs structures possibles
                        entities = group.get("entities", [])
                        if entities:
                            entities_count += len(entities)
                        else:
                            # Fallback sur entity_uuids si présent
                            entity_uuids = group.get("entity_uuids", [])
                            entities_count += len(entity_uuids)
                except Exception as e:
                    logger.warning(f"Erreur comptage entités snapshot {snap_id}: {e}")

            snapshots.append({
                "snapshot_id": snap_id,
                "type_name": snap_type,
                "created_at": created_at,
                "expires_at": expires_at,
                "is_expired": is_expired,
                "is_restored": bool(restored),
                "ttl_hours": round(ttl_hours, 1),
                "can_rollback": not is_expired and not restored,
                "entities_count": entities_count
            })

        return {"snapshots": snapshots}

    finally:
        session.close()


__all__ = ["router"]
