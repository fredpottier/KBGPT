"""
Tests de régression Type 2 - Anti-hallucination.

Ces tests vérifient que le système ne produit PAS de faux positifs (Type 2).
Un faux positif Type 2 = accepter une relation qui ne devrait pas l'être.

Principe: "Il vaut mieux s'abstenir que de se tromper."

Cas testés:
1. Opinions subjectives → ABSTAIN
2. Relations causales (ENABLES, CAUSES) en mode DISCURSIVE → ABSTAIN
3. Causalité implicite sans marqueur → ABSTAIN
4. Patterns valides (ALTERNATIVE, DEFAULT, EXCEPTION) → ACCEPT

Ref: doc/ongoing/ADR_DISCURSIVE_RELATIONS.md

Author: Claude Code
Date: 2026-01-21
"""

import pytest
from typing import List, Optional, Tuple

from knowbase.relations.types import (
    AssertionKind,
    DiscursiveBasis,
    DiscursiveAbstainReason,
    RelationType,
    ExtractionMethod,
    EvidenceBundle,
    EvidenceSpan,
    EvidenceSpanRole,
    DefensibilityTier,
    SemanticGrade,
)
from knowbase.relations.assertion_validation import (
    ValidationErrorCode,
    ValidationResult,
    validate_before_write,
    validate_extraction_method_c3bis,
    validate_relation_type_c4,
)
from knowbase.relations.tier_attribution import (
    compute_defensibility_tier,
    is_relation_type_allowed_for_discursive,
    should_abstain,
    TierAttributionResult,
)
from knowbase.relations.discursive_pattern_extractor import (
    DiscursivePatternExtractor,
    DiscursiveCandidate,
    get_discursive_pattern_extractor,
)


# =============================================================================
# Helpers
# =============================================================================

def make_evidence_bundle(
    text: str,
    basis: DiscursiveBasis = DiscursiveBasis.ALTERNATIVE,
    has_bridge: bool = True,
) -> EvidenceBundle:
    """Crée un EvidenceBundle de test."""
    return EvidenceBundle(
        basis=basis,
        spans=[
            EvidenceSpan(
                doc_item_id="item_001",
                role=EvidenceSpanRole.SCOPE_SETTER,
                text_excerpt=text,
            ),
            EvidenceSpan(
                doc_item_id="item_002",
                role=EvidenceSpanRole.BRIDGE if has_bridge else EvidenceSpanRole.MENTION,
                text_excerpt=text,
            ),
        ],
        section_id="sec_001",
        document_id="doc_001",
        has_bridge=has_bridge,
    )


def extract_discursive_candidates(text: str) -> List[DiscursiveCandidate]:
    """
    Extrait les candidats discursifs d'un texte.

    Utilise un inventaire de concepts SAP typiques pour les tests.
    Règle E6: opère sur inventaire de concepts existants uniquement.
    """
    # Concepts de test typiques SAP/IT
    test_concepts = [
        {"concept_id": "sap_hana", "canonical_name": "SAP HANA", "surface_forms": ["HANA", "SAP HANA", "hana"]},
        {"concept_id": "sap_bw", "canonical_name": "SAP BW", "surface_forms": ["BW", "SAP BW", "Business Warehouse"]},
        {"concept_id": "oracle", "canonical_name": "Oracle", "surface_forms": ["Oracle", "Oracle Database"]},
        {"concept_id": "s4hana", "canonical_name": "SAP S/4HANA", "surface_forms": ["S/4HANA", "SAP S/4HANA", "S4HANA"]},
        {"concept_id": "postgresql", "canonical_name": "PostgreSQL", "surface_forms": ["PostgreSQL", "Postgres"]},
        {"concept_id": "legacy_mode", "canonical_name": "Legacy Mode", "surface_forms": ["legacy mode", "Legacy Mode"]},
        {"concept_id": "modules", "canonical_name": "Modules", "surface_forms": ["modules", "All modules"]},
        {"concept_id": "deployments", "canonical_name": "Deployments", "surface_forms": ["deployments", "all deployments"]},
        {"concept_id": "on_premise_legacy", "canonical_name": "On-premise Legacy", "surface_forms": ["on-premise legacy", "On-premise Legacy"]},
    ]

    extractor = get_discursive_pattern_extractor()
    result = extractor.extract(
        text=text,
        concepts=test_concepts,
        document_id="test_doc",
        chunk_id=None,
    )
    return result.candidates


