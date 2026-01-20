"""
Tests d'intégration pour le pipeline des Relations Discursivement Déterminées.

Valide le flux complet:
RawAssertion (avec assertion_kind) → CanonicalRelation (avec compteurs) → SemanticRelation (avec tier)

Ref: doc/ongoing/ADR_DISCURSIVE_RELATIONS.md

Author: Claude Code
Date: 2025-01-20
"""

import pytest
from datetime import datetime
from unittest.mock import MagicMock, patch

from knowbase.relations.types import (
    # Enums de base
    RelationType,
    ExtractionMethod,
    RelationMaturity,
    RelationStatus,
    RawAssertionFlags,
    PredicateProfile,
    # ADR Discursive
    AssertionKind,
    DiscursiveBasis,
    DiscursiveAbstainReason,
    SemanticGrade,
    DefensibilityTier,
    # Models
    RawAssertion,
    CanonicalRelation,
    SemanticRelation,
    SupportStrength,
    # Functions
    compute_semantic_grade,
    compute_bundle_diversity,
)
from knowbase.relations.tier_attribution import (
    compute_defensibility_tier,
    compute_tier_for_discursive,
    TierAttributionResult,
)


class TestComputeSemanticGrade:
    """Tests pour le calcul du semantic_grade."""

    def test_only_explicit_assertions(self):
        """Seulement des assertions EXPLICIT → grade EXPLICIT."""
        grade = compute_semantic_grade(explicit_count=5, discursive_count=0)
        assert grade == SemanticGrade.EXPLICIT

    def test_only_discursive_assertions(self):
        """Seulement des assertions DISCURSIVE → grade DISCURSIVE."""
        grade = compute_semantic_grade(explicit_count=0, discursive_count=3)
        assert grade == SemanticGrade.DISCURSIVE

    def test_mixed_assertions(self):
        """Mix EXPLICIT + DISCURSIVE → grade MIXED."""
        grade = compute_semantic_grade(explicit_count=2, discursive_count=3)
        assert grade == SemanticGrade.MIXED

    def test_zero_both(self):
        """Aucune assertion → MIXED (edge case, 0 des deux côtés)."""
        # Note: 0 EXPLICIT et 0 DISCURSIVE → ratio indéterminé → MIXED par défaut
        grade = compute_semantic_grade(explicit_count=0, discursive_count=0)
        assert grade == SemanticGrade.MIXED


class TestComputeBundleDiversity:
    """Tests pour le calcul de bundle_diversity."""

    def test_zero_sections(self):
        """0 sections → diversity 0."""
        diversity = compute_bundle_diversity(0)
        assert diversity == 0.0

    def test_one_section(self):
        """1 section → diversity 0.33."""
        diversity = compute_bundle_diversity(1)
        assert abs(diversity - 0.33) < 0.01

    def test_two_sections(self):
        """2 sections → diversity 0.67."""
        diversity = compute_bundle_diversity(2)
        assert abs(diversity - 0.67) < 0.01

    def test_three_or_more_sections(self):
        """≥3 sections → diversity 1.0."""
        assert compute_bundle_diversity(3) == 1.0
        assert compute_bundle_diversity(5) == 1.0
        assert compute_bundle_diversity(10) == 1.0


