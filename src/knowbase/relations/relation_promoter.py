"""
Phase C - Relation Promoter avec seuils différenciés.

Ce module implémente les seuils de promotion pour décider si une CanonicalRelation
doit être promue en SemanticRelation.

Seuils par SemanticGrade:
- EXPLICIT: Seuil bas (1 assertion suffit, confiance ≥ 0.6)
- MIXED: Seuil moyen (au moins 1 EXPLICIT, confiance ≥ 0.65)
- DISCURSIVE: Seuil haut (≥2 assertions ou ≥2 docs, confiance ≥ 0.7, bundle_diversity ≥ 0.33)

Ref: doc/ongoing/ADR_DISCURSIVE_RELATIONS.md

Author: Claude Code
Date: 2026-01-21
"""

import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import List, Optional, Dict, Any

from .types import (
    CanonicalRelation,
    SemanticRelation,
    SemanticGrade,
    DefensibilityTier,
    SupportStrength,
    RelationMaturity,
    ExtractionMethod,
    DiscursiveBasis,
    compute_semantic_grade,
    compute_bundle_diversity,
)
from .tier_attribution import compute_defensibility_tier
from .semantic_relation_writer import SemanticRelationWriter, get_semantic_relation_writer

logger = logging.getLogger(__name__)


class PromotionDecision(str, Enum):
    """Décision de promotion."""
    PROMOTE = "PROMOTE"           # Promouvoir en SemanticRelation
    DEFER = "DEFER"               # Ne pas promouvoir, attendre plus de preuves
    REJECT = "REJECT"             # Ne pas promouvoir, qualité insuffisante


@dataclass
class PromotionThresholds:
    """
    Seuils de promotion par SemanticGrade.

    Ces seuils sont calibrés pour maximiser la précision (éviter Type 2)
    tout en permettant un rappel raisonnable.
    """
    # EXPLICIT: Confiance élevée, un seul support suffit
    explicit_min_support: int = 1
    explicit_min_confidence: float = 0.60
    explicit_min_docs: int = 1

    # MIXED: Au moins une preuve EXPLICIT, seuil légèrement plus haut
    mixed_min_support: int = 1
    mixed_min_confidence: float = 0.65
    mixed_min_explicit: int = 1  # Au moins 1 EXPLICIT requis

    # DISCURSIVE: Seuils plus stricts (risque Type 2)
    discursive_min_support: int = 2  # ≥2 assertions OU ≥2 docs
    discursive_min_confidence: float = 0.70
    discursive_min_docs: int = 1
    discursive_min_diversity: float = 0.33  # Au moins 1 section distincte

    # Seuil de rejet absolu
    absolute_min_confidence: float = 0.40


@dataclass
class PromotionResult:
    """Résultat d'une évaluation de promotion."""
    decision: PromotionDecision
    reason: str
    semantic_grade: Optional[SemanticGrade] = None
    support_strength: Optional[SupportStrength] = None
    warnings: List[str] = field(default_factory=list)

    def __repr__(self) -> str:
        return f"PromotionResult({self.decision.value}: {self.reason})"


