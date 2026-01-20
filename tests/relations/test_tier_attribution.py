# Tests ADR Relations Discursivement Déterminées - Tier Attribution
#
# Valide les règles d'attribution du DefensibilityTier selon l'ADR.
# Ref: doc/ongoing/ADR_DISCURSIVE_RELATIONS.md

import pytest
from knowbase.relations.types import (
    AssertionKind,
    DiscursiveBasis,
    DiscursiveAbstainReason,
    DefensibilityTier,
    SemanticGrade,
    RelationType,
    ExtractionMethod,
)
from knowbase.relations.tier_attribution import (
    # Whitelists
    DISCURSIVE_ALLOWED_RELATION_TYPES,
    DISCURSIVE_FORBIDDEN_RELATION_TYPES,
    DISCURSIVE_ALLOWED_EXTRACTION_METHODS,
    # Bases
    STRONG_DETERMINISTIC_BASES,
    WEAK_DETERMINISTIC_BASES,
    # Fonctions
    is_relation_type_allowed_for_discursive,
    is_extraction_method_allowed_for_discursive,
    has_strong_deterministic_basis,
    compute_tier_for_discursive,
    compute_defensibility_tier,
    validate_discursive_assertion,
    should_abstain,
    TierAttributionResult,
)


# =============================================================================
# Tests des Whitelists (Contrainte C4)
# =============================================================================

class TestWhitelistRelationType:
    """Tests pour la whitelist RelationType DISCURSIVE."""

    def test_allowed_types_are_in_whitelist(self):
        """Les types autorisés doivent être dans la whitelist."""
        allowed = [
            RelationType.ALTERNATIVE_TO,
            RelationType.APPLIES_TO,
            RelationType.REQUIRES,
            RelationType.REPLACES,
            RelationType.DEPRECATES,
        ]
        for rt in allowed:
            assert rt in DISCURSIVE_ALLOWED_RELATION_TYPES, f"{rt} devrait être autorisé"

    def test_forbidden_types_are_in_forbidden_list(self):
        """Les types interdits doivent être dans la liste d'interdiction."""
        forbidden = [
            RelationType.CAUSES,
            RelationType.PREVENTS,
            RelationType.MITIGATES,
            RelationType.ENABLES,
            RelationType.DEFINES,
        ]
        for rt in forbidden:
            assert rt in DISCURSIVE_FORBIDDEN_RELATION_TYPES, f"{rt} devrait être interdit"

    def test_no_overlap_between_allowed_and_forbidden(self):
        """Pas de chevauchement entre autorisés et interdits."""
        overlap = DISCURSIVE_ALLOWED_RELATION_TYPES & DISCURSIVE_FORBIDDEN_RELATION_TYPES
        assert len(overlap) == 0, f"Chevauchement détecté: {overlap}"

    def test_is_relation_type_allowed_for_discursive(self):
        """Test de la fonction is_relation_type_allowed_for_discursive."""
        # Autorisés
        assert is_relation_type_allowed_for_discursive(RelationType.ALTERNATIVE_TO) is True
        assert is_relation_type_allowed_for_discursive(RelationType.APPLIES_TO) is True
        assert is_relation_type_allowed_for_discursive(RelationType.REQUIRES) is True

        # Interdits
        assert is_relation_type_allowed_for_discursive(RelationType.CAUSES) is False
        assert is_relation_type_allowed_for_discursive(RelationType.PREVENTS) is False
        assert is_relation_type_allowed_for_discursive(RelationType.ENABLES) is False


class TestWhitelistExtractionMethod:
    """Tests pour la whitelist ExtractionMethod (Contrainte C3bis)."""

    def test_pattern_is_allowed(self):
        """PATTERN doit être autorisé pour DISCURSIVE."""
        assert ExtractionMethod.PATTERN in DISCURSIVE_ALLOWED_EXTRACTION_METHODS

    def test_hybrid_is_allowed(self):
        """HYBRID doit être autorisé pour DISCURSIVE."""
        assert ExtractionMethod.HYBRID in DISCURSIVE_ALLOWED_EXTRACTION_METHODS

    def test_llm_alone_is_not_allowed(self):
        """LLM seul ne doit PAS être autorisé pour DISCURSIVE."""
        assert ExtractionMethod.LLM not in DISCURSIVE_ALLOWED_EXTRACTION_METHODS

    def test_inferred_is_not_allowed(self):
        """INFERRED ne doit PAS être autorisé pour DISCURSIVE."""
        assert ExtractionMethod.INFERRED not in DISCURSIVE_ALLOWED_EXTRACTION_METHODS

    def test_is_extraction_method_allowed(self):
        """Test de la fonction is_extraction_method_allowed_for_discursive."""
        assert is_extraction_method_allowed_for_discursive(ExtractionMethod.PATTERN) is True
        assert is_extraction_method_allowed_for_discursive(ExtractionMethod.HYBRID) is True
        assert is_extraction_method_allowed_for_discursive(ExtractionMethod.LLM) is False
        assert is_extraction_method_allowed_for_discursive(ExtractionMethod.INFERRED) is False


