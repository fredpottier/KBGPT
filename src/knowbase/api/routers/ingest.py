from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, File, Form, Request, UploadFile

from knowbase.api.services.ingestion import handle_dispatch
from knowbase.config.settings import get_settings

router = APIRouter()
logger = logging.getLogger("knowbase.api")


@router.post("/dispatch")
async def dispatch_action(
    request: Request,
    action_type: Optional[str] = Form(None),
    document_type: Optional[str] = Form(None),
    question: Optional[str] = Form(None),
    file: Optional[UploadFile] = File(None),
    meta: Optional[str] = Form(None),
):
    settings = get_settings()
    return handle_dispatch(
        request=request,
        action_type=action_type,
        document_type=document_type,
        question=question,
        file=file,
        meta=meta,
        settings=settings,
        logger=logger,
    )


__all__ = ["router"]
