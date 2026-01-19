"""
OSMOSE - Anchor Validator (Charspan Contract v1)

Validation des anchors avant persistance dans Neo4j.

Spec: doc/ongoing/ADR_CHARSPAN_CONTRACT_V1.md Section 5.4
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from enum import Enum
from typing import List, Optional

logger = logging.getLogger(__name__)


class AnchorQuality(str, Enum):
    """
    Qualité de l'anchor selon la méthode d'obtention.

    Spec: ADR_CHARSPAN_CONTRACT_V1.md Section 3.6
    """
    PRIMARY = "PRIMARY"      # Spans de l'extracteur primaire (NER/spaCy/LLM)
    DERIVED = "DERIVED"      # Calculé par transformation fiable et déterministe
    APPROX = "APPROX"        # indexOf / fuzzy match
    AMBIGUOUS = "AMBIGUOUS"  # Plusieurs matches plausibles


class ValidationErrorType(str, Enum):
    """Types d'erreurs de validation."""
    INVALID_SPAN_ORDERING = "invalid_span_ordering"
    SPAN_OUT_OF_BOUNDS = "span_out_of_bounds"
    SURFACE_FORM_MISMATCH = "surface_form_mismatch"
    EMPTY_SPAN = "empty_span"
    MISSING_REQUIRED_FIELD = "missing_required_field"


@dataclass
class ValidationError:
    """Erreur de validation d'un anchor."""
    error_type: ValidationErrorType
    message: str
    field: Optional[str] = None
    expected: Optional[str] = None
    actual: Optional[str] = None


@dataclass
class ValidationResult:
    """Résultat de la validation d'un anchor."""
    is_valid: bool
    errors: List[ValidationError]
    warnings: List[str]

    @property
    def has_errors(self) -> bool:
        return len(self.errors) > 0

    @property
    def has_warnings(self) -> bool:
        return len(self.warnings) > 0


@dataclass
class AnchorData:
    """
    Données d'un anchor à valider.

    Correspond aux propriétés de la relation ANCHORED_IN.
    """
    span_start: int
    span_end: int
    surface_form: Optional[str] = None
    anchor_quality: Optional[str] = None
    anchor_method: Optional[str] = None
    anchor_id: Optional[str] = None
    confidence: Optional[float] = None


def validate_anchor(
    docitem_text: str,
    anchor: AnchorData,
    strict: bool = True
) -> ValidationResult:
    """
    Valide un anchor avant persistance.

    Checks V1 (obligatoires):
    1. Bounds: 0 <= span_start < span_end <= len(text)
    2. Surface form: si fournie, doit matcher le slice
    3. Non-vide: span_end - span_start > 0

    Args:
        docitem_text: Texte du DocItem cible
        anchor: Données de l'anchor à valider
        strict: Si True, fail sur toute erreur. Si False, log warnings.

    Returns:
        ValidationResult avec erreurs et warnings
    """
    errors: List[ValidationError] = []
    warnings: List[str] = []
    text_len = len(docitem_text) if docitem_text else 0

    # V1.1 - Bounds check
    if anchor.span_start < 0:
        errors.append(ValidationError(
            error_type=ValidationErrorType.INVALID_SPAN_ORDERING,
            message=f"span_start ({anchor.span_start}) must be >= 0",
            field="span_start",
            expected=">= 0",
            actual=str(anchor.span_start)
        ))

    if anchor.span_end <= anchor.span_start:
        errors.append(ValidationError(
            error_type=ValidationErrorType.INVALID_SPAN_ORDERING,
            message=f"span_end ({anchor.span_end}) must be > span_start ({anchor.span_start})",
            field="span_end",
            expected=f"> {anchor.span_start}",
            actual=str(anchor.span_end)
        ))

    if anchor.span_end > text_len:
        errors.append(ValidationError(
            error_type=ValidationErrorType.SPAN_OUT_OF_BOUNDS,
            message=f"span_end ({anchor.span_end}) exceeds text length ({text_len})",
            field="span_end",
            expected=f"<= {text_len}",
            actual=str(anchor.span_end)
        ))

    # V1.2 - Surface form check (si fournie et bounds valides)
    if anchor.surface_form and not errors:
        actual_slice = docitem_text[anchor.span_start:anchor.span_end]
        if actual_slice != anchor.surface_form:
            errors.append(ValidationError(
                error_type=ValidationErrorType.SURFACE_FORM_MISMATCH,
                message=f"Surface form mismatch",
                field="surface_form",
                expected=anchor.surface_form,
                actual=actual_slice
            ))

    # V1.3 - Non-vide (redondant avec V1.1 mais explicite)
    span_length = anchor.span_end - anchor.span_start
    if span_length <= 0:
        errors.append(ValidationError(
            error_type=ValidationErrorType.EMPTY_SPAN,
            message=f"Span length ({span_length}) must be > 0",
            field="span_length",
            expected="> 0",
            actual=str(span_length)
        ))

    # V2 - Checks de robustesse (warnings)
    if anchor.anchor_quality == AnchorQuality.APPROX.value:
        warnings.append(
            f"Anchor uses APPROX quality (method={anchor.anchor_method}), "
            "may not be suitable for extractive validation"
        )

    if anchor.anchor_quality == AnchorQuality.AMBIGUOUS.value:
        warnings.append(
            "Anchor is AMBIGUOUS, requires disambiguation before use"
        )

    is_valid = len(errors) == 0
    return ValidationResult(is_valid=is_valid, errors=errors, warnings=warnings)


