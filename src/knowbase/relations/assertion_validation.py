"""
Validation des assertions avant écriture.

Ce module implémente les validations requises par les ADR:
- C3bis: DISCURSIVE + LLM seul est interdit
- C4: Whitelist RelationType pour DISCURSIVE
- INV-SEP-01: No Scope-to-Assertion Promotion sans preuve locale
- INV-SEP-02: Assertion requires local evidence

Ref: doc/ongoing/ADR_DISCURSIVE_RELATIONS.md
Ref: doc/ongoing/ADR_SCOPE_VS_ASSERTION_SEPARATION.md

Author: Claude Code
Date: 2026-01-21
"""

import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import List, Optional

from .types import (
    AssertionKind,
    DiscursiveBasis,
    DiscursiveAbstainReason,
    RelationType,
    ExtractionMethod,
    EvidenceBundle,
    EvidenceSpan,
    CandidatePair,
    CandidatePairStatus,
)
from .tier_attribution import (
    is_relation_type_allowed_for_discursive,
    is_extraction_method_allowed_for_discursive,
    DISCURSIVE_ALLOWED_RELATION_TYPES,
    DISCURSIVE_FORBIDDEN_RELATION_TYPES,
)

logger = logging.getLogger(__name__)


class ValidationErrorCode(str, Enum):
    """Codes d'erreur de validation."""

    # C3bis violations
    DISCURSIVE_LLM_ONLY = "DISCURSIVE_LLM_ONLY"

    # C4 violations
    RELATION_TYPE_FORBIDDEN = "RELATION_TYPE_FORBIDDEN"
    RELATION_TYPE_NOT_ALLOWED = "RELATION_TYPE_NOT_ALLOWED"

    # INV-SEP-01 violations
    SCOPE_TO_ASSERTION_PROMOTION = "SCOPE_TO_ASSERTION_PROMOTION"

    # INV-SEP-02 violations
    NO_LOCAL_EVIDENCE = "NO_LOCAL_EVIDENCE"
    EVIDENCE_TOO_WEAK = "EVIDENCE_TOO_WEAK"
    NO_BRIDGE_FOR_DISCURSIVE = "NO_BRIDGE_FOR_DISCURSIVE"
    NO_RELATION_IN_SPAN = "NO_RELATION_IN_SPAN"

    # General
    MISSING_REQUIRED_FIELD = "MISSING_REQUIRED_FIELD"


@dataclass
class ValidationResult:
    """Résultat de validation d'une assertion."""

    is_valid: bool
    error_code: Optional[ValidationErrorCode] = None
    error_message: Optional[str] = None
    warnings: List[str] = field(default_factory=list)

    # Pour les rejets, raison d'abstention ADR
    abstain_reason: Optional[DiscursiveAbstainReason] = None


# =============================================================================
# C3bis: ExtractionMethod validation
# =============================================================================

def validate_extraction_method_c3bis(
    assertion_kind: AssertionKind,
    extraction_method: ExtractionMethod,
) -> ValidationResult:
    """
    Valide la contrainte C3bis: DISCURSIVE + LLM seul est interdit.

    Args:
        assertion_kind: Type d'assertion (EXPLICIT ou DISCURSIVE)
        extraction_method: Méthode d'extraction utilisée

    Returns:
        ValidationResult
    """
    # C3bis ne s'applique qu'aux assertions DISCURSIVE
    if assertion_kind != AssertionKind.DISCURSIVE:
        return ValidationResult(is_valid=True)

    # DISCURSIVE ne peut pas être produit par LLM seul
    if not is_extraction_method_allowed_for_discursive(extraction_method):
        return ValidationResult(
            is_valid=False,
            error_code=ValidationErrorCode.DISCURSIVE_LLM_ONLY,
            error_message=(
                f"C3bis violation: DISCURSIVE assertions cannot use "
                f"ExtractionMethod={extraction_method.value}. "
                f"Allowed methods: PATTERN, HYBRID."
            ),
            abstain_reason=DiscursiveAbstainReason.TYPE2_RISK,
        )

    return ValidationResult(is_valid=True)


