from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, Depends, File, Form, Request, UploadFile

from knowbase.api.dependencies import require_editor, get_tenant_id
from knowbase.api.services.ingestion import handle_dispatch, handle_excel_qa_upload, handle_excel_rfp_fill, analyze_excel_file
from knowbase.config.settings import get_settings

router = APIRouter()
logger = logging.getLogger("knowbase.api")


@router.post("/dispatch")
async def dispatch_action(
    request: Request,
    action_type: Optional[str] = Form(None),
    document_type: Optional[str] = Form(None),
    document_type_id: Optional[str] = Form(None),
    question: Optional[str] = Form(None),
    file: Optional[UploadFile] = File(None),
    meta: Optional[str] = Form(None),
    use_vision: Optional[str] = Form("true"),  # Par défaut true pour rétrocompatibilité
    current_user: dict = Depends(require_editor),
    tenant_id: str = Depends(get_tenant_id),
):
    """
    Dispatch un document pour ingestion.

    **Sécurité**: Requiert authentification JWT avec rôle 'editor' ou 'admin'.
    """
    settings = get_settings()
    # Convertir use_vision string en bool
    use_vision_bool = use_vision.lower() in ("true", "1", "yes") if use_vision else True
    return handle_dispatch(
        request=request,
        action_type=action_type,
        document_type=document_type,
        document_type_id=document_type_id,
        question=question,
        file=file,
        meta=meta,
        use_vision=use_vision_bool,
        settings=settings,
        logger=logger,
    )


@router.post("/documents/upload-excel-qa")
async def upload_excel_qa(
    file: UploadFile = File(...),
    meta_file: Optional[UploadFile] = File(None),
    current_user: dict = Depends(require_editor),
    tenant_id: str = Depends(get_tenant_id),
):
    """
    Upload un fichier Excel Q&A.

    **Sécurité**: Requiert authentification JWT avec rôle 'editor' ou 'admin'.
    """
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
    current_user: dict = Depends(require_editor),
    tenant_id: str = Depends(get_tenant_id),
):
    """
    Remplit un fichier Excel RFP.

    **Sécurité**: Requiert authentification JWT avec rôle 'editor' ou 'admin'.
    """
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
    current_user: dict = Depends(require_editor),
    tenant_id: str = Depends(get_tenant_id),
):
    """
    Analyse un fichier Excel pour identifier les onglets et colonnes disponibles.

    **Sécurité**: Requiert authentification JWT avec rôle 'editor' ou 'admin'.
    """
    settings = get_settings()
    return await analyze_excel_file(
        file=file,
        settings=settings,
        logger=logger,
    )




__all__ = ["router"]
