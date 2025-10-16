"""
API Admin pour gestion Ontologies (P0.2 Rollback).

Endpoints:
- POST /admin/ontology/deprecate: Déprécier entité et migrer vers nouvelle
- GET /admin/ontology/deprecated: Liste entités dépréciées
- GET /admin/ontology/pending: Liste entités en attente validation
"""
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel, Field
from typing import Optional, List
from datetime import datetime
import logging

from knowbase.config.settings import get_settings
from knowbase.ontology.neo4j_schema import (
    deprecate_ontology_entity,
    DeprecationReason,
    OntologyStatus
)
from neo4j import GraphDatabase

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/admin/ontology", tags=["admin", "ontology"])


# ============================================================================
# Pydantic Models
# ============================================================================

class DeprecateEntityRequest(BaseModel):
    """Request pour déprécier une entité ontologie."""
    old_entity_id: str = Field(..., description="ID entité à déprécier")
    new_entity_id: str = Field(..., description="ID nouvelle entité de remplacement")
    reason: str = Field(..., description="Raison deprecation (voir DeprecationReason enum)")
    comment: Optional[str] = Field(None, description="Commentaire optionnel admin")
    deprecated_by: str = Field("admin", description="User ID qui fait la deprecation")
    tenant_id: str = Field("default", description="Tenant ID")

    class Config:
        json_schema_extra = {
            "example": {
                "old_entity_id": "ORACLE_ERP_WRONG",
                "new_entity_id": "SAP_S4HANA_CLOUD",
                "reason": "incorrect_fusion",
                "comment": "Oracle et SAP fusionnés à tort, correction manuelle",
                "deprecated_by": "admin@example.com",
                "tenant_id": "default"
            }
        }


class DeprecateEntityResponse(BaseModel):
    """Response après deprecation."""
    success: bool
    old_entity_id: str
    new_entity_id: str
    reason: str
    migrated_count: Optional[int] = Field(None, description="Nombre CanonicalConcept migrés")
    message: str


class DeprecatedEntityItem(BaseModel):
    """Entité dépréciée avec metadata."""
    entity_id: str
    canonical_name: str
    entity_type: str
    deprecated_at: Optional[datetime]
    deprecated_by: Optional[str]
    new_entity_id: Optional[str]
    new_canonical_name: Optional[str]
    reason: Optional[str]
    comment: Optional[str]


class PendingEntityItem(BaseModel):
    """Entité en attente validation avec metadata."""
    entity_id: str
    canonical_name: str
    entity_type: str
    confidence: float
    created_at: Optional[datetime]
    created_by: Optional[str]
    requires_admin_validation: bool


# ============================================================================
# Dependency: Neo4j Driver
# ============================================================================

def get_neo4j_driver():
    """Get Neo4j driver instance."""
    settings = get_settings()
    driver = GraphDatabase.driver(
        settings.neo4j_uri,
        auth=(settings.neo4j_user, settings.neo4j_password)
    )
    try:
        yield driver
    finally:
        driver.close()


# ============================================================================
# Endpoints
# ============================================================================

@router.post("/deprecate", response_model=DeprecateEntityResponse)
async def deprecate_entity(
    request: DeprecateEntityRequest,
    driver = Depends(get_neo4j_driver)
):
    """
    Déprécier une entité ontologie et migrer vers nouvelle (P0.2 Rollback).

    Opérations atomiques:
    1. Marquer old_entity status=DEPRECATED
    2. Créer relation DEPRECATED_BY vers new_entity
    3. Migrer tous les CanonicalConcept qui pointaient vers old_entity

    **Exemple use case**:
    - Fusion incorrecte: Oracle + SAP fusionnés à tort → séparer
    - Nom canonique incorrect: "sap s4hana" → "SAP S/4HANA Cloud"
    - Doublon: "S4HANA" et "SAP S/4HANA" → merger
    """
    logger.info(
        f"[API:Rollback] Deprecation request: {request.old_entity_id} → {request.new_entity_id} "
        f"(reason={request.reason}, by={request.deprecated_by})"
    )

    # Validate reason
    try:
        DeprecationReason(request.reason)
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid reason '{request.reason}'. "
                   f"Valid values: {[r.value for r in DeprecationReason]}"
        )

    # Execute deprecation
    success = deprecate_ontology_entity(
        driver=driver,
        old_entity_id=request.old_entity_id,
        new_entity_id=request.new_entity_id,
        reason=request.reason,
        deprecated_by=request.deprecated_by,
        tenant_id=request.tenant_id,
        comment=request.comment
    )

    if not success:
        raise HTTPException(
            status_code=500,
            detail=f"Deprecation failed for entity {request.old_entity_id}"
        )

    # Count migrated CanonicalConcept (TODO: return from deprecate function)
    migrated_count = None  # TODO: get from deprecate_ontology_entity return

    return DeprecateEntityResponse(
        success=True,
        old_entity_id=request.old_entity_id,
        new_entity_id=request.new_entity_id,
        reason=request.reason,
        migrated_count=migrated_count,
        message=f"Entity {request.old_entity_id} successfully deprecated and migrated to {request.new_entity_id}"
    )


