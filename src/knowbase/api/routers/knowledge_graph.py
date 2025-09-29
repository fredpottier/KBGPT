"""
Router API Knowledge Graph - Phase 2 Multi-Tenant
Endpoints pour la gestion du graphe de connaissances (Corporate + Personnel)
"""

import logging
from typing import List, Optional
from fastapi import APIRouter, HTTPException, Query, Path, Depends, Request
from fastapi.responses import JSONResponse

from knowbase.api.services.user_knowledge_graph import UserKnowledgeGraphService
from knowbase.api.middleware.user_context import get_user_context
from knowbase.api.schemas.knowledge_graph import (
    EntityCreate, EntityResponse, RelationCreate, RelationResponse,
    SubgraphRequest, SubgraphResponse, KnowledgeGraphStats,
    RelationType
)

logger = logging.getLogger(__name__)

router = APIRouter()


async def get_kg_service() -> UserKnowledgeGraphService:
    """Dependency injection pour le service Knowledge Graph multi-tenant"""
    return UserKnowledgeGraphService()


@router.get("/knowledge-graph/health",
           summary="Health check du Knowledge Graph (Corporate ou Personnel)",
           tags=["Knowledge Graph"])
async def health_check(
    request: Request,
    service: UserKnowledgeGraphService = Depends(get_kg_service)
):
    """
    Vérifie la santé du Knowledge Graph (Corporate par défaut ou Personnel si X-User-ID fourni)
    """
    try:
        # Récupérer le contexte utilisateur
        context = get_user_context(request)

        # Récupérer les stats selon le contexte
        stats = await service.get_user_stats(request)

        # Message selon le mode
        mode = "Personnel" if context["is_personal_kg"] else "Corporate"
        message = f"Knowledge Graph {mode} opérationnel"

        return JSONResponse(content={
            "status": "healthy",
            "message": message,
            "mode": mode.lower(),
            "group_id": context["group_id"],
            "user_id": context.get("user_id"),
            "stats": {
                "total_entities": stats.total_entities,
                "total_relations": stats.total_relations
            }
        })

    except Exception as e:
        logger.error(f"Erreur health check KG: {e}")
        context = get_user_context(request)
        return JSONResponse(
            status_code=503,
            content={
                "status": "unhealthy",
                "message": f"Erreur Knowledge Graph: {str(e)}",
                "group_id": context.get("group_id", "corporate")
            }
        )


@router.post("/knowledge-graph/entities",
            response_model=EntityResponse,
            summary="Créer une entité (Corporate ou Personnel selon contexte)",
            tags=["Knowledge Graph", "Entities"])
async def create_entity(
    entity: EntityCreate,
    request: Request,
    service: UserKnowledgeGraphService = Depends(get_kg_service)
):
    """
    Crée une nouvelle entité dans le Knowledge Graph (Corporate par défaut ou Personnel si X-User-ID)

    - **name**: Nom de l'entité (requis)
    - **entity_type**: Type d'entité (document, concept, solution, etc.)
    - **description**: Description optionnelle
    - **attributes**: Attributs additionnels au format JSON

    Mode d'opération :
    - Sans X-User-ID : Création dans le KG Corporate (partagé)
    - Avec X-User-ID : Création dans le KG Personnel de l'utilisateur (isolé)
    """
    try:
        context = get_user_context(request)
        mode = "personnel" if context["is_personal_kg"] else "corporate"

        result = await service.create_entity_for_user(request, entity)
        logger.info(f"Entité créée via API ({mode}): {entity.name}")
        return result

    except ValueError as e:
        logger.warning(f"Erreur validation entité: {e}")
        raise HTTPException(status_code=400, detail=str(e))

    except Exception as e:
        logger.error(f"Erreur création entité: {e}")
        raise HTTPException(status_code=500, detail="Erreur interne serveur")


@router.get("/knowledge-graph/entities/{entity_id}",
           response_model=EntityResponse,
           summary="Récupérer une entité (contexte Corporate ou Personnel)",
           tags=["Knowledge Graph", "Entities"])
