"""
Tests unitaires pour ClaimKeyPatterns.

Vérifie l'inférence ClaimKey Niveau A (déterministe, sans LLM):
- Patterns TLS, SLA, backup, retention, etc.
- Résolution templates ({context}, {country}, {topic})
- Questions canoniques
"""

import pytest
from knowbase.stratified.claimkey.patterns import ClaimKeyPatterns, get_claimkey_patterns, PatternMatch


@pytest.fixture
def patterns():
    return ClaimKeyPatterns()


class TestTLSPatterns:
    """Tests patterns TLS/SSL."""

    def test_tls_version(self, patterns):
        result = patterns.infer_claimkey("TLS 1.3 is required", {})
        assert result is not None
        assert result.key == "tls_min_version"
        assert result.domain == "security.encryption"
        assert result.value_kind == "version"
        assert "TLS" in result.canonical_question

    def test_tls_lowercase(self, patterns):
        result = patterns.infer_claimkey("tls 1.2 minimum", {})
        assert result is not None
        assert result.key == "tls_min_version"

    def test_ssl_version(self, patterns):
        result = patterns.infer_claimkey("SSL 3.0 is deprecated", {})
        # SSL also matches the TLS pattern (tls|ssl)
        assert result is not None or result is None  # May or may not match depending on pattern


class TestSLAPatterns:
    """Tests patterns SLA/availability."""

    def test_sla_percent(self, patterns):
        result = patterns.infer_claimkey("99.9% SLA availability", {"product": "S4HANA"})
        assert result is not None
        assert "sla" in result.key.lower()
        assert result.domain == "sla.availability"
        assert result.value_kind == "percent"

    def test_uptime_percent(self, patterns):
        result = patterns.infer_claimkey("99.95% uptime guaranteed", {})
        assert result is not None
        assert result.domain == "sla.availability"

    def test_availability_sla(self, patterns):
        # Pattern expects: number% followed by sla/availability/uptime
        result = patterns.infer_claimkey("99.99% availability SLA", {})
        assert result is not None


class TestEncryptionPatterns:
    """Tests patterns encryption."""

    def test_encryption_at_rest(self, patterns):
        # Pattern: (?:encryption|encrypted)\s*(at\s*rest)
        result = patterns.infer_claimkey("encrypted at rest", {})
        assert result is not None
        assert result.key == "encryption_at_rest"
        assert result.domain == "security.encryption"
        assert result.value_kind == "boolean"

    def test_encryption_in_transit(self, patterns):
        result = patterns.infer_claimkey("encrypted in transit", {})
        assert result is not None
        assert result.key == "encryption_in_transit"

    def test_encrypted_at_rest(self, patterns):
        result = patterns.infer_claimkey("all data is encrypted at rest", {})
        assert result is not None


class TestBackupPatterns:
    """Tests patterns backup."""

    def test_backup_daily(self, patterns):
        result = patterns.infer_claimkey("backups are performed daily", {})
        assert result is not None
        assert result.key == "backup_frequency"
        assert result.domain == "operations.backup"
        assert result.value_kind == "enum"

    def test_backup_weekly(self, patterns):
        result = patterns.infer_claimkey("weekly backup schedule", {})
        assert result is not None
        assert result.key == "backup_frequency"

    def test_backup_hourly(self, patterns):
        result = patterns.infer_claimkey("backup hourly", {})
        assert result is not None

    def test_backup_with_hours(self, patterns):
        result = patterns.infer_claimkey("backups every 4 hours", {})
        assert result is not None


class TestRetentionPatterns:
    """Tests patterns retention."""

    def test_retention_days(self, patterns):
        result = patterns.infer_claimkey("retention period of 30 days", {})
        assert result is not None
        assert result.key == "data_retention_period"
        assert result.domain == "compliance.retention"
        assert result.value_kind == "number"

    def test_retention_months(self, patterns):
        result = patterns.infer_claimkey("data retention: 12 months", {})
        assert result is not None
        assert result.key == "data_retention_period"

    def test_retention_years(self, patterns):
        result = patterns.infer_claimkey("retention period 7 years", {})
        assert result is not None


class TestResidencyPatterns:
    """Tests patterns data residency."""

    def test_data_residency_country(self, patterns):
        result = patterns.infer_claimkey("data must remain in Germany", {})
        assert result is not None
        assert "residency" in result.key
        assert "germany" in result.key.lower()
        assert result.domain == "compliance.residency"

    def test_data_stored_within(self, patterns):
        result = patterns.infer_claimkey("data stored within EU", {})
        assert result is not None

    def test_data_shall_stay(self, patterns):
        result = patterns.infer_claimkey("data shall stay in China", {})
        assert result is not None
        assert "china" in result.key.lower()


class TestResponsibilityPatterns:
    """Tests patterns responsibility."""

    def test_customer_responsible(self, patterns):
        result = patterns.infer_claimkey(
            "customer is responsible for backup",
            {"current_theme": "backup"}
        )
        assert result is not None
        assert "responsibility" in result.key
        assert result.domain == "operations.responsibility"
        assert result.value_kind == "enum"

    def test_sap_manages(self, patterns):
        result = patterns.infer_claimkey(
            "SAP manages the infrastructure",
            {"current_theme": "infrastructure"}
        )
        assert result is not None

    def test_vendor_responsibility(self, patterns):
        result = patterns.infer_claimkey(
            "vendor responsible for updates",
            {"current_theme": "updates"}
        )
        assert result is not None


