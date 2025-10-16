"""
🤖 OSMOSE Agentique - LLM Dispatcher

Rate limiting et orchestration appels LLM.
"""

from typing import Dict, Any, Optional, List
import logging
import time
from enum import Enum
from collections import deque
from pydantic import model_validator

from ..base import BaseAgent, AgentRole, AgentState, ToolInput, ToolOutput

logger = logging.getLogger(__name__)


class Priority(int, Enum):
    """Priorités pour queue LLM."""
    P0_RETRY = 0  # Retry après échec
    P1_FIRST_PASS = 1  # Premier passage
    P2_BATCH = 2  # Traitement batch


class DispatchLLMInput(ToolInput):
    """Input pour DispatchLLM tool."""
    model_tier: str = "SMALL"  # SMALL, BIG, VISION
    prompt: str
    priority: int = Priority.P1_FIRST_PASS
    max_tokens: int = 1500
    temperature: float = 0.3


class DispatchLLMOutput(ToolOutput):
    """Output pour DispatchLLM tool."""
    response: str = ""
    cost: float = 0.0
    latency_ms: int = 0

    @model_validator(mode='after')
    def sync_from_data(self):
        """Synchronise les attributs depuis data si data est fourni."""
        if self.data and not self.response:
            self.response = self.data.get("response", "")
        if self.data and not self.cost:
            self.cost = self.data.get("cost", 0.0)
        if self.data and not self.latency_ms:
            self.latency_ms = self.data.get("latency_ms", 0)
        return self


class GetQueueStatsInput(ToolInput):
    """Input pour GetQueueStats tool."""
    pass


class GetQueueStatsOutput(ToolOutput):
    """Output pour GetQueueStats tool."""
    queue_sizes: Dict[str, int] = {}
    active_calls: int = 0
    total_calls: int = 0
    error_rate: float = 0.0

    @model_validator(mode='after')
    def sync_from_data(self):
        """Synchronise les attributs depuis data si data est fourni."""
        if self.data and not self.queue_sizes:
            self.queue_sizes = self.data.get("queue_sizes", {})
        if self.data and not self.active_calls:
            self.active_calls = self.data.get("active_calls", 0)
        if self.data and not self.total_calls:
            self.total_calls = self.data.get("total_calls", 0)
        if self.data and not self.error_rate:
            self.error_rate = self.data.get("error_rate", 0.0)
        return self


class CircuitBreakerState(str, Enum):
    """États du circuit breaker."""
    CLOSED = "closed"  # Tout va bien
    OPEN = "open"  # Trop d'erreurs, suspend calls
    HALF_OPEN = "half_open"  # Test si service récupéré


