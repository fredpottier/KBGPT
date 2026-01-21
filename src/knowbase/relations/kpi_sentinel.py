"""
KPI Sentinel - Dashboard de métriques pour le système de relations.

Ce module fournit des outils pour mesurer et rapporter les KPIs
de qualité du système de relations discursives.

KPIs principaux (ADR):
- FP Type 2 = 0% (faux positifs - relations acceptées à tort)
- Accept Type 1 ≥ 80% (relations valides acceptées)
- Abstain motivé = 100% (toutes les abstentions ont une raison)

Ref: doc/ongoing/ADR_DISCURSIVE_RELATIONS.md

Author: Claude Code
Date: 2026-01-21
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple
from collections import Counter

from knowbase.relations.types import (
    AssertionKind,
    DefensibilityTier,
    SemanticGrade,
    DiscursiveAbstainReason,
    RelationType,
    ExtractionMethod,
    RawAssertion,
    CanonicalRelation,
    SemanticRelation,
)
from knowbase.relations.tier_attribution import (
    is_relation_type_allowed_for_discursive,
    is_extraction_method_allowed_for_discursive,
)

logger = logging.getLogger(__name__)


# =============================================================================
# Data Classes pour les métriques
# =============================================================================

@dataclass
class TierDistribution:
    """Distribution des DefensibilityTier."""
    strict_count: int = 0
    extended_count: int = 0
    experimental_count: int = 0

    @property
    def total(self) -> int:
        return self.strict_count + self.extended_count + self.experimental_count

    @property
    def strict_ratio(self) -> float:
        return self.strict_count / self.total if self.total > 0 else 0.0

    @property
    def extended_ratio(self) -> float:
        return self.extended_count / self.total if self.total > 0 else 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "STRICT": self.strict_count,
            "EXTENDED": self.extended_count,
            "EXPERIMENTAL": self.experimental_count,
            "total": self.total,
            "strict_ratio": round(self.strict_ratio * 100, 2),
            "extended_ratio": round(self.extended_ratio * 100, 2),
        }


@dataclass
class GradeDistribution:
    """Distribution des SemanticGrade."""
    explicit_count: int = 0
    discursive_count: int = 0
    mixed_count: int = 0

    @property
    def total(self) -> int:
        return self.explicit_count + self.discursive_count + self.mixed_count

    @property
    def explicit_ratio(self) -> float:
        return self.explicit_count / self.total if self.total > 0 else 0.0

    @property
    def discursive_ratio(self) -> float:
        return self.discursive_count / self.total if self.total > 0 else 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "EXPLICIT": self.explicit_count,
            "DISCURSIVE": self.discursive_count,
            "MIXED": self.mixed_count,
            "total": self.total,
            "explicit_ratio": round(self.explicit_ratio * 100, 2),
            "discursive_ratio": round(self.discursive_ratio * 100, 2),
        }


@dataclass
class AbstentionMetrics:
    """Métriques d'abstention."""
    total_abstentions: int = 0
    with_reason: int = 0
    without_reason: int = 0
    reasons: Dict[str, int] = field(default_factory=dict)

    @property
    def motivated_ratio(self) -> float:
        """Ratio d'abstentions motivées (cible: 100%)."""
        if self.total_abstentions == 0:
            return 1.0  # Pas d'abstention = 100% motivé
        return self.with_reason / self.total_abstentions

    def to_dict(self) -> Dict[str, Any]:
        return {
            "total_abstentions": self.total_abstentions,
            "with_reason": self.with_reason,
            "without_reason": self.without_reason,
            "motivated_ratio": round(self.motivated_ratio * 100, 2),
            "kpi_status": "PASS" if self.motivated_ratio >= 1.0 else "FAIL",
            "reasons_breakdown": self.reasons,
        }


