# src/knowbase/claimfirst/models/comparability_verdict.py
"""
ComparabilityVerdict — Verdict de comparabilité entre deux QuestionSignatures.

Détermine si deux QS peuvent être comparées (même question, même scope,
valeurs compatibles) ou non, avec la raison précise du blocage.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Optional


class ComparabilityLevel(str, Enum):
    """Niveaux de comparabilité entre deux QS."""
    COMPARABLE_STRICT = "COMPARABLE_STRICT"
    COMPARABLE_LOOSE = "COMPARABLE_LOOSE"
    NOT_COMPARABLE = "NOT_COMPARABLE"
    NEED_REVIEW = "NEED_REVIEW"


NON_COMPARABILITY_REASONS = frozenset({
    "dimension_not_validated",
    "dimension_mismatch",
    "incompatible_value_type",
    "incompatible_operator",
    "anchor_mismatch",
    "contradictory_axes",
    "ambiguous_scope",
    "missing_scope",
    "scope_policy_violation",
})


@dataclass
class ComparabilityVerdict:
    """Verdict de comparabilité entre deux QS."""

    level: ComparabilityLevel
    reason: Optional[str] = None       # Obligatoire si NOT_COMPARABLE
    blocking_criterion: Optional[str] = None  # Critère bloquant spécifique

    def __post_init__(self):
        if self.level == ComparabilityLevel.NOT_COMPARABLE and not self.reason:
            raise ValueError("reason est obligatoire quand level=NOT_COMPARABLE")


def _scope_get(scope, key: str, default=None):
    """Accède à un champ de scope, que ce soit un dict ou un objet."""
    if isinstance(scope, dict):
        return scope.get(key, default)
    return getattr(scope, key, default)


def are_comparable(qs_a, qs_b, dimension=None) -> ComparabilityVerdict:
    """
    Détermine si deux QuestionSignatures sont comparables.

    Vérifie :
    1. Même dimension
    2. Compatibilité value_type
    3. Compatibilité operator (pas d'inversion)
    4. Scope policy (si dimension fournie)
    5. Scope non contradictoire

    Args:
        qs_a: Première QuestionSignature (avec dimension_id, value_type, etc.)
        qs_b: Deuxième QuestionSignature
        dimension: QuestionDimension optionnelle (pour scope_policy enforcement)

    Returns:
        ComparabilityVerdict
    """
    # 1. Même dimension
    if getattr(qs_a, 'dimension_id', None) != getattr(qs_b, 'dimension_id', None):
        return ComparabilityVerdict(
            level=ComparabilityLevel.NOT_COMPARABLE,
            reason="dimension_mismatch",
            blocking_criterion="dimension_id differs",
        )

    # 2. Compatibilité value_type
    vt_a = getattr(qs_a, 'value_type', None)
    vt_b = getattr(qs_b, 'value_type', None)
    if vt_a and vt_b:
        vt_a_str = vt_a.value if hasattr(vt_a, 'value') else str(vt_a)
        vt_b_str = vt_b.value if hasattr(vt_b, 'value') else str(vt_b)
        if vt_a_str != vt_b_str:
            return ComparabilityVerdict(
                level=ComparabilityLevel.NOT_COMPARABLE,
                reason="incompatible_value_type",
                blocking_criterion=f"{vt_a_str} vs {vt_b_str}",
            )

    # 3. Compatibilité operator (inversion = non comparable)
    op_a = getattr(qs_a, 'operator', None)
    op_b = getattr(qs_b, 'operator', None)
    if op_a and op_b:
        inversions = {(">=", "<="), ("<=", ">="), (">", "<"), ("<", ">")}
        if (op_a, op_b) in inversions:
            return ComparabilityVerdict(
                level=ComparabilityLevel.NOT_COMPARABLE,
                reason="incompatible_operator",
                blocking_criterion=f"operator inversion: {op_a} vs {op_b}",
            )

    # 4. Scope policy enforcement (si dimension fournie)
    if dimension:
        scope_policy = getattr(dimension, 'scope_policy', 'any')
        if scope_policy != 'any':
            _weak_bases = {"section_context", "document_context"}
            for qs in (qs_a, qs_b):
                qs_scope = getattr(qs, 'scope', None)
                if qs_scope:
                    basis = _scope_get(qs_scope, 'scope_basis', 'missing')
                    if basis in _weak_bases:
                        return ComparabilityVerdict(
                            level=ComparabilityLevel.NOT_COMPARABLE,
                            reason="scope_policy_violation",
                            blocking_criterion=f"scope_policy={scope_policy} requires specific scope, got {basis}",
                        )

    # 5. Scope — vérifier non-contradiction
    scope_a = getattr(qs_a, 'scope', None)
    scope_b = getattr(qs_b, 'scope', None)

    if scope_a and scope_b:
        status_a = _scope_get(scope_a, 'scope_status', 'missing')
        status_b = _scope_get(scope_b, 'scope_status', 'missing')

        # Ambiguous scope → NEED_REVIEW
        if status_a == "ambiguous" or status_b == "ambiguous":
            return ComparabilityVerdict(
                level=ComparabilityLevel.NEED_REVIEW,
                reason="ambiguous_scope",
            )

        # Missing scope → NOT_COMPARABLE
        if status_a == "missing" or status_b == "missing":
            return ComparabilityVerdict(
                level=ComparabilityLevel.NOT_COMPARABLE,
                reason="missing_scope",
                blocking_criterion="one or both scopes missing",
            )

        # Anchor mismatch (produits différents)
        anchor_a = _scope_get(scope_a, 'primary_anchor_id')
        anchor_b = _scope_get(scope_b, 'primary_anchor_id')
        if anchor_a and anchor_b and anchor_a != anchor_b:
            # Même type d'ancre mais IDs différents → COMPARABLE_LOOSE
            type_a = _scope_get(scope_a, 'primary_anchor_type')
            type_b = _scope_get(scope_b, 'primary_anchor_type')
            if type_a == type_b:
                return ComparabilityVerdict(
                    level=ComparabilityLevel.COMPARABLE_LOOSE,
                    reason=None,
                )
            else:
                return ComparabilityVerdict(
                    level=ComparabilityLevel.NOT_COMPARABLE,
                    reason="anchor_mismatch",
                    blocking_criterion=f"anchor types differ: {type_a} vs {type_b}",
                )

    # Tout est compatible
    strict = True

    # Dégradation vers LOOSE si scope hérité
    if scope_a and _scope_get(scope_a, 'scope_basis', '') in ("section_context", "document_context"):
        strict = False
    if scope_b and _scope_get(scope_b, 'scope_basis', '') in ("section_context", "document_context"):
        strict = False

    return ComparabilityVerdict(
        level=ComparabilityLevel.COMPARABLE_STRICT if strict else ComparabilityLevel.COMPARABLE_LOOSE,
    )


__all__ = [
    "ComparabilityLevel",
    "ComparabilityVerdict",
    "NON_COMPARABILITY_REASONS",
    "are_comparable",
]
