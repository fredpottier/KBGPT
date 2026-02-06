"""
Phase 2 - Verification API Schemas V1.1

Pydantic schemas for text verification against Knowledge Graph.
Implements assertion-level fact-checking with evidence tracking.

V1.1: Added comparison_details for deterministic comparison transparency.

Author: Claude Code
Date: 2026-02-03
Version: 1.1
"""

from enum import Enum
from typing import List, Dict, Optional, Literal, Any
from pydantic import BaseModel, Field


class VerificationStatus(str, Enum):
    """Status of a verified assertion."""
    CONFIRMED = "confirmed"       # Claim confirms the assertion
    CONTRADICTED = "contradicted" # Claim contradicts the assertion
    INCOMPLETE = "incomplete"     # Partial information found
    FALLBACK = "fallback"         # Found in Qdrant only (no claim)
    UNKNOWN = "unknown"           # Nothing found


class ComparisonDetails(BaseModel):
    """
    V1.1: Details of deterministic comparison.

    Provides transparency on how the verdict was determined.
    """
    reason_code: str = Field(
        description="Structured reason code (e.g., VALUE_OUTSIDE_INTERVAL, EXACT_MATCH)"
    )
    reason_message: str = Field(
        description="Human-readable explanation of the comparison"
    )
    deterministic: bool = Field(
        default=True,
        description="True if comparison was deterministic, False if LLM-based"
    )
    authority: Optional[str] = Field(
        default=None,
        description="Authority level of the source (HIGH, MEDIUM, LOW)"
    )
    tolerance_applied: Optional[float] = Field(
        default=None,
        description="Tolerance applied during comparison (0.0 = strict)"
    )


class Evidence(BaseModel):
    """Evidence supporting or contradicting an assertion."""
    type: Literal["claim", "chunk"] = Field(
        description="Source type: claim from KG or chunk from RAG"
    )
    text: str = Field(description="Evidence text excerpt")
    source_doc: str = Field(description="Source document name/ID")
    source_page: Optional[int] = Field(default=None, description="Page number if available")
    source_section: Optional[str] = Field(default=None, description="Section name if available")
    confidence: float = Field(ge=0.0, le=1.0, description="Confidence score")
    relationship: Literal["supports", "contradicts", "partial"] = Field(
        description="How this evidence relates to the assertion"
    )
    # V1.1: Structured comparison details
    comparison_details: Optional[Dict[str, Any]] = Field(
        default=None,
        description="V1.1: Details of the comparison (reason_code, deterministic, etc.)"
    )


class Assertion(BaseModel):
    """A verified assertion from the input text."""
    id: str = Field(description="Unique assertion ID (A1, A2, ...)")
    text: str = Field(description="The assertion text")
    start_index: int = Field(ge=0, description="Start position in original text")
    end_index: int = Field(ge=0, description="End position in original text")
    status: VerificationStatus = Field(description="Verification status")
    confidence: float = Field(ge=0.0, le=1.0, description="Overall confidence")
    evidence: List[Evidence] = Field(default_factory=list, description="Supporting evidence")


class VerifyRequest(BaseModel):
    """Request to analyze and verify text."""
    text: str = Field(min_length=10, max_length=50000, description="Text to verify")
    tenant_id: str = Field(default="default", description="Tenant ID")


class VerifyResponse(BaseModel):
    """Response with verified assertions."""
    original_text: str = Field(description="Original input text")
    assertions: List[Assertion] = Field(description="List of verified assertions")
    summary: Dict[str, int] = Field(
        description="Summary counts by status",
        example={
            "total": 10,
            "confirmed": 5,
            "contradicted": 2,
            "incomplete": 1,
            "fallback": 1,
            "unknown": 1
        }
    )


class CorrectRequest(BaseModel):
    """Request to correct text based on verified assertions."""
    text: str = Field(min_length=10, max_length=50000, description="Original text")
    assertions: List[Assertion] = Field(description="Verified assertions with evidence")
    tenant_id: str = Field(default="default", description="Tenant ID")


class CorrectionChange(BaseModel):
    """A single correction made to the text."""
    original: str = Field(description="Original text segment")
    corrected: str = Field(description="Corrected text segment")
    reason: str = Field(description="Reason for the correction")


class CorrectResponse(BaseModel):
    """Response with corrected text."""
    corrected_text: str = Field(description="Text with corrections applied")
    changes: List[CorrectionChange] = Field(
        default_factory=list,
        description="List of changes made"
    )
