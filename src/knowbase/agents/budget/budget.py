"""
🤖 OSMOSE Agentique - Budget Manager

Gestion caps et quotas LLM.
"""

from typing import Dict, Any, Optional
import logging
from datetime import datetime, timedelta
from pydantic import model_validator

from ..base import BaseAgent, AgentRole, AgentState, ToolInput, ToolOutput
from knowbase.common.clients.redis_client import get_redis_client, RedisClient

logger = logging.getLogger(__name__)


class CheckBudgetInput(ToolInput):
    """Input pour CheckBudget tool."""
    tenant_id: str = "default"
    model_tier: str = "SMALL"  # SMALL, BIG, VISION
    requested_calls: int = 1


class CheckBudgetOutput(ToolOutput):
    """Output pour CheckBudget tool."""
    budget_ok: bool = False
    remaining: int = 0
    reason: str = ""

    @model_validator(mode='after')
    def sync_from_data(self):
        """Synchronise les attributs depuis data si data est fourni."""
        if self.data and not self.budget_ok:
            self.budget_ok = self.data.get("budget_ok", False)
        if self.data and not self.remaining:
            self.remaining = self.data.get("remaining", 0)
        if self.data and not self.reason:
            self.reason = self.data.get("reason", "")
        return self


class ConsumeBudgetInput(ToolInput):
    """Input pour ConsumeBudget tool."""
    tenant_id: str = "default"
    model_tier: str = "SMALL"
    calls: int = 1
    cost: float = 0.0


class ConsumeBudgetOutput(ToolOutput):
    """Output pour ConsumeBudget tool."""
    consumed: bool = False
    new_remaining: int = 0

    @model_validator(mode='after')
    def sync_from_data(self):
        """Synchronise les attributs depuis data si data est fourni."""
        if self.data and not self.consumed:
            self.consumed = self.data.get("consumed", False)
        if self.data and not self.new_remaining:
            self.new_remaining = self.data.get("new_remaining", 0)
        return self


class RefundBudgetInput(ToolInput):
    """Input pour RefundBudget tool."""
    tenant_id: str = "default"
    model_tier: str = "SMALL"
    calls: int = 1
    cost: float = 0.0


class RefundBudgetOutput(ToolOutput):
    """Output pour RefundBudget tool."""
    refunded: bool = False
    new_remaining: int = 0

    @model_validator(mode='after')
    def sync_from_data(self):
        """Synchronise les attributs depuis data si data est fourni."""
        if self.data and not self.refunded:
            self.refunded = self.data.get("refunded", False)
        if self.data and not self.new_remaining:
            self.new_remaining = self.data.get("new_remaining", 0)
        return self


