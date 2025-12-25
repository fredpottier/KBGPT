"""
Phase 2.11 - Claims API Schemas

Pydantic schemas for Claims API endpoints.
Implements KG/RAG Contract separation for intelligent response handling.

Author: Claude Code
Date: 2025-12-24
"""

from datetime import datetime
from typing import List, Optional
from pydantic import BaseModel, Field


class ClaimSourceResponse(BaseModel):
    """Source of a claim for API response."""
    document_id: str
    excerpt: str
    page_number: Optional[int] = None
    date: Optional[str] = None


class CanonicalClaimResponse(BaseModel):
    """CanonicalClaim for API response."""
    canonical_claim_id: str
    subject_concept_id: str
    subject_name: Optional[str] = Field(default=None, description="Denormalized concept name")
    claim_type: str
    value: str
    value_numeric: Optional[float] = None
    unit: Optional[str] = None
    value_type: str
    scope_key: str
    scope_struct: dict = Field(default_factory=dict)
    distinct_documents: int
    total_assertions: int
    confidence_p50: float
    maturity: str
    status: str
    conflicts_with: List[str] = Field(default_factory=list)
    supersedes: Optional[str] = None
    sources: List[ClaimSourceResponse] = Field(default_factory=list)
    created_at: Optional[datetime] = None
    last_seen_utc: Optional[datetime] = None


class ClaimSearchRequest(BaseModel):
    """Request for claim search."""
    query: Optional[str] = Field(default=None, description="Free text search query")
    subject_concept_id: Optional[str] = Field(default=None, description="Filter by subject concept")
    claim_type: Optional[str] = Field(default=None, description="Filter by claim type")
    maturity: Optional[str] = Field(
        default=None,
        description="Filter by maturity (VALIDATED, CANDIDATE, CONFLICTING, etc.)"
    )
    min_confidence: float = Field(
        default=0.0,
        ge=0.0,
        le=1.0,
        description="Minimum confidence threshold"
    )
    limit: int = Field(default=20, ge=1, le=100, description="Max results")
    offset: int = Field(default=0, ge=0, description="Pagination offset")


class ClaimSearchResponse(BaseModel):
    """Response for claim search."""
    claims: List[CanonicalClaimResponse]
    total: int
    limit: int
    offset: int


class ConceptClaimsRequest(BaseModel):
    """Request for claims by concept."""
    concept_id: str
    claim_types: Optional[List[str]] = Field(
        default=None,
        description="Filter by claim types"
    )
    include_conflicting: bool = Field(
        default=True,
        description="Include conflicting claims"
    )


class ConflictingClaimsResponse(BaseModel):
    """Response showing conflicting claims."""
    claim_type: str
    subject_concept_id: str
    subject_name: Optional[str] = None
    conflicting_values: List[str]
    claims: List[CanonicalClaimResponse]
    resolution_suggestion: Optional[str] = None


class ConflictsListResponse(BaseModel):
    """List of all conflicts."""
    conflicts: List[ConflictingClaimsResponse]
    total_conflicts: int


# =============================================================================
# KG/RAG Contract Response (Phase 2.11 - Key Feature)
# =============================================================================

class KGFactResponse(BaseModel):
    """
    A fact from the Knowledge Graph (VALIDATED claims).

    These are high-confidence facts that should be stated directly.
    The LLM should NOT contradict these facts.
    """
    claim_type: str
    value: str
    value_numeric: Optional[float] = None
    unit: Optional[str] = None
    confidence: float
    source_count: int = Field(description="Number of distinct documents")
    evidence: Optional[str] = Field(
        default=None,
        description="Representative evidence excerpt"
    )


class RAGSuggestionResponse(BaseModel):
    """
    A suggestion from RAG (CANDIDATE or CONTEXT_DEPENDENT claims).

    These should be presented with appropriate hedging:
    - "According to available information..."
    - "Some sources suggest..."
    - "In certain contexts..."
    """
    claim_type: str
    value: str
    maturity: str = Field(description="CANDIDATE, CONTEXT_DEPENDENT, or CONFLICTING")
    confidence: float
    condition: Optional[str] = Field(
        default=None,
        description="Condition or context for applicability"
    )
    sources: List[ClaimSourceResponse] = Field(default_factory=list)


class ConflictInfo(BaseModel):
    """Information about a conflict for LLM handling."""
    claim_type: str
    values: List[str]
    recommendation: str = Field(
        description="How the LLM should handle this conflict"
    )


class KGRAGContractResponse(BaseModel):
    """
    KG/RAG Contract response for a concept.

    Separates knowledge into:
    - kg_facts: VALIDATED claims (high confidence, multi-source)
    - rag_suggestions: CANDIDATE/CONTEXT_DEPENDENT claims (need hedging)
    - conflicts: CONFLICTING claims (need explicit acknowledgment)

    This allows the LLM to:
    1. State kg_facts directly without hedging
    2. Present rag_suggestions with appropriate uncertainty language
    3. Acknowledge conflicts explicitly when relevant

    Example prompt injection:
    "For concept X, you MAY state: [kg_facts].
     You SHOULD hedge: [rag_suggestions].
     Known conflicts to acknowledge: [conflicts]."
    """
    concept_id: str
    concept_name: Optional[str] = None

    kg_facts: List[KGFactResponse] = Field(
        default_factory=list,
        description="VALIDATED claims - state directly without hedging"
    )

    rag_suggestions: List[RAGSuggestionResponse] = Field(
        default_factory=list,
        description="CANDIDATE/CONTEXT_DEPENDENT claims - use hedging language"
    )

    conflicts: List[ConflictInfo] = Field(
        default_factory=list,
        description="CONFLICTING claims - acknowledge explicitly"
    )

    total_claims: int = Field(
        default=0,
        description="Total claims for this concept"
    )

    llm_prompt_hint: str = Field(
        default="",
        description="Suggested prompt text for LLM injection"
    )


class ConsolidationRequest(BaseModel):
    """Request to trigger consolidation."""
    subject_concept_id: Optional[str] = None
    claim_type: Optional[str] = None
    doc_id: Optional[str] = None
    force: bool = Field(default=False, description="Force reconsolidation")


class ConsolidationResponse(BaseModel):
    """Response from consolidation."""
    claims_consolidated: int
    relations_consolidated: int
    conflicts_detected: int
    execution_time_ms: float
