"""
Tests for StructuredExtractor - Text to ClaimForm extraction.

Tests the extraction of structured claim forms from text.

Author: Claude Code
Date: 2026-02-03
"""

import pytest

from knowbase.verification.comparison import (
    StructuredExtractor,
    ClaimFormType,
    TruthRegime,
    AuthorityLevel,
    ScalarValue,
    IntervalValue,
    SetValue,
    InequalityValue,
    BooleanValue,
    VersionValue,
)


@pytest.fixture
def extractor():
    return StructuredExtractor()


class TestPercentageExtraction:
    """Tests for percentage value extraction."""

    @pytest.mark.asyncio
    async def test_scalar_percent(self, extractor):
        """Extract scalar percentage: 'SLA is 99.5%'"""
        form = await extractor.extract("The SLA is 99.5%")

        assert form is not None
        assert form.form_type == ClaimFormType.EXACT_VALUE
        assert isinstance(form.value, ScalarValue)
        assert form.value.value == 99.5
        assert form.value.unit == "%"
        assert form.property_surface.lower() == "sla"

    @pytest.mark.asyncio
    async def test_interval_percent(self, extractor):
        """Extract interval percentage: 'SLA between 99.7-99.9%'"""
        form = await extractor.extract("The SLA is 99.7-99.9%")

        assert form is not None
        assert form.form_type == ClaimFormType.INTERVAL_VALUE
        assert isinstance(form.value, IntervalValue)
        assert form.value.low == 99.7
        assert form.value.high == 99.9

    @pytest.mark.asyncio
    async def test_french_percent(self, extractor):
        """Extract French percentage: 'Le SLA est de 99,5%'"""
        form = await extractor.extract("Le SLA est de 99,5%")

        assert form is not None
        assert isinstance(form.value, ScalarValue)
        assert form.value.value == 99.5


class TestDurationExtraction:
    """Tests for duration value extraction."""

    @pytest.mark.asyncio
    async def test_scalar_minutes(self, extractor):
        """Extract scalar duration: 'RPO is 30 minutes'"""
        form = await extractor.extract("The RPO is 30 minutes")

        assert form is not None
        assert isinstance(form.value, ScalarValue)
        assert form.value.value == 30
        assert form.value.unit == "min"

    @pytest.mark.asyncio
    async def test_set_values(self, extractor):
        """Extract set of values: 'RPO is 0 or 30 min'"""
        form = await extractor.extract("The RPO is 0 or 30 min")

        assert form is not None
        assert form.form_type == ClaimFormType.SET_VALUE
        assert isinstance(form.value, SetValue)
        assert 0 in form.value.values
        assert 30 in form.value.values

    @pytest.mark.asyncio
    async def test_interval_duration(self, extractor):
        """Extract interval duration: 'RTO is 0-30 min'"""
        form = await extractor.extract("The RTO is 0-30 min")

        assert form is not None
        assert form.form_type == ClaimFormType.INTERVAL_VALUE
        assert isinstance(form.value, IntervalValue)


class TestInequalityExtraction:
    """Tests for inequality extraction."""

    @pytest.mark.asyncio
    async def test_at_least(self, extractor):
        """Extract 'at least' inequality"""
        form = await extractor.extract("SLA must be at least 99.5%")

        assert form is not None
        assert form.form_type == ClaimFormType.BOUNDED_VALUE
        assert isinstance(form.value, InequalityValue)
        assert form.value.operator == ">="
        assert form.value.bound == 99.5

    @pytest.mark.asyncio
    async def test_at_most(self, extractor):
        """Extract 'at most' inequality"""
        form = await extractor.extract("Latency must be at most 100 ms")

        assert form is not None
        assert isinstance(form.value, InequalityValue)
        assert form.value.operator == "<="
        assert form.value.bound == 100

    @pytest.mark.asyncio
    async def test_minimum(self, extractor):
        """Extract 'minimum' inequality with direct value"""
        # Use a format where minimum is directly followed by the value
        form = await extractor.extract("Minimum 99.9% availability required")

        assert form is not None
        assert isinstance(form.value, InequalityValue)
        assert form.value.operator == ">="


