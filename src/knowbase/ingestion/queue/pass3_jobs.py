"""
Pass 3 Background Jobs for RQ Queue.

Système de jobs async pour Pass 3 (Semantic Consolidation / Validation).
Pattern identique à pass2_jobs.py pour cohérence.

Author: OSMOSE
Date: 2026-01-10
"""

import asyncio
import json
import logging
import time
import uuid
from datetime import datetime
from typing import List, Dict, Any, Optional
from dataclasses import dataclass, field, asdict
from enum import Enum

import redis
from rq import Queue

from knowbase.config.settings import get_settings

logger = logging.getLogger(__name__)


# =============================================================================
# Job State Management (Redis-backed)
# =============================================================================

class Pass3JobStatus(str, Enum):
    """États possibles d'un job Pass3."""
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass
class Pass3JobProgress:
    """Progression d'un job Pass3."""
    current_phase: str = ""
    phase_index: int = 0
    total_phases: int = 1
    items_processed: int = 0
    items_total: int = 0
    items_created: int = 0
    started_at: Optional[str] = None
    phase_started_at: Optional[str] = None
    elapsed_seconds: float = 0
    estimated_remaining_seconds: float = 0
    last_message: str = ""
    errors: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        data = asdict(self)
        data["phase"] = self.current_phase
        data["current_batch"] = 1
        data["total_batches"] = 1
        if self.items_total > 0:
            data["percentage"] = (self.items_processed / self.items_total) * 100
        else:
            data["percentage"] = 0
        return data

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Pass3JobProgress":
        errors = data.get("errors") or []
        return cls(
            current_phase=data.get("current_phase", ""),
            phase_index=data.get("phase_index", 0),
            total_phases=data.get("total_phases", 1),
            items_processed=data.get("items_processed", 0),
            items_total=data.get("items_total", 0),
            items_created=data.get("items_created", 0),
            started_at=data.get("started_at"),
            phase_started_at=data.get("phase_started_at"),
            elapsed_seconds=data.get("elapsed_seconds", 0),
            estimated_remaining_seconds=data.get("estimated_remaining_seconds", 0),
            last_message=data.get("last_message", ""),
            errors=errors
        )


@dataclass
class Pass3JobState:
    """État complet d'un job Pass3."""
    job_id: str
    tenant_id: str
    status: Pass3JobStatus
    document_id: Optional[str] = None
    max_candidates: int = 50
    progress: Pass3JobProgress = field(default_factory=Pass3JobProgress)
    result: Dict[str, Any] = field(default_factory=dict)
    created_at: str = ""
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    created_by: str = "admin"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "job_id": self.job_id,
            "tenant_id": self.tenant_id,
            "status": self.status.value,
            "document_id": self.document_id,
            "max_candidates": self.max_candidates,
            "progress": self.progress.to_dict(),
            "result": self.result,
            "created_at": self.created_at,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "created_by": self.created_by
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Pass3JobState":
        return cls(
            job_id=data["job_id"],
            tenant_id=data.get("tenant_id", "default"),
            status=Pass3JobStatus(data.get("status", "pending")),
            document_id=data.get("document_id"),
            max_candidates=data.get("max_candidates", 50),
            progress=Pass3JobProgress.from_dict(data.get("progress", {})),
            result=data.get("result", {}),
            created_at=data.get("created_at", ""),
            started_at=data.get("started_at"),
            completed_at=data.get("completed_at"),
            created_by=data.get("created_by", "admin")
        )


