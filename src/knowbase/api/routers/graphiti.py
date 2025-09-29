"""
Endpoints FastAPI pour l'intégration Graphiti
"""
from typing import Dict, Any, List, Optional
from fastapi import APIRouter, HTTPException, Depends, Query
from pydantic import BaseModel, Field
import logging
from datetime import datetime

from ...common.graphiti import GraphitiStore, graphiti_config
from ...common.graphiti.tenant_manager import GraphitiTenantManager, create_tenant_manager
from ...common.interfaces.graph_store import FactStatus

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/graphiti", tags=["graphiti"])

# Singleton pour le gestionnaire de tenants
_tenant_manager: Optional[GraphitiTenantManager] = None


async def get_tenant_manager() -> GraphitiTenantManager:
    """Dependency pour obtenir le gestionnaire de tenants"""
    global _tenant_manager
    if _tenant_manager is None:
        _tenant_manager = await create_tenant_manager()
    return _tenant_manager


# Schémas Pydantic

class EpisodeCreate(BaseModel):
    """Schéma pour créer un épisode"""
    group_id: str = Field(..., description="Identifiant du groupe (multi-tenant)")
    content: str = Field(..., description="Contenu de l'épisode")
    episode_type: str = Field(default="message", description="Type d'épisode")
    metadata: Optional[Dict[str, Any]] = Field(default=None, description="Métadonnées additionnelles")


class FactCreate(BaseModel):
    """Schéma pour créer un fait"""
    group_id: str = Field(..., description="Identifiant du groupe")
    subject: str = Field(..., description="Sujet du fait")
    predicate: str = Field(..., description="Prédicat/relation")
    object: str = Field(..., description="Objet du fait")
    confidence: float = Field(default=1.0, ge=0.0, le=1.0, description="Confiance du fait")
    source: str = Field(default="api", description="Source du fait")
    status: FactStatus = Field(default=FactStatus.PROPOSED, description="Statut du fait")


class RelationCreate(BaseModel):
    """Schéma pour créer une relation"""
    source_id: str = Field(..., description="ID de l'entité source")
    relation_type: str = Field(..., description="Type de relation")
    target_id: str = Field(..., description="ID de l'entité cible")
    properties: Optional[Dict[str, Any]] = Field(default=None, description="Propriétés de la relation")


class SubgraphRequest(BaseModel):
    """Schéma pour récupérer un sous-graphe"""
    entity_id: str = Field(..., description="ID de l'entité centrale")
    depth: int = Field(default=2, ge=1, le=5, description="Profondeur de recherche")
    group_id: Optional[str] = Field(default=None, description="Filtre par groupe")


class TenantCreate(BaseModel):
    """Schéma pour créer un tenant"""
    group_id: str = Field(..., description="Identifiant unique du groupe")
    name: Optional[str] = Field(default=None, description="Nom du groupe")
    description: Optional[str] = Field(default=None, description="Description du groupe")
    metadata: Optional[Dict[str, Any]] = Field(default=None, description="Métadonnées du groupe")


# Endpoints

@router.get("/health")
async def health_check() -> Dict[str, Any]:
    """
    Vérifie l'état de santé de Graphiti (version simplifiée)
    """
    try:
        return {
            "service": "graphiti",
            "status": "healthy",
            "message": "Endpoints Graphiti disponibles",
            "config": {
                "neo4j_uri": graphiti_config.neo4j_uri,
                "neo4j_user": graphiti_config.neo4j_user,
                "group_isolation_enabled": graphiti_config.enable_group_isolation
            },
            "timestamp": datetime.now().isoformat()
        }
    except Exception as e:
        logger.error(f"Erreur health check Graphiti: {e}")
        raise HTTPException(status_code=500, detail=f"Erreur health check: {str(e)}")


@router.get("/health-full")
async def health_check_full(manager: GraphitiTenantManager = Depends(get_tenant_manager)) -> Dict[str, Any]:
    """
    Vérifie l'état de santé complet de Graphiti avec connexion Neo4j
    """
    try:
        health_status = await manager.store.health_check()
        return {
            "service": "graphiti",
            "status": health_status["status"],
            "details": health_status,
            "config": {
                "neo4j_uri": graphiti_config.neo4j_uri,
                "neo4j_user": graphiti_config.neo4j_user,
                "group_isolation_enabled": graphiti_config.enable_group_isolation
            }
        }
    except Exception as e:
        logger.error(f"Erreur health check Graphiti: {e}")
        raise HTTPException(status_code=500, detail=f"Erreur health check: {str(e)}")


