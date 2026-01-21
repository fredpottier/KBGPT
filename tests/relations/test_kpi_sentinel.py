"""
Tests pour le KPI Sentinel.

Tests du dashboard de métriques pour le système de relations.

KPIs testés:
- FP Type 2 = 0%
- Accept Type 1 >= 80%
- Abstain motivé = 100%

Ref: doc/ongoing/ADR_DISCURSIVE_RELATIONS.md

Author: Claude Code
Date: 2026-01-21
"""

import pytest
from datetime import datetime
from unittest.mock import MagicMock

from knowbase.relations.types import (
    AssertionKind,
    DefensibilityTier,
    SemanticGrade,
    DiscursiveAbstainReason,
    DiscursiveBasis,
    RelationType,
    ExtractionMethod,
)
from knowbase.relations.kpi_sentinel import (
    TierDistribution,
    GradeDistribution,
    AbstentionMetrics,
    Type2Metrics,
    Type1Metrics,
    SentinelReport,
    RawAssertionAnalyzer,
    SemanticRelationAnalyzer,
    KPISentinel,
    create_sentinel_report,
    validate_kpis,
)


# =============================================================================
# Helpers - Mock objects
# =============================================================================

def create_mock_raw_assertion(
    assertion_id: str = "raw_001",
    abstain_reason: DiscursiveAbstainReason = None,
):
    """Crée un mock de RawAssertion."""
    mock = MagicMock()
    mock.raw_assertion_id = assertion_id
    mock.abstain_reason = abstain_reason
    return mock


def create_mock_semantic_relation(
    relation_id: str = "rel_001",
    relation_type: RelationType = RelationType.ALTERNATIVE_TO,
    semantic_grade: SemanticGrade = SemanticGrade.DISCURSIVE,
    defensibility_tier: DefensibilityTier = DefensibilityTier.STRICT,
):
    """Crée un mock de SemanticRelation."""
    mock = MagicMock()
    mock.semantic_relation_id = relation_id
    mock.relation_type = relation_type
    mock.semantic_grade = semantic_grade
    mock.defensibility_tier = defensibility_tier
    return mock


# =============================================================================
# Fixtures
# =============================================================================

@pytest.fixture
def sample_raw_assertions():
    """Liste de RawAssertions de test (mocks) - 4 acceptées, 1 rejetée = 80%."""
    return [
        # Acceptées
        create_mock_raw_assertion("raw_001", abstain_reason=None),
        create_mock_raw_assertion("raw_002", abstain_reason=None),
        create_mock_raw_assertion("raw_003", abstain_reason=None),
        create_mock_raw_assertion("raw_004", abstain_reason=None),
        # Rejetée avec raison
        create_mock_raw_assertion("raw_005", abstain_reason=DiscursiveAbstainReason.WHITELIST_VIOLATION),
    ]


@pytest.fixture
def sample_semantic_relations():
    """Liste de SemanticRelations de test (mocks)."""
    return [
        create_mock_semantic_relation(
            "rel_001",
            RelationType.ALTERNATIVE_TO,
            SemanticGrade.DISCURSIVE,
            DefensibilityTier.STRICT,
        ),
        create_mock_semantic_relation(
            "rel_002",
            RelationType.REQUIRES,
            SemanticGrade.EXPLICIT,
            DefensibilityTier.STRICT,
        ),
        create_mock_semantic_relation(
            "rel_003",
            RelationType.USES,
            SemanticGrade.MIXED,
            DefensibilityTier.STRICT,
        ),
    ]


# =============================================================================
# Tests TierDistribution
# =============================================================================