class TestDefensibilityTierCalculation:
    """Tests pour le calcul du DefensibilityTier via semantic_grade."""

    def test_explicit_grade_always_strict(self):
        """EXPLICIT → toujours STRICT."""
        result = compute_defensibility_tier(semantic_grade=SemanticGrade.EXPLICIT)
        assert result.tier == DefensibilityTier.STRICT
        assert "EXPLICIT" in result.reason

    def test_mixed_grade_always_strict(self):
        """MIXED → toujours STRICT (ancré par au moins un EXPLICIT)."""
        result = compute_defensibility_tier(semantic_grade=SemanticGrade.MIXED)
        assert result.tier == DefensibilityTier.STRICT
        assert "MIXED" in result.reason

    def test_discursive_with_strong_basis_and_marker_is_strict(self):
        """DISCURSIVE + base forte + marqueur → STRICT."""
        result = compute_defensibility_tier(
            semantic_grade=SemanticGrade.DISCURSIVE,
            discursive_bases=[DiscursiveBasis.ALTERNATIVE],
            relation_type=RelationType.ALTERNATIVE_TO,
            extraction_method=ExtractionMethod.PATTERN,
            has_marker_in_text=True,
        )
        assert result.tier == DefensibilityTier.STRICT

    def test_discursive_with_strong_basis_no_marker_is_extended(self):
        """DISCURSIVE + base forte sans marqueur → EXTENDED."""
        result = compute_defensibility_tier(
            semantic_grade=SemanticGrade.DISCURSIVE,
            discursive_bases=[DiscursiveBasis.ALTERNATIVE],
            relation_type=RelationType.ALTERNATIVE_TO,
            extraction_method=ExtractionMethod.PATTERN,
            has_marker_in_text=False,
        )
        assert result.tier == DefensibilityTier.EXTENDED

    def test_discursive_with_weak_basis_2_spans_is_strict(self):
        """DISCURSIVE + base faible + 2 spans → STRICT."""
        result = compute_defensibility_tier(
            semantic_grade=SemanticGrade.DISCURSIVE,
            discursive_bases=[DiscursiveBasis.SCOPE],
            relation_type=RelationType.APPLIES_TO,
            extraction_method=ExtractionMethod.HYBRID,
            span_count=2,
        )
        assert result.tier == DefensibilityTier.STRICT

    def test_discursive_with_weak_basis_1_span_is_extended(self):
        """DISCURSIVE + base faible + 1 span → EXTENDED."""
        result = compute_defensibility_tier(
            semantic_grade=SemanticGrade.DISCURSIVE,
            discursive_bases=[DiscursiveBasis.SCOPE],
            relation_type=RelationType.APPLIES_TO,
            extraction_method=ExtractionMethod.HYBRID,
            span_count=1,
        )
        assert result.tier == DefensibilityTier.EXTENDED

    def test_discursive_llm_only_is_extended(self):
        """DISCURSIVE + LLM seul → EXTENDED (C3bis)."""
        result = compute_defensibility_tier(
            semantic_grade=SemanticGrade.DISCURSIVE,
            discursive_bases=[DiscursiveBasis.ALTERNATIVE],
            relation_type=RelationType.ALTERNATIVE_TO,
            extraction_method=ExtractionMethod.LLM,  # Interdit pour DISCURSIVE
            has_marker_in_text=True,
        )
        assert result.tier == DefensibilityTier.EXTENDED
        assert result.abstain_reason == DiscursiveAbstainReason.TYPE2_RISK

    def test_discursive_forbidden_type_is_extended(self):
        """DISCURSIVE + type interdit (CAUSES) → EXTENDED (C4)."""
        result = compute_defensibility_tier(
            semantic_grade=SemanticGrade.DISCURSIVE,
            discursive_bases=[DiscursiveBasis.ALTERNATIVE],
            relation_type=RelationType.CAUSES,  # Interdit pour DISCURSIVE
            extraction_method=ExtractionMethod.PATTERN,
            has_marker_in_text=True,
        )
        assert result.tier == DefensibilityTier.EXTENDED
        assert result.abstain_reason == DiscursiveAbstainReason.WHITELIST_VIOLATION


class TestRawAssertionDiscursiveFields:
    """Tests pour les champs discursifs sur RawAssertion."""

    def test_default_values(self):
        """Valeurs par défaut: EXPLICIT, pas de basis, pas de abstain."""
        assertion = RawAssertion(
            raw_assertion_id="ra_test",
            tenant_id="default",
            raw_fingerprint="abc123",
            predicate_raw="uses",
            predicate_norm="uses",
            subject_concept_id="cc_1",
            object_concept_id="cc_2",
            evidence_text="SAP uses HANA",
            source_doc_id="doc_1",
            source_chunk_id="chunk_1",
            confidence_extractor=0.9,
            confidence_final=0.9,
        )
        assert assertion.assertion_kind == AssertionKind.EXPLICIT
        assert assertion.discursive_basis == []
        assert assertion.abstain_reason is None

    def test_discursive_assertion(self):
        """Assertion DISCURSIVE avec basis et raison d'abstention."""
        assertion = RawAssertion(
            raw_assertion_id="ra_test",
            tenant_id="default",
            raw_fingerprint="abc123",
            predicate_raw="or",
            predicate_norm="alternative to",
            subject_concept_id="cc_1",
            object_concept_id="cc_2",
            evidence_text="Use SAP or Oracle",
            source_doc_id="doc_1",
            source_chunk_id="chunk_1",
            confidence_extractor=0.8,
            confidence_final=0.8,
            assertion_kind=AssertionKind.DISCURSIVE,
            discursive_basis=[DiscursiveBasis.ALTERNATIVE],
            abstain_reason=None,  # Pas d'abstention car basis forte
        )
        assert assertion.assertion_kind == AssertionKind.DISCURSIVE
        assert DiscursiveBasis.ALTERNATIVE in assertion.discursive_basis


