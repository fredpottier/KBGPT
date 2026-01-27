"""
Tests unitaires pour ConceptRefinerV2 (Pass 1.2b)
=================================================
Ref: doc/ongoing/PLAN_CAPTATION_V2.md

Teste:
- SaturationMetrics et ses propriétés (C4)
- _is_quality_assertion (C2, C2b)
- _validate_concept_quality (C2)
- refine_concepts
- should_continue_iteration
"""

import pytest
from unittest.mock import MagicMock, patch

from knowbase.stratified.pass1.concept_refiner import (
    ConceptRefinerV2,
    SaturationMetrics,
)


# ============================================================================
# FIXTURES
# ============================================================================

@pytest.fixture
def refiner():
    """ConceptRefinerV2 sans LLM (pour tests unitaires)."""
    return ConceptRefinerV2(llm_client=None)


@pytest.fixture
def sample_assertion_log():
    """Exemple de assertion_log pour tests."""
    return [
        # PROMOTED assertions
        {"assertion_id": "a1", "text": "TLS 1.2 is required", "type": "PRESCRIPTIVE", "status": "PROMOTED", "reason": "promoted", "concept_id": "c1"},
        {"assertion_id": "a2", "text": "Data is encrypted at rest", "type": "FACTUAL", "status": "PROMOTED", "reason": "promoted", "concept_id": "c2"},
        # ABSTAINED - no_concept_match (cibles du raffinement)
        {"assertion_id": "a3", "text": "Backup retention is 30 days", "type": "PRESCRIPTIVE", "status": "ABSTAINED", "reason": "no_concept_match", "concept_id": None},
        {"assertion_id": "a4", "text": "High Availability is enabled", "type": "FACTUAL", "status": "ABSTAINED", "reason": "no_concept_match", "concept_id": None},
        {"assertion_id": "a5", "text": "DR site must be in different region", "type": "PRESCRIPTIVE", "status": "ABSTAINED", "reason": "no_concept_match", "concept_id": None},
        # REJECTED
        {"assertion_id": "a6", "text": "Some generic text", "type": "PROCEDURAL", "status": "REJECTED", "reason": "policy_rejected", "concept_id": None},
    ]


# ============================================================================
# TEST: SaturationMetrics
# ============================================================================

class TestSaturationMetrics:
    """Tests pour SaturationMetrics."""

    def test_basic_properties(self):
        """Test des propriétés de base."""
        metrics = SaturationMetrics(
            total_assertions=100,
            promoted=50,
            abstained=40,
            rejected=10,
            no_concept_match=30,
        )

        assert metrics.promotion_rate == 0.5
        assert metrics.no_concept_match_rate == 0.30
        assert metrics.coverage_rate == 50 / 80  # promoted / (promoted + no_concept_match)

    def test_should_iterate_true(self):
        """C4: should_iterate True quand rate > 10% ET count > 20."""
        metrics = SaturationMetrics(
            total_assertions=200,
            promoted=100,
            abstained=80,
            rejected=20,
            no_concept_match=50,  # 25% > 10% ET 50 > 20
        )

        assert metrics.should_iterate is True

    def test_should_iterate_false_low_rate(self):
        """C4: should_iterate False quand rate <= 10%."""
        metrics = SaturationMetrics(
            total_assertions=200,
            promoted=180,
            abstained=15,
            rejected=5,
            no_concept_match=15,  # 7.5% < 10%
        )

        assert metrics.should_iterate is False

    def test_should_iterate_false_low_count(self):
        """C4: should_iterate False quand count <= 20."""
        metrics = SaturationMetrics(
            total_assertions=100,
            promoted=60,
            abstained=30,
            rejected=10,
            no_concept_match=18,  # 18 <= 20
        )

        assert metrics.should_iterate is False

    def test_quality_unlinked_count(self):
        """Test du compteur de qualité."""
        metrics = SaturationMetrics(
            total_assertions=100,
            promoted=50,
            abstained=40,
            rejected=10,
            no_concept_match=30,
            prescriptive_unlinked=15,
            value_bearing_unlinked=8,
        )

        assert metrics.quality_unlinked_count == 23


