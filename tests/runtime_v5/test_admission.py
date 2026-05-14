"""Tests AdmissionController (CH-52.6.2 / S5.2)."""
from __future__ import annotations

import pytest

from knowbase.runtime_v5.api.admission import (
    AdmissionConfig,
    AdmissionController,
    AdmissionError,
    CircuitBreakerOpen,
    CircuitState,
    ConcurrencyBudgetExceeded,
    DailyQuotaExceeded,
    FakeTimeProvider,
    RateLimitExceeded,
)


@pytest.fixture
def fake_time():
    return FakeTimeProvider(start=1000.0)


@pytest.fixture
def controller(fake_time):
    cfg = AdmissionConfig(
        rate_limit_per_min=5,
        daily_quota_complex=10,
        concurrency_budget=2,
        breaker_failure_threshold=3,
        breaker_window_s=60.0,
        breaker_open_duration_s=60.0,
    )
    return AdmissionController(config=cfg, time_provider=fake_time)


# ─── Rate limit ──────────────────────────────────────────────────────────────


class TestRateLimit:
    def test_below_limit_ok(self, controller):
        for _ in range(5):
            controller.check_rate_limit("tenant_a")

    def test_exceeded(self, controller):
        for _ in range(5):
            controller.check_rate_limit("tenant_a")
        with pytest.raises(RateLimitExceeded) as exc:
            controller.check_rate_limit("tenant_a")
        assert exc.value.retry_after_s is not None
        assert exc.value.retry_after_s > 0

    def test_window_slides(self, controller, fake_time):
        for _ in range(5):
            controller.check_rate_limit("tenant_a")
        # Advance >60s → all expire
        fake_time.advance(61.0)
        controller.check_rate_limit("tenant_a")  # OK again

    def test_per_tenant_isolated(self, controller):
        for _ in range(5):
            controller.check_rate_limit("tenant_a")
        # tenant_b should still be OK
        controller.check_rate_limit("tenant_b")


# ─── Daily quota ─────────────────────────────────────────────────────────────


class TestDailyQuota:
    def test_complex_shape_quota_enforced(self, controller):
        for _ in range(10):
            controller.check_daily_quota("tenant_a", "multi_hop")
        with pytest.raises(DailyQuotaExceeded):
            controller.check_daily_quota("tenant_a", "multi_hop")

    def test_non_complex_shape_no_quota(self, controller):
        for _ in range(50):
            controller.check_daily_quota("tenant_a", "factual")
        # Aucune exception

    def test_no_shape_no_quota(self, controller):
        for _ in range(50):
            controller.check_daily_quota("tenant_a", None)

    def test_quota_resets_after_24h(self, controller, fake_time):
        for _ in range(10):
            controller.check_daily_quota("tenant_a", "comparison")
        fake_time.advance(86401.0)
        controller.check_daily_quota("tenant_a", "comparison")  # OK


# ─── Concurrency budget ──────────────────────────────────────────────────────


class TestConcurrencyBudget:
    def test_acquire_within_budget(self, controller):
        controller.acquire_concurrency_slot("tenant_a")
        controller.acquire_concurrency_slot("tenant_a")
        # Budget=2 → 3ème refusé
        with pytest.raises(ConcurrencyBudgetExceeded):
            controller.acquire_concurrency_slot("tenant_a")

    def test_release_frees_slot(self, controller):
        controller.acquire_concurrency_slot("tenant_a")
        controller.acquire_concurrency_slot("tenant_a")
        controller.release_concurrency_slot("tenant_a")
        # 1 slot libre maintenant
        controller.acquire_concurrency_slot("tenant_a")

    def test_release_idempotent_no_underflow(self, controller):
        controller.release_concurrency_slot("tenant_a")  # rien acquis avant
        controller.release_concurrency_slot("tenant_a")
        # Pas d'exception, ne descend pas sous 0
        snap = controller.snapshot("tenant_a")
        assert snap["concurrency"]["active"] == 0


# ─── Circuit breaker ─────────────────────────────────────────────────────────


