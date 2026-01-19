"""
OSMOSE Evidence Bundle - Bundle Validator (Pass 3.5)

Validation des bundles avant promotion en SemanticRelation.

Sprint 1: Validation stricte pour haute précision (≥95%).
- Règles POS-based (agnostiques à la langue)
- Validation de proximité textuelle
- Vérification de complétude

Référence: ADR_MULTI_SPAN_EVIDENCE_BUNDLES.md v1.3
"""

from __future__ import annotations

import logging
from typing import List, Optional

from knowbase.relations.evidence_bundle_models import (
    BundleValidationResult,
    BundleValidationStatus,
    EvidenceBundle,
    EvidenceFragment,
    FragmentType,
    PredicateCandidate,
)
from knowbase.relations.predicate_extractor import (
    get_spacy_model,
    is_auxiliary_verb,
    is_copula_or_attributive,
    is_modal_or_intentional,
    locate_entity_in_doc,
)

logger = logging.getLogger(__name__)


# ===================================
# VALIDATION CONSTANTS
# ===================================

# Sprint 1: Seuils de validation
MIN_CONFIDENCE_THRESHOLD = 0.5  # Confiance minimale pour promotion
MAX_CHAR_DISTANCE = 500  # Distance max entre entités (caractères)
MIN_PREDICATE_CONFIDENCE = 0.6  # Confiance minimale sur le prédicat


# ===================================
# FRAGMENT VALIDATION
# ===================================

def validate_fragment(
    fragment: EvidenceFragment,
) -> tuple[bool, str]:
    """
    Valide un fragment d'evidence individuel.

    Args:
        fragment: Fragment à valider

    Returns:
        Tuple (is_valid, reason)
    """
    # Check 1: Texte non vide
    if not fragment.text or not fragment.text.strip():
        return False, "EMPTY_TEXT"

    # Check 2: Confiance suffisante
    if fragment.confidence < MIN_CONFIDENCE_THRESHOLD:
        return False, f"LOW_CONFIDENCE ({fragment.confidence:.2f})"

    # Check 3: Context ID présent
    if not fragment.source_context_id:
        return False, "MISSING_CONTEXT_ID"

    # Check 4: Pour Sprint 1, charspan requis sur ENTITY_MENTION
    if fragment.fragment_type == FragmentType.ENTITY_MENTION:
        if fragment.char_start is None or fragment.char_end is None:
            return False, "MISSING_CHARSPAN"

    return True, "VALID"


def validate_subject_fragment(
    fragment: EvidenceFragment,
) -> tuple[bool, str]:
    """
    Valide le fragment sujet (EA).

    Args:
        fragment: Fragment sujet

    Returns:
        Tuple (is_valid, reason)
    """
    # Validation de base
    is_valid, reason = validate_fragment(fragment)
    if not is_valid:
        return False, f"SUBJECT_{reason}"

    # Check type
    if fragment.fragment_type != FragmentType.ENTITY_MENTION:
        return False, "SUBJECT_WRONG_TYPE"

    return True, "VALID"


def validate_object_fragment(
    fragment: EvidenceFragment,
) -> tuple[bool, str]:
    """
    Valide le fragment objet (EB).

    Args:
        fragment: Fragment objet

    Returns:
        Tuple (is_valid, reason)
    """
    # Validation de base
    is_valid, reason = validate_fragment(fragment)
    if not is_valid:
        return False, f"OBJECT_{reason}"

    # Check type
    if fragment.fragment_type != FragmentType.ENTITY_MENTION:
        return False, "OBJECT_WRONG_TYPE"

    return True, "VALID"


def validate_predicate_fragment(
    fragment: EvidenceFragment,
) -> tuple[bool, str]:
    """
    Valide le fragment prédicat (EP).

    Args:
        fragment: Fragment prédicat

    Returns:
        Tuple (is_valid, reason)
    """
    # Validation de base
    is_valid, reason = validate_fragment(fragment)
    if not is_valid:
        return False, f"PREDICATE_{reason}"

    # Check type
    if fragment.fragment_type != FragmentType.PREDICATE_LEXICAL:
        return False, "PREDICATE_WRONG_TYPE"

    return True, "VALID"


# ===================================
# PROXIMITY VALIDATION
# ===================================

