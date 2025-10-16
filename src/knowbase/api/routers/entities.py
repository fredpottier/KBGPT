"""
Router API pour gestion des entités Knowledge Graph.

Phase 1 - Gestion validation entités dynamiques
Phase 3 - Admin actions (approve, merge, delete cascade)
"""
from typing import List, Optional
from pathlib import Path
import yaml

from fastapi import APIRouter, HTTPException, Query, Depends, Body, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from knowbase.api.schemas.knowledge_graph import EntityResponse
from knowbase.api.services.knowledge_graph_service import KnowledgeGraphService
from knowbase.api.dependencies import require_admin, require_editor, get_tenant_id, get_current_user
from knowbase.api.validators import validate_entity_type, validate_entity_name
from knowbase.api.utils.audit_helpers import log_audit
from knowbase.common.log_sanitizer import sanitize_for_log
from knowbase.db import get_db
from knowbase.common.logging import setup_logging
from knowbase.config.settings import get_settings

settings = get_settings()
logger = setup_logging(settings.logs_dir, "entities_router.log")

router = APIRouter(prefix="/entities", tags=["entities"])


class EntitiesListResponse(BaseModel):
    """Réponse liste entités avec filtres."""

    entities: List[EntityResponse] = Field(
        ...,
        description="Liste entités"
    )
    total: int = Field(
        ...,
        description="Nombre total entités"
    )
    entity_type_filter: Optional[str] = Field(
        default=None,
        description="Filtre entity_type appliqué (si any)"
    )
    status_filter: Optional[str] = Field(
        default=None,
        description="Filtre status appliqué (si any)"
    )


class PendingEntitiesResponse(BaseModel):
    """Réponse liste entités pending."""

    entities: List[EntityResponse] = Field(
        ...,
        description="Liste entités en attente validation"
    )
    total: int = Field(
        ...,
        description="Nombre total entités pending"
    )
    entity_type_filter: Optional[str] = Field(
        default=None,
        description="Filtre entity_type appliqué (si any)"
    )


@router.get(
    "",
    response_model=EntitiesListResponse,
    summary="Liste entités avec filtres",
    description="""
    Liste les entités du Knowledge Graph avec filtres optionnels.

    **Filtres disponibles**:
    - `entity_type` : Filtrer par type (SOLUTION, COMPONENT, etc.)
    - `status` : Filtrer par statut (pending, validated)
    - `tenant_id` : Isolation multi-tenant
    - `limit` / `offset` : Pagination

    **Use Case**: Page drill-down types dynamiques (/admin/dynamic-types/{typeName})
    """,
    responses={
        200: {
            "description": "Liste entités avec filtres",
            "content": {
                "application/json": {
                    "example": {
                        "entities": [
                            {
                                "uuid": "123e4567-e89b-12d3-a456-426614174000",
                                "name": "SAP S/4HANA",
                                "entity_type": "SOLUTION",
                                "status": "pending",
                                "description": "ERP solution",
                                "confidence": 0.95
                            }
                        ],
                        "total": 22,
                        "entity_type_filter": "SOLUTION",
                        "status_filter": None
                    }
                }
            }
        }
    }
)
async def list_entities(
    tenant_id: str = Depends(get_tenant_id),
    current_user: dict = Depends(get_current_user),
    entity_type: Optional[str] = Query(
        default=None,
        description="Filtrer par entity_type (ex: SOLUTION, COMPONENT)",
        example="SOLUTION"
    ),
    status: Optional[str] = Query(
        default=None,
        description="Filtrer par status (pending | validated)",
        example="pending"
    ),
    limit: int = Query(
        default=100,
        ge=1,
        le=1000,
        description="Limite résultats (max 1000)",
        example=100
    ),
    offset: int = Query(
        default=0,
        ge=0,
        description="Offset pagination",
        example=0
    )
):
    """
    Liste entités avec filtres entity_type et status.

    Args:
        entity_type: Type d'entité (optionnel)
        status: Statut entité (optionnel)
        tenant_id: Tenant ID
        limit: Limite résultats
        offset: Offset pagination

    Returns:
        Liste entités filtrées
    """
    # Validation entity_type si fourni (Phase 0 - Input Validation)
    if entity_type:
        try:
            entity_type = validate_entity_type(entity_type)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))

    logger.info(
        f"📋 GET /entities - entity_type={sanitize_for_log(entity_type)}, status={status}, "
        f"tenant={tenant_id}, limit={limit}, offset={offset}, user={current_user.get('email')}"
    )

    kg_service = KnowledgeGraphService(tenant_id=tenant_id)

    try:
        # Query Neo4j avec filtres
        query = """
        MATCH (e:Entity {tenant_id: $tenant_id})
        """

        params = {"tenant_id": tenant_id, "limit": limit, "offset": offset}

        # Ajouter filtres conditionnels
        if entity_type:
            query += " WHERE e.entity_type = $entity_type"
            params["entity_type"] = entity_type

        if status:
            if entity_type:
                query += " AND e.status = $status"
            else:
                query += " WHERE e.status = $status"
            params["status"] = status

        query += """
        RETURN e
        ORDER BY e.created_at DESC
        SKIP $offset
        LIMIT $limit
        """

        entities = []
        total = 0

        with kg_service.driver.session() as session:
            # Compter total (enlever ORDER BY, SKIP, LIMIT)
            count_query = query.replace("RETURN e\n        ORDER BY e.created_at DESC\n        SKIP $offset\n        LIMIT $limit", "RETURN count(e) AS total")
            count_result = session.run(count_query, params)
            count_record = count_result.single()
            total = count_record["total"] if count_record else 0

            # Récupérer entités
            result = session.run(query, params)

            for record in result:
                node = record["e"]

                # Parse attributes si c'est une string JSON
                attributes = node.get("attributes", {})
                if isinstance(attributes, str):
                    import json
                    try:
                        attributes = json.loads(attributes) if attributes else {}
                    except:
                        attributes = {}

                entities.append(EntityResponse(
                    uuid=node["uuid"],
                    name=node["name"],
                    entity_type=node["entity_type"],
                    canonical_name=node.get("canonical_name"),  # Nom canonique après normalisation
                    description=node.get("description"),
                    confidence=node.get("confidence", 0.0),
                    attributes=attributes,
                    source_slide_number=node.get("source_slide_number"),
                    source_document=node.get("source_document"),
                    source_chunk_id=node.get("source_chunk_id"),
                    tenant_id=node["tenant_id"],
                    status=node.get("status", "pending"),
                    is_cataloged=node.get("is_cataloged", False),
                    created_at=node["created_at"].to_native(),
                    updated_at=node.get("updated_at").to_native() if node.get("updated_at") else None
                ))

        logger.info(
            f"✅ Trouvé {len(entities)} entités (total={total}, "
            f"type={entity_type or 'all'}, status={status or 'all'})"
        )

        kg_service.close()

        return EntitiesListResponse(
            entities=entities,
            total=total,
            entity_type_filter=entity_type,
            status_filter=status
        )

    except Exception as e:
        logger.error(f"❌ Erreur list entities: {e}", exc_info=True)
        kg_service.close()
        raise HTTPException(
            status_code=500,
            detail=f"Failed to list entities: {str(e)}"
        )


