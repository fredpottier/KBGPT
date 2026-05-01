"""
Router API pour monitoring jobs async (RQ).

Phase 5B - Job Status Monitoring
"""
from fastapi import APIRouter, Depends, HTTPException
from redis import Redis
from rq.job import Job
import os

from knowbase.api.dependencies import get_current_user, get_tenant_id
from knowbase.common.logging import setup_logging
from knowbase.config.settings import get_settings

settings = get_settings()
logger = setup_logging(settings.logs_dir, "jobs_router.log")

router = APIRouter(prefix="/jobs", tags=["jobs"])


@router.get(
    "/{job_id}/status",
    summary="Vérifier statut job RQ",
    description="""
    Retourne statut et résultat d'un job RQ async.

    **Statuts possibles**:
    - `queued`: Job en attente
    - `started`: Job en cours d'exécution
    - `finished`: Job terminé avec succès
    - `failed`: Job échoué

    **Returns**:
    - `status`: Statut job
    - `result`: Résultat si finished
    - `error`: Message d'erreur si failed
    """,
    responses={
        200: {
            "description": "Statut job récupéré",
            "content": {
                "application/json": {
                    "examples": {
                        "queued": {
                            "summary": "Job en attente",
                            "value": {
                                "job_id": "abc-123",
                                "status": "queued",
                                "result": None
                            }
                        },
                        "finished": {
                            "summary": "Job terminé",
                            "value": {
                                "job_id": "abc-123",
                                "status": "finished",
                                "result": {
                                    "groups_proposed": 12,
                                    "entities_analyzed": 47
                                }
                            }
                        },
                        "failed": {
                            "summary": "Job échoué",
                            "value": {
                                "job_id": "abc-123",
                                "status": "failed",
                                "error": "LLM API error"
                            }
                        }
                    }
                }
            }
        },
        404: {
            "description": "Job introuvable"
        }
    }
)
async def get_job_status(
    job_id: str,
    current_user: dict = Depends(get_current_user),
    tenant_id: str = Depends(get_tenant_id),
):
    """
    Récupère statut job RQ.

    **Sécurité**: Requiert authentification JWT (tous rôles).

    Args:
        job_id: ID job RQ

    Returns:
        Dict avec status, result/error
    """
    logger.info(f"📊 GET /jobs/{job_id}/status")

    redis_conn = Redis(
        host=os.getenv("REDIS_HOST", "redis"),
        port=int(os.getenv("REDIS_PORT", "6379")), password=os.getenv("REDIS_PASSWORD") or None,
        db=0  # Même DB que worker ingestion
    )

    try:
        job = Job.fetch(job_id, connection=redis_conn)
    except Exception as e:
        logger.error(f"❌ Job {job_id} non trouvé: {e}")
        raise HTTPException(
            status_code=404,
            detail=f"Job '{job_id}' not found"
        )

    # Mapper statut RQ vers API
    status_map = {
        "queued": "queued",
        "started": "started",
        "finished": "finished",
        "failed": "failed",
        "stopped": "stopped",
        "canceled": "canceled",
        "deferred": "queued"
    }

    status = status_map.get(job.get_status(), "unknown")

    response = {
        "job_id": job_id,
        "status": status,
        "created_at": job.created_at.isoformat() if job.created_at else None,
        "started_at": job.started_at.isoformat() if job.started_at else None,
        "ended_at": job.ended_at.isoformat() if job.ended_at else None,
    }

    if status == "finished":
        response["result"] = job.result
    elif status == "failed":
        response["error"] = str(job.exc_info) if job.exc_info else "Unknown error"

    logger.info(f"✅ Job {job_id} status: {status}")

    return response


__all__ = ["router"]