class RelationPromoter:
    """
    Évalue et promeut les CanonicalRelations en SemanticRelations.

    Responsabilités:
    1. Calculer le semantic_grade et support_strength
    2. Évaluer si les seuils de promotion sont atteints
    3. Déléguer l'écriture à SemanticRelationWriter si promotion décidée
    """

    def __init__(
        self,
        thresholds: Optional[PromotionThresholds] = None,
        writer: Optional[SemanticRelationWriter] = None,
        tenant_id: str = "default",
    ):
        """
        Initialize promoter.

        Args:
            thresholds: Seuils de promotion (utilise défauts si None)
            writer: SemanticRelationWriter (crée un nouveau si None)
            tenant_id: Tenant ID
        """
        self.thresholds = thresholds or PromotionThresholds()
        self.writer = writer
        self.tenant_id = tenant_id

        self._stats = {
            "evaluated": 0,
            "promoted": 0,
            "deferred": 0,
            "rejected": 0,
            "explicit_promoted": 0,
            "mixed_promoted": 0,
            "discursive_promoted": 0,
        }

    def _get_writer(self) -> SemanticRelationWriter:
        """Get or create writer instance."""
        if self.writer is None:
            self.writer = get_semantic_relation_writer(tenant_id=self.tenant_id)
        return self.writer

    def compute_support_strength(
        self,
        canonical: CanonicalRelation,
    ) -> SupportStrength:
        """
        Calcule le SupportStrength à partir d'une CanonicalRelation.

        Args:
            canonical: CanonicalRelation à évaluer

        Returns:
            SupportStrength calculé
        """
        return SupportStrength(
            support_count=canonical.total_assertions,
            explicit_count=canonical.explicit_support_count,
            discursive_count=canonical.discursive_support_count,
            doc_coverage=canonical.distinct_documents,
            distinct_sections=canonical.distinct_sections,
            bundle_diversity=compute_bundle_diversity(canonical.distinct_sections),
        )

    def evaluate_promotion(
        self,
        canonical: CanonicalRelation,
    ) -> PromotionResult:
        """
        Évalue si une CanonicalRelation doit être promue.

        Args:
            canonical: CanonicalRelation à évaluer

        Returns:
            PromotionResult avec décision et justification
        """
        self._stats["evaluated"] += 1
        warnings: List[str] = []

        # Calculer semantic_grade
        semantic_grade = compute_semantic_grade(
            canonical.explicit_support_count,
            canonical.discursive_support_count
        )

        # Calculer support_strength
        support = self.compute_support_strength(canonical)

        # Vérification du seuil absolu
        confidence = canonical.confidence_p50
        if confidence < self.thresholds.absolute_min_confidence:
            self._stats["rejected"] += 1
            return PromotionResult(
                decision=PromotionDecision.REJECT,
                reason=f"Confidence {confidence:.2f} < absolute minimum {self.thresholds.absolute_min_confidence}",
                semantic_grade=semantic_grade,
                support_strength=support,
            )

        # Évaluer selon le semantic_grade
        if semantic_grade == SemanticGrade.EXPLICIT:
            result = self._evaluate_explicit(canonical, support, confidence)
        elif semantic_grade == SemanticGrade.MIXED:
            result = self._evaluate_mixed(canonical, support, confidence)
        else:  # DISCURSIVE
            result = self._evaluate_discursive(canonical, support, confidence)

        # Mettre à jour les stats
        result.semantic_grade = semantic_grade
        result.support_strength = support

        if result.decision == PromotionDecision.PROMOTE:
            self._stats["promoted"] += 1
            if semantic_grade == SemanticGrade.EXPLICIT:
                self._stats["explicit_promoted"] += 1
            elif semantic_grade == SemanticGrade.MIXED:
                self._stats["mixed_promoted"] += 1
            else:
                self._stats["discursive_promoted"] += 1
        elif result.decision == PromotionDecision.DEFER:
            self._stats["deferred"] += 1
        else:
            self._stats["rejected"] += 1

        return result

    def _evaluate_explicit(
        self,
        canonical: CanonicalRelation,
        support: SupportStrength,
        confidence: float,
    ) -> PromotionResult:
        """Évalue un candidat EXPLICIT."""
        t = self.thresholds

        # EXPLICIT: seuils bas
        if support.support_count < t.explicit_min_support:
            return PromotionResult(
                decision=PromotionDecision.DEFER,
                reason=f"EXPLICIT: support_count {support.support_count} < {t.explicit_min_support}",
            )

        if confidence < t.explicit_min_confidence:
            return PromotionResult(
                decision=PromotionDecision.DEFER,
                reason=f"EXPLICIT: confidence {confidence:.2f} < {t.explicit_min_confidence}",
            )

        # Promouvoir
        return PromotionResult(
            decision=PromotionDecision.PROMOTE,
            reason=f"EXPLICIT: meets thresholds (support={support.support_count}, conf={confidence:.2f})",
        )

    def _evaluate_mixed(
        self,
        canonical: CanonicalRelation,
        support: SupportStrength,
        confidence: float,
    ) -> PromotionResult:
        """Évalue un candidat MIXED."""
        t = self.thresholds

        # MIXED: doit avoir au moins 1 EXPLICIT
        if support.explicit_count < t.mixed_min_explicit:
            return PromotionResult(
                decision=PromotionDecision.DEFER,
                reason=f"MIXED: explicit_count {support.explicit_count} < {t.mixed_min_explicit}",
            )

        if support.support_count < t.mixed_min_support:
            return PromotionResult(
                decision=PromotionDecision.DEFER,
                reason=f"MIXED: support_count {support.support_count} < {t.mixed_min_support}",
            )

        if confidence < t.mixed_min_confidence:
            return PromotionResult(
                decision=PromotionDecision.DEFER,
                reason=f"MIXED: confidence {confidence:.2f} < {t.mixed_min_confidence}",
            )

        # Promouvoir
        return PromotionResult(
            decision=PromotionDecision.PROMOTE,
            reason=f"MIXED: meets thresholds (explicit={support.explicit_count}, conf={confidence:.2f})",
        )

    def _evaluate_discursive(
        self,
        canonical: CanonicalRelation,
        support: SupportStrength,
        confidence: float,
    ) -> PromotionResult:
        """Évalue un candidat DISCURSIVE (seuils plus stricts)."""
        t = self.thresholds
        warnings: List[str] = []

        # DISCURSIVE: ≥2 assertions OU ≥2 documents
        support_ok = (
            support.support_count >= t.discursive_min_support or
            support.doc_coverage >= 2
        )
        if not support_ok:
            return PromotionResult(
                decision=PromotionDecision.DEFER,
                reason=(
                    f"DISCURSIVE: insufficient support "
                    f"(support={support.support_count}, docs={support.doc_coverage})"
                ),
            )

        # Confiance
        if confidence < t.discursive_min_confidence:
            return PromotionResult(
                decision=PromotionDecision.DEFER,
                reason=f"DISCURSIVE: confidence {confidence:.2f} < {t.discursive_min_confidence}",
            )

        # Bundle diversity (au moins 1 section = diversity ≥ 0.33)
        if support.bundle_diversity < t.discursive_min_diversity:
            # Warning mais pas bloquant si multi-docs
            if support.doc_coverage >= 2:
                warnings.append(
                    f"Low bundle_diversity ({support.bundle_diversity:.2f}) "
                    f"but multi-doc coverage compensates"
                )
            else:
                return PromotionResult(
                    decision=PromotionDecision.DEFER,
                    reason=(
                        f"DISCURSIVE: bundle_diversity {support.bundle_diversity:.2f} < "
                        f"{t.discursive_min_diversity}"
                    ),
                )

        # Promouvoir
        return PromotionResult(
            decision=PromotionDecision.PROMOTE,
            reason=(
                f"DISCURSIVE: meets thresholds "
                f"(support={support.support_count}, docs={support.doc_coverage}, "
                f"diversity={support.bundle_diversity:.2f}, conf={confidence:.2f})"
            ),
            warnings=warnings,
        )

    def promote_if_eligible(
        self,
        canonical: CanonicalRelation,
        discursive_bases: Optional[List[DiscursiveBasis]] = None,
        extraction_method: ExtractionMethod = ExtractionMethod.HYBRID,
        span_count: int = 1,
        has_marker_in_text: bool = True,
    ) -> Optional[SemanticRelation]:
        """
        Évalue et promeut une CanonicalRelation si éligible.

        Args:
            canonical: CanonicalRelation à évaluer
            discursive_bases: Bases discursives (pour calcul tier)
            extraction_method: Méthode d'extraction
            span_count: Nombre de spans
            has_marker_in_text: Marqueur textuel présent

        Returns:
            SemanticRelation si promue, None sinon
        """
        # Évaluer
        result = self.evaluate_promotion(canonical)

        if result.decision != PromotionDecision.PROMOTE:
            logger.debug(
                f"[RelationPromoter] Not promoting {canonical.canonical_relation_id}: "
                f"{result.reason}"
            )
            return None

        # Promouvoir via le writer
        writer = self._get_writer()

        # Convertir les bases en string pour le writer
        bases_str = None
        if discursive_bases:
            bases_str = [b.value if hasattr(b, 'value') else str(b) for b in discursive_bases]

        return writer.promote_relation(
            canonical=canonical,
            discursive_bases=bases_str,
            extraction_method=extraction_method,
            span_count=span_count,
            has_marker_in_text=has_marker_in_text,
            promotion_reason=result.reason,
        )

    def promote_batch(
        self,
        canonicals: List[CanonicalRelation],
        **kwargs,
    ) -> List[SemanticRelation]:
        """
        Évalue et promeut un batch de CanonicalRelations.

        Args:
            canonicals: Liste de CanonicalRelation
            **kwargs: Arguments passés à promote_if_eligible

        Returns:
            Liste des SemanticRelations promues
        """
        promoted: List[SemanticRelation] = []

        for canonical in canonicals:
            result = self.promote_if_eligible(canonical, **kwargs)
            if result:
                promoted.append(result)

        logger.info(
            f"[RelationPromoter] Batch: {len(promoted)}/{len(canonicals)} promoted "
            f"(EXPLICIT={self._stats['explicit_promoted']}, "
            f"MIXED={self._stats['mixed_promoted']}, "
            f"DISCURSIVE={self._stats['discursive_promoted']})"
        )

        return promoted

    def get_stats(self) -> Dict[str, int]:
        """Get promotion statistics."""
        return self._stats.copy()

    def reset_stats(self) -> None:
        """Reset statistics."""
        self._stats = {
            "evaluated": 0,
            "promoted": 0,
            "deferred": 0,
            "rejected": 0,
            "explicit_promoted": 0,
            "mixed_promoted": 0,
            "discursive_promoted": 0,
        }


# Singleton-like access
_promoter_instance: Optional[RelationPromoter] = None


def get_relation_promoter(
    tenant_id: str = "default",
    thresholds: Optional[PromotionThresholds] = None,
    **kwargs,
) -> RelationPromoter:
    """Get or create RelationPromoter instance."""
    global _promoter_instance
    if _promoter_instance is None or _promoter_instance.tenant_id != tenant_id:
        _promoter_instance = RelationPromoter(
            tenant_id=tenant_id,
            thresholds=thresholds,
            **kwargs,
        )
    return _promoter_instance


def should_promote(
    canonical: CanonicalRelation,
    thresholds: Optional[PromotionThresholds] = None,
) -> PromotionResult:
    """
    Fonction utilitaire pour évaluer rapidement si une relation doit être promue.

    Args:
        canonical: CanonicalRelation à évaluer
        thresholds: Seuils optionnels

    Returns:
        PromotionResult avec décision
    """
    promoter = RelationPromoter(thresholds=thresholds)
    return promoter.evaluate_promotion(canonical)
