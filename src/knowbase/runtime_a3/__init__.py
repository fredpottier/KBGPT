"""runtime_a3 — Runtime Parse → Plan → Execute → Evaluate → Synthesize.

Implémentation de l'ADR `ADR_PARSE_EVALUATE_RUNTIME.md` v1.2 (Phase A3).

Modules :
    - schemas    : Pydantic schemas versionnés v"a3.0" (ParseOutput, PlanOutput, etc.)
    - parse      : Module Parse (LLM #1) — décomposition question → sub-goals
    - plan       : Module Plan (déterministe) — mapping sub_goal → tool [A3.2]
    - execute    : Module Execute (déterministe) — exécution Cypher + filtres bitemporels [A3.3]
    - evaluate   : Module Evaluate (LLM #2) — verdict 4-classes [A3.4]
    - synthesize : Module Synthesize (LLM #3) — rédaction réponse [A3.5]

Cohérent avec :
    - ADR_BITEMPOREL_CLAIMS §4.4 (filtre runtime obligatoire)
    - ADR_RELATIONS_CLAIM_CLAIM §2.6 (politique ConflictPending)
    - VISION.md §3.5 (Probability Isolation) + §4.4 (pipeline runtime 5 modules)
"""

from knowbase.runtime_a3.schemas import (
    ParseInput,
    ParseOutput,
    PlanOutput,
    SubGoal,
    ToolCall,
    ToolName,
)

__all__ = [
    "ParseInput",
    "ParseOutput",
    "PlanOutput",
    "SubGoal",
    "ToolCall",
    "ToolName",
]