# =============================================================================
# C4: RelationType whitelist validation
# =============================================================================

def validate_relation_type_c4(
    assertion_kind: AssertionKind,
    relation_type: RelationType,
) -> ValidationResult:
    """
    Valide la contrainte C4: Whitelist RelationType pour DISCURSIVE.

    Args:
        assertion_kind: Type d'assertion (EXPLICIT ou DISCURSIVE)
        relation_type: Type de relation

    Returns:
        ValidationResult
    """
    # C4 ne s'applique qu'aux assertions DISCURSIVE
    if assertion_kind != AssertionKind.DISCURSIVE:
        return ValidationResult(is_valid=True)

    # Vérifier si interdit explicitement
    if relation_type in DISCURSIVE_FORBIDDEN_RELATION_TYPES:
        return ValidationResult(
            is_valid=False,
            error_code=ValidationErrorCode.RELATION_TYPE_FORBIDDEN,
            error_message=(
                f"C4 violation: RelationType={relation_type.value} is explicitly "
                f"forbidden for DISCURSIVE assertions (causal reasoning)."
            ),
            abstain_reason=DiscursiveAbstainReason.WHITELIST_VIOLATION,
        )

    # Vérifier si dans la whitelist
    if not is_relation_type_allowed_for_discursive(relation_type):
        return ValidationResult(
            is_valid=False,
            error_code=ValidationErrorCode.RELATION_TYPE_NOT_ALLOWED,
            error_message=(
                f"C4 violation: RelationType={relation_type.value} is not in "
                f"the DISCURSIVE whitelist. Allowed types: "
                f"{[rt.value for rt in DISCURSIVE_ALLOWED_RELATION_TYPES]}"
            ),
            abstain_reason=DiscursiveAbstainReason.WHITELIST_VIOLATION,
        )

    return ValidationResult(is_valid=True)


# =============================================================================
# INV-SEP-01 & INV-SEP-02: Evidence validation
# =============================================================================

def validate_evidence_inv_sep(
    assertion_kind: AssertionKind,
    evidence_bundle: Optional[EvidenceBundle],
    evidence_text: Optional[str] = None,
) -> ValidationResult:
    """
    Valide les invariants INV-SEP-01 et INV-SEP-02.

    INV-SEP-01: No Scope-to-Assertion Promotion sans preuve locale
    INV-SEP-02: Assertion requires local evidence

    Args:
        assertion_kind: Type d'assertion
        evidence_bundle: Bundle de preuves (peut être None)
        evidence_text: Texte de preuve direct (fallback si pas de bundle)

    Returns:
        ValidationResult
    """
    warnings = []

    # Vérifier qu'on a au moins une preuve
    has_bundle = evidence_bundle is not None and bool(evidence_bundle.spans)
    has_text = evidence_text is not None and len(evidence_text.strip()) > 0

    if not has_bundle and not has_text:
        return ValidationResult(
            is_valid=False,
            error_code=ValidationErrorCode.NO_LOCAL_EVIDENCE,
            error_message=(
                "INV-SEP-02 violation: Assertion requires local evidence. "
                "No EvidenceBundle or evidence_text provided."
            ),
            abstain_reason=DiscursiveAbstainReason.WEAK_BUNDLE,
        )

    # Si on a un evidence_text mais pas de bundle, avertir
    if has_text and not has_bundle:
        warnings.append(
            "Evidence provided as text only, not as structured EvidenceBundle. "
            "Consider using EvidenceBundle for better traceability."
        )

    # Vérifier la qualité de l'evidence_text
    if has_text and len(evidence_text.strip()) < 10:
        return ValidationResult(
            is_valid=False,
            error_code=ValidationErrorCode.EVIDENCE_TOO_WEAK,
            error_message=(
                "INV-SEP-02 violation: Evidence text too short (<10 chars). "
                "This suggests scope metadata, not local textual evidence."
            ),
            abstain_reason=DiscursiveAbstainReason.WEAK_BUNDLE,
        )

    # Pour DISCURSIVE, vérifications supplémentaires sur le bundle
    if assertion_kind == AssertionKind.DISCURSIVE and has_bundle:
        bundle = evidence_bundle

        # Vérifier qu'il y a un bridge (co-présence locale)
        if not bundle.has_bridge:
            return ValidationResult(
                is_valid=False,
                error_code=ValidationErrorCode.NO_BRIDGE_FOR_DISCURSIVE,
                error_message=(
                    "INV-SEP-01 violation: DISCURSIVE assertions require a bridge "
                    "(local co-presence of concepts). This looks like scope promotion."
                ),
                abstain_reason=DiscursiveAbstainReason.WEAK_BUNDLE,
            )

    # Pour EXPLICIT, on fait confiance à l'evidence_text fourni
    # (le texte de preuve directe passé séparément)
    if assertion_kind == AssertionKind.EXPLICIT:
        if not has_text:
            warnings.append(
                "EXPLICIT assertion should have explicit evidence_text "
                "with the relation stated in the text."
            )

    return ValidationResult(
        is_valid=True,
        warnings=warnings,
    )


