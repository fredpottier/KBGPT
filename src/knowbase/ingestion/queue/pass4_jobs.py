"""
Pass 4 Background Jobs for RQ Queue.

Système de jobs async pour Pass 4:
- Pass 4a: Entity Resolution (CORPUS_ER)
- Pass 4b: Corpus Links (CO_OCCURS_IN_CORPUS)

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

class Pass4JobStatus(str, Enum):
    """États possibles d'un job Pass4."""
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass
class Pass4JobProgress:
    """Progression d'un job Pass4."""
    current_phase: str = ""
    phase_index: int = 0
    total_phases: int = 2  # ER + Links
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
        data["current_batch"] = self.phase_index + 1
        data["total_batches"] = self.total_phases
        if self.total_phases > 0:
            data["percentage"] = ((self.phase_index + 1) / self.total_phases) * 100
        else:
            data["percentage"] = 0
        return data

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Pass4JobProgress":
        errors = data.get("errors") or []
        return cls(
            current_phase=data.get("current_phase", ""),
            phase_index=data.get("phase_index", 0),
            total_phases=data.get("total_phases", 2),
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
class Pass4JobState:
    """État complet d'un job Pass4."""
    job_id: str
    tenant_id: str
    status: Pass4JobStatus
    skip_er: bool = False
    skip_links: bool = False
    dry_run: bool = False
    progress: Pass4JobProgress = field(default_factory=Pass4JobProgress)
    phase_results: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    created_at: str = ""
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    created_by: str = "admin"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "job_id": self.job_id,
            "tenant_id": self.tenant_id,
            "status": self.status.value,
            "skip_er": self.skip_er,
            "skip_links": self.skip_links,
            "dry_run": self.dry_run,
            "progress": self.progress.to_dict(),
            "phase_results": self.phase_results,
            "created_at": self.created_at,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "created_by": self.created_by
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Pass4JobState":
        return cls(
            job_id=data["job_id"],
            tenant_id=data.get("tenant_id", "default"),
            status=Pass4JobStatus(data.get("status", "pending")),
            skip_er=data.get("skip_er", False),
            skip_links=data.get("skip_links", False),
            dry_run=data.get("dry_run", False),
            progress=Pass4JobProgress.from_dict(data.get("progress", {})),
            phase_results=data.get("phase_results", {}),
            created_at=data.get("created_at", ""),
            started_at=data.get("started_at"),
            completed_at=data.get("completed_at"),
            created_by=data.get("created_by", "admin")
        )


class Pass4JobManager:
    """Gestionnaire des jobs Pass4 avec persistance Redis."""

    REDIS_PREFIX = "pass4:job:"
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
        skip_er: bool = False,
        skip_links: bool = False,
        dry_run: bool = False,
        created_by: str = "admin"
    ) -> Pass4JobState:
        """Crée un nouveau job Pass4."""
        job_id = f"p4_{uuid.uuid4().hex[:12]}"
        now = datetime.utcnow().isoformat() + "Z"

        # Calculer le nombre de phases
        total_phases = 0
        if not skip_er:
            total_phases += 1
        if not skip_links:
            total_phases += 1

        state = Pass4JobState(
            job_id=job_id,
            tenant_id=tenant_id,
            status=Pass4JobStatus.PENDING,
            skip_er=skip_er,
            skip_links=skip_links,
            dry_run=dry_run,
            created_at=now,
            created_by=created_by
        )
        state.progress.total_phases = total_phases

        self._save_state(state)
        self._redis.lpush(self._list_key(tenant_id), job_id)
        self._redis.ltrim(self._list_key(tenant_id), 0, 99)

        logger.info(f"[Pass4JobManager] Created job {job_id}")
        return state

    def get_job(self, job_id: str) -> Optional[Pass4JobState]:
        """Récupère l'état d'un job."""
        data = self._redis.get(self._job_key(job_id))
        if not data:
            return None
        try:
            return Pass4JobState.from_dict(json.loads(data))
        except Exception as e:
            logger.error(f"[Pass4JobManager] Error parsing job {job_id}: {e}")
            return None

    def list_jobs(self, tenant_id: str = "default", limit: int = 20) -> List[Pass4JobState]:
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
        phase_index: Optional[int] = None,
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
        if phase_index is not None:
            state.progress.phase_index = phase_index
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

    def set_phase_result(self, job_id: str, phase: str, result: Dict[str, Any]):
        """Enregistre le résultat d'une phase."""
        state = self.get_job(job_id)
        if state:
            state.phase_results[phase] = result
            self._save_state(state)

    def start_job(self, job_id: str):
        """Marque un job comme démarré."""
        state = self.get_job(job_id)
        if state:
            state.status = Pass4JobStatus.RUNNING
            state.started_at = datetime.utcnow().isoformat() + "Z"
            state.progress.started_at = state.started_at
            self._save_state(state)
            logger.info(f"[Pass4JobManager] Job {job_id} started")

    def complete_job(self, job_id: str, phase_results: Optional[Dict] = None):
        """Marque un job comme terminé."""
        state = self.get_job(job_id)
        if state:
            state.status = Pass4JobStatus.COMPLETED
            state.completed_at = datetime.utcnow().isoformat() + "Z"
            if phase_results:
                state.phase_results = phase_results
            state.progress.last_message = "Pass 4 completed successfully"
            self._save_state(state)
            logger.info(f"[Pass4JobManager] Job {job_id} completed")

    def fail_job(self, job_id: str, error: str):
        """Marque un job comme échoué."""
        state = self.get_job(job_id)
        if state:
            state.status = Pass4JobStatus.FAILED
            state.completed_at = datetime.utcnow().isoformat() + "Z"
            state.progress.errors.append(error)
            state.progress.last_message = f"Failed: {error}"
            self._save_state(state)
            logger.error(f"[Pass4JobManager] Job {job_id} failed: {error}")

    def cancel_job(self, job_id: str) -> bool:
        """Annule un job."""
        state = self.get_job(job_id)
        if not state or state.status not in [Pass4JobStatus.PENDING, Pass4JobStatus.RUNNING]:
            return False

        state.status = Pass4JobStatus.CANCELLED
        state.completed_at = datetime.utcnow().isoformat() + "Z"
        state.progress.last_message = "Cancelled by user"
        self._save_state(state)
        logger.info(f"[Pass4JobManager] Job {job_id} cancelled")
        return True

    def is_cancelled(self, job_id: str) -> bool:
        """Vérifie si un job a été annulé."""
        state = self.get_job(job_id)
        return state.status == Pass4JobStatus.CANCELLED if state else False

    def _save_state(self, state: Pass4JobState):
        """Sauvegarde l'état dans Redis."""
        self._redis.setex(
            self._job_key(state.job_id),
            self.JOB_TTL_SECONDS,
            json.dumps(state.to_dict())
        )


