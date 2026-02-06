"""
Tests for AggregatorPolicy - Multi-claim aggregation.

Tests the aggregation of multiple claim comparisons into a final verdict.

Author: Claude Code
Date: 2026-02-03
"""

import pytest

from knowbase.verification.comparison import (
    AggregatorPolicy,
    ClaimComparison,
    ComparisonResult,
    ComparisonExplanation,
    ReasonCode,
    AuthorityLevel,
    ClaimForm,
    ClaimFormType,
    ScalarValue,
    TruthRegime,
)


@pytest.fixture
def aggregator():
    return AggregatorPolicy()


def make_claim_form(value_num: float = 99.5) -> ClaimForm:
    """Helper to create ClaimForm for tests."""
    return ClaimForm(
        form_type=ClaimFormType.EXACT_VALUE,
        property_surface="SLA",
        value=ScalarValue(value_num, "%"),
        truth_regime=TruthRegime.NORMATIVE_STRICT,
        authority=AuthorityLevel.MEDIUM,
        original_text="test",
        verbatim_quote="test",
    )


def make_comparison(
    result: ComparisonResult,
    reason_code: ReasonCode,
    authority: AuthorityLevel = AuthorityLevel.MEDIUM,
    confidence: float = 0.9,
) -> ClaimComparison:
    """Helper to create ClaimComparison for tests."""
    return ClaimComparison(
        claim={"claim_id": "test", "value": "test"},
        claim_form=make_claim_form(),
        explanation=ComparisonExplanation(
            result=result,
            reason_code=reason_code,
            confidence=confidence,
        ),
        authority=authority,
        scope_match_score=1.0,
    )


class TestSingleClaimAggregation:
    """Tests with a single claim."""

    def test_single_supports(self, aggregator):
        """Single SUPPORTS claim = SUPPORTS verdict"""
        assertion_form = make_claim_form()
        comparisons = [
            make_comparison(ComparisonResult.SUPPORTS, ReasonCode.EXACT_MATCH)
        ]

        result = aggregator.aggregate(assertion_form, comparisons)

        assert result.result == ComparisonResult.SUPPORTS
        assert result.primary_claim is not None

    def test_single_contradicts(self, aggregator):
        """Single CONTRADICTS claim = CONTRADICTS verdict"""
        assertion_form = make_claim_form()
        comparisons = [
            make_comparison(ComparisonResult.CONTRADICTS, ReasonCode.VALUE_OUTSIDE_INTERVAL)
        ]

        result = aggregator.aggregate(assertion_form, comparisons)

        assert result.result == ComparisonResult.CONTRADICTS


class TestConflictingClaims:
    """Tests for conflicting claims detection."""

    def test_high_authority_conflict(self, aggregator):
        """Two HIGH authority claims with opposite results = UNKNOWN + CONFLICTING_EVIDENCE"""
        assertion_form = make_claim_form()
        comparisons = [
            make_comparison(
                ComparisonResult.SUPPORTS,
                ReasonCode.EXACT_MATCH,
                authority=AuthorityLevel.HIGH
            ),
            make_comparison(
                ComparisonResult.CONTRADICTS,
                ReasonCode.VALUE_OUTSIDE_INTERVAL,
                authority=AuthorityLevel.HIGH
            ),
        ]

        result = aggregator.aggregate(assertion_form, comparisons)

        assert result.result == ComparisonResult.UNKNOWN
        assert result.reason_code == ReasonCode.CONFLICTING_EVIDENCE

    def test_different_authority_no_conflict(self, aggregator):
        """HIGH vs LOW authority with opposite results = HIGH wins"""
        assertion_form = make_claim_form()
        comparisons = [
            make_comparison(
                ComparisonResult.CONTRADICTS,
                ReasonCode.VALUE_OUTSIDE_INTERVAL,
                authority=AuthorityLevel.HIGH
            ),
            make_comparison(
                ComparisonResult.SUPPORTS,
                ReasonCode.EXACT_MATCH,
                authority=AuthorityLevel.LOW
            ),
        ]

        result = aggregator.aggregate(assertion_form, comparisons)

        # HIGH authority CONTRADICTS wins
        assert result.result == ComparisonResult.CONTRADICTS
        assert len(result.conflicting_claims) > 0