class TestCircuitBreaker:
    def test_initial_closed(self, controller):
        controller.check_circuit_breaker("together")
        status = controller.get_circuit_status("together")
        assert status.state == CircuitState.CLOSED

    def test_trip_after_n_failures(self, controller):
        # 3 failures < window → trip
        for _ in range(3):
            controller.record_provider_failure("together")
        status = controller.get_circuit_status("together")
        assert status.state == CircuitState.OPEN
        # Tentative check → raise
        with pytest.raises(CircuitBreakerOpen):
            controller.check_circuit_breaker("together")

    def test_open_to_half_open_after_duration(self, controller, fake_time):
        for _ in range(3):
            controller.record_provider_failure("together")
        assert controller.get_circuit_status("together").state == CircuitState.OPEN
        fake_time.advance(61.0)
        # Check après duration → HALF_OPEN, ne raise pas
        controller.check_circuit_breaker("together")
        assert controller.get_circuit_status("together").state == CircuitState.HALF_OPEN

    def test_half_open_to_closed_on_success(self, controller, fake_time):
        for _ in range(3):
            controller.record_provider_failure("together")
        fake_time.advance(61.0)
        controller.check_circuit_breaker("together")  # HALF_OPEN
        controller.record_provider_success("together")
        assert controller.get_circuit_status("together").state == CircuitState.CLOSED

    def test_half_open_to_open_on_failure(self, controller, fake_time):
        for _ in range(3):
            controller.record_provider_failure("together")
        fake_time.advance(61.0)
        controller.check_circuit_breaker("together")  # → HALF_OPEN
        controller.record_provider_failure("together")
        assert controller.get_circuit_status("together").state == CircuitState.OPEN

    def test_failures_window_slides(self, controller, fake_time):
        """1 failure puis 61s plus tard 2 autres → ne trip pas (1ère hors window)."""
        controller.record_provider_failure("together")
        fake_time.advance(61.0)
        controller.record_provider_failure("together")
        controller.record_provider_failure("together")
        # 2 failures dans window → encore CLOSED
        assert controller.get_circuit_status("together").state == CircuitState.CLOSED

    def test_per_provider_isolated(self, controller):
        for _ in range(3):
            controller.record_provider_failure("together")
        # deepinfra reste CLOSED
        controller.check_circuit_breaker("deepinfra")


# ─── admit() combined ────────────────────────────────────────────────────────


class TestAdmitCombined:
    def test_admit_ok_acquires_concurrency(self, controller):
        controller.admit("tenant_a", answer_shape="factual", provider="together")
        snap = controller.snapshot("tenant_a")
        assert snap["concurrency"]["active"] == 1

    def test_admit_fails_does_not_acquire(self, controller):
        # Tip d'abord le breaker
        for _ in range(3):
            controller.record_provider_failure("together")
        with pytest.raises(CircuitBreakerOpen):
            controller.admit("tenant_a", provider="together")
        # concurrency reste à 0
        snap = controller.snapshot("tenant_a")
        assert snap["concurrency"]["active"] == 0

    def test_rate_limit_blocks_admit(self, controller):
        for _ in range(5):
            controller.admit("tenant_a", answer_shape="factual")
            controller.release_concurrency_slot("tenant_a")
        # 6ème → rate limit (les slots concurrency sont libres)
        with pytest.raises(RateLimitExceeded):
            controller.admit("tenant_a", answer_shape="factual")


# ─── Snapshot ────────────────────────────────────────────────────────────────


class TestSnapshot:
    def test_snapshot_structure(self, controller):
        controller.check_rate_limit("tenant_a")
        controller.acquire_concurrency_slot("tenant_a")
        controller.check_daily_quota("tenant_a", "multi_hop")
        snap = controller.snapshot("tenant_a")
        assert snap["rate_limit"]["current_per_min"] == 1
        assert snap["concurrency"]["active"] == 1
        assert snap["daily_quota_complex"]["current"] == 1


# ─── Lenient config (dev) ────────────────────────────────────────────────────


class TestLenientConfig:
    def test_lenient_does_not_block(self):
        controller = AdmissionController(config=AdmissionConfig.lenient())
        for _ in range(50):
            controller.check_rate_limit("tenant_a")
        # No exception