# =============================================================================
# Tests des Bases Déterministes
# =============================================================================

class TestDeterministicBases:
    """Tests pour les bases déterministes fortes vs faibles."""

    def test_strong_bases(self):
        """Vérifier les bases fortes."""
        assert DiscursiveBasis.ALTERNATIVE in STRONG_DETERMINISTIC_BASES
        assert DiscursiveBasis.DEFAULT in STRONG_DETERMINISTIC_BASES
        assert DiscursiveBasis.EXCEPTION in STRONG_DETERMINISTIC_BASES

    def test_weak_bases(self):
        """Vérifier les bases faibles."""
        assert DiscursiveBasis.SCOPE in WEAK_DETERMINISTIC_BASES
        assert DiscursiveBasis.COREF in WEAK_DETERMINISTIC_BASES
        assert DiscursiveBasis.ENUMERATION in WEAK_DETERMINISTIC_BASES

    def test_no_overlap(self):
        """Pas de chevauchement entre fortes et faibles."""
        overlap = STRONG_DETERMINISTIC_BASES & WEAK_DETERMINISTIC_BASES
        assert len(overlap) == 0

    def test_has_strong_deterministic_basis_true(self):
        """has_strong_deterministic_basis retourne True si base forte présente."""
        assert has_strong_deterministic_basis([DiscursiveBasis.ALTERNATIVE]) is True
        assert has_strong_deterministic_basis([DiscursiveBasis.DEFAULT]) is True
        assert has_strong_deterministic_basis([DiscursiveBasis.EXCEPTION]) is True
        # Mixte
        assert has_strong_deterministic_basis([DiscursiveBasis.COREF, DiscursiveBasis.ALTERNATIVE]) is True

    def test_has_strong_deterministic_basis_false(self):
        """has_strong_deterministic_basis retourne False si que bases faibles."""
        assert has_strong_deterministic_basis([DiscursiveBasis.SCOPE]) is False
        assert has_strong_deterministic_basis([DiscursiveBasis.COREF]) is False
        assert has_strong_deterministic_basis([DiscursiveBasis.SCOPE, DiscursiveBasis.COREF]) is False

    def test_has_strong_deterministic_basis_empty(self):
        """has_strong_deterministic_basis retourne False si liste vide."""
        assert has_strong_deterministic_basis([]) is False


# =============================================================================
# Tests compute_tier_for_discursive (Matrice basis → tier)
# =============================================================================

