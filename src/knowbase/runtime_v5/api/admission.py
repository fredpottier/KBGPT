"""V5 AdmissionController — rate limit + concurrency + circuit breaker.

ADR V1.5 §3a + §3h : protège les ressources partagées AVANT l'agent.

Mécaniques :
1. **Rate limit** : sliding window par tenant
   - 10 req/min/tenant (configurable)
   - 50 q/jour/tenant pour shapes complexes (configurable)

2. **Concurrency budget** : N requêtes simultanées max par tenant
   - default 3/tenant (premium peuvent négocier)
   - acquire() avant exec / release() en finally

3. **Circuit breaker provider** : track failures sur les LLM providers
   - 3 failures consécutifs sur 60s → OPEN circuit (failover possible)
   - Auto-close après 60s en HALF_OPEN puis success → CLOSED

Backend : in-memory par défaut, Redis-backed via option pour multi-instance.
Pour les tests : `InMemoryAdmissionBackend` (déterministe, time-faked).
Pour la prod : `RedisAdmissionBackend` (à brancher quand on industrialise).

Domain-agnostic : aucune dépendance corpus-spécifique.
"""
from __future__ import annotations

import logging
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from enum import Enum
from typing import Callable, Optional

logger = logging.getLogger(__name__)


# ─── Errors ──────────────────────────────────────────────────────────────────


class AdmissionError(Exception):
    """Levée quand l'admission est refusée."""
    def __init__(self, reason: str, retry_after_s: Optional[float] = None):
        self.reason = reason
        self.retry_after_s = retry_after_s
        super().__init__(f"AdmissionDenied: {reason}")


class RateLimitExceeded(AdmissionError):
    pass


class ConcurrencyBudgetExceeded(AdmissionError):
    pass


class DailyQuotaExceeded(AdmissionError):
    pass


class CircuitBreakerOpen(AdmissionError):
    pass


# ─── Circuit breaker states ──────────────────────────────────────────────────


class CircuitState(str, Enum):
    CLOSED = "closed"  # tout marche, requests pass
    OPEN = "open"  # breaker trip, requests refusées
    HALF_OPEN = "half_open"  # test de récupération


@dataclass
class CircuitBreakerStatus:
    state: CircuitState
    failures: int
    last_failure_at: Optional[float]
    opened_at: Optional[float]
    half_open_at: Optional[float]


# ─── Time provider abstraction (testable) ────────────────────────────────────


class TimeProvider:
    """Abstraction time.monotonic() pour rendre les tests déterministes."""
    def now(self) -> float:
        return time.monotonic()


class FakeTimeProvider(TimeProvider):
    """Time provider scriptable pour tests."""
    def __init__(self, start: float = 0.0):
        self._t = start

    def now(self) -> float:
        return self._t

    def advance(self, seconds: float) -> None:
        self._t += seconds


# ─── AdmissionController ─────────────────────────────────────────────────────


@dataclass
class AdmissionConfig:
    """Configuration limites admission (configurable per-tenant)."""
    rate_limit_per_min: int = 10
    daily_quota_complex: int = 50  # /jour/tenant shape=complex
    concurrency_budget: int = 3  # requêtes simultanées max
    breaker_failure_threshold: int = 3
    breaker_window_s: float = 60.0
    breaker_open_duration_s: float = 60.0

    @staticmethod
    def lenient() -> AdmissionConfig:
        """Config souple pour dev/tests."""
        return AdmissionConfig(
            rate_limit_per_min=1000,
            daily_quota_complex=10_000,
            concurrency_budget=100,
        )


# Shapes considérés "complexes" pour le quota daily
COMPLEX_SHAPES = frozenset({
    "multi_hop", "comparison", "lifecycle", "causal", "quantitative",
})