class TestCanonicalRelationCounters:
    """Tests pour les compteurs discursifs sur CanonicalRelation."""

    def test_explicit_only_counters(self):
        """Seulement des EXPLICIT → explicit_count > 0, discursive_count = 0."""
        relation = CanonicalRelation(
            canonical_relation_id="cr_test",
            tenant_id="default",
            relation_type=RelationType.USES,
            predicate_norm="uses",
            subject_concept_id="cc_1",
            object_concept_id="cc_2",
            distinct_documents=2,
            distinct_chunks=3,
            total_assertions=5,
            maturity=RelationMaturity.VALIDATED,
            status=RelationStatus.ACTIVE,
            explicit_support_count=5,
            discursive_support_count=0,
            distinct_sections=2,
        )
        assert relation.explicit_support_count == 5
        assert relation.discursive_support_count == 0

    def test_mixed_counters(self):
        """Mix EXPLICIT + DISCURSIVE → les deux compteurs > 0."""
        relation = CanonicalRelation(
            canonical_relation_id="cr_test",
            tenant_id="default",
            relation_type=RelationType.ALTERNATIVE_TO,
            predicate_norm="alternative to",
            subject_concept_id="cc_1",
            object_concept_id="cc_2",
            distinct_documents=3,
            distinct_chunks=5,
            total_assertions=8,
            maturity=RelationMaturity.VALIDATED,
            status=RelationStatus.ACTIVE,
            explicit_support_count=3,
            discursive_support_count=5,
            distinct_sections=4,
        )
        assert relation.explicit_support_count == 3
        assert relation.discursive_support_count == 5
        assert relation.distinct_sections == 4


class TestSemanticRelationPromotion:
    """Tests pour la promotion de CanonicalRelation vers SemanticRelation."""

    def test_semantic_relation_from_explicit_canonical(self):
        """Promotion d'une CanonicalRelation avec seulement des EXPLICIT."""
        # CanonicalRelation source
        canonical = CanonicalRelation(
            canonical_relation_id="cr_test",
            tenant_id="default",
            relation_type=RelationType.REQUIRES,
            predicate_norm="requires",
            subject_concept_id="cc_1",
            object_concept_id="cc_2",
            distinct_documents=2,
            distinct_chunks=3,
            total_assertions=4,
            maturity=RelationMaturity.VALIDATED,
            status=RelationStatus.ACTIVE,
            confidence_p50=0.85,
            explicit_support_count=4,
            discursive_support_count=0,
            distinct_sections=2,
        )

        # Calculer semantic_grade
        grade = compute_semantic_grade(
            canonical.explicit_support_count,
            canonical.discursive_support_count
        )
        assert grade == SemanticGrade.EXPLICIT

        # Calculer tier
        tier_result = compute_defensibility_tier(semantic_grade=grade)
        assert tier_result.tier == DefensibilityTier.STRICT

        # Construire SemanticRelation
        semantic = SemanticRelation(
            semantic_relation_id="sr_test",
            canonical_relation_id=canonical.canonical_relation_id,
            tenant_id=canonical.tenant_id,
            relation_type=canonical.relation_type,
            subject_concept_id=canonical.subject_concept_id,
            object_concept_id=canonical.object_concept_id,
            semantic_grade=grade,
            defensibility_tier=tier_result.tier,
            support_strength=SupportStrength(
                support_count=canonical.total_assertions,
                explicit_count=canonical.explicit_support_count,
                discursive_count=canonical.discursive_support_count,
                doc_coverage=canonical.distinct_documents,
                distinct_sections=canonical.distinct_sections,
                bundle_diversity=compute_bundle_diversity(canonical.distinct_sections),
            ),
            confidence=canonical.confidence_p50,
        )

        assert semantic.semantic_grade == SemanticGrade.EXPLICIT
        assert semantic.defensibility_tier == DefensibilityTier.STRICT
        assert semantic.support_strength.explicit_count == 4
        assert semantic.support_strength.discursive_count == 0

    def test_semantic_relation_from_mixed_canonical(self):
        """Promotion d'une CanonicalRelation MIXED → STRICT."""
        canonical = CanonicalRelation(
            canonical_relation_id="cr_mixed",
            tenant_id="default",
            relation_type=RelationType.ALTERNATIVE_TO,
            predicate_norm="alternative to",
            subject_concept_id="cc_1",
            object_concept_id="cc_2",
            distinct_documents=2,
            distinct_chunks=4,
            total_assertions=6,
            maturity=RelationMaturity.VALIDATED,
            status=RelationStatus.ACTIVE,
            confidence_p50=0.75,
            explicit_support_count=2,
            discursive_support_count=4,
            distinct_sections=3,
        )

        grade = compute_semantic_grade(
            canonical.explicit_support_count,
            canonical.discursive_support_count
        )
        assert grade == SemanticGrade.MIXED

        tier_result = compute_defensibility_tier(semantic_grade=grade)
        assert tier_result.tier == DefensibilityTier.STRICT  # MIXED → STRICT

    def test_semantic_relation_from_discursive_strong_basis(self):
        """Promotion DISCURSIVE avec base forte + marqueur → STRICT."""
        canonical = CanonicalRelation(
            canonical_relation_id="cr_discursive",
            tenant_id="default",
            relation_type=RelationType.ALTERNATIVE_TO,
            predicate_norm="alternative to",
            subject_concept_id="cc_1",
            object_concept_id="cc_2",
            distinct_documents=1,
            distinct_chunks=1,
            total_assertions=2,
            maturity=RelationMaturity.CANDIDATE,
            status=RelationStatus.ACTIVE,
            confidence_p50=0.70,
            explicit_support_count=0,
            discursive_support_count=2,
            distinct_sections=1,
        )

        grade = compute_semantic_grade(0, 2)
        assert grade == SemanticGrade.DISCURSIVE

        # Avec base forte ALTERNATIVE et marqueur présent → STRICT
        tier_result = compute_defensibility_tier(
            semantic_grade=grade,
            discursive_bases=[DiscursiveBasis.ALTERNATIVE],
            relation_type=RelationType.ALTERNATIVE_TO,
            extraction_method=ExtractionMethod.PATTERN,
            has_marker_in_text=True,
        )
        assert tier_result.tier == DefensibilityTier.STRICT


