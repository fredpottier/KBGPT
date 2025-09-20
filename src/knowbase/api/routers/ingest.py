from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, File, Form, Request, UploadFile

from knowbase.api.services.ingestion import handle_dispatch, handle_excel_qa_upload, handle_excel_rfp_fill, analyze_excel_file
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


@router.post("/documents/upload-excel-qa")
async def upload_excel_qa(
    file: UploadFile = File(...),
    meta_file: Optional[UploadFile] = File(None),
):
    settings = get_settings()
    return await handle_excel_qa_upload(
        file=file,
        meta_file=meta_file,
        settings=settings,
        logger=logger,
    )


@router.post("/documents/fill-excel-rfp")
async def fill_excel_rfp(
    file: UploadFile = File(...),
    meta_file: Optional[UploadFile] = File(None),
):
    settings = get_settings()
    return await handle_excel_rfp_fill(
        file=file,
        meta_file=meta_file,
        settings=settings,
        logger=logger,
    )


@router.post("/documents/analyze-excel")
async def analyze_excel(
    file: UploadFile = File(...),
):
    """Analyse un fichier Excel pour identifier les onglets et colonnes disponibles."""
    settings = get_settings()
    return await analyze_excel_file(
        file=file,
        settings=settings,
        logger=logger,
    )




__all__ = ["router"]
