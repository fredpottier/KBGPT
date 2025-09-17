from __future__ import annotations

from fastapi import APIRouter

from knowbase.api.services.status import job_status

router = APIRouter()


@router.get("/status/{uid}")
def get_status(uid: str):
    return job_status(uid)


__all__ = ["router"]
