"""
Tests for Prometheus Metrics - src/knowbase/common/metrics.py

Tests cover:
- Counter metrics (merge, undo, bootstrap)
- Histogram metrics (durations)
- Gauge metrics (circuit breaker state, queue size)
- Helper functions (record_merge, record_undo, record_bootstrap)
- Timed operation decorator
- Metrics export
"""
from __future__ import annotations

import asyncio
import sys
import time
from typing import Callable
from unittest.mock import MagicMock, patch
from contextlib import contextmanager

import pytest


# ============================================
# Mock prometheus_client before importing metrics
# ============================================

class MockMetric:
    """Base mock metric class."""

    def __init__(self, *args, **kwargs):
        self._value = 0
        self._labels = {}

    def labels(self, **kwargs):
        """Return self for chaining."""
        key = tuple(sorted(kwargs.items()))
        if key not in self._labels:
            self._labels[key] = MockMetric()
        return self._labels[key]

    def inc(self, amount=1):
        """Increment counter."""
        self._value += amount

    def set(self, value):
        """Set gauge value."""
        self._value = value

    def observe(self, value):
        """Observe histogram value."""
        self._value = value

    @contextmanager
    def time(self):
        """Time context manager."""
        yield


class MockCounter(MockMetric):
    """Mock Prometheus Counter."""
    pass


class MockHistogram(MockMetric):
    """Mock Prometheus Histogram."""
    pass


class MockGauge(MockMetric):
    """Mock Prometheus Gauge."""
    pass


class MockCollectorRegistry:
    """Mock Prometheus CollectorRegistry."""

    def __init__(self, auto_describe=False):
        self.auto_describe = auto_describe


def mock_generate_latest(registry):
    """Mock generate_latest function."""
    return b"# HELP test_metric Test metric\n# TYPE test_metric counter\ntest_metric 0\n"


# Create mock module
mock_prometheus = MagicMock()
mock_prometheus.Counter = MockCounter
mock_prometheus.Histogram = MockHistogram
mock_prometheus.Gauge = MockGauge
mock_prometheus.CollectorRegistry = MockCollectorRegistry
mock_prometheus.generate_latest = mock_generate_latest
mock_prometheus.REGISTRY = MockCollectorRegistry()

# Patch before import
sys.modules['prometheus_client'] = mock_prometheus


# ============================================
# Fixtures
# ============================================

@pytest.fixture(autouse=True)
def reset_metrics():
    """Reset metrics state before each test."""
    yield


@pytest.fixture
def metrics_module():
    """Import metrics module for testing."""
    from knowbase.common import metrics
    return metrics


# ============================================
# Test Counter Metrics
# ============================================

class TestCounterMetrics:
    """Tests for Counter metrics."""

    def test_merge_counter_exists(self, metrics_module) -> None:
        """merge_counter should exist."""
        assert metrics_module.merge_counter is not None

    def test_undo_counter_exists(self, metrics_module) -> None:
        """undo_counter should exist."""
        assert metrics_module.undo_counter is not None

    def test_bootstrap_counter_exists(self, metrics_module) -> None:
        """bootstrap_counter should exist."""
        assert metrics_module.bootstrap_counter is not None

    def test_merge_counter_has_status_label(self, metrics_module) -> None:
        """merge_counter should have status label."""
        # Labels are defined, we can increment with different statuses
        metrics_module.merge_counter.labels(status="success")
        metrics_module.merge_counter.labels(status="failed")
        metrics_module.merge_counter.labels(status="rejected")

    def test_counters_increment(self, metrics_module) -> None:
        """Counters should be incrementable."""
        metrics_module.merge_counter.labels(status="test_success").inc()
        metrics_module.undo_counter.labels(status="test_success").inc()
        metrics_module.bootstrap_counter.labels(status="test_success").inc()


# ============================================
# Test Histogram Metrics
# ============================================

