"""Operators Layer 1 (Cap2) — production-grade.

Cap2.A `temporal_active_version` : reuse from runtime_v4_poc (already validated).
Cap2.B `lifecycle_resolution` : new in Phase 2.
Cap2.C `kg_query` : Phase 2 (à venir).
Cap2.D `set_reasoning` : Phase 2 (à venir).
Cap2.E `comparison_contradiction` : Phase 4 (à venir).

Charte commune (ADR §1) :
  - LLM = aiguilleur (intent detection léger DeepSeek) ou rédacteur (formatage final)
  - JAMAIS LLM dans la chaîne de raisonnement structurel
  - Code Python déterministe + Cypher pour la logique
  - Pattern fallback : primary → fallback_1 → fallback_2 → escalate Layer 2
"""
from knowbase.runtime_v4_poc.operators.temporal_active_version import (
    TemporalActiveVersionOperator,
    TemporalActiveResult,
)
from knowbase.runtime_v4_2.operators.lifecycle_resolution import (
    LifecycleResolutionOperator,
    LifecycleResolutionResult,
)
from knowbase.runtime_v4_2.operators.kg_query import (
    KGQueryOperator,
    KGQueryResult,
)
from knowbase.runtime_v4_2.operators.set_reasoning import (
    SetReasoningOperator,
    SetReasoningResult,
)

__all__ = [
    "TemporalActiveVersionOperator",
    "TemporalActiveResult",
    "LifecycleResolutionOperator",
    "LifecycleResolutionResult",
    "KGQueryOperator",
    "KGQueryResult",
    "SetReasoningOperator",
    "SetReasoningResult",
]
