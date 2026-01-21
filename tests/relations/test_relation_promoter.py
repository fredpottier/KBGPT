"""
Tests pour le module relation_promoter.

Tests des seuils de promotion différenciés par SemanticGrade:
- EXPLICIT: Seuil bas (1 assertion, confiance ≥ 0.6)
- MIXED: Seuil moyen (au moins 1 EXPLICIT, confiance ≥ 0.65)
- DISCURSIVE: Seuil haut (≥2 assertions ou ≥2 docs, confiance ≥ 0.7, diversity ≥ 0.33)

Ref: doc/ongoing/ADR_DISCURSIVE_RELATIONS.md

Author: Claude Code
Date: 2026-01-21
"""

import pytest
from unittest.mock import MagicMock, patch

from knowbase.relations.types import (
    CanonicalRelation,
    PredicateProfile,
    SemanticRelation,
    SemanticGrade,
    DefensibilityTier,
    SupportStrength,
    RelationMaturity,
    RelationType,
    ExtractionMethod,
    DiscursiveBasis,
)
from knowbase.relations.relation_promoter import (
    PromotionDecision,
    PromotionThresholds,
    PromotionResult,
    RelationPromoter,
    get_relation_promoter,
    should_promote,
)


# =============================================================================
# Fixtures
# =============================================================================

@pytest.fixture
def default_thresholds():
    """Seuils par défaut."""
    return PromotionThresholds()


@pytest.fixture
def promoter(default_thresholds):
    """Promoter avec seuils par défaut."""
    return RelationPromoter(thresholds=default_thresholds)


def make_canonical(
    explicit_count: int = 0,
    discursive_count: int = 0,
    distinct_docs: int = 1,
    distinct_sections: int = 1,
    confidence: float = 0.75,
) -> CanonicalRelation:
    """Helper pour créer une CanonicalRelation de test."""
    return CanonicalRelation(
        canonical_relation_id="cr_test_001",
        tenant_id="default",
        subject_concept_id="concept_a",
        object_concept_id="concept_b",
        relation_type=RelationType.ALTERNATIVE_TO,
        predicate_norm="alternative_to",
        predicate_profile=PredicateProfile(
            normalized_predicate="alternative_to",
            occurrence_count=explicit_count + discursive_count,
            documents=[],
        ),
        explicit_support_count=explicit_count,
        discursive_support_count=discursive_count,
        total_assertions=explicit_count + discursive_count,
        distinct_documents=distinct_docs,
        distinct_sections=distinct_sections,
        confidence_p50=confidence,
        maturity=RelationMaturity.VALIDATED,
    )


# =============================================================================
# Tests PromotionThresholds
# =============================================================================

class TestPromotionThresholds:
    """Tests pour les seuils de promotion."""

    def test_default_explicit_thresholds(self, default_thresholds):
        """Seuils EXPLICIT par défaut."""
        assert default_thresholds.explicit_min_support == 1
        assert default_thresholds.explicit_min_confidence == 0.60

    def test_default_mixed_thresholds(self, default_thresholds):
        """Seuils MIXED par défaut."""
        assert default_thresholds.mixed_min_support == 1
        assert default_thresholds.mixed_min_confidence == 0.65
        assert default_thresholds.mixed_min_explicit == 1

    def test_default_discursive_thresholds(self, default_thresholds):
        """Seuils DISCURSIVE par défaut."""
        assert default_thresholds.discursive_min_support == 2
        assert default_thresholds.discursive_min_confidence == 0.70
        assert default_thresholds.discursive_min_diversity == 0.33

    def test_absolute_min_confidence(self, default_thresholds):
        """Seuil de rejet absolu."""
        assert default_thresholds.absolute_min_confidence == 0.40


# =============================================================================
# Tests SupportStrength calculation
# =============================================================================