async def get_entity(
    entity_id: str = Path(..., description="Identifiant unique de l'entité"),
    request: Request = None,
    service: UserKnowledgeGraphService = Depends(get_kg_service)
):
    """
    Récupère une entité par son identifiant unique dans le contexte approprié

    Isolation multi-tenant :
    - Sans X-User-ID : Recherche dans le KG Corporate
    - Avec X-User-ID : Recherche dans le KG Personnel de l'utilisateur
    """
    try:
        entity = await service.get_entity_for_user(request, entity_id)

        if not entity:
            raise HTTPException(status_code=404, detail="Entité non trouvée")

        return entity

    except HTTPException:
        raise

    except Exception as e:
        logger.error(f"Erreur récupération entité {entity_id}: {e}")
        raise HTTPException(status_code=500, detail="Erreur interne serveur")


@router.post("/knowledge-graph/relations",
            response_model=RelationResponse,
            summary="Créer une relation (contexte Corporate ou Personnel)",
            tags=["Knowledge Graph", "Relations"])
async def create_relation(
    relation: RelationCreate,
    request: Request,
    service: UserKnowledgeGraphService = Depends(get_kg_service)
):
    """
    Crée une nouvelle relation entre deux entités dans le contexte approprié

    - **source_entity_id**: ID de l'entité source (requis)
    - **target_entity_id**: ID de l'entité cible (requis)
    - **relation_type**: Type de relation (contains, relates_to, etc.)
    - **description**: Description optionnelle
    - **confidence**: Score de confiance (0.0 à 1.0)
    - **attributes**: Attributs additionnels au format JSON

    Isolation multi-tenant :
    - Sans X-User-ID : Création dans le KG Corporate
    - Avec X-User-ID : Création dans le KG Personnel de l'utilisateur
    """
    try:
        context = get_user_context(request)
        mode = "personnel" if context["is_personal_kg"] else "corporate"

        result = await service.create_relation_for_user(request, relation)
        logger.info(f"Relation créée via API ({mode}): {relation.source_entity_id} -> {relation.target_entity_id}")
        return result

    except ValueError as e:
        logger.warning(f"Erreur validation relation: {e}")
        raise HTTPException(status_code=400, detail=str(e))

    except Exception as e:
        logger.error(f"Erreur création relation: {e}")
        raise HTTPException(status_code=500, detail="Erreur interne serveur")


@router.get("/knowledge-graph/relations",
           response_model=List[RelationResponse],
           summary="Lister les relations (contexte Corporate ou Personnel)",
           tags=["Knowledge Graph", "Relations"])
async def list_relations(
    entity_id: Optional[str] = Query(None, description="Filtrer par entité (source ou cible)"),
    relation_type: Optional[RelationType] = Query(None, description="Filtrer par type de relation"),
    limit: int = Query(100, ge=1, le=1000, description="Nombre maximum de résultats"),
    request: Request = None,
    service: UserKnowledgeGraphService = Depends(get_kg_service)
):
    """
    Liste les relations du Knowledge Graph dans le contexte approprié

    Filtres disponibles:
    - **entity_id**: Relations impliquant cette entité (source ou cible)
    - **relation_type**: Relations d'un type spécifique
    - **limit**: Nombre maximum de résultats (1-1000)

    Isolation multi-tenant :
    - Sans X-User-ID : Listing depuis le KG Corporate
    - Avec X-User-ID : Listing depuis le KG Personnel de l'utilisateur
    """
    try:
        context = get_user_context(request)
        mode = "personnel" if context["is_personal_kg"] else "corporate"

        relations = await service.list_relations_for_user(
            request=request,
            entity_id=entity_id,
            relation_type=relation_type,
            limit=limit
        )

        logger.info(f"Relations listées via API ({mode}): {len(relations)} résultats")
        return relations

    except Exception as e:
        logger.error(f"Erreur listage relations: {e}")
        raise HTTPException(status_code=500, detail="Erreur interne serveur")


@router.delete("/knowledge-graph/relations/{relation_id}",
              summary="Supprimer une relation (contexte Corporate ou Personnel)",
              tags=["Knowledge Graph", "Relations"])
