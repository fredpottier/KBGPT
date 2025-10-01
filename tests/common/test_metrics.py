"""
Tests Métriques Prometheus - Phase 0.5 P2.11
"""
import pytest
from knowbase.common.metrics import (
    merge_counter,
    undo_counter,
    bootstrap_counter,
    merge_duration,
    backfill_duration,
    bootstrap_duration,
    quarantine_queue_size,
    circuit_breaker_state,
    record_merge,
    record_undo,
    record_bootstrap,
    timed_operation,
    get_metrics,
    update_circuit_breaker_metric,
    registry
)


def test_record_merge():
    """Test compteur merge"""
    initial = merge_counter.labels(status="success")._value.get()
    record_merge("success")
    assert merge_counter.labels(status="success")._value.get() == initial + 1


def test_record_undo():
    """Test compteur undo"""
    initial = undo_counter.labels(status="failed")._value.get()
    record_undo("failed")
    assert undo_counter.labels(status="failed")._value.get() == initial + 1


def test_record_bootstrap():
    """Test compteur bootstrap"""
    initial = bootstrap_counter.labels(status="success")._value.get()
    record_bootstrap("success")
    assert bootstrap_counter.labels(status="success")._value.get() == initial + 1


def test_timed_operation_sync():
    """Test décorateur timing synchrone"""
    @timed_operation(merge_duration)
    def slow_function():
        import time
        time.sleep(0.1)
        return "result"

    result = slow_function()
    assert result == "result"
    # Décorateur fonctionne, latence enregistrée


@pytest.mark.asyncio
async def test_timed_operation_async():
    """Test décorateur timing asynchrone"""
    @timed_operation(backfill_duration)
    async def async_slow_function():
        import asyncio
        await asyncio.sleep(0.1)
        return "async_result"

    result = await async_slow_function()
    assert result == "async_result"
    # Décorateur fonctionne, latence enregistrée


def test_quarantine_gauge():
    """Test gauge queue quarantine"""
    quarantine_queue_size.set(42)
    assert quarantine_queue_size._value.get() == 42


def test_circuit_breaker_metric():
    """Test métrique circuit breaker"""
    # CLOSED (0)
    update_circuit_breaker_metric("llm", "closed")
    assert circuit_breaker_state.labels(circuit_name="llm")._value.get() == 0

    # OPEN (1)
    update_circuit_breaker_metric("llm", "open")
    assert circuit_breaker_state.labels(circuit_name="llm")._value.get() == 1

    # HALF_OPEN (2)
    update_circuit_breaker_metric("qdrant", "half_open")
    assert circuit_breaker_state.labels(circuit_name="qdrant")._value.get() == 2


def test_get_metrics_format():
    """Test format Prometheus des métriques"""
    metrics_bytes = get_metrics()
    metrics_text = metrics_bytes.decode('utf-8')

    # Vérifier présence métriques principales
    assert "canonicalization_merge_total" in metrics_text
    assert "canonicalization_undo_total" in metrics_text
    assert "canonicalization_bootstrap_total" in metrics_text
    assert "canonicalization_merge_duration_seconds" in metrics_text
    assert "qdrant_backfill_duration_seconds" in metrics_text
    assert "canonicalization_quarantine_queue_size" in metrics_text
    assert "circuit_breaker_state" in metrics_text


def test_metrics_endpoint_integration():
    """Test intégration endpoint /metrics (simulation)"""
    # Simuler activité
    record_merge("success")
    record_merge("failed")
    record_undo("success")
    record_bootstrap("success")
    quarantine_queue_size.set(5)
    update_circuit_breaker_metric("llm", "open")

    # Récupérer métriques
    metrics = get_metrics().decode('utf-8')

    # Vérifier présence données
    assert "canonicalization_merge_total" in metrics
    assert 'status="success"' in metrics
    assert 'status="failed"' in metrics
    assert "canonicalization_quarantine_queue_size 5" in metrics
    assert 'circuit_name="llm"' in metrics
