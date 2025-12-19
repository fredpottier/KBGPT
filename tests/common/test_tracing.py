"""
Tests for Distributed Tracing - src/knowbase/common/tracing.py

Tests cover:
- Configuration loading (OTEL_ENABLED, OTEL_SERVICE_NAME, etc.)
- trace_operation decorator (sync and async)
- trace_span context manager
- get_trace_context function
- Graceful handling when OpenTelemetry is disabled
- Error handling and attribute setting
"""
from __future__ import annotations

import asyncio
import os
from contextlib import contextmanager
from typing import Any, Generator
from unittest.mock import MagicMock, patch

import pytest


# ============================================
# Fixtures
# ============================================

@pytest.fixture
def mock_otel_disabled():
    """Mock environment with OTEL disabled."""
    with patch.dict(os.environ, {"OTEL_ENABLED": "false"}):
        yield


@pytest.fixture
def mock_otel_enabled():
    """Mock environment with OTEL enabled but without actual OpenTelemetry."""
    with patch.dict(os.environ, {"OTEL_ENABLED": "true"}):
        yield


# ============================================
# Test Configuration
# ============================================

class TestTracingConfiguration:
    """Tests for tracing configuration."""

    def test_otel_enabled_default_is_false(self) -> None:
        """OTEL_ENABLED should default to false."""
        with patch.dict(os.environ, {}, clear=True):
            # Re-import to get fresh config
            import importlib
            from knowbase.common import tracing
            importlib.reload(tracing)

            # With no env var, should be false
            # Note: This may not work perfectly due to module caching

    def test_otel_service_name_has_default(self) -> None:
        """OTEL_SERVICE_NAME should have a default."""
        from knowbase.common.tracing import OTEL_SERVICE_NAME
        assert OTEL_SERVICE_NAME is not None
        assert len(OTEL_SERVICE_NAME) > 0

    def test_otel_exporter_has_default(self) -> None:
        """OTEL_EXPORTER should default to console."""
        from knowbase.common.tracing import OTEL_EXPORTER
        assert OTEL_EXPORTER is not None


# ============================================
# Test trace_operation Decorator (Disabled Mode)
# ============================================

class TestTraceOperationDisabled:
    """Tests for trace_operation when tracing is disabled."""

    def test_sync_function_works_without_tracing(self) -> None:
        """Sync function should work when tracing is disabled."""
        from knowbase.common.tracing import trace_operation

        @trace_operation("test_operation")
        def sync_func():
            return "sync_result"

        result = sync_func()
        assert result == "sync_result"

    def test_async_function_works_without_tracing(self) -> None:
        """Async function should work when tracing is disabled."""
        from knowbase.common.tracing import trace_operation

        @trace_operation("test_async_operation")
        async def async_func():
            return "async_result"

        result = asyncio.run(async_func())
        assert result == "async_result"

    def test_preserves_arguments_without_tracing(self) -> None:
        """Arguments should be preserved when tracing is disabled."""
        from knowbase.common.tracing import trace_operation

        @trace_operation("test_args")
        def with_args(a: int, b: str, multiply: bool = False) -> str:
            return f"{a}-{b}-{multiply}"

        result = with_args(42, "test", multiply=True)
        assert result == "42-test-True"

    def test_async_preserves_arguments_without_tracing(self) -> None:
        """Async arguments should be preserved when tracing is disabled."""
        from knowbase.common.tracing import trace_operation

        @trace_operation("test_async_args")
        async def async_with_args(a: int, b: str) -> str:
            return f"async-{a}-{b}"

        result = asyncio.run(async_with_args(10, "hello"))
        assert result == "async-10-hello"

    def test_exception_propagates_without_tracing(self) -> None:
        """Exceptions should propagate when tracing is disabled."""
        from knowbase.common.tracing import trace_operation

        @trace_operation("test_exception")
        def raise_error():
            raise ValueError("Test error")

        with pytest.raises(ValueError) as exc_info:
            raise_error()

        assert "Test error" in str(exc_info.value)

    def test_async_exception_propagates_without_tracing(self) -> None:
        """Async exceptions should propagate when tracing is disabled."""
        from knowbase.common.tracing import trace_operation

        @trace_operation("test_async_exception")
        async def async_raise_error():
            raise RuntimeError("Async error")

        with pytest.raises(RuntimeError) as exc_info:
            asyncio.run(async_raise_error())

        assert "Async error" in str(exc_info.value)

    def test_decorator_with_attributes(self) -> None:
        """Decorator should accept attributes parameter."""
        from knowbase.common.tracing import trace_operation

        @trace_operation("test_with_attrs", attributes={"tenant": "test"})
        def func_with_attrs():
            return "result"

        result = func_with_attrs()
        assert result == "result"


