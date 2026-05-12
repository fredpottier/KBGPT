"""Runtime V4.2 — Tiered Pipeline production (CH-49 Phase 1+).

Architecture cible OSMOSIS V4.2 (cf ADR `2026-05-10_CH-49_ADR_PIPELINE_V4_2_ARCHITECTURE_CIBLE_v1.md`).

Capabilities runtime :
    Cap1 — Cheap Certainty Layer (Layer 0)
    Cap2 — Structured Reasoning Operators (Layer 1)
    Cap3 — Adaptive Orchestrator (Layer 2)
    Cap4 — Evidence Routing & Structuring (transverse)
    Cap5 — Evaluation & Observability (transverse)

Phase 1 (current) : Layer 0 production-grade + Q↔A Verifier + multi-view scorer
                    + abstain reward + 3 catégories logging + QuestionTrace telemetry.

Modules :
    - models : Layer0Response, QuestionTrace, AbstainCategory, EscalationReason
    - telemetry : trace logger (file-based, JSONL append-only)
    - qa_alignment_verifier : DeepSeek-V3.1 verifier + retry/fallback
    - pipeline : Layer0Pipeline production (extend POC)
    - operators : Cap2 operators (Cap2.A live, Cap2.B/C/D/E à venir Phase 2)
"""

from knowbase.runtime_v4_2.models import (
    AbstainCategory,
    EscalationReason,
    Layer0Response,
    QuestionTrace,
)

__all__ = [
    "AbstainCategory",
    "EscalationReason",
    "Layer0Response",
    "QuestionTrace",
]
