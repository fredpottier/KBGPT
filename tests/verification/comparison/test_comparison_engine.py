"""
Tests for Comparison Engine - Deterministic comparison matrix.

Tests the core comparison logic between different value types.

Author: Claude Code
Date: 2026-02-03
"""

import pytest

from knowbase.verification.comparison import (
    ComparisonEngine,
    ComparisonResult,
    ReasonCode,
    TruthRegime,
    AuthorityLevel,
    ScalarValue,
    IntervalValue,
    SetValue,
    InequalityValue,
    BooleanValue,
    VersionValue,
    TextValue,
    ClaimForm,
    ClaimFormType,
)


@pytest.fixture
def engine():
    return ComparisonEngine()


def make_claim_form(
    value,
    property_surface: str = "test_property",
    claim_key: str = None,
    regime: TruthRegime = TruthRegime.NORMATIVE_STRICT,
    authority: AuthorityLevel = AuthorityLevel.MEDIUM,
) -> ClaimForm:
    """Helper to create ClaimForm for tests."""
    form_type_map = {
        ScalarValue: ClaimFormType.EXACT_VALUE,
        IntervalValue: ClaimFormType.INTERVAL_VALUE,
        SetValue: ClaimFormType.SET_VALUE,
        InequalityValue: ClaimFormType.BOUNDED_VALUE,
        BooleanValue: ClaimFormType.BOOLEAN_VALUE,
        VersionValue: ClaimFormType.VERSION_VALUE,
        TextValue: ClaimFormType.TEXT_VALUE,
    }
    return ClaimForm(
        form_type=form_type_map.get(type(value), ClaimFormType.TEXT_VALUE),
        property_surface=property_surface,
        claim_key=claim_key,
        value=value,
        truth_regime=regime,
        authority=authority,
        original_text="test",
        verbatim_quote="test",
    )


class TestScalarVsScalar:
    """Tests for Scalar vs Scalar comparisons."""

    def test_exact_match(self, engine):
        """Scalar 99.5% vs Scalar 99.5% = SUPPORTS"""
        a = make_claim_form(ScalarValue(value=99.5, unit="%"), property_surface="SLA")
        c = make_claim_form(ScalarValue(value=99.5, unit="%"), property_surface="SLA")

        result = engine.compare(a, c, tolerance=0.0)

        assert result.result == ComparisonResult.SUPPORTS
        assert result.reason_code == ReasonCode.EXACT_MATCH
        assert result.confidence == 1.0

    def test_different_values_contradicts(self, engine):
        """Scalar 99.5% vs Scalar 99.7% = CONTRADICTS"""
        a = make_claim_form(ScalarValue(value=99.5, unit="%"), property_surface="SLA")
        c = make_claim_form(ScalarValue(value=99.7, unit="%"), property_surface="SLA")

        result = engine.compare(a, c, tolerance=0.0)

        assert result.result == ComparisonResult.CONTRADICTS
        assert result.confidence == 1.0

    def test_with_tolerance_supports(self, engine):
        """Scalar 99.5% vs Scalar 99.6% with 2% tolerance = SUPPORTS"""
        a = make_claim_form(ScalarValue(value=99.5, unit="%"), property_surface="SLA")
        c = make_claim_form(ScalarValue(value=99.6, unit="%"), property_surface="SLA")

        result = engine.compare(a, c, tolerance=0.02)

        assert result.result == ComparisonResult.SUPPORTS
        assert result.reason_code == ReasonCode.EQUIVALENT_MATCH


class TestScalarVsInterval:
    """Tests for Scalar vs Interval comparisons."""

    def test_scalar_outside_interval_contradicts(self, engine):
        """Scalar 99.5% vs Interval [99.7, 99.9]% = CONTRADICTS (key test case!)"""
        a = make_claim_form(ScalarValue(value=99.5, unit="%"), property_surface="SLA")
        c = make_claim_form(IntervalValue(low=99.7, high=99.9, unit="%"), property_surface="SLA")

        result = engine.compare(a, c, tolerance=0.0)

        assert result.result == ComparisonResult.CONTRADICTS
        assert result.reason_code == ReasonCode.VALUE_OUTSIDE_INTERVAL
        assert result.confidence == 1.0
        assert result.details["value"] == 99.5
        assert result.details["low"] == 99.7
        assert result.details["high"] == 99.9

    def test_scalar_inside_interval_supports(self, engine):
        """Scalar 99.8% vs Interval [99.7, 99.9]% = SUPPORTS"""
        a = make_claim_form(ScalarValue(value=99.8, unit="%"), property_surface="SLA")
        c = make_claim_form(IntervalValue(low=99.7, high=99.9, unit="%"), property_surface="SLA")

        result = engine.compare(a, c, tolerance=0.0)

        assert result.result == ComparisonResult.SUPPORTS
        assert result.reason_code == ReasonCode.VALUE_IN_INTERVAL

    def test_scalar_at_boundary_supports(self, engine):
        """Scalar 99.7% (lower bound) vs Interval [99.7, 99.9]% = SUPPORTS"""
        a = make_claim_form(ScalarValue(value=99.7, unit="%"), property_surface="SLA")
        c = make_claim_form(IntervalValue(low=99.7, high=99.9, unit="%"), property_surface="SLA")

        result = engine.compare(a, c, tolerance=0.0)

        assert result.result == ComparisonResult.SUPPORTS


