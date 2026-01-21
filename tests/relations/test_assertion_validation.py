"""
Tests pour le module assertion_validation.

Tests des validations:
- C3bis: ExtractionMethod pour DISCURSIVE
- C4: RelationType whitelist pour DISCURSIVE
- INV-SEP-01/02: Evidence locale obligatoire

Ref: doc/ongoing/ADR_DISCURSIVE_RELATIONS.md
Ref: doc/ongoing/ADR_SCOPE_VS_ASSERTION_SEPARATION.md

Author: Claude Code
Date: 2026-01-21
"""

import pytest
from unittest.mock import MagicMock

from knowbase.relations.types import (
    AssertionKind,
    DiscursiveBasis,
    DiscursiveAbstainReason,
    RelationType,
    ExtractionMethod,
    EvidenceBundle,
    EvidenceSpan,
    EvidenceSpanRole,
    CandidatePair,
    CandidatePairStatus,
)
from knowbase.relations.assertion_validation import (
    ValidationErrorCode,
    ValidationResult,
    validate_extraction_method_c3bis,
    validate_relation_type_c4,
    validate_evidence_inv_sep,
    validate_before_write,
    can_create_assertion,
    filter_valid_candidates,
)


# =============================================================================
# Tests C3bis: ExtractionMethod validation
# =============================================================================

class TestValidateExtractionMethodC3bis:
    """Tests pour la contrainte C3bis."""

    def test_explicit_allows_any_method(self):
        """EXPLICIT autorise toute méthode."""
        for method in ExtractionMethod:
            result = validate_extraction_method_c3bis(
                AssertionKind.EXPLICIT,
                method
            )
            assert result.is_valid, f"EXPLICIT should allow {method}"

    def test_discursive_allows_pattern(self):
        """DISCURSIVE autorise PATTERN."""
        result = validate_extraction_method_c3bis(
            AssertionKind.DISCURSIVE,
            ExtractionMethod.PATTERN
        )
        assert result.is_valid

    def test_discursive_allows_hybrid(self):
        """DISCURSIVE autorise HYBRID."""
        result = validate_extraction_method_c3bis(
            AssertionKind.DISCURSIVE,
            ExtractionMethod.HYBRID
        )
        assert result.is_valid

    def test_discursive_rejects_llm(self):
        """C3bis: DISCURSIVE + LLM seul est interdit."""
        result = validate_extraction_method_c3bis(
            AssertionKind.DISCURSIVE,
            ExtractionMethod.LLM
        )
        assert not result.is_valid
        assert result.error_code == ValidationErrorCode.DISCURSIVE_LLM_ONLY
        assert result.abstain_reason == DiscursiveAbstainReason.TYPE2_RISK


# =============================================================================
# Tests C4: RelationType whitelist validation
# =============================================================================

class TestValidateRelationTypeC4:
    """Tests pour la contrainte C4."""

    def test_explicit_allows_any_type(self):
        """EXPLICIT autorise tout type de relation."""
        for rtype in RelationType:
            result = validate_relation_type_c4(
                AssertionKind.EXPLICIT,
                rtype
            )
            assert result.is_valid, f"EXPLICIT should allow {rtype}"

    def test_discursive_allows_whitelisted_types(self):
        """DISCURSIVE autorise les types dans la whitelist."""
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
            result = validate_relation_type_c4(
                AssertionKind.DISCURSIVE,
                rtype
            )
            assert result.is_valid, f"DISCURSIVE should allow {rtype}"

    def test_discursive_rejects_causes(self):
        """C4: CAUSES est interdit pour DISCURSIVE (causalité)."""
        result = validate_relation_type_c4(
            AssertionKind.DISCURSIVE,
            RelationType.CAUSES
        )
        assert not result.is_valid
        assert result.error_code == ValidationErrorCode.RELATION_TYPE_FORBIDDEN
        assert result.abstain_reason == DiscursiveAbstainReason.WHITELIST_VIOLATION

    def test_discursive_rejects_prevents(self):
        """C4: PREVENTS est interdit pour DISCURSIVE (causalité)."""
        result = validate_relation_type_c4(
            AssertionKind.DISCURSIVE,
            RelationType.PREVENTS
        )
        assert not result.is_valid
        assert result.error_code == ValidationErrorCode.RELATION_TYPE_FORBIDDEN

    def test_discursive_rejects_enables(self):
        """C4: ENABLES est interdit pour DISCURSIVE."""
        result = validate_relation_type_c4(
            AssertionKind.DISCURSIVE,
            RelationType.ENABLES
        )
        assert not result.is_valid