class TestComputeSupportStrength:
    """Tests pour le calcul de SupportStrength."""

    def test_basic_support_strength(self, promoter):
        """Calcul basique de SupportStrength."""
        canonical = make_canonical(
            explicit_count=2,
            discursive_count=1,
            distinct_docs=2,
            distinct_sections=3,
        )
        support = promoter.compute_support_strength(canonical)

        assert support.support_count == 3  # 2 + 1
        assert support.explicit_count == 2
        assert support.discursive_count == 1
        assert support.doc_coverage == 2
        assert support.distinct_sections == 3

    def test_bundle_diversity_calculation(self, promoter):
        """Calcul bundle_diversity."""
        # 1 section = diversity 0.33
        canonical_1sec = make_canonical(distinct_sections=1)
        support_1 = promoter.compute_support_strength(canonical_1sec)
        assert support_1.bundle_diversity == pytest.approx(0.33, rel=0.1)

        # 2 sections = diversity 0.66
        canonical_2sec = make_canonical(distinct_sections=2)
        support_2 = promoter.compute_support_strength(canonical_2sec)
        assert support_2.bundle_diversity == pytest.approx(0.66, rel=0.1)

        # 3+ sections = diversity 1.0
        canonical_3sec = make_canonical(distinct_sections=3)
        support_3 = promoter.compute_support_strength(canonical_3sec)
        assert support_3.bundle_diversity == 1.0


# =============================================================================
# Tests EXPLICIT promotion
# =============================================================================

class TestExplicitPromotion:
    """Tests pour la promotion EXPLICIT."""

    def test_explicit_meets_thresholds(self, promoter):
        """EXPLICIT avec seuils atteints = PROMOTE."""
        canonical = make_canonical(
            explicit_count=1,
            discursive_count=0,
            confidence=0.65,
        )
        result = promoter.evaluate_promotion(canonical)

        assert result.decision == PromotionDecision.PROMOTE
        assert result.semantic_grade == SemanticGrade.EXPLICIT
        assert "EXPLICIT" in result.reason

    def test_explicit_low_confidence_defers(self, promoter):
        """EXPLICIT avec confiance trop basse = DEFER."""
        canonical = make_canonical(
            explicit_count=1,
            discursive_count=0,
            confidence=0.55,  # < 0.60
        )
        result = promoter.evaluate_promotion(canonical)

        assert result.decision == PromotionDecision.DEFER
        assert result.semantic_grade == SemanticGrade.EXPLICIT

    def test_explicit_no_support_defers(self, promoter):
        """EXPLICIT sans support = DEFER."""
        canonical = make_canonical(
            explicit_count=0,
            discursive_count=0,
            confidence=0.70,
        )
        result = promoter.evaluate_promotion(canonical)

        # Note: avec 0 explicit et 0 discursive, le grade sera calculé
        # En pratique, ce cas ne devrait pas arriver
        assert result.decision == PromotionDecision.DEFER


# =============================================================================
# Tests MIXED promotion
# =============================================================================

class TestMixedPromotion:
    """Tests pour la promotion MIXED."""

    def test_mixed_meets_thresholds(self, promoter):
        """MIXED avec seuils atteints = PROMOTE."""
        canonical = make_canonical(
            explicit_count=1,
            discursive_count=1,
            confidence=0.70,
        )
        result = promoter.evaluate_promotion(canonical)

        assert result.decision == PromotionDecision.PROMOTE
        assert result.semantic_grade == SemanticGrade.MIXED
        assert "MIXED" in result.reason

    def test_mixed_no_explicit_defers(self, promoter):
        """MIXED sans EXPLICIT = DEFER."""
        # Note: Si explicit_count=0 et discursive_count>0, c'est DISCURSIVE pas MIXED
        # MIXED requiert au moins 1 EXPLICIT et au moins 1 DISCURSIVE
        canonical = make_canonical(
            explicit_count=0,
            discursive_count=2,
            confidence=0.70,
        )
        result = promoter.evaluate_promotion(canonical)

        # Ce sera DISCURSIVE, pas MIXED
        assert result.semantic_grade == SemanticGrade.DISCURSIVE

    def test_mixed_low_confidence_defers(self, promoter):
        """MIXED avec confiance trop basse = DEFER."""
        canonical = make_canonical(
            explicit_count=1,
            discursive_count=1,
            confidence=0.60,  # < 0.65
        )
        result = promoter.evaluate_promotion(canonical)

        assert result.decision == PromotionDecision.DEFER
        assert result.semantic_grade == SemanticGrade.MIXED


# =============================================================================
# Tests DISCURSIVE promotion (seuils stricts)
# =============================================================================