# =============================================================================
# Combined validation: validate_before_write
# =============================================================================

def validate_before_write(
    assertion_kind: AssertionKind,
    relation_type: Optional[RelationType],
    extraction_method: Optional[ExtractionMethod],
    evidence_bundle: Optional[EvidenceBundle] = None,
    evidence_text: Optional[str] = None,
    discursive_basis: Optional[List[DiscursiveBasis]] = None,
) -> ValidationResult:
    """
    Validation complète avant écriture d'une assertion.

    Combine toutes les validations:
    - C3bis: ExtractionMethod pour DISCURSIVE
    - C4: RelationType whitelist pour DISCURSIVE
    - INV-SEP-01/02: Evidence locale obligatoire

    Args:
        assertion_kind: Type d'assertion (EXPLICIT ou DISCURSIVE)
        relation_type: Type de relation
        extraction_method: Méthode d'extraction
        evidence_bundle: Bundle de preuves
        evidence_text: Texte de preuve (fallback)
        discursive_basis: Bases discursives (pour DISCURSIVE)

    Returns:
        ValidationResult combiné
    """
    all_warnings = []

    # Valeurs par défaut
    if relation_type is None:
        relation_type = RelationType.ASSOCIATED_WITH
    if extraction_method is None:
        extraction_method = ExtractionMethod.HYBRID

    # 1. C3bis: ExtractionMethod
    result = validate_extraction_method_c3bis(assertion_kind, extraction_method)
    if not result.is_valid:
        return result
    all_warnings.extend(result.warnings)

    # 2. C4: RelationType whitelist
    result = validate_relation_type_c4(assertion_kind, relation_type)
    if not result.is_valid:
        return result
    all_warnings.extend(result.warnings)

    # 3. INV-SEP-01/02: Evidence
    result = validate_evidence_inv_sep(
        assertion_kind,
        evidence_bundle,
        evidence_text,
    )
    if not result.is_valid:
        return result
    all_warnings.extend(result.warnings)

    # 4. Pour DISCURSIVE, vérifier qu'il y a au moins une basis
    if assertion_kind == AssertionKind.DISCURSIVE:
        if not discursive_basis:
            all_warnings.append(
                "DISCURSIVE assertion without discursive_basis. "
                "Consider specifying the linguistic basis (ALTERNATIVE, DEFAULT, etc.)."
            )

    return ValidationResult(
        is_valid=True,
        warnings=all_warnings,
    )


# =============================================================================
# can_create_assertion: Guard function for CandidatePair
# =============================================================================