# Singleton
_job_manager: Optional[Pass4JobManager] = None


def get_pass4_job_manager() -> Pass4JobManager:
    """Récupère l'instance singleton du gestionnaire."""
    global _job_manager
    if _job_manager is None:
        _job_manager = Pass4JobManager()
    return _job_manager


# =============================================================================
# Main Worker Function - Execute Pass 4 with Progress
# =============================================================================

def execute_pass4_job(job_id: str):
    """
    Fonction worker RQ: Exécute Pass 4 (Corpus Consolidation) avec progression.

    Pass 4a: Entity Resolution (CORPUS_ER)
    Pass 4b: Corpus Links (CO_OCCURS_IN_CORPUS)

    Args:
        job_id: ID du job à exécuter
    """
    from knowbase.api.services.pass2_service import get_pass2_service

    manager = get_pass4_job_manager()
    state = manager.get_job(job_id)

    if not state:
        logger.error(f"[Pass4Worker] Job {job_id} not found")
        return

    if state.status == Pass4JobStatus.CANCELLED:
        logger.info(f"[Pass4Worker] Job {job_id} was cancelled, skipping")
        return

    manager.start_job(job_id)

    try:
        service = get_pass2_service(state.tenant_id)
        phase_results = {}
        phase_index = 0

        # Phase 1: Entity Resolution (Pass 4a)
        if not state.skip_er and not manager.is_cancelled(job_id):
            manager.update_progress(
                job_id,
                current_phase="ENTITY_RESOLUTION",
                phase_index=phase_index,
                message="Running Entity Resolution..."
            )

            result = service.run_corpus_er(dry_run=state.dry_run)

            phase_results["entity_resolution"] = {
                "success": result.success,
                "items_processed": result.items_processed,
                "items_created": result.items_created,
                "items_updated": result.items_updated,
                "execution_time_ms": result.execution_time_ms,
                "details": result.details
            }
            manager.set_phase_result(job_id, "entity_resolution", phase_results["entity_resolution"])

            # Mise à jour progression
            auto_merges = result.details.get("auto_merges", 0) if result.details else 0
            proposals = result.details.get("proposals_created", 0) if result.details else 0
            manager.update_progress(
                job_id,
                items_processed=result.items_processed,
                items_created=result.items_created,
                message=f"ER: {auto_merges} merges, {proposals} proposals"
            )

            phase_index += 1
            logger.info(f"[Pass4Worker] ENTITY_RESOLUTION complete: {auto_merges} merges")

        # Phase 2: Corpus Links (Pass 4b)
        if not state.skip_links and not manager.is_cancelled(job_id):
            manager.update_progress(
                job_id,
                current_phase="CORPUS_LINKS",
                phase_index=phase_index,
                message="Creating corpus links..."
            )

            # Exécution async
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)

            try:
                result = loop.run_until_complete(service.run_corpus_links())
            finally:
                loop.close()

            phase_results["corpus_links"] = {
                "success": result.success,
                "items_processed": result.items_processed,
                "items_created": result.items_created,
                "execution_time_ms": result.execution_time_ms,
                "details": result.details
            }
            manager.set_phase_result(job_id, "corpus_links", phase_results["corpus_links"])

            manager.update_progress(
                job_id,
                items_processed=result.items_processed,
                items_created=result.items_created,
                message=f"Links: {result.items_created} CO_OCCURS created"
            )

            logger.info(f"[Pass4Worker] CORPUS_LINKS complete: {result.items_created} links")

        if manager.is_cancelled(job_id):
            return

        manager.complete_job(job_id, phase_results)
        logger.info(f"[Pass4Worker] Job {job_id} completed")

    except Exception as e:
        logger.exception(f"[Pass4Worker] Job {job_id} failed")
        manager.fail_job(job_id, str(e))


