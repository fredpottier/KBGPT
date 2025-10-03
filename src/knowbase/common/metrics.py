"""
Métriques Prometheus - Phase 0.5 P2.11

Métriques business pour monitoring:
- Compteurs: merge_total, undo_total, bootstrap_total
- Histogrammes: merge_duration, backfill_duration
- Gauges: quarantine_queue_size, circuit_breaker_state

Usage:
    from knowbase.common.metrics import (
        merge_counter, merge_duration, record_merge
    )

    with merge_duration.time():
        result = do_merge()
    merge_counter.labels(status="success").inc()

Endpoint: GET /metrics (format Prometheus)
"""

from prometheus_client import Counter, Histogram, Gauge, generate_latest, REGISTRY
from prometheus_client import CollectorRegistry
import time
from functools import wraps
from typing import Callable

# Registry custom pour éviter conflits
registry = CollectorRegistry(auto_describe=True)

# Compteurs (count events)
merge_counter = Counter(
    'canonicalization_merge_total',
    'Total merge operations',
    ['status'],  # success, failed, rejected
    registry=registry
)

undo_counter = Counter(
    'canonicalization_undo_total',
    'Total undo operations',
    ['status'],
    registry=registry
)

bootstrap_counter = Counter(
    'canonicalization_bootstrap_total',
    'Total bootstrap operations',
    ['status'],
    registry=registry
)

# Histogrammes (latence/durée)
merge_duration = Histogram(
    'canonicalization_merge_duration_seconds',
    'Merge operation duration',
    buckets=[0.1, 0.5, 1.0, 2.0, 5.0, 10.0],
    registry=registry
)

backfill_duration = Histogram(
    'qdrant_backfill_duration_seconds',
    'Qdrant backfill duration',
    buckets=[1.0, 5.0, 10.0, 30.0, 60.0, 120.0],
    registry=registry
)

bootstrap_duration = Histogram(
    'canonicalization_bootstrap_duration_seconds',
    'Bootstrap operation duration',
    buckets=[10.0, 30.0, 60.0, 120.0, 300.0],
    registry=registry
)

# Gauges (état actuel)
quarantine_queue_size = Gauge(
    'canonicalization_quarantine_queue_size',
    'Number of merges in quarantine',
    registry=registry
)

circuit_breaker_state = Gauge(
    'circuit_breaker_state',
    'Circuit breaker state (0=closed, 1=open, 2=half_open)',
    ['circuit_name'],
    registry=registry
)


def record_merge(status: str = "success"):
    """Helper pour enregistrer merge avec métrique"""
    merge_counter.labels(status=status).inc()


def record_undo(status: str = "success"):
    """Helper pour enregistrer undo avec métrique"""
    undo_counter.labels(status=status).inc()


def record_bootstrap(status: str = "success"):
    """Helper pour enregistrer bootstrap avec métrique"""
    bootstrap_counter.labels(status=status).inc()


def timed_operation(histogram: Histogram):
    """Décorateur pour mesurer durée opération"""
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        async def async_wrapper(*args, **kwargs):
            start = time.time()
            try:
                result = await func(*args, **kwargs)
                return result
            finally:
                duration = time.time() - start
                histogram.observe(duration)

        @wraps(func)
        def sync_wrapper(*args, **kwargs):
            start = time.time()
            try:
                result = func(*args, **kwargs)
                return result
            finally:
                duration = time.time() - start
                histogram.observe(duration)

        # Retourner wrapper approprié selon fonction async/sync
        import asyncio
        if asyncio.iscoroutinefunction(func):
            return async_wrapper
        return sync_wrapper

    return decorator


def get_metrics() -> bytes:
    """
    Récupérer métriques au format Prometheus

    Returns:
        Metrics bytes au format Prometheus text
    """
    return generate_latest(registry)


def update_circuit_breaker_metric(circuit_name: str, state: str):
    """
    Mettre à jour métrique circuit breaker

    Args:
        circuit_name: Nom circuit (llm, qdrant)
        state: État (closed, open, half_open)
    """
    state_map = {"closed": 0, "open": 1, "half_open": 2}
    circuit_breaker_state.labels(circuit_name=circuit_name).set(
        state_map.get(state, 0)
    )