@router.get(
    "/pending",
    response_model=PendingEntitiesResponse,
    summary="Liste entités non cataloguées (pending)",
    description="""
    Retourne toutes les entités avec status='pending' (non cataloguées dans ontologie YAML).

    **Workflow Auto-Classification**:
    - Import document → LLM extrait entités → EntityNormalizer check ontologie
    - Si entité trouvée dans YAML → status='validated', is_cataloged=true
    - Si entité NON trouvée → status='pending', is_cataloged=false
    - Admin review via cette API → Approve/Merge/Delete

    **Use Cases**:
    - UI Admin: Page /admin/entities-pending affiche cette liste
    - Curation: Identifier nouvelles entités métier découvertes
    - Quality: Détecter entités mal extraites (typos, doublons)

    **Filtrage**:
    - `entity_type` : Focus sur un type spécifique (ex: SOLUTION, COMPONENT)
    - `tenant_id` : Isolation multi-tenant stricte
    - Pagination : limit/offset

    **Performance**: < 100ms (index Neo4j sur tenant_id + status)
    """,
    responses={
        200: {
            "description": "Liste entités pending",
            "content": {
                "application/json": {
                    "example": {
                        "entities": [
                            {
                                "uuid": "ent-123",
                                "name": "SAP Analytics Cloud Advanced",
                                "entity_type": "SOLUTION",
                                "description": "Advanced analytics platform",
                                "status": "pending",
                                "is_cataloged": False,
                                "confidence": 0.87,
                                "source_document": "SAP_Portfolio_2025.pptx",
                                "created_at": "2025-10-06T10:15:00Z"
                            }
                        ],
                        "total": 1,
                        "entity_type_filter": None,
                        "tenant_id": "default"
                    }
                }
            }
        },
        422: {
            "description": "Paramètres invalides (limit/offset négatifs)",
            "content": {
                "application/json": {
                    "example": {
                        "detail": [
                            {
                                "loc": ["query", "limit"],
                                "msg": "ensure this value is greater than or equal to 1",
                                "type": "value_error.number.not_ge"
                            }
                        ]
                    }
                }
            }
        }
    }
)
async def list_pending_entities(
    tenant_id: str = Depends(get_tenant_id),
    current_user: dict = Depends(get_current_user),
    entity_type: Optional[str] = Query(
        default=None,
        description="Filtrer par type d'entité (ex: INFRASTRUCTURE)",
        example="SOLUTION"
    ),
    limit: int = Query(
        default=100,
        ge=1,
        le=1000,
        description="Nombre max entités retournées",
        example=100
    ),
    offset: int = Query(
        default=0,
        ge=0,
        description="Offset pagination",
        example=0
    )
):
    """
    Liste toutes les entités avec status=pending (non cataloguées).

    Retourne uniquement les entités qui n'ont PAS été trouvées dans les catalogues
    d'ontologie YAML. Ces entités nécessitent validation manuelle admin.

    Args:
        entity_type: Filtrer par type (optionnel)
        tenant_id: ID tenant
        limit: Limite résultats (défaut 100, max 1000)
        offset: Offset pagination (défaut 0)

    Returns:
        Liste entités pending avec total count
    """
    # Validation entity_type si fourni (Phase 0 - Input Validation)
    if entity_type:
        try:
            entity_type = validate_entity_type(entity_type)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))

    logger.info(
        f"📋 GET /entities/pending - entity_type={sanitize_for_log(entity_type)}, tenant={tenant_id}, "
        f"limit={limit}, offset={offset}, user={current_user.get('email')}"
    )

    kg_service = KnowledgeGraphService(tenant_id=tenant_id)

    try:
        # Construire requête Cypher avec filtres
        query = """
        MATCH (e:Entity)
        WHERE e.tenant_id = $tenant_id
          AND e.status = 'pending'
        """

        params = {
            "tenant_id": tenant_id,
            "limit": limit,
            "offset": offset
        }

        # Filtre optionnel entity_type
        if entity_type:
            query += " AND e.entity_type = $entity_type"
            params["entity_type"] = entity_type

        # Order by created_at desc (plus récents en premier)
        query += """
        RETURN e
        ORDER BY e.created_at DESC
        SKIP $offset
        LIMIT $limit
        """

        with kg_service.driver.session() as session:
            result = session.run(query, **params)
            records = result.data()

        # Convertir Neo4j records → EntityResponse
        import json
        entities = []
        for record in records:
            node = record["e"]
            attributes_dict = json.loads(node.get("attributes", "{}"))

            entity = EntityResponse(
                uuid=node["uuid"],
                name=node["name"],
                entity_type=node["entity_type"],
                description=node["description"],
                confidence=node["confidence"],
                attributes=attributes_dict,
                source_slide_number=node.get("source_slide_number"),
                source_document=node.get("source_document"),
                source_chunk_id=node.get("source_chunk_id"),
                tenant_id=node["tenant_id"],
                status=node["status"],
                is_cataloged=node.get("is_cataloged", False),
                created_at=node["created_at"].to_native(),
                updated_at=node.get("updated_at").to_native() if node.get("updated_at") else None
            )
            entities.append(entity)

        # Count total (sans limit/offset)
        count_query = """
        MATCH (e:Entity)
        WHERE e.tenant_id = $tenant_id
          AND e.status = 'pending'
        """
        count_params = {"tenant_id": tenant_id}

        if entity_type:
            count_query += " AND e.entity_type = $entity_type"
            count_params["entity_type"] = entity_type.upper()

        count_query += " RETURN count(e) as total"

        with kg_service.driver.session() as session:
            count_result = session.run(count_query, **count_params)
            total = count_result.single()["total"]

        logger.info(
            f"✅ Trouvé {len(entities)} entités pending (total={total}, "
            f"entity_type={entity_type or 'all'})"
        )

        return PendingEntitiesResponse(
            entities=entities,
            total=total,
            entity_type_filter=entity_type
        )

    except Exception as e:
        logger.error(f"❌ Erreur récupération entités pending: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to fetch pending entities: {str(e)}"
        )
    finally:
        kg_service.close()