def validate_proximity(
    subject_fragment: EvidenceFragment,
    object_fragment: EvidenceFragment,
    max_distance: int = MAX_CHAR_DISTANCE,
) -> tuple[bool, str]:
    """
    Valide la proximité textuelle entre sujet et objet.

    Sprint 1: Simple validation de distance en caractères.

    Args:
        subject_fragment: Fragment sujet
        object_fragment: Fragment objet
        max_distance: Distance maximale autorisée

    Returns:
        Tuple (is_valid, reason)
    """
    # Check: Même section
    if subject_fragment.source_context_id != object_fragment.source_context_id:
        return False, "DIFFERENT_SECTIONS"

    # Check: Charspans disponibles
    if (
        subject_fragment.char_start is None
        or object_fragment.char_start is None
    ):
        # Sprint 1: Sans charspan, on ne peut pas valider la proximité
        return False, "MISSING_CHARSPANS"

    # Calculer la distance
    # Distance = écart entre la fin d'un et le début de l'autre
    if subject_fragment.char_end <= object_fragment.char_start:
        distance = object_fragment.char_start - subject_fragment.char_end
    elif object_fragment.char_end <= subject_fragment.char_start:
        distance = subject_fragment.char_start - object_fragment.char_end
    else:
        # Entités qui se chevauchent
        distance = 0

    if distance > max_distance:
        return False, f"TOO_FAR ({distance} chars > {max_distance})"

    return True, "VALID"


# ===================================
# PREDICATE VALIDATION (POS-based)
# ===================================

def validate_predicate_pos(
    predicate_text: str,
    section_text: str,
    predicate_char_start: int,
    predicate_char_end: int,
    lang: str = "fr",
) -> tuple[bool, str]:
    """
    Valide le prédicat via analyse POS.

    Vérifie que le prédicat n'est pas:
    - Un auxiliaire (POS=AUX)
    - Une copule/attributif
    - Un modal/intentionnel

    Args:
        predicate_text: Texte du prédicat
        section_text: Texte de la section
        predicate_char_start: Position début
        predicate_char_end: Position fin
        lang: Code langue

    Returns:
        Tuple (is_valid, reason)
    """
    # Parser le texte
    nlp = get_spacy_model(lang)
    doc = nlp(section_text)

    # Localiser le prédicat
    span = doc.char_span(predicate_char_start, predicate_char_end)
    if span is None:
        span = doc.char_span(
            predicate_char_start, predicate_char_end, alignment_mode="expand"
        )

    if span is None:
        # Fallback: chercher le token par texte
        for token in doc:
            if token.text == predicate_text:
                span = doc[token.i : token.i + 1]
                break

    if span is None:
        return False, "PREDICATE_NOT_FOUND"

    # Vérifier chaque token du span
    for token in span:
        if token.pos_ == "VERB":
            if is_auxiliary_verb(token):
                return False, "AUXILIARY_VERB"

            if is_copula_or_attributive(token):
                return False, "COPULA_OR_ATTRIBUTIVE"

            if is_modal_or_intentional(token):
                return False, "MODAL_OR_INTENTIONAL"

    return True, "VALID"


# ===================================
# BUNDLE VALIDATION ORCHESTRATOR
# ===================================

