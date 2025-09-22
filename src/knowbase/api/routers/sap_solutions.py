"""
Router API pour la gestion des solutions SAP.
"""

from fastapi import APIRouter, HTTPException
from typing import List, Dict, Any
from pydantic import BaseModel
from knowbase.api.services.sap_solutions import get_sap_solutions_manager
from knowbase.common.logging import setup_logging
from pathlib import Path

logger = setup_logging(Path(__file__).parent.parent.parent.parent.parent / "data" / "logs", "api_sap_solutions.log")

router = APIRouter(prefix="/api/sap-solutions", tags=["SAP Solutions"])


class SolutionResponse(BaseModel):
    """Modèle de réponse pour une solution SAP."""
    id: str
    name: str


class SolutionsListResponse(BaseModel):
    """Modèle de réponse pour la liste des solutions."""
    solutions: List[SolutionResponse]
    total: int


class SolutionResolveRequest(BaseModel):
    """Modèle de requête pour résoudre une solution."""
    solution_input: str


class SolutionResolveResponse(BaseModel):
    """Modèle de réponse pour la résolution d'une solution."""
    canonical_name: str
    solution_id: str
    original_input: str


@router.get("/", response_model=SolutionsListResponse)
async def get_solutions():
    """
    Récupère la liste de toutes les solutions SAP disponibles.

    Returns:
        SolutionsListResponse: Liste des solutions avec ID et nom canonique
    """
    try:
        solutions_list = get_sap_solutions_manager().get_solutions_list()

        solutions = [
            SolutionResponse(id=solution_id, name=canonical_name)
            for canonical_name, solution_id in solutions_list
        ]

        logger.info(f"📋 Retourné {len(solutions)} solutions SAP")

        return SolutionsListResponse(
            solutions=solutions,
            total=len(solutions)
        )

    except Exception as e:
        logger.error(f"❌ Erreur récupération solutions: {e}")
        raise HTTPException(status_code=500, detail=f"Erreur serveur: {str(e)}")


@router.post("/resolve", response_model=SolutionResolveResponse)
async def resolve_solution(request: SolutionResolveRequest):
    """
    Résout une solution SAP depuis l'input utilisateur en utilisant l'IA.

    Args:
        request: Requête contenant l'input utilisateur

    Returns:
        SolutionResolveResponse: Solution résolue avec nom canonique et ID
    """
    try:
        if not request.solution_input.strip():
            raise HTTPException(status_code=400, detail="L'input solution ne peut pas être vide")

        logger.info(f"🔍 Résolution solution pour: '{request.solution_input}'")

        canonical_name, solution_id = get_sap_solutions_manager().resolve_solution(request.solution_input)

        logger.info(f"✅ Solution résolue: '{request.solution_input}' → '{canonical_name}' (ID: {solution_id})")

        return SolutionResolveResponse(
            canonical_name=canonical_name,
            solution_id=solution_id,
            original_input=request.solution_input
        )

    except Exception as e:
        logger.error(f"❌ Erreur résolution solution '{request.solution_input}': {e}")
        raise HTTPException(status_code=500, detail=f"Impossible de résoudre la solution: {str(e)}")


@router.get("/search/{query}")
async def search_solutions(query: str):
    """
    Recherche des solutions SAP par nom ou alias.

    Args:
        query: Terme de recherche

    Returns:
        Liste des solutions correspondantes
    """
    try:
        solutions_list = get_sap_solutions_manager().get_solutions_list()
        query_lower = query.lower()

        # Filtrer les solutions qui contiennent le terme de recherche
        matching_solutions = [
            SolutionResponse(id=solution_id, name=canonical_name)
            for canonical_name, solution_id in solutions_list
            if query_lower in canonical_name.lower()
        ]

        logger.info(f"🔍 Recherche '{query}': {len(matching_solutions)} résultats")

        return SolutionsListResponse(
            solutions=matching_solutions,
            total=len(matching_solutions)
        )

    except Exception as e:
        logger.error(f"❌ Erreur recherche solutions '{query}': {e}")
        raise HTTPException(status_code=500, detail=f"Erreur de recherche: {str(e)}")