class Pass3JobManager:
    """Gestionnaire des jobs Pass3 avec persistance Redis."""

    REDIS_PREFIX = "pass3:job:"
    JOB_TTL_SECONDS = 86400 * 7  # 7 jours

    def __init__(self, redis_client: Optional[redis.Redis] = None):
        if redis_client:
            self._redis = redis_client
        else:
            settings = get_settings()
            redis_url = f"redis://{settings.redis_host}:{settings.redis_port}/0"
            self._redis = redis.from_url(redis_url, decode_responses=True)

    def _job_key(self, job_id: str) -> str:
        return f"{self.REDIS_PREFIX}{job_id}"

    def _list_key(self, tenant_id: str) -> str:
        return f"{self.REDIS_PREFIX}list:{tenant_id}"

    def create_job(
        self,
        tenant_id: str = "default",
        document_id: Optional[str] = None,
        max_candidates: int = 50,
        created_by: str = "admin"
    ) -> Pass3JobState:
        """Crée un nouveau job Pass3."""
        job_id = f"p3_{uuid.uuid4().hex[:12]}"
        now = datetime.utcnow().isoformat() + "Z"

        state = Pass3JobState(
            job_id=job_id,
            tenant_id=tenant_id,
            status=Pass3JobStatus.PENDING,
            document_id=document_id,
            max_candidates=max_candidates,
            created_at=now,
            created_by=created_by
        )

        self._save_state(state)
        self._redis.lpush(self._list_key(tenant_id), job_id)
        self._redis.ltrim(self._list_key(tenant_id), 0, 99)

        logger.info(f"[Pass3JobManager] Created job {job_id}")
        return state

    def get_job(self, job_id: str) -> Optional[Pass3JobState]:
        """Récupère l'état d'un job."""
        data = self._redis.get(self._job_key(job_id))
        if not data:
            return None
        try:
            return Pass3JobState.from_dict(json.loads(data))
        except Exception as e:
            logger.error(f"[Pass3JobManager] Error parsing job {job_id}: {e}")
            return None

    def list_jobs(self, tenant_id: str = "default", limit: int = 20) -> List[Pass3JobState]:
        """Liste les jobs d'un tenant."""
        job_ids = self._redis.lrange(self._list_key(tenant_id), 0, limit - 1)
        jobs = []
        for job_id in job_ids:
            state = self.get_job(job_id)
            if state:
                jobs.append(state)
        return jobs

    def update_progress(
        self,
        job_id: str,
        current_phase: Optional[str] = None,
        items_processed: Optional[int] = None,
        items_total: Optional[int] = None,
        items_created: Optional[int] = None,
        message: Optional[str] = None,
        error: Optional[str] = None
    ):
        """Met à jour la progression d'un job."""
        state = self.get_job(job_id)
        if not state:
            return

        if current_phase is not None:
            state.progress.current_phase = current_phase
            state.progress.phase_started_at = datetime.utcnow().isoformat() + "Z"
        if items_processed is not None:
            state.progress.items_processed = items_processed
        if items_total is not None:
            state.progress.items_total = items_total
        if items_created is not None:
            state.progress.items_created = items_created
        if message:
            state.progress.last_message = message
        if error:
            state.progress.errors.append(error)

        # Calculer temps écoulé
        if state.started_at:
            try:
                started = datetime.fromisoformat(state.started_at.replace("Z", "+00:00"))
                now = datetime.utcnow().replace(tzinfo=started.tzinfo)
                state.progress.elapsed_seconds = (now - started).total_seconds()
            except Exception:
                pass

        self._save_state(state)

    def start_job(self, job_id: str):
        """Marque un job comme démarré."""
        state = self.get_job(job_id)
        if state:
            state.status = Pass3JobStatus.RUNNING
            state.started_at = datetime.utcnow().isoformat() + "Z"
            state.progress.started_at = state.started_at
            self._save_state(state)
            logger.info(f"[Pass3JobManager] Job {job_id} started")

    def complete_job(self, job_id: str, result: Optional[Dict] = None):
        """Marque un job comme terminé."""
        state = self.get_job(job_id)
        if state:
            state.status = Pass3JobStatus.COMPLETED
            state.completed_at = datetime.utcnow().isoformat() + "Z"
            if result:
                state.result = result
            state.progress.last_message = "Pass 3 completed successfully"
            self._save_state(state)
            logger.info(f"[Pass3JobManager] Job {job_id} completed")

    def fail_job(self, job_id: str, error: str):
        """Marque un job comme échoué."""
        state = self.get_job(job_id)
        if state:
            state.status = Pass3JobStatus.FAILED
            state.completed_at = datetime.utcnow().isoformat() + "Z"
            state.progress.errors.append(error)
            state.progress.last_message = f"Failed: {error}"
            self._save_state(state)
            logger.error(f"[Pass3JobManager] Job {job_id} failed: {error}")

    def cancel_job(self, job_id: str) -> bool:
        """Annule un job."""
        state = self.get_job(job_id)
        if not state or state.status not in [Pass3JobStatus.PENDING, Pass3JobStatus.RUNNING]:
            return False

        state.status = Pass3JobStatus.CANCELLED
        state.completed_at = datetime.utcnow().isoformat() + "Z"
        state.progress.last_message = "Cancelled by user"
        self._save_state(state)
        logger.info(f"[Pass3JobManager] Job {job_id} cancelled")
        return True

    def is_cancelled(self, job_id: str) -> bool:
        """Vérifie si un job a été annulé."""
        state = self.get_job(job_id)
        return state.status == Pass3JobStatus.CANCELLED if state else False

    def _save_state(self, state: Pass3JobState):
        """Sauvegarde l'état dans Redis."""
        self._redis.setex(
            self._job_key(state.job_id),
            self.JOB_TTL_SECONDS,
            json.dumps(state.to_dict())
        )