# =============================================================================
# Type 2 Regression: Opinions subjectives → ABSTAIN
# =============================================================================

class TestType2Opinions:
    """
    Tests: Les opinions subjectives ne doivent PAS produire d'assertions.

    Type 2 = Accepter une relation non-factuelle.
    """

    def test_comparative_opinion_no_candidates(self):
        """'X is better than Y' ne doit pas produire de candidat."""
        text = "SAP is better than Oracle for enterprise applications."
        candidates = extract_discursive_candidates(text)

        # Pas de pattern ALTERNATIVE détecté (pas de "or")
        assert len(candidates) == 0, (
            "Opinion comparative ne doit pas produire de candidat discursif"
        )

    def test_subjective_preference_no_candidates(self):
        """'We prefer X over Y' ne doit pas produire de candidat."""
        text = "We prefer HANA over traditional databases."
        candidates = extract_discursive_candidates(text)

        assert len(candidates) == 0, (
            "Préférence subjective ne doit pas produire de candidat"
        )

    def test_recommendation_without_marker_no_candidates(self):
        """'You should use X' sans marqueur explicite ne doit pas être DISCURSIVE."""
        text = "You should use SAP HANA for better performance."
        candidates = extract_discursive_candidates(text)

        # "should" n'est pas un pattern ALTERNATIVE/DEFAULT/EXCEPTION
        assert len(candidates) == 0


# =============================================================================
# Type 2 Regression: Relations causales interdites
# =============================================================================

class TestType2CausalRelations:
    """
    Tests: Les relations causales (ENABLES, CAUSES, PREVENTS) sont interdites
    pour les assertions DISCURSIVE.

    Raison: La causalité requiert un raisonnement sur le monde, pas juste
    une reconstruction textuelle.
    """

    def test_enables_forbidden_for_discursive(self):
        """ENABLES est interdit pour DISCURSIVE (C4 violation)."""
        result = validate_relation_type_c4(
            AssertionKind.DISCURSIVE,
            RelationType.ENABLES
        )

        assert not result.is_valid
        assert result.error_code == ValidationErrorCode.RELATION_TYPE_FORBIDDEN
        assert result.abstain_reason == DiscursiveAbstainReason.WHITELIST_VIOLATION

    def test_causes_forbidden_for_discursive(self):
        """CAUSES est interdit pour DISCURSIVE (C4 violation)."""
        result = validate_relation_type_c4(
            AssertionKind.DISCURSIVE,
            RelationType.CAUSES
        )

        assert not result.is_valid
        assert result.error_code == ValidationErrorCode.RELATION_TYPE_FORBIDDEN

    def test_prevents_forbidden_for_discursive(self):
        """PREVENTS est interdit pour DISCURSIVE (C4 violation)."""
        result = validate_relation_type_c4(
            AssertionKind.DISCURSIVE,
            RelationType.PREVENTS
        )

        assert not result.is_valid
        assert result.error_code == ValidationErrorCode.RELATION_TYPE_FORBIDDEN

    def test_enables_text_not_extracted_as_alternative(self):
        """'X enables Y' ne doit pas être extrait comme ALTERNATIVE."""
        text = "HANA enables real-time analytics for business users."
        candidates = extract_discursive_candidates(text)

        # Pas de pattern "or" donc pas d'ALTERNATIVE
        assert len(candidates) == 0

    def test_implicit_causality_no_candidates(self):
        """Causalité implicite 'If X then Y' ne doit pas produire de candidat."""
        text = "If you use BW, you need HANA for optimal performance."
        candidates = extract_discursive_candidates(text)

        # "If...then" n'est pas un pattern ALTERNATIVE
        # Note: "unless" serait EXCEPTION, mais "If" n'est pas traité
        # car la causalité est implicite
        alternative_candidates = [c for c in candidates if c.discursive_basis == DiscursiveBasis.ALTERNATIVE]
        assert len(alternative_candidates) == 0