@router.get("/types/discovered", response_model=List[dict])
async def list_discovered_entity_types(
    tenant_id: str = Query(
        default="default",
        description="Tenant ID"
    )
):
    """
    Liste tous les entity_types découverts dans le système.

    Retourne la liste des types avec comptage entités (pending vs validated).

    Returns:
        Liste dicts: [{type_name, total_entities, pending_count, validated_count}]
    """
    logger.info(f"📋 GET /entities/types/discovered - tenant={tenant_id}")

    kg_service = KnowledgeGraphService(tenant_id=tenant_id)

    try:
        query = """
        MATCH (e:Entity {tenant_id: $tenant_id})
        WITH e.entity_type AS type_name,
             count(e) AS total_entities,
             sum(CASE WHEN e.status = 'pending' THEN 1 ELSE 0 END) AS pending_count,
             sum(CASE WHEN e.status = 'validated' THEN 1 ELSE 0 END) AS validated_count
        RETURN type_name, total_entities, pending_count, validated_count
        ORDER BY total_entities DESC
        """

        with kg_service.driver.session() as session:
            result = session.run(query, tenant_id=tenant_id)
            records = result.data()

        logger.info(f"✅ Trouvé {len(records)} types d'entités découverts")

        return records

    except Exception as e:
        logger.error(f"❌ Erreur récupération types découverts: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to fetch discovered types: {str(e)}"
        )
    finally:
        kg_service.close()


# === PHASE 3: ADMIN ACTIONS ===


class ApproveEntityRequest(BaseModel):
    """Requête approbation entité."""

    add_to_ontology: bool = Field(
        default=False,
        description="Ajouter automatiquement à l'ontologie YAML correspondante"
    )
    ontology_description: Optional[str] = Field(
        default=None,
        description="Description pour ontologie (si add_to_ontology=True)"
    )


class MergeEntitiesRequest(BaseModel):
    """Requête fusion entités."""

    target_uuid: str = Field(
        ...,
        description="UUID entité cible (celle qui sera conservée)"
    )
    canonical_name: Optional[str] = Field(
        default=None,
        description="Nom canonique final (optionnel, sinon garde nom cible)"
    )