@router.post("/episodes")
async def create_episode(
    episode_data: EpisodeCreate,
    manager: GraphitiTenantManager = Depends(get_tenant_manager)
) -> Dict[str, Any]:
    """
    Crée un nouvel épisode dans Graphiti
    """
    try:
        episode_uuid = await manager.isolate_tenant_data(
            group_id=episode_data.group_id,
            action="create_episode",
            content=episode_data.content,
            episode_type=episode_data.episode_type,
            metadata=episode_data.metadata
        )

        return {
            "episode_uuid": episode_uuid,
            "group_id": episode_data.group_id,
            "episode_type": episode_data.episode_type,
            "status": "created"
        }

    except Exception as e:
        logger.error(f"Erreur création épisode: {e}")
        raise HTTPException(status_code=500, detail=f"Erreur création épisode: {str(e)}")


@router.post("/facts")
async def create_fact(
    fact_data: FactCreate,
    manager: GraphitiTenantManager = Depends(get_tenant_manager)
) -> Dict[str, Any]:
    """
    Crée un nouveau fait dans le graphe de connaissances
    """
    try:
        fact_dict = {
            "subject": fact_data.subject,
            "predicate": fact_data.predicate,
            "object": fact_data.object,
            "confidence": fact_data.confidence,
            "source": fact_data.source
        }

        fact_uuid = await manager.isolate_tenant_data(
            group_id=fact_data.group_id,
            action="create_fact",
            fact=fact_dict,
            status=fact_data.status
        )

        return {
            "fact_uuid": fact_uuid,
            "group_id": fact_data.group_id,
            "subject": fact_data.subject,
            "predicate": fact_data.predicate,
            "object": fact_data.object,
            "status": fact_data.status.value
        }

    except Exception as e:
        logger.error(f"Erreur création fait: {e}")
        raise HTTPException(status_code=500, detail=f"Erreur création fait: {str(e)}")


@router.get("/facts")
async def search_facts(
    query: str = Query(..., description="Requête de recherche"),
    group_id: Optional[str] = Query(default=None, description="Filtre par groupe"),
    status_filter: Optional[FactStatus] = Query(default=None, description="Filtre par statut"),
    limit: int = Query(default=10, ge=1, le=100, description="Nombre maximum de résultats"),
    manager: GraphitiTenantManager = Depends(get_tenant_manager)
) -> Dict[str, Any]:
    """
    Recherche des faits dans le graphe
    """
    try:
        if group_id:
            facts = await manager.isolate_tenant_data(
                group_id=group_id,
                action="search_facts",
                query=query,
                status_filter=status_filter,
                limit=limit
            )
        else:
            facts = await manager.store.search_facts(
                query=query,
                group_id=None,
                status_filter=status_filter,
                limit=limit
            )

        return {
            "query": query,
            "group_id": group_id,
            "status_filter": status_filter.value if status_filter else None,
            "results_count": len(facts),
            "facts": facts
        }

    except Exception as e:
        logger.error(f"Erreur recherche faits: {e}")
        raise HTTPException(status_code=500, detail=f"Erreur recherche faits: {str(e)}")


@router.post("/relations")
async def create_relation(
    relation_data: RelationCreate,
    manager: GraphitiTenantManager = Depends(get_tenant_manager)
) -> Dict[str, Any]:
    """
    Crée une relation entre deux entités
    Note: Dans Graphiti, les relations sont gérées automatiquement via les épisodes
    """
    try:
        relation_id = await manager.store.create_relation(
            source_id=relation_data.source_id,
            relation_type=relation_data.relation_type,
            target_id=relation_data.target_id,
            properties=relation_data.properties
        )

        return {
            "relation_id": relation_id,
            "source_id": relation_data.source_id,
            "relation_type": relation_data.relation_type,
            "target_id": relation_data.target_id,
            "status": "noted",
            "note": "Relations gérées automatiquement par Graphiti via les épisodes"
        }

    except Exception as e:
        logger.error(f"Erreur création relation: {e}")
        raise HTTPException(status_code=500, detail=f"Erreur création relation: {str(e)}")