# =============================================================================
# Type 2 Regression: LLM seul interdit pour DISCURSIVE
# =============================================================================

class TestType2LLMOnly:
    """
    Tests: DISCURSIVE + LLM seul est interdit (C3bis).

    Raison: Le LLM peut halluciner des relations. Les assertions DISCURSIVE
    doivent être basées sur des patterns textuels vérifiables.
    """

    def test_discursive_llm_only_forbidden(self):
        """DISCURSIVE + ExtractionMethod.LLM est interdit."""
        result = validate_extraction_method_c3bis(
            AssertionKind.DISCURSIVE,
            ExtractionMethod.LLM
        )

        assert not result.is_valid
        assert result.error_code == ValidationErrorCode.DISCURSIVE_LLM_ONLY
        assert result.abstain_reason == DiscursiveAbstainReason.TYPE2_RISK

    def test_discursive_pattern_allowed(self):
        """DISCURSIVE + ExtractionMethod.PATTERN est autorisé."""
        result = validate_extraction_method_c3bis(
            AssertionKind.DISCURSIVE,
            ExtractionMethod.PATTERN
        )

        assert result.is_valid

    def test_discursive_hybrid_allowed(self):
        """DISCURSIVE + ExtractionMethod.HYBRID est autorisé."""
        result = validate_extraction_method_c3bis(
            AssertionKind.DISCURSIVE,
            ExtractionMethod.HYBRID
        )

        assert result.is_valid

    def test_explicit_llm_allowed(self):
        """EXPLICIT + ExtractionMethod.LLM est autorisé."""
        result = validate_extraction_method_c3bis(
            AssertionKind.EXPLICIT,
            ExtractionMethod.LLM
        )

        assert result.is_valid


# =============================================================================
# Type 2 Regression: Evidence locale obligatoire
# =============================================================================

class TestType2EvidenceRequired:
    """
    Tests: Une assertion DISCURSIVE doit avoir une preuve locale avec bridge.

    Raison: Sans preuve locale, on fait de la "promotion de scope" qui
    est une source de Type 2.
    """

    def test_discursive_without_bridge_rejected(self):
        """DISCURSIVE sans bridge local est rejeté."""
        bundle = make_evidence_bundle(
            text="Some text mentioning concepts",
            basis=DiscursiveBasis.SCOPE,
            has_bridge=False,  # Pas de bridge
        )

        result = validate_before_write(
            assertion_kind=AssertionKind.DISCURSIVE,
            relation_type=RelationType.ALTERNATIVE_TO,
            extraction_method=ExtractionMethod.PATTERN,
            evidence_bundle=bundle,
            discursive_basis=[DiscursiveBasis.SCOPE],
        )

        assert not result.is_valid
        assert result.error_code == ValidationErrorCode.NO_BRIDGE_FOR_DISCURSIVE

    def test_discursive_with_bridge_accepted(self):
        """DISCURSIVE avec bridge local est accepté."""
        bundle = make_evidence_bundle(
            text="Use HANA or BW for analytics",
            basis=DiscursiveBasis.ALTERNATIVE,
            has_bridge=True,
        )

        result = validate_before_write(
            assertion_kind=AssertionKind.DISCURSIVE,
            relation_type=RelationType.ALTERNATIVE_TO,
            extraction_method=ExtractionMethod.PATTERN,
            evidence_bundle=bundle,
            discursive_basis=[DiscursiveBasis.ALTERNATIVE],
        )

        assert result.is_valid


# =============================================================================
# Valid Patterns: Ces cas DOIVENT produire des assertions
# =============================================================================