@dataclass
class Type2Metrics:
    """Métriques de faux positifs Type 2."""
    total_accepted: int = 0
    true_positives: int = 0  # Relations correctement acceptées
    false_positives: int = 0  # Relations acceptées à tort

    # Détail des violations potentielles
    whitelist_violations: int = 0
    extraction_method_violations: int = 0
    missing_evidence_violations: int = 0

    @property
    def fp_rate(self) -> float:
        """Taux de faux positifs (cible: 0%)."""
        if self.total_accepted == 0:
            return 0.0
        return self.false_positives / self.total_accepted

    @property
    def is_kpi_met(self) -> bool:
        """Le KPI FP=0% est-il respecté?"""
        return self.false_positives == 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "total_accepted": self.total_accepted,
            "true_positives": self.true_positives,
            "false_positives": self.false_positives,
            "fp_rate": round(self.fp_rate * 100, 4),
            "kpi_status": "PASS" if self.is_kpi_met else "FAIL",
            "violations": {
                "whitelist": self.whitelist_violations,
                "extraction_method": self.extraction_method_violations,
                "missing_evidence": self.missing_evidence_violations,
            },
        }


@dataclass
class Type1Metrics:
    """Métriques de faux négatifs Type 1."""
    total_candidates: int = 0
    accepted: int = 0
    rejected: int = 0

    @property
    def acceptance_rate(self) -> float:
        """Taux d'acceptation (cible: ≥80%)."""
        if self.total_candidates == 0:
            return 1.0
        return self.accepted / self.total_candidates

    @property
    def is_kpi_met(self) -> bool:
        """Le KPI Accept≥80% est-il respecté?"""
        return self.acceptance_rate >= 0.80

    def to_dict(self) -> Dict[str, Any]:
        return {
            "total_candidates": self.total_candidates,
            "accepted": self.accepted,
            "rejected": self.rejected,
            "acceptance_rate": round(self.acceptance_rate * 100, 2),
            "kpi_status": "PASS" if self.is_kpi_met else "WARNING",
        }


@dataclass
class SentinelReport:
    """Rapport complet du KPI Sentinel."""
    timestamp: datetime = field(default_factory=datetime.now)

    # Métriques principales
    type2_metrics: Type2Metrics = field(default_factory=Type2Metrics)
    type1_metrics: Type1Metrics = field(default_factory=Type1Metrics)
    abstention_metrics: AbstentionMetrics = field(default_factory=AbstentionMetrics)

    # Distributions
    tier_distribution: TierDistribution = field(default_factory=TierDistribution)
    grade_distribution: GradeDistribution = field(default_factory=GradeDistribution)

    # Compteurs détaillés
    relation_type_counts: Dict[str, int] = field(default_factory=dict)
    extraction_method_counts: Dict[str, int] = field(default_factory=dict)

    @property
    def all_kpis_met(self) -> bool:
        """Tous les KPIs sont-ils respectés?"""
        return (
            self.type2_metrics.is_kpi_met and
            self.type1_metrics.is_kpi_met and
            self.abstention_metrics.motivated_ratio >= 1.0
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "timestamp": self.timestamp.isoformat(),
            "overall_status": "PASS" if self.all_kpis_met else "FAIL",
            "kpis": {
                "type2_fp_zero": self.type2_metrics.to_dict(),
                "type1_accept_80": self.type1_metrics.to_dict(),
                "abstention_motivated": self.abstention_metrics.to_dict(),
            },
            "distributions": {
                "tier": self.tier_distribution.to_dict(),
                "grade": self.grade_distribution.to_dict(),
            },
            "details": {
                "relation_types": self.relation_type_counts,
                "extraction_methods": self.extraction_method_counts,
            },
        }

    def to_summary_string(self) -> str:
        """Génère un résumé texte du rapport."""
        status = "✅ PASS" if self.all_kpis_met else "❌ FAIL"

        lines = [
            "=" * 60,
            f"  KPI SENTINEL REPORT - {self.timestamp.strftime('%Y-%m-%d %H:%M:%S')}",
            "=" * 60,
            f"  Overall Status: {status}",
            "",
            "  KPI 1: FP Type 2 = 0%",
            f"    Status: {'PASS' if self.type2_metrics.is_kpi_met else 'FAIL'}",
            f"    FP Rate: {self.type2_metrics.fp_rate * 100:.2f}%",
            f"    FP Count: {self.type2_metrics.false_positives}/{self.type2_metrics.total_accepted}",
            "",
            "  KPI 2: Accept Type 1 >= 80%",
            f"    Status: {'PASS' if self.type1_metrics.is_kpi_met else 'WARNING'}",
            f"    Rate: {self.type1_metrics.acceptance_rate * 100:.2f}%",
            f"    Accepted: {self.type1_metrics.accepted}/{self.type1_metrics.total_candidates}",
            "",
            "  KPI 3: Abstain Motivated = 100%",
            f"    Status: {'PASS' if self.abstention_metrics.motivated_ratio >= 1.0 else 'FAIL'}",
            f"    Rate: {self.abstention_metrics.motivated_ratio * 100:.2f}%",
            f"    Abstentions: {self.abstention_metrics.total_abstentions}",
            "",
            "  Tier Distribution:",
            f"    STRICT: {self.tier_distribution.strict_count} ({self.tier_distribution.strict_ratio * 100:.1f}%)",
            f"    EXTENDED: {self.tier_distribution.extended_count} ({self.tier_distribution.extended_ratio * 100:.1f}%)",
            "",
            "  Grade Distribution:",
            f"    EXPLICIT: {self.grade_distribution.explicit_count} ({self.grade_distribution.explicit_ratio * 100:.1f}%)",
            f"    DISCURSIVE: {self.grade_distribution.discursive_count} ({self.grade_distribution.discursive_ratio * 100:.1f}%)",
            f"    MIXED: {self.grade_distribution.mixed_count}",
            "=" * 60,
        ]

        return "\n".join(lines)


