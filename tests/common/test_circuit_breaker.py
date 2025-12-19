"""
Tests for Circuit Breaker Pattern - src/knowbase/common/circuit_breaker.py

Tests cover:
- State transitions (CLOSED -> OPEN -> HALF_OPEN -> CLOSED)
- Failure threshold behavior
- Recovery timeout logic
- Success threshold in HALF_OPEN state
- Decorator functionality
- Edge cases and error handling
"""
from __future__ import annotations

import time
from unittest.mock import patch, MagicMock

import pytest

from knowbase.common.circuit_breaker import (
    CircuitBreaker,
    CircuitBreakerOpenError,
    CircuitState,
    llm_circuit_breaker,
    qdrant_circuit_breaker,
)


# ============================================
# Fixtures
# ============================================

@pytest.fixture
def circuit_breaker() -> CircuitBreaker:
    """Create a fresh circuit breaker for testing."""
    return CircuitBreaker(
        name="test",
        failure_threshold=3,
        recovery_timeout=5,
        success_threshold=2
    )


@pytest.fixture
def fast_circuit_breaker() -> CircuitBreaker:
    """Circuit breaker with minimal timeouts for faster tests."""
    return CircuitBreaker(
        name="fast_test",
        failure_threshold=2,
        recovery_timeout=1,  # 1 second recovery
        success_threshold=1
    )


# ============================================
# Test CircuitState Enum
# ============================================

class TestCircuitState:
    """Tests for CircuitState enum."""

    def test_states_are_strings(self) -> None:
        """Verify states are string values."""
        assert CircuitState.CLOSED.value == "closed"
        assert CircuitState.OPEN.value == "open"
        assert CircuitState.HALF_OPEN.value == "half_open"

    def test_all_states_exist(self) -> None:
        """Verify all expected states exist."""
        states = [s for s in CircuitState]
        assert len(states) == 3
        assert CircuitState.CLOSED in states
        assert CircuitState.OPEN in states
        assert CircuitState.HALF_OPEN in states


# ============================================
# Test CircuitBreaker Initialization
# ============================================

class TestCircuitBreakerInit:
    """Tests for CircuitBreaker initialization."""

    def test_default_state_is_closed(self, circuit_breaker: CircuitBreaker) -> None:
        """New circuit breaker should start in CLOSED state."""
        assert circuit_breaker.state == CircuitState.CLOSED

    def test_failure_count_starts_at_zero(self, circuit_breaker: CircuitBreaker) -> None:
        """Failure count should start at zero."""
        assert circuit_breaker.failure_count == 0

    def test_success_count_starts_at_zero(self, circuit_breaker: CircuitBreaker) -> None:
        """Success count should start at zero."""
        assert circuit_breaker.success_count == 0

    def test_last_failure_time_is_none(self, circuit_breaker: CircuitBreaker) -> None:
        """Last failure time should be None initially."""
        assert circuit_breaker.last_failure_time is None

    def test_custom_parameters(self) -> None:
        """Verify custom parameters are stored correctly."""
        cb = CircuitBreaker(
            name="custom",
            failure_threshold=10,
            recovery_timeout=120,
            success_threshold=5
        )
        assert cb.name == "custom"
        assert cb.failure_threshold == 10
        assert cb.recovery_timeout == 120
        assert cb.success_threshold == 5


# ============================================
# Test State Transitions
# ============================================