async def delete_relation(
    relation_id: str = Path(..., description="Identifiant unique de la relation"),
    request: Request = None,
    service: UserKnowledgeGraphService = Depends(get_kg_service)
):
    """
    Supprime une relation du Knowledge Graph dans le contexte approprié

    Isolation multi-tenant :
    - Sans X-User-ID : Suppression depuis le KG Corporate
    - Avec X-User-ID : Suppression depuis le KG Personnel de l'utilisateur
    """
    try:
        context = get_user_context(request)
        mode = "personnel" if context["is_personal_kg"] else "corporate"

        success = await service.delete_relation_for_user(request, relation_id)

        if not success:
            raise HTTPException(status_code=404, detail="Relation non trouvée")

        return JSONResponse(content={
            "status": "success",
            "message": f"Relation {relation_id} supprimée ({mode})",
            "relation_id": relation_id,
            "mode": mode
        })

    except HTTPException:
        raise

    except Exception as e:
        logger.error(f"Erreur suppression relation {relation_id}: {e}")
        raise HTTPException(status_code=500, detail="Erreur interne serveur")


@router.post("/knowledge-graph/subgraph",
            response_model=SubgraphResponse,
            summary="Récupérer un sous-graphe (contexte Corporate ou Personnel)",
            tags=["Knowledge Graph", "Subgraph"])
async def get_subgraph(
    subgraph_request: SubgraphRequest,
    request: Request = None,
    service: UserKnowledgeGraphService = Depends(get_kg_service)
):
    """
    Récupère un sous-graphe centré sur une entité dans le contexte approprié

    - **entity_id**: ID de l'entité centrale (requis)
    - **depth**: Profondeur d'exploration (1-5, défaut: 2)
    - **entity_types**: Types d'entités à inclure (optionnel)
    - **relation_types**: Types de relations à inclure (optionnel)

    Le sous-graphe retourné contient:
    - L'entité centrale
    - Tous les noeuds connectés jusqu'à la profondeur spécifiée
    - Toutes les arêtes entre ces noeuds
    - Métadonnées de structure (nombre de noeuds/arêtes, profondeur atteinte)

    Isolation multi-tenant :
    - Sans X-User-ID : Sous-graphe depuis le KG Corporate
    - Avec X-User-ID : Sous-graphe depuis le KG Personnel de l'utilisateur
    """
    try:
        context = get_user_context(request)
        mode = "personnel" if context["is_personal_kg"] else "corporate"

        result = await service.get_subgraph_for_user(request, subgraph_request)
        logger.info(f"Sous-graphe généré via API ({mode}): {result.total_nodes} noeuds, {result.total_edges} arêtes")
        return result

    except ValueError as e:
        logger.warning(f"Erreur validation sous-graphe: {e}")
        raise HTTPException(status_code=400, detail=str(e))

    except Exception as e:
        logger.error(f"Erreur génération sous-graphe: {e}")
        raise HTTPException(status_code=500, detail="Erreur interne serveur")


@router.get("/knowledge-graph/stats",
           response_model=KnowledgeGraphStats,
           summary="Statistiques du Knowledge Graph (contexte Corporate ou Personnel)",
           tags=["Knowledge Graph", "Stats"])
async def get_stats(
    request: Request = None,
    service: UserKnowledgeGraphService = Depends(get_kg_service)
):
    """
    Récupère les statistiques complètes du Knowledge Graph dans le contexte approprié

    Inclut:
    - Nombre total d'entités et relations
    - Répartition par types d'entités
    - Répartition par types de relations
    - Métadonnées du groupe (corporate ou personnel)

    Isolation multi-tenant :
    - Sans X-User-ID : Statistiques du KG Corporate
    - Avec X-User-ID : Statistiques du KG Personnel de l'utilisateur
    """
    try:
        context = get_user_context(request)
        mode = "personnel" if context["is_personal_kg"] else "corporate"

        stats = await service.get_user_stats(request)
        logger.info(f"Stats KG via API ({mode}): {stats.total_entities} entités, {stats.total_relations} relations")
        return stats

    except Exception as e:
        logger.error(f"Erreur récupération stats: {e}")
        raise HTTPException(status_code=500, detail="Erreur interne serveur")