"""
Circuit Breaker Pattern - Phase 0.5 P1.6

Prévient cascading failures sur services externes (LLM, Qdrant):
- États: CLOSED (normal), OPEN (fail), HALF_OPEN (recovery test)
- Ouvre circuit après N échecs consécutifs
- Recovery automatique après timeout
- Fail fast si circuit OPEN (évite latence)

Usage:
    breaker = CircuitBreaker(failure_threshold=5, recovery_timeout=60)

    @breaker.call
    def call_llm():
        return llm.complete(...)
"""

import time
import logging
from enum import Enum
from typing import Callable, Any
from functools import wraps

logger = logging.getLogger(__name__)


class CircuitState(str, Enum):
    """États du circuit breaker"""
    CLOSED = "closed"        # Normal, requêtes passent
    OPEN = "open"            # Circuit ouvert, fail fast
    HALF_OPEN = "half_open"  # Test recovery, 1 requête autorisée


class CircuitBreakerOpenError(Exception):
    """Exception levée quand circuit ouvert"""
    pass


class CircuitBreaker:
    """
    Circuit breaker pattern pour services externes

    - CLOSED: Requêtes passent normalement
    - OPEN: Fail fast après N échecs (évite timeout)
    - HALF_OPEN: Test recovery après timeout
    """

    def __init__(
        self,
        name: str = "default",
        failure_threshold: int = 5,
        recovery_timeout: int = 60,
        success_threshold: int = 2
    ):
        """
        Args:
            name: Nom du circuit (ex: "llm", "qdrant")
            failure_threshold: Nombre échecs avant OPEN
            recovery_timeout: Secondes avant test recovery
            success_threshold: Succès requis en HALF_OPEN avant CLOSED
        """
        self.name = name
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.success_threshold = success_threshold

        self.state = CircuitState.CLOSED
        self.failure_count = 0
        self.success_count = 0
        self.last_failure_time = None

        logger.info(
            f"CircuitBreaker '{name}': "
            f"threshold={failure_threshold}, timeout={recovery_timeout}s"
        )

    def call(self, func: Callable) -> Callable:
        """Décorateur pour protéger fonction avec circuit breaker"""
        @wraps(func)
        def wrapper(*args, **kwargs) -> Any:
            # Vérifier si circuit ouvert
            if self.state == CircuitState.OPEN:
                if self._should_attempt_reset():
                    self._transition_to_half_open()
                else:
                    logger.warning(
                        f"⚡ Circuit '{self.name}' OPEN - fail fast "
                        f"(failures={self.failure_count})"
                    )
                    raise CircuitBreakerOpenError(
                        f"Circuit breaker '{self.name}' is OPEN"
                    )

            try:
                # Exécuter fonction
                result = func(*args, **kwargs)
                self._on_success()
                return result

            except Exception as e:
                self._on_failure(e)
                raise

        return wrapper

    def _should_attempt_reset(self) -> bool:
        """Vérifier si timeout recovery atteint"""
        if not self.last_failure_time:
            return False
        return (time.time() - self.last_failure_time) >= self.recovery_timeout

    def _transition_to_half_open(self):
        """Passer en HALF_OPEN pour tester recovery"""
        self.state = CircuitState.HALF_OPEN
        self.success_count = 0
        logger.info(f"🔄 Circuit '{self.name}': OPEN → HALF_OPEN (testing recovery)")
        # Métrique Prometheus
        try:
            from knowbase.common.metrics import update_circuit_breaker_metric
            update_circuit_breaker_metric(self.name, "half_open")
        except ImportError:
            pass

    def _on_success(self):
        """Gérer succès fonction"""
        if self.state == CircuitState.HALF_OPEN:
            self.success_count += 1
            if self.success_count >= self.success_threshold:
                self._transition_to_closed()
        elif self.state == CircuitState.CLOSED:
            # Reset failure count sur succès
            self.failure_count = 0

    def _on_failure(self, exception: Exception):
        """Gérer échec fonction"""
        self.failure_count += 1
        self.last_failure_time = time.time()

        if self.state == CircuitState.HALF_OPEN:
            # Échec en HALF_OPEN → retour OPEN
            self._transition_to_open()
        elif self.state == CircuitState.CLOSED:
            if self.failure_count >= self.failure_threshold:
                self._transition_to_open()

        logger.warning(
            f"⚠️ Circuit '{self.name}' failure {self.failure_count}/{self.failure_threshold}: "
            f"{type(exception).__name__}"
        )

    def _transition_to_open(self):
        """Ouvrir circuit après trop d'échecs"""
        self.state = CircuitState.OPEN
        logger.error(
            f"⚡ Circuit '{self.name}': CLOSED → OPEN "
            f"(failures={self.failure_count} ≥ {self.failure_threshold})"
        )
        # Métrique Prometheus
        try:
            from knowbase.common.metrics import update_circuit_breaker_metric
            update_circuit_breaker_metric(self.name, "open")
        except ImportError:
            pass

    def _transition_to_closed(self):
        """Fermer circuit après recovery réussie"""
        self.state = CircuitState.CLOSED
        self.failure_count = 0
        self.success_count = 0
        logger.info(f"✅ Circuit '{self.name}': HALF_OPEN → CLOSED (recovered)")
        # Métrique Prometheus
        try:
            from knowbase.common.metrics import update_circuit_breaker_metric
            update_circuit_breaker_metric(self.name, "closed")
        except ImportError:
            pass

    def get_state(self) -> dict:
        """Récupérer état actuel du circuit"""
        return {
            "name": self.name,
            "state": self.state.value,
            "failure_count": self.failure_count,
            "success_count": self.success_count,
            "last_failure_time": self.last_failure_time
        }


# Circuit breakers globaux pour services externes
llm_circuit_breaker = CircuitBreaker(
    name="llm",
    failure_threshold=5,
    recovery_timeout=60
)

qdrant_circuit_breaker = CircuitBreaker(
    name="qdrant",
    failure_threshold=3,
    recovery_timeout=30
)
