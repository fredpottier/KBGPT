"""V5 API router FastAPI — endpoints async mode B (S5.4).

ADR V1.5 §3h Mode B :
- POST /api/runtime_v5/answer?async=true → 202 + request_id
- GET  /api/runtime_v5/answer/{request_id}
- POST /api/runtime_v5/answer/{request_id}/cancel

Mode A (SSE streaming) : à brancher en S5.5.

Auth : middleware existant `src/knowbase/api/auth/` à brancher en S5.6 final.
Pour S5.4 : header X-Tenant-ID requis (validation in-router).
"""
from __future__ import annotations

import asyncio
import logging
from typing import Annotated, Optional

from fastapi import APIRouter, Header, HTTPException, Request, Response
from fastapi.responses import JSONResponse

from knowbase.runtime_v5.agent.cancellation import CancellationToken
from knowbase.runtime_v5.api.admission import (
    AdmissionController,
    AdmissionError,
    CircuitBreakerOpen,
    ConcurrencyBudgetExceeded,
    DailyQuotaExceeded,
    RateLimitExceeded,
)
from knowbase.runtime_v5.api.idempotency import (
    IdempotencyConflict,
    IdempotencyStore,
)
from knowbase.runtime_v5.api.job_store import (
    CrossTenantAccessError,
    InMemoryJobStore,
    JobNotFoundError,
)
from knowbase.runtime_v5.api.models import (
    AnswerRequest,
    AnswerResponse,
    AsyncJobAccepted,
    AsyncJobCancelResponse,
    AsyncJobStatusResponse,
    EpistemicStatusAPI,
    ErrorDetail,
    ErrorResponse,
    ErrorType,
    JobStatus,
    ResponseMetrics,
    http_status_for_error,
)

logger = logging.getLogger(__name__)


# ─── Job runner protocol ─────────────────────────────────────────────────────


class JobRunner:
    """Interface pour lancer un job en arrière-plan.

    Implémentation production : asyncio.create_task() qui appelle ReasoningAgentV51.
    Implémentation tests : MockJobRunner (qui appelle direct + scriptable).
    """

    async def execute(
        self,
        request_id: str,
        tenant_id: str,
        request: AnswerRequest,
        cancellation_token: CancellationToken,
    ) -> AnswerResponse:
        """À implémenter : exec ReasoningAgentV51 + retourner AnswerResponse."""
        raise NotImplementedError


# ─── Router factory ──────────────────────────────────────────────────────────


