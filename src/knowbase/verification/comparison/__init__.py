"""
OSMOSE Verification - Deterministic Comparison Engine V1.1

Moteur de comparaison déterministe pour remplacer la classification LLM
par des règles structurées basées sur:
- Truth Regimes: Strictness déduite du langage
- Value Algebra: Types de valeurs unifiés
- Claim Forms: Formes logiques structurées
- Comparison Matrix: Règles déterministes

Author: Claude Code
Date: 2026-02-03
Version: 1.1 (Hardened)
"""

from knowbase.verification.comparison.reason_codes import ReasonCode
from knowbase.verification.comparison.truth_regimes import TruthRegime, TruthRegimeDetector
from knowbase.verification.comparison.value_algebra import (
    Value,
    ScalarValue,
    IntervalValue,
    InequalityValue,
    SetValue,
    BooleanValue,
    VersionValue,
    TextValue,
    AuthorityLevel,
)
from knowbase.verification.comparison.claim_forms import (
    ClaimForm,
    ClaimFormType,
    StructuredClaimForm,
)
from knowbase.verification.comparison.tolerance_policy import TolerancePolicy
from knowbase.verification.comparison.aggregator import AggregatorPolicy, ClaimComparison, AggregatedResult
from knowbase.verification.comparison.comparison_engine import (
    ComparisonEngine,
    ComparisonResult,
    ComparisonExplanation,
)
from knowbase.verification.comparison.structured_extractor import StructuredExtractor

__all__ = [
    # Reason codes
    "ReasonCode",
    # Truth regimes
    "TruthRegime",
    "TruthRegimeDetector",
    # Value algebra
    "Value",
    "ScalarValue",
    "IntervalValue",
    "InequalityValue",
    "SetValue",
    "BooleanValue",
    "VersionValue",
    "TextValue",
    "AuthorityLevel",
    # Claim forms
    "ClaimForm",
    "ClaimFormType",
    "StructuredClaimForm",
    # Policies
    "TolerancePolicy",
    "AggregatorPolicy",
    "ClaimComparison",
    "AggregatedResult",
    # Engine
    "ComparisonEngine",
    "ComparisonResult",
    "ComparisonExplanation",
    # Extractor
    "StructuredExtractor",
]