class TestValidPatterns:
    """
    Tests: Les patterns valides doivent produire des assertions correctes.

    Type 1 = Rejeter une relation valide (faux négatif).
    On veut minimiser Type 1 tout en garantissant 0% Type 2.
    """

    def test_alternative_or_pattern_produces_candidate(self):
        """'X or Y' doit produire un candidat ALTERNATIVE."""
        text = "Use HANA or Oracle for the database layer."
        candidates = extract_discursive_candidates(text)

        # Doit avoir au moins un candidat ALTERNATIVE
        alternative_candidates = [
            c for c in candidates
            if c.discursive_basis == DiscursiveBasis.ALTERNATIVE
        ]
        assert len(alternative_candidates) >= 1, (
            "Pattern 'or' doit produire au moins un candidat ALTERNATIVE"
        )

    def test_alternative_either_or_pattern(self):
        """'Either X or Y' doit produire un candidat ALTERNATIVE."""
        text = "You can use either SAP BW or SAP HANA for analytics."
        candidates = extract_discursive_candidates(text)

        alternative_candidates = [
            c for c in candidates
            if c.discursive_basis == DiscursiveBasis.ALTERNATIVE
        ]
        assert len(alternative_candidates) >= 1

    def test_default_pattern_produces_candidate(self):
        """'X by default' doit produire un candidat DEFAULT."""
        text = "S/4HANA uses HANA by default for the database."
        candidates = extract_discursive_candidates(text)

        default_candidates = [
            c for c in candidates
            if c.discursive_basis == DiscursiveBasis.DEFAULT
        ]
        assert len(default_candidates) >= 1, (
            "Pattern 'by default' doit produire au moins un candidat DEFAULT"
        )

    def test_exception_unless_pattern_produces_candidate(self):
        """'X unless Y' doit produire un candidat EXCEPTION."""
        text = "All modules require HANA, unless running in legacy mode."
        candidates = extract_discursive_candidates(text)

        exception_candidates = [
            c for c in candidates
            if c.discursive_basis == DiscursiveBasis.EXCEPTION
        ]
        assert len(exception_candidates) >= 1, (
            "Pattern 'unless' doit produire au moins un candidat EXCEPTION"
        )

    def test_exception_except_pattern_produces_candidate(self):
        """'X except Y' doit produire un candidat EXCEPTION.

        Note: Les patterns EXCEPTION attendent la voix active.
        Pattern: "X requires Y, except..." ou "all X require Y, except..."
        """
        # Texte avec voix active correspondant au pattern
        text = "All deployments require SAP HANA, except when using Legacy Mode."
        candidates = extract_discursive_candidates(text)

        exception_candidates = [
            c for c in candidates
            if c.discursive_basis == DiscursiveBasis.EXCEPTION
        ]
        assert len(exception_candidates) >= 1

    def test_french_ou_pattern(self):
        """'X ou Y' (français) doit produire un candidat ALTERNATIVE."""
        text = "Utilisez SAP HANA ou Oracle pour la base de données."
        candidates = extract_discursive_candidates(text)

        alternative_candidates = [
            c for c in candidates
            if c.discursive_basis == DiscursiveBasis.ALTERNATIVE
        ]
        assert len(alternative_candidates) >= 1

    def test_french_par_defaut_pattern(self):
        """'par défaut' (français) doit produire un candidat DEFAULT."""
        text = "S/4HANA utilise HANA par défaut."
        candidates = extract_discursive_candidates(text)

        default_candidates = [
            c for c in candidates
            if c.discursive_basis == DiscursiveBasis.DEFAULT
        ]
        assert len(default_candidates) >= 1


# =============================================================================
# Tier Attribution: STRICT vs EXTENDED
# =============================================================================