class TestDiscursivePromotion:
    """Tests pour la promotion DISCURSIVE (seuils stricts)."""

    def test_discursive_meets_all_thresholds(self, promoter):
        """DISCURSIVE avec tous les seuils = PROMOTE."""
        canonical = make_canonical(
            explicit_count=0,
            discursive_count=2,  # ≥2 assertions
            distinct_docs=1,
            distinct_sections=2,  # diversity = 0.66
            confidence=0.75,  # ≥0.70
        )
        result = promoter.evaluate_promotion(canonical)

        assert result.decision == PromotionDecision.PROMOTE
        assert result.semantic_grade == SemanticGrade.DISCURSIVE
        assert "DISCURSIVE" in result.reason

    def test_discursive_multi_doc_compensates_low_support(self, promoter):
        """DISCURSIVE avec multi-doc compense faible support."""
        canonical = make_canonical(
            explicit_count=0,
            discursive_count=1,  # < 2 assertions
            distinct_docs=2,  # ≥2 docs compense
            distinct_sections=1,
            confidence=0.75,
        )
        result = promoter.evaluate_promotion(canonical)

        assert result.decision == PromotionDecision.PROMOTE
        assert result.semantic_grade == SemanticGrade.DISCURSIVE

    def test_discursive_insufficient_support_defers(self, promoter):
        """DISCURSIVE sans assez de support = DEFER."""
        canonical = make_canonical(
            explicit_count=0,
            discursive_count=1,  # < 2 assertions
            distinct_docs=1,  # < 2 docs
            confidence=0.75,
        )
        result = promoter.evaluate_promotion(canonical)

        assert result.decision == PromotionDecision.DEFER
        assert result.semantic_grade == SemanticGrade.DISCURSIVE
        assert "insufficient support" in result.reason.lower()

    def test_discursive_low_confidence_defers(self, promoter):
        """DISCURSIVE avec confiance trop basse = DEFER."""
        canonical = make_canonical(
            explicit_count=0,
            discursive_count=2,
            confidence=0.65,  # < 0.70
        )
        result = promoter.evaluate_promotion(canonical)

        assert result.decision == PromotionDecision.DEFER
        assert result.semantic_grade == SemanticGrade.DISCURSIVE

    def test_discursive_low_diversity_single_doc_defers(self, promoter):
        """DISCURSIVE avec faible diversité et 1 doc = DEFER."""
        canonical = make_canonical(
            explicit_count=0,
            discursive_count=2,
            distinct_docs=1,
            distinct_sections=0,  # diversity = 0
            confidence=0.75,
        )
        result = promoter.evaluate_promotion(canonical)

        assert result.decision == PromotionDecision.DEFER
        assert "diversity" in result.reason.lower()

    def test_discursive_low_diversity_multi_doc_promotes_with_warning(self, promoter):
        """DISCURSIVE avec faible diversité mais multi-doc = PROMOTE avec warning."""
        canonical = make_canonical(
            explicit_count=0,
            discursive_count=2,
            distinct_docs=2,  # Multi-doc compense
            distinct_sections=0,  # Faible diversité
            confidence=0.75,
        )
        result = promoter.evaluate_promotion(canonical)

        assert result.decision == PromotionDecision.PROMOTE
        assert result.semantic_grade == SemanticGrade.DISCURSIVE
        # Warning sur la faible diversité
        assert len(result.warnings) > 0 or "diversity" in result.reason.lower()


# =============================================================================
# Tests absolute rejection
# =============================================================================

class TestAbsoluteRejection:
    """Tests pour le rejet absolu (confiance < 0.40)."""

    def test_very_low_confidence_rejects(self, promoter):
        """Confiance très basse = REJECT."""
        canonical = make_canonical(
            explicit_count=5,
            discursive_count=5,
            distinct_docs=3,
            confidence=0.35,  # < 0.40
        )
        result = promoter.evaluate_promotion(canonical)

        assert result.decision == PromotionDecision.REJECT
        assert "absolute minimum" in result.reason.lower()


# =============================================================================
# Tests statistics
# =============================================================================

class TestPromotionStatistics:
    """Tests pour les statistiques de promotion."""

    def test_stats_tracking(self, promoter):
        """Vérification du suivi des statistiques."""
        # EXPLICIT - promote
        promoter.evaluate_promotion(make_canonical(explicit_count=1, confidence=0.70))
        # MIXED - promote
        promoter.evaluate_promotion(make_canonical(explicit_count=1, discursive_count=1, confidence=0.70))
        # DISCURSIVE - defer (insufficient)
        promoter.evaluate_promotion(make_canonical(discursive_count=1, confidence=0.75))
        # Very low confidence - reject
        promoter.evaluate_promotion(make_canonical(explicit_count=1, confidence=0.30))

        stats = promoter.get_stats()

        assert stats["evaluated"] == 4
        assert stats["promoted"] == 2
        assert stats["explicit_promoted"] == 1
        assert stats["mixed_promoted"] == 1
        assert stats["deferred"] == 1
        assert stats["rejected"] == 1

    def test_stats_reset(self, promoter):
        """Reset des statistiques."""
        promoter.evaluate_promotion(make_canonical(explicit_count=1, confidence=0.70))
        assert promoter.get_stats()["evaluated"] == 1

        promoter.reset_stats()

        stats = promoter.get_stats()
        assert stats["evaluated"] == 0
        assert stats["promoted"] == 0


