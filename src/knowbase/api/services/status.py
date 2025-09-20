from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from knowbase.config.settings import get_settings
from knowbase.ingestion.queue import fetch_job
from knowbase.api.services.import_history_redis import get_redis_import_history_service

PUBLIC_URL = os.getenv("PUBLIC_URL", "knowbase.ngrok.app")


def job_status(uid: str) -> dict[str, Any]:
    job = fetch_job(uid)
    if job is None:
        return {"action": "unknown", "status": "not_found"}

    job_type = str(job.meta.get("job_type", "unknown"))
    status = job.get_status(refresh=True)
    history_service = get_redis_import_history_service()

    if job.is_failed:
        # Mettre à jour l'historique
        error_message = str(job.exc_info) if job.exc_info else "Erreur inconnue"
        history_service.update_import_status(uid, "failed", error_message=error_message)
        return {"action": job_type, "status": "error", "message": job.exc_info}

    if job.is_finished:
        result = job.result if isinstance(job.result, dict) else {}
        response: dict[str, Any] = {"action": job_type, "status": "done"}

        # Mettre à jour l'historique
        chunks_inserted = result.get("chunks_inserted", 0) if result else 0
        history_service.update_import_status(uid, "completed", chunks_inserted=chunks_inserted)

        output_path = result.get("output_path")
        if output_path:
            filename = os.path.basename(output_path)
            response["download_url"] = f"https://{PUBLIC_URL}/static/presentations/{filename}"
        if result:
            response["result"] = result
            # Ajouter chunks_inserted à la réponse pour l'interface
            if "chunks_inserted" in result:
                response["chunks_inserted"] = result["chunks_inserted"]
        return response

    if status in {"started", "queued", "deferred"}:
        # Récupérer les détails de progression depuis les métadonnées
        progress_info = {
            "action": job_type,
            "status": "processing"
        }

        # Ajouter les informations de progression si disponibles
        if hasattr(job, 'meta') and job.meta:
            current_step = job.meta.get("current_step")
            progress = job.meta.get("progress", 0)
            total_steps = job.meta.get("total_steps", 0)
            step_message = job.meta.get("step_message", "")

            if current_step:
                progress_info.update({
                    "current_step": current_step,
                    "progress": progress,
                    "total_steps": total_steps,
                    "step_message": step_message,
                    "progress_percentage": round((progress / total_steps) * 100) if total_steps > 0 else 0
                })

        return progress_info

    return {"action": job_type, "status": status}


__all__ = ["job_status"]