class TestComputeTierForDiscursive:
    """Tests pour compute_tier_for_discursive (assertions DISCURSIVE)."""

    # --- Cas STRICT avec bases fortes ---

    def test_alternative_with_marker_is_strict(self):
        """ALTERNATIVE avec marqueur → STRICT."""
        result = compute_tier_for_discursive(
            bases=[DiscursiveBasis.ALTERNATIVE],
            relation_type=RelationType.ALTERNATIVE_TO,
            extraction_method=ExtractionMethod.PATTERN,
            span_count=1,
            has_marker_in_text=True,
        )
        assert result.tier == DefensibilityTier.STRICT
        assert "ALTERNATIVE" in result.reason

    def test_default_with_marker_is_strict(self):
        """DEFAULT avec marqueur → STRICT."""
        result = compute_tier_for_discursive(
            bases=[DiscursiveBasis.DEFAULT],
            relation_type=RelationType.APPLIES_TO,
            extraction_method=ExtractionMethod.HYBRID,
            span_count=1,
            has_marker_in_text=True,
        )
        assert result.tier == DefensibilityTier.STRICT

    def test_exception_with_marker_is_strict(self):
        """EXCEPTION avec marqueur → STRICT."""
        result = compute_tier_for_discursive(
            bases=[DiscursiveBasis.EXCEPTION],
            relation_type=RelationType.APPLIES_TO,
            extraction_method=ExtractionMethod.PATTERN,
            span_count=1,
            has_marker_in_text=True,
        )
        assert result.tier == DefensibilityTier.STRICT

    # --- Cas EXTENDED avec bases fortes (marqueur absent) ---

    def test_alternative_without_marker_is_extended(self):
        """ALTERNATIVE sans marqueur → EXTENDED."""
        result = compute_tier_for_discursive(
            bases=[DiscursiveBasis.ALTERNATIVE],
            relation_type=RelationType.ALTERNATIVE_TO,
            extraction_method=ExtractionMethod.PATTERN,
            span_count=1,
            has_marker_in_text=False,
        )
        assert result.tier == DefensibilityTier.EXTENDED
        assert result.abstain_reason == DiscursiveAbstainReason.WEAK_BUNDLE

    # --- Cas STRICT avec bases faibles (≥ 2 spans) ---

    def test_scope_with_2_spans_is_strict(self):
        """SCOPE avec ≥ 2 spans → STRICT."""
        result = compute_tier_for_discursive(
            bases=[DiscursiveBasis.SCOPE],
            relation_type=RelationType.APPLIES_TO,
            extraction_method=ExtractionMethod.HYBRID,
            span_count=2,
            has_marker_in_text=True,
        )
        assert result.tier == DefensibilityTier.STRICT
        assert "2 spans" in result.reason

    def test_coref_with_3_spans_is_strict(self):
        """COREF avec 3 spans → STRICT."""
        result = compute_tier_for_discursive(
            bases=[DiscursiveBasis.COREF],
            relation_type=RelationType.REQUIRES,
            extraction_method=ExtractionMethod.PATTERN,
            span_count=3,
            has_marker_in_text=True,
        )
        assert result.tier == DefensibilityTier.STRICT

    # --- Cas EXTENDED avec bases faibles (< 2 spans) ---

    def test_scope_with_1_span_is_extended(self):
        """SCOPE avec 1 span → EXTENDED."""
        result = compute_tier_for_discursive(
            bases=[DiscursiveBasis.SCOPE],
            relation_type=RelationType.APPLIES_TO,
            extraction_method=ExtractionMethod.HYBRID,
            span_count=1,
            has_marker_in_text=True,
        )
        assert result.tier == DefensibilityTier.EXTENDED
        assert "< 2 requis" in result.reason

    def test_coref_with_1_span_is_extended(self):
        """COREF avec 1 span → EXTENDED."""
        result = compute_tier_for_discursive(
            bases=[DiscursiveBasis.COREF],
            relation_type=RelationType.REQUIRES,
            extraction_method=ExtractionMethod.PATTERN,
            span_count=1,
            has_marker_in_text=True,
        )
        assert result.tier == DefensibilityTier.EXTENDED

    # --- Cas EXTENDED pour violations de contraintes ---

    def test_llm_extraction_method_is_extended(self):
        """LLM seul → EXTENDED (violation C3bis)."""
        result = compute_tier_for_discursive(
            bases=[DiscursiveBasis.ALTERNATIVE],
            relation_type=RelationType.ALTERNATIVE_TO,
            extraction_method=ExtractionMethod.LLM,  # Interdit
            span_count=1,
            has_marker_in_text=True,
        )
        assert result.tier == DefensibilityTier.EXTENDED
        assert "C3bis" in result.reason
        assert result.abstain_reason == DiscursiveAbstainReason.TYPE2_RISK

    def test_forbidden_relation_type_is_extended(self):
        """RelationType interdit → EXTENDED (violation C4)."""
        result = compute_tier_for_discursive(
            bases=[DiscursiveBasis.ALTERNATIVE],
            relation_type=RelationType.CAUSES,  # Interdit
            extraction_method=ExtractionMethod.PATTERN,
            span_count=1,
            has_marker_in_text=True,
        )
        assert result.tier == DefensibilityTier.EXTENDED
        assert "C4" in result.reason
        assert result.abstain_reason == DiscursiveAbstainReason.WHITELIST_VIOLATION

    def test_no_basis_is_extended(self):
        """Pas de basis → EXTENDED."""
        result = compute_tier_for_discursive(
            bases=[],
            relation_type=RelationType.ALTERNATIVE_TO,
            extraction_method=ExtractionMethod.PATTERN,
            span_count=1,
            has_marker_in_text=True,
        )
        assert result.tier == DefensibilityTier.EXTENDED
        assert result.abstain_reason == DiscursiveAbstainReason.WEAK_BUNDLE


# =============================================================================
# Tests compute_defensibility_tier (Règle principale)
# =============================================================================

