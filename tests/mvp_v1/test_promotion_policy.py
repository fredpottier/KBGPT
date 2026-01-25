"""
Tests unitaires pour PromotionPolicy.

Vérifie la politique de promotion Information-First:
- Promotion par type (PRESCRIPTIVE, DEFINITIONAL)
- Promotion par rôle (fact, definition, instruction)
- Rejet par pattern méta
- Défaut PROMOTED_UNLINKED (jamais de rejet silencieux)
"""

import pytest
from knowbase.stratified.pass1.promotion_policy import PromotionPolicy, get_promotion_policy
from knowbase.stratified.models.information import PromotionStatus


@pytest.fixture
def policy():
    return PromotionPolicy()


class TestPromotionByType:
    """Tests promotion par type d'assertion."""

    def test_prescriptive_always_promoted(self, policy):
        assertion = {
            "text": "All data must be encrypted at rest",
            "type": "PRESCRIPTIVE",
            "rhetorical_role": "fact"
        }
        status, reason = policy.evaluate(assertion)
        assert status == PromotionStatus.PROMOTED_LINKED
        assert "type:PRESCRIPTIVE" in reason

    def test_definitional_always_promoted(self, policy):
        assertion = {
            "text": "SAP S/4HANA is an ERP system",
            "type": "DEFINITIONAL",
            "rhetorical_role": "definition"
        }
        status, reason = policy.evaluate(assertion)
        assert status == PromotionStatus.PROMOTED_LINKED
        assert "type:DEFINITIONAL" in reason

    def test_causal_not_auto_promoted(self, policy):
        assertion = {
            "text": "Because of the architecture, performance is improved",
            "type": "CAUSAL",
            "rhetorical_role": "claim"
        }
        status, reason = policy.evaluate(assertion)
        # CAUSAL n'est pas dans ALWAYS_PROMOTE_TYPES
        assert status in [PromotionStatus.PROMOTED_LINKED, PromotionStatus.PROMOTED_UNLINKED]


class TestPromotionByRole:
    """Tests promotion par rôle rhétorique."""

    def test_fact_role_promoted(self, policy):
        assertion = {
            "text": "The system supports up to 1000 concurrent users",
            "type": "COMPARATIVE",
            "rhetorical_role": "fact"
        }
        status, reason = policy.evaluate(assertion)
        assert status == PromotionStatus.PROMOTED_LINKED
        assert "role:fact" in reason

    def test_definition_role_promoted(self, policy):
        assertion = {
            "text": "A tenant is an isolated logical environment",
            "type": "COMPARATIVE",
            "rhetorical_role": "definition"
        }
        status, reason = policy.evaluate(assertion)
        assert status == PromotionStatus.PROMOTED_LINKED
        assert "role:definition" in reason

    def test_instruction_role_promoted(self, policy):
        assertion = {
            "text": "Configure the firewall to allow port 443",
            "type": "COMPARATIVE",
            "rhetorical_role": "instruction"
        }
        status, reason = policy.evaluate(assertion)
        assert status == PromotionStatus.PROMOTED_LINKED
        assert "role:instruction" in reason

    def test_example_role_unlinked(self, policy):
        """Examples are promoted but without ClaimKey."""
        assertion = {
            "text": "For example, you can use the REST API",
            "type": "COMPARATIVE",
            "rhetorical_role": "example"
        }
        status, reason = policy.evaluate(assertion)
        assert status == PromotionStatus.PROMOTED_UNLINKED
        assert "role_no_claimkey" in reason

    def test_caution_role_unlinked(self, policy):
        """Cautions are promoted but without ClaimKey."""
        assertion = {
            "text": "Warning: This action cannot be undone",
            "type": "COMPARATIVE",
            "rhetorical_role": "caution"
        }
        status, reason = policy.evaluate(assertion)
        assert status == PromotionStatus.PROMOTED_UNLINKED
        assert "role_no_claimkey" in reason


class TestPromotionByValue:
    """Tests promotion par présence de valeur."""

    def test_with_value_promoted(self, policy):
        assertion = {
            "text": "Storage capacity is 500 GB",
            "type": "COMPARATIVE",
            "rhetorical_role": "claim",
            "value": {"kind": "number", "normalized": 500}
        }
        status, reason = policy.evaluate(assertion)
        assert status == PromotionStatus.PROMOTED_LINKED
        assert "has_value" in reason