# Singleton
_job_manager: Optional[Pass3JobManager] = None


def get_pass3_job_manager() -> Pass3JobManager:
    """Récupère l'instance singleton du gestionnaire."""
    global _job_manager
    if _job_manager is None:
        _job_manager = Pass3JobManager()
    return _job_manager


# =============================================================================
# Main Worker Function - Execute Pass 3 with Progress
# =============================================================================

def execute_pass3_job(job_id: str):
    """
    Fonction worker RQ: Exécute Pass 3 (Semantic Consolidation) avec progression.

    Args:
        job_id: ID du job à exécuter
    """
    from knowbase.api.services.pass2_service import get_pass2_service

    manager = get_pass3_job_manager()
    state = manager.get_job(job_id)

    if not state:
        logger.error(f"[Pass3Worker] Job {job_id} not found")
        return

    if state.status == Pass3JobStatus.CANCELLED:
        logger.info(f"[Pass3Worker] Job {job_id} was cancelled, skipping")
        return

    manager.start_job(job_id)

    try:
        service = get_pass2_service(state.tenant_id)

        # Mise à jour progression: démarrage
        manager.update_progress(
            job_id,
            current_phase="SEMANTIC_CONSOLIDATION",
            message="Starting semantic consolidation..."
        )

        # Exécution de la consolidation sémantique
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

        try:
            result = loop.run_until_complete(
                service.run_semantic_consolidation(
                    document_id=state.document_id,
                    max_candidates=state.max_candidates
                )
            )
        finally:
            loop.close()

        if manager.is_cancelled(job_id):
            return

        # Mise à jour finale
        manager.update_progress(
            job_id,
            items_processed=result.items_processed,
            items_total=result.items_processed,
            items_created=result.items_created,
            message=f"Completed: {result.items_created} proven relations"
        )

        result_dict = {
            "success": result.success,
            "phase": result.phase,
            "items_processed": result.items_processed,
            "items_created": result.items_created,
            "items_updated": result.items_updated,
            "execution_time_ms": result.execution_time_ms,
            "errors": result.errors,
            "details": result.details
        }

        manager.complete_job(job_id, result_dict)
        logger.info(f"[Pass3Worker] Job {job_id} completed: {result.items_created} relations created")

    except Exception as e:
        logger.exception(f"[Pass3Worker] Job {job_id} failed")
        manager.fail_job(job_id, str(e))


def enqueue_pass3_job(
    tenant_id: str = "default",
    document_id: Optional[str] = None,
    max_candidates: int = 50,
    created_by: str = "admin"
) -> Pass3JobState:
    """
    Crée et enqueue un job Pass3.

    Args:
        tenant_id: ID du tenant
        document_id: Optionnel - filtrer par document
        max_candidates: Nombre max de candidats par document
        created_by: Email du créateur

    Returns:
        Pass3JobState avec job_id pour suivi
    """
    manager = get_pass3_job_manager()

    state = manager.create_job(
        tenant_id=tenant_id,
        document_id=document_id,
        max_candidates=max_candidates,
        created_by=created_by
    )

    settings = get_settings()
    redis_url = f"redis://{settings.redis_host}:{settings.redis_port}/0"
    redis_conn = redis.from_url(redis_url)
    queue = Queue("ingestion", connection=redis_conn)

    queue.enqueue(
        execute_pass3_job,
        state.job_id,
        job_timeout="2h",
        result_ttl=86400,
        job_id=f"rq_{state.job_id}"
    )

    logger.info(f"[Pass3Jobs] Enqueued job {state.job_id}")
    return state


__all__ = [
    "Pass3JobStatus",
    "Pass3JobProgress",
    "Pass3JobState",
    "Pass3JobManager",
    "get_pass3_job_manager",
    "execute_pass3_job",
    "enqueue_pass3_job",
]
