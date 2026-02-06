"""
OSMOSE Verification API Router

Endpoints for verifying text against Knowledge Graph.

Author: Claude Code
Date: 2026-02-03
"""

import logging
from fastapi import APIRouter, HTTPException

from knowbase.api.schemas.verification import (
    VerifyRequest,
    VerifyResponse,
    CorrectRequest,
    CorrectResponse,
)
from knowbase.api.services.verification_service import get_verification_service

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/verify",
    tags=["verification"],
    responses={
        500: {"description": "Internal server error"}
    }
)


@router.post(
    "/analyze",
    response_model=VerifyResponse,
    summary="Analyser et vérifier un texte",
    description="""
Analyse un texte et vérifie chaque affirmation contre le Knowledge Graph.

**Processus:**
1. Découpe le texte en assertions vérifiables (via LLM)
2. Recherche des claims similaires dans Neo4j
3. Si pas de claim trouvé, fallback vers recherche Qdrant
4. Détermine le statut de chaque assertion

**Statuts possibles:**
- `confirmed`: Un claim confirme l'assertion
- `contradicted`: Un claim contredit l'assertion
- `incomplete`: Information partielle trouvée
- `fallback`: Trouvé dans Qdrant seulement (pas de claim)
- `unknown`: Aucune information trouvée
"""
)
async def analyze_text(request: VerifyRequest) -> VerifyResponse:
    """
    Analyse un texte et vérifie chaque assertion contre le KG.

    Args:
        request: Texte à vérifier et tenant_id

    Returns:
        Texte original avec assertions annotées et résumé
    """
    try:
        service = get_verification_service(tenant_id=request.tenant_id)
        result = await service.analyze(request.text)
        logger.info(
            f"[VERIFY_API] Analyzed text: {result.summary['total']} assertions, "
            f"{result.summary['confirmed']} confirmed, "
            f"{result.summary['contradicted']} contradicted"
        )
        return result

    except Exception as e:
        logger.error(f"[VERIFY_API] Analysis failed: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Erreur lors de l'analyse: {str(e)}"
        )


@router.post(
    "/correct",
    response_model=CorrectResponse,
    summary="Corriger un texte basé sur les vérifications",
    description="""
Génère une version corrigée du texte basée sur les assertions vérifiées.

**Processus:**
1. Filtre les assertions problématiques (contredites ou incomplètes)
2. Utilise un LLM pour réécrire le texte avec les corrections
3. Retourne le texte corrigé avec la liste des changements

**Note:** Seules les assertions `contradicted` et `incomplete` sont corrigées.
Les assertions `unknown` ou `fallback` ne sont pas modifiées.
"""
)
async def correct_text(request: CorrectRequest) -> CorrectResponse:
    """
    Génère une version corrigée du texte basée sur les claims.

    Args:
        request: Texte original et assertions vérifiées

    Returns:
        Texte corrigé avec liste des changements
    """
    try:
        service = get_verification_service(tenant_id=request.tenant_id)
        result = await service.correct(request.text, request.assertions)
        logger.info(
            f"[VERIFY_API] Generated corrections: {len(result.changes)} changes"
        )
        return result

    except Exception as e:
        logger.error(f"[VERIFY_API] Correction failed: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Erreur lors de la correction: {str(e)}"
        )