@router.post("/subgraph")
async def get_subgraph(
    subgraph_request: SubgraphRequest,
    manager: GraphitiTenantManager = Depends(get_tenant_manager)
) -> Dict[str, Any]:
    """
    Récupère un sous-graphe autour d'une entité
    """
    try:
        if subgraph_request.group_id:
            subgraph = await manager.isolate_tenant_data(
                group_id=subgraph_request.group_id,
                action="get_subgraph",
                entity_id=subgraph_request.entity_id,
                depth=subgraph_request.depth
            )
        else:
            subgraph = await manager.store.get_subgraph(
                entity_id=subgraph_request.entity_id,
                depth=subgraph_request.depth,
                group_id=subgraph_request.group_id
            )

        return {
            "entity_id": subgraph_request.entity_id,
            "depth": subgraph_request.depth,
            "group_id": subgraph_request.group_id,
            "subgraph": subgraph
        }

    except Exception as e:
        logger.error(f"Erreur récupération sous-graphe: {e}")
        raise HTTPException(status_code=500, detail=f"Erreur récupération sous-graphe: {str(e)}")


@router.get("/memory/{group_id}")
async def get_memory(
    group_id: str,
    limit: int = Query(default=20, ge=1, le=100, description="Nombre d'épisodes à récupérer"),
    manager: GraphitiTenantManager = Depends(get_tenant_manager)
) -> Dict[str, Any]:
    """
    Récupère la mémoire conversationnelle pour un groupe
    """
    try:
        memory = await manager.isolate_tenant_data(
            group_id=group_id,
            action="get_memory",
            limit=limit
        )

        return {
            "group_id": group_id,
            "memory_count": len(memory),
            "limit": limit,
            "memory": memory
        }

    except Exception as e:
        logger.error(f"Erreur récupération mémoire: {e}")
        raise HTTPException(status_code=500, detail=f"Erreur récupération mémoire: {str(e)}")


# Endpoints de gestion des tenants

@router.post("/tenants")
async def create_tenant(
    tenant_data: TenantCreate,
    manager: GraphitiTenantManager = Depends(get_tenant_manager)
) -> Dict[str, Any]:
    """
    Crée un nouveau tenant (groupe)
    """
    try:
        metadata = tenant_data.metadata or {}
        if tenant_data.name:
            metadata["name"] = tenant_data.name
        if tenant_data.description:
            metadata["description"] = tenant_data.description

        tenant_info = await manager.create_tenant(
            group_id=tenant_data.group_id,
            metadata=metadata
        )

        return {
            "message": f"Tenant {tenant_data.group_id} créé avec succès",
            "tenant": tenant_info
        }

    except Exception as e:
        logger.error(f"Erreur création tenant: {e}")
        raise HTTPException(status_code=500, detail=f"Erreur création tenant: {str(e)}")


@router.get("/tenants")
async def list_tenants(
    manager: GraphitiTenantManager = Depends(get_tenant_manager)
) -> Dict[str, Any]:
    """
    Liste tous les tenants
    """
    try:
        tenants = await manager.list_tenants()

        return {
            "tenants_count": len(tenants),
            "tenants": tenants
        }

    except Exception as e:
        logger.error(f"Erreur listage tenants: {e}")
        raise HTTPException(status_code=500, detail=f"Erreur listage tenants: {str(e)}")


@router.get("/tenants/{group_id}")
async def get_tenant_info(
    group_id: str,
    manager: GraphitiTenantManager = Depends(get_tenant_manager)
) -> Dict[str, Any]:
    """
    Récupère les informations d'un tenant
    """
    try:
        tenant_info = await manager.get_tenant_info(group_id)

        if not tenant_info:
            raise HTTPException(status_code=404, detail=f"Tenant {group_id} non trouvé")

        return {
            "tenant": tenant_info
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Erreur récupération tenant: {e}")
        raise HTTPException(status_code=500, detail=f"Erreur récupération tenant: {str(e)}")


@router.delete("/tenants/{group_id}")
async def delete_tenant(
    group_id: str,
    confirm: bool = Query(default=False, description="Confirmation de suppression"),
    manager: GraphitiTenantManager = Depends(get_tenant_manager)
) -> Dict[str, Any]:
    """
    Supprime un tenant et toutes ses données
    """
    try:
        success = await manager.delete_tenant(group_id, confirm=confirm)

        if not success:
            raise HTTPException(
                status_code=400,
                detail=f"Suppression tenant {group_id} échouée. Confirmez avec ?confirm=true"
            )

        return {
            "message": f"Tenant {group_id} supprimé avec succès",
            "group_id": group_id
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Erreur suppression tenant: {e}")
        raise HTTPException(status_code=500, detail=f"Erreur suppression tenant: {str(e)}")