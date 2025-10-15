"""
🤖 OSMOSE Agentique - Budget Manager

Gestion caps et quotas LLM.
"""

from typing import Dict, Any, Optional
import logging
from datetime import datetime, timedelta

from ..base import BaseAgent, AgentRole, AgentState, ToolInput, ToolOutput

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
        else:
            self.daily_quotas = self.DAILY_QUOTAS
            self.document_caps = self.DOCUMENT_CAPS

        # Redis client (TODO: Intégrer Redis)
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

            check_result = self.call_tool("check_budget", check_input)

            if not check_result.success:
                logger.error(f"[BUDGET] Budget check failed for {tier}: {check_result.message}")
                state.errors.append(f"Budget check failed for {tier}")
                continue

            check_output = CheckBudgetOutput(**check_result.data)

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

            # Vérifier quota tenant/jour (mock pour l'instant)
            daily_quota = self.daily_quotas.get(model_tier, 0)
            daily_consumed = 0  # TODO: Redis GET budget:tenant:{tenant_id}:{tier}:{date}

            if daily_consumed + requested_calls > daily_quota:
                return ToolOutput(
                    success=True,
                    message="Budget check complete",
                    data={
                        "budget_ok": False,
                        "remaining": daily_quota - daily_consumed,
                        "reason": f"Daily quota exhausted for {model_tier} (limit {daily_quota})"
                    }
                )

            # Budget OK
            return ToolOutput(
                success=True,
                message="Budget check complete",
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
            # TODO: Redis INCR budget:tenant:{tenant_id}:{tier}:{date}

            logger.debug(f"[BUDGET:ConsumeBudget] {tenant_id}/{model_tier}: {calls} calls, ${cost:.3f}")

            return ToolOutput(
                success=True,
                message="Budget consumed",
                data={
                    "consumed": True,
                    "new_remaining": 0  # TODO: Calculer depuis Redis
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
            # TODO: Redis DECR budget:tenant:{tenant_id}:{tier}:{date}

            logger.debug(f"[BUDGET:RefundBudget] {tenant_id}/{model_tier}: {calls} calls refunded")

            return ToolOutput(
                success=True,
                message="Budget refunded",
                data={
                    "refunded": True,
                    "new_remaining": 0  # TODO: Calculer depuis Redis
                }
            )

        except Exception as e:
            logger.error(f"[BUDGET:RefundBudget] Error: {e}")
            return ToolOutput(
                success=False,
                message=f"RefundBudget failed: {str(e)}"
            )