# =============================================================================
# Tests promote_if_eligible
# =============================================================================

class TestPromoteIfEligible:
    """Tests pour promote_if_eligible."""

    @patch('knowbase.relations.relation_promoter.get_semantic_relation_writer')
    def test_eligible_calls_writer(self, mock_get_writer, promoter):
        """Si éligible, appelle le writer."""
        mock_writer = MagicMock()
        mock_writer.promote_relation.return_value = MagicMock(spec=SemanticRelation)
        mock_get_writer.return_value = mock_writer

        canonical = make_canonical(explicit_count=1, confidence=0.70)
        result = promoter.promote_if_eligible(canonical)

        assert result is not None
        mock_writer.promote_relation.assert_called_once()

    @patch('knowbase.relations.relation_promoter.get_semantic_relation_writer')
    def test_not_eligible_returns_none(self, mock_get_writer, promoter):
        """Si non éligible, retourne None."""
        canonical = make_canonical(explicit_count=0, discursive_count=1, confidence=0.50)
        result = promoter.promote_if_eligible(canonical)

        assert result is None
        mock_get_writer.assert_not_called()

    @patch('knowbase.relations.relation_promoter.get_semantic_relation_writer')
    def test_passes_discursive_bases(self, mock_get_writer, promoter):
        """Passe les bases discursives au writer."""
        mock_writer = MagicMock()
        mock_writer.promote_relation.return_value = MagicMock(spec=SemanticRelation)
        mock_get_writer.return_value = mock_writer

        canonical = make_canonical(explicit_count=1, confidence=0.70)
        bases = [DiscursiveBasis.ALTERNATIVE, DiscursiveBasis.SCOPE]

        promoter.promote_if_eligible(canonical, discursive_bases=bases)

        call_args = mock_writer.promote_relation.call_args
        assert call_args.kwargs.get('discursive_bases') is not None


# =============================================================================
# Tests helper functions
# =============================================================================

class TestHelperFunctions:
    """Tests pour les fonctions utilitaires."""

    def test_get_relation_promoter_singleton(self):
        """get_relation_promoter retourne instance singleton."""
        p1 = get_relation_promoter(tenant_id="test1")
        p2 = get_relation_promoter(tenant_id="test1")

        assert p1 is p2

    def test_get_relation_promoter_different_tenants(self):
        """Différents tenants = différentes instances."""
        p1 = get_relation_promoter(tenant_id="tenant_a")
        p2 = get_relation_promoter(tenant_id="tenant_b")

        assert p1 is not p2

    def test_should_promote_utility(self):
        """Fonction utilitaire should_promote."""
        canonical = make_canonical(explicit_count=1, confidence=0.70)
        result = should_promote(canonical)

        assert result.decision == PromotionDecision.PROMOTE
        assert result.semantic_grade == SemanticGrade.EXPLICIT


# =============================================================================
# Tests promote_batch
# =============================================================================

class TestPromoteBatch:
    """Tests pour promote_batch."""

    @patch('knowbase.relations.relation_promoter.get_semantic_relation_writer')
    def test_batch_promotion(self, mock_get_writer, promoter):
        """Promotion en batch."""
        mock_writer = MagicMock()
        mock_writer.promote_relation.return_value = MagicMock(spec=SemanticRelation)
        mock_get_writer.return_value = mock_writer

        canonicals = [
            make_canonical(explicit_count=1, confidence=0.70),  # Should promote
            make_canonical(explicit_count=0, discursive_count=1, confidence=0.50),  # Should defer
            make_canonical(explicit_count=2, confidence=0.80),  # Should promote
        ]

        results = promoter.promote_batch(canonicals)

        assert len(results) == 2  # 2 promoted
        assert mock_writer.promote_relation.call_count == 2