def can_create_assertion(candidate: CandidatePair) -> ValidationResult:
    """
    Vérifie si un CandidatePair peut devenir une assertion.

    Implémente INV-SEP-01 et INV-SEP-02 comme garde-fou
    avant la création d'une RawAssertion.

    Args:
        candidate: CandidatePair à valider

    Returns:
        ValidationResult indiquant si l'assertion peut être créée
    """
    # Vérifier les champs requis
    if not candidate.pivot_concept_id or not candidate.other_concept_id:
        return ValidationResult(
            is_valid=False,
            error_code=ValidationErrorCode.MISSING_REQUIRED_FIELD,
            error_message="CandidatePair missing pivot_concept_id or other_concept_id",
        )

    # Récupérer le bundle
    bundle = candidate.evidence_bundle

    # Doit avoir au moins un span
    if bundle is None or not bundle.spans:
        return ValidationResult(
            is_valid=False,
            error_code=ValidationErrorCode.NO_LOCAL_EVIDENCE,
            error_message=(
                "INV-SEP-02 violation: CandidatePair has no evidence spans. "
                "Cannot create assertion without local textual evidence."
            ),
            abstain_reason=DiscursiveAbstainReason.WEAK_BUNDLE,
        )

    # Pour DISCURSIVE, doit avoir un bridge (co-présence locale)
    if candidate.assertion_kind == AssertionKind.DISCURSIVE:
        if not bundle.has_bridge:
            return ValidationResult(
                is_valid=False,
                error_code=ValidationErrorCode.NO_BRIDGE_FOR_DISCURSIVE,
                error_message=(
                    "INV-SEP-01 violation: DISCURSIVE candidate has no bridge. "
                    "Concepts must be co-present locally, not just in scope."
                ),
                abstain_reason=DiscursiveAbstainReason.WEAK_BUNDLE,
            )

    # Pour EXPLICIT, on vérifie que les spans ont du contenu significatif
    if candidate.assertion_kind == AssertionKind.EXPLICIT:
        # Vérifier que les spans ont du texte substantiel
        has_substantial_text = any(
            len(span.text_excerpt.strip()) >= 20 for span in bundle.spans
        )

        if not has_substantial_text:
            return ValidationResult(
                is_valid=False,
                error_code=ValidationErrorCode.NO_RELATION_IN_SPAN,
                error_message=(
                    "INV-SEP-02 violation: EXPLICIT candidate spans too short. "
                    "Need substantial textual evidence (>=20 chars)."
                ),
                abstain_reason=DiscursiveAbstainReason.WEAK_BUNDLE,
            )

    # Valider avec validate_before_write pour les contraintes C3bis et C4
    # Note: candidate.relation_type est un alias vers verified_relation_type
    result = validate_before_write(
        assertion_kind=candidate.assertion_kind,
        relation_type=candidate.verified_relation_type,
        extraction_method=candidate.extraction_method,
        evidence_bundle=bundle,
        discursive_basis=candidate.discursive_basis,
    )

    return result


# =============================================================================
# Helper: Filter valid candidates
# =============================================================================

def filter_valid_candidates(
    candidates: List[CandidatePair],
) -> List[CandidatePair]:
    """
    Filtre une liste de candidats pour ne garder que les valides.

    Args:
        candidates: Liste de CandidatePair

    Returns:
        Liste des candidats valides
    """
    valid = []
    rejected_count = 0

    for candidate in candidates:
        result = can_create_assertion(candidate)

        if result.is_valid:
            valid.append(candidate)
        else:
            rejected_count += 1
            logger.debug(
                f"[AssertionValidation] Rejected candidate: "
                f"{candidate.pivot_concept_id} -> {candidate.other_concept_id}: "
                f"{result.error_code}"
            )
            # Mettre à jour le statut du candidat
            candidate.status = CandidatePairStatus.REJECTED
            candidate.rejection_reason = result.error_message

    if rejected_count > 0:
        logger.info(
            f"[AssertionValidation] Filtered {rejected_count} invalid candidates "
            f"({len(valid)} valid)"
        )

    return valid