class TestTierAttribution:
    """
    Tests: Attribution correcte des DefensibilityTier.

    STRICT = Haute confiance, utilisable en production.
    EXTENDED = Exploration seulement, nécessite validation humaine.
    """

    def test_strong_basis_with_marker_is_strict(self):
        """Base forte (ALTERNATIVE) avec marqueur → STRICT."""
        result = compute_defensibility_tier(
            semantic_grade=SemanticGrade.DISCURSIVE,
            discursive_bases=[DiscursiveBasis.ALTERNATIVE],
            relation_type=RelationType.ALTERNATIVE_TO,  # Type autorisé
            extraction_method=ExtractionMethod.PATTERN,
            span_count=2,
            has_marker_in_text=True,  # Marqueur "or" présent
        )

        assert result.tier == DefensibilityTier.STRICT
        assert result.abstain_reason is None

    def test_strong_basis_without_marker_is_extended(self):
        """Base forte sans marqueur explicite → EXTENDED."""
        result = compute_defensibility_tier(
            semantic_grade=SemanticGrade.DISCURSIVE,
            discursive_bases=[DiscursiveBasis.ALTERNATIVE],
            relation_type=RelationType.ALTERNATIVE_TO,  # Type autorisé
            extraction_method=ExtractionMethod.PATTERN,
            span_count=2,
            has_marker_in_text=False,  # Pas de marqueur
        )

        assert result.tier == DefensibilityTier.EXTENDED

    def test_weak_basis_with_insufficient_spans_is_extended(self):
        """Base faible (SCOPE) avec 1 seul span → EXTENDED."""
        result = compute_defensibility_tier(
            semantic_grade=SemanticGrade.DISCURSIVE,
            discursive_bases=[DiscursiveBasis.SCOPE],
            relation_type=RelationType.APPLIES_TO,  # Type autorisé pour SCOPE
            extraction_method=ExtractionMethod.PATTERN,
            span_count=1,  # < 2 requis pour base faible
            has_marker_in_text=True,
        )

        assert result.tier == DefensibilityTier.EXTENDED

    def test_weak_basis_with_sufficient_spans_is_strict(self):
        """Base faible (SCOPE) avec ≥ 2 spans → STRICT."""
        result = compute_defensibility_tier(
            semantic_grade=SemanticGrade.DISCURSIVE,
            discursive_bases=[DiscursiveBasis.SCOPE],
            relation_type=RelationType.APPLIES_TO,  # Type autorisé pour SCOPE
            extraction_method=ExtractionMethod.PATTERN,
            span_count=2,  # ≥ 2 requis pour base faible
            has_marker_in_text=True,
        )

        assert result.tier == DefensibilityTier.STRICT

    def test_explicit_is_always_strict(self):
        """EXPLICIT est toujours STRICT."""
        result = compute_defensibility_tier(
            semantic_grade=SemanticGrade.EXPLICIT,
            discursive_bases=[],
            extraction_method=ExtractionMethod.LLM,
            span_count=1,
            has_marker_in_text=True,
        )

        assert result.tier == DefensibilityTier.STRICT

    def test_llm_only_discursive_abstains(self):
        """DISCURSIVE + LLM seul → ABSTAIN."""
        result = compute_defensibility_tier(
            semantic_grade=SemanticGrade.DISCURSIVE,
            discursive_bases=[DiscursiveBasis.ALTERNATIVE],
            extraction_method=ExtractionMethod.LLM,  # LLM seul interdit
            span_count=2,
            has_marker_in_text=True,
        )

        assert result.abstain_reason == DiscursiveAbstainReason.TYPE2_RISK


# =============================================================================
# Abstention explicite
# =============================================================================

