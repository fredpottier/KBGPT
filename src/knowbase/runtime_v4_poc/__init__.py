"""Runtime V4 POC — Tiered Architecture validation (CH-49.POC).

Goal : valider en 2-3 jours que l'architecture "Cheap Certainty Layer + Operators"
apporte des gains mesurables vs pipeline V4.1 monolithique, avant refonte ADR complète.

Modules :
- qa_alignment_verifier : DeepSeek-V3.1 verifier post-Composer (anti-biais auto-juge)
- layer0_pipeline : retrieval V4.1 reuse + extraction directe Llama-Turbo + Q↔A check
- operators/temporal_active_version : operator déterministe Cypher (pas de LLM raisonnement)

Architecture cible (post-validation POC) : 5 capabilities runtime, voir ADR CH-49 v1.0 (à venir).
"""

from knowbase.runtime_v4_poc.qa_alignment_verifier import (
    QAAlignmentVerifier,
    QAAlignmentResult,
)
from knowbase.runtime_v4_poc.operators import (
    TemporalActiveVersionOperator,
    TemporalActiveResult,
)

__all__ = [
    "QAAlignmentVerifier",
    "QAAlignmentResult",
    "TemporalActiveVersionOperator",
    "TemporalActiveResult",
]
