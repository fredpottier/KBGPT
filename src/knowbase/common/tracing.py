"""
Distributed Tracing OpenTelemetry - Phase 0.5 P2.12

Tracing distribué pour observabilité:
- Tracer requêtes multi-services (API → Worker → LLM → Qdrant)
- Propagation context (trace_id, span_id) via headers
- Export vers Jaeger/Zipkin (configurable)

Usage:
    from knowbase.common.tracing import trace_operation

    @trace_operation(name="merge_entities")
    async def merge(canonical, candidates):
        # Span automatique créé
        return result

Configuration (.env):
    OTEL_ENABLED=true
    OTEL_SERVICE_NAME=sap-kb-api
    OTEL_EXPORTER=jaeger  # ou zipkin, console
    OTEL_JAEGER_ENDPOINT=http://jaeger:14268/api/traces
"""

import os
import logging
from functools import wraps
from typing import Callable, Any, Optional
from contextlib import contextmanager

logger = logging.getLogger(__name__)

# Configuration OpenTelemetry
OTEL_ENABLED = os.getenv("OTEL_ENABLED", "false").lower() == "true"
OTEL_SERVICE_NAME = os.getenv("OTEL_SERVICE_NAME", "sap-kb")
OTEL_EXPORTER = os.getenv("OTEL_EXPORTER", "console")  # jaeger, zipkin, console
OTEL_JAEGER_ENDPOINT = os.getenv(
    "OTEL_JAEGER_ENDPOINT", "http://jaeger:14268/api/traces"
)

# Import conditionnel OpenTelemetry (optionnel)
tracer = None
trace = None

if OTEL_ENABLED:
    try:
        from opentelemetry import trace as otel_trace
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.exporter.jaeger.thrift import JaegerExporter
        from opentelemetry.exporter.zipkin.json import ZipkinExporter
        from opentelemetry.sdk.trace.export import ConsoleSpanExporter

        # Créer provider avec resource
        resource = Resource.create({"service.name": OTEL_SERVICE_NAME})
        provider = TracerProvider(resource=resource)

        # Configurer exporter selon config
        if OTEL_EXPORTER == "jaeger":
            exporter = JaegerExporter(
                collector_endpoint=OTEL_JAEGER_ENDPOINT,
            )
        elif OTEL_EXPORTER == "zipkin":
            exporter = ZipkinExporter(
                endpoint=os.getenv("OTEL_ZIPKIN_ENDPOINT", "http://zipkin:9411/api/v2/spans")
            )
        else:
            # Console par défaut (dev)
            exporter = ConsoleSpanExporter()

        # Ajouter processor
        processor = BatchSpanProcessor(exporter)
        provider.add_span_processor(processor)

        # Définir provider global
        otel_trace.set_tracer_provider(provider)

        # Créer tracer
        tracer = otel_trace.get_tracer(__name__)
        trace = otel_trace

        logger.info(
            f"✅ OpenTelemetry enabled: {OTEL_SERVICE_NAME} → {OTEL_EXPORTER}"
        )

    except ImportError as e:
        logger.warning(
            f"⚠️ OpenTelemetry dependencies not installed: {e}. "
            "Tracing disabled. Install: pip install opentelemetry-api opentelemetry-sdk opentelemetry-exporter-jaeger"
        )
        OTEL_ENABLED = False
else:
    logger.info("OpenTelemetry disabled (OTEL_ENABLED=false)")


def trace_operation(name: str, attributes: Optional[dict] = None):
    """
    Décorateur pour tracer opération avec span

    Args:
        name: Nom span (ex: "canonicalization.merge")
        attributes: Attributs additionnels

    Usage:
        @trace_operation("merge_entities", {"tenant": "bouygues"})
        async def merge(...):
            return result
    """
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        async def async_wrapper(*args, **kwargs) -> Any:
            if not OTEL_ENABLED or not tracer:
                # Pas de tracing, exécuter directement
                return await func(*args, **kwargs)

            # Créer span
            with tracer.start_as_current_span(name) as span:
                # Ajouter attributs
                if attributes:
                    for key, value in attributes.items():
                        span.set_attribute(key, str(value))

                # Ajouter request_id si disponible
                try:
                    from knowbase.common.request_context import get_request_id
                    request_id = get_request_id()
                    if request_id:
                        span.set_attribute("request_id", request_id)
                except ImportError:
                    pass

                try:
                    result = await func(*args, **kwargs)
                    span.set_attribute("status", "success")
                    return result
                except Exception as e:
                    span.set_attribute("status", "error")
                    span.set_attribute("error.type", type(e).__name__)
                    span.set_attribute("error.message", str(e))
                    span.record_exception(e)
                    raise

        @wraps(func)
        def sync_wrapper(*args, **kwargs) -> Any:
            if not OTEL_ENABLED or not tracer:
                return func(*args, **kwargs)

            with tracer.start_as_current_span(name) as span:
                if attributes:
                    for key, value in attributes.items():
                        span.set_attribute(key, str(value))

                try:
                    from knowbase.common.request_context import get_request_id
                    request_id = get_request_id()
                    if request_id:
                        span.set_attribute("request_id", request_id)
                except ImportError:
                    pass

                try:
                    result = func(*args, **kwargs)
                    span.set_attribute("status", "success")
                    return result
                except Exception as e:
                    span.set_attribute("status", "error")
                    span.set_attribute("error.type", type(e).__name__)
                    span.set_attribute("error.message", str(e))
                    span.record_exception(e)
                    raise

        # Retourner wrapper approprié
        import asyncio
        if asyncio.iscoroutinefunction(func):
            return async_wrapper
        return sync_wrapper

    return decorator


@contextmanager
def trace_span(name: str, attributes: Optional[dict] = None):
    """
    Context manager pour créer span manuel

    Usage:
        with trace_span("fetch_chunks", {"entity_id": entity_id}):
            chunks = fetch_from_qdrant(entity_id)
    """
    if not OTEL_ENABLED or not tracer:
        yield
        return

    with tracer.start_as_current_span(name) as span:
        if attributes:
            for key, value in attributes.items():
                span.set_attribute(key, str(value))

        try:
            yield span
        except Exception as e:
            span.set_attribute("status", "error")
            span.set_attribute("error.type", type(e).__name__)
            span.set_attribute("error.message", str(e))
            span.record_exception(e)
            raise


def get_trace_context() -> dict:
    """
    Récupérer contexte trace actuel (trace_id, span_id)

    Returns:
        {"trace_id": "...", "span_id": "..."}
    """
    if not OTEL_ENABLED or not trace:
        return {}

    span = trace.get_current_span()
    if not span or not span.get_span_context().is_valid:
        return {}

    ctx = span.get_span_context()
    return {
        "trace_id": format(ctx.trace_id, '032x'),
        "span_id": format(ctx.span_id, '016x'),
        "trace_flags": ctx.trace_flags
    }
