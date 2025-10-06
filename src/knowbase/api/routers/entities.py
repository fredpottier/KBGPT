"""
Router API pour gestion des entités Knowledge Graph.

Phase 1 - Gestion validation entités dynamiques
Phase 3 - Admin actions (approve, merge, delete cascade)
"""
from typing import List, Optional
from pathlib import Path
import yaml

from fastapi import APIRouter, HTTPException, Query, Depends
from pydantic import BaseModel, Field

from knowbase.api.schemas.knowledge_graph import EntityResponse
from knowbase.api.services.knowledge_graph_service import KnowledgeGraphService
from knowbase.api.dependencies.auth import require_admin, get_tenant_id
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


@router.post("/{uuid}/approve", response_model=EntityResponse)
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
    request: MergeEntitiesRequest,
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
        request: UUID target + options
        admin: Admin user (authenticated)
        tenant_id: Tenant ID (from header)

    Returns:
        dict: Résultat fusion avec stats

    Raises:
        404: Une des entités non trouvée
        400: Tentative fusion même entité
    """
    logger.info(
        f"🔀 POST /entities/{source_uuid}/merge → {request.target_uuid} "
        f"- admin={admin['email']}"
    )

    if source_uuid == request.target_uuid:
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
                target_uuid=request.target_uuid,
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
                target_uuid=request.target_uuid,
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
                target_uuid=request.target_uuid,
                tenant_id=tenant_id
            )
            transferred_in = result_in.single()["transferred_in"]

            # Optionnel: Renommer entité cible
            if request.canonical_name:
                query_rename = """
                MATCH (target:Entity {uuid: $target_uuid, tenant_id: $tenant_id})
                SET target.name = $canonical_name
                """
                session.run(
                    query_rename,
                    target_uuid=request.target_uuid,
                    tenant_id=tenant_id,
                    canonical_name=request.canonical_name
                )

            # Supprimer entité source
            query_delete_source = """
            MATCH (source:Entity {uuid: $source_uuid, tenant_id: $tenant_id})
            DELETE source
            """
            session.run(query_delete_source, source_uuid=source_uuid, tenant_id=tenant_id)

            logger.info(
                f"✅ Fusion réussie: {source_uuid} → {request.target_uuid} "
                f"(relations transférées: {transferred_out + transferred_in})"
            )

            return {
                "status": "merged",
                "source_uuid": source_uuid,
                "target_uuid": request.target_uuid,
                "relations_transferred": transferred_out + transferred_in,
                "canonical_name": request.canonical_name
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


__all__ = ["router"]
