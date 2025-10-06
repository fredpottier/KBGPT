"""
Router API pour gestion des entités Knowledge Graph.

Phase 1 - Gestion validation entités dynamiques
"""
from typing import List, Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from knowbase.api.schemas.knowledge_graph import EntityResponse
from knowbase.api.services.knowledge_graph_service import KnowledgeGraphService
from knowbase.common.logging import setup_logging
from knowbase.config.settings import get_settings

settings = get_settings()
logger = setup_logging(settings.logs_dir, "entities_router.log")

router = APIRouter(prefix="/entities", tags=["entities"])


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


@router.get("/pending", response_model=PendingEntitiesResponse)
async def list_pending_entities(
    entity_type: Optional[str] = Query(
        default=None,
        description="Filtrer par type d'entité (ex: INFRASTRUCTURE)"
    ),
    tenant_id: str = Query(
        default="default",
        description="Tenant ID (multi-tenancy)"
    ),
    limit: int = Query(
        default=100,
        ge=1,
        le=1000,
        description="Nombre max entités retournées"
    ),
    offset: int = Query(
        default=0,
        ge=0,
        description="Offset pagination"
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
    logger.info(
        f"📋 GET /entities/pending - entity_type={entity_type}, tenant={tenant_id}, "
        f"limit={limit}, offset={offset}"
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
            params["entity_type"] = entity_type.upper()

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


__all__ = ["router"]
