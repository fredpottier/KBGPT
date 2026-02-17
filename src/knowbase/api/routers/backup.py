"""
Router FastAPI pour Backup & Restore.

Sauvegarde et restauration complète du système OSMOSE.
"""

from fastapi import APIRouter, Depends, HTTPException
from typing import Dict

from knowbase.api.dependencies import require_admin, get_tenant_id
from knowbase.api.schemas.backup import (
    BackupManifest,
    BackupListResponse,
    CurrentSystemStats,
    BackupCreateRequest,
    BackupRestoreRequest,
    BackupJobStatus,
)
from knowbase.api.services.backup_service import get_backup_service
from knowbase.common.logging import setup_logging
from knowbase.config.settings import get_settings

settings = get_settings()
logger = setup_logging(settings.logs_dir, "backup_router.log")

router = APIRouter(prefix="/backup", tags=["backup"])


@router.get(
    "/list",
    response_model=BackupListResponse,
    summary="Liste des backups disponibles",
)
async def list_backups(
    admin: dict = Depends(require_admin),
):
    """Liste tous les backups avec résumé."""
    service = get_backup_service()
    return service.list_backups()


@router.get(
    "/current-stats",
    response_model=CurrentSystemStats,
    summary="Stats du système actuel",
)
async def get_current_stats(
    admin: dict = Depends(require_admin),
):
    """Collecte les statistiques actuelles de tous les composants."""
    service = get_backup_service()
    return service.get_current_stats()


@router.get(
    "/{name}",
    response_model=BackupManifest,
    summary="Détail d'un backup",
)
async def get_backup_detail(
    name: str,
    admin: dict = Depends(require_admin),
):
    """Retourne le manifest complet d'un backup."""
    service = get_backup_service()
    manifest = service.get_backup(name)
    if not manifest:
        raise HTTPException(status_code=404, detail=f"Backup '{name}' non trouvé")
    return manifest


@router.delete(
    "/{name}",
    summary="Supprimer un backup",
)
async def delete_backup(
    name: str,
    admin: dict = Depends(require_admin),
) -> Dict:
    """Supprime un backup et tous ses fichiers."""
    service = get_backup_service()
    success = service.delete_backup(name)
    if not success:
        raise HTTPException(status_code=404, detail=f"Backup '{name}' non trouvé")
    return {"success": True, "message": f"Backup '{name}' supprimé"}


@router.post(
    "/create",
    response_model=BackupJobStatus,
    summary="Créer un backup",
)
async def create_backup(
    request: BackupCreateRequest,
    admin: dict = Depends(require_admin),
) -> BackupJobStatus:
    """Lance un backup complet en background."""
    service = get_backup_service()

    # Vérifier qu'un backup du même nom n'existe pas
    existing = service.get_backup(request.name)
    if existing:
        raise HTTPException(
            status_code=409,
            detail=f"Un backup '{request.name}' existe déjà"
        )

    logger.info(f"Création backup '{request.name}' par {admin.get('email', 'admin')}")
    return service.launch_backup(request.name, request.include_cache)


@router.post(
    "/restore",
    response_model=BackupJobStatus,
    summary="Restaurer un backup",
)
async def restore_backup(
    request: BackupRestoreRequest,
    admin: dict = Depends(require_admin),
) -> BackupJobStatus:
    """Lance une restauration en background."""
    service = get_backup_service()

    # Vérifier que le backup existe
    manifest = service.get_backup(request.name)
    if not manifest:
        raise HTTPException(
            status_code=404,
            detail=f"Backup '{request.name}' non trouvé"
        )

    logger.warning(f"Restauration backup '{request.name}' par {admin.get('email', 'admin')}")
    return service.launch_restore(request.name, request.auto_backup)


@router.get(
    "/status/{job_id}",
    response_model=BackupJobStatus,
    summary="Statut d'une opération",
)
async def get_job_status(
    job_id: str,
    admin: dict = Depends(require_admin),
):
    """Retourne le statut d'une opération backup/restore en cours."""
    service = get_backup_service()
    status = service.get_job_status(job_id)
    if not status:
        raise HTTPException(status_code=404, detail=f"Job '{job_id}' non trouvé")
    return status


__all__ = ["router"]