# =============================================================================
# Tests INV-SEP: Evidence validation
# =============================================================================

class TestValidateEvidenceInvSep:
    """Tests pour les invariants INV-SEP-01 et INV-SEP-02."""

    def test_no_evidence_fails(self):
        """INV-SEP-02: Pas de preuve = échec."""
        result = validate_evidence_inv_sep(
            AssertionKind.EXPLICIT,
            evidence_bundle=None,
            evidence_text=None,
        )
        assert not result.is_valid
        assert result.error_code == ValidationErrorCode.NO_LOCAL_EVIDENCE

    def test_evidence_text_only_valid(self):
        """evidence_text seul est valide (avec avertissement)."""
        result = validate_evidence_inv_sep(
            AssertionKind.EXPLICIT,
            evidence_bundle=None,
            evidence_text="SAP HANA requires 256GB RAM minimum",
        )
        assert result.is_valid
        assert len(result.warnings) > 0  # Avertissement sur bundle manquant

    def test_evidence_text_too_short_fails(self):
        """INV-SEP-02: Texte trop court = rejet."""
        result = validate_evidence_inv_sep(
            AssertionKind.EXPLICIT,
            evidence_bundle=None,
            evidence_text="short",  # < 10 chars
        )
        assert not result.is_valid
        assert result.error_code == ValidationErrorCode.EVIDENCE_TOO_WEAK

    def test_discursive_without_bridge_fails(self):
        """INV-SEP-01: DISCURSIVE sans bridge = rejet."""
        bundle = EvidenceBundle(
            basis=DiscursiveBasis.SCOPE,
            spans=[
                EvidenceSpan(
                    doc_item_id="item1",
                    role=EvidenceSpanRole.SCOPE_SETTER,
                    text_excerpt="System Requirements section",
                ),
                EvidenceSpan(
                    doc_item_id="item2",
                    role=EvidenceSpanRole.MENTION,
                    text_excerpt="SAP HANA is mentioned",
                ),
            ],
            section_id="sec1",
            document_id="doc1",
            has_bridge=False,  # Pas de bridge
        )
        result = validate_evidence_inv_sep(
            AssertionKind.DISCURSIVE,
            evidence_bundle=bundle,
        )
        assert not result.is_valid
        assert result.error_code == ValidationErrorCode.NO_BRIDGE_FOR_DISCURSIVE

    def test_discursive_with_bridge_valid(self):
        """DISCURSIVE avec bridge est valide."""
        bundle = EvidenceBundle(
            basis=DiscursiveBasis.SCOPE,
            spans=[
                EvidenceSpan(
                    doc_item_id="item1",
                    role=EvidenceSpanRole.SCOPE_SETTER,
                    text_excerpt="SAP HANA or SAP BW can be used",
                ),
                EvidenceSpan(
                    doc_item_id="item2",
                    role=EvidenceSpanRole.MENTION,
                    text_excerpt="Choose between HANA and BW",
                ),
            ],
            section_id="sec1",
            document_id="doc1",
            has_bridge=True,  # Bridge trouvé
        )
        result = validate_evidence_inv_sep(
            AssertionKind.DISCURSIVE,
            evidence_bundle=bundle,
        )
        assert result.is_valid


# =============================================================================
# Tests validate_before_write (combined)
# =============================================================================