# ============================================================================
# TEST: _is_quality_assertion (C2, C2b)
# ============================================================================

class TestIsQualityAssertion:
    """Tests pour _is_quality_assertion."""

    def test_prescriptive_is_quality(self, refiner):
        """C2: Type PRESCRIPTIVE est de qualité."""
        assertion = {"type": "PRESCRIPTIVE", "text": "Some text"}
        assert refiner._is_quality_assertion(assertion) is True

    def test_value_bearing_is_quality(self, refiner):
        """C2: Assertion avec valeur est de qualité."""
        assertions = [
            {"type": "FACTUAL", "text": "Version 1.2.3 is required"},  # Version
            {"type": "FACTUAL", "text": "Uptime must be 99.9%"},  # Pourcentage
            {"type": "FACTUAL", "text": "Backup retention is 30 days"},  # Durée
            {"type": "FACTUAL", "text": "Temperature should be 2-8°C"},  # Température
            {"type": "FACTUAL", "text": "Budget is 500K€"},  # Montant
        ]

        for a in assertions:
            assert refiner._is_quality_assertion(a) is True, f"Failed for: {a['text']}"

    def test_obligation_without_modal_is_quality(self, refiner):
        """C2b: Obligations sans modal (juridique)."""
        assertions = [
            {"type": "FACTUAL", "text": "Customer is required to provide access"},
            {"type": "FACTUAL", "text": "Access is prohibited without authorization"},
            {"type": "FACTUAL", "text": "Reporting is mandatory"},
            {"type": "FACTUAL", "text": "Report must be submitted no later than Friday"},
            {"type": "FACTUAL", "text": "Payment is due within 30 days"},
            {"type": "FACTUAL", "text": "This is subject to approval"},
            {"type": "FACTUAL", "text": "Data shall not be shared"},
            {"type": "FACTUAL", "text": "Data may not be used externally"},
            {"type": "FACTUAL", "text": "User cannot access admin panel"},
        ]

        for a in assertions:
            assert refiner._is_quality_assertion(a) is True, f"Failed for: {a['text']}"

    def test_generic_factual_not_quality(self, refiner):
        """C2: Assertion FACTUAL générique n'est pas de qualité."""
        assertion = {"type": "FACTUAL", "text": "The system provides various features"}
        assert refiner._is_quality_assertion(assertion) is False


# ============================================================================
# TEST: calculate_saturation
# ============================================================================

class TestCalculateSaturation:
    """Tests pour calculate_saturation."""

    def test_basic_calculation(self, refiner, sample_assertion_log):
        """Test du calcul de base des métriques."""
        metrics = refiner.calculate_saturation(sample_assertion_log)

        assert metrics.total_assertions == 6
        assert metrics.promoted == 2
        assert metrics.abstained == 3
        assert metrics.rejected == 1
        assert metrics.no_concept_match == 3

    def test_quality_counting(self, refiner, sample_assertion_log):
        """Test du comptage des assertions de qualité."""
        metrics = refiner.calculate_saturation(sample_assertion_log)

        # a3 et a5 sont PRESCRIPTIVE (qualité)
        # a4 est FACTUAL sans valeur (pas qualité)
        assert metrics.prescriptive_unlinked >= 2


# ============================================================================
# TEST: should_continue_iteration
# ============================================================================

