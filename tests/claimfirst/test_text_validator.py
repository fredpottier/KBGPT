# tests/claimfirst/test_text_validator.py
"""
Tests pour TextValidator.

INV-23: Toute réponse cite explicitement ses claims sources
"""

import pytest

from knowbase.claimfirst.query.text_validator import (
    TextValidator,
    TextValidationResult,
    ValidationStatus,
)


@pytest.fixture
def validator():
    """Crée un validateur sans Neo4j."""
    return TextValidator(neo4j_driver=None, tenant_id="default")


class TestTextValidator:
    """Tests pour TextValidator."""

    def test_validate_no_driver_returns_uncertain(self, validator):
        """Sans Neo4j, retourne UNCERTAIN."""
        result = validator.validate(
            user_statement="GL Accounting supports multi-currency.",
        )

        assert result.status == ValidationStatus.UNCERTAIN
        assert "not available" in result.explanation.lower()

    def test_stats_tracking(self, validator):
        """Vérifie le tracking des statistiques."""
        validator.reset_stats()

        validator.validate("Statement 1")
        validator.validate("Statement 2")

        stats = validator.get_stats()
        assert stats["validations"] == 2

    def test_reset_stats(self, validator):
        """Reset des statistiques."""
        validator.validate("Statement")
        validator.reset_stats()

        stats = validator.get_stats()
        assert stats["validations"] == 0


class TestTextValidationResult:
    """Tests pour TextValidationResult model."""

    def test_result_confirmed(self):
        """Résultat CONFIRMED."""
        result = TextValidationResult(
            user_text="GL Accounting supports multi-currency.",
            status=ValidationStatus.CONFIRMED,
            supporting_claims=[
                {"claim_id": "c1", "text": "GL supports multi-currency", "similarity": 0.95},
                {"claim_id": "c2", "text": "Multi-currency is enabled", "similarity": 0.88},
            ],  # INV-23
            confidence=0.95,
            explanation="The statement is supported by 2 claims.",
        )

        assert result.status == ValidationStatus.CONFIRMED
        assert len(result.supporting_claims) == 2  # INV-23
        assert result.confidence == 0.95

    def test_result_incorrect(self):
        """Résultat INCORRECT avec contradicting claims."""
        result = TextValidationResult(
            user_text="Feature X is always available.",
            status=ValidationStatus.INCORRECT,
            supporting_claims=[],
            contradicting_claims=[
                {"claim_id": "c1", "text": "Feature X is not available in Standard Edition", "similarity": 0.85},
            ],  # INV-23
            confidence=0.85,
            explanation="The statement contradicts corpus claims.",
        )

        assert result.status == ValidationStatus.INCORRECT
        assert len(result.contradicting_claims) == 1  # INV-23

    def test_result_uncertain(self):
        """Résultat UNCERTAIN."""
        result = TextValidationResult(
            user_text="Feature Y may be configured.",
            status=ValidationStatus.UNCERTAIN,
            supporting_claims=[
                {"claim_id": "c1", "text": "Y configuration options", "similarity": 0.70},
            ],
            confidence=0.50,
            explanation="Found related claims but not enough evidence.",
        )

        assert result.status == ValidationStatus.UNCERTAIN
        assert result.confidence < 0.75

    def test_result_not_documented(self):
        """Résultat NOT_DOCUMENTED."""
        result = TextValidationResult(
            user_text="Unknown feature Z does something.",
            status=ValidationStatus.NOT_DOCUMENTED,
            supporting_claims=[],
            contradicting_claims=[],
            confidence=0.0,
            explanation="No relevant claims found in the corpus.",
        )

        assert result.status == ValidationStatus.NOT_DOCUMENTED
        assert result.confidence == 0.0

    def test_context_used_tracked(self):
        """Le contexte utilisé est tracké."""
        result = TextValidationResult(
            user_text="Statement",
            status=ValidationStatus.CONFIRMED,
            confidence=0.9,
            explanation="Confirmed",
            context_used="2023",
        )

        assert result.context_used == "2023"


class TestValidationStatus:
    """Tests pour ValidationStatus enum."""

    def test_enum_values(self):
        """Vérifie les valeurs de l'enum."""
        assert ValidationStatus.CONFIRMED.value == "confirmed"
        assert ValidationStatus.INCORRECT.value == "incorrect"
        assert ValidationStatus.UNCERTAIN.value == "uncertain"
        assert ValidationStatus.NOT_DOCUMENTED.value == "not_documented"
