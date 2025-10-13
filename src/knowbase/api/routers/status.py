from __future__ import annotations

from fastapi import APIRouter, Depends

from knowbase.api.dependencies import get_current_user, get_tenant_id
from knowbase.api.services.status import job_status

router = APIRouter()


@router.get("/status/{uid}")
def get_status(
    uid: str,
    current_user: dict = Depends(get_current_user),
    tenant_id: str = Depends(get_tenant_id),
):
    """
    Récupère le statut d'un job par UID.

    **Sécurité**: Requiert authentification JWT (tous rôles).
    """
    return job_status(uid)


__all__ = ["router"]