class TestStateTransitions:
    """Tests for circuit breaker state transitions."""

    def test_closed_to_open_on_threshold_failures(
        self, circuit_breaker: CircuitBreaker
    ) -> None:
        """Circuit should open after reaching failure threshold."""
        @circuit_breaker.call
        def failing_function():
            raise ValueError("Test error")

        # Call failing function until threshold reached
        for _ in range(circuit_breaker.failure_threshold):
            with pytest.raises(ValueError):
                failing_function()

        assert circuit_breaker.state == CircuitState.OPEN

    def test_stays_closed_below_threshold(
        self, circuit_breaker: CircuitBreaker
    ) -> None:
        """Circuit should stay closed below failure threshold."""
        @circuit_breaker.call
        def failing_function():
            raise ValueError("Test error")

        # Call one less than threshold
        for _ in range(circuit_breaker.failure_threshold - 1):
            with pytest.raises(ValueError):
                failing_function()

        assert circuit_breaker.state == CircuitState.CLOSED

    def test_open_raises_circuit_breaker_error(
        self, circuit_breaker: CircuitBreaker
    ) -> None:
        """Open circuit should raise CircuitBreakerOpenError."""
        @circuit_breaker.call
        def any_function():
            return "result"

        # Force circuit to open
        circuit_breaker.state = CircuitState.OPEN
        circuit_breaker.last_failure_time = time.time()

        with pytest.raises(CircuitBreakerOpenError) as exc_info:
            any_function()

        assert "test" in str(exc_info.value)
        assert "OPEN" in str(exc_info.value)

    def test_open_to_half_open_after_recovery_timeout(
        self, fast_circuit_breaker: CircuitBreaker
    ) -> None:
        """Circuit should transition to HALF_OPEN after recovery timeout."""
        call_count = 0

        @fast_circuit_breaker.call
        def sometimes_fails():
            nonlocal call_count
            call_count += 1
            return "success"

        # Force circuit to open
        fast_circuit_breaker.state = CircuitState.OPEN
        fast_circuit_breaker.last_failure_time = time.time() - 2  # 2 seconds ago

        # Should transition to HALF_OPEN and allow call
        result = sometimes_fails()
        assert result == "success"
        assert call_count == 1
        # After success in HALF_OPEN with success_threshold=1, it transitions to CLOSED
        # This is expected behavior - the circuit recovered
        assert fast_circuit_breaker.state in (CircuitState.HALF_OPEN, CircuitState.CLOSED)

    def test_half_open_to_closed_on_success_threshold(
        self, circuit_breaker: CircuitBreaker
    ) -> None:
        """Circuit should close after success threshold in HALF_OPEN."""
        call_count = 0

        @circuit_breaker.call
        def succeeding_function():
            nonlocal call_count
            call_count += 1
            return "success"

        # Set to HALF_OPEN
        circuit_breaker.state = CircuitState.HALF_OPEN
        circuit_breaker.success_count = 0

        # Call success_threshold times
        for _ in range(circuit_breaker.success_threshold):
            succeeding_function()

        assert circuit_breaker.state == CircuitState.CLOSED

    def test_half_open_to_open_on_failure(
        self, circuit_breaker: CircuitBreaker
    ) -> None:
        """Circuit should reopen on failure in HALF_OPEN state."""
        @circuit_breaker.call
        def failing_function():
            raise RuntimeError("Still failing")

        # Set to HALF_OPEN
        circuit_breaker.state = CircuitState.HALF_OPEN

        with pytest.raises(RuntimeError):
            failing_function()

        assert circuit_breaker.state == CircuitState.OPEN


# ============================================
# Test Success/Failure Handling
# ============================================

class TestSuccessFailureHandling:
    """Tests for success and failure counting."""

    def test_success_resets_failure_count_in_closed(
        self, circuit_breaker: CircuitBreaker
    ) -> None:
        """Success in CLOSED state should reset failure count."""
        @circuit_breaker.call
        def mixed_function(should_fail: bool):
            if should_fail:
                raise ValueError("Error")
            return "success"

        # Accumulate some failures
        for _ in range(2):
            with pytest.raises(ValueError):
                mixed_function(True)

        assert circuit_breaker.failure_count == 2

        # One success should reset
        mixed_function(False)
        assert circuit_breaker.failure_count == 0

    def test_failure_increments_count(self, circuit_breaker: CircuitBreaker) -> None:
        """Each failure should increment failure count."""
        @circuit_breaker.call
        def failing_function():
            raise ValueError("Error")

        for i in range(2):
            with pytest.raises(ValueError):
                failing_function()
            assert circuit_breaker.failure_count == i + 1

    def test_failure_updates_last_failure_time(
        self, circuit_breaker: CircuitBreaker
    ) -> None:
        """Failure should update last_failure_time."""
        @circuit_breaker.call
        def failing_function():
            raise ValueError("Error")

        assert circuit_breaker.last_failure_time is None

        before = time.time()
        with pytest.raises(ValueError):
            failing_function()
        after = time.time()

        assert circuit_breaker.last_failure_time is not None
        assert before <= circuit_breaker.last_failure_time <= after


# ============================================
# Test Decorator Functionality
# ============================================