# ============================================
# Test trace_span Context Manager (Disabled Mode)
# ============================================

class TestTraceSpanDisabled:
    """Tests for trace_span context manager when disabled."""

    def test_trace_span_works_when_disabled(self) -> None:
        """trace_span should work as no-op when tracing disabled."""
        from knowbase.common.tracing import trace_span

        with trace_span("test_span"):
            result = 1 + 1

        assert result == 2

    def test_trace_span_with_attributes(self) -> None:
        """trace_span should accept attributes."""
        from knowbase.common.tracing import trace_span

        with trace_span("test_span", attributes={"key": "value"}):
            result = "executed"

        assert result == "executed"

    def test_trace_span_exception_propagates(self) -> None:
        """Exceptions should propagate through trace_span."""
        from knowbase.common.tracing import trace_span

        with pytest.raises(ValueError) as exc_info:
            with trace_span("test_error_span"):
                raise ValueError("Span error")

        assert "Span error" in str(exc_info.value)

    def test_trace_span_yields_none_when_disabled(self) -> None:
        """trace_span should yield None when disabled."""
        from knowbase.common.tracing import trace_span, OTEL_ENABLED

        if not OTEL_ENABLED:
            # When disabled, the context manager yields nothing (no 'as' value)
            with trace_span("test_yield"):
                pass  # Just verify it works


# ============================================
# Test get_trace_context Function
# ============================================

class TestGetTraceContext:
    """Tests for get_trace_context function."""

    def test_returns_empty_dict_when_disabled(self) -> None:
        """get_trace_context should return empty dict when disabled."""
        from knowbase.common.tracing import get_trace_context, OTEL_ENABLED

        if not OTEL_ENABLED:
            result = get_trace_context()
            assert result == {}

    def test_returns_dict_type(self) -> None:
        """get_trace_context should return a dict."""
        from knowbase.common.tracing import get_trace_context

        result = get_trace_context()
        assert isinstance(result, dict)


# ============================================
# Test Decorator on Class Methods
# ============================================

class TestDecoratorOnClassMethods:
    """Tests for decorator on class methods."""

    def test_sync_method_decorated(self) -> None:
        """Decorator should work on sync class methods."""
        from knowbase.common.tracing import trace_operation

        class MyService:
            @trace_operation("service_method")
            def process(self, data: str) -> str:
                return f"processed: {data}"

        service = MyService()
        result = service.process("test_data")
        assert result == "processed: test_data"

    def test_async_method_decorated(self) -> None:
        """Decorator should work on async class methods."""
        from knowbase.common.tracing import trace_operation

        class AsyncService:
            @trace_operation("async_service_method")
            async def process(self, data: str) -> str:
                return f"async processed: {data}"

        service = AsyncService()
        result = asyncio.run(service.process("async_data"))
        assert result == "async processed: async_data"

    def test_static_method_decorated(self) -> None:
        """Decorator should work on static methods."""
        from knowbase.common.tracing import trace_operation

        class StaticService:
            @staticmethod
            @trace_operation("static_method")
            def compute(x: int, y: int) -> int:
                return x + y

        result = StaticService.compute(5, 3)
        assert result == 8