class AdmissionController:
    """Garde-fou amont de l'agent.

    Thread-safe via lock unique. Pour multi-instance : utiliser RedisBackend.
    """

    def __init__(
        self,
        config: Optional[AdmissionConfig] = None,
        time_provider: Optional[TimeProvider] = None,
    ):
        self.config = config or AdmissionConfig()
        self.time = time_provider or TimeProvider()
        self._lock = threading.RLock()
        # State per-tenant
        self._req_timestamps: dict[str, deque[float]] = {}  # rate limit sliding window
        self._daily_complex_count: dict[str, int] = {}  # daily quota
        self._daily_reset_at: dict[str, float] = {}  # ts epoch when daily window resets
        self._concurrency_active: dict[str, int] = {}
        # Circuit breaker per-provider
        self._cb_state: dict[str, CircuitState] = {}
        self._cb_failures: dict[str, deque[float]] = {}
        self._cb_opened_at: dict[str, Optional[float]] = {}

    # ─── Rate limit ──────────────────────────────────────────────────────────

    def _trim_window(self, deque_ts: deque[float], window_s: float, now: float):
        cutoff = now - window_s
        while deque_ts and deque_ts[0] < cutoff:
            deque_ts.popleft()

    def check_rate_limit(self, tenant_id: str) -> None:
        """Vérifie + enregistre 1 req pour le rate limit /min."""
        with self._lock:
            now = self.time.now()
            ts = self._req_timestamps.setdefault(tenant_id, deque())
            self._trim_window(ts, 60.0, now)
            if len(ts) >= self.config.rate_limit_per_min:
                # Retry after = quand la 1ère req sort de la window
                retry_after = max(0.0, 60.0 - (now - ts[0]))
                raise RateLimitExceeded(
                    f"tenant '{tenant_id}' rate_limit "
                    f"{len(ts)}/{self.config.rate_limit_per_min} req/min",
                    retry_after_s=retry_after,
                )
            ts.append(now)

    # ─── Daily quota (shape=complex) ─────────────────────────────────────────

    def check_daily_quota(self, tenant_id: str, answer_shape: Optional[str]) -> None:
        if not answer_shape or answer_shape.lower() not in COMPLEX_SHAPES:
            return  # Non-complex : pas de quota daily
        with self._lock:
            now = self.time.now()
            # Reset window if 24h elapsed
            reset_at = self._daily_reset_at.get(tenant_id, 0.0)
            if now >= reset_at:
                self._daily_reset_at[tenant_id] = now + 86400.0
                self._daily_complex_count[tenant_id] = 0
            count = self._daily_complex_count.get(tenant_id, 0)
            if count >= self.config.daily_quota_complex:
                retry_after = max(0.0, self._daily_reset_at[tenant_id] - now)
                raise DailyQuotaExceeded(
                    f"tenant '{tenant_id}' daily_quota_complex "
                    f"{count}/{self.config.daily_quota_complex}",
                    retry_after_s=retry_after,
                )
            self._daily_complex_count[tenant_id] = count + 1

    # ─── Concurrency budget ──────────────────────────────────────────────────

    def acquire_concurrency_slot(self, tenant_id: str) -> None:
        """Acquire 1 slot. Raise si dépassement."""
        with self._lock:
            active = self._concurrency_active.get(tenant_id, 0)
            if active >= self.config.concurrency_budget:
                raise ConcurrencyBudgetExceeded(
                    f"tenant '{tenant_id}' concurrency "
                    f"{active}/{self.config.concurrency_budget}",
                )
            self._concurrency_active[tenant_id] = active + 1

    def release_concurrency_slot(self, tenant_id: str) -> None:
        """Release 1 slot. Idempotent (no underflow)."""
        with self._lock:
            active = self._concurrency_active.get(tenant_id, 0)
            self._concurrency_active[tenant_id] = max(0, active - 1)

    # ─── Circuit breaker ─────────────────────────────────────────────────────

    def check_circuit_breaker(self, provider: str) -> None:
        """Vérifie l'état du breaker. Raise si OPEN (avant qu'on tente une call)."""
        with self._lock:
            now = self.time.now()
            state = self._cb_state.get(provider, CircuitState.CLOSED)
            if state == CircuitState.OPEN:
                opened_at = self._cb_opened_at.get(provider) or now
                if now - opened_at >= self.config.breaker_open_duration_s:
                    # Promote to HALF_OPEN : 1 essai autorisé
                    self._cb_state[provider] = CircuitState.HALF_OPEN
                    logger.info(
                        f"[CircuitBreaker] {provider} OPEN→HALF_OPEN after "
                        f"{self.config.breaker_open_duration_s}s"
                    )
                else:
                    retry_after = self.config.breaker_open_duration_s - (now - opened_at)
                    raise CircuitBreakerOpen(
                        f"provider '{provider}' breaker OPEN, "
                        f"retry in {retry_after:.1f}s",
                        retry_after_s=retry_after,
                    )

    def record_provider_success(self, provider: str) -> None:
        """À appeler après un call provider réussi."""
        with self._lock:
            state = self._cb_state.get(provider, CircuitState.CLOSED)
            if state == CircuitState.HALF_OPEN:
                # Recovery confirmed → close
                self._cb_state[provider] = CircuitState.CLOSED
                self._cb_failures[provider] = deque()
                self._cb_opened_at[provider] = None
                logger.info(f"[CircuitBreaker] {provider} HALF_OPEN→CLOSED (recovered)")
            elif state == CircuitState.OPEN:
                # Theoretically shouldn't happen — pass
                pass
            # Clear partial failures on success
            self._cb_failures.setdefault(provider, deque())
            # Don't clear all failures, just trim window
            now = self.time.now()
            self._trim_window(
                self._cb_failures[provider],
                self.config.breaker_window_s, now,
            )

    def record_provider_failure(self, provider: str) -> CircuitBreakerStatus:
        """À appeler après un call provider échoué.

        Trip le breaker si N failures dans window_s.
        Returns status post-update.
        """
        with self._lock:
            now = self.time.now()
            failures = self._cb_failures.setdefault(provider, deque())
            self._trim_window(failures, self.config.breaker_window_s, now)
            failures.append(now)

            state = self._cb_state.get(provider, CircuitState.CLOSED)
            if state == CircuitState.HALF_OPEN:
                # Recovery failed → re-open
                self._cb_state[provider] = CircuitState.OPEN
                self._cb_opened_at[provider] = now
                logger.warning(
                    f"[CircuitBreaker] {provider} HALF_OPEN→OPEN (recovery failed)"
                )
            elif state == CircuitState.CLOSED and len(failures) >= self.config.breaker_failure_threshold:
                # Trip the breaker
                self._cb_state[provider] = CircuitState.OPEN
                self._cb_opened_at[provider] = now
                logger.warning(
                    f"[CircuitBreaker] {provider} CLOSED→OPEN ({len(failures)} "
                    f"failures in {self.config.breaker_window_s}s)"
                )

            return CircuitBreakerStatus(
                state=self._cb_state.get(provider, CircuitState.CLOSED),
                failures=len(failures),
                last_failure_at=now,
                opened_at=self._cb_opened_at.get(provider),
                half_open_at=None,
            )

    def get_circuit_status(self, provider: str) -> CircuitBreakerStatus:
        """Status read-only."""
        with self._lock:
            return CircuitBreakerStatus(
                state=self._cb_state.get(provider, CircuitState.CLOSED),
                failures=len(self._cb_failures.get(provider, [])),
                last_failure_at=None,
                opened_at=self._cb_opened_at.get(provider),
                half_open_at=None,
            )

    # ─── Combined admission check ───────────────────────────────────────────

    def admit(
        self,
        tenant_id: str,
        answer_shape: Optional[str] = None,
        provider: Optional[str] = None,
    ) -> None:
        """Check rate_limit + daily_quota + concurrency + breaker.

        Acquire un concurrency slot si OK. À release via release_concurrency_slot.

        Raises:
            RateLimitExceeded / DailyQuotaExceeded / ConcurrencyBudgetExceeded /
            CircuitBreakerOpen
        """
        self.check_rate_limit(tenant_id)
        self.check_daily_quota(tenant_id, answer_shape)
        if provider:
            self.check_circuit_breaker(provider)
        self.acquire_concurrency_slot(tenant_id)

    # ─── Stats / snapshot ────────────────────────────────────────────────────

    def snapshot(self, tenant_id: str) -> dict:
        """État courant pour un tenant (debug/cockpit)."""
        with self._lock:
            now = self.time.now()
            ts = self._req_timestamps.get(tenant_id, deque())
            self._trim_window(ts, 60.0, now)
            return {
                "tenant_id": tenant_id,
                "rate_limit": {
                    "current_per_min": len(ts),
                    "max": self.config.rate_limit_per_min,
                },
                "daily_quota_complex": {
                    "current": self._daily_complex_count.get(tenant_id, 0),
                    "max": self.config.daily_quota_complex,
                    "reset_at": self._daily_reset_at.get(tenant_id),
                },
                "concurrency": {
                    "active": self._concurrency_active.get(tenant_id, 0),
                    "budget": self.config.concurrency_budget,
                },
            }
