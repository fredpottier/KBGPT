"""
JobManager Redis-backed — P4.1.

Persiste l'état de chaque doc d'ingestion dans Redis avec TTL 24h.
Permet la reprise au démarrage du worker via list_active_jobs().

Pattern de clés : `osmose:ingest:job:{doc_id}` → JSON JobState
TTL : 86400s (24h) refreshé à chaque update_state.

Cohérent avec le pattern existant `osmose:burst:state` et `osmose:claimfirst:state`.
"""
from __future__ import annotations

import json
import logging
import os
from datetime import datetime
from typing import Optional

import redis as _redis

from knowbase.ingestion.resilience.job_state import (
    JobCheckpoint,
    JobState,
    JobStateEnum,
)

logger = logging.getLogger(__name__)


KEY_PREFIX = "osmose:ingest:job:"
DEFAULT_TTL_SECONDS = 86400  # 24h


class JobManager:
    """JobManager Redis-backed pour la résilience ingestion (P4.1).

    Args:
        redis_client: Redis client (optionnel, sinon connect localhost)
        ttl_seconds: TTL Redis (default 24h)
    """

    def __init__(
        self,
        redis_client: Optional[_redis.Redis] = None,
        ttl_seconds: int = DEFAULT_TTL_SECONDS,
        host: str = "redis",
        port: int = 6379,
    ) -> None:
        self.redis = redis_client or _redis.Redis(host=host, port=port, password=os.getenv("REDIS_PASSWORD") or None, decode_responses=True)
        self.ttl_seconds = ttl_seconds

    def _key(self, doc_id: str) -> str:
        return f"{KEY_PREFIX}{doc_id}"

    def create_job(self, doc_id: str, file_path: str, metadata: Optional[dict] = None) -> JobState:
        """Crée un nouveau job. Si le doc_id existe en state=processing → erreur.

        Returns le JobState créé.
        """
        existing = self.get_state(doc_id)
        if existing and existing.state == JobStateEnum.PROCESSING:
            raise ValueError(
                f"Job {doc_id} already exists in state=processing (started {existing.started_at})"
            )

        job = JobState(
            doc_id=doc_id,
            file_path=file_path,
            state=JobStateEnum.PENDING,
            metadata=metadata or {},
        )
        self._persist(job)
        logger.info("[JobManager] Created job: doc_id=%s file=%s", doc_id, file_path)
        return job

    def update_state(
        self,
        doc_id: str,
        state: JobStateEnum,
        checkpoint: Optional[JobCheckpoint] = None,
        error: Optional[str] = None,
    ) -> JobState:
        """Met à jour l'état + checkpoint optionnel. Refresh TTL."""
        job = self.get_state(doc_id)
        if job is None:
            raise ValueError(f"Job {doc_id} not found")
        job.state = state
        job.updated_at = datetime.utcnow().isoformat() + "Z"
        if checkpoint is not None:
            job.last_checkpoint = checkpoint
        if error is not None:
            job.error = error
        self._persist(job)
        return job

    def get_state(self, doc_id: str) -> Optional[JobState]:
        """Récupère l'état actuel ou None si pas trouvé."""
        raw = self.redis.get(self._key(doc_id))
        if raw is None:
            return None
        try:
            data = json.loads(raw)
            return JobState(**data)
        except (json.JSONDecodeError, ValueError) as exc:
            logger.warning("[JobManager] Corrupt state for %s: %s", doc_id, exc)
            return None

    def list_active_jobs(self) -> list[JobState]:
        """Tous les jobs avec state ∈ {pending, processing, post_import, paused}.

        Used at worker startup to detect interrupted jobs and trigger resumption.
        """
        active_states = {
            JobStateEnum.PENDING,
            JobStateEnum.PROCESSING,
            JobStateEnum.POST_IMPORT,
            JobStateEnum.PAUSED,
        }
        result = []
        # SCAN car KEYS est bloquant en prod
        for key in self.redis.scan_iter(match=f"{KEY_PREFIX}*"):
            raw = self.redis.get(key)
            if raw is None:
                continue
            try:
                job = JobState(**json.loads(raw))
                if job.state in active_states:
                    result.append(job)
            except (json.JSONDecodeError, ValueError):
                continue
        return result

    def cleanup_stale(self, ttl_hours: int = 48) -> int:
        """Supprime les jobs failed older than ttl_hours.

        Returns le count supprimé.
        """
        from datetime import timedelta
        cutoff = datetime.utcnow() - timedelta(hours=ttl_hours)
        n_deleted = 0
        for key in self.redis.scan_iter(match=f"{KEY_PREFIX}*"):
            raw = self.redis.get(key)
            if raw is None:
                continue
            try:
                job = JobState(**json.loads(raw))
            except (json.JSONDecodeError, ValueError):
                continue
            if job.state != JobStateEnum.FAILED:
                continue
            try:
                updated = datetime.fromisoformat(job.updated_at.rstrip("Z"))
                if updated < cutoff:
                    self.redis.delete(key)
                    n_deleted += 1
            except ValueError:
                continue
        if n_deleted:
            logger.info("[JobManager] Cleaned %d stale failed jobs", n_deleted)
        return n_deleted

    def delete_job(self, doc_id: str) -> bool:
        """Supprime un job (utiliser avec prudence)."""
        return bool(self.redis.delete(self._key(doc_id)))

    def _persist(self, job: JobState) -> None:
        """SETEX avec TTL refresh."""
        self.redis.setex(
            self._key(job.doc_id),
            self.ttl_seconds,
            job.model_dump_json(),
        )