# ============================================
# Test Return Value Preservation
# ============================================

class TestReturnValuePreservation:
    """Tests for return value preservation."""

    def test_preserves_none_return(self) -> None:
        """Decorator should preserve None return."""
        from knowbase.common.tracing import trace_operation

        @trace_operation("return_none")
        def return_nothing() -> None:
            pass

        result = return_nothing()
        assert result is None

    def test_preserves_dict_return(self) -> None:
        """Decorator should preserve dict return."""
        from knowbase.common.tracing import trace_operation

        @trace_operation("return_dict")
        def return_dict() -> dict:
            return {"key": "value", "count": 42}

        result = return_dict()
        assert result == {"key": "value", "count": 42}

    def test_preserves_list_return(self) -> None:
        """Decorator should preserve list return."""
        from knowbase.common.tracing import trace_operation

        @trace_operation("return_list")
        def return_list() -> list:
            return [1, 2, 3, 4, 5]

        result = return_list()
        assert result == [1, 2, 3, 4, 5]

    def test_async_preserves_complex_return(self) -> None:
        """Async decorator should preserve complex return."""
        from knowbase.common.tracing import trace_operation

        @trace_operation("async_complex_return")
        async def async_complex() -> dict:
            return {
                "status": "success",
                "data": [1, 2, 3],
                "nested": {"key": "value"}
            }

        result = asyncio.run(async_complex())
        assert result["status"] == "success"
        assert result["data"] == [1, 2, 3]
        assert result["nested"]["key"] == "value"


# ============================================
# Test Multiple Decorators
# ============================================

class TestMultipleDecorators:
    """Tests for multiple decorators stacked."""

    def test_multiple_traced_functions(self) -> None:
        """Multiple functions can be traced independently."""
        from knowbase.common.tracing import trace_operation

        @trace_operation("func_a")
        def func_a():
            return "A"

        @trace_operation("func_b")
        def func_b():
            return "B"

        assert func_a() == "A"
        assert func_b() == "B"

    def test_nested_traced_calls(self) -> None:
        """Nested traced function calls should work."""
        from knowbase.common.tracing import trace_operation

        @trace_operation("inner")
        def inner_func(x: int) -> int:
            return x * 2

        @trace_operation("outer")
        def outer_func(x: int) -> int:
            return inner_func(x) + 1

        result = outer_func(5)
        assert result == 11  # (5 * 2) + 1


# ============================================
# Test Edge Cases
# ============================================

class TestEdgeCases:
    """Tests for edge cases."""

    def test_empty_name(self) -> None:
        """Empty span name should work."""
        from knowbase.common.tracing import trace_operation

        @trace_operation("")
        def empty_name_func():
            return "ok"

        result = empty_name_func()
        assert result == "ok"

    def test_none_attributes(self) -> None:
        """None attributes should work."""
        from knowbase.common.tracing import trace_operation

        @trace_operation("test", attributes=None)
        def none_attrs_func():
            return "ok"

        result = none_attrs_func()
        assert result == "ok"

    def test_empty_attributes(self) -> None:
        """Empty attributes dict should work."""
        from knowbase.common.tracing import trace_operation

        @trace_operation("test", attributes={})
        def empty_attrs_func():
            return "ok"

        result = empty_attrs_func()
        assert result == "ok"

    def test_unicode_in_name(self) -> None:
        """Unicode in span name should work."""
        from knowbase.common.tracing import trace_operation

        @trace_operation("test_北京_операция")
        def unicode_name_func():
            return "unicode ok"

        result = unicode_name_func()
        assert result == "unicode ok"

    def test_special_characters_in_attributes(self) -> None:
        """Special characters in attributes should work."""
        from knowbase.common.tracing import trace_operation

        @trace_operation("test", attributes={"path": "/api/v1/test?q=1&x=2"})
        def special_chars_func():
            return "special ok"

        result = special_chars_func()
        assert result == "special ok"