# =============================================================================
# Analyseurs
# =============================================================================

class RawAssertionAnalyzer:
    """Analyse les RawAssertions pour les métriques."""

    def analyze(self, assertions: List[RawAssertion]) -> Tuple[Type1Metrics, AbstentionMetrics]:
        """
        Analyse une liste de RawAssertions.

        Returns:
            Tuple[Type1Metrics, AbstentionMetrics]
        """
        type1 = Type1Metrics(total_candidates=len(assertions))
        abstention = AbstentionMetrics()

        for assertion in assertions:
            # Compter acceptés vs rejetés
            if assertion.abstain_reason is not None:
                type1.rejected += 1
                abstention.total_abstentions += 1

                # Vérifier si motivé
                reason_name = assertion.abstain_reason.value if assertion.abstain_reason else None
                if reason_name:
                    abstention.with_reason += 1
                    abstention.reasons[reason_name] = abstention.reasons.get(reason_name, 0) + 1
                else:
                    abstention.without_reason += 1
            else:
                type1.accepted += 1

        return type1, abstention


class SemanticRelationAnalyzer:
    """Analyse les SemanticRelations pour les métriques."""

    def analyze(
        self,
        relations: List[SemanticRelation],
    ) -> Tuple[Type2Metrics, TierDistribution, GradeDistribution, Dict[str, int], Dict[str, int]]:
        """
        Analyse une liste de SemanticRelations.

        Returns:
            Tuple avec:
            - Type2Metrics
            - TierDistribution
            - GradeDistribution
            - relation_type_counts
            - extraction_method_counts
        """
        type2 = Type2Metrics(total_accepted=len(relations))
        tier_dist = TierDistribution()
        grade_dist = GradeDistribution()
        relation_types: Counter = Counter()
        extraction_methods: Counter = Counter()

        for rel in relations:
            # Distribution des tiers
            if rel.defensibility_tier == DefensibilityTier.STRICT:
                tier_dist.strict_count += 1
            elif rel.defensibility_tier == DefensibilityTier.EXTENDED:
                tier_dist.extended_count += 1
            elif rel.defensibility_tier == DefensibilityTier.EXPERIMENTAL:
                tier_dist.experimental_count += 1

            # Distribution des grades
            if rel.semantic_grade == SemanticGrade.EXPLICIT:
                grade_dist.explicit_count += 1
            elif rel.semantic_grade == SemanticGrade.DISCURSIVE:
                grade_dist.discursive_count += 1
            elif rel.semantic_grade == SemanticGrade.MIXED:
                grade_dist.mixed_count += 1

            # Compteurs relation_type et extraction_method
            if rel.relation_type:
                relation_types[rel.relation_type.value] += 1

            # Vérifier les violations potentielles (Type 2)
            violations = self._check_violations(rel)
            if violations:
                type2.false_positives += 1
                type2.whitelist_violations += violations.get("whitelist", 0)
                type2.extraction_method_violations += violations.get("extraction_method", 0)
                type2.missing_evidence_violations += violations.get("missing_evidence", 0)
            else:
                type2.true_positives += 1

        return (
            type2,
            tier_dist,
            grade_dist,
            dict(relation_types),
            dict(extraction_methods),
        )

    def _check_violations(self, rel: SemanticRelation) -> Optional[Dict[str, int]]:
        """
        Vérifie si une relation viole les contraintes (Type 2 potentiel).

        Returns:
            Dict de violations si trouvées, None sinon
        """
        violations: Dict[str, int] = {}

        # Vérifier les relations DISCURSIVE
        if rel.semantic_grade == SemanticGrade.DISCURSIVE:
            # C4: Whitelist RelationType
            if rel.relation_type and not is_relation_type_allowed_for_discursive(rel.relation_type):
                violations["whitelist"] = 1

        return violations if violations else None


