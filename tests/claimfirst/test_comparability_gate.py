# tests/claimfirst/test_comparability_gate.py
"""Tests Phase 2 — Candidate Gating domain-agnostic (v1 + v2 signals)."""

import pytest
from dataclasses import dataclass
from typing import Optional, Dict, Any

from knowbase.claimfirst.extractors.comparability_gate import (
    candidate_gate,
    GatingResult,
)


@dataclass
class FakeClaim:
    claim_id: str = "c1"
    text: str = ""
    claim_type: Optional[Any] = None
    structured_form: Optional[Dict] = None


class TestStrongSignals:

    def test_numeric_with_unit(self):
        claim = FakeClaim(text="The system requires 128 GB of RAM for production", structured_form={"subject": "system"})
        result = candidate_gate(claim)
        assert result.retained is True
        assert any("numeric_with_unit" in s for s in result.signals)

    def test_version_explicit(self):
        claim = FakeClaim(text="The protocol must support version 3.1 for compliance", structured_form={"subject": "protocol"})
        result = candidate_gate(claim)
        assert result.retained is True
        assert any("version_explicit" in s for s in result.signals)

    def test_constraint_min_max(self):
        claim = FakeClaim(text="Users can store at least 500 records in the database", structured_form={"subject": "database"})
        result = candidate_gate(claim)
        assert result.retained is True
        assert any("constraint_min_max" in s for s in result.signals)

    def test_deprecation(self):
        claim = FakeClaim(text="The legacy interface has been deprecated since the last major release", structured_form={"subject": "interface"})
        result = candidate_gate(claim)
        assert result.retained is True
        assert any("deprecation" in s for s in result.signals)

    def test_default_value(self):
        claim = FakeClaim(text="The connection timeout defaults to 30 for all endpoints", structured_form={"subject": "connection"})
        result = candidate_gate(claim)
        assert result.retained is True
        assert any("default_value" in s for s in result.signals)


class TestWeakSignals:

    def test_two_weak_signals_retained(self):
        claim = FakeClaim(
            text="Encryption must be enabled for all production environments",
            structured_form={"subject": "encryption"},
        )
        result = candidate_gate(claim)
        assert result.retained is True
        weak_signals = [s for s in result.signals if s.startswith("weak:")]
        assert len(weak_signals) >= 2

    def test_one_weak_with_entity_retained(self):
        claim = FakeClaim(
            text="The feature is supported on all editions of the product",
            structured_form={"entities": [{"name": "ProductX"}]},
        )
        result = candidate_gate(claim)
        assert result.retained is True

    def test_one_weak_without_entity_rejected(self):
        """1 signal faible + structured_form non vide → RETAINED (v2 rule)."""
        claim = FakeClaim(
            text="The configuration must follow the established guidelines and procedures",
            structured_form={},  # structured_form vide (falsy)
        )
        result = candidate_gate(claim)
        # En v2, structured_form={} est falsy → pas de bonus structured_form
        # "must" match normative_with_value? Non, pas de valeur après "must"
        # Donc toujours rejeté
        assert result.retained is False


class TestNegativeSignals:

    def test_text_too_short(self):
        claim = FakeClaim(text="Short text", structured_form={"subject": "x"})
        result = candidate_gate(claim)
        assert result.retained is False
        assert result.rejection_reason == "text_too_short"

    def test_no_structured_form_no_entities(self):
        claim = FakeClaim(
            text="This is a sufficiently long claim text that should be analyzed properly",
            structured_form=None,
        )
        result = candidate_gate(claim)
        assert result.retained is False
        assert result.rejection_reason == "no_structured_form_no_entities"


class TestDomainAgnostic:

    def test_no_domain_keywords_in_patterns(self):
        """Vérifier qu'aucun pattern ne contient de mots-clés domaine."""
        from knowbase.claimfirst.extractors.comparability_gate import STRONG_SIGNALS, WEAK_SIGNALS
        domain_keywords = {"tls", "sla", "backup", "ram", "sap", "sql", "ssl", "ssh", "http"}
        for name, pattern in {**STRONG_SIGNALS, **WEAK_SIGNALS}.items():
            pattern_str = pattern.pattern.lower()
            for kw in domain_keywords:
                assert kw not in pattern_str, f"Pattern {name} contient mot-clé domaine: {kw}"


# ── V2 : Nouveaux signaux ─────────────────────────────────────────────

class TestNormativeWithValue:
    """weak:normative_with_value remplace weak:normative_operator."""

    def test_normative_with_numeric_value(self):
        claim = FakeClaim(
            text="The system must support 256 concurrent connections at all times",
            structured_form={"subject": "system"},
        )
        result = candidate_gate(claim)
        assert result.retained is True
        assert any("normative_with_value" in s for s in result.signals)

    def test_normative_with_boolean_value(self):
        claim = FakeClaim(
            text="Encryption shall be enabled for all external communications",
            structured_form={"subject": "encryption"},
        )
        result = candidate_gate(claim)
        assert result.retained is True
        assert any("normative_with_value" in s for s in result.signals)

    def test_normative_without_value_rejected(self):
        """Mot normatif seul sans valeur → pas de signal normative_with_value."""
        claim = FakeClaim(
            text="The configuration must follow the established guidelines and procedures",
            structured_form={},
        )
        result = candidate_gate(claim)
        # Pas de valeur après "must" → pas normative_with_value
        assert not any("normative_with_value" in s for s in result.signals)