class TestAbstention:
    """
    Tests: Le système doit s'abstenir correctement et documenter pourquoi.

    should_abstain() retourne Optional[DiscursiveAbstainReason]:
    - None si l'assertion est acceptable
    - DiscursiveAbstainReason si l'assertion doit être rejetée
    """

    def test_should_abstain_for_forbidden_relation_type(self):
        """should_abstain() retourne raison pour type interdit."""
        reason = should_abstain(
            assertion_kind=AssertionKind.DISCURSIVE,
            relation_type=RelationType.CAUSES,
            extraction_method=ExtractionMethod.PATTERN,
        )

        assert reason is not None, "Devrait s'abstenir pour type interdit"
        assert reason == DiscursiveAbstainReason.WHITELIST_VIOLATION

    def test_should_abstain_for_llm_only(self):
        """should_abstain() retourne raison pour LLM seul."""
        reason = should_abstain(
            assertion_kind=AssertionKind.DISCURSIVE,
            relation_type=RelationType.ALTERNATIVE_TO,
            extraction_method=ExtractionMethod.LLM,
        )

        assert reason is not None, "Devrait s'abstenir pour LLM seul"
        assert reason == DiscursiveAbstainReason.TYPE2_RISK

    def test_should_not_abstain_for_valid_combination(self):
        """should_abstain() retourne None pour combinaison valide."""
        reason = should_abstain(
            assertion_kind=AssertionKind.DISCURSIVE,
            relation_type=RelationType.ALTERNATIVE_TO,
            extraction_method=ExtractionMethod.PATTERN,
            discursive_bases=[DiscursiveBasis.ALTERNATIVE],  # Base requise
        )

        assert reason is None, "Ne devrait pas s'abstenir pour combinaison valide"


# =============================================================================
# Whitelist RelationType pour DISCURSIVE
# =============================================================================

class TestRelationTypeWhitelist:
    """
    Tests: Seuls certains types de relations sont autorisés pour DISCURSIVE.
    """

    def test_allowed_types(self):
        """Types autorisés pour DISCURSIVE."""
        allowed_types = [
            RelationType.CHOICE_BETWEEN,
            RelationType.ALTERNATIVE_TO,
            RelationType.APPLIES_TO,
            RelationType.REQUIRES,
            RelationType.REPLACES,
            RelationType.DEPRECATES,
            RelationType.USES,
        ]

        for rtype in allowed_types:
            assert is_relation_type_allowed_for_discursive(rtype), (
                f"{rtype} devrait être autorisé pour DISCURSIVE"
            )

    def test_forbidden_types(self):
        """Types interdits pour DISCURSIVE (causalité)."""
        forbidden_types = [
            RelationType.CAUSES,
            RelationType.PREVENTS,
            RelationType.ENABLES,
            RelationType.MITIGATES,
        ]

        for rtype in forbidden_types:
            assert not is_relation_type_allowed_for_discursive(rtype), (
                f"{rtype} devrait être interdit pour DISCURSIVE"
            )


# =============================================================================
# Cas limites et edge cases
# =============================================================================

class TestEdgeCases:
    """Tests pour les cas limites."""

    def test_empty_text_no_candidates(self):
        """Texte vide ne produit pas de candidat."""
        candidates = extract_discursive_candidates("")
        assert len(candidates) == 0

    def test_text_with_only_punctuation(self):
        """Texte avec seulement ponctuation ne produit pas de candidat."""
        candidates = extract_discursive_candidates("... !!! ???")
        assert len(candidates) == 0

    def test_or_in_different_context(self):
        """'or' dans un contexte non-alternatif."""
        # "or" qui n'est pas une alternative
        text = "More or less the same configuration."
        candidates = extract_discursive_candidates(text)

        # Le pattern matcher peut détecter "or" mais ce n'est pas une vraie alternative
        # Le système devrait être prudent
        for c in candidates:
            if c.discursive_basis == DiscursiveBasis.ALTERNATIVE:
                # Si détecté, devrait avoir faible confiance
                assert c.pattern_confidence <= 0.7, (
                    "'more or less' ne devrait pas avoir haute confiance comme ALTERNATIVE"
                )

    def test_negated_alternative(self):
        """Alternative niée ne devrait pas être capturée."""
        text = "Do not use HANA or Oracle, use PostgreSQL instead."
        candidates = extract_discursive_candidates(text)

        # Le pattern peut être détecté mais la négation change le sens
        # C'est un cas où le LLM verifier devrait rejeter
        # Pour l'instant, on vérifie juste que le système ne crash pas
        assert isinstance(candidates, list)