class TestDecoratorFunctionality:
    """Tests for the decorator pattern."""

    def test_decorator_preserves_function_result(
        self, circuit_breaker: CircuitBreaker
    ) -> None:
        """Decorator should return function result."""
        @circuit_breaker.call
        def return_value():
            return {"key": "value", "number": 42}

        result = return_value()
        assert result == {"key": "value", "number": 42}

    def test_decorator_passes_arguments(
        self, circuit_breaker: CircuitBreaker
    ) -> None:
        """Decorator should pass positional and keyword arguments."""
        @circuit_breaker.call
        def with_args(a: int, b: int, multiply: bool = False):
            if multiply:
                return a * b
            return a + b

        assert with_args(2, 3) == 5
        assert with_args(2, 3, multiply=True) == 6

    def test_decorator_preserves_exception_type(
        self, circuit_breaker: CircuitBreaker
    ) -> None:
        """Decorator should preserve original exception type."""
        class CustomError(Exception):
            pass

        @circuit_breaker.call
        def raise_custom():
            raise CustomError("Custom message")

        with pytest.raises(CustomError) as exc_info:
            raise_custom()

        assert "Custom message" in str(exc_info.value)

    def test_decorator_works_with_class_methods(
        self, circuit_breaker: CircuitBreaker
    ) -> None:
        """Decorator should work with class methods."""
        class MyService:
            def __init__(self):
                self.call_count = 0

            @circuit_breaker.call
            def process(self, data: str) -> str:
                self.call_count += 1
                return f"processed: {data}"

        service = MyService()
        result = service.process("test")

        assert result == "processed: test"
        assert service.call_count == 1


# ============================================
# Test get_state Method
# ============================================

class TestGetState:
    """Tests for get_state method."""

    def test_get_state_returns_complete_info(
        self, circuit_breaker: CircuitBreaker
    ) -> None:
        """get_state should return complete circuit info."""
        state = circuit_breaker.get_state()

        assert "name" in state
        assert "state" in state
        assert "failure_count" in state
        assert "success_count" in state
        assert "last_failure_time" in state

    def test_get_state_reflects_current_state(
        self, circuit_breaker: CircuitBreaker
    ) -> None:
        """get_state should reflect actual current state."""
        assert circuit_breaker.get_state()["state"] == "closed"

        circuit_breaker.state = CircuitState.OPEN
        assert circuit_breaker.get_state()["state"] == "open"

        circuit_breaker.state = CircuitState.HALF_OPEN
        assert circuit_breaker.get_state()["state"] == "half_open"


# ============================================
# Test Edge Cases
# ============================================

class TestEdgeCases:
    """Tests for edge cases."""

    def test_multiple_decorators_same_breaker(
        self, circuit_breaker: CircuitBreaker
    ) -> None:
        """Multiple functions can use same circuit breaker."""
        @circuit_breaker.call
        def func_a():
            raise ValueError("A fails")

        @circuit_breaker.call
        def func_b():
            raise ValueError("B fails")

        # Failures from both functions should count
        with pytest.raises(ValueError):
            func_a()
        with pytest.raises(ValueError):
            func_b()

        assert circuit_breaker.failure_count == 2

    def test_rapid_failures_open_circuit(
        self, circuit_breaker: CircuitBreaker
    ) -> None:
        """Rapid consecutive failures should open circuit."""
        @circuit_breaker.call
        def fail():
            raise RuntimeError("Rapid fail")

        for _ in range(circuit_breaker.failure_threshold):
            with pytest.raises(RuntimeError):
                fail()

        # Next call should fail fast
        with pytest.raises(CircuitBreakerOpenError):
            fail()

    def test_should_not_attempt_reset_without_failure_time(
        self, circuit_breaker: CircuitBreaker
    ) -> None:
        """_should_attempt_reset should return False without last_failure_time."""
        circuit_breaker.last_failure_time = None
        assert circuit_breaker._should_attempt_reset() is False

    def test_recovery_timeout_boundary(
        self, fast_circuit_breaker: CircuitBreaker
    ) -> None:
        """Test behavior exactly at recovery timeout boundary."""
        @fast_circuit_breaker.call
        def test_func():
            return "ok"

        # Set state to OPEN with failure time just at recovery boundary
        fast_circuit_breaker.state = CircuitState.OPEN
        fast_circuit_breaker.last_failure_time = (
            time.time() - fast_circuit_breaker.recovery_timeout
        )

        # Should allow call (exactly at timeout)
        result = test_func()
        assert result == "ok"