class TestComparisonWords:

    def test_comparison_higher(self):
        claim = FakeClaim(
            text="The throughput is higher than the industry average for this category",
            structured_form={"subject": "throughput"},
        )
        result = candidate_gate(claim)
        assert any("comparison_words" in s for s in result.signals)

    def test_comparison_between(self):
        claim = FakeClaim(
            text="The value is between the acceptable range and the maximum limit value",
            structured_form={"subject": "value"},
        )
        result = candidate_gate(claim)
        assert any("comparison_words" in s for s in result.signals)


class TestTemporalMarker:

    def test_since_version(self):
        claim = FakeClaim(
            text="This feature has been available since the initial deployment of the platform",
            structured_form={"subject": "feature"},
        )
        result = candidate_gate(claim)
        assert any("temporal_marker" in s for s in result.signals)

    def test_starting_with(self):
        claim = FakeClaim(
            text="Starting with the new release, the feature requires additional configuration",
            structured_form={"subject": "feature"},
        )
        result = candidate_gate(claim)
        assert any("temporal_marker" in s for s in result.signals)


class TestListConstraint:

    def test_one_of(self):
        claim = FakeClaim(
            text="The authentication method must be one of the approved protocols listed below",
            structured_form={"subject": "auth"},
        )
        result = candidate_gate(claim)
        assert any("list_constraint" in s for s in result.signals)

    def test_only(self):
        claim = FakeClaim(
            text="Only administrators can access the advanced configuration panel directly",
            structured_form={"subject": "access"},
        )
        result = candidate_gate(claim)
        assert any("list_constraint" in s for s in result.signals)


class TestProtocolFormat:

    def test_tls_version(self):
        """Pattern opportuniste : TLS 1.2 capté comme format techno.
        Note : cette claim matche aussi strong:version_explicit, donc elle
        est retenue via le signal fort avant même d'évaluer les signaux faibles.
        On vérifie directement le regex ici."""
        import re
        from knowbase.claimfirst.extractors.comparability_gate import WEAK_SIGNALS
        pattern = WEAK_SIGNALS["weak:protocol_format"]
        assert pattern.search("The connection uses TLS 1.2 for secure communication")

    def test_http_version(self):
        import re
        from knowbase.claimfirst.extractors.comparability_gate import WEAK_SIGNALS
        pattern = WEAK_SIGNALS["weak:protocol_format"]
        assert pattern.search("The API supports HTTP 2.0 for improved performance")

    def test_no_match_lowercase(self):
        """protocol_format exige majuscules (case-sensitive)."""
        claim = FakeClaim(
            text="the system uses tls 1.2 for secure connections between all nodes",
            structured_form={"subject": "system"},
        )
        result = candidate_gate(claim)
        assert not any("protocol_format" in s for s in result.signals)


class TestStructuredFormRule:
    """V2 : 1 signal faible + structured_form non vide → RETAIN."""

    def test_one_weak_with_structured_form_retained(self):
        claim = FakeClaim(
            text="The platform supports only the enterprise edition for production deployments",
            structured_form={"subject": "platform", "predicate": "supports"},
        )
        result = candidate_gate(claim)
        # "only" = list_constraint (1 signal faible) + structured_form non vide → retained
        assert result.retained is True

    def test_one_weak_empty_structured_form_rejected(self):
        """structured_form={} est falsy → pas de bonus."""
        claim = FakeClaim(
            text="Only authorized users can perform this particular administrative action",
            structured_form={},
        )
        result = candidate_gate(claim)
        # {} is falsy, so no structured_form bonus.
        # "only" = 1 weak signal, no entity → check if there are other signals
        # "authorized" doesn't match anything extra → rejected with 1 weak
        assert result.retained is False

    def test_no_weak_with_structured_form_still_rejected(self):
        """structured_form ne suffit pas seule, il faut au moins 1 signal faible."""
        claim = FakeClaim(
            text="The platform provides comprehensive documentation for all features available",
            structured_form={"subject": "platform", "predicate": "provides"},
        )
        result = candidate_gate(claim)
        assert result.retained is False


class TestRegression:
    """Les claims retenues en v1 restent retenues."""

    def test_strong_signal_still_works(self):
        claim = FakeClaim(
            text="The system requires 128 GB of RAM for production environments",
            structured_form={"subject": "system"},
        )
        result = candidate_gate(claim)
        assert result.retained is True

    def test_two_weak_still_works(self):
        claim = FakeClaim(
            text="The daily threshold must be enabled for compliance monitoring across regions",
            structured_form={"subject": "threshold"},
        )
        result = candidate_gate(claim)
        assert result.retained is True
