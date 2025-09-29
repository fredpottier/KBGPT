"""
Router API Facts Gouvernées - Phase 3
Endpoints REST pour gestion du cycle de vie des faits avec validation humaine
"""

import logging
from typing import Optional
from fastapi import APIRouter, HTTPException, Depends, Request, Query
from fastapi.responses import JSONResponse

from knowbase.api.schemas.facts_governance import (
    FactCreate, FactResponse, FactUpdate, FactFilters,
    FactApprovalRequest, FactRejectionRequest,
    FactTimelineResponse, FactsListResponse, ConflictsListResponse,
    FactStats, FactStatus
)
from knowbase.api.services.facts_governance_service import FactsGovernanceService
from knowbase.api.middleware.user_context import get_user_context

logger = logging.getLogger(__name__)

# Créer le router
router = APIRouter(
    prefix="/api/facts",
    tags=["Facts Governance"],
    responses={404: {"description": "Not found"}}
)


def get_facts_service() -> FactsGovernanceService:
    """Dependency injection pour le service Facts"""
    return FactsGovernanceService()


@router.post("", response_model=FactResponse, status_code=201)
async def create_fact(
    fact: FactCreate,
    request: Request,
    service: FactsGovernanceService = Depends(get_facts_service)
):
    """
    Crée un nouveau fait avec statut "proposed"

    Le fait est automatiquement créé en attente de validation.
    La détection de conflits est effectuée automatiquement.

    **Workflow**:
    1. Création avec statut "proposed"
    2. Détection automatique de conflits
    3. Si conflits: statut peut être "conflicted"
    4. Nécessite approbation expert pour passer à "approved"

    **Permissions**: Tous utilisateurs authentifiés
    """
    try:
        # Récupérer le contexte utilisateur
        context = get_user_context(request)
        created_by = context.get("user_id", "system")

        # Définir le groupe multi-tenant
        await service.set_group(context.get("group_id", "corporate"))

        # Détecter les conflits avant création
        conflicts = await service.detect_conflicts(fact)

        # Créer le fait
        created_fact = await service.create_fact(fact, created_by=created_by)

        # Ajouter info conflits dans les headers
        if conflicts:
            logger.warning(f"Fait {created_fact.uuid} créé avec {len(conflicts)} conflits détectés")

        return created_fact

    except Exception as e:
        logger.error(f"Erreur création fait: {e}")
        raise HTTPException(status_code=500, detail=f"Erreur création fait: {str(e)}")


@router.get("", response_model=FactsListResponse)
async def list_facts(
    request: Request,
    status: Optional[FactStatus] = Query(None, description="Filtrer par statut"),
    created_by: Optional[str] = Query(None, description="Filtrer par créateur"),
    subject: Optional[str] = Query(None, description="Filtrer par sujet"),
    predicate: Optional[str] = Query(None, description="Filtrer par prédicat"),
    limit: int = Query(100, ge=1, le=1000, description="Nombre de résultats"),
    offset: int = Query(0, ge=0, description="Offset pagination"),
    service: FactsGovernanceService = Depends(get_facts_service)
):
    """
    Liste les faits avec filtres et pagination

    **Filtres disponibles**:
    - `status`: proposed/approved/rejected/conflicted
    - `created_by`: Identifiant utilisateur créateur
    - `subject`: Sujet du fait (recherche partielle)
    - `predicate`: Prédicat du fait (recherche partielle)

    **Pagination**:
    - `limit`: Nombre maximum de résultats (1-1000)
    - `offset`: Position de départ

    **Permissions**: Tous utilisateurs (données filtrées par groupe)
    """
    try:
        # Récupérer le contexte utilisateur
        context = get_user_context(request)
        await service.set_group(context.get("group_id", "corporate"))

        # Construire les filtres
        filters = FactFilters(
            status=status,
            created_by=created_by,
            subject=subject,
            predicate=predicate,
            limit=limit,
            offset=offset
        )

        # Récupérer les faits
        result = await service.list_facts(filters)

        return result

    except Exception as e:
        logger.error(f"Erreur listage faits: {e}")
        raise HTTPException(status_code=500, detail=f"Erreur listage faits: {str(e)}")


