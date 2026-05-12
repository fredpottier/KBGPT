"""
Evidence-locked validator V3.3 — vérifie chaque field d'un ApplicabilityFrameV2.

Pour chaque field non-null produit par le LLM, vérifie que `evidence_quote`
est substring du full_text source (insensible aux espaces multiples + lowercase).

Si la quote est absente :
- Field reset à None
- Entrée ajoutée à `rejected_fields` du frame avec raison

Pour les dates avec date_role :
- Si date_role ∈ {ADOPTION, SIGNATURE} → la valeur ne peut pas peupler validity_start
  (uniquement publication_date est autorisé pour ces rôles, et seulement si pas
  d'autre date avec role PUBLICATION)
- Si date_role = UNKNOWN avec value non-null → reject

Pattern V3.3 : 0 hallucination tolérée sur les fields persistés.
"""
from __future__ import annotations

import logging
import re
from typing import Optional

from knowbase.claimfirst.applicability.models import (
    ApplicabilityFrameV2,
    DateField,
    DateRole,
    EvidenceLockedField,
    LifecycleAxis,
    LifecycleStatus,
    ScopeAxis,
    TemporalityAxis,
)

logger = logging.getLogger(__name__)


# ============================================================================
# Quote validation
# ============================================================================

_WHITESPACE_RE = re.compile(r"\s+")


def normalize_for_match(s: str) -> str:
    """
    Normalise pour matching : collapse whitespace + lowercase.

    Tolérance aux artefacts Docling (double espaces autour de la ponctuation).
    """
    return _WHITESPACE_RE.sub(" ", s.lower()).strip()


def quote_is_present(quote: Optional[str], full_text_normalized: str) -> bool:
    """
    Vérifie qu'une quote est substring du full_text normalisé.

    Args:
        quote: Citation à vérifier (peut être None → return False)
        full_text_normalized: full_text déjà normalisé (whitespace + lowercase)

    Returns:
        True si quote est présente verbatim dans le source
    """
    if not quote:
        return False
    return normalize_for_match(quote) in full_text_normalized


# ============================================================================
# Field validators
# ============================================================================

def _validate_evidence_locked_field(
    field: Optional[EvidenceLockedField],
    full_text_normalized: str,
    axis_name: str,
    field_name: str,
    rejects: list,
) -> Optional[EvidenceLockedField]:
    """Valide un EvidenceLockedField. Return cleaned field or None."""
    if field is None or field.value is None:
        return None
    if field.source == "tier1_filename":
        # Tier 1 déterministe : pas besoin de quote (déjà cross-validated par filename)
        return field
    if quote_is_present(field.evidence_quote, full_text_normalized):
        return field
    rejects.append({
        "axis": axis_name,
        "field": field_name,
        "value": field.value,
        "quote": field.evidence_quote,
        "source": field.source,
        "reason": "quote not found in full_text",
    })
    return None


def _validate_date_field(
    field: Optional[DateField],
    full_text_normalized: str,
    axis_name: str,
    field_name: str,
    expected_roles: set[DateRole],
    rejects: list,
) -> Optional[DateField]:
    """
    Valide un DateField : evidence_quote présente + date_role correct.

    Args:
        expected_roles: rôles autorisés pour ce field (ex: {EFFECTIVE, APPLICABLE_FROM} pour validity_start)

    Returns:
        Field cleaned ou None si rejected
    """
    if field is None or field.value is None:
        return None

    # Tier 1 déterministe : pas de quote requise (year extraite du filename)
    if field.source == "tier1_filename":
        return field

    # Validate quote
    if not quote_is_present(field.evidence_quote, full_text_normalized):
        rejects.append({
            "axis": axis_name,
            "field": field_name,
            "value": field.value,
            "quote": field.evidence_quote,
            "date_role": field.date_role.value,
            "source": field.source,
            "reason": "quote not found in full_text",
        })
        return None

    # Validate date_role
    if field.date_role not in expected_roles:
        rejects.append({
            "axis": axis_name,
            "field": field_name,
            "value": field.value,
            "quote": field.evidence_quote,
            "date_role": field.date_role.value,
            "source": field.source,
            "reason": f"date_role {field.date_role.value} not in allowed roles {[r.value for r in expected_roles]}",
        })
        return None

    return field