def validate_anchor_batch(
    docitem_texts: dict[str, str],
    anchors: List[tuple[str, AnchorData]],
    fail_fast: bool = False
) -> dict[str, ValidationResult]:
    """
    Valide un batch d'anchors.

    Args:
        docitem_texts: Dict docitem_id -> texte
        anchors: Liste de tuples (docitem_id, AnchorData)
        fail_fast: Si True, arrête à la première erreur

    Returns:
        Dict docitem_id:span -> ValidationResult
    """
    results = {}

    for docitem_id, anchor in anchors:
        text = docitem_texts.get(docitem_id, "")
        key = f"{docitem_id}:{anchor.span_start}:{anchor.span_end}"

        result = validate_anchor(text, anchor)
        results[key] = result

        if fail_fast and result.has_errors:
            logger.error(
                f"[AnchorValidator] Validation failed for {key}: "
                f"{[e.message for e in result.errors]}"
            )
            break

        if result.has_warnings:
            for warning in result.warnings:
                logger.warning(f"[AnchorValidator] {key}: {warning}")

    return results


def check_multi_occurrence(
    text: str,
    surface_form: str,
    case_sensitive: bool = False
) -> int:
    """
    Compte le nombre d'occurrences d'une surface form dans le texte.

    Utilisé pour détecter les anchors AMBIGUOUS.

    Args:
        text: Texte à chercher
        surface_form: Forme de surface à trouver
        case_sensitive: Si False, ignore la casse

    Returns:
        Nombre d'occurrences
    """
    if not text or not surface_form:
        return 0

    search_text = text if case_sensitive else text.lower()
    search_form = surface_form if case_sensitive else surface_form.lower()

    count = 0
    start = 0
    while True:
        pos = search_text.find(search_form, start)
        if pos == -1:
            break
        count += 1
        start = pos + 1

    return count


def determine_anchor_quality(
    text: str,
    surface_form: str,
    method: str,
    case_sensitive: bool = False
) -> AnchorQuality:
    """
    Détermine la qualité d'un anchor basé sur la méthode et le contexte.

    Args:
        text: Texte du DocItem
        surface_form: Forme de surface du concept
        method: Méthode d'extraction (spacy_ner, llm, indexOf_fallback, etc.)
        case_sensitive: Si False, ignore la casse pour le check multi-occurrence

    Returns:
        AnchorQuality appropriée
    """
    # Méthodes primaires
    if method in ("spacy_ner", "llm_with_offsets", "regex_primary"):
        return AnchorQuality.PRIMARY

    # Méthodes dérivées
    if method in ("token_to_char_mapping", "sentence_boundary"):
        return AnchorQuality.DERIVED

    # Fallback indexOf: vérifier multi-occurrence
    if method in ("indexOf_fallback", "text_search"):
        occurrences = check_multi_occurrence(text, surface_form, case_sensitive)
        if occurrences > 1:
            return AnchorQuality.AMBIGUOUS
        return AnchorQuality.APPROX

    # Par défaut: APPROX
    return AnchorQuality.APPROX


# ============================================
# Fonctions utilitaires pour la persistance
# ============================================

def create_anchor_id(
    proto_id: str,
    docitem_id: str,
    span_start: int,
    span_end: int
) -> str:
    """
    Génère un anchor_id unique.

    Format: {proto_id}:{docitem_id}:{span_start}:{span_end}
    """
    return f"{proto_id}:{docitem_id}:{span_start}:{span_end}"


def validate_before_persist(
    docitem_text: str,
    anchor: AnchorData,
    raise_on_error: bool = True
) -> bool:
    """
    Valide un anchor et lève une exception si invalide.

    À appeler avant toute persistance Neo4j.

    Args:
        docitem_text: Texte du DocItem
        anchor: Données de l'anchor
        raise_on_error: Si True, lève ValueError sur erreur

    Returns:
        True si valide

    Raises:
        ValueError: Si invalide et raise_on_error=True
    """
    result = validate_anchor(docitem_text, anchor)

    if result.has_errors:
        error_messages = [f"{e.error_type.value}: {e.message}" for e in result.errors]
        msg = f"Anchor validation failed: {'; '.join(error_messages)}"

        if raise_on_error:
            raise ValueError(msg)

        logger.error(f"[AnchorValidator] {msg}")
        return False

    return True
