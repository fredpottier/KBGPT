"""
Tests for TolerancePolicy - Dynamic tolerance calculation.

Tests the tolerance calculation rules based on value type, unit, regime, and authority.

Author: Claude Code
Date: 2026-02-03
"""

import pytest

from knowbase.verification.comparison import (
    TolerancePolicy,
    TruthRegime,
    AuthorityLevel,
)


@pytest.fixture
def policy():
    return TolerancePolicy()


class TestHighAuthorityAlwaysStrict:
    """HIGH authority sources should always have 0 tolerance."""

    def test_high_authority_descriptive_approx(self, policy):
        """HIGH authority + DESCRIPTIVE_APPROX still = 0 tolerance"""
        tolerance = policy.get_tolerance(
            value_kind="ScalarValue",
            unit="%",
            regime=TruthRegime.DESCRIPTIVE_APPROX,
            authority=AuthorityLevel.HIGH,
        )
        assert tolerance == 0.0

    def test_high_authority_duration(self, policy):
        """HIGH authority duration = 0 tolerance"""
        tolerance = policy.get_tolerance(
            value_kind="ScalarValue",
            unit="min",
            regime=TruthRegime.DESCRIPTIVE_APPROX,
            authority=AuthorityLevel.HIGH,
        )
        assert tolerance == 0.0


class TestNormativeRegimesStrict:
    """Normative regimes should have 0 tolerance regardless of authority."""

    def test_normative_strict_medium_authority(self, policy):
        """NORMATIVE_STRICT + MEDIUM authority = 0 tolerance"""
        tolerance = policy.get_tolerance(
            value_kind="ScalarValue",
            unit="%",
            regime=TruthRegime.NORMATIVE_STRICT,
            authority=AuthorityLevel.MEDIUM,
        )
        assert tolerance == 0.0

    def test_normative_bounded_low_authority(self, policy):
        """NORMATIVE_BOUNDED + LOW authority = 0 tolerance"""
        tolerance = policy.get_tolerance(
            value_kind="ScalarValue",
            unit="%",
            regime=TruthRegime.NORMATIVE_BOUNDED,
            authority=AuthorityLevel.LOW,
        )
        assert tolerance == 0.0

    def test_empirical_statistical_strict(self, policy):
        """EMPIRICAL_STATISTICAL = 0 tolerance (p-values are strict)"""
        tolerance = policy.get_tolerance(
            value_kind="ScalarValue",
            unit=None,
            regime=TruthRegime.EMPIRICAL_STATISTICAL,
            authority=AuthorityLevel.MEDIUM,
        )
        assert tolerance == 0.0


class TestDescriptiveApproxWithTolerance:
    """DESCRIPTIVE_APPROX with MEDIUM/LOW authority allows tolerance."""

    def test_percent_tolerance(self, policy):
        """Percentage with DESCRIPTIVE_APPROX = 1% tolerance"""
        tolerance = policy.get_tolerance(
            value_kind="ScalarValue",
            unit="%",
            regime=TruthRegime.DESCRIPTIVE_APPROX,
            authority=AuthorityLevel.MEDIUM,
        )
        assert tolerance == 0.01

    def test_duration_tolerance(self, policy):
        """Duration with DESCRIPTIVE_APPROX = 5% tolerance"""
        tolerance = policy.get_tolerance(
            value_kind="ScalarValue",
            unit="min",
            regime=TruthRegime.DESCRIPTIVE_APPROX,
            authority=AuthorityLevel.MEDIUM,
        )
        assert tolerance == 0.05

    def test_default_tolerance(self, policy):
        """Unknown unit with DESCRIPTIVE_APPROX = 2% tolerance"""
        tolerance = policy.get_tolerance(
            value_kind="ScalarValue",
            unit="widgets",
            regime=TruthRegime.DESCRIPTIVE_APPROX,
            authority=AuthorityLevel.MEDIUM,
        )
        assert tolerance == 0.02


class TestAlwaysStrictValueTypes:
    """Some value types should never have tolerance."""

    def test_boolean_always_strict(self, policy):
        """BooleanValue = 0 tolerance always"""
        tolerance = policy.get_tolerance(
            value_kind="BooleanValue",
            unit=None,
            regime=TruthRegime.DESCRIPTIVE_APPROX,
            authority=AuthorityLevel.LOW,
        )
        assert tolerance == 0.0

    def test_version_always_strict(self, policy):
        """VersionValue = 0 tolerance always"""
        tolerance = policy.get_tolerance(
            value_kind="VersionValue",
            unit=None,
            regime=TruthRegime.DESCRIPTIVE_APPROX,
            authority=AuthorityLevel.LOW,
        )
        assert tolerance == 0.0


class TestHedgeStrengthAdjustment:
    """Hedge strength should increase tolerance."""

    def test_hedge_increases_tolerance(self, policy):
        """Strong hedge increases tolerance by up to 50%"""
        # Without hedge
        base = policy.get_tolerance(
            value_kind="ScalarValue",
            unit="min",
            regime=TruthRegime.DESCRIPTIVE_APPROX,
            authority=AuthorityLevel.MEDIUM,
            hedge_strength=0.0,
        )

        # With hedge
        with_hedge = policy.get_tolerance(
            value_kind="ScalarValue",
            unit="min",
            regime=TruthRegime.DESCRIPTIVE_APPROX,
            authority=AuthorityLevel.MEDIUM,
            hedge_strength=1.0,  # Maximum hedge
        )

        assert with_hedge > base
        assert with_hedge <= 0.10  # Capped at 10%

    def test_hedge_does_not_affect_strict(self, policy):
        """Hedge should not add tolerance to strict regimes"""
        tolerance = policy.get_tolerance(
            value_kind="ScalarValue",
            unit="%",
            regime=TruthRegime.NORMATIVE_STRICT,
            authority=AuthorityLevel.MEDIUM,
            hedge_strength=1.0,
        )
        assert tolerance == 0.0


class TestIsStrictComparison:
    """Tests for is_strict_comparison helper."""

    def test_high_authority_is_strict(self, policy):
        assert policy.is_strict_comparison(
            TruthRegime.DESCRIPTIVE_APPROX,
            AuthorityLevel.HIGH
        ) == True

    def test_normative_strict_is_strict(self, policy):
        assert policy.is_strict_comparison(
            TruthRegime.NORMATIVE_STRICT,
            AuthorityLevel.MEDIUM
        ) == True

    def test_descriptive_approx_not_strict(self, policy):
        assert policy.is_strict_comparison(
            TruthRegime.DESCRIPTIVE_APPROX,
            AuthorityLevel.MEDIUM
        ) == False


class TestExplainTolerance:
    """Tests for explain_tolerance method."""

    def test_explanation_includes_reasons(self, policy):
        """Explanation should include reasons for the tolerance."""
        explanation = policy.explain_tolerance(
            value_kind="ScalarValue",
            unit="%",
            regime=TruthRegime.DESCRIPTIVE_APPROX,
            authority=AuthorityLevel.MEDIUM,
        )

        assert "tolerance" in explanation
        assert "is_strict" in explanation
        assert "reasons" in explanation
        assert len(explanation["reasons"]) > 0
