# src/knowbase/api/routers/challenge.py
"""
Endpoint API Challenge pour MVP V1.

Part of: OSMOSE MVP V1 - Usage B (Challenge de Texte)
Reference: SPEC_IMPLEMENTATION_CLASSES_MVP_V1.md
"""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from typing import Optional

from ..services.challenge_service import TextChallenger, ChallengeResponse
from knowbase.common.clients.neo4j_client import get_neo4j_client

router = APIRouter(prefix="/api/v2/challenge", tags=["Challenge"])


class ChallengeRequest(BaseModel):
    """Requête de challenge."""
    text: str = Field(..., description="Texte à challenger", min_length=10)
    tenant_id: str = Field(default="default")
    context: Optional[dict] = Field(
        default=None,
        description="Contexte optionnel (edition, region, product)"
    )
    include_missing: bool = Field(
        default=True,
        description="Inclure les claims non documentés"
    )


@router.post("/", response_model=ChallengeResponse)
async def challenge_text(request: ChallengeRequest):
    """
    Challenge un texte utilisateur contre le corpus documentaire.

    Retourne pour chaque claim:
    - CONFIRMED: Validé par le corpus
    - CONTRADICTED: Contredit par le corpus (avec niveau soft/hard)
    - PARTIAL: Trouvé mais non comparable
    - MISSING: Sujet documenté, valeur absente
    - UNMAPPED: Pas de pattern reconnu (INVARIANT 2: jamais silencieux)

    Reference: SPEC_TECHNIQUE_MVP_V1_USAGE_B.md
    """
    neo4j_client = get_neo4j_client()
    challenger = TextChallenger(neo4j_client.driver, request.tenant_id)

    try:
        result = await challenger.challenge(
            text=request.text,
            context=request.context,
            include_missing=request.include_missing
        )
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/health")
async def health():
    """Health check."""
    return {"status": "ok", "service": "challenge"}