class TestTierDistribution:
    """Tests pour TierDistribution."""

    def test_default_values(self):
        """Test valeurs par défaut."""
        dist = TierDistribution()

        assert dist.strict_count == 0
        assert dist.extended_count == 0
        assert dist.experimental_count == 0
        assert dist.total == 0

    def test_total_calculation(self):
        """Test calcul du total."""
        dist = TierDistribution(strict_count=10, extended_count=5, experimental_count=2)

        assert dist.total == 17

    def test_strict_ratio(self):
        """Test ratio STRICT."""
        dist = TierDistribution(strict_count=8, extended_count=2)

        assert dist.strict_ratio == 0.8

    def test_to_dict(self):
        """Test conversion en dict."""
        dist = TierDistribution(strict_count=7, extended_count=3)
        result = dist.to_dict()

        assert result["STRICT"] == 7
        assert result["EXTENDED"] == 3
        assert result["total"] == 10
        assert result["strict_ratio"] == 70.0


# =============================================================================
# Tests GradeDistribution
# =============================================================================

class TestGradeDistribution:
    """Tests pour GradeDistribution."""

    def test_default_values(self):
        """Test valeurs par défaut."""
        dist = GradeDistribution()

        assert dist.explicit_count == 0
        assert dist.discursive_count == 0
        assert dist.mixed_count == 0

    def test_ratios(self):
        """Test calcul des ratios."""
        dist = GradeDistribution(explicit_count=60, discursive_count=30, mixed_count=10)

        assert dist.explicit_ratio == 0.6
        assert dist.discursive_ratio == 0.3


# =============================================================================
# Tests AbstentionMetrics
# =============================================================================

class TestAbstentionMetrics:
    """Tests pour AbstentionMetrics."""

    def test_motivated_ratio_all_with_reason(self):
        """Test ratio 100% si toutes motivées."""
        metrics = AbstentionMetrics(
            total_abstentions=5,
            with_reason=5,
            without_reason=0,
        )

        assert metrics.motivated_ratio == 1.0

    def test_motivated_ratio_none(self):
        """Test ratio si pas d'abstention."""
        metrics = AbstentionMetrics()

        assert metrics.motivated_ratio == 1.0  # 100% par défaut

    def test_motivated_ratio_partial(self):
        """Test ratio partiel."""
        metrics = AbstentionMetrics(
            total_abstentions=10,
            with_reason=8,
            without_reason=2,
        )

        assert metrics.motivated_ratio == 0.8

    def test_to_dict_kpi_status(self):
        """Test KPI status dans dict."""
        # KPI PASS
        metrics_pass = AbstentionMetrics(total_abstentions=5, with_reason=5)
        assert metrics_pass.to_dict()["kpi_status"] == "PASS"

        # KPI FAIL
        metrics_fail = AbstentionMetrics(total_abstentions=5, with_reason=4, without_reason=1)
        assert metrics_fail.to_dict()["kpi_status"] == "FAIL"


# =============================================================================
# Tests Type2Metrics
# =============================================================================

class TestType2Metrics:
    """Tests pour Type2Metrics."""

    def test_fp_rate_zero(self):
        """Test FP rate = 0%."""
        metrics = Type2Metrics(
            total_accepted=100,
            true_positives=100,
            false_positives=0,
        )

        assert metrics.fp_rate == 0.0
        assert metrics.is_kpi_met is True

    def test_fp_rate_with_violations(self):
        """Test FP rate avec violations."""
        metrics = Type2Metrics(
            total_accepted=100,
            true_positives=98,
            false_positives=2,
        )

        assert metrics.fp_rate == 0.02
        assert metrics.is_kpi_met is False

    def test_to_dict_violations(self):
        """Test violations dans dict."""
        metrics = Type2Metrics(
            whitelist_violations=2,
            extraction_method_violations=1,
        )
        result = metrics.to_dict()

        assert result["violations"]["whitelist"] == 2
        assert result["violations"]["extraction_method"] == 1


# =============================================================================
# Tests Type1Metrics
# =============================================================================

class TestType1Metrics:
    """Tests pour Type1Metrics."""

    def test_acceptance_rate_above_threshold(self):
        """Test acceptance >= 80%."""
        metrics = Type1Metrics(
            total_candidates=100,
            accepted=85,
            rejected=15,
        )

        assert metrics.acceptance_rate == 0.85
        assert metrics.is_kpi_met is True

    def test_acceptance_rate_below_threshold(self):
        """Test acceptance < 80%."""
        metrics = Type1Metrics(
            total_candidates=100,
            accepted=70,
            rejected=30,
        )

        assert metrics.acceptance_rate == 0.70
        assert metrics.is_kpi_met is False


