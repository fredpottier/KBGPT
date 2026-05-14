"""V5 JobStore — état des async jobs.

Backend in-memory pour tests + dev. Production : RedisJobStore (futur, hors S5.4).

Lifecycle :
    QUEUED → RUNNING → (VERIFYING) → COMPLETED / FAILED / CANCELLED
"""
from __future__ import annotations

import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

from knowbase.runtime_v5.agent.cancellation import CancellationToken
from knowbase.runtime_v5.api.models import (
    AnswerResponse,
    AsyncJobPartial,
    ErrorDetail,
    JobStatus,
)


@dataclass
class JobRecord:
    """État d'un job async."""
    request_id: str
    tenant_id: str
    status: JobStatus
    cancellation_token: CancellationToken
    partial: AsyncJobPartial = field(default_factory=AsyncJobPartial)
    result: Optional[AnswerResponse] = None
    error: Optional[ErrorDetail] = None
    created_at: datetime = field(default_factory=datetime.utcnow)
    updated_at: datetime = field(default_factory=datetime.utcnow)


class JobNotFoundError(Exception):
    pass


class CrossTenantAccessError(Exception):
    pass


class InMemoryJobStore:
    """JobStore in-memory thread-safe (singleton process)."""

    def __init__(self):
        self._lock = threading.RLock()
        self._jobs: dict[str, JobRecord] = {}

    # ─── CRUD ────────────────────────────────────────────────────────────────

    def create(
        self,
        tenant_id: str,
        cancellation_token: Optional[CancellationToken] = None,
    ) -> JobRecord:
        """Crée un job QUEUED."""
        with self._lock:
            request_id = f"req_{uuid.uuid4().hex[:16]}"
            job = JobRecord(
                request_id=request_id,
                tenant_id=tenant_id,
                status=JobStatus.QUEUED,
                cancellation_token=cancellation_token or CancellationToken(),
            )
            self._jobs[request_id] = job
            return job

    def get(self, request_id: str, tenant_id: str) -> JobRecord:
        """Récupère un job + check tenant ownership.

        Raises:
            JobNotFoundError si request_id absent
            CrossTenantAccessError si tenant_id ne correspond pas
        """
        with self._lock:
            job = self._jobs.get(request_id)
            if job is None:
                raise JobNotFoundError(f"job {request_id} not found")
            if job.tenant_id != tenant_id:
                raise CrossTenantAccessError(
                    f"job {request_id} belongs to a different tenant"
                )
            return job

    def update_status(
        self,
        request_id: str,
        new_status: JobStatus,
    ) -> None:
        with self._lock:
            job = self._jobs.get(request_id)
            if job is None:
                raise JobNotFoundError(f"job {request_id} not found")
            job.status = new_status
            job.updated_at = datetime.utcnow()

    def update_partial(
        self,
        request_id: str,
        partial: AsyncJobPartial,
    ) -> None:
        with self._lock:
            job = self._jobs.get(request_id)
            if job is None:
                raise JobNotFoundError(f"job {request_id} not found")
            job.partial = partial
            job.updated_at = datetime.utcnow()

    def complete(
        self,
        request_id: str,
        result: AnswerResponse,
    ) -> None:
        with self._lock:
            job = self._jobs.get(request_id)
            if job is None:
                raise JobNotFoundError(f"job {request_id} not found")
            job.status = JobStatus.COMPLETED
            job.result = result
            job.updated_at = datetime.utcnow()

    def fail(
        self,
        request_id: str,
        error: ErrorDetail,
    ) -> None:
        with self._lock:
            job = self._jobs.get(request_id)
            if job is None:
                raise JobNotFoundError(f"job {request_id} not found")
            job.status = JobStatus.FAILED
            job.error = error
            job.updated_at = datetime.utcnow()

    def cancel(
        self,
        request_id: str,
        tenant_id: str,
        reason: str = "user_requested",
    ) -> JobRecord:
        """Cancel un job. Le token est trigged, le runner doit voir CancellationRequested.

        Returns:
            JobRecord mis à jour
        """
        with self._lock:
            job = self.get(request_id, tenant_id)
            if job.status not in (JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.CANCELLED):
                job.cancellation_token.cancel(reason=reason, source="api_cancel")
                job.status = JobStatus.CANCELLED
                job.updated_at = datetime.utcnow()
            return job

    # ─── Utility ─────────────────────────────────────────────────────────────

    def list_for_tenant(self, tenant_id: str, limit: int = 50) -> list[JobRecord]:
        """Liste les jobs d'un tenant (admin/cockpit)."""
        with self._lock:
            return [j for j in self._jobs.values() if j.tenant_id == tenant_id][:limit]

    def purge_old(self, max_age_s: int = 86400) -> int:
        """Supprime les jobs terminés depuis plus de max_age_s. Returns count purged."""
        with self._lock:
            now = datetime.utcnow()
            to_delete = []
            for rid, j in self._jobs.items():
                if j.status in (JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.CANCELLED):
                    age = (now - j.updated_at).total_seconds()
                    if age > max_age_s:
                        to_delete.append(rid)
            for rid in to_delete:
                del self._jobs[rid]
            return len(to_delete)

    def stats(self) -> dict:
        """Stats globales."""
        with self._lock:
            counts = {}
            for j in self._jobs.values():
                counts[j.status.value] = counts.get(j.status.value, 0) + 1
            return {
                "n_jobs_total": len(self._jobs),
                "by_status": counts,
            }


# ─── Singleton ───────────────────────────────────────────────────────────────


_default_store: Optional[InMemoryJobStore] = None
_default_lock = threading.RLock()


def get_default_job_store() -> InMemoryJobStore:
    global _default_store
    with _default_lock:
        if _default_store is None:
            _default_store = InMemoryJobStore()
        return _default_store


def reset_default_job_store() -> None:
    global _default_store
    with _default_lock:
        _default_store = None