def create_router(
    admission: AdmissionController,
    idempotency: IdempotencyStore,
    job_store: InMemoryJobStore,
    job_runner: JobRunner,
    workspace_url_template: str = "/admin/workspaces/{request_id}",
) -> APIRouter:
    """Crée un APIRouter V5 lié aux dépendances injectées.

    Permet l'isolation pour les tests (mock everything).
    """
    router = APIRouter(prefix="/api/runtime_v5", tags=["runtime_v5"])

    # ─── Helpers internes ────────────────────────────────────────────────────

    def _error_response(
        error_type: ErrorType,
        message: str,
        request_id: Optional[str] = None,
        details: Optional[dict] = None,
    ) -> JSONResponse:
        status_code = http_status_for_error(error_type)
        payload = ErrorResponse(
            error=ErrorDetail.from_type(error_type, message, details=details),
            request_id=request_id,
        )
        return JSONResponse(
            status_code=status_code,
            content=payload.model_dump(mode="json"),
        )

    def _check_tenant_header(x_tenant_id: Optional[str]) -> Optional[JSONResponse]:
        if not x_tenant_id or not x_tenant_id.strip():
            return _error_response(
                ErrorType.UNAUTHORIZED,
                "missing X-Tenant-ID header",
            )
        return None

    async def _run_job_background(
        request_id: str,
        tenant_id: str,
        request: AnswerRequest,
        idempotency_key: Optional[str],
        request_payload: dict,
    ):
        """Tâche async exécutée en arrière-plan."""
        try:
            job_store.update_status(request_id, JobStatus.RUNNING)
            job_record = job_store.get(request_id, tenant_id)
            try:
                result = await job_runner.execute(
                    request_id=request_id,
                    tenant_id=tenant_id,
                    request=request,
                    cancellation_token=job_record.cancellation_token,
                )
                job_store.complete(request_id, result)
                if idempotency_key:
                    idempotency.save_completed(
                        tenant_id, idempotency_key, result.model_dump(mode="json"),
                    )
            except Exception as e:
                # Map known exceptions to ErrorType
                err = ErrorDetail.from_type(
                    ErrorType.INTERNAL_ERROR,
                    message=f"{type(e).__name__}: {e}",
                )
                job_store.fail(request_id, err)
                if idempotency_key:
                    idempotency.save_failed(
                        tenant_id, idempotency_key,
                        ErrorResponse(error=err, request_id=request_id).model_dump(mode="json"),
                    )
        finally:
            admission.release_concurrency_slot(tenant_id)

    # ─── POST /answer?async=true ─────────────────────────────────────────────

    @router.post(
        "/answer",
        responses={
            202: {"model": AsyncJobAccepted},
            400: {"model": ErrorResponse},
            401: {"model": ErrorResponse},
            409: {"model": ErrorResponse},
            429: {"model": ErrorResponse},
            502: {"model": ErrorResponse},
        },
    )
    async def post_answer(
        request: AnswerRequest,
        x_tenant_id: Annotated[Optional[str], Header(alias="X-Tenant-ID")] = None,
        x_idempotency_key: Annotated[Optional[str], Header(alias="X-Idempotency-Key")] = None,
        x_runtime_version: Annotated[Optional[str], Header(alias="X-Runtime-Version")] = None,
        async_mode: bool = False,
    ):
        """POST /api/runtime_v5/answer."""
        err = _check_tenant_header(x_tenant_id)
        if err:
            return err
        tenant_id = x_tenant_id.strip()

        # Idempotency check
        payload_dict = request.model_dump(mode="json")
        try:
            # Reserve provisoirement avec un request_id temporaire — on l'écrasera
            pre_request_id = "pending_" + tenant_id
            is_new, existing = idempotency.check_or_reserve(
                tenant_id=tenant_id,
                idempotency_key=x_idempotency_key or "",
                request_payload=payload_dict,
                request_id=pre_request_id,
            )
        except IdempotencyConflict as ic:
            return _error_response(
                ErrorType.IDEMPOTENCY_CONFLICT,
                str(ic),
                details={"key": ic.key},
            )

        # Si déjà cached → retourne
        if not is_new and existing is not None and existing.status.value == "completed":
            cached = idempotency.get_cached_response(tenant_id, x_idempotency_key)
            if cached:
                return JSONResponse(status_code=202, content=cached)

        # Admission control
        try:
            admission.admit(
                tenant_id=tenant_id,
                answer_shape=request.answer_shape_hint,
            )
        except RateLimitExceeded as e:
            return _error_response(
                ErrorType.RATE_LIMIT_EXCEEDED, str(e),
                details={"retry_after_s": e.retry_after_s},
            )
        except DailyQuotaExceeded as e:
            return _error_response(
                ErrorType.RATE_LIMIT_EXCEEDED, str(e),
                details={"retry_after_s": e.retry_after_s},
            )
        except ConcurrencyBudgetExceeded as e:
            return _error_response(
                ErrorType.CONCURRENCY_BUDGET_EXCEEDED, str(e),
            )
        except CircuitBreakerOpen as e:
            return _error_response(
                ErrorType.PROVIDER_FAILOVER_IN_PROGRESS, str(e),
                details={"retry_after_s": e.retry_after_s},
            )
        except AdmissionError as e:
            return _error_response(ErrorType.INTERNAL_ERROR, str(e))

        # Create job
        job = job_store.create(tenant_id=tenant_id)
        # Launch background task
        asyncio.create_task(_run_job_background(
            request_id=job.request_id,
            tenant_id=tenant_id,
            request=request,
            idempotency_key=x_idempotency_key,
            request_payload=payload_dict,
        ))

        accepted = AsyncJobAccepted(
            request_id=job.request_id,
            status=JobStatus.QUEUED,
            status_url=f"/api/runtime_v5/answer/{job.request_id}",
        )
        return JSONResponse(
            status_code=202,
            content=accepted.model_dump(mode="json"),
        )

    # ─── GET /answer/{request_id} ────────────────────────────────────────────

    @router.get(
        "/answer/{request_id}",
        responses={
            200: {"model": AsyncJobStatusResponse},
            401: {"model": ErrorResponse},
            403: {"model": ErrorResponse},
            404: {"model": ErrorResponse},
        },
    )
    async def get_answer_status(
        request_id: str,
        x_tenant_id: Annotated[Optional[str], Header(alias="X-Tenant-ID")] = None,
    ):
        err = _check_tenant_header(x_tenant_id)
        if err:
            return err
        tenant_id = x_tenant_id.strip()

        try:
            job = job_store.get(request_id, tenant_id)
        except JobNotFoundError:
            return _error_response(
                ErrorType.NOT_FOUND,
                f"request_id '{request_id}' not found",
                request_id=request_id,
            )
        except CrossTenantAccessError:
            return _error_response(
                ErrorType.CROSS_TENANT_DENIED,
                f"request_id '{request_id}' belongs to another tenant",
                request_id=request_id,
            )

        resp = AsyncJobStatusResponse(
            request_id=job.request_id,
            status=job.status,
            partial=job.partial,
            result=job.result,
            error=job.error,
            created_at=job.created_at,
            updated_at=job.updated_at,
        )
        return JSONResponse(
            status_code=200, content=resp.model_dump(mode="json"),
        )

    # ─── POST /answer/{request_id}/cancel ───────────────────────────────────

    @router.post(
        "/answer/{request_id}/cancel",
        responses={
            200: {"model": AsyncJobCancelResponse},
            401: {"model": ErrorResponse},
            403: {"model": ErrorResponse},
            404: {"model": ErrorResponse},
        },
    )
    async def cancel_answer(
        request_id: str,
        x_tenant_id: Annotated[Optional[str], Header(alias="X-Tenant-ID")] = None,
    ):
        err = _check_tenant_header(x_tenant_id)
        if err:
            return err
        tenant_id = x_tenant_id.strip()

        try:
            cancelled = job_store.cancel(request_id, tenant_id, reason="api_cancel")
        except JobNotFoundError:
            return _error_response(
                ErrorType.NOT_FOUND,
                f"request_id '{request_id}' not found",
                request_id=request_id,
            )
        except CrossTenantAccessError:
            return _error_response(
                ErrorType.CROSS_TENANT_DENIED,
                f"request_id '{request_id}' belongs to another tenant",
                request_id=request_id,
            )

        # Best-effort metrics from partial
        tokens_consumed = 0
        if cancelled.partial:
            tokens_consumed = cancelled.partial.n_tool_calls_so_far * 100  # estimation grossière

        resp = AsyncJobCancelResponse(
            request_id=cancelled.request_id,
            status=cancelled.status,
            tokens_consumed=tokens_consumed,
            cost_estimated=0.0,
        )
        return JSONResponse(
            status_code=200, content=resp.model_dump(mode="json"),
        )

    return router