class TestComputeDefensibilityTier:
    """Tests pour compute_defensibility_tier (règle par SemanticGrade)."""

    # --- EXPLICIT → STRICT ---

    def test_explicit_is_always_strict(self):
        """EXPLICIT → STRICT (toujours)."""
        result = compute_defensibility_tier(semantic_grade=SemanticGrade.EXPLICIT)
        assert result.tier == DefensibilityTier.STRICT
        assert "EXPLICIT" in result.reason

    # --- MIXED → STRICT ---

    def test_mixed_is_always_strict(self):
        """MIXED → STRICT (au moins une preuve EXPLICIT)."""
        result = compute_defensibility_tier(semantic_grade=SemanticGrade.MIXED)
        assert result.tier == DefensibilityTier.STRICT
        assert "MIXED" in result.reason

    # --- DISCURSIVE → dépend de la matrice ---

    def test_discursive_with_strong_basis_is_strict(self):
        """DISCURSIVE avec base forte → STRICT."""
        result = compute_defensibility_tier(
            semantic_grade=SemanticGrade.DISCURSIVE,
            discursive_bases=[DiscursiveBasis.ALTERNATIVE],
            relation_type=RelationType.ALTERNATIVE_TO,
            extraction_method=ExtractionMethod.PATTERN,
            span_count=1,
            has_marker_in_text=True,
        )
        assert result.tier == DefensibilityTier.STRICT

    def test_discursive_with_weak_basis_and_enough_spans_is_strict(self):
        """DISCURSIVE avec base faible + ≥ 2 spans → STRICT."""
        result = compute_defensibility_tier(
            semantic_grade=SemanticGrade.DISCURSIVE,
            discursive_bases=[DiscursiveBasis.COREF],
            relation_type=RelationType.REQUIRES,
            extraction_method=ExtractionMethod.HYBRID,
            span_count=2,
            has_marker_in_text=True,
        )
        assert result.tier == DefensibilityTier.STRICT

    def test_discursive_with_weak_basis_and_few_spans_is_extended(self):
        """DISCURSIVE avec base faible + 1 span → EXTENDED."""
        result = compute_defensibility_tier(
            semantic_grade=SemanticGrade.DISCURSIVE,
            discursive_bases=[DiscursiveBasis.SCOPE],
            relation_type=RelationType.APPLIES_TO,
            extraction_method=ExtractionMethod.PATTERN,
            span_count=1,
            has_marker_in_text=True,
        )
        assert result.tier == DefensibilityTier.EXTENDED


# =============================================================================
# Tests validate_discursive_assertion et should_abstain
# =============================================================================

class TestValidation:
    """Tests pour les fonctions de validation."""

    def test_validate_valid_discursive(self):
        """Assertion DISCURSIVE valide → None."""
        reason = validate_discursive_assertion(
            relation_type=RelationType.ALTERNATIVE_TO,
            extraction_method=ExtractionMethod.PATTERN,
            discursive_bases=[DiscursiveBasis.ALTERNATIVE],
        )
        assert reason is None

    def test_validate_llm_alone_fails(self):
        """LLM seul → TYPE2_RISK."""
        reason = validate_discursive_assertion(
            relation_type=RelationType.ALTERNATIVE_TO,
            extraction_method=ExtractionMethod.LLM,
            discursive_bases=[DiscursiveBasis.ALTERNATIVE],
        )
        assert reason == DiscursiveAbstainReason.TYPE2_RISK

    def test_validate_forbidden_type_fails(self):
        """RelationType interdit → WHITELIST_VIOLATION."""
        reason = validate_discursive_assertion(
            relation_type=RelationType.CAUSES,
            extraction_method=ExtractionMethod.PATTERN,
            discursive_bases=[DiscursiveBasis.ALTERNATIVE],
        )
        assert reason == DiscursiveAbstainReason.WHITELIST_VIOLATION

    def test_validate_no_basis_fails(self):
        """Pas de basis → WEAK_BUNDLE."""
        reason = validate_discursive_assertion(
            relation_type=RelationType.ALTERNATIVE_TO,
            extraction_method=ExtractionMethod.PATTERN,
            discursive_bases=[],
        )
        assert reason == DiscursiveAbstainReason.WEAK_BUNDLE

    def test_should_abstain_explicit_never(self):
        """EXPLICIT ne doit jamais abstain."""
        reason = should_abstain(
            assertion_kind=AssertionKind.EXPLICIT,
            relation_type=RelationType.CAUSES,  # Même interdit pour DISCURSIVE
            extraction_method=ExtractionMethod.LLM,
        )
        assert reason is None

    def test_should_abstain_discursive_valid(self):
        """DISCURSIVE valide ne doit pas abstain."""
        reason = should_abstain(
            assertion_kind=AssertionKind.DISCURSIVE,
            relation_type=RelationType.ALTERNATIVE_TO,
            extraction_method=ExtractionMethod.PATTERN,
            discursive_bases=[DiscursiveBasis.ALTERNATIVE],
        )
        assert reason is None

    def test_should_abstain_discursive_invalid(self):
        """DISCURSIVE invalide doit abstain."""
        reason = should_abstain(
            assertion_kind=AssertionKind.DISCURSIVE,
            relation_type=RelationType.CAUSES,
            extraction_method=ExtractionMethod.PATTERN,
            discursive_bases=[DiscursiveBasis.ALTERNATIVE],
        )
        assert reason == DiscursiveAbstainReason.WHITELIST_VIOLATION