@router.post(
    "/{uuid}/approve",
    response_model=EntityResponse,
    summary="Approuver entité pending",
    description="""
    Approuve une entité pending (transition pending → validated) + optionnel enrichissement ontologie YAML.

    **Workflow Complet**:
    1. Vérification existence entité (status='pending')
    2. UPDATE Neo4j : status='validated', validated_by, validated_at
    3. **Optionnel** (si add_to_ontology=true):
       - Détermine fichier YAML selon entity_type (ex: SOLUTION → solutions.yaml)
       - Ajoute entité avec name, aliases, description
       - **Impact futur** : Entités similaires → Automatiquement is_cataloged=true

    **Use Cases**:
    - Nouvelle entité métier découverte → Approuver pour futures utilisations
    - Enrichir ontologie automatiquement sans édition manuelle YAML
    - Traçabilité : Qui a validé quoi et quand

    **Security**:
    - Requiert header `X-Admin-Key` (auth simplifiée dev, JWT prévu prod)
    - Requiert header `X-Tenant-ID` (isolation multi-tenant)

    **Performance**: < 50ms (Neo4j update + optionnel YAML write)
    """,
    responses={
        200: {
            "description": "Entité approuvée avec succès",
            "content": {
                "application/json": {
                    "example": {
                        "uuid": "ent-456",
                        "name": "SAP Analytics Cloud Advanced",
                        "entity_type": "SOLUTION",
                        "status": "validated",
                        "is_cataloged": True,
                        "validated_by": "admin@example.com",
                        "validated_at": "2025-10-06T16:00:00Z",
                        "tenant_id": "default"
                    }
                }
            }
        },
        400: {
            "description": "Entité déjà validated",
            "content": {
                "application/json": {
                    "example": {
                        "detail": "Entity already validated (current status: validated)"
                    }
                }
            }
        },
        401: {
            "description": "X-Admin-Key manquant",
            "content": {
                "application/json": {
                    "example": {"detail": "X-Admin-Key header required"}
                }
            }
        },
        403: {
            "description": "X-Admin-Key invalide",
            "content": {
                "application/json": {
                    "example": {"detail": "Admin access required"}
                }
            }
        },
        404: {
            "description": "Entité non trouvée",
            "content": {
                "application/json": {
                    "example": {"detail": "Entity with uuid 'ent-unknown' not found"}
                }
            }
        }
    }
)
async def approve_entity(
    uuid: str,
    request: ApproveEntityRequest,
    admin: dict = Depends(require_admin),
    tenant_id: str = Depends(get_tenant_id)
):
    """
    Approuve une entité pending → validated.

    **Phase 3 - Admin Action**

    Actions:
    1. Change status: pending → validated
    2. Optionnel: Ajoute entité à l'ontologie YAML correspondante

    Args:
        uuid: UUID entité
        request: Options approbation
        admin: Admin user (authenticated)
        tenant_id: Tenant ID (from header)

    Returns:
        EntityResponse: Entité approuvée

    Raises:
        404: Entité non trouvée
        400: Entité déjà validated
    """
    logger.info(
        f"✅ POST /entities/{uuid}/approve - admin={admin['email']}, "
        f"add_to_ontology={request.add_to_ontology}"
    )

    kg_service = KnowledgeGraphService(tenant_id=tenant_id)

    try:
        # Récupérer entité
        query_get = """
        MATCH (e:Entity {uuid: $uuid, tenant_id: $tenant_id})
        RETURN e
        """

        with kg_service.driver.session() as session:
            result = session.run(query_get, uuid=uuid, tenant_id=tenant_id)
            record = result.single()

            if not record:
                raise HTTPException(
                    status_code=404,
                    detail=f"Entity with uuid '{uuid}' not found"
                )

            node = record["e"]

            # Vérifier status actuel
            current_status = node.get("status", "pending")
            if current_status == "validated":
                raise HTTPException(
                    status_code=400,
                    detail="Entity already validated"
                )

            # Approuver: changer status
            query_approve = """
            MATCH (e:Entity {uuid: $uuid, tenant_id: $tenant_id})
            SET e.status = 'validated',
                e.validated_by = $admin_email,
                e.validated_at = datetime()
            RETURN e
            """

            result_approve = session.run(
                query_approve,
                uuid=uuid,
                tenant_id=tenant_id,
                admin_email=admin["email"]
            )
            updated_node = result_approve.single()["e"]

            # Optionnel: Ajouter à ontologie YAML
            if request.add_to_ontology:
                try:
                    _add_entity_to_ontology(
                        entity_type=node["entity_type"],
                        entity_name=node["name"],
                        description=request.ontology_description
                    )
                    logger.info(
                        f"📝 Entité ajoutée à ontologie: {node['entity_type']}/{node['name']}"
                    )
                except Exception as e:
                    logger.warning(f"⚠️ Erreur ajout ontologie: {e}")
                    # Continue quand même (entité approuvée)

            logger.info(f"✅ Entité approuvée: {uuid}")

            # Audit logging (Phase 0 - Audit Trail)
            log_audit(
                action="APPROVE",
                user=admin,
                resource_type="entity",
                resource_id=uuid,
                tenant_id=tenant_id,
                details=f"Entity '{updated_node['name']}' approved, type={updated_node['entity_type']}"
            )

            # Convertir en EntityResponse
            return EntityResponse(
                uuid=updated_node["uuid"],
                name=updated_node["name"],
                entity_type=updated_node["entity_type"],
                description=updated_node.get("description"),
                confidence=updated_node.get("confidence", 1.0),
                attributes=updated_node.get("attributes", {}),
                tenant_id=updated_node["tenant_id"],
                status=updated_node.get("status", "pending"),
                is_cataloged=updated_node.get("is_cataloged", False),
                created_at=updated_node["created_at"].to_native(),
                updated_at=updated_node["updated_at"].to_native() if updated_node.get("updated_at") else None
            )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Erreur approbation entité: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to approve entity: {str(e)}"
        )
    finally:
        kg_service.close()


