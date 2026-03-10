"""
Router API pour le téléchargement des fichiers traités.
"""

from fastapi import APIRouter, Depends, HTTPException, Response
from fastapi.responses import FileResponse
from pathlib import Path
import logging
from knowbase.api.dependencies import get_current_user, get_tenant_id
from knowbase.config.settings import get_settings
from knowbase.api.services.import_history_redis import get_redis_import_history_service

logger = logging.getLogger("knowbase.api.downloads")
router = APIRouter(prefix="/api/downloads", tags=["Downloads"])


@router.get("/filled-rfp/{uid}")
async def download_filled_rfp(
    uid: str,
    current_user: dict = Depends(get_current_user),
    tenant_id: str = Depends(get_tenant_id),
):
    """
    Télécharge un fichier Excel RFP complété par UID.

    **Sécurité**: Requiert authentification JWT (tous rôles).

    Args:
        uid: Identifiant unique de l'import RFP

    Returns:
        FileResponse: Le fichier Excel complété
    """
    try:
        settings = get_settings()

        # Récupérer les informations depuis l'historique Redis
        history_service = get_redis_import_history_service()
        import_record = history_service.get_import_by_uid(uid)

        if not import_record:
            logger.warning(f"📥 Import UID '{uid}' non trouvé dans l'historique")
            raise HTTPException(status_code=404, detail="Import non trouvé")

        # Vérifier que c'est bien un import de type fill_rfp
        if import_record.get("import_type") != "fill_rfp":
            logger.warning(f"📥 Import UID '{uid}' n'est pas de type fill_rfp")
            raise HTTPException(status_code=400, detail="Ce n'est pas un fichier RFP complété")

        # Vérifier que le traitement est terminé avec succès
        if import_record.get("status") != "completed":
            logger.warning(f"📥 Import UID '{uid}' n'est pas terminé (statut: {import_record.get('status')})")
            raise HTTPException(status_code=400, detail="Le traitement n'est pas terminé")

        # Construire le chemin du fichier complété
        # Les fichiers RFP sont sauvegardés dans presentations_dir avec le pattern {stem}_{short_uid}_filled.xlsx
        original_filename = import_record.get("filename", f"{uid}.xlsx")
        filename_stem = Path(original_filename).stem

        # Construire le nom de fichier avec le format: {original_stem}_{YYYYMMJJHHMMSS}_filled.xlsx
        # Extraire le nom original et l'UID court
        original_stem = filename_stem.split('_')[0]  # "CriteoToFill" de "CriteoToFill.xlsx"

        # Extraire la partie date/time de l'UID au format YYYYMMJJHHMMSS
        uid_parts = uid.split('_')
        if len(uid_parts) >= 3 and uid_parts[-3:-1] == ['rfp']:
            date_part = uid_parts[-2]  # YYYYMMJJ
            time_part = uid_parts[-1]  # HHMMSS
            short_uid = f"{date_part}{time_part}"  # YYYYMMJJHHMMSS
        else:
            short_uid = uid

        filled_filename = f"{original_stem}_{short_uid}_filled.xlsx"
        file_path = settings.presentations_dir / filled_filename

        if not file_path.exists():
            logger.error(f"📥 Fichier complété non trouvé: {file_path}")
            raise HTTPException(status_code=404, detail="Fichier complété non trouvé")

        # Nom du fichier pour le téléchargement (plus convivial)
        download_filename = f"RFP_complété_{original_filename}"

        logger.info(f"📥 Téléchargement RFP complété: {uid} -> {download_filename}")

        return FileResponse(
            path=file_path,
            filename=download_filename,
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Erreur téléchargement RFP '{uid}': {e}")
        raise HTTPException(status_code=500, detail=f"Erreur serveur: {str(e)}")


@router.get("/import-files/{uid}")
async def download_import_file(
    uid: str,
    current_user: dict = Depends(get_current_user),
    tenant_id: str = Depends(get_tenant_id),
):
    """
    Télécharge le fichier original d'un import par UID.

    **Sécurité**: Requiert authentification JWT (tous rôles).

    Args:
        uid: Identifiant unique de l'import

    Returns:
        FileResponse: Le fichier original de l'import
    """
    try:
        settings = get_settings()

        # Récupérer les informations depuis l'historique Redis
        history_service = get_redis_import_history_service()
        import_record = history_service.get_import_by_uid(uid)

        if not import_record:
            logger.warning(f"📥 Import UID '{uid}' non trouvé dans l'historique")
            raise HTTPException(status_code=404, detail="Import non trouvé")

        # Déterminer le répertoire selon le statut
        status = import_record.get("status", "")
        if status == "completed":
            base_dir = settings.docs_done_dir
        else:
            base_dir = settings.docs_in_dir

        # Essayer de trouver le fichier avec différentes extensions
        extensions = [".xlsx", ".xls", ".pdf", ".pptx", ".docx", ".md", ".html", ".htm"]
        file_path = None

        for ext in extensions:
            potential_path = base_dir / f"{uid}{ext}"
            if potential_path.exists():
                file_path = potential_path
                break

        if not file_path:
            logger.error(f"📥 Fichier d'import non trouvé pour UID: {uid}")
            raise HTTPException(status_code=404, detail="Fichier d'import non trouvé")

        # Déterminer le type MIME
        mime_types = {
            ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            ".xls": "application/vnd.ms-excel",
            ".pdf": "application/pdf",
            ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
            ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            ".md": "text/markdown",
            ".html": "text/html",
            ".htm": "text/html"
        }

        file_extension = file_path.suffix.lower()
        media_type = mime_types.get(file_extension, "application/octet-stream")

        # Nom du fichier pour le téléchargement
        original_filename = import_record.get("filename", file_path.name)

        logger.info(f"📥 Téléchargement fichier import: {uid} -> {original_filename}")

        return FileResponse(
            path=file_path,
            filename=original_filename,
            media_type=media_type
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Erreur téléchargement fichier '{uid}': {e}")
        raise HTTPException(status_code=500, detail=f"Erreur serveur: {str(e)}")


__all__ = ["router"]