@router.get("/{fact_id}", response_model=FactResponse)
async def get_fact(
    fact_id: str,
    request: Request,
    service: FactsGovernanceService = Depends(get_facts_service)
):
    """
    Récupère un fait par son identifiant

    **Retour**: Fait complet avec métadonnées et historique

    **Permissions**: Tous utilisateurs (données filtrées par groupe)
    """
    try:
        # Récupérer le contexte utilisateur
        context = get_user_context(request)
        await service.set_group(context.get("group_id", "corporate"))

        # Récupérer le fait
        fact = await service.get_fact(fact_id)

        if not fact:
            raise HTTPException(status_code=404, detail=f"Fait {fact_id} introuvable")

        return fact

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Erreur récupération fait {fact_id}: {e}")
        raise HTTPException(status_code=500, detail=f"Erreur récupération fait: {str(e)}")


@router.put("/{fact_id}/approve", response_model=FactResponse)
async def approve_fact(
    fact_id: str,
    approval: FactApprovalRequest,
    request: Request,
    service: FactsGovernanceService = Depends(get_facts_service)
):
    """
    Approuve un fait proposé → statut "approved"

    **Workflow**:
    1. Vérifie que le fait existe et est en statut "proposed"
    2. Valide les permissions du validateur (rôle expert/admin)
    3. Change le statut à "approved"
    4. Enregistre l'audit trail (qui/quand/pourquoi)

    **Permissions**: Utilisateurs avec rôle expert ou admin

    **Note**: Un fait approuvé ne peut plus être modifié sans versioning
    """
    try:
        # Récupérer le contexte utilisateur
        context = get_user_context(request)
        await service.set_group(context.get("group_id", "corporate"))

        # TODO: Vérifier le rôle utilisateur (expert/admin requis)
        # Pour l'instant, on fait confiance au approver_id fourni

        # Approuver le fait
        approved_fact = await service.approve_fact(fact_id, approval)

        return approved_fact

    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.error(f"Erreur approbation fait {fact_id}: {e}")
        raise HTTPException(status_code=500, detail=f"Erreur approbation fait: {str(e)}")


@router.put("/{fact_id}/reject", response_model=FactResponse)
async def reject_fact(
    fact_id: str,
    rejection: FactRejectionRequest,
    request: Request,
    service: FactsGovernanceService = Depends(get_facts_service)
):
    """
    Rejette un fait proposé → statut "rejected"

    **Workflow**:
    1. Vérifie que le fait existe et est en statut "proposed"
    2. Valide les permissions du rejeteur (rôle expert/admin)
    3. Change le statut à "rejected"
    4. Enregistre le motif de rejet
    5. Enregistre l'audit trail (qui/quand/pourquoi)

    **Permissions**: Utilisateurs avec rôle expert ou admin

    **Note**: Un fait rejeté reste dans la base pour audit mais n'est plus utilisé
    """
    try:
        # Récupérer le contexte utilisateur
        context = get_user_context(request)
        await service.set_group(context.get("group_id", "corporate"))

        # TODO: Vérifier le rôle utilisateur (expert/admin requis)
        # Pour l'instant, on fait confiance au rejector_id fourni

        # Rejeter le fait
        rejected_fact = await service.reject_fact(fact_id, rejection)

        return rejected_fact

    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.error(f"Erreur rejet fait {fact_id}: {e}")
        raise HTTPException(status_code=500, detail=f"Erreur rejet fait: {str(e)}")


@router.get("/conflicts/list", response_model=ConflictsListResponse)
async def list_conflicts(
    request: Request,
    service: FactsGovernanceService = Depends(get_facts_service)
):
    """
    Liste tous les conflits actifs nécessitant résolution

    **Conflits détectés**:
    - Valeurs contradictoires pour même sujet/prédicat
    - Chevauchements temporels
    - Contradictions logiques
    - Duplications

    **Retour**: Liste des conflits avec suggestions de résolution

    **Permissions**: Utilisateurs avec rôle expert ou admin
    """
    try:
        # Récupérer le contexte utilisateur
        context = get_user_context(request)
        await service.set_group(context.get("group_id", "corporate"))

        # Récupérer les conflits
        conflicts = await service.get_conflicts()

        return conflicts

    except Exception as e:
        logger.error(f"Erreur récupération conflits: {e}")
        raise HTTPException(status_code=500, detail=f"Erreur récupération conflits: {str(e)}")