class TestBooleanExtraction:
    """Tests for boolean value extraction."""

    @pytest.mark.asyncio
    async def test_supported(self, extractor):
        """Extract 'supported' boolean"""
        form = await extractor.extract("Encryption is supported")

        assert form is not None
        assert form.form_type == ClaimFormType.BOOLEAN_VALUE
        assert isinstance(form.value, BooleanValue)
        assert form.value.value == True

    @pytest.mark.asyncio
    async def test_not_supported(self, extractor):
        """Extract 'not supported' boolean"""
        form = await extractor.extract("The feature is not supported")

        assert form is not None
        assert isinstance(form.value, BooleanValue)
        assert form.value.value == False


class TestVersionExtraction:
    """Tests for version extraction."""

    @pytest.mark.asyncio
    async def test_tls_version(self, extractor):
        """Extract TLS version"""
        form = await extractor.extract("TLS 1.2 is required")

        assert form is not None
        assert form.form_type == ClaimFormType.VERSION_VALUE
        assert isinstance(form.value, VersionValue)
        assert form.value.major == 1
        assert form.value.minor == 2

    @pytest.mark.asyncio
    async def test_software_version(self, extractor):
        """Extract software version"""
        form = await extractor.extract("Version 2023.10 is available")

        assert form is not None
        assert isinstance(form.value, VersionValue)


class TestTruthRegimeDetection:
    """Tests for truth regime detection."""

    @pytest.mark.asyncio
    async def test_normative_strict(self, extractor):
        """Detect NORMATIVE_STRICT from 'must'"""
        form = await extractor.extract("SLA must be 99.5%")

        assert form is not None
        assert form.truth_regime == TruthRegime.NORMATIVE_STRICT

    @pytest.mark.asyncio
    async def test_normative_bounded(self, extractor):
        """Detect NORMATIVE_BOUNDED from 'at least'"""
        # Note: "should" triggers NORMATIVE_STRICT before "at least" triggers BOUNDED
        # Use a clearer sentence
        form = await extractor.extract("Capacity at least 1000 users")

        assert form is not None
        assert form.truth_regime == TruthRegime.NORMATIVE_BOUNDED

    @pytest.mark.asyncio
    async def test_descriptive_approx(self, extractor):
        """Detect DESCRIPTIVE_APPROX from 'approximately'"""
        form = await extractor.extract("SLA is approximately 99.5%")

        assert form is not None
        assert form.truth_regime == TruthRegime.DESCRIPTIVE_APPROX


class TestScopeExtraction:
    """Tests for scope extraction."""

    @pytest.mark.asyncio
    async def test_version_scope(self, extractor):
        """Extract version scope"""
        form = await extractor.extract("For version 2023, SLA is 99.5%")

        assert form is not None
        assert form.scope_version == "2023"

    @pytest.mark.asyncio
    async def test_edition_scope(self, extractor):
        """Extract edition scope"""
        form = await extractor.extract("Enterprise edition SLA is 99.9%")

        assert form is not None
        assert form.scope_edition == "Enterprise"

    @pytest.mark.asyncio
    async def test_region_scope(self, extractor):
        """Extract region scope"""
        form = await extractor.extract("EU region SLA is 99.5%")

        assert form is not None
        assert form.scope_region == "EU"


class TestPropertyExtraction:
    """Tests for property name extraction."""

    @pytest.mark.asyncio
    async def test_sla_property(self, extractor):
        """Extract SLA property"""
        form = await extractor.extract("The SLA guarantee is 99.5%")

        assert form is not None
        assert form.property_surface.lower() == "sla"
        assert form.claim_key == "service_level_agreement"

    @pytest.mark.asyncio
    async def test_rpo_property(self, extractor):
        """Extract RPO property"""
        form = await extractor.extract("The RPO is 30 minutes")

        assert form is not None
        assert form.property_surface.lower() == "rpo"
        assert form.claim_key == "recovery_point_objective"


class TestFallbackToText:
    """Tests for fallback to TEXT_VALUE."""

    @pytest.mark.asyncio
    async def test_complex_text_fallback(self, extractor):
        """Complex text without clear values should fallback"""
        form = await extractor.extract(
            "The system provides comprehensive monitoring capabilities"
        )

        assert form is not None
        assert form.form_type == ClaimFormType.TEXT_VALUE


class TestSyncExtraction:
    """Tests for synchronous extraction."""

    def test_sync_extract(self, extractor):
        """Test synchronous extraction method"""
        form = extractor.extract_sync("SLA is 99.5%")

        assert form is not None
        assert isinstance(form.value, ScalarValue)
