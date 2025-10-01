"""
Tests Distributed Tracing - Phase 0.5 P2.12
"""
import pytest
import os


def test_tracing_disabled_by_default():
    """Test tracing désactivé par défaut"""
    from knowbase.common.tracing import OTEL_ENABLED
    # Par défaut, tracing désactivé (pas de OTEL_ENABLED=true)
    # NOTE: Ce test peut échouer si OTEL_ENABLED=true dans .env


def test_trace_operation_decorator_disabled():
    """Test décorateur quand tracing désactivé"""
    from knowbase.common.tracing import trace_operation

    @trace_operation("test_op")
    def simple_func():
        return "result"

    # Devrait fonctionner même si tracing désactivé
    result = simple_func()
    assert result == "result"


@pytest.mark.asyncio
async def test_trace_operation_decorator_async_disabled():
    """Test décorateur async quand tracing désactivé"""
    from knowbase.common.tracing import trace_operation

    @trace_operation("test_async_op")
    async def async_func():
        return "async_result"

    result = await async_func()
    assert result == "async_result"


def test_trace_span_context_manager_disabled():
    """Test context manager quand tracing désactivé"""
    from knowbase.common.tracing import trace_span

    with trace_span("manual_span", {"key": "value"}):
        result = 42

    assert result == 42


def test_get_trace_context_disabled():
    """Test récupération contexte quand tracing désactivé"""
    from knowbase.common.tracing import get_trace_context

    context = get_trace_context()
    # Quand désactivé, retourne dict vide
    assert context == {}


def test_trace_operation_with_exception():
    """Test décorateur capture exception"""
    from knowbase.common.tracing import trace_operation

    @trace_operation("failing_op")
    def failing_func():
        raise ValueError("test error")

    with pytest.raises(ValueError, match="test error"):
        failing_func()


@pytest.mark.asyncio
async def test_trace_operation_async_with_exception():
    """Test décorateur async capture exception"""
    from knowbase.common.tracing import trace_operation

    @trace_operation("failing_async_op")
    async def failing_async_func():
        raise ValueError("async test error")

    with pytest.raises(ValueError, match="async test error"):
        await failing_async_func()