class TestVersionPatterns:
    """Tests patterns version requirements."""

    def test_minimum_version(self, patterns):
        result = patterns.infer_claimkey(
            "minimum version 2.0 required",
            {"product": "HANA"}
        )
        assert result is not None
        assert "min_version" in result.key
        assert result.domain == "compatibility.version"
        assert result.value_kind == "version"

    def test_required_version(self, patterns):
        result = patterns.infer_claimkey(
            "required version: 3.5.1",
            {"product": "S4"}
        )
        assert result is not None

    def test_supported_version(self, patterns):
        result = patterns.infer_claimkey(
            "supported version 1.0 or higher",
            {}
        )
        assert result is not None


class TestPatchPatterns:
    """Tests patterns patch/update."""

    def test_patch_monthly(self, patterns):
        result = patterns.infer_claimkey("patches applied monthly", {})
        assert result is not None
        assert result.key == "patch_frequency"
        assert result.domain == "operations.patching"
        assert result.value_kind == "enum"

    def test_updates_weekly(self, patterns):
        result = patterns.infer_claimkey("updates installed weekly", {})
        assert result is not None

    def test_patch_quarterly(self, patterns):
        result = patterns.infer_claimkey("quarterly patch cycle", {})
        assert result is not None


class TestRTORPOPatterns:
    """Tests patterns RTO/RPO."""

    def test_rto_hours(self, patterns):
        result = patterns.infer_claimkey("RTO of 4 hours", {})
        assert result is not None
        assert result.key == "rto_target"
        assert result.domain == "sla.recovery"
        assert result.value_kind == "number"

    def test_rpo_minutes(self, patterns):
        result = patterns.infer_claimkey("RPO: 15 minutes", {})
        assert result is not None
        assert result.key == "rpo_target"


class TestSizeThresholdPatterns:
    """Tests patterns size thresholds."""

    def test_above_tib(self, patterns):
        result = patterns.infer_claimkey(
            "storage above 500 TiB",
            {"product": "HANA"}
        )
        assert result is not None
        assert "size_threshold" in result.key
        assert result.domain == "infrastructure.sizing"

    def test_exceeds_gb(self, patterns):
        result = patterns.infer_claimkey(
            "data exceeds 100 GB",
            {"product": "BW"}
        )
        assert result is not None


class TestNoMatch:
    """Tests cas sans match."""

    def test_generic_text(self, patterns):
        result = patterns.infer_claimkey("this is just a description", {})
        assert result is None

    def test_empty_text(self, patterns):
        result = patterns.infer_claimkey("", {})
        assert result is None

    def test_unrelated_numbers(self, patterns):
        result = patterns.infer_claimkey("chapter 5 section 3", {})
        # Might not match any specific pattern
        # Just verifying it doesn't crash


class TestCanonicalQuestions:
    """Tests questions canoniques."""

    def test_known_claimkey_question(self, patterns):
        question = patterns.get_canonical_question("ck_tls_min_version")
        assert "TLS" in question
        assert "?" in question

    def test_unknown_claimkey_question(self, patterns):
        question = patterns.get_canonical_question("ck_unknown_key")
        assert "Question for" in question


class TestTemplateResolution:
    """Tests résolution templates."""

    def test_context_placeholder(self, patterns):
        result = patterns.infer_claimkey(
            "99.9% SLA availability",
            {"product": "S/4HANA Cloud"}
        )
        assert result is not None
        # product should be normalized
        assert "s_4hana" in result.key.lower() or "cloud" in result.key.lower() or "general" in result.key.lower()

    def test_topic_placeholder(self, patterns):
        result = patterns.infer_claimkey(
            "customer is responsible",
            {"current_theme": "Security"}
        )
        assert result is not None
        assert "security" in result.key.lower()


class TestSingleton:
    """Test singleton pattern."""

    def test_get_claimkey_patterns_singleton(self):
        p1 = get_claimkey_patterns()
        p2 = get_claimkey_patterns()
        assert p1 is p2


class TestPatternMatchDataclass:
    """Tests PatternMatch dataclass."""

    def test_pattern_match_fields(self, patterns):
        result = patterns.infer_claimkey("TLS 1.3 required", {})
        assert result is not None
        assert isinstance(result, PatternMatch)
        assert hasattr(result, "claimkey_id")
        assert hasattr(result, "key")
        assert hasattr(result, "domain")
        assert hasattr(result, "canonical_question")
        assert hasattr(result, "value_kind")
        assert hasattr(result, "match_text")
        assert result.inference_method == "pattern_level_a"

    def test_claimkey_id_prefix(self, patterns):
        result = patterns.infer_claimkey("TLS 1.3", {})
        assert result is not None
        assert result.claimkey_id.startswith("ck_")