@router.get("/deprecated", response_model=List[DeprecatedEntityItem])
async def list_deprecated_entities(
    tenant_id: str = "default",
    limit: int = 100,
    driver = Depends(get_neo4j_driver)
):
    """
    Liste toutes les entités dépréciées avec metadata (P0.2 Rollback).

    Retourne:
    - Entité dépréciée (old)
    - Entité de remplacement (new)
    - Raison deprecation
    - Metadata (qui, quand, pourquoi)
    """
    logger.info(f"[API:Rollback] Listing deprecated entities (tenant={tenant_id}, limit={limit})")

    query = """
    MATCH (old:OntologyEntity {status: 'deprecated', tenant_id: $tenant_id})-[rel:DEPRECATED_BY]->(new:OntologyEntity)
    RETURN
        old.entity_id AS entity_id,
        old.canonical_name AS canonical_name,
        old.entity_type AS entity_type,
        old.deprecated_at AS deprecated_at,
        old.deprecated_by AS deprecated_by,
        new.entity_id AS new_entity_id,
        new.canonical_name AS new_canonical_name,
        rel.reason AS reason,
        rel.comment AS comment
    ORDER BY old.deprecated_at DESC
    LIMIT $limit
    """

    with driver.session() as session:
        result = session.run(query, {"tenant_id": tenant_id, "limit": limit})

        deprecated_entities = []
        for record in result:
            deprecated_entities.append(DeprecatedEntityItem(
                entity_id=record["entity_id"],
                canonical_name=record["canonical_name"],
                entity_type=record["entity_type"],
                deprecated_at=record["deprecated_at"],
                deprecated_by=record["deprecated_by"],
                new_entity_id=record["new_entity_id"],
                new_canonical_name=record["new_canonical_name"],
                reason=record["reason"],
                comment=record["comment"]
            ))

    logger.info(f"[API:Rollback] Found {len(deprecated_entities)} deprecated entities")

    return deprecated_entities


@router.get("/pending", response_model=List[PendingEntityItem])
async def list_pending_entities(
    tenant_id: str = "default",
    limit: int = 100,
    driver = Depends(get_neo4j_driver)
):
    """
    Liste toutes les entités en attente validation admin (P0.1 Sandbox).

    Retourne:
    - Entités avec status='auto_learned_pending'
    - Confidence < 0.95
    - Requires admin validation
    """
    logger.info(f"[API:Sandbox] Listing pending entities (tenant={tenant_id}, limit={limit})")

    query = """
    MATCH (ont:OntologyEntity {
        status: 'auto_learned_pending',
        tenant_id: $tenant_id
    })
    RETURN
        ont.entity_id AS entity_id,
        ont.canonical_name AS canonical_name,
        ont.entity_type AS entity_type,
        ont.confidence AS confidence,
        ont.created_at AS created_at,
        ont.created_by AS created_by,
        ont.requires_admin_validation AS requires_admin_validation
    ORDER BY ont.created_at DESC
    LIMIT $limit
    """

    with driver.session() as session:
        result = session.run(query, {"tenant_id": tenant_id, "limit": limit})

        pending_entities = []
        for record in result:
            pending_entities.append(PendingEntityItem(
                entity_id=record["entity_id"],
                canonical_name=record["canonical_name"],
                entity_type=record["entity_type"],
                confidence=record["confidence"],
                created_at=record["created_at"],
                created_by=record["created_by"],
                requires_admin_validation=record["requires_admin_validation"]
            ))

    logger.info(f"[API:Sandbox] Found {len(pending_entities)} pending entities")

    return pending_entities