class TestScalarVsSet:
    """Tests for Scalar vs Set comparisons."""

    def test_scalar_in_set_incomplete(self, engine):
        """Scalar 30 vs Set {0, 30} = PARTIAL (key test case!)"""
        a = make_claim_form(ScalarValue(value=30, unit="min"), property_surface="RPO")
        c = make_claim_form(SetValue(values={0, 30}, unit="min"), property_surface="RPO")

        result = engine.compare(a, c, tolerance=0.0)

        assert result.result == ComparisonResult.PARTIAL
        assert result.reason_code == ReasonCode.VALUE_IN_SET_INCOMPLETE
        assert result.details["value"] == 30
        assert 0 in result.details["missing"]

    def test_scalar_not_in_set_contradicts(self, engine):
        """Scalar 60 vs Set {0, 30} = CONTRADICTS"""
        a = make_claim_form(ScalarValue(value=60, unit="min"), property_surface="RPO")
        c = make_claim_form(SetValue(values={0, 30}, unit="min"), property_surface="RPO")

        result = engine.compare(a, c, tolerance=0.0)

        assert result.result == ComparisonResult.CONTRADICTS
        assert result.reason_code == ReasonCode.VALUE_NOT_IN_SET

    def test_scalar_in_singleton_set_supports(self, engine):
        """Scalar 30 vs Set {30} = SUPPORTS"""
        a = make_claim_form(ScalarValue(value=30, unit="min"), property_surface="RPO")
        c = make_claim_form(SetValue(values={30}, unit="min"), property_surface="RPO")

        result = engine.compare(a, c, tolerance=0.0)

        assert result.result == ComparisonResult.SUPPORTS
        assert result.reason_code == ReasonCode.VALUE_IN_SET


class TestIntervalVsInterval:
    """Tests for Interval vs Interval comparisons."""

    def test_exact_match(self, engine):
        """Interval [99.7, 99.9]% vs Interval [99.7, 99.9]% = SUPPORTS"""
        a = make_claim_form(IntervalValue(low=99.7, high=99.9, unit="%"), property_surface="SLA")
        c = make_claim_form(IntervalValue(low=99.7, high=99.9, unit="%"), property_surface="SLA")

        result = engine.compare(a, c, tolerance=0.0)

        assert result.result == ComparisonResult.SUPPORTS
        assert result.reason_code == ReasonCode.EXACT_MATCH

    def test_overlapping_intervals_partial(self, engine):
        """Interval [99.5, 99.8]% vs Interval [99.7, 99.9]% = PARTIAL (overlap)"""
        a = make_claim_form(IntervalValue(low=99.5, high=99.8, unit="%"), property_surface="SLA")
        c = make_claim_form(IntervalValue(low=99.7, high=99.9, unit="%"), property_surface="SLA")

        result = engine.compare(a, c, tolerance=0.0)

        assert result.result == ComparisonResult.PARTIAL
        assert result.reason_code == ReasonCode.INTERVALS_OVERLAP

    def test_disjoint_intervals_contradicts(self, engine):
        """Interval [99.0, 99.5]% vs Interval [99.7, 99.9]% = CONTRADICTS"""
        a = make_claim_form(IntervalValue(low=99.0, high=99.5, unit="%"), property_surface="SLA")
        c = make_claim_form(IntervalValue(low=99.7, high=99.9, unit="%"), property_surface="SLA")

        result = engine.compare(a, c, tolerance=0.0)

        assert result.result == ComparisonResult.CONTRADICTS
        assert result.reason_code == ReasonCode.INTERVALS_DISJOINT


class TestSetVsSet:
    """Tests for Set vs Set comparisons."""

    def test_equal_sets_supports(self, engine):
        """Set {0, 30} vs Set {0, 30} = SUPPORTS"""
        a = make_claim_form(SetValue(values={0, 30}, unit="min"), property_surface="RPO")
        c = make_claim_form(SetValue(values={0, 30}, unit="min"), property_surface="RPO")

        result = engine.compare(a, c, tolerance=0.0)

        assert result.result == ComparisonResult.SUPPORTS
        assert result.reason_code == ReasonCode.SETS_EQUAL

    def test_subset_partial(self, engine):
        """Set {30} vs Set {0, 30} = PARTIAL (subset)"""
        a = make_claim_form(SetValue(values={30}, unit="min"), property_surface="RPO")
        c = make_claim_form(SetValue(values={0, 30}, unit="min"), property_surface="RPO")

        result = engine.compare(a, c, tolerance=0.0)

        assert result.result == ComparisonResult.PARTIAL
        assert result.reason_code == ReasonCode.SET_SUBSET

    def test_disjoint_sets_contradicts(self, engine):
        """Set {60, 120} vs Set {0, 30} = CONTRADICTS"""
        a = make_claim_form(SetValue(values={60, 120}, unit="min"), property_surface="RPO")
        c = make_claim_form(SetValue(values={0, 30}, unit="min"), property_surface="RPO")

        result = engine.compare(a, c, tolerance=0.0)

        assert result.result == ComparisonResult.CONTRADICTS
        assert result.reason_code == ReasonCode.SETS_DISJOINT