class TestValidateBeforeWrite:
    """Tests pour la validation combinée."""

    def test_valid_explicit_assertion(self):
        """Assertion EXPLICIT valide passe."""
        result = validate_before_write(
            assertion_kind=AssertionKind.EXPLICIT,
            relation_type=RelationType.REQUIRES,
            extraction_method=ExtractionMethod.LLM,
            evidence_text="SAP HANA requires 256GB RAM",
        )
        assert result.is_valid

    def test_valid_discursive_assertion(self):
        """Assertion DISCURSIVE valide passe."""
        result = validate_before_write(
            assertion_kind=AssertionKind.DISCURSIVE,
            relation_type=RelationType.ALTERNATIVE_TO,
            extraction_method=ExtractionMethod.PATTERN,
            evidence_text="Use SAP HANA or SAP BW for analytics",
            discursive_basis=[DiscursiveBasis.ALTERNATIVE],
        )
        assert result.is_valid

    def test_discursive_llm_fails(self):
        """DISCURSIVE + LLM échoue (C3bis)."""
        result = validate_before_write(
            assertion_kind=AssertionKind.DISCURSIVE,
            relation_type=RelationType.ALTERNATIVE_TO,
            extraction_method=ExtractionMethod.LLM,
            evidence_text="Use SAP HANA or SAP BW",
        )
        assert not result.is_valid
        assert result.error_code == ValidationErrorCode.DISCURSIVE_LLM_ONLY

    def test_discursive_causes_fails(self):
        """DISCURSIVE + CAUSES échoue (C4)."""
        result = validate_before_write(
            assertion_kind=AssertionKind.DISCURSIVE,
            relation_type=RelationType.CAUSES,
            extraction_method=ExtractionMethod.PATTERN,
            evidence_text="This causes that",
        )
        assert not result.is_valid
        assert result.error_code == ValidationErrorCode.RELATION_TYPE_FORBIDDEN

    def test_discursive_without_basis_warns(self):
        """DISCURSIVE sans basis génère un avertissement."""
        result = validate_before_write(
            assertion_kind=AssertionKind.DISCURSIVE,
            relation_type=RelationType.ALTERNATIVE_TO,
            extraction_method=ExtractionMethod.PATTERN,
            evidence_text="Use SAP HANA or SAP BW",
            discursive_basis=None,  # Pas de basis
        )
        assert result.is_valid  # Valide mais avec warning
        assert any("basis" in w.lower() for w in result.warnings)


# =============================================================================
# Tests can_create_assertion (CandidatePair)
# =============================================================================

class TestCanCreateAssertion:
    """Tests pour can_create_assertion."""

    def _make_bundle(self, has_bridge: bool = True, text_len: int = 30) -> EvidenceBundle:
        """Helper pour créer un EvidenceBundle."""
        return EvidenceBundle(
            basis=DiscursiveBasis.SCOPE,
            spans=[
                EvidenceSpan(
                    doc_item_id="item1",
                    role=EvidenceSpanRole.SCOPE_SETTER,
                    text_excerpt="X" * text_len,
                ),
                EvidenceSpan(
                    doc_item_id="item2",
                    role=EvidenceSpanRole.MENTION,
                    text_excerpt="Y" * text_len,
                ),
            ],
            section_id="sec1",
            document_id="doc1",
            has_bridge=has_bridge,
        )

    def test_valid_candidate_passes(self):
        """Candidat valide passe la validation."""
        candidate = CandidatePair(
            candidate_id="cand_001",
            pivot_concept_id="concept1",
            other_concept_id="concept2",
            evidence_bundle=self._make_bundle(has_bridge=True),
            section_id="sec1",
            document_id="doc1",
            assertion_kind=AssertionKind.DISCURSIVE,
            verified_relation_type=RelationType.ALTERNATIVE_TO,
            extraction_method=ExtractionMethod.PATTERN,
            discursive_basis=[DiscursiveBasis.ALTERNATIVE],
        )
        result = can_create_assertion(candidate)
        assert result.is_valid

    def test_candidate_without_bridge_fails_for_discursive(self):
        """Candidat DISCURSIVE sans bridge échoue."""
        candidate = CandidatePair(
            candidate_id="cand_002",
            pivot_concept_id="concept1",
            other_concept_id="concept2",
            evidence_bundle=self._make_bundle(has_bridge=False),
            section_id="sec1",
            document_id="doc1",
            assertion_kind=AssertionKind.DISCURSIVE,
            verified_relation_type=RelationType.ALTERNATIVE_TO,
            extraction_method=ExtractionMethod.PATTERN,
        )
        result = can_create_assertion(candidate)
        assert not result.is_valid
        assert result.error_code == ValidationErrorCode.NO_BRIDGE_FOR_DISCURSIVE

    def test_candidate_short_spans_fails_for_explicit(self):
        """Candidat EXPLICIT avec spans trop courts échoue."""
        candidate = CandidatePair(
            candidate_id="cand_003",
            pivot_concept_id="concept1",
            other_concept_id="concept2",
            evidence_bundle=self._make_bundle(has_bridge=True, text_len=5),  # Trop court
            section_id="sec1",
            document_id="doc1",
            assertion_kind=AssertionKind.EXPLICIT,
            verified_relation_type=RelationType.REQUIRES,
            extraction_method=ExtractionMethod.LLM,
        )
        result = can_create_assertion(candidate)
        assert not result.is_valid
        assert result.error_code == ValidationErrorCode.NO_RELATION_IN_SPAN