def validate_frame_v2(frame: ApplicabilityFrameV2, full_text: str) -> ApplicabilityFrameV2:
    """
    Valide un ApplicabilityFrameV2 : evidence-locked + date_role correct.

    Modifie le frame in-place (rejects ajoutés à frame.rejected_fields, fields
    invalides reset à None) et le retourne.

    Args:
        frame: Frame à valider (output Tier 2 LLM)
        full_text: Source d'autorité pour les evidence_quote

    Returns:
        Frame nettoyé (les fields invalides sont None)
    """
    rejects: list[dict] = []
    full_text_normalized = normalize_for_match(full_text)

    # === Scope axis ===
    scope = frame.scope or ScopeAxis()
    scope.product_version = _validate_evidence_locked_field(
        scope.product_version, full_text_normalized, "scope", "product_version", rejects
    )
    scope.region = _validate_evidence_locked_field(
        scope.region, full_text_normalized, "scope", "region", rejects
    )
    scope.edition = _validate_evidence_locked_field(
        scope.edition, full_text_normalized, "scope", "edition", rejects
    )
    scope.subject_class = _validate_evidence_locked_field(
        scope.subject_class, full_text_normalized, "scope", "subject_class", rejects
    )
    # Conditions list : filtrer celles dont la quote n'est pas présente
    valid_conditions: list[EvidenceLockedField] = []
    for i, cond in enumerate(scope.conditions or []):
        cleaned = _validate_evidence_locked_field(
            cond, full_text_normalized, "scope", f"conditions[{i}]", rejects
        )
        if cleaned is not None:
            valid_conditions.append(cleaned)
    scope.conditions = valid_conditions
    frame.scope = scope

    # === Temporality axis ===
    temp = frame.temporality or TemporalityAxis()
    # publication_date : seul role autorisé = PUBLICATION (pas d'adoption/signature)
    temp.publication_date = _validate_date_field(
        temp.publication_date, full_text_normalized, "temporality", "publication_date",
        {DateRole.PUBLICATION}, rejects
    )
    # validity_start : roles autorisés = EFFECTIVE, APPLICABLE_FROM
    # (PAS adoption/signature : c'est l'invariant V3.3)
    temp.validity_start = _validate_date_field(
        temp.validity_start, full_text_normalized, "temporality", "validity_start",
        {DateRole.EFFECTIVE, DateRole.APPLICABLE_FROM}, rejects
    )
    # validity_end : roles autorisés = EXPIRY
    temp.validity_end = _validate_date_field(
        temp.validity_end, full_text_normalized, "temporality", "validity_end",
        {DateRole.EXPIRY}, rejects
    )
    frame.temporality = temp

    # === Lifecycle axis ===
    lifecycle = frame.lifecycle or LifecycleAxis()
    # status : si non-UNKNOWN, doit avoir une evidence_quote présente
    if lifecycle.status != LifecycleStatus.UNKNOWN:
        if not quote_is_present(lifecycle.status_evidence_quote, full_text_normalized):
            rejects.append({
                "axis": "lifecycle",
                "field": "status",
                "value": lifecycle.status.value,
                "quote": lifecycle.status_evidence_quote,
                "reason": "quote not found in full_text",
            })
            lifecycle.status = LifecycleStatus.UNKNOWN
            lifecycle.status_evidence_quote = None

    # supersedes / superseded_by / evolves_from : evidence_quote requise
    valid_supersedes: list[EvidenceLockedField] = []
    for i, sup in enumerate(lifecycle.supersedes or []):
        cleaned = _validate_evidence_locked_field(
            sup, full_text_normalized, "lifecycle", f"supersedes[{i}]", rejects
        )
        if cleaned is not None:
            valid_supersedes.append(cleaned)
    lifecycle.supersedes = valid_supersedes

    lifecycle.superseded_by = _validate_evidence_locked_field(
        lifecycle.superseded_by, full_text_normalized, "lifecycle", "superseded_by", rejects
    )
    lifecycle.evolves_from = _validate_evidence_locked_field(
        lifecycle.evolves_from, full_text_normalized, "lifecycle", "evolves_from", rejects
    )
    frame.lifecycle = lifecycle

    # === Update frame metadata ===
    frame.rejected_fields = rejects
    if rejects:
        frame.validation_notes.append(
            f"Validator V3.3 rejected {len(rejects)} fields (evidence_quote not in source or date_role mismatch)"
        )

    return frame


def compute_rejection_rate(frame: ApplicabilityFrameV2) -> tuple[int, int, float]:
    """
    Calcule le taux de rejet (= taux d'hallucination potentiel).

    Returns:
        (n_rejected, n_total_attempted, rate_pct)
    """
    n_rejected = len(frame.rejected_fields or [])

    # n_total = fields validés + rejetés
    n_validated = 0
    if frame.scope.product_version: n_validated += 1
    if frame.scope.region: n_validated += 1
    if frame.scope.edition: n_validated += 1
    if frame.scope.subject_class: n_validated += 1
    n_validated += len(frame.scope.conditions)

    if frame.temporality.publication_date and frame.temporality.publication_date.value: n_validated += 1
    if frame.temporality.validity_start and frame.temporality.validity_start.value: n_validated += 1
    if frame.temporality.validity_end and frame.temporality.validity_end.value: n_validated += 1

    if frame.lifecycle.status != LifecycleStatus.UNKNOWN: n_validated += 1
    n_validated += len(frame.lifecycle.supersedes)
    if frame.lifecycle.superseded_by: n_validated += 1
    if frame.lifecycle.evolves_from: n_validated += 1

    n_total = n_validated + n_rejected
    rate = (n_rejected / n_total * 100) if n_total > 0 else 0.0
    return (n_rejected, n_total, rate)


__all__ = [
    "normalize_for_match",
    "quote_is_present",
    "validate_frame_v2",
    "compute_rejection_rate",
]