class TestRejectionByPattern:
    """Tests rejet par pattern méta."""

    def test_meta_page_describes(self, policy):
        assertion = {
            "text": "This page describes the configuration options",
            "type": "DEFINITIONAL",
            "rhetorical_role": "fact"
        }
        status, reason = policy.evaluate(assertion)
        assert status == PromotionStatus.REJECTED
        assert "meta_pattern" in reason

    def test_meta_see_also(self, policy):
        assertion = {
            "text": "See also the documentation for more details",
            "type": "DEFINITIONAL",
            "rhetorical_role": "fact"
        }
        status, reason = policy.evaluate(assertion)
        assert status == PromotionStatus.REJECTED
        assert "meta_pattern" in reason

    def test_meta_refer_to(self, policy):
        assertion = {
            "text": "Refer to chapter 5 for security guidelines",
            "type": "DEFINITIONAL",
            "rhetorical_role": "fact"
        }
        status, reason = policy.evaluate(assertion)
        assert status == PromotionStatus.REJECTED
        assert "meta_pattern" in reason

    def test_meta_for_more_information(self, policy):
        assertion = {
            "text": "For more information, visit our website",
            "type": "DEFINITIONAL",
            "rhetorical_role": "fact"
        }
        status, reason = policy.evaluate(assertion)
        assert status == PromotionStatus.REJECTED
        assert "meta_pattern" in reason

    def test_meta_note(self, policy):
        assertion = {
            "text": "Note: This is just a reminder",
            "type": "DEFINITIONAL",
            "rhetorical_role": "fact"
        }
        status, reason = policy.evaluate(assertion)
        assert status == PromotionStatus.REJECTED
        assert "meta_pattern" in reason

    def test_meta_copyright(self, policy):
        assertion = {
            "text": "Copyright 2024 SAP SE",
            "type": "DEFINITIONAL",
            "rhetorical_role": "fact"
        }
        status, reason = policy.evaluate(assertion)
        assert status == PromotionStatus.REJECTED
        assert "meta_pattern" in reason


class TestRejectionByLength:
    """Tests rejet par longueur."""

    def test_too_short_rejected(self, policy):
        assertion = {
            "text": "Yes",
            "type": "DEFINITIONAL",
            "rhetorical_role": "fact"
        }
        status, reason = policy.evaluate(assertion)
        assert status == PromotionStatus.REJECTED
        assert "text_too_short" in reason

    def test_minimum_length_accepted(self, policy):
        assertion = {
            "text": "This is a valid assertion text",
            "type": "DEFINITIONAL",
            "rhetorical_role": "fact"
        }
        status, reason = policy.evaluate(assertion)
        assert status == PromotionStatus.PROMOTED_LINKED


class TestDefaultBehavior:
    """Tests comportement par défaut (INVARIANT: jamais de rejet silencieux)."""

    def test_unknown_type_not_silently_rejected(self, policy):
        """Unknown type should be PROMOTED_UNLINKED, not rejected."""
        assertion = {
            "text": "This is some text without clear categorization",
            "type": "UNKNOWN_TYPE",
            "rhetorical_role": "unknown_role"
        }
        status, reason = policy.evaluate(assertion)
        # Should be PROMOTED_UNLINKED, never silently rejected
        assert status == PromotionStatus.PROMOTED_UNLINKED
        assert "no_clear_category" in reason

    def test_no_type_no_role_not_silently_rejected(self, policy):
        """Missing type and role should be PROMOTED_UNLINKED."""
        assertion = {
            "text": "This is some ambiguous content in the document"
        }
        status, reason = policy.evaluate(assertion)
        assert status == PromotionStatus.PROMOTED_UNLINKED

    def test_claim_role_not_silently_rejected(self, policy):
        """claim role without other criteria should be PROMOTED_UNLINKED."""
        assertion = {
            "text": "We believe this approach is better",
            "type": "COMPARATIVE",
            "rhetorical_role": "claim"
        }
        status, reason = policy.evaluate(assertion)
        assert status == PromotionStatus.PROMOTED_UNLINKED


class TestSingleton:
    """Test singleton pattern."""

    def test_get_promotion_policy_singleton(self):
        p1 = get_promotion_policy()
        p2 = get_promotion_policy()
        assert p1 is p2


class TestEdgeCases:
    """Tests cas limites."""

    def test_empty_text(self, policy):
        assertion = {"text": "", "type": "DEFINITIONAL", "rhetorical_role": "fact"}
        status, reason = policy.evaluate(assertion)
        assert status == PromotionStatus.REJECTED
        assert "text_too_short" in reason

    def test_whitespace_only(self, policy):
        assertion = {"text": "   ", "type": "DEFINITIONAL", "rhetorical_role": "fact"}
        status, reason = policy.evaluate(assertion)
        assert status == PromotionStatus.REJECTED
        assert "text_too_short" in reason

    def test_none_text(self, policy):
        assertion = {"text": None, "type": "DEFINITIONAL", "rhetorical_role": "fact"}
        status, reason = policy.evaluate(assertion)
        assert status == PromotionStatus.REJECTED

    def test_missing_text_key(self, policy):
        assertion = {"type": "DEFINITIONAL", "rhetorical_role": "fact"}
        status, reason = policy.evaluate(assertion)
        assert status == PromotionStatus.REJECTED