# =============================================================================
# Tests filter_valid_candidates
# =============================================================================

class TestFilterValidCandidates:
    """Tests pour filter_valid_candidates."""

    def _make_valid_candidate(self, concept_id: str) -> CandidatePair:
        """Crée un candidat valide."""
        bundle = EvidenceBundle(
            basis=DiscursiveBasis.SCOPE,
            spans=[
                EvidenceSpan(
                    doc_item_id="item1",
                    role=EvidenceSpanRole.SCOPE_SETTER,
                    text_excerpt="This is a valid evidence span with sufficient text",
                ),
                EvidenceSpan(
                    doc_item_id="item2",
                    role=EvidenceSpanRole.MENTION,
                    text_excerpt="Another evidence span for the relation",
                ),
            ],
            section_id="sec1",
            document_id="doc1",
            has_bridge=True,
        )
        return CandidatePair(
            candidate_id=f"cand_{concept_id}",
            pivot_concept_id=concept_id,
            other_concept_id=f"{concept_id}_obj",
            evidence_bundle=bundle,
            section_id="sec1",
            document_id="doc1",
            assertion_kind=AssertionKind.DISCURSIVE,
            verified_relation_type=RelationType.ALTERNATIVE_TO,
            extraction_method=ExtractionMethod.PATTERN,
            discursive_basis=[DiscursiveBasis.ALTERNATIVE],
        )

    def _make_invalid_candidate(self, concept_id: str) -> CandidatePair:
        """Crée un candidat invalide (sans bridge)."""
        bundle = EvidenceBundle(
            basis=DiscursiveBasis.SCOPE,
            spans=[
                EvidenceSpan(
                    doc_item_id="item1",
                    role=EvidenceSpanRole.SCOPE_SETTER,
                    text_excerpt="Evidence without bridge",
                ),
            ],
            section_id="sec1",
            document_id="doc1",
            has_bridge=False,  # Pas de bridge
        )
        return CandidatePair(
            candidate_id=f"cand_{concept_id}",
            pivot_concept_id=concept_id,
            other_concept_id=f"{concept_id}_obj",
            evidence_bundle=bundle,
            section_id="sec1",
            document_id="doc1",
            assertion_kind=AssertionKind.DISCURSIVE,
            verified_relation_type=RelationType.ALTERNATIVE_TO,
            extraction_method=ExtractionMethod.PATTERN,
        )

    def test_filters_invalid_candidates(self):
        """Filtre correctement les candidats invalides."""
        candidates = [
            self._make_valid_candidate("c1"),
            self._make_invalid_candidate("c2"),
            self._make_valid_candidate("c3"),
            self._make_invalid_candidate("c4"),
        ]

        valid = filter_valid_candidates(candidates)

        assert len(valid) == 2
        assert all(c.pivot_concept_id in ["c1", "c3"] for c in valid)

    def test_updates_rejected_status(self):
        """Met à jour le statut des candidats rejetés."""
        invalid = self._make_invalid_candidate("c1")
        candidates = [invalid]

        filter_valid_candidates(candidates)

        assert invalid.status == CandidatePairStatus.REJECTED
        assert invalid.rejection_reason is not None
