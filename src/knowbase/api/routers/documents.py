"""
Router API pour gestion documents et déduplication

Endpoints:
- POST /api/documents/check-duplicate : Vérification duplicate avant upload
- GET /api/documents/imports/{import_id} : Metadata import
- GET /api/documents/imports/history : Historique imports tenant

Phase 1 - Critère 1.5
"""

import logging
from typing import Optional
from fastapi import APIRouter, HTTPException, Depends, Query

from knowbase.api.schemas.import_tracking import (
    CheckDuplicateRequest,
    CheckDuplicateResponse,
    ImportMetadata,
    ImportHistoryResponse
)
from knowbase.ingestion.deduplication import (
    check_duplicate,
    get_import_metadata,
    get_imports_history,
    DuplicateStatus
)
from knowbase.common.qdrant_client import get_qdrant_client

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/documents",
    tags=["documents"],
    responses={404: {"description": "Not found"}},
)


@router.post("/check-duplicate", response_model=CheckDuplicateResponse)
async def check_duplicate_document(
    request: CheckDuplicateRequest,
    qdrant_client = Depends(get_qdrant_client)
):
    """
    Vérification duplicate avant upload

    Frontend appelle cet endpoint avec hashes calculés côté client
    (file_hash immédiat, content_hash après extraction si disponible).

    **Workflow**:
    1. Client calcule file_hash avant upload (optionnel)
    2. Après extraction, calcule content_hash
    3. Appelle /check-duplicate avec hashes
    4. Si duplicate → affiche modal warning
    5. Si nouveau → procède upload normal

    **Statuts possibles**:
    - `EXACT_DUPLICATE`: Contenu identique → Rejet (allow_upload=False)
    - `CONTENT_MODIFIED`: Contenu modifié → Autorisé (nouveau episode KG)
    - `NEW_DOCUMENT`: Nouveau document → Autorisé

    **Exemple**:
    ```bash
    curl -X POST /api/documents/check-duplicate \\
      -H "Content-Type: application/json" \\
      -d '{
        "content_hash": "sha256:abc123...",
        "filename": "my_doc.pptx",
        "tenant_id": "corporate"
      }'
    ```
    """
    try:
        logger.info(
            f"Check duplicate: filename='{request.filename}' "
            f"tenant={request.tenant_id}"
        )

        # Si content_hash non fourni, considérer comme nouveau
        if not request.content_hash:
            logger.warning(
                f"content_hash non fourni pour {request.filename}, "
                "considéré comme nouveau document"
            )
            return CheckDuplicateResponse(
                status=DuplicateStatus.NEW_DOCUMENT,
                is_duplicate=False,
                existing_import=None,
                message="Nouveau document (hash non fourni, vérification impossible)",
                allow_upload=True
            )

        # Check duplicate via Qdrant
        duplicate_info = await check_duplicate(
            content_hash=request.content_hash,
            tenant_id=request.tenant_id,
            qdrant_client=qdrant_client,
            collection_name="knowbase"
        )

        # Si duplicate, récupérer metadata complète import existant
        existing_import_meta = None
        if duplicate_info.is_duplicate and duplicate_info.existing_import_id:
            existing_import_meta = await get_import_metadata(
                import_id=duplicate_info.existing_import_id,
                tenant_id=request.tenant_id,
                qdrant_client=qdrant_client
            )

            if existing_import_meta:
                existing_import_meta = ImportMetadata(**existing_import_meta)

        response = CheckDuplicateResponse(
            status=duplicate_info.status,
            is_duplicate=duplicate_info.is_duplicate,
            existing_import=existing_import_meta,
            message=duplicate_info.message,
            allow_upload=duplicate_info.allow_upload
        )

        logger.info(
            f"Check duplicate résultat: {duplicate_info.status} "
            f"(allow_upload={duplicate_info.allow_upload})"
        )

        return response

    except Exception as e:
        logger.error(f"Erreur check_duplicate_document: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Erreur vérification duplicate: {str(e)}"
        )


@router.get("/imports/{import_id}", response_model=ImportMetadata)
async def get_import_by_id(
    import_id: str,
    tenant_id: str = Query(..., description="ID tenant"),
    qdrant_client = Depends(get_qdrant_client)
):
    """
    Récupération metadata import complet

    Retourne toutes les informations d'un import (hashes, chunks, episode, etc.).

    **Paramètres**:
    - `import_id`: UUID import (path parameter)
    - `tenant_id`: ID tenant (query parameter, requis pour sécurité)

    **Exemple**:
    ```bash
    curl -X GET "/api/documents/imports/550e8400-e29b-41d4-a716-446655440000?tenant_id=corporate"
    ```
    """
    try:
        logger.info(f"Get import metadata: import_id={import_id[:8]}... tenant={tenant_id}")

        metadata = await get_import_metadata(
            import_id=import_id,
            tenant_id=tenant_id,
            qdrant_client=qdrant_client,
            collection_name="knowbase"
        )

        if not metadata:
            raise HTTPException(
                status_code=404,
                detail=f"Import {import_id} introuvable pour tenant {tenant_id}"
            )

        return ImportMetadata(**metadata)

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Erreur get_import_by_id: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Erreur récupération import: {str(e)}"
        )


@router.get("/imports/history", response_model=ImportHistoryResponse)
async def get_imports_history_endpoint(
    tenant_id: str = Query(..., description="ID tenant"),
    limit: int = Query(50, ge=1, le=200, description="Nombre max imports (1-200)"),
    offset: int = Query(0, ge=0, description="Offset pagination"),
    qdrant_client = Depends(get_qdrant_client)
):
    """
    Historique imports par tenant

    Retourne liste imports triés par date DESC avec pagination.

    **Paramètres**:
    - `tenant_id`: ID tenant (requis)
    - `limit`: Nombre max imports à retourner (défaut: 50, max: 200)
    - `offset`: Offset pagination (défaut: 0)

    **Exemple**:
    ```bash
    curl -X GET "/api/documents/imports/history?tenant_id=corporate&limit=20&offset=0"
    ```

    **Réponse**:
    ```json
    {
      "imports": [
        {
          "import_id": "550e8400-...",
          "filename": "Doc1.pptx",
          "chunk_count": 42,
          "imported_at": "2025-10-02T14:30:00Z",
          ...
        }
      ],
      "total": 15,
      "limit": 20,
      "offset": 0
    }
    ```
    """
    try:
        logger.info(
            f"Get imports history: tenant={tenant_id} "
            f"limit={limit} offset={offset}"
        )

        imports_list = await get_imports_history(
            tenant_id=tenant_id,
            qdrant_client=qdrant_client,
            collection_name="knowbase",
            limit=limit,
            offset=offset
        )

        # Total avant pagination (approximation car agrégation)
        # TODO: optimiser avec count exact si nécessaire
        total = len(imports_list) + offset

        response = ImportHistoryResponse(
            imports=imports_list,
            total=total,
            limit=limit,
            offset=offset
        )

        logger.info(f"Imports history retourné: {len(imports_list)} imports")
        return response

    except Exception as e:
        logger.error(f"Erreur get_imports_history: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Erreur récupération historique: {str(e)}"
        )