class TestPipelineEndToEnd:
    """Tests du flux complet conceptuel (sans Neo4j)."""

    def test_pipeline_explicit_only(self):
        """Flux: 3 RawAssertion EXPLICIT → CanonicalRelation → SemanticRelation STRICT."""
        # Simuler 3 RawAssertions EXPLICIT
        raw_assertions = [
            {"assertion_kind": AssertionKind.EXPLICIT, "source_doc_id": "doc_1"},
            {"assertion_kind": AssertionKind.EXPLICIT, "source_doc_id": "doc_2"},
            {"assertion_kind": AssertionKind.EXPLICIT, "source_doc_id": "doc_3"},
        ]

        # Agrégation (simulée par RelationConsolidator)
        explicit_count = sum(1 for a in raw_assertions if a["assertion_kind"] == AssertionKind.EXPLICIT)
        discursive_count = sum(1 for a in raw_assertions if a["assertion_kind"] == AssertionKind.DISCURSIVE)

        assert explicit_count == 3
        assert discursive_count == 0

        # Calcul semantic_grade
        grade = compute_semantic_grade(explicit_count, discursive_count)
        assert grade == SemanticGrade.EXPLICIT

        # Calcul tier
        tier_result = compute_defensibility_tier(semantic_grade=grade)
        assert tier_result.tier == DefensibilityTier.STRICT

    def test_pipeline_discursive_extended(self):
        """Flux: RawAssertions DISCURSIVE avec weak basis, 1 span → EXTENDED."""
        raw_assertions = [
            {"assertion_kind": AssertionKind.DISCURSIVE, "source_doc_id": "doc_1"},
        ]

        explicit_count = 0
        discursive_count = 1

        grade = compute_semantic_grade(explicit_count, discursive_count)
        assert grade == SemanticGrade.DISCURSIVE

        # Weak basis (SCOPE) avec 1 seul span → EXTENDED
        tier_result = compute_defensibility_tier(
            semantic_grade=grade,
            discursive_bases=[DiscursiveBasis.SCOPE],
            relation_type=RelationType.APPLIES_TO,
            extraction_method=ExtractionMethod.HYBRID,
            span_count=1,
        )
        assert tier_result.tier == DefensibilityTier.EXTENDED

    def test_pipeline_mixed_always_strict(self):
        """Flux: Mix EXPLICIT + DISCURSIVE → toujours STRICT."""
        explicit_count = 1
        discursive_count = 5

        grade = compute_semantic_grade(explicit_count, discursive_count)
        assert grade == SemanticGrade.MIXED

        # Même sans bases, MIXED → STRICT car ancré par l'EXPLICIT
        tier_result = compute_defensibility_tier(semantic_grade=grade)
        assert tier_result.tier == DefensibilityTier.STRICT


class TestTierAttributionResult:
    """Tests pour TierAttributionResult."""

    def test_repr(self):
        """Test représentation string."""
        result = TierAttributionResult(
            tier=DefensibilityTier.STRICT,
            reason="Test reason"
        )
        assert "STRICT" in repr(result)
        assert "Test reason" in repr(result)

    def test_with_abstain_reason(self):
        """Test avec raison d'abstention."""
        result = TierAttributionResult(
            tier=DefensibilityTier.EXTENDED,
            reason="LLM seul interdit",
            abstain_reason=DiscursiveAbstainReason.TYPE2_RISK
        )
        assert result.tier == DefensibilityTier.EXTENDED
        assert result.abstain_reason == DiscursiveAbstainReason.TYPE2_RISK