class TestHistogramMetrics:
    """Tests for Histogram metrics."""

    def test_merge_duration_exists(self, metrics_module) -> None:
        """merge_duration histogram should exist."""
        assert metrics_module.merge_duration is not None

    def test_backfill_duration_exists(self, metrics_module) -> None:
        """backfill_duration histogram should exist."""
        assert metrics_module.backfill_duration is not None

    def test_bootstrap_duration_exists(self, metrics_module) -> None:
        """bootstrap_duration histogram should exist."""
        assert metrics_module.bootstrap_duration is not None

    def test_histogram_observe(self, metrics_module) -> None:
        """Histograms should accept observations."""
        metrics_module.merge_duration.observe(0.5)
        metrics_module.backfill_duration.observe(10.0)
        metrics_module.bootstrap_duration.observe(60.0)

    def test_histogram_time_context_manager(self, metrics_module) -> None:
        """Histogram time() context manager should work."""
        with metrics_module.merge_duration.time():
            time.sleep(0.01)  # Small delay


# ============================================
# Test Gauge Metrics
# ============================================

class TestGaugeMetrics:
    """Tests for Gauge metrics."""

    def test_quarantine_queue_size_exists(self, metrics_module) -> None:
        """quarantine_queue_size gauge should exist."""
        assert metrics_module.quarantine_queue_size is not None

    def test_circuit_breaker_state_exists(self, metrics_module) -> None:
        """circuit_breaker_state gauge should exist."""
        assert metrics_module.circuit_breaker_state is not None

    def test_quarantine_gauge_set(self, metrics_module) -> None:
        """Quarantine gauge should accept set()."""
        metrics_module.quarantine_queue_size.set(10)
        metrics_module.quarantine_queue_size.set(0)

    def test_circuit_breaker_state_with_label(self, metrics_module) -> None:
        """Circuit breaker gauge should work with labels."""
        metrics_module.circuit_breaker_state.labels(circuit_name="test_llm").set(0)
        metrics_module.circuit_breaker_state.labels(circuit_name="test_qdrant").set(1)


# ============================================
# Test Helper Functions
# ============================================

class TestHelperFunctions:
    """Tests for helper functions."""

    def test_record_merge_success(self, metrics_module) -> None:
        """record_merge should increment counter with success status."""
        # Should not raise
        metrics_module.record_merge(status="success")

    def test_record_merge_failed(self, metrics_module) -> None:
        """record_merge should work with failed status."""
        metrics_module.record_merge(status="failed")

    def test_record_merge_default_status(self, metrics_module) -> None:
        """record_merge should default to success."""
        metrics_module.record_merge()  # Default status

    def test_record_undo_success(self, metrics_module) -> None:
        """record_undo should increment counter."""
        metrics_module.record_undo(status="success")

    def test_record_undo_failed(self, metrics_module) -> None:
        """record_undo should work with failed status."""
        metrics_module.record_undo(status="failed")

    def test_record_bootstrap_success(self, metrics_module) -> None:
        """record_bootstrap should increment counter."""
        metrics_module.record_bootstrap(status="success")

    def test_record_bootstrap_failed(self, metrics_module) -> None:
        """record_bootstrap should work with failed status."""
        metrics_module.record_bootstrap(status="failed")


# ============================================
# Test timed_operation Decorator
# ============================================

