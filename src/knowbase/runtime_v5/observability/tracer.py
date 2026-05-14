"""V5 ObservabilityTracer — interface OTel-compatible (CH-52.7.2 / S6.2).

ADR V1.5 §3g : trace span hierarchy avec attributes PII-redacted.

Architecture :
    [Agent] → ObservabilityTracer.start_span("gen_ai.agent.answer")
              └─ Span.set_attribute(key, value) [redacted via PIIRedactor]
              └─ Span.add_event("plan_emitted", attrs)
              └─ Span.set_status(StatusCode.OK | ERROR)
              └─ Span.end()

Production : OTelTracer adapter (wraps opentelemetry SDK) — branchement S6.5.
Tests : InMemoryTracer (capture all spans pour assertions).
Default : NoOpTracer (zero overhead).

Span hierarchy ADR §3g :
    gen_ai.agent.answer (root)
        ├─ gen_ai.inference (LLM call per iter)
        ├─ gen_ai.execute_tool (tool exec per call)
        ├─ gen_ai.embeddings
        └─ verifier.check
"""
from __future__ import annotations

import logging
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, ContextManager, Optional, Protocol

from knowbase.runtime_v5.observability.pii import PIIRedactor

logger = logging.getLogger(__name__)


# ─── Status codes (OTel compat) ──────────────────────────────────────────────


class SpanStatus(str, Enum):
    UNSET = "unset"
    OK = "ok"
    ERROR = "error"


# ─── SpanEvent dataclass ─────────────────────────────────────────────────────


@dataclass
class SpanEvent:
    """Event interne au span (analogue OTel SpanEvent)."""
    name: str
    timestamp: float
    attributes: dict[str, Any] = field(default_factory=dict)


# ─── Span ────────────────────────────────────────────────────────────────────


@dataclass
class Span:
    """Représentation d'un span (compat OTel structural).

    Attributs sont PII-redacted automatiquement par le tracer parent
    (si redactor configuré).

    Pour la prod, on aura un OTelSpan qui délègue les méthodes à opentelemetry-sdk.
    """
    name: str
    span_id: str
    trace_id: str
    parent_id: Optional[str] = None
    start_time: float = 0.0
    end_time: Optional[float] = None
    attributes: dict[str, Any] = field(default_factory=dict)
    events: list[SpanEvent] = field(default_factory=list)
    status: SpanStatus = SpanStatus.UNSET
    status_message: str = ""

    def set_attribute(self, key: str, value: Any) -> None:
        self.attributes[key] = value

    def set_attributes(self, mapping: dict[str, Any]) -> None:
        self.attributes.update(mapping)

    def add_event(self, name: str, attributes: Optional[dict] = None) -> None:
        self.events.append(SpanEvent(
            name=name, timestamp=time.monotonic(),
            attributes=attributes or {},
        ))

    def set_status(self, status: SpanStatus, message: str = "") -> None:
        self.status = status
        if message:
            self.status_message = message

    def record_exception(self, exc: BaseException) -> None:
        """Enregistre une exception comme event + set status ERROR."""
        self.add_event("exception", {
            "exception.type": type(exc).__name__,
            "exception.message": str(exc),
        })
        self.set_status(SpanStatus.ERROR, message=f"{type(exc).__name__}: {exc}")

    def duration_ms(self) -> Optional[float]:
        if self.end_time is None:
            return None
        return (self.end_time - self.start_time) * 1000.0

    def end(self) -> None:
        if self.end_time is None:
            self.end_time = time.monotonic()


# ─── Tracer Protocol ─────────────────────────────────────────────────────────


class ObservabilityTracer(Protocol):
    """Interface tracer (OTel-compatible)."""

    def start_span(
        self,
        name: str,
        parent_span: Optional[Span] = None,
        attributes: Optional[dict[str, Any]] = None,
    ) -> Span:
        ...

    def end_span(self, span: Span) -> None:
        ...


# ─── NoOpTracer ──────────────────────────────────────────────────────────────