# =============================================================================
# Tests d'intégration (cas réels POC)
# =============================================================================

class TestPOCCases:
    """Tests basés sur les cas du POC v3/v4 (0% FP Type 2)."""

    def test_rto_alternative_case(self):
        """
        Cas POC: 'RTO is 12h or 4h' → ALTERNATIVE_TO
        Doit être STRICT car base forte ALTERNATIVE avec marqueur 'or'.
        """
        result = compute_defensibility_tier(
            semantic_grade=SemanticGrade.DISCURSIVE,
            discursive_bases=[DiscursiveBasis.ALTERNATIVE],
            relation_type=RelationType.ALTERNATIVE_TO,
            extraction_method=ExtractionMethod.PATTERN,
            span_count=1,
            has_marker_in_text=True,  # "or" présent
        )
        assert result.tier == DefensibilityTier.STRICT

    def test_by_default_case(self):
        """
        Cas POC: 'By default, compression is enabled'
        Doit être STRICT car base forte DEFAULT avec marqueur 'by default'.
        """
        result = compute_defensibility_tier(
            semantic_grade=SemanticGrade.DISCURSIVE,
            discursive_bases=[DiscursiveBasis.DEFAULT],
            relation_type=RelationType.APPLIES_TO,
            extraction_method=ExtractionMethod.HYBRID,
            span_count=1,
            has_marker_in_text=True,  # "by default" présent
        )
        assert result.tier == DefensibilityTier.STRICT

    def test_unless_exception_case(self):
        """
        Cas POC: 'Unless specified otherwise, TLS 1.3 is required'
        Doit être STRICT car base forte EXCEPTION avec marqueur 'unless'.
        """
        result = compute_defensibility_tier(
            semantic_grade=SemanticGrade.DISCURSIVE,
            discursive_bases=[DiscursiveBasis.EXCEPTION],
            relation_type=RelationType.REQUIRES,
            extraction_method=ExtractionMethod.PATTERN,
            span_count=1,
            has_marker_in_text=True,  # "unless" présent
        )
        assert result.tier == DefensibilityTier.STRICT

    def test_causal_relation_rejected(self):
        """
        Cas POC Type 2: 'A causes B' doit être rejeté pour DISCURSIVE.
        La causalité est du raisonnement monde, pas text-determined.
        """
        reason = should_abstain(
            assertion_kind=AssertionKind.DISCURSIVE,
            relation_type=RelationType.CAUSES,
            extraction_method=ExtractionMethod.PATTERN,
            discursive_bases=[DiscursiveBasis.SCOPE],
        )
        assert reason == DiscursiveAbstainReason.WHITELIST_VIOLATION

    def test_coref_with_multi_span_case(self):
        """
        Cas POC: Coréférence avec 2 spans (scope + référence).
        Doit être STRICT car ≥ 2 spans.
        """
        result = compute_defensibility_tier(
            semantic_grade=SemanticGrade.DISCURSIVE,
            discursive_bases=[DiscursiveBasis.COREF, DiscursiveBasis.SCOPE],
            relation_type=RelationType.APPLIES_TO,
            extraction_method=ExtractionMethod.HYBRID,
            span_count=2,
            has_marker_in_text=True,
        )
        assert result.tier == DefensibilityTier.STRICT


# =============================================================================
# Tests TierAttributionResult
# =============================================================================

class TestTierAttributionResult:
    """Tests pour la classe TierAttributionResult."""

    def test_repr(self):
        """Test __repr__."""
        result = TierAttributionResult(
            tier=DefensibilityTier.STRICT,
            reason="Test reason",
        )
        repr_str = repr(result)
        assert "STRICT" in repr_str
        assert "Test reason" in repr_str

    def test_with_abstain_reason(self):
        """Test avec abstain_reason."""
        result = TierAttributionResult(
            tier=DefensibilityTier.EXTENDED,
            reason="Violation C4",
            abstain_reason=DiscursiveAbstainReason.WHITELIST_VIOLATION,
        )
        assert result.tier == DefensibilityTier.EXTENDED
        assert result.abstain_reason == DiscursiveAbstainReason.WHITELIST_VIOLATION