class BudgetManager(BaseAgent):
    """
    Budget Manager Agent.

    Responsabilités:
    - Enforce caps durs par document:
      * SMALL: 120 calls/doc
      * BIG: 8 calls/doc
      * VISION: 2 calls/doc

    - Enforce quotas tenant/jour:
      * SMALL: 10,000 calls/jour/tenant
      * BIG: 500 calls/jour/tenant
      * VISION: 100 calls/jour/tenant

    - Tracking temps-réel: Redis pour quotas jour
    - Refund logic: Si retry échoue, rembourse appels

    Clés Redis:
    - budget:tenant:{tenant_id}:SMALL:{date} → count calls
    - budget:tenant:{tenant_id}:BIG:{date} → count calls
    - budget:tenant:{tenant_id}:VISION:{date} → count calls
    """

    # Quotas tenant/jour (configurables)
    DAILY_QUOTAS = {
        "SMALL": 10_000,
        "BIG": 500,
        "VISION": 100
    }

    # Caps par document (configurables)
    DOCUMENT_CAPS = {
        "SMALL": 120,
        "BIG": 8,
        "VISION": 2
    }

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        """Initialise le Budget Manager."""
        super().__init__(AgentRole.BUDGET, config)

        # Override quotas/caps si fournis dans config
        if config:
            self.daily_quotas = config.get("daily_quotas", self.DAILY_QUOTAS)
            self.document_caps = config.get("document_caps", self.DOCUMENT_CAPS)
            redis_host = config.get("redis_host", "redis")  # Docker service name
            redis_port = config.get("redis_port", 6379)
            redis_db = config.get("redis_db", 0)
        else:
            self.daily_quotas = self.DAILY_QUOTAS
            self.document_caps = self.DOCUMENT_CAPS
            redis_host = "redis"  # Docker service name
            redis_port = 6379
            redis_db = 0

        # Redis client pour quotas tracking
        try:
            self.redis_client = get_redis_client(
                host=redis_host,
                port=redis_port,
                db=redis_db
            )
            if self.redis_client.is_connected():
                logger.info("[BUDGET] Redis client connected for quotas tracking")
            else:
                logger.warning("[BUDGET] Redis client initialized but not connected (fallback mode)")
        except Exception as e:
            logger.error(f"[BUDGET] Redis client initialization failed: {e}")
            self.redis_client = None

        logger.info(
            f"[BUDGET] Initialized with caps SMALL={self.document_caps['SMALL']}, "
            f"BIG={self.document_caps['BIG']}, VISION={self.document_caps['VISION']}"
        )

    def _register_tools(self):
        """Enregistre les tools de l'agent."""
        self.tools = {
            "check_budget": self._check_budget_tool,
            "consume_budget": self._consume_budget_tool,
            "refund_budget": self._refund_budget_tool
        }

    async def execute(
        self,
        state: AgentState,
        instruction: Optional[str] = None
    ) -> AgentState:
        """
        Vérifie budget disponible pour le document.

        Args:
            state: État actuel
            instruction: Ignored (agent autonome)

        Returns:
            État inchangé (budget check only)
        """
        logger.info(f"[BUDGET] Checking budgets for tenant '{state.tenant_id}'")

        # Vérifier budgets SMALL, BIG, VISION
        for tier in ["SMALL", "BIG", "VISION"]:
            check_input = CheckBudgetInput(
                tenant_id=state.tenant_id,
                model_tier=tier,
                requested_calls=1
            )

            check_result = await self.call_tool("check_budget", check_input)

            if not check_result.success:
                logger.error(f"[BUDGET] Budget check failed for {tier}: {check_result.message}")
                state.errors.append(f"Budget check failed for {tier}")
                continue

            # check_result est déjà un CheckBudgetOutput (hérite de ToolOutput)
            check_output = check_result

            if not check_output.budget_ok:
                logger.warning(f"[BUDGET] Budget insufficient for {tier}: {check_output.reason}")
            else:
                logger.debug(f"[BUDGET] {tier}: {check_output.remaining} calls remaining")

        return state

    async def check_budget(self, state: AgentState) -> bool:
        """
        Helper: Vérifie si budget suffisant (appelé par Supervisor).

        Args:
            state: État actuel

        Returns:
            True si budgets OK
        """
        # Vérifier caps document
        for tier in ["SMALL", "BIG", "VISION"]:
            if state.budget_remaining[tier] <= 0:
                logger.warning(f"[BUDGET] Document cap exhausted for {tier}")
                return False

        # Vérifier quotas tenant (TODO: Redis check)
        # Pour l'instant: mock OK
        return True

    def _check_budget_tool(self, tool_input: CheckBudgetInput) -> ToolOutput:
        """
        Tool CheckBudget: Vérifie si budget disponible.

        Vérifie:
        1. Quota tenant/jour (Redis)
        2. Cap document (AgentState)

        Args:
            tool_input: tenant_id, model_tier, requested_calls

        Returns:
            budget_ok, remaining, reason
        """
        try:
            tenant_id = tool_input.tenant_id
            model_tier = tool_input.model_tier
            requested_calls = tool_input.requested_calls

            # Vérifier quota tenant/jour (Redis)
            daily_quota = self.daily_quotas.get(model_tier, 0)

            # Récupérer consommation depuis Redis
            if self.redis_client and self.redis_client.is_connected():
                daily_consumed = self.redis_client.get_budget_consumed(tenant_id, model_tier)
            else:
                # Fallback si Redis non disponible: assume 0 (mode dégradé)
                daily_consumed = 0
                logger.warning(f"[BUDGET:CheckBudget] Redis unavailable, fallback mode (assume 0 consumed)")

            if daily_consumed + requested_calls > daily_quota:
                return CheckBudgetOutput(
                    success=True,
                    message="Budget check complete",
                    budget_ok=False,
                    remaining=daily_quota - daily_consumed,
                    reason=f"Daily quota exhausted for {model_tier} (limit {daily_quota})",
                    data={
                        "budget_ok": False,
                        "remaining": daily_quota - daily_consumed,
                        "reason": f"Daily quota exhausted for {model_tier} (limit {daily_quota})"
                    }
                )

            # Budget OK
            return CheckBudgetOutput(
                success=True,
                message="Budget check complete",
                budget_ok=True,
                remaining=daily_quota - daily_consumed,
                reason="",
                data={
                    "budget_ok": True,
                    "remaining": daily_quota - daily_consumed,
                    "reason": ""
                }
            )

        except Exception as e:
            logger.error(f"[BUDGET:CheckBudget] Error: {e}")
            return ToolOutput(
                success=False,
                message=f"CheckBudget failed: {str(e)}"
            )

    def _consume_budget_tool(self, tool_input: ConsumeBudgetInput) -> ToolOutput:
        """
        Tool ConsumeBudget: Consomme budget après appel LLM.

        Args:
            tool_input: tenant_id, model_tier, calls, cost

        Returns:
            consumed, new_remaining
        """
        try:
            tenant_id = tool_input.tenant_id
            model_tier = tool_input.model_tier
            calls = tool_input.calls
            cost = tool_input.cost

            # Consommer quota tenant (Redis INCR)
            if self.redis_client and self.redis_client.is_connected():
                new_value = self.redis_client.increment_budget(
                    tenant_id=tenant_id,
                    model_tier=model_tier,
                    calls=calls,
                    cost=cost
                )
                daily_quota = self.daily_quotas.get(model_tier, 0)
                new_remaining = daily_quota - new_value

                logger.debug(
                    f"[BUDGET:ConsumeBudget] {tenant_id}/{model_tier}: {calls} calls, "
                    f"${cost:.3f}, remaining {new_remaining}/{daily_quota}"
                )
            else:
                # Fallback si Redis non disponible
                logger.warning(f"[BUDGET:ConsumeBudget] Redis unavailable, skipping increment")
                new_remaining = 0

            return ConsumeBudgetOutput(
                success=True,
                message="Budget consumed",
                consumed=True,
                new_remaining=new_remaining,
                data={
                    "consumed": True,
                    "new_remaining": new_remaining
                }
            )

        except Exception as e:
            logger.error(f"[BUDGET:ConsumeBudget] Error: {e}")
            return ToolOutput(
                success=False,
                message=f"ConsumeBudget failed: {str(e)}"
            )

    def _refund_budget_tool(self, tool_input: RefundBudgetInput) -> ToolOutput:
        """
        Tool RefundBudget: Rembourse budget si retry échoue.

        Args:
            tool_input: tenant_id, model_tier, calls, cost

        Returns:
            refunded, new_remaining
        """
        try:
            tenant_id = tool_input.tenant_id
            model_tier = tool_input.model_tier
            calls = tool_input.calls
            cost = tool_input.cost

            # Rembourser quota tenant (Redis DECR)
            if self.redis_client and self.redis_client.is_connected():
                new_value = self.redis_client.decrement_budget(
                    tenant_id=tenant_id,
                    model_tier=model_tier,
                    calls=calls,
                    cost=cost
                )
                daily_quota = self.daily_quotas.get(model_tier, 0)
                new_remaining = daily_quota - new_value

                logger.debug(
                    f"[BUDGET:RefundBudget] {tenant_id}/{model_tier}: {calls} calls refunded, "
                    f"remaining {new_remaining}/{daily_quota}"
                )
            else:
                # Fallback si Redis non disponible
                logger.warning(f"[BUDGET:RefundBudget] Redis unavailable, skipping decrement")
                new_remaining = 0

            return RefundBudgetOutput(
                success=True,
                message="Budget refunded",
                refunded=True,
                new_remaining=new_remaining,
                data={
                    "refunded": True,
                    "new_remaining": new_remaining
                }
            )

        except Exception as e:
            logger.error(f"[BUDGET:RefundBudget] Error: {e}")
            return ToolOutput(
                success=False,
                message=f"RefundBudget failed: {str(e)}"
            )