class TestBooleanComparisons:
    """Tests for Boolean comparisons."""

    def test_true_true_supports(self, engine):
        """Boolean True vs Boolean True = SUPPORTS"""
        a = make_claim_form(BooleanValue(value=True), property_surface="encryption")
        c = make_claim_form(BooleanValue(value=True), property_surface="encryption")

        result = engine.compare(a, c, tolerance=0.0)

        assert result.result == ComparisonResult.SUPPORTS
        assert result.reason_code == ReasonCode.BOOLEAN_MATCH

    def test_true_false_contradicts(self, engine):
        """Boolean True vs Boolean False = CONTRADICTS"""
        a = make_claim_form(BooleanValue(value=True), property_surface="encryption")
        c = make_claim_form(BooleanValue(value=False), property_surface="encryption")

        result = engine.compare(a, c, tolerance=0.0)

        assert result.result == ComparisonResult.CONTRADICTS
        assert result.reason_code == ReasonCode.BOOLEAN_MISMATCH


class TestVersionComparisons:
    """Tests for Version comparisons."""

    def test_exact_version_match(self, engine):
        """Version TLS 1.2 vs Version TLS 1.2 = SUPPORTS"""
        a = make_claim_form(VersionValue.parse("TLS 1.2"), property_surface="protocol")
        c = make_claim_form(VersionValue.parse("TLS 1.2"), property_surface="protocol")

        result = engine.compare(a, c, tolerance=0.0)

        assert result.result == ComparisonResult.SUPPORTS
        assert result.reason_code == ReasonCode.VERSION_MATCH

    def test_different_version_mismatch(self, engine):
        """Version TLS 1.2 vs Version TLS 1.3 = varies based on compatibility"""
        a = make_claim_form(VersionValue.parse("TLS 1.3"), property_surface="protocol")
        c = make_claim_form(VersionValue.parse("TLS 1.2"), property_surface="protocol")

        result = engine.compare(a, c, tolerance=0.0)

        # 1.3 >= 1.2, so compatible
        assert result.result == ComparisonResult.SUPPORTS
        assert result.reason_code == ReasonCode.VERSION_COMPATIBLE


class TestPropertyMismatch:
    """Tests for property mismatch handling."""

    def test_different_claim_keys_unknown(self, engine):
        """Different claim_keys should return UNKNOWN"""
        a = make_claim_form(
            ScalarValue(99.5, "%"),
            property_surface="SLA",
            claim_key="service_level_agreement"
        )
        c = make_claim_form(
            ScalarValue(99.5, "%"),
            property_surface="uptime",
            claim_key="uptime_percentage"
        )

        result = engine.compare(a, c, tolerance=0.0)

        assert result.result == ComparisonResult.UNKNOWN
        assert result.reason_code == ReasonCode.PROPERTY_MISMATCH


class TestScopeMismatch:
    """Tests for scope handling."""

    def test_scope_missing_needs_scope(self, engine):
        """Assertion without scope vs Claim with scope = NEEDS_SCOPE"""
        a = make_claim_form(
            ScalarValue(value=30, unit="min"),
            property_surface="RPO"
        )
        c = make_claim_form(
            ScalarValue(value=30, unit="min"),
            property_surface="RPO"
        )
        # Add scope to claim
        c.scope_edition = "Enterprise"

        result = engine.compare(a, c, tolerance=0.0)

        assert result.result == ComparisonResult.NEEDS_SCOPE
        assert result.reason_code == ReasonCode.SCOPE_MISSING


class TestUnitMismatch:
    """Tests for unit mismatch handling."""

    def test_incompatible_units_unknown(self, engine):
        """Different incompatible units should return UNKNOWN"""
        a = make_claim_form(
            ScalarValue(value=30, unit="min"),
            property_surface="duration"
        )
        c = make_claim_form(
            ScalarValue(value=30, unit="%"),  # Different unit
            property_surface="duration"
        )

        result = engine.compare(a, c, tolerance=0.0)

        assert result.result == ComparisonResult.UNKNOWN
        assert result.reason_code == ReasonCode.UNIT_MISMATCH