class TestAuthorityPriority:
    """Tests for authority-based priority."""

    def test_high_authority_wins(self, aggregator):
        """HIGH authority claim takes precedence"""
        assertion_form = make_claim_form()
        comparisons = [
            make_comparison(
                ComparisonResult.SUPPORTS,
                ReasonCode.EXACT_MATCH,
                authority=AuthorityLevel.MEDIUM
            ),
            make_comparison(
                ComparisonResult.CONTRADICTS,
                ReasonCode.VALUE_OUTSIDE_INTERVAL,
                authority=AuthorityLevel.HIGH
            ),
        ]

        result = aggregator.aggregate(assertion_form, comparisons)

        # HIGH authority claim should be primary
        assert result.result == ComparisonResult.CONTRADICTS


class TestLowAuthorityOnly:
    """Tests for LOW authority only scenario."""

    def test_only_low_authority_penalty(self, aggregator):
        """Only LOW authority claims = LOW_AUTHORITY_ONLY warning"""
        assertion_form = make_claim_form()
        comparisons = [
            make_comparison(
                ComparisonResult.SUPPORTS,
                ReasonCode.EXACT_MATCH,
                authority=AuthorityLevel.LOW,
                confidence=0.9
            ),
        ]

        result = aggregator.aggregate(assertion_form, comparisons)

        assert result.result == ComparisonResult.SUPPORTS
        assert result.reason_code == ReasonCode.LOW_AUTHORITY_ONLY
        # Confidence should be penalized
        assert result.confidence < 0.9


class TestSupportingClaimsBoost:
    """Tests for supporting claims confidence boost."""

    def test_multiple_supporting_claims_boost(self, aggregator):
        """Multiple supporting claims increase confidence"""
        assertion_form = make_claim_form()
        comparisons = [
            make_comparison(
                ComparisonResult.SUPPORTS,
                ReasonCode.EXACT_MATCH,
                authority=AuthorityLevel.MEDIUM,
                confidence=0.8
            ),
            make_comparison(
                ComparisonResult.SUPPORTS,
                ReasonCode.EXACT_MATCH,
                authority=AuthorityLevel.MEDIUM,
                confidence=0.85
            ),
            make_comparison(
                ComparisonResult.SUPPORTS,
                ReasonCode.EXACT_MATCH,
                authority=AuthorityLevel.MEDIUM,
                confidence=0.9
            ),
        ]

        result = aggregator.aggregate(assertion_form, comparisons)

        assert result.result == ComparisonResult.SUPPORTS
        # Should have supporting claims
        assert len(result.supporting_claims) == 2
        # Confidence should be boosted
        assert result.confidence > comparisons[0].explanation.confidence


class TestEmptyComparisons:
    """Tests for edge cases with no comparisons."""

    def test_no_comparisons(self, aggregator):
        """No comparisons = UNKNOWN + INSUFFICIENT_EVIDENCE"""
        assertion_form = make_claim_form()
        comparisons = []

        result = aggregator.aggregate(assertion_form, comparisons)

        assert result.result == ComparisonResult.UNKNOWN
        assert result.reason_code == ReasonCode.INSUFFICIENT_EVIDENCE

    def test_all_unknown_comparisons(self, aggregator):
        """All UNKNOWN comparisons = UNKNOWN"""
        assertion_form = make_claim_form()
        comparisons = [
            make_comparison(
                ComparisonResult.UNKNOWN,
                ReasonCode.PROPERTY_MISMATCH,
                confidence=0.3
            ),
            make_comparison(
                ComparisonResult.UNKNOWN,
                ReasonCode.INCOMPATIBLE_TYPES,
                confidence=0.4
            ),
        ]

        result = aggregator.aggregate(assertion_form, comparisons)

        assert result.result == ComparisonResult.UNKNOWN
