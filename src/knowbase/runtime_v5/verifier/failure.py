"""V5 VerifierFailure typed + retry policy (CH-52.8.5 / S7.5).

ADR V1.5 §3f §C3 : `VerifierFailure {reason, details, retryable}`.

Retry policy :
- Retry SEULEMENT si `reason ∈ {missing_evidence, citation_mismatch}`
- 1 retry max
- Pas de retry sur version_conflict, cross_tenant, tool_error, cost_cap_exceeded,
  contradictory_citations, unsupported_numeric_transform
- Budget tokens séparé pour retry (cap 30k)
- Métrique OTel `retry_rate_by_reason`, alert si > 5%
"""
from __future__ import annotations

from enum import Enum
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


class FailureReason(str, Enum):
    """Raisons typées (ADR §3f §C3)."""
    MISSING_EVIDENCE = "missing_evidence"  # claim non soutenu par evidence cited
    CITATION_MISMATCH = "citation_mismatch"  # claim cite X mais X ne match pas
    VERSION_CONFLICT = "version_conflict"  # claim mélange versions différentes
    CROSS_TENANT = "cross_tenant"  # cross-tenant leak détecté (rare)
    TOOL_ERROR = "tool_error"  # tool exec failed
    COST_CAP_EXCEEDED = "cost_cap_exceeded"  # budget tokens dépassé
    CONTRADICTORY_CITATIONS = "contradictory_citations"  # 2 claims se contredisent
    UNSUPPORTED_NUMERIC_TRANSFORM = "unsupported_numeric_transform"  # delta sans compute_derived_metric
    MISSING_QUALIFIER = "missing_qualifier"  # claim global sans qualification


# Reasons éligibles au retry (ADR §3f re-run policy)
RETRYABLE_REASONS = frozenset({
    FailureReason.MISSING_EVIDENCE,
    FailureReason.CITATION_MISMATCH,
})


class VerifierFailure(BaseModel):
    """Échec verifier typé."""
    model_config = ConfigDict(extra="forbid")

    reason: FailureReason
    details: str = Field(..., min_length=1, max_length=2000)
    retryable: bool = False
    affected_claim_text: Optional[str] = Field(default=None, max_length=2000)
    affected_claim_index: Optional[int] = Field(default=None, ge=0)


def is_retryable(reason: FailureReason) -> bool:
    """Helper : retourne si reason est dans RETRYABLE_REASONS."""
    return reason in RETRYABLE_REASONS


def make_failure(
    reason: FailureReason,
    details: str,
    affected_claim_text: Optional[str] = None,
    affected_claim_index: Optional[int] = None,
) -> VerifierFailure:
    """Factory : crée une VerifierFailure avec retryable auto-calculé."""
    return VerifierFailure(
        reason=reason,
        details=details[:2000],
        retryable=is_retryable(reason),
        affected_claim_text=affected_claim_text[:2000] if affected_claim_text else None,
        affected_claim_index=affected_claim_index,
    )