def enqueue_pass4_job(
    tenant_id: str = "default",
    skip_er: bool = False,
    skip_links: bool = False,
    dry_run: bool = False,
    created_by: str = "admin"
) -> Pass4JobState:
    """
    Crée et enqueue un job Pass4 (Corpus Consolidation).

    Args:
        tenant_id: ID du tenant
        skip_er: Ignorer Entity Resolution (Pass 4a)
        skip_links: Ignorer Corpus Links (Pass 4b)
        dry_run: Mode simulation pour ER
        created_by: Email du créateur

    Returns:
        Pass4JobState avec job_id pour suivi
    """
    manager = get_pass4_job_manager()

    state = manager.create_job(
        tenant_id=tenant_id,
        skip_er=skip_er,
        skip_links=skip_links,
        dry_run=dry_run,
        created_by=created_by
    )

    settings = get_settings()
    redis_url = f"redis://{settings.redis_host}:{settings.redis_port}/0"
    redis_conn = redis.from_url(redis_url)
    queue = Queue("ingestion", connection=redis_conn)

    queue.enqueue(
        execute_pass4_job,
        state.job_id,
        job_timeout="2h",
        result_ttl=86400,
        job_id=f"rq_{state.job_id}"
    )

    logger.info(f"[Pass4Jobs] Enqueued job {state.job_id}")
    return state


__all__ = [
    "Pass4JobStatus",
    "Pass4JobProgress",
    "Pass4JobState",
    "Pass4JobManager",
    "get_pass4_job_manager",
    "execute_pass4_job",
    "enqueue_pass4_job",
]