def validate_bundle(
    bundle: EvidenceBundle,
    section_text: Optional[str] = None,
    lang: str = "fr",
) -> BundleValidationResult:
    """
    Valide un bundle complet.

    Orchestrateur principal qui vérifie:
    1. Fragment sujet (EA)
    2. Fragment objet (EB)
    3. Fragment(s) prédicat (EP)
    4. Proximité textuelle
    5. Validation POS du prédicat

    Args:
        bundle: Bundle à valider
        section_text: Texte de la section (pour validation POS)
        lang: Code langue

    Returns:
        BundleValidationResult avec détails
    """
    checks_passed: List[str] = []
    checks_failed: List[str] = []
    validation_details: dict[str, str] = {}

    # Check 1: Fragment sujet
    is_valid, reason = validate_subject_fragment(bundle.evidence_subject)
    if is_valid:
        checks_passed.append("subject_fragment")
    else:
        checks_failed.append("subject_fragment")
        validation_details["subject_fragment"] = reason

    # Check 2: Fragment objet
    is_valid, reason = validate_object_fragment(bundle.evidence_object)
    if is_valid:
        checks_passed.append("object_fragment")
    else:
        checks_failed.append("object_fragment")
        validation_details["object_fragment"] = reason

    # Check 3: Au moins un prédicat
    if not bundle.evidence_predicate:
        checks_failed.append("predicate_present")
        validation_details["predicate_present"] = "NO_PREDICATE"
    else:
        # Valider le premier prédicat (le principal)
        predicate_fragment = bundle.evidence_predicate[0]
        is_valid, reason = validate_predicate_fragment(predicate_fragment)
        if is_valid:
            checks_passed.append("predicate_fragment")
        else:
            checks_failed.append("predicate_fragment")
            validation_details["predicate_fragment"] = reason

    # Check 4: Proximité
    is_valid, reason = validate_proximity(
        bundle.evidence_subject, bundle.evidence_object
    )
    if is_valid:
        checks_passed.append("proximity")
    else:
        checks_failed.append("proximity")
        validation_details["proximity"] = reason

    # Check 5: Validation POS du prédicat (si section_text fourni)
    if section_text and bundle.evidence_predicate:
        predicate_fragment = bundle.evidence_predicate[0]
        if predicate_fragment.char_start is not None:
            is_valid, reason = validate_predicate_pos(
                predicate_fragment.text,
                section_text,
                predicate_fragment.char_start,
                predicate_fragment.char_end or predicate_fragment.char_start + len(predicate_fragment.text),
                lang=lang,
            )
            if is_valid:
                checks_passed.append("predicate_pos")
            else:
                checks_failed.append("predicate_pos")
                validation_details["predicate_pos"] = reason
        else:
            # Sans charspan, on passe ce check avec warning
            checks_passed.append("predicate_pos")
            validation_details["predicate_pos"] = "SKIPPED_NO_CHARSPAN"

    # Check 6: Confiance globale
    if bundle.confidence >= MIN_CONFIDENCE_THRESHOLD:
        checks_passed.append("confidence_threshold")
    else:
        checks_failed.append("confidence_threshold")
        validation_details["confidence_threshold"] = (
            f"LOW ({bundle.confidence:.2f} < {MIN_CONFIDENCE_THRESHOLD})"
        )

    # Check 7: Concepts différents
    if bundle.subject_concept_id == bundle.object_concept_id:
        checks_failed.append("different_concepts")
        validation_details["different_concepts"] = "SELF_RELATION"
    else:
        checks_passed.append("different_concepts")

    # Déterminer le résultat final
    is_bundle_valid = len(checks_failed) == 0

    # Raison de rejet principale
    rejection_reason = None
    if not is_bundle_valid:
        # Prendre le premier échec comme raison principale
        first_failed = checks_failed[0]
        rejection_reason = validation_details.get(first_failed, first_failed.upper())

    result = BundleValidationResult(
        is_valid=is_bundle_valid,
        rejection_reason=rejection_reason,
        checks_passed=checks_passed,
        checks_failed=checks_failed,
        validation_details=validation_details,
    )

    # Logging
    if is_bundle_valid:
        logger.info(
            f"[OSMOSE:Pass3.5] Bundle {bundle.bundle_id} VALID "
            f"({len(checks_passed)} checks passed)"
        )
    else:
        logger.info(
            f"[OSMOSE:Pass3.5] Bundle {bundle.bundle_id} REJECTED: {rejection_reason} "
            f"(passed: {len(checks_passed)}, failed: {len(checks_failed)})"
        )

    return result


def validate_bundle_for_promotion(
    bundle: EvidenceBundle,
    section_text: Optional[str] = None,
    lang: str = "fr",
) -> tuple[bool, Optional[str]]:
    """
    Vérifie si un bundle peut être promu en SemanticRelation.

    Wrapper simplifié pour validate_bundle.

    Args:
        bundle: Bundle à vérifier
        section_text: Texte de la section
        lang: Code langue

    Returns:
        Tuple (can_promote, rejection_reason)
    """
    result = validate_bundle(bundle, section_text, lang)
    return result.is_valid, result.rejection_reason


def apply_validation_to_bundle(
    bundle: EvidenceBundle,
    section_text: Optional[str] = None,
    lang: str = "fr",
) -> EvidenceBundle:
    """
    Applique la validation et met à jour le bundle.

    Args:
        bundle: Bundle à valider
        section_text: Texte de la section
        lang: Code langue

    Returns:
        Bundle mis à jour avec status et rejection_reason
    """
    from datetime import datetime

    result = validate_bundle(bundle, section_text, lang)

    if result.is_valid:
        bundle.validation_status = BundleValidationStatus.CANDIDATE
    else:
        bundle.validation_status = BundleValidationStatus.REJECTED
        bundle.rejection_reason = result.rejection_reason
        bundle.validated_at = datetime.utcnow()

    return bundle
