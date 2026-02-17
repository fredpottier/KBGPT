"""
Tests pour la reclassification déterministe post-LLM des axis_values.

10 tests couvrant:
- Reclassification YYYY temporal→revision avec produit dans le titre
- Pas de reclassification quand le contexte produit est absent
- Pas de reclassification quand la valeur n'est pas dans le titre
- Downgrade via evidence_quote_contains_any
- Pas de rules → pas de changement
- Rules vides → pas de changement
- JSON invalide → warning, pas de crash
- Priorité des rules
- confidence_override
- new_role invalide → skip, pas de crash
"""

import json
import logging
from unittest.mock import MagicMock, patch

import pytest

from knowbase.claimfirst.models.subject_resolver_output import (
    AxisValueOutput,
    ComparableSubjectOutput,
    DiscriminatingRole,
    EvidenceSpanOutput,
    EvidenceSource,
    SubjectResolverOutput,
    SupportEvidence,
)
from knowbase.claimfirst.resolution.subject_resolver_v2 import SubjectResolverV2


# ── Helpers ──────────────────────────────────────────────────────────────

def _make_axis(
    value_raw: str,
    role: DiscriminatingRole,
    confidence: float = 0.85,
    rationale: str = "LLM rationale",
    evidence_quotes: list[str] | None = None,
) -> AxisValueOutput:
    spans = []
    for q in (evidence_quotes or []):
        spans.append(EvidenceSpanOutput(source=EvidenceSource.TITLE, quote=q))
    return AxisValueOutput(
        value_raw=value_raw,
        discriminating_role=role,
        confidence=confidence,
        rationale=rationale,
        support=SupportEvidence(evidence_spans=spans),
    )


def _make_output(*axes: AxisValueOutput) -> SubjectResolverOutput:
    return SubjectResolverOutput(
        comparable_subject=ComparableSubjectOutput(
            label="SAP S/4HANA",
            confidence=0.95,
            rationale="test subject",
        ),
        axis_values=list(axes),
    )


def _mock_profile(rules_json: str):
    """Crée un mock DomainContextProfile avec les rules données."""
    profile = MagicMock()
    profile.axis_reclassification_rules = rules_json
    return profile


def _mock_store(profile):
    """Crée un mock store qui retourne le profil donné."""
    store = MagicMock()
    store.get_profile.return_value = profile
    return store


RULE_YYYY_TITLE_PRODUCT = {
    "rule_id": "yyyy_in_title_with_product_is_revision",
    "priority": 100,
    "conditions": {
        "value_pattern": r"^(19|20)\d{2}$",
        "current_role": "temporal",
        "title_contains_value": True,
        "title_context_pattern": r"(?i)(s/4hana|sap\s|release|version|upgrade|feature pack)",
    },
    "action": {"new_role": "revision"},
}

RULE_DOC_VERSION = {
    "rule_id": "doc_version_not_product_release",
    "priority": 90,
    "conditions": {
        "value_pattern": r"^\d+\.\d+$",
        "current_role": "revision",
        "evidence_quote_contains_any": ["document version", "doc version"],
    },
    "action": {"new_role": "unknown", "confidence_override": 0.3},
}


# ── Tests ────────────────────────────────────────────────────────────────