class TestShouldContinueIteration:
    """Tests pour should_continue_iteration."""

    def test_max_iterations_reached(self, refiner):
        """Arrêt quand max iterations atteint."""
        before = SaturationMetrics(100, 50, 40, 10, 30)
        after = SaturationMetrics(100, 60, 30, 10, 20)

        assert refiner.should_continue_iteration(before, after, 3, 30) is False

    def test_surface_max_reached(self, refiner):
        """Arrêt quand surface max atteinte."""
        before = SaturationMetrics(100, 50, 40, 10, 30)
        after = SaturationMetrics(100, 60, 30, 10, 20)

        assert refiner.should_continue_iteration(before, after, 1, 55) is False

    def test_threshold_reached(self, refiner):
        """Arrêt quand seuil minimum atteint."""
        before = SaturationMetrics(100, 50, 40, 10, 30)
        after = SaturationMetrics(100, 85, 10, 5, 10)  # no_concept_match < 20

        assert refiner.should_continue_iteration(before, after, 1, 30) is False

    def test_diminishing_returns(self, refiner):
        """Arrêt quand rendement décroissant."""
        before = SaturationMetrics(100, 50, 40, 10, 30)
        # Réduction de seulement 2 (30 → 28), soit 6.7% < 15%
        after = SaturationMetrics(100, 52, 38, 10, 28)

        assert refiner.should_continue_iteration(before, after, 1, 30) is False

    def test_continue_if_significant_gain(self, refiner):
        """Continue si gain significatif."""
        before = SaturationMetrics(200, 100, 80, 20, 60)
        # Réduction de 20 (60 → 40), soit 33% > 15%
        after = SaturationMetrics(200, 120, 60, 20, 40)

        assert refiner.should_continue_iteration(before, after, 1, 30) is True


# ============================================================================
# TEST: _validate_concept_quality (C2)
# ============================================================================

class TestValidateConceptQuality:
    """Tests pour _validate_concept_quality."""

    def test_concept_with_matching_quality_assertions(self, refiner):
        """C2: Concept valide avec assertions de qualité."""
        concept = {
            "name": "backup retention",
            "lexical_triggers": ["backup", "retention", "30 days"]
        }
        assertions = [
            {"type": "PRESCRIPTIVE", "text": "Backup retention must be at least 30 days"},
            {"type": "FACTUAL", "text": "Backup data is stored in a separate location"},
            {"type": "PRESCRIPTIVE", "text": "Backup retention policy applies to all data"},
        ]

        assert refiner._validate_concept_quality(concept, assertions) is True

    def test_concept_without_quality_assertions(self, refiner):
        """C2: Concept invalide sans assertions de qualité."""
        concept = {
            "name": "generic feature",
            "lexical_triggers": ["feature", "generic"]
        }
        assertions = [
            {"type": "FACTUAL", "text": "The feature is available"},
            {"type": "FACTUAL", "text": "A generic implementation exists"},
        ]

        assert refiner._validate_concept_quality(concept, assertions) is False

    def test_concept_with_less_than_2_matches(self, refiner):
        """C2: Concept invalide avec moins de 2 matches."""
        concept = {
            "name": "rare concept",
            "lexical_triggers": ["rare", "unique"]
        }
        assertions = [
            {"type": "PRESCRIPTIVE", "text": "This rare item must be handled carefully"},
        ]

        assert refiner._validate_concept_quality(concept, assertions) is False

    def test_concept_without_triggers(self, refiner):
        """C2: Concept invalide sans triggers."""
        concept = {
            "name": "empty triggers",
            "lexical_triggers": []
        }
        assertions = [
            {"type": "PRESCRIPTIVE", "text": "Some text"},
        ]

        assert refiner._validate_concept_quality(concept, assertions) is False


# ============================================================================
# TEST: _has_value
# ============================================================================

class TestHasValue:
    """Tests pour _has_value."""

    def test_version_detected(self, refiner):
        """Détection des versions."""
        assert refiner._has_value("Version 1.2.3 is required") is True
        assert refiner._has_value("Use TLS 1.2") is True

    def test_percentage_detected(self, refiner):
        """Détection des pourcentages."""
        assert refiner._has_value("Uptime must be 99.9%") is True
        assert refiner._has_value("CPU usage below 80%") is True

    def test_duration_detected(self, refiner):
        """Détection des durées."""
        assert refiner._has_value("Retention period is 30 days") is True
        assert refiner._has_value("Timeout after 5 minutes") is True
        assert refiner._has_value("Valid for 2 years") is True

    def test_no_value(self, refiner):
        """Pas de valeur détectée."""
        assert refiner._has_value("The system provides features") is False
        assert refiner._has_value("Security is important") is False