# =============================================================================
# Tests SentinelReport
# =============================================================================

class TestSentinelReport:
    """Tests pour SentinelReport."""

    def test_all_kpis_met(self):
        """Test all_kpis_met quand tout est OK."""
        report = SentinelReport(
            type2_metrics=Type2Metrics(total_accepted=10, true_positives=10, false_positives=0),
            type1_metrics=Type1Metrics(total_candidates=10, accepted=9, rejected=1),
            abstention_metrics=AbstentionMetrics(total_abstentions=1, with_reason=1),
        )

        assert report.all_kpis_met is True

    def test_all_kpis_not_met(self):
        """Test all_kpis_met quand un KPI échoue."""
        report = SentinelReport(
            type2_metrics=Type2Metrics(total_accepted=10, true_positives=9, false_positives=1),
        )

        assert report.all_kpis_met is False

    def test_to_summary_string(self):
        """Test génération du résumé texte."""
        report = SentinelReport()
        summary = report.to_summary_string()

        assert "KPI SENTINEL REPORT" in summary
        assert "FP Type 2" in summary
        assert "Accept Type 1" in summary
        assert "Abstain Motivated" in summary


# =============================================================================
# Tests RawAssertionAnalyzer
# =============================================================================

class TestRawAssertionAnalyzer:
    """Tests pour RawAssertionAnalyzer."""

    def test_analyze_counts_correctly(self, sample_raw_assertions):
        """Test analyse des compteurs."""
        analyzer = RawAssertionAnalyzer()
        type1, abstention = analyzer.analyze(sample_raw_assertions)

        # 5 assertions: 4 acceptées, 1 rejetée = 80%
        assert type1.total_candidates == 5
        assert type1.accepted == 4
        assert type1.rejected == 1

    def test_analyze_abstention_reasons(self, sample_raw_assertions):
        """Test analyse des raisons d'abstention."""
        analyzer = RawAssertionAnalyzer()
        type1, abstention = analyzer.analyze(sample_raw_assertions)

        assert abstention.total_abstentions == 1
        assert abstention.with_reason == 1
        assert "WHITELIST_VIOLATION" in abstention.reasons


# =============================================================================
# Tests SemanticRelationAnalyzer
# =============================================================================

class TestSemanticRelationAnalyzer:
    """Tests pour SemanticRelationAnalyzer."""

    def test_analyze_tier_distribution(self, sample_semantic_relations):
        """Test distribution des tiers."""
        analyzer = SemanticRelationAnalyzer()
        type2, tier_dist, grade_dist, rel_types, extr_methods = analyzer.analyze(
            sample_semantic_relations
        )

        # Toutes STRICT
        assert tier_dist.strict_count == 3
        assert tier_dist.extended_count == 0

    def test_analyze_grade_distribution(self, sample_semantic_relations):
        """Test distribution des grades."""
        analyzer = SemanticRelationAnalyzer()
        type2, tier_dist, grade_dist, rel_types, extr_methods = analyzer.analyze(
            sample_semantic_relations
        )

        # 1 EXPLICIT, 1 DISCURSIVE, 1 MIXED
        assert grade_dist.explicit_count == 1
        assert grade_dist.discursive_count == 1
        assert grade_dist.mixed_count == 1

    def test_analyze_relation_types(self, sample_semantic_relations):
        """Test comptage des relation_types."""
        analyzer = SemanticRelationAnalyzer()
        type2, tier_dist, grade_dist, rel_types, extr_methods = analyzer.analyze(
            sample_semantic_relations
        )

        assert "ALTERNATIVE_TO" in rel_types
        assert "REQUIRES" in rel_types
        assert "USES" in rel_types

    def test_detect_violation_forbidden_relation_type(self):
        """Test détection violation whitelist."""
        analyzer = SemanticRelationAnalyzer()

        # Relation DISCURSIVE avec type interdit (utilise mock)
        bad_relation = create_mock_semantic_relation(
            relation_id="rel_bad",
            relation_type=RelationType.CAUSES,  # Interdit pour DISCURSIVE
            semantic_grade=SemanticGrade.DISCURSIVE,
            defensibility_tier=DefensibilityTier.EXTENDED,
        )

        type2, _, _, _, _ = analyzer.analyze([bad_relation])

        assert type2.false_positives == 1
        assert type2.whitelist_violations == 1


