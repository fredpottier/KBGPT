"""V5 SSE endpoint — Mode A streaming (S5.5).

ADR V1.5 §3h Mode A : Server-Sent Events pour UX chat interactive.

Format SSE :
    event: <type>
    data: <json>

    (ligne vide entre events)

Types d'events :
- plan : plan généré (1ère iter sur shapes complexes)
- tool_call : un tool appelé (iter, tool, args, evidence_gain)
- section_read : section lue (section_id, title, excerpt, doc_id)
- draft_answer : draft answer composé (text, citations)
- verifier_pending : verifier en cours
- complete : final answer + metrics
- error : erreur structurée

Cancellation native : si le client ferme la connexion (StreamingResponse
détecte disconnect), le token est cancel et l'agent stoppe à la prochaine iter.

Backend :
- Streamer interface : async generator qui yield SSE events
- StreamingJobRunner : variant de JobRunner qui yield events au lieu de retourner
  un AnswerResponse final
"""
from __future__ import annotations

import asyncio
import json
import logging
from typing import Annotated, AsyncIterator, Optional

from fastapi import APIRouter, Header, HTTPException
from fastapi.responses import StreamingResponse, JSONResponse

from knowbase.runtime_v5.agent.cancellation import CancellationRequested, CancellationToken
from knowbase.runtime_v5.api.admission import (
    AdmissionController,
    CircuitBreakerOpen,
    ConcurrencyBudgetExceeded,
    DailyQuotaExceeded,
    RateLimitExceeded,
)
from knowbase.runtime_v5.api.models import (
    AnswerRequest,
    ErrorDetail,
    ErrorResponse,
    ErrorType,
    SSEEventComplete,
    SSEEventError,
    SSEEventType,
    http_status_for_error,
)

logger = logging.getLogger(__name__)


# ─── Streamer protocol ───────────────────────────────────────────────────────


class StreamingJobRunner:
    """Interface streaming : yield SSE events au fil de l'eau.

    Production : implémentation qui wrappe ReasoningAgentV51 et émet events
    sur les hooks (plan, tool_call, section_read, ...).
    Tests : MockStreamingRunner qui yield events scriptés.
    """

    async def stream(
        self,
        request_id: str,
        tenant_id: str,
        request: AnswerRequest,
        cancellation_token: CancellationToken,
    ) -> AsyncIterator[tuple[SSEEventType, dict]]:
        """Yield (event_type, payload_dict) pairs au fil de l'eau.

        Doit yield un event `complete` ou `error` en dernier (terminal).
        Doit checker `cancellation_token` régulièrement.
        """
        raise NotImplementedError
        yield  # unreachable, marker pour async generator


# ─── SSE formatting ──────────────────────────────────────────────────────────


def _format_sse(event_type: str, payload: dict) -> str:
    """Format un event SSE conforme spec.

    'event: <type>\ndata: <json>\n\n'
    """
    data_json = json.dumps(payload, ensure_ascii=False, default=str)
    return f"event: {event_type}\ndata: {data_json}\n\n"


# ─── Router factory ──────────────────────────────────────────────────────────


def create_sse_router(
    admission: AdmissionController,
    streaming_runner: StreamingJobRunner,
) -> APIRouter:
    """Crée un APIRouter qui expose POST /api/runtime_v5/answer?stream=true."""
    router = APIRouter(prefix="/api/runtime_v5", tags=["runtime_v5_sse"])

    def _error_sse_response(
        error_type: ErrorType,
        message: str,
    ) -> JSONResponse:
        """Erreurs pré-stream → renvoyées en JSON normal (pas SSE)."""
        payload = ErrorResponse(
            error=ErrorDetail.from_type(error_type, message),
        )
        return JSONResponse(
            status_code=http_status_for_error(error_type),
            content=payload.model_dump(mode="json"),
        )

    @router.post("/answer/stream")
    async def stream_answer(
        request: AnswerRequest,
        x_tenant_id: Annotated[Optional[str], Header(alias="X-Tenant-ID")] = None,
    ):
        """POST /api/runtime_v5/answer/stream → text/event-stream.

        Validation + admission AVANT d'ouvrir le stream. En cas d'erreur
        de validation/admission, retourne JSON (pas SSE).
        """
        # 1. Validate tenant header
        if not x_tenant_id or not x_tenant_id.strip():
            return _error_sse_response(
                ErrorType.UNAUTHORIZED, "missing X-Tenant-ID header",
            )
        tenant_id = x_tenant_id.strip()

        # 2. Admission check (avant d'ouvrir le stream)
        try:
            admission.admit(
                tenant_id=tenant_id,
                answer_shape=request.answer_shape_hint,
            )
        except RateLimitExceeded as e:
            return _error_sse_response(
                ErrorType.RATE_LIMIT_EXCEEDED, str(e),
            )
        except DailyQuotaExceeded as e:
            return _error_sse_response(
                ErrorType.RATE_LIMIT_EXCEEDED, str(e),
            )
        except ConcurrencyBudgetExceeded as e:
            return _error_sse_response(
                ErrorType.CONCURRENCY_BUDGET_EXCEEDED, str(e),
            )
        except CircuitBreakerOpen as e:
            return _error_sse_response(
                ErrorType.PROVIDER_FAILOVER_IN_PROGRESS, str(e),
            )

        # 3. Generate request_id + cancellation token
        import uuid
        request_id = f"req_{uuid.uuid4().hex[:16]}"
        cancellation = CancellationToken()

        # 4. Stream generator
        async def _event_generator() -> AsyncIterator[bytes]:
            try:
                async for event_type, payload in streaming_runner.stream(
                    request_id=request_id,
                    tenant_id=tenant_id,
                    request=request,
                    cancellation_token=cancellation,
                ):
                    # Send each event
                    yield _format_sse(event_type.value, payload).encode("utf-8")
            except CancellationRequested as ce:
                # Emit error event before closing
                err_payload = SSEEventError(
                    type=ErrorType.CLIENT_CANCELLED,
                    message=f"cancelled: {ce.reason}",
                    retryable=False,
                ).model_dump(mode="json")
                yield _format_sse(
                    SSEEventType.ERROR.value, err_payload,
                ).encode("utf-8")
            except Exception as e:
                # Emit error event for unexpected errors
                err_payload = SSEEventError(
                    type=ErrorType.INTERNAL_ERROR,
                    message=f"{type(e).__name__}: {e}",
                    retryable=True,
                ).model_dump(mode="json")
                yield _format_sse(
                    SSEEventType.ERROR.value, err_payload,
                ).encode("utf-8")
            finally:
                admission.release_concurrency_slot(tenant_id)

        return StreamingResponse(
            _event_generator(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "X-Accel-Buffering": "no",  # nginx hint : no buffering
                "X-Request-ID": request_id,
            },
        )

    return router