@router.post("/{source_uuid}/merge")
async def merge_entities(
    source_uuid: str,
    merge_entities_request: MergeEntitiesRequest = Body(..., embed=False),
    admin: dict = Depends(require_admin),
    tenant_id: str = Depends(get_tenant_id)
):
    """
    Fusionne deux entités (source → target).

    **Phase 3 - Admin Action**

    Actions:
    1. Transfère toutes les relations de source vers target
    2. Supprime entité source
    3. Optionnel: Renomme entité cible

    Args:
        source_uuid: UUID entité source (sera supprimée)
        merge_request: UUID target + options
        admin: Admin user (authenticated)
        tenant_id: Tenant ID (from header)

    Returns:
        dict: Résultat fusion avec stats

    Raises:
        404: Une des entités non trouvée
        400: Tentative fusion même entité
    """
    logger.info(
        f"🔀 POST /entities/{source_uuid}/merge → {merge_entities_request.target_uuid} "
        f"- admin={admin['email']}"
    )

    if source_uuid == merge_entities_request.target_uuid:
        raise HTTPException(
            status_code=400,
            detail="Cannot merge entity with itself"
        )

    kg_service = KnowledgeGraphService(tenant_id=tenant_id)

    try:
        with kg_service.driver.session() as session:
            # Vérifier existence des deux entités
            query_check = """
            MATCH (source:Entity {uuid: $source_uuid, tenant_id: $tenant_id})
            MATCH (target:Entity {uuid: $target_uuid, tenant_id: $tenant_id})
            RETURN source, target
            """

            result_check = session.run(
                query_check,
                source_uuid=source_uuid,
                target_uuid=merge_entities_request.target_uuid,
                tenant_id=tenant_id
            )
            record_check = result_check.single()

            if not record_check:
                raise HTTPException(
                    status_code=404,
                    detail="Source or target entity not found"
                )

            # Transférer relations sortantes: (source)-[r]->(other) → (target)-[r]->(other)
            query_transfer_out = """
            MATCH (source:Entity {uuid: $source_uuid, tenant_id: $tenant_id})-[r]->(other)
            MATCH (target:Entity {uuid: $target_uuid, tenant_id: $tenant_id})
            WHERE NOT (target)-[]->(other)
            CREATE (target)-[r2:RELATION]->(other)
            SET r2 = properties(r)
            DELETE r
            RETURN count(r) as transferred_out
            """

            result_out = session.run(
                query_transfer_out,
                source_uuid=source_uuid,
                target_uuid=merge_entities_request.target_uuid,
                tenant_id=tenant_id
            )
            transferred_out = result_out.single()["transferred_out"]

            # Transférer relations entrantes: (other)-[r]->(source) → (other)-[r]->(target)
            query_transfer_in = """
            MATCH (other)-[r]->(source:Entity {uuid: $source_uuid, tenant_id: $tenant_id})
            MATCH (target:Entity {uuid: $target_uuid, tenant_id: $tenant_id})
            WHERE NOT (other)-[]->(target)
            CREATE (other)-[r2:RELATION]->(target)
            SET r2 = properties(r)
            DELETE r
            RETURN count(r) as transferred_in
            """

            result_in = session.run(
                query_transfer_in,
                source_uuid=source_uuid,
                target_uuid=merge_entities_request.target_uuid,
                tenant_id=tenant_id
            )
            transferred_in = result_in.single()["transferred_in"]

            # Optionnel: Renommer entité cible
            if merge_entities_request.canonical_name:
                query_rename = """
                MATCH (target:Entity {uuid: $target_uuid, tenant_id: $tenant_id})
                SET target.name = $canonical_name
                """
                session.run(
                    query_rename,
                    target_uuid=merge_entities_request.target_uuid,
                    tenant_id=tenant_id,
                    canonical_name=merge_entities_request.canonical_name
                )

            # Supprimer entité source
            query_delete_source = """
            MATCH (source:Entity {uuid: $source_uuid, tenant_id: $tenant_id})
            DELETE source
            """
            session.run(query_delete_source, source_uuid=source_uuid, tenant_id=tenant_id)

            logger.info(
                f"✅ Fusion réussie: {source_uuid} → {merge_entities_request.target_uuid} "
                f"(relations transférées: {transferred_out + transferred_in})"
            )

            return {
                "status": "merged",
                "source_uuid": source_uuid,
                "target_uuid": merge_entities_request.target_uuid,
                "relations_transferred": transferred_out + transferred_in,
                "canonical_name": merge_entities_request.canonical_name
            }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Erreur fusion entités: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to merge entities: {str(e)}"
        )
    finally:
        kg_service.close()


