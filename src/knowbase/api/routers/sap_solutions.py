"""
Router API pour la gestion des solutions SAP.
"""

from fastapi import APIRouter, Depends, HTTPException
from typing import List, Dict, Any
from pydantic import BaseModel
from knowbase.api.dependencies import get_current_user, get_tenant_id
from knowbase.api.services.sap_solutions import get_sap_solutions_manager
from knowbase.common.logging import setup_logging
from knowbase.common.clients import get_qdrant_client
from knowbase.config.settings import get_settings
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
async def get_solutions(
    current_user: dict = Depends(get_current_user),
    tenant_id: str = Depends(get_tenant_id),
):
    """
    Récupère la liste de toutes les solutions SAP disponibles.

    **Sécurité**: Requiert authentification JWT (tous rôles).

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
async def resolve_solution(
    request: SolutionResolveRequest,
    current_user: dict = Depends(get_current_user),
    tenant_id: str = Depends(get_tenant_id),
):
    """
    Résout une solution SAP depuis l'input utilisateur en utilisant l'IA.

    **Sécurité**: Requiert authentification JWT (tous rôles).

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
async def search_solutions(
    query: str,
    current_user: dict = Depends(get_current_user),
    tenant_id: str = Depends(get_tenant_id),
):
    """
    Recherche des solutions SAP par nom ou alias.

    **Sécurité**: Requiert authentification JWT (tous rôles).

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


@router.get("/with-chunks", response_model=SolutionsListResponse)
async def get_solutions_with_chunks(
    extend_search: bool = False,
    current_user: dict = Depends(get_current_user),
    tenant_id: str = Depends(get_tenant_id),
):
    """
    Récupère uniquement les solutions SAP qui ont des chunks dans les collections Qdrant.

    **Sécurité**: Requiert authentification JWT (tous rôles).

    Args:
        extend_search: Si False, ne cherche que dans Q/A RFP. Si True, inclut aussi la collection principale.

    Returns:
        SolutionsListResponse: Liste des solutions ayant des chunks en base
    """
    try:
        settings = get_settings()
        qdrant_client = get_qdrant_client()

        # Déterminer les collections à vérifier selon le paramètre extend_search
        if extend_search:
            collections_to_check = [settings.qdrant_collection, settings.qdrant_qa_collection]
            logger.info("🔍 Recherche étendue : Q/A RFP + Base de connaissances principale")
        else:
            collections_to_check = [settings.qdrant_qa_collection]
            logger.info("🔍 Recherche limitée : Q/A RFP uniquement")

        solutions_with_chunks = set()

        for collection_name in collections_to_check:
            try:
                # Récupérer un échantillon de points pour voir quelles solutions existent
                scroll_result = qdrant_client.scroll(
                    collection_name=collection_name,
                    limit=1000,  # Limiter pour performance
                    with_payload=["main_solution", "solution"]
                )

                # Extraire les solutions uniques selon la collection
                for point in scroll_result[0]:
                    if point.payload:
                        # Collection Q/A RFP : utilise main_solution
                        if collection_name == settings.qdrant_qa_collection:
                            if "main_solution" in point.payload:
                                solution_name = point.payload["main_solution"]
                                if isinstance(solution_name, str) and solution_name.strip():
                                    solutions_with_chunks.add(solution_name.strip())

                        # Collection principale : utilise solution.main
                        elif collection_name == settings.qdrant_collection:
                            if "solution" in point.payload and isinstance(point.payload["solution"], dict):
                                solution_main = point.payload["solution"].get("main")
                                if isinstance(solution_main, str) and solution_main.strip():
                                    solutions_with_chunks.add(solution_main.strip())

            except Exception as collection_error:
                logger.warning(f"⚠️ Impossible d'accéder à la collection {collection_name}: {collection_error}")
                continue

        # Filtrer la liste complète des solutions pour ne garder que celles avec chunks
        all_solutions = get_sap_solutions_manager().get_solutions_list()
        filtered_solutions = [
            SolutionResponse(id=solution_id, name=canonical_name)
            for canonical_name, solution_id in all_solutions
            if canonical_name in solutions_with_chunks
        ]

        logger.info(f"📋 Solutions avec chunks: {len(filtered_solutions)}/{len(all_solutions)} solutions disponibles")
        logger.info(f"🔍 Solutions trouvées: {[s.name for s in filtered_solutions]}")

        return SolutionsListResponse(
            solutions=filtered_solutions,
            total=len(filtered_solutions)
        )

    except Exception as e:
        logger.error(f"❌ Erreur récupération solutions avec chunks: {e}")
        raise HTTPException(status_code=500, detail=f"Erreur serveur: {str(e)}")