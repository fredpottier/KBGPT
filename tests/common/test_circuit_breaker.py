"""Tests Circuit Breaker - Phase 0.5 P1.6"""
import pytest
import time
from knowbase.common.circuit_breaker import (
    CircuitBreaker,
    CircuitState,
    CircuitBreakerOpenError
)


def test_circuit_closed_normal():
    """Circuit CLOSED permet requêtes"""
    breaker = CircuitBreaker("test", failure_threshold=3)

    @breaker.call
    def success_func():
        return "ok"

    assert success_func() == "ok"
    assert breaker.state == CircuitState.CLOSED
    print("OK: Circuit CLOSED normal")


def test_circuit_opens_after_failures():
    """Circuit s'ouvre après N échecs"""
    breaker = CircuitBreaker("test", failure_threshold=3)

    @breaker.call
    def fail_func():
        raise ValueError("fail")

    # 3 échecs
    for i in range(3):
        with pytest.raises(ValueError):
            fail_func()

    # Circuit maintenant OPEN
    assert breaker.state == CircuitState.OPEN
    print("OK: Circuit OPEN after 3 failures")


def test_circuit_open_fails_fast():
    """Circuit OPEN fail fast sans exécuter fonction"""
    breaker = CircuitBreaker("test", failure_threshold=2)

    call_count = 0

    @breaker.call
    def tracked_func():
        nonlocal call_count
        call_count += 1
        raise ValueError("fail")

    # 2 échecs → OPEN
    for i in range(2):
        with pytest.raises(ValueError):
            tracked_func()

    assert breaker.state == CircuitState.OPEN
    assert call_count == 2

    # 3ème appel fail fast (fonction pas exécutée)
    with pytest.raises(CircuitBreakerOpenError):
        tracked_func()

    assert call_count == 2  # Pas incrémenté
    print("OK: Circuit OPEN fails fast")


def test_circuit_recovery_half_open():
    """Circuit HALF_OPEN après timeout, puis CLOSED si succès"""
    breaker = CircuitBreaker("test", failure_threshold=2, recovery_timeout=1, success_threshold=2)

    @breaker.call
    def func(should_fail=False):
        if should_fail:
            raise ValueError("fail")
        return "ok"

    # 2 échecs → OPEN
    for i in range(2):
        with pytest.raises(ValueError):
            func(should_fail=True)

    assert breaker.state == CircuitState.OPEN

    # Attendre recovery timeout
    time.sleep(1.1)

    # 1er appel après timeout → HALF_OPEN
    assert func(should_fail=False) == "ok"
    assert breaker.state == CircuitState.HALF_OPEN

    # 2ème succès → CLOSED
    assert func(should_fail=False) == "ok"
    assert breaker.state == CircuitState.CLOSED

    print("OK: Recovery OPEN → HALF_OPEN → CLOSED")


def test_circuit_get_state():
    """get_state retourne état actuel"""
    breaker = CircuitBreaker("test", failure_threshold=5)
    state = breaker.get_state()

    assert state["name"] == "test"
    assert state["state"] == "closed"
    assert state["failure_count"] == 0

    print("OK: get_state()")