@router.delete("/{uuid}")
async def delete_entity_cascade(
    uuid: str,
    cascade: bool = Query(
        default=True,
        description="Supprimer aussi toutes les relations (cascade delete)"
    ),
    admin: dict = Depends(require_admin),
    tenant_id: str = Depends(get_tenant_id)
):
    """
    Supprime une entité avec cascade delete optionnel.

    **Phase 3 - Admin Action**

    Actions:
    1. Si cascade=True: Supprime toutes les relations liées
    2. Supprime l'entité
    3. Audit trail (logged)

    Args:
        uuid: UUID entité
        cascade: Supprimer relations (défaut True)
        admin: Admin user (authenticated)
        tenant_id: Tenant ID (from header)

    Returns:
        dict: Résultat suppression avec stats

    Raises:
        404: Entité non trouvée
    """
    logger.info(
        f"🗑️ DELETE /entities/{uuid} - cascade={cascade}, admin={admin['email']}"
    )

    kg_service = KnowledgeGraphService(tenant_id=tenant_id)

    try:
        with kg_service.driver.session() as session:
            # Vérifier existence
            query_check = """
            MATCH (e:Entity {uuid: $uuid, tenant_id: $tenant_id})
            RETURN e
            """

            result_check = session.run(query_check, uuid=uuid, tenant_id=tenant_id)
            if not result_check.single():
                raise HTTPException(
                    status_code=404,
                    detail=f"Entity with uuid '{uuid}' not found"
                )

            # Compter relations avant suppression
            query_count_relations = """
            MATCH (e:Entity {uuid: $uuid, tenant_id: $tenant_id})
            OPTIONAL MATCH (e)-[r]-()
            RETURN count(r) as relation_count
            """

            result_count = session.run(query_count_relations, uuid=uuid, tenant_id=tenant_id)
            relation_count = result_count.single()["relation_count"]

            # Supprimer
            if cascade:
                query_delete = """
                MATCH (e:Entity {uuid: $uuid, tenant_id: $tenant_id})
                DETACH DELETE e
                """
            else:
                query_delete = """
                MATCH (e:Entity {uuid: $uuid, tenant_id: $tenant_id})
                DELETE e
                """

            session.run(query_delete, uuid=uuid, tenant_id=tenant_id)

            logger.info(
                f"✅ Entité supprimée: {uuid} (cascade={cascade}, "
                f"relations supprimées={relation_count if cascade else 0})"
            )

            # Audit logging (Phase 0 - Audit Trail)
            log_audit(
                action="DELETE",
                user=admin,
                resource_type="entity",
                resource_id=uuid,
                tenant_id=tenant_id,
                details=f"Entity deleted (cascade={cascade}, relations={relation_count})"
            )

            return {
                "status": "deleted",
                "uuid": uuid,
                "cascade": cascade,
                "relations_deleted": relation_count if cascade else 0,
                "deleted_by": admin["email"]
            }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Erreur suppression entité: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to delete entity: {str(e)}"
        )
    finally:
        kg_service.close()


def _add_entity_to_ontology(
    entity_type: str,
    entity_name: str,
    description: Optional[str] = None
) -> None:
    """
    Ajoute une entité à l'ontologie YAML correspondante.

    **Helper Phase 3**

    Trouve le fichier ontologie correspondant au type et ajoute l'entité.

    Args:
        entity_type: Type entité (ex: SOLUTION, COMPONENT)
        entity_name: Nom entité
        description: Description (optionnel)

    Raises:
        FileNotFoundError: Fichier ontologie non trouvé
        ValueError: Format ontologie invalide
    """
    # Mapper type → fichier ontologie
    type_to_file = {
        "SOLUTION": "solutions.yaml",
        "COMPONENT": "components.yaml",
        "TECHNOLOGY": "technologies.yaml",
        "CONCEPT": "concepts.yaml",
        "ORGANIZATION": "organizations.yaml",
        "PERSON": "persons.yaml"
    }

    ontology_file = type_to_file.get(entity_type.upper())
    if not ontology_file:
        raise ValueError(f"No ontology file mapped for type: {entity_type}")

    ontology_path = settings.ontologies_dir / ontology_file

    if not ontology_path.exists():
        raise FileNotFoundError(f"Ontology file not found: {ontology_path}")

    # Charger ontologie
    with open(ontology_path, "r", encoding="utf-8") as f:
        ontology = yaml.safe_load(f) or {}

    # Ajouter entité
    entity_id = entity_name.upper().replace(" ", "_").replace("/", "_")

    if "entities" not in ontology:
        ontology["entities"] = {}

    ontology["entities"][entity_id] = {
        "name": entity_name,
        "aliases": [entity_name],
        "description": description or f"Entity added from admin approval",
        "category": "user-approved"
    }

    # Sauvegarder
    with open(ontology_path, "w", encoding="utf-8") as f:
        yaml.dump(ontology, f, allow_unicode=True, sort_keys=False)

    logger.info(f"📝 Entité ajoutée à {ontology_file}: {entity_id}")