# =============================================================================
# Service principal
# =============================================================================

class KPISentinel:
    """
    Service de monitoring KPI pour le système de relations.

    Usage:
        sentinel = KPISentinel()
        report = sentinel.generate_report(
            raw_assertions=assertions,
            semantic_relations=relations,
        )
        print(report.to_summary_string())
    """

    def __init__(self):
        self.raw_analyzer = RawAssertionAnalyzer()
        self.semantic_analyzer = SemanticRelationAnalyzer()

    def generate_report(
        self,
        raw_assertions: Optional[List[RawAssertion]] = None,
        semantic_relations: Optional[List[SemanticRelation]] = None,
    ) -> SentinelReport:
        """
        Génère un rapport complet des KPIs.

        Args:
            raw_assertions: Liste des RawAssertions à analyser
            semantic_relations: Liste des SemanticRelations à analyser

        Returns:
            SentinelReport avec toutes les métriques
        """
        report = SentinelReport()

        # Analyser les RawAssertions si fournies
        if raw_assertions:
            type1, abstention = self.raw_analyzer.analyze(raw_assertions)
            report.type1_metrics = type1
            report.abstention_metrics = abstention

        # Analyser les SemanticRelations si fournies
        if semantic_relations:
            (
                type2,
                tier_dist,
                grade_dist,
                rel_types,
                extr_methods,
            ) = self.semantic_analyzer.analyze(semantic_relations)

            report.type2_metrics = type2
            report.tier_distribution = tier_dist
            report.grade_distribution = grade_dist
            report.relation_type_counts = rel_types
            report.extraction_method_counts = extr_methods

        return report

    def check_kpis(
        self,
        raw_assertions: Optional[List[RawAssertion]] = None,
        semantic_relations: Optional[List[SemanticRelation]] = None,
    ) -> Tuple[bool, SentinelReport]:
        """
        Vérifie si les KPIs sont respectés.

        Returns:
            Tuple[all_kpis_met: bool, report: SentinelReport]
        """
        report = self.generate_report(raw_assertions, semantic_relations)
        return report.all_kpis_met, report


# =============================================================================
# Fonctions utilitaires
# =============================================================================

def create_sentinel_report(
    raw_assertions: Optional[List[RawAssertion]] = None,
    semantic_relations: Optional[List[SemanticRelation]] = None,
) -> SentinelReport:
    """
    Fonction helper pour créer un rapport rapidement.

    Usage:
        report = create_sentinel_report(assertions, relations)
        print(report.to_summary_string())
    """
    sentinel = KPISentinel()
    return sentinel.generate_report(raw_assertions, semantic_relations)


def validate_kpis(
    raw_assertions: Optional[List[RawAssertion]] = None,
    semantic_relations: Optional[List[SemanticRelation]] = None,
) -> bool:
    """
    Validation rapide des KPIs.

    Returns:
        True si tous les KPIs sont respectés
    """
    sentinel = KPISentinel()
    all_met, _ = sentinel.check_kpis(raw_assertions, semantic_relations)
    return all_met
