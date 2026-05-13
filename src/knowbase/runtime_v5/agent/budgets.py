"""V5 ReasoningAgent — Separate hard caps (Sprint S4.2).

ADR V1.5 §3e : 4 budgets indépendants pour empêcher qu'un seul axe
(par exemple un tool qui retourne 500k chars) ne fasse exploser tout.

Budgets :
- max_iterations : 8 default, 12 hard cap
- max_tool_calls : 25 default, 40 hard cap
- max_retrieved_chars : 50k default, 120k hard cap
- max_output_tokens : 4k default, 8k hard cap

Budget adaptatif par answer_shape :
- factual : 3 iter, 8 tools, 20k chars, 3k tokens
- listing : 5 iter, 12 tools, 35k chars, 4k tokens
- multi_hop / lifecycle / causal / comparison : 8 iter, 25 tools, 50k chars, 5k tokens
- contextual / unanswerable / false_premise : 5 iter, 15 tools, 30k chars, 3k tokens
- HARD CAP absolu : 12 iter, 40 tools, 120k chars, 8k tokens

Charte domain-agnostic : aucune dépendance à un domaine. answer_shape provient
du classifier DeBERTa S2 (S0.5 - voir CH-52.1).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class BudgetExceeded(Exception):
    """Levée quand un budget est dépassé. Inclut le nom du budget violé."""
    def __init__(self, budget_name: str, current: int, cap: int):
        self.budget_name = budget_name
        self.current = current
        self.cap = cap
        super().__init__(f"Budget '{budget_name}' exceeded: {current} > {cap}")


# ─── Hard caps absolus (jamais dépassables) ──────────────────────────────────


HARD_CAP_ITER = 12
HARD_CAP_TOOL_CALLS = 40
HARD_CAP_RETRIEVED_CHARS = 120_000
HARD_CAP_OUTPUT_TOKENS = 8_000


# ─── Default budgets per answer_shape ────────────────────────────────────────


@dataclass(frozen=True)
class ShapeBudget:
    """Budget par answer_shape (immutable)."""
    max_iterations: int
    max_tool_calls: int
    max_retrieved_chars: int
    max_output_tokens: int


# Mapping answer_shape → ShapeBudget. Shapes du classifier DeBERTa S2.
# Si shape inconnu/None → DEFAULT_SHAPE_BUDGET (multi_hop = profil moyen).
SHAPE_BUDGETS: dict[str, ShapeBudget] = {
    "factual": ShapeBudget(
        max_iterations=3, max_tool_calls=8,
        max_retrieved_chars=20_000, max_output_tokens=3_000,
    ),
    "factual_simple": ShapeBudget(
        max_iterations=3, max_tool_calls=8,
        max_retrieved_chars=20_000, max_output_tokens=3_000,
    ),
    "listing": ShapeBudget(
        max_iterations=5, max_tool_calls=12,
        max_retrieved_chars=35_000, max_output_tokens=4_000,
    ),
    "multi_hop": ShapeBudget(
        max_iterations=8, max_tool_calls=25,
        max_retrieved_chars=50_000, max_output_tokens=5_000,
    ),
    "lifecycle": ShapeBudget(
        max_iterations=8, max_tool_calls=25,
        max_retrieved_chars=50_000, max_output_tokens=5_000,
    ),
    "causal": ShapeBudget(
        max_iterations=8, max_tool_calls=25,
        max_retrieved_chars=50_000, max_output_tokens=5_000,
    ),
    "comparison": ShapeBudget(
        max_iterations=8, max_tool_calls=25,
        max_retrieved_chars=50_000, max_output_tokens=5_000,
    ),
    "quantitative": ShapeBudget(
        max_iterations=8, max_tool_calls=25,
        max_retrieved_chars=50_000, max_output_tokens=5_000,
    ),
    "contextual": ShapeBudget(
        max_iterations=5, max_tool_calls=15,
        max_retrieved_chars=30_000, max_output_tokens=3_000,
    ),
    "unanswerable": ShapeBudget(
        max_iterations=5, max_tool_calls=15,
        max_retrieved_chars=30_000, max_output_tokens=3_000,
    ),
    "false_premise": ShapeBudget(
        max_iterations=5, max_tool_calls=15,
        max_retrieved_chars=30_000, max_output_tokens=3_000,
    ),
    "negation": ShapeBudget(
        max_iterations=5, max_tool_calls=15,
        max_retrieved_chars=30_000, max_output_tokens=3_000,
    ),
}

DEFAULT_SHAPE_BUDGET = SHAPE_BUDGETS["multi_hop"]  # fallback : profil moyen


def get_shape_budget(answer_shape: Optional[str]) -> ShapeBudget:
    """Retourne le ShapeBudget pour answer_shape (default si inconnu)."""
    if not answer_shape:
        return DEFAULT_SHAPE_BUDGET
    return SHAPE_BUDGETS.get(answer_shape.lower(), DEFAULT_SHAPE_BUDGET)


# ─── BudgetTracker ──────────────────────────────────────────────────────────


@dataclass
class BudgetTracker:
    """Suit les 4 axes indépendamment, vérifie cap et signale dépassements.

    Args:
        shape : answer_shape (configure les budgets soft initiaux)
        override_max_iterations : optionnel, force ce budget (utile tests / config)
        override_max_tool_calls : idem
        override_max_retrieved_chars : idem
        override_max_output_tokens : idem
    """
    shape: Optional[str] = None
    override_max_iterations: Optional[int] = None
    override_max_tool_calls: Optional[int] = None
    override_max_retrieved_chars: Optional[int] = None
    override_max_output_tokens: Optional[int] = None

    # Counters (incremental)
    iterations: int = 0
    tool_calls: int = 0
    retrieved_chars: int = 0
    output_tokens: int = 0

    # Auto-init from shape
    soft_caps: ShapeBudget = field(init=False)

    def __post_init__(self):
        base = get_shape_budget(self.shape)
        # Apply overrides if any, clamped to hard caps
        self.soft_caps = ShapeBudget(
            max_iterations=min(
                self.override_max_iterations or base.max_iterations,
                HARD_CAP_ITER,
            ),
            max_tool_calls=min(
                self.override_max_tool_calls or base.max_tool_calls,
                HARD_CAP_TOOL_CALLS,
            ),
            max_retrieved_chars=min(
                self.override_max_retrieved_chars or base.max_retrieved_chars,
                HARD_CAP_RETRIEVED_CHARS,
            ),
            max_output_tokens=min(
                self.override_max_output_tokens or base.max_output_tokens,
                HARD_CAP_OUTPUT_TOKENS,
            ),
        )

    # ─── Increment counters ──────────────────────────────────────────────────

    def increment_iteration(self) -> None:
        self.iterations += 1

    def increment_tool_call(self) -> None:
        self.tool_calls += 1

    def add_retrieved_chars(self, n: int) -> None:
        if n > 0:
            self.retrieved_chars += n

    def add_output_tokens(self, n: int) -> None:
        if n > 0:
            self.output_tokens += n

    # ─── Check budgets ───────────────────────────────────────────────────────

    def check_soft_caps(self) -> tuple[bool, Optional[str]]:
        """Returns (any_exceeded, name_of_first_exceeded).

        Soft cap = limite par shape adaptive. À utiliser pour décider de force
        conclude proprement.
        """
        if self.iterations >= self.soft_caps.max_iterations:
            return True, "max_iterations"
        if self.tool_calls >= self.soft_caps.max_tool_calls:
            return True, "max_tool_calls"
        if self.retrieved_chars >= self.soft_caps.max_retrieved_chars:
            return True, "max_retrieved_chars"
        if self.output_tokens >= self.soft_caps.max_output_tokens:
            return True, "max_output_tokens"
        return False, None

    def check_hard_caps(self) -> tuple[bool, Optional[str]]:
        """Returns (any_exceeded, name_of_first_exceeded).

        Hard cap = absolu, jamais dépassable. Raise si dépassé.
        """
        if self.iterations > HARD_CAP_ITER:
            return True, "max_iterations"
        if self.tool_calls > HARD_CAP_TOOL_CALLS:
            return True, "max_tool_calls"
        if self.retrieved_chars > HARD_CAP_RETRIEVED_CHARS:
            return True, "max_retrieved_chars"
        if self.output_tokens > HARD_CAP_OUTPUT_TOKENS:
            return True, "max_output_tokens"
        return False, None

    def enforce_hard_caps(self) -> None:
        """Raise BudgetExceeded si un hard cap est franchi."""
        if self.iterations > HARD_CAP_ITER:
            raise BudgetExceeded("max_iterations", self.iterations, HARD_CAP_ITER)
        if self.tool_calls > HARD_CAP_TOOL_CALLS:
            raise BudgetExceeded("max_tool_calls", self.tool_calls, HARD_CAP_TOOL_CALLS)
        if self.retrieved_chars > HARD_CAP_RETRIEVED_CHARS:
            raise BudgetExceeded("max_retrieved_chars", self.retrieved_chars, HARD_CAP_RETRIEVED_CHARS)
        if self.output_tokens > HARD_CAP_OUTPUT_TOKENS:
            raise BudgetExceeded("max_output_tokens", self.output_tokens, HARD_CAP_OUTPUT_TOKENS)

    # ─── Status ──────────────────────────────────────────────────────────────

    def snapshot(self) -> dict:
        """État courant lisible (pour observability / debug)."""
        return {
            "shape": self.shape,
            "counters": {
                "iterations": self.iterations,
                "tool_calls": self.tool_calls,
                "retrieved_chars": self.retrieved_chars,
                "output_tokens": self.output_tokens,
            },
            "soft_caps": {
                "max_iterations": self.soft_caps.max_iterations,
                "max_tool_calls": self.soft_caps.max_tool_calls,
                "max_retrieved_chars": self.soft_caps.max_retrieved_chars,
                "max_output_tokens": self.soft_caps.max_output_tokens,
            },
            "hard_caps": {
                "max_iterations": HARD_CAP_ITER,
                "max_tool_calls": HARD_CAP_TOOL_CALLS,
                "max_retrieved_chars": HARD_CAP_RETRIEVED_CHARS,
                "max_output_tokens": HARD_CAP_OUTPUT_TOKENS,
            },
            "utilization_soft": {
                "iterations": (self.iterations / self.soft_caps.max_iterations
                              if self.soft_caps.max_iterations else 0),
                "tool_calls": (self.tool_calls / self.soft_caps.max_tool_calls
                              if self.soft_caps.max_tool_calls else 0),
                "retrieved_chars": (self.retrieved_chars / self.soft_caps.max_retrieved_chars
                                   if self.soft_caps.max_retrieved_chars else 0),
                "output_tokens": (self.output_tokens / self.soft_caps.max_output_tokens
                                 if self.soft_caps.max_output_tokens else 0),
            },
        }

    def extend_for_degraded_structure(self, extra_iter: int = 2) -> None:
        """ADR §3e : `degraded_structure_flag` détecté → max_iter += 2 (compense).

        Clamp à HARD_CAP_ITER absolu.
        """
        new_max = min(self.soft_caps.max_iterations + extra_iter, HARD_CAP_ITER)
        # ShapeBudget est frozen → on recrée
        self.soft_caps = ShapeBudget(
            max_iterations=new_max,
            max_tool_calls=self.soft_caps.max_tool_calls,
            max_retrieved_chars=self.soft_caps.max_retrieved_chars,
            max_output_tokens=self.soft_caps.max_output_tokens,
        )