# =============================================================================
# Tests KPISentinel
# =============================================================================

class TestKPISentinel:
    """Tests pour KPISentinel."""

    def test_generate_report(self, sample_raw_assertions, sample_semantic_relations):
        """Test génération du rapport complet."""
        sentinel = KPISentinel()
        report = sentinel.generate_report(
            raw_assertions=sample_raw_assertions,
            semantic_relations=sample_semantic_relations,
        )

        assert report.type1_metrics.total_candidates == 5  # 4 acceptées + 1 rejetée
        assert report.type2_metrics.total_accepted == 3
        assert report.tier_distribution.total == 3

    def test_check_kpis(self, sample_raw_assertions, sample_semantic_relations):
        """Test vérification des KPIs."""
        sentinel = KPISentinel()
        all_met, report = sentinel.check_kpis(
            raw_assertions=sample_raw_assertions,
            semantic_relations=sample_semantic_relations,
        )

        # Doit passer (pas de FP, acceptance > 80%, abstentions motivées)
        assert all_met is True


# =============================================================================
# Tests Helper Functions
# =============================================================================

class TestHelperFunctions:
    """Tests pour les fonctions helper."""

    def test_create_sentinel_report(self, sample_raw_assertions, sample_semantic_relations):
        """Test create_sentinel_report."""
        report = create_sentinel_report(
            raw_assertions=sample_raw_assertions,
            semantic_relations=sample_semantic_relations,
        )

        assert isinstance(report, SentinelReport)
        assert report.timestamp is not None

    def test_validate_kpis(self, sample_raw_assertions, sample_semantic_relations):
        """Test validate_kpis."""
        result = validate_kpis(
            raw_assertions=sample_raw_assertions,
            semantic_relations=sample_semantic_relations,
        )

        assert isinstance(result, bool)


# =============================================================================
# Tests Edge Cases
# =============================================================================

class TestEdgeCases:
    """Tests pour les cas limites."""

    def test_empty_assertions(self):
        """Test avec listes vides."""
        sentinel = KPISentinel()
        report = sentinel.generate_report(
            raw_assertions=[],
            semantic_relations=[],
        )

        # Pas de données = KPIs respectés par défaut
        assert report.all_kpis_met is True

    def test_only_raw_assertions(self, sample_raw_assertions):
        """Test avec seulement RawAssertions."""
        sentinel = KPISentinel()
        report = sentinel.generate_report(raw_assertions=sample_raw_assertions)

        assert report.type1_metrics.total_candidates == 5  # 4 acceptées + 1 rejetée
        assert report.type2_metrics.total_accepted == 0  # Pas de relations

    def test_only_semantic_relations(self, sample_semantic_relations):
        """Test avec seulement SemanticRelations."""
        sentinel = KPISentinel()
        report = sentinel.generate_report(semantic_relations=sample_semantic_relations)

        assert report.type2_metrics.total_accepted == 3
        assert report.type1_metrics.total_candidates == 0  # Pas d'assertions

    def test_report_to_dict(self, sample_raw_assertions, sample_semantic_relations):
        """Test conversion complète en dict."""
        report = create_sentinel_report(
            raw_assertions=sample_raw_assertions,
            semantic_relations=sample_semantic_relations,
        )

        result = report.to_dict()

        assert "timestamp" in result
        assert "overall_status" in result
        assert "kpis" in result
        assert "distributions" in result
        assert "details" in result