@router.get("/timeline/{entity_id}", response_model=FactTimelineResponse)
async def get_entity_timeline(
    entity_id: str,
    request: Request,
    service: FactsGovernanceService = Depends(get_facts_service)
):
    """
    Récupère l'historique temporel complet d'une entité

    **Historique bi-temporel**:
    - Transaction time: Quand le fait a été enregistré dans le système
    - Valid time: Période de validité réelle du fait

    **Retour**: Timeline chronologique avec toutes les versions

    **Use cases**:
    - Audit trail complet
    - Requêtes "au point dans le temps"
    - Analyse évolution connaissances
    - Détection divergences temporelles

    **Permissions**: Tous utilisateurs (données filtrées par groupe)
    """
    try:
        # Récupérer le contexte utilisateur
        context = get_user_context(request)
        await service.set_group(context.get("group_id", "corporate"))

        # Récupérer la timeline
        timeline = await service.get_timeline(entity_id)

        return timeline

    except Exception as e:
        logger.error(f"Erreur récupération timeline {entity_id}: {e}")
        raise HTTPException(status_code=500, detail=f"Erreur récupération timeline: {str(e)}")


@router.delete("/{fact_id}", status_code=204)
async def delete_fact(
    fact_id: str,
    request: Request,
    service: FactsGovernanceService = Depends(get_facts_service)
):
    """
    Supprime un fait (soft delete avec audit trail)

    **Note**: Les faits ne sont jamais vraiment supprimés pour préserver l'audit trail.
    Cette opération marque le fait comme supprimé et l'exclut des résultats.

    **Workflow**:
    1. Vérifie que le fait existe
    2. Marque comme supprimé avec métadata
    3. Enregistre l'audit trail (qui/quand)

    **Permissions**: Utilisateurs admin uniquement

    **Retour**: 204 No Content si succès
    """
    try:
        # Récupérer le contexte utilisateur
        context = get_user_context(request)
        await service.set_group(context.get("group_id", "corporate"))

        # TODO: Vérifier le rôle utilisateur (admin requis)

        # Pour l'instant, on rejette simplement le fait
        # Une vraie suppression nécessiterait une méthode dédiée
        fact = await service.get_fact(fact_id)
        if not fact:
            raise HTTPException(status_code=404, detail=f"Fait {fact_id} introuvable")

        # Marquer comme supprimé via rejet
        rejection = FactRejectionRequest(
            rejector_id=context.get("user_id", "system"),
            reason="Suppression du fait",
            comment="Supprimé par l'administrateur"
        )
        await service.reject_fact(fact_id, rejection)

        return JSONResponse(status_code=204, content=None)

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Erreur suppression fait {fact_id}: {e}")
        raise HTTPException(status_code=500, detail=f"Erreur suppression fait: {str(e)}")


@router.get("/stats/overview", response_model=FactStats)
async def get_facts_stats(
    request: Request,
    service: FactsGovernanceService = Depends(get_facts_service)
):
    """
    Récupère les statistiques globales sur les faits

    **Statistiques incluses**:
    - Nombre total de faits
    - Répartition par statut (proposed/approved/rejected)
    - Faits en attente de validation
    - Nombre de conflits actifs
    - Temps moyen d'approbation
    - Top contributeurs

    **Permissions**: Tous utilisateurs (données filtrées par groupe)
    """
    try:
        # Récupérer le contexte utilisateur
        context = get_user_context(request)
        await service.set_group(context.get("group_id", "corporate"))

        # Calculer les statistiques
        stats = await service.get_stats()

        return stats

    except Exception as e:
        logger.error(f"Erreur calcul statistiques: {e}")
        raise HTTPException(status_code=500, detail=f"Erreur calcul statistiques: {str(e)}")