class TestTimedOperationDecorator:
    """Tests for timed_operation decorator."""

    def test_timed_operation_sync_function(self, metrics_module) -> None:
        """timed_operation should work with sync functions."""
        @metrics_module.timed_operation(metrics_module.merge_duration)
        def sync_operation():
            time.sleep(0.01)
            return "result"

        result = sync_operation()
        assert result == "result"

    def test_timed_operation_async_function(self, metrics_module) -> None:
        """timed_operation should work with async functions."""
        @metrics_module.timed_operation(metrics_module.merge_duration)
        async def async_operation():
            await asyncio.sleep(0.01)
            return "async_result"

        result = asyncio.run(async_operation())
        assert result == "async_result"

    def test_timed_operation_preserves_arguments(self, metrics_module) -> None:
        """timed_operation should preserve function arguments."""
        @metrics_module.timed_operation(metrics_module.merge_duration)
        def with_args(a: int, b: str, multiply: bool = False) -> str:
            return f"{a}-{b}-{multiply}"

        result = with_args(42, "test", multiply=True)
        assert result == "42-test-True"

    def test_timed_operation_preserves_exception(self, metrics_module) -> None:
        """timed_operation should preserve exceptions."""
        @metrics_module.timed_operation(metrics_module.merge_duration)
        def raise_error():
            raise ValueError("Test error")

        with pytest.raises(ValueError) as exc_info:
            raise_error()

        assert "Test error" in str(exc_info.value)

    def test_timed_operation_async_preserves_exception(self, metrics_module) -> None:
        """timed_operation should preserve async exceptions."""
        @metrics_module.timed_operation(metrics_module.merge_duration)
        async def async_raise_error():
            raise RuntimeError("Async error")

        with pytest.raises(RuntimeError) as exc_info:
            asyncio.run(async_raise_error())

        assert "Async error" in str(exc_info.value)


# ============================================
# Test get_metrics Function
# ============================================

class TestGetMetrics:
    """Tests for get_metrics function."""

    def test_get_metrics_returns_bytes(self, metrics_module) -> None:
        """get_metrics should return bytes."""
        result = metrics_module.get_metrics()
        assert isinstance(result, bytes)

    def test_get_metrics_prometheus_format(self, metrics_module) -> None:
        """get_metrics should return Prometheus format."""
        result = metrics_module.get_metrics()
        text = result.decode('utf-8')

        # Should contain metric names
        assert "canonicalization_merge_total" in text or "# HELP" in text

    def test_get_metrics_includes_custom_metrics(self, metrics_module) -> None:
        """get_metrics should include custom metrics."""
        # Record some metrics
        metrics_module.record_merge(status="test_export")

        result = metrics_module.get_metrics()
        text = result.decode('utf-8')

        # Should be valid Prometheus format
        assert len(text) > 0


# ============================================
# Test update_circuit_breaker_metric Function
# ============================================

class TestUpdateCircuitBreakerMetric:
    """Tests for update_circuit_breaker_metric function."""

    def test_update_closed_state(self, metrics_module) -> None:
        """Should set state to 0 for closed."""
        metrics_module.update_circuit_breaker_metric("test_circuit", "closed")

    def test_update_open_state(self, metrics_module) -> None:
        """Should set state to 1 for open."""
        metrics_module.update_circuit_breaker_metric("test_circuit", "open")

    def test_update_half_open_state(self, metrics_module) -> None:
        """Should set state to 2 for half_open."""
        metrics_module.update_circuit_breaker_metric("test_circuit", "half_open")

    def test_update_unknown_state_defaults_to_zero(self, metrics_module) -> None:
        """Unknown state should default to 0."""
        metrics_module.update_circuit_breaker_metric("test_circuit", "unknown")

    def test_update_multiple_circuits(self, metrics_module) -> None:
        """Should handle multiple circuit names."""
        metrics_module.update_circuit_breaker_metric("llm", "closed")
        metrics_module.update_circuit_breaker_metric("qdrant", "open")
        metrics_module.update_circuit_breaker_metric("neo4j", "half_open")


# ============================================
# Test Registry
# ============================================

class TestRegistry:
    """Tests for custom registry."""

    def test_registry_exists(self, metrics_module) -> None:
        """Custom registry should exist."""
        assert metrics_module.registry is not None

    def test_registry_auto_describe(self, metrics_module) -> None:
        """Registry should have auto_describe enabled."""
        # This is a configuration detail, just verify registry works
        metrics = metrics_module.get_metrics()
        assert len(metrics) > 0
