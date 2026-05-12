"""Modèles Runtime V4.2 (CH-49 Phase 1).

Schemas issus de l'ADR §1 (Cap5) Amendment 5 (Telemetry schema Claude Web)
et Amendment 1 (3 catégories abstain monitoring ChatGPT).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional


class AbstainCategory(str, Enum):
    """3 catégories d'abstain (Amendment 1, Cap5).

    - ALIGNED : Q↔A Verifier laisse passer (réponse alignée)
    - MISALIGNED_ABSTAIN_CORRECT : Verifier rejette ET la décision était bonne
      (gold answerability=unanswerable / no evidence retrievable)
    - MISALIGNED_BUT_ANSWERABLE : Verifier rejette MAIS la question était
      en fait answerable → alerte qualité (threshold 5%).
    """

    ALIGNED = "aligned"
    MISALIGNED_ABSTAIN_CORRECT = "misaligned_abstain_correct"
    MISALIGNED_BUT_ANSWERABLE = "misaligned_but_answerable"
    UNKNOWN = "unknown"


class EscalationReason(str, Enum):
    """Raison d'escalade vers Layer 1 ou Layer 2 (Cap3 §1)."""

    OPERATOR_TRIGGERED = "operator_triggered"
    LAYER0_ABSTAIN_NO_OP = "layer0_abstain_no_op"
    LAYER1_LOW_CONFIDENCE = "layer1_low_confidence"
    OPERATORS_CONFLICT = "operators_conflict"
    NO_OPERATOR_APPLICABLE = "no_operator_applicable"
    NONE = "none"


@dataclass
class Layer0Response:
    """Réponse Layer 0 production (étend POC avec champs telemetry)."""

    question: str
    decision: str  # ANSWER | ABSTAIN
    answer: str
    layer: str = "layer0"  # layer0 | layer1_<op> | layer2
    abstention_reason: Optional[str] = None
    abstain_category: Optional[AbstainCategory] = None
    qa_alignment: Optional[str] = None  # ALIGNED | MISALIGNED | ABSTAIN_OK
    qa_reason: Optional[str] = None
    qa_confidence: Optional[float] = None
    n_chunks_used: int = 0
    doc_ids_cited: list[str] = field(default_factory=list)
    latency_breakdown_ms: dict[str, int] = field(default_factory=dict)
    escalation_reason: EscalationReason = EscalationReason.NONE
    used_unified_prompt: bool = False
    # Provenance pour fallback Layer 2 (ne pas leak vers le client)
    raw_evidence_n_claims: int = 0


@dataclass
class QAVerifierTrace:
    decision: str
    reason: str
    confidence: float
    latency_ms: int
    provider: str  # together | deepinfra | error
    fallback_used: bool = False


@dataclass
class QuestionTrace:
    """Schema telemetry complet (Amendment 5, Cap5).

    Persisté en JSONL append-only sous data/runtime_v4_2/traces/<YYYY-MM-DD>.jsonl
    pour analyse offline (distribution layer, false_abstain, latence, coût).
    """

    question_id: str  # Hash question + timestamp
    question: str
    timestamp: str  # ISO-8601 UTC
    layer_used: str  # layer0 | layer1_<op_name> | layer2
    layer0_output: dict[str, Any] = field(default_factory=dict)
    verifier_result: Optional[dict[str, Any]] = None
    intent_scores: dict[str, float] = field(default_factory=dict)
    layer1_operator: Optional[str] = None
    layer1_output: Optional[dict[str, Any]] = None
    layer1_fallback_path: Optional[str] = None  # primary | fallback_1 | fallback_2 | escalate
    layer2_plan: Optional[list[Any]] = None
    layer2_tool_calls: Optional[list[Any]] = None
    layer2_iterations: Optional[int] = None
    final_answer: dict[str, Any] = field(default_factory=dict)
    escalation_path: str = "layer0"  # layer0 | layer0->layer1_<op> | layer0->layer2 | ...
    latency_breakdown_ms: dict[str, int] = field(default_factory=dict)
    cost_usd: float = 0.0
    abstain_category: Optional[str] = None  # AbstainCategory.value
    used_unified_prompt: bool = False
    error: Optional[str] = None


@dataclass
class UnifiedExtractionResult:
    """Output du prompt unifié (Amendment 7).

    1 seul appel LLM produit : extraction + intent scores + Q↔A self-check.
    Permet d'économiser 1 round-trip Q↔A Verifier quand confidence haute.
    """

    extracted_answer: str
    qa_alignment: str  # ALIGNED | MISALIGNED | ABSTAIN_OK
    qa_reason: str
    qa_confidence: float
    intent_scores: dict[str, float]  # par operator candidate
    needs_external_verifier: bool  # True si confidence < threshold → fallback DeepSeek
    raw_response: dict[str, Any] = field(default_factory=dict)