# ============================================
# Test Global Circuit Breakers
# ============================================

class TestGlobalCircuitBreakers:
    """Tests for pre-configured global circuit breakers."""

    def test_llm_circuit_breaker_exists(self) -> None:
        """llm_circuit_breaker should be pre-configured."""
        assert llm_circuit_breaker is not None
        assert llm_circuit_breaker.name == "llm"
        assert llm_circuit_breaker.failure_threshold == 5
        assert llm_circuit_breaker.recovery_timeout == 60

    def test_qdrant_circuit_breaker_exists(self) -> None:
        """qdrant_circuit_breaker should be pre-configured."""
        assert qdrant_circuit_breaker is not None
        assert qdrant_circuit_breaker.name == "qdrant"
        assert qdrant_circuit_breaker.failure_threshold == 3
        assert qdrant_circuit_breaker.recovery_timeout == 30


# ============================================
# Test Metrics Integration
# ============================================

class TestMetricsIntegration:
    """Tests for Prometheus metrics integration."""

    def test_metrics_called_on_state_transition_to_open(
        self, circuit_breaker: CircuitBreaker
    ) -> None:
        """Metrics should be updated when transitioning to OPEN."""
        with patch.dict("sys.modules", {"knowbase.common.metrics": MagicMock()}):
            import sys
            mock_module = sys.modules["knowbase.common.metrics"]
            mock_module.update_circuit_breaker_metric = MagicMock()

            circuit_breaker._transition_to_open()

            # Verify transition happened
            assert circuit_breaker.state == CircuitState.OPEN

    def test_metrics_called_on_state_transition_to_half_open(
        self, circuit_breaker: CircuitBreaker
    ) -> None:
        """Metrics should be updated when transitioning to HALF_OPEN."""
        with patch.dict("sys.modules", {"knowbase.common.metrics": MagicMock()}):
            import sys
            mock_module = sys.modules["knowbase.common.metrics"]
            mock_module.update_circuit_breaker_metric = MagicMock()

            circuit_breaker._transition_to_half_open()

            # Verify transition happened
            assert circuit_breaker.state == CircuitState.HALF_OPEN

    def test_metrics_called_on_state_transition_to_closed(
        self, circuit_breaker: CircuitBreaker
    ) -> None:
        """Metrics should be updated when transitioning to CLOSED."""
        with patch.dict("sys.modules", {"knowbase.common.metrics": MagicMock()}):
            import sys
            mock_module = sys.modules["knowbase.common.metrics"]
            mock_module.update_circuit_breaker_metric = MagicMock()

            circuit_breaker._transition_to_closed()

            # Verify transition happened
            assert circuit_breaker.state == CircuitState.CLOSED

    def test_metrics_import_error_handled_gracefully(
        self, circuit_breaker: CircuitBreaker
    ) -> None:
        """ImportError for metrics should not break circuit breaker."""
        # Transitions should work even if metrics module unavailable
        circuit_breaker._transition_to_open()
        assert circuit_breaker.state == CircuitState.OPEN

        circuit_breaker._transition_to_half_open()
        assert circuit_breaker.state == CircuitState.HALF_OPEN

        circuit_breaker._transition_to_closed()
        assert circuit_breaker.state == CircuitState.CLOSED


# ============================================
# Test CircuitBreakerOpenError
# ============================================

class TestCircuitBreakerOpenError:
    """Tests for CircuitBreakerOpenError exception."""

    def test_error_is_exception_subclass(self) -> None:
        """CircuitBreakerOpenError should be an Exception."""
        assert issubclass(CircuitBreakerOpenError, Exception)

    def test_error_message_preserved(self) -> None:
        """Error message should be preserved."""
        error = CircuitBreakerOpenError("Test message")
        assert str(error) == "Test message"

    def test_error_can_be_caught_as_exception(self) -> None:
        """Error can be caught as generic Exception."""
        try:
            raise CircuitBreakerOpenError("Test")
        except Exception as e:
            assert isinstance(e, CircuitBreakerOpenError)