class LLMDispatcher(BaseAgent):
    """
    LLM Dispatcher Agent.

    Responsabilités:
    - Rate limiting strict:
      * SMALL (gpt-4o-mini): 500 RPM
      * BIG (gpt-4o): 100 RPM
      * VISION (gpt-4o-vision): 50 RPM

    - Priority queue (3 niveaux):
      * P0 (RETRY): Retry après échec
      * P1 (FIRST_PASS): Premier passage
      * P2 (BATCH): Traitement batch

    - Concurrency control: Max 10 calls simultanées

    - Circuit breaker:
      * CLOSED: Normal operation
      * OPEN: Error rate > 30%, suspend 60s
      * HALF_OPEN: Test recovery après 60s

    Métriques temps-réel:
    - Queue size par priorité
    - Active calls count
    - Error rate (sliding window 100 calls)
    - P50/P95/P99 latency
    """

    # Rate limits (calls/minute)
    RATE_LIMITS = {
        "SMALL": 500,
        "BIG": 100,
        "VISION": 50
    }

    # Circuit breaker thresholds
    ERROR_THRESHOLD = 0.30  # 30%
    CIRCUIT_OPEN_DURATION = 60  # 60s

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        """Initialise le LLM Dispatcher."""
        super().__init__(AgentRole.DISPATCHER, config)

        # Override rate limits si config fournie
        if config:
            self.rate_limits = config.get("rate_limits", self.RATE_LIMITS)
            self.max_concurrent = config.get("max_concurrent", 10)
        else:
            self.rate_limits = self.RATE_LIMITS
            self.max_concurrent = 10

        # Priority queues (3 niveaux)
        self.queues: Dict[Priority, deque] = {
            Priority.P0_RETRY: deque(),
            Priority.P1_FIRST_PASS: deque(),
            Priority.P2_BATCH: deque()
        }

        # Rate limiting state (sliding window)
        self.call_timestamps: Dict[str, deque] = {
            "SMALL": deque(),
            "BIG": deque(),
            "VISION": deque()
        }

        # Circuit breaker state
        self.circuit_state = CircuitBreakerState.CLOSED
        self.circuit_opened_at: Optional[float] = None

        # Metrics
        self.active_calls = 0
        self.total_calls = 0
        self.error_count = 0
        self.recent_errors = deque(maxlen=100)  # Sliding window

        logger.info(
            f"[DISPATCHER] Initialized with rate limits SMALL={self.rate_limits['SMALL']}rpm, "
            f"BIG={self.rate_limits['BIG']}rpm, VISION={self.rate_limits['VISION']}rpm"
        )

    def _register_tools(self):
        """Enregistre les tools de l'agent."""
        self.tools = {
            "dispatch_llm": self._dispatch_llm_tool,
            "get_queue_stats": self._get_queue_stats_tool
        }

    async def execute(
        self,
        state: AgentState,
        instruction: Optional[str] = None
    ) -> AgentState:
        """
        Execute dispatcher (monitoring uniquement).

        Args:
            state: État actuel
            instruction: Ignored (agent passif)

        Returns:
            État inchangé
        """
        logger.info("[DISPATCHER] Monitoring LLM queue...")

        # Get stats
        stats_result = await self.call_tool("get_queue_stats", GetQueueStatsInput())

        if stats_result.success:
            # stats_result est déjà un GetQueueStatsOutput (hérite de ToolOutput)
            stats = stats_result
            logger.info(
                f"[DISPATCHER] Queue stats: active={stats.active_calls}, "
                f"total={stats.total_calls}, error_rate={stats.error_rate:.1%}"
            )

        return state

    def _dispatch_llm_tool(self, tool_input: DispatchLLMInput) -> ToolOutput:
        """
        Tool DispatchLLM: Enqueue et execute appel LLM.

        Algorithme:
        1. Vérifier circuit breaker (si OPEN, reject)
        2. Vérifier rate limit (si dépassé, wait)
        3. Vérifier concurrency (si max, queue)
        4. Exécuter appel LLM
        5. Mettre à jour métriques

        Args:
            tool_input: model_tier, prompt, priority, max_tokens, temperature

        Returns:
            response, cost, latency_ms
        """
        try:
            model_tier = tool_input.model_tier
            prompt = tool_input.prompt
            priority = Priority(tool_input.priority)

            # Étape 1: Vérifier circuit breaker
            if not self._check_circuit_breaker():
                logger.warning("[DISPATCHER:DispatchLLM] Circuit breaker OPEN, rejecting call")
                return ToolOutput(
                    success=False,
                    message="Circuit breaker OPEN, LLM service suspended"
                )

            # Étape 2: Vérifier rate limit
            if not self._check_rate_limit(model_tier):
                logger.warning(f"[DISPATCHER:DispatchLLM] Rate limit exceeded for {model_tier}")
                return ToolOutput(
                    success=False,
                    message=f"Rate limit exceeded for {model_tier}"
                )

            # Étape 3: Vérifier concurrency
            if self.active_calls >= self.max_concurrent:
                logger.warning("[DISPATCHER:DispatchLLM] Max concurrency reached, queueing")
                # TODO: Implémenter queue avec retry
                return ToolOutput(
                    success=False,
                    message="Max concurrency reached"
                )

            # Étape 4: Exécuter appel LLM (mock pour l'instant)
            start_time = time.time()

            # TODO: Appeler LLM réel via LLMRouter
            response = f"Mock LLM response for prompt: {prompt[:50]}..."
            cost = 0.002 if model_tier == "SMALL" else 0.015

            latency_ms = int((time.time() - start_time) * 1000)

            # Étape 5: Mettre à jour métriques
            self._record_call_success(model_tier)

            logger.debug(
                f"[DISPATCHER:DispatchLLM] {model_tier} call completed, "
                f"latency={latency_ms}ms, cost=${cost:.3f}"
            )

            return DispatchLLMOutput(
                success=True,
                message="LLM call completed",
                response=response,
                cost=cost,
                latency_ms=latency_ms,
                data={
                    "response": response,
                    "cost": cost,
                    "latency_ms": latency_ms
                }
            )

        except Exception as e:
            logger.error(f"[DISPATCHER:DispatchLLM] Error: {e}")

            # Record error pour circuit breaker
            self._record_call_error()

            return ToolOutput(
                success=False,
                message=f"LLM call failed: {str(e)}"
            )

    def _check_circuit_breaker(self) -> bool:
        """
        Vérifie état du circuit breaker.

        Returns:
            True si CLOSED (OK to proceed), False si OPEN
        """
        if self.circuit_state == CircuitBreakerState.CLOSED:
            return True

        elif self.circuit_state == CircuitBreakerState.OPEN:
            # Vérifier si 60s écoulées
            if self.circuit_opened_at:
                elapsed = time.time() - self.circuit_opened_at
                if elapsed >= self.CIRCUIT_OPEN_DURATION:
                    logger.info("[DISPATCHER] Circuit breaker transitioning to HALF_OPEN")
                    self.circuit_state = CircuitBreakerState.HALF_OPEN
                    return True

            return False  # Still OPEN

        elif self.circuit_state == CircuitBreakerState.HALF_OPEN:
            # Test call allowed
            return True

        return False

    def _check_rate_limit(self, model_tier: str) -> bool:
        """
        Vérifie rate limit pour model_tier.

        Args:
            model_tier: SMALL, BIG, VISION

        Returns:
            True si rate limit OK
        """
        now = time.time()
        timestamps = self.call_timestamps[model_tier]

        # Supprimer appels > 60s
        while timestamps and now - timestamps[0] > 60:
            timestamps.popleft()

        # Vérifier limite
        limit = self.rate_limits[model_tier]
        if len(timestamps) >= limit:
            return False

        # Enregistrer nouvel appel
        timestamps.append(now)
        return True

    def _record_call_success(self, model_tier: str):
        """Record successful LLM call."""
        self.total_calls += 1
        self.recent_errors.append(0)  # No error

        # Si HALF_OPEN, transition vers CLOSED
        if self.circuit_state == CircuitBreakerState.HALF_OPEN:
            logger.info("[DISPATCHER] Circuit breaker transitioning to CLOSED")
            self.circuit_state = CircuitBreakerState.CLOSED

    def _record_call_error(self):
        """Record failed LLM call."""
        self.total_calls += 1
        self.error_count += 1
        self.recent_errors.append(1)  # Error

        # Calculer error rate (sliding window 100 calls)
        error_rate = sum(self.recent_errors) / len(self.recent_errors)

        # Ouvrir circuit si error_rate > 30%
        if error_rate > self.ERROR_THRESHOLD and self.circuit_state == CircuitBreakerState.CLOSED:
            logger.error(f"[DISPATCHER] Circuit breaker OPENING (error_rate={error_rate:.1%})")
            self.circuit_state = CircuitBreakerState.OPEN
            self.circuit_opened_at = time.time()

    def _get_queue_stats_tool(self, tool_input: GetQueueStatsInput) -> ToolOutput:
        """
        Tool GetQueueStats: Retourne métriques queue.

        Returns:
            queue_sizes, active_calls, total_calls, error_rate
        """
        try:
            queue_sizes = {
                "P0_RETRY": len(self.queues[Priority.P0_RETRY]),
                "P1_FIRST_PASS": len(self.queues[Priority.P1_FIRST_PASS]),
                "P2_BATCH": len(self.queues[Priority.P2_BATCH])
            }

            error_rate = sum(self.recent_errors) / len(self.recent_errors) if self.recent_errors else 0.0

            return GetQueueStatsOutput(
                success=True,
                message="Queue stats retrieved",
                queue_sizes=queue_sizes,
                active_calls=self.active_calls,
                total_calls=self.total_calls,
                error_rate=error_rate,
                data={
                    "queue_sizes": queue_sizes,
                    "active_calls": self.active_calls,
                    "total_calls": self.total_calls,
                    "error_rate": error_rate
                }
            )

        except Exception as e:
            logger.error(f"[DISPATCHER:GetQueueStats] Error: {e}")
            return ToolOutput(
                success=False,
                message=f"GetQueueStats failed: {str(e)}"
            )