class TestReclassificationRules:

    @patch("knowbase.ontology.domain_context_store.get_domain_context_store")
    def test_yyyy_temporal_in_title_with_product_reclassified(self, mock_get_store):
        """'2021' temporal + titre 'Operations Guide for SAP S/4HANA 2021' → revision."""
        rules = json.dumps([RULE_YYYY_TITLE_PRODUCT])
        mock_get_store.return_value = _mock_store(_mock_profile(rules))

        resolver = SubjectResolverV2(tenant_id="default")
        av = _make_axis("2021", DiscriminatingRole.TEMPORAL)
        output = _make_output(av)

        result = resolver._apply_reclassification_rules(
            output, "Operations Guide for SAP S/4HANA 2021"
        )

        assert result.axis_values[0].discriminating_role == DiscriminatingRole.REVISION
        assert "[Reclassified temporal" in result.axis_values[0].rationale
        assert "yyyy_in_title_with_product_is_revision" in result.axis_values[0].rationale

    @patch("knowbase.ontology.domain_context_store.get_domain_context_store")
    def test_yyyy_temporal_in_title_without_product_stays(self, mock_get_store):
        """'2021' temporal + titre 'Annual Report 2021' (pas de produit) → reste temporal."""
        rules = json.dumps([RULE_YYYY_TITLE_PRODUCT])
        mock_get_store.return_value = _mock_store(_mock_profile(rules))

        resolver = SubjectResolverV2(tenant_id="default")
        av = _make_axis("2021", DiscriminatingRole.TEMPORAL)
        output = _make_output(av)

        result = resolver._apply_reclassification_rules(
            output, "Annual Report 2021"
        )

        assert result.axis_values[0].discriminating_role == DiscriminatingRole.TEMPORAL

    @patch("knowbase.ontology.domain_context_store.get_domain_context_store")
    def test_yyyy_temporal_not_in_title_stays(self, mock_get_store):
        """'2021' temporal, titre ne contient pas '2021' → reste temporal."""
        rules = json.dumps([RULE_YYYY_TITLE_PRODUCT])
        mock_get_store.return_value = _mock_store(_mock_profile(rules))

        resolver = SubjectResolverV2(tenant_id="default")
        av = _make_axis("2021", DiscriminatingRole.TEMPORAL)
        output = _make_output(av)

        result = resolver._apply_reclassification_rules(
            output, "SAP S/4HANA Operations Guide"
        )

        assert result.axis_values[0].discriminating_role == DiscriminatingRole.TEMPORAL

    @patch("knowbase.ontology.domain_context_store.get_domain_context_store")
    def test_doc_version_with_evidence_quote_downgraded(self, mock_get_store):
        """'9.0' revision + evidence 'Document Version: 9.0' → unknown, confidence 0.3."""
        rules = json.dumps([RULE_DOC_VERSION])
        mock_get_store.return_value = _mock_store(_mock_profile(rules))

        resolver = SubjectResolverV2(tenant_id="default")
        av = _make_axis(
            "9.0",
            DiscriminatingRole.REVISION,
            confidence=0.85,
            evidence_quotes=["Document Version: 9.0"],
        )
        output = _make_output(av)

        result = resolver._apply_reclassification_rules(output, "Some Title")

        assert result.axis_values[0].discriminating_role == DiscriminatingRole.UNKNOWN
        assert result.axis_values[0].confidence == pytest.approx(0.3)

    @patch("knowbase.ontology.domain_context_store.get_domain_context_store")
    def test_no_rules_no_change(self, mock_get_store):
        """Profil sans rules → inchangé."""
        mock_get_store.return_value = _mock_store(_mock_profile(""))

        resolver = SubjectResolverV2(tenant_id="default")
        av = _make_axis("2021", DiscriminatingRole.TEMPORAL)
        output = _make_output(av)

        result = resolver._apply_reclassification_rules(output, "SAP S/4HANA 2021")

        assert result.axis_values[0].discriminating_role == DiscriminatingRole.TEMPORAL

    @patch("knowbase.ontology.domain_context_store.get_domain_context_store")
    def test_empty_rules_no_change(self, mock_get_store):
        """rules = '[]' → inchangé."""
        mock_get_store.return_value = _mock_store(_mock_profile("[]"))

        resolver = SubjectResolverV2(tenant_id="default")
        av = _make_axis("2021", DiscriminatingRole.TEMPORAL)
        output = _make_output(av)

        result = resolver._apply_reclassification_rules(output, "SAP S/4HANA 2021")

        assert result.axis_values[0].discriminating_role == DiscriminatingRole.TEMPORAL

    @patch("knowbase.ontology.domain_context_store.get_domain_context_store")
    def test_invalid_json_rules_logged_no_crash(self, mock_get_store, caplog):
        """rules = 'invalid{' → inchangé, logger.warning."""
        mock_get_store.return_value = _mock_store(_mock_profile("invalid{"))

        resolver = SubjectResolverV2(tenant_id="default")
        av = _make_axis("2021", DiscriminatingRole.TEMPORAL)
        output = _make_output(av)

        with caplog.at_level(logging.WARNING):
            result = resolver._apply_reclassification_rules(output, "SAP S/4HANA 2021")

        assert result.axis_values[0].discriminating_role == DiscriminatingRole.TEMPORAL
        assert "Invalid JSON" in caplog.text

    @patch("knowbase.ontology.domain_context_store.get_domain_context_store")
    def test_priority_ordering(self, mock_get_store):
        """Deux rules applicables, priority=100 gagne sur priority=50."""
        rule_low = {
            "rule_id": "low_priority",
            "priority": 50,
            "conditions": {
                "value_pattern": r"^(19|20)\d{2}$",
                "current_role": "temporal",
            },
            "action": {"new_role": "unknown"},
        }
        rule_high = {
            "rule_id": "high_priority",
            "priority": 100,
            "conditions": {
                "value_pattern": r"^(19|20)\d{2}$",
                "current_role": "temporal",
            },
            "action": {"new_role": "revision"},
        }
        # Injecter low en premier dans la liste pour prouver que le tri par priorité fonctionne
        rules = json.dumps([rule_low, rule_high])
        mock_get_store.return_value = _mock_store(_mock_profile(rules))

        resolver = SubjectResolverV2(tenant_id="default")
        av = _make_axis("2021", DiscriminatingRole.TEMPORAL)
        output = _make_output(av)

        result = resolver._apply_reclassification_rules(output, "Any title")

        assert result.axis_values[0].discriminating_role == DiscriminatingRole.REVISION
        assert "high_priority" in result.axis_values[0].rationale

    @patch("knowbase.ontology.domain_context_store.get_domain_context_store")
    def test_confidence_override(self, mock_get_store):
        """Vérifie confidence_override dans action."""
        rule = {
            "rule_id": "override_test",
            "priority": 100,
            "conditions": {
                "value_pattern": r"^(19|20)\d{2}$",
                "current_role": "temporal",
            },
            "action": {"new_role": "revision", "confidence_override": 0.99},
        }
        rules = json.dumps([rule])
        mock_get_store.return_value = _mock_store(_mock_profile(rules))

        resolver = SubjectResolverV2(tenant_id="default")
        av = _make_axis("2021", DiscriminatingRole.TEMPORAL, confidence=0.5)
        output = _make_output(av)

        result = resolver._apply_reclassification_rules(output, "Title")

        assert result.axis_values[0].confidence == pytest.approx(0.99)

    @patch("knowbase.ontology.domain_context_store.get_domain_context_store")
    def test_invalid_new_role_skipped(self, mock_get_store, caplog):
        """new_role='bogus' → pas de crash, warning loggé, axis inchangé."""
        rule = {
            "rule_id": "bogus_rule",
            "priority": 100,
            "conditions": {
                "value_pattern": r"^(19|20)\d{2}$",
                "current_role": "temporal",
            },
            "action": {"new_role": "bogus"},
        }
        rules = json.dumps([rule])
        mock_get_store.return_value = _mock_store(_mock_profile(rules))

        resolver = SubjectResolverV2(tenant_id="default")
        av = _make_axis("2021", DiscriminatingRole.TEMPORAL)
        output = _make_output(av)

        with caplog.at_level(logging.WARNING):
            result = resolver._apply_reclassification_rules(output, "Title")

        assert result.axis_values[0].discriminating_role == DiscriminatingRole.TEMPORAL
        assert "Invalid role 'bogus'" in caplog.text
