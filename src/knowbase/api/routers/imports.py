from __future__ import annotations

from fastapi import APIRouter, HTTPException
from typing import List, Dict, Any

from knowbase.api.services.import_history_redis import get_redis_import_history_service

router = APIRouter()


@router.get("/imports/history")
def get_import_history(limit: int = 100) -> List[Dict[str, Any]]:
    """Récupère l'historique des imports."""
    service = get_redis_import_history_service()
    return service.get_history(limit=limit)


@router.get("/imports/active")
def get_active_imports() -> List[Dict[str, Any]]:
    """Récupère les imports actifs (en cours)."""
    service = get_redis_import_history_service()
    return service.get_active_imports()


@router.post("/imports/sync")
def sync_orphaned_jobs() -> Dict[str, Any]:
    """Synchronise les jobs RQ terminés avec l'historique Redis."""
    service = get_redis_import_history_service()
    synced_count = service.sync_orphaned_jobs()
    return {
        "message": f"{synced_count} jobs synchronisés",
        "synced_count": synced_count
    }


@router.post("/imports/cleanup")
def cleanup_old_imports(days: int = 30) -> Dict[str, Any]:
    """Nettoie les anciens enregistrements d'imports."""
    service = get_redis_import_history_service()
    deleted_count = service.cleanup_old_records(days=days)
    return {
        "message": f"{deleted_count} enregistrements supprimés",
        "deleted_count": deleted_count
    }


@router.delete("/imports/{uid}/delete")
def delete_import_completely(uid: str) -> Dict[str, Any]:
    """Supprime complètement un import : chunks, fichiers, historique."""
    from knowbase.api.services.import_deletion import delete_import_completely as delete_service

    try:
        result = delete_service(uid)
        return {
            "message": f"Import {uid} supprimé complètement",
            "deleted_items": result
        }
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erreur lors de la suppression: {str(e)}")


__all__ = ["router"]