class NoOpTracer:
    """Tracer qui n'enregistre rien (overhead ~0). Default safe."""

    def start_span(
        self,
        name: str,
        parent_span: Optional[Span] = None,
        attributes: Optional[dict[str, Any]] = None,
    ) -> Span:
        return Span(
            name=name,
            span_id=f"sp_{uuid.uuid4().hex[:12]}",
            trace_id=(parent_span.trace_id if parent_span
                      else f"tr_{uuid.uuid4().hex[:16]}"),
            parent_id=parent_span.span_id if parent_span else None,
            start_time=time.monotonic(),
            attributes=dict(attributes or {}),
        )

    def end_span(self, span: Span) -> None:
        span.end()


# ─── InMemoryTracer (tests) ──────────────────────────────────────────────────


class InMemoryTracer:
    """Tracer qui capture tous les spans en mémoire pour assertions tests.

    Args:
        redactor : PIIRedactor optionnel (None = pas de redaction)
    """

    def __init__(self, redactor: Optional[PIIRedactor] = None):
        self.redactor = redactor
        self.spans: list[Span] = []
        self.active_spans: dict[str, Span] = {}  # span_id → span (en cours)

    def start_span(
        self,
        name: str,
        parent_span: Optional[Span] = None,
        attributes: Optional[dict[str, Any]] = None,
    ) -> Span:
        # Generate IDs
        if parent_span is None:
            trace_id = f"tr_{uuid.uuid4().hex[:16]}"
            parent_id = None
        else:
            trace_id = parent_span.trace_id
            parent_id = parent_span.span_id

        # PII redact attributes
        attrs = dict(attributes or {})
        if self.redactor and attrs:
            attrs = self.redactor.redact_dict(attrs)

        span = Span(
            name=name,
            span_id=f"sp_{uuid.uuid4().hex[:12]}",
            trace_id=trace_id,
            parent_id=parent_id,
            start_time=time.monotonic(),
            attributes=attrs,
        )
        self.active_spans[span.span_id] = span
        return span

    def end_span(self, span: Span) -> None:
        span.end()
        # PII redact events attributes too (post-update)
        if self.redactor:
            for ev in span.events:
                if ev.attributes:
                    ev.attributes = self.redactor.redact_dict(ev.attributes)
            # Re-redact final attributes
            span.attributes = self.redactor.redact_dict(span.attributes)
        self.active_spans.pop(span.span_id, None)
        self.spans.append(span)

    # ─── Helpers tests ───────────────────────────────────────────────────────

    def get_spans_by_name(self, name: str) -> list[Span]:
        return [s for s in self.spans if s.name == name]

    def get_root_spans(self) -> list[Span]:
        return [s for s in self.spans if s.parent_id is None]

    def get_children(self, parent: Span) -> list[Span]:
        return [s for s in self.spans if s.parent_id == parent.span_id]

    def reset(self) -> None:
        self.spans = []
        self.active_spans = {}


# ─── Context-manager helper (recommandé) ─────────────────────────────────────


class SpanContext:
    """Context manager pour span auto-end + record_exception.

    Usage :
        with SpanContext(tracer, "gen_ai.agent.answer", attributes={...}) as span:
            ... work ...
            span.set_attribute("output_tokens", N)
    """

    def __init__(
        self,
        tracer: ObservabilityTracer,
        name: str,
        parent_span: Optional[Span] = None,
        attributes: Optional[dict[str, Any]] = None,
    ):
        self.tracer = tracer
        self.name = name
        self.parent_span = parent_span
        self.attributes = attributes
        self.span: Optional[Span] = None

    def __enter__(self) -> Span:
        self.span = self.tracer.start_span(
            name=self.name,
            parent_span=self.parent_span,
            attributes=self.attributes,
        )
        return self.span

    def __exit__(self, exc_type, exc_val, exc_tb) -> bool:
        if self.span is None:
            return False
        if exc_val is not None:
            self.span.record_exception(exc_val)
        elif self.span.status == SpanStatus.UNSET:
            self.span.set_status(SpanStatus.OK)
        self.tracer.end_span(self.span)
        return False  # propagate exception


# ─── Singleton ───────────────────────────────────────────────────────────────


_default_tracer: Optional[ObservabilityTracer] = None


def get_default_tracer() -> ObservabilityTracer:
    global _default_tracer
    if _default_tracer is None:
        _default_tracer = NoOpTracer()
    return _default_tracer


def set_default_tracer(tracer: ObservabilityTracer) -> None:
    global _default_tracer
    _default_tracer = tracer


def reset_default_tracer() -> None:
    global _default_tracer
    _default_tracer = None