class ChangeEntityTypeRequest(BaseModel):
    """Requête changement type entité."""

    new_entity_type: str = Field(
        ...,
        description="Nouveau type d'entité (ex: SOLUTION, COMPONENT, etc.)"
    )


@router.patch("/{entity_uuid}/change-type")
async def change_entity_type(
    entity_uuid: str,
    new_entity_type: str = Body(..., embed=True),
    admin: dict = Depends(require_admin),
    tenant_id: str = Depends(get_tenant_id),
    db: Session = Depends(get_db)
):
    """
    Change le type d'une entité.

    Utile quand le LLM a mal classifié une entité lors de l'extraction.

    Args:
        entity_uuid: UUID de l'entité
        request: Nouveau type d'entité
        admin: Admin authentifié
        tenant_id: Tenant ID

    Returns:
        Entité mise à jour
    """
    logger.info(f"🔄 Changement type entité {entity_uuid} → {new_entity_type}")

    from neo4j import GraphDatabase
    import os
    from knowbase.api.services.entity_type_registry_service import EntityTypeRegistryService

    neo4j_uri = os.getenv("NEO4J_URI", "bolt://neo4j:7687")
    neo4j_user = os.getenv("NEO4J_USER", "neo4j")
    neo4j_password = os.getenv("NEO4J_PASSWORD", "password")

    driver = GraphDatabase.driver(neo4j_uri, auth=(neo4j_user, neo4j_password))

    try:
        with driver.session() as session:
            # Récupérer entité actuelle et changer son type
            query = """
            MATCH (e:Entity {uuid: $uuid, tenant_id: $tenant_id})
            WITH e, e.entity_type AS old_type
            SET e.entity_type = $new_type,
                e.updated_at = datetime()
            RETURN e, old_type
            """

            result = session.run(
                query,
                uuid=entity_uuid,
                tenant_id=tenant_id,
                new_type=new_entity_type.upper()
            )

            record = result.single()
            if not record:
                driver.close()
                raise HTTPException(status_code=404, detail="Entity not found")

            node = record["e"]
            old_type = record["old_type"]

        driver.close()

        logger.info(
            f"✅ Type changé: {entity_uuid} de {old_type} → {new_entity_type}"
        )

        # Enregistrer le nouveau type dans le registry s'il n'existe pas
        # Les types créés manuellement sont automatiquement approuvés
        registry_service = EntityTypeRegistryService(db)
        entity_type_record = registry_service.get_or_create_type(
            type_name=new_entity_type.upper(),
            tenant_id=tenant_id,
            discovered_by="admin"  # Type créé manuellement par admin
        )

        # Si le type a été créé maintenant, l'approuver automatiquement
        # (les types créés manuellement par admin sont considérés valides)
        if entity_type_record.status == "pending" and entity_type_record.discovered_by == "admin":
            registry_service.approve_type(
                type_name=new_entity_type.upper(),
                admin_email=admin.get("email", "admin@example.com"),
                tenant_id=tenant_id
            )
            logger.info(f"✅ Type {new_entity_type} auto-approuvé (créé manuellement)")

        # Mettre à jour les compteurs pour les deux types (ancien et nouveau)
        # On recalcule les compteurs depuis Neo4j
        driver_counts = GraphDatabase.driver(neo4j_uri, auth=(neo4j_user, neo4j_password))

        for type_to_update in [old_type, new_entity_type.upper()]:
            with driver_counts.session() as session:
                result = session.run("""
                    MATCH (e:Entity {entity_type: $type, tenant_id: $tenant_id})
                    RETURN count(e) as total,
                           sum(CASE WHEN e.status = 'pending' THEN 1 ELSE 0 END) as pending
                """, type=type_to_update, tenant_id=tenant_id)

                record = result.single()
                if record:
                    registry_service.update_entity_counts(
                        type_name=type_to_update,
                        tenant_id=tenant_id,
                        total_count=record["total"],
                        pending_count=record["pending"]
                    )

        driver_counts.close()

        logger.info(f"📝 Type {new_entity_type} enregistré dans le registry")

        # Retourner entité mise à jour
        updated_entity = dict(node)

        # Convertir Neo4j DateTime en Python datetime si nécessaire
        created_at = updated_entity.get("created_at")
        if hasattr(created_at, 'to_native'):
            created_at = created_at.to_native()

        return EntityResponse(
            uuid=updated_entity["uuid"],
            name=updated_entity["name"],
            entity_type=updated_entity["entity_type"],
            canonical_name=updated_entity.get("canonical_name"),
            description=updated_entity.get("description", ""),
            confidence=updated_entity.get("confidence", 1.0),
            status=updated_entity.get("status", "pending"),
            is_cataloged=updated_entity.get("is_cataloged", False),
            created_at=created_at,
            tenant_id=updated_entity.get("tenant_id", "default")
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Erreur changement type: {e}")
        raise HTTPException(status_code=500, detail=str(e))


class BulkChangeTypeRequest(BaseModel):
    """Requête changement type en masse."""

    entity_uuids: List[str] = Field(
        ...,
        description="Liste des UUIDs des entités à migrer"
    )
    new_entity_type: str = Field(
        ...,
        description="Nouveau type d'entité (ex: SOLUTION, COMPONENT, etc.)"
    )


class BulkChangeTypeResponse(BaseModel):
    """Réponse changement type en masse."""

    migrated_count: int = Field(
        ...,
        description="Nombre d'entités migrées avec succès"
    )
    failed_count: int = Field(
        default=0,
        description="Nombre d'entités en échec"
    )
    errors: List[dict] = Field(
        default_factory=list,
        description="Liste des erreurs rencontrées"
    )


@router.post("/bulk-change-type", response_model=BulkChangeTypeResponse)
async def bulk_change_entity_type(
    request: Request,
    admin: dict = Depends(require_admin),
    tenant_id: str = Depends(get_tenant_id),
    db: Session = Depends(get_db)
):
    """
    Change le type de plusieurs entités en une seule opération.

    Utile pour migrer en masse des entités d'un type vers un autre.

    Args:
        request: Liste des UUIDs et nouveau type
        admin: Admin authentifié
        tenant_id: Tenant ID
        db: Session DB

    Returns:
        Statistiques de migration
    """
    # Parser le body manuellement pour debug
    body = await request.json()
    logger.info(f"🔍 DEBUG bulk-change-type - Body reçu: {body}")

    try:
        bulk_request = BulkChangeTypeRequest(**body)
    except Exception as e:
        logger.error(f"❌ Erreur validation Pydantic: {e}")
        raise

    logger.info(
        f"🔄 Migration en masse de {len(bulk_request.entity_uuids)} entités → {bulk_request.new_entity_type}"
    )

    from neo4j import GraphDatabase
    import os
    from knowbase.api.services.entity_type_registry_service import EntityTypeRegistryService

    neo4j_uri = os.getenv("NEO4J_URI", "bolt://neo4j:7687")
    neo4j_user = os.getenv("NEO4J_USER", "neo4j")
    neo4j_password = os.getenv("NEO4J_PASSWORD", "password")

    driver = GraphDatabase.driver(neo4j_uri, auth=(neo4j_user, neo4j_password))

    migrated_count = 0
    failed_count = 0
    errors = []
    old_types = set()

    try:
        # Migrer chaque entité
        for entity_uuid in bulk_request.entity_uuids:
            try:
                with driver.session() as session:
                    query = """
                    MATCH (e:Entity {uuid: $uuid, tenant_id: $tenant_id})
                    WITH e, e.entity_type AS old_type
                    SET e.entity_type = $new_type,
                        e.updated_at = datetime()
                    RETURN e, old_type
                    """

                    result = session.run(
                        query,
                        uuid=entity_uuid,
                        tenant_id=tenant_id,
                        new_type=bulk_request.new_entity_type.upper()
                    )

                    record = result.single()
                    if not record:
                        failed_count += 1
                        errors.append({
                            "uuid": entity_uuid,
                            "error": "Entity not found"
                        })
                        continue

                    old_types.add(record["old_type"])
                    migrated_count += 1

            except Exception as e:
                failed_count += 1
                errors.append({
                    "uuid": entity_uuid,
                    "error": str(e)
                })
                logger.error(f"❌ Erreur migration {entity_uuid}: {e}")

        driver.close()

        # Enregistrer le nouveau type dans le registry s'il n'existe pas
        registry_service = EntityTypeRegistryService(db)
        entity_type_record = registry_service.get_or_create_type(
            type_name=bulk_request.new_entity_type.upper(),
            tenant_id=tenant_id,
            discovered_by="admin"
        )

        # Approuver automatiquement si créé maintenant
        if entity_type_record.status == "pending" and entity_type_record.discovered_by == "admin":
            registry_service.approve_type(
                type_name=bulk_request.new_entity_type.upper(),
                admin_email=admin.get("email", "admin@example.com"),
                tenant_id=tenant_id
            )

        # Mettre à jour les compteurs pour tous les types concernés
        driver_counts = GraphDatabase.driver(neo4j_uri, auth=(neo4j_user, neo4j_password))

        # Types à mettre à jour : ancien types + nouveau type
        types_to_update = list(old_types) + [bulk_request.new_entity_type.upper()]

        for type_to_update in types_to_update:
            with driver_counts.session() as session:
                result = session.run("""
                    MATCH (e:Entity {entity_type: $type, tenant_id: $tenant_id})
                    RETURN count(e) as total,
                           sum(CASE WHEN e.status = 'pending' THEN 1 ELSE 0 END) as pending
                """, type=type_to_update, tenant_id=tenant_id)

                record = result.single()
                if record:
                    registry_service.update_entity_counts(
                        type_name=type_to_update,
                        tenant_id=tenant_id,
                        total_count=record["total"],
                        pending_count=record["pending"]
                    )

        driver_counts.close()

        logger.info(
            f"✅ Migration terminée: {migrated_count} réussies, {failed_count} échecs"
        )

        return BulkChangeTypeResponse(
            migrated_count=migrated_count,
            failed_count=failed_count,
            errors=errors
        )

    except Exception as e:
        logger.error(f"❌ Erreur migration en masse: {e}")
        raise HTTPException(status_code=500, detail=str(e))


__all__ = ["router"]
