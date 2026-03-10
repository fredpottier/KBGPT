# src/knowbase/claimfirst/comparisons/qs_comparator.py
"""
QS Comparator — Moteur de comparaison cross-doc.

Traverse les QuestionSignatures groupées par dimension, évalue la
comparabilité, puis classifie les différences :
- EVOLUTION : même question + même scope + valeur différente (docs différents)
- CONTRADICTION : même question + même scope + valeurs incompatibles (même contexte)
- CONVERGENCE : même question + scopes différents + valeurs identiques
- AGREEMENT : même question + même scope + même valeur (confirmation cross-doc)
"""

from __future__ import annotations

import logging
from collections import defaultdict
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple

from knowbase.claimfirst.models.comparability_verdict import (
    ComparabilityLevel,
    ComparabilityVerdict,
    are_comparable,
)
from knowbase.claimfirst.models.question_signature import QuestionSignature
from knowbase.claimfirst.models.resolved_scope import ResolvedScope

logger = logging.getLogger("[OSMOSE] qs_comparator")


class ComparisonType(str, Enum):
    """Type de résultat de comparaison entre deux QS."""

    EVOLUTION = "EVOLUTION"
    """Même question + même scope + valeur différente entre docs/releases."""

    CONTRADICTION = "CONTRADICTION"
    """Même question + même scope + valeurs incompatibles (même contexte temporel)."""

    CONVERGENCE = "CONVERGENCE"
    """Même question + scopes différents + valeurs identiques."""

    AGREEMENT = "AGREEMENT"
    """Même question + même scope + même valeur (confirmation cross-doc)."""

    UNDETERMINED = "UNDETERMINED"
    """Comparaison possible mais classification incertaine."""


@dataclass
class ValueDiff:
    """Différence de valeur entre deux QS."""

    value_a: str
    value_b: str
    normalized_a: Optional[str] = None
    normalized_b: Optional[str] = None
    operator_a: str = "="
    operator_b: str = "="
    values_equal: bool = False
    direction: Optional[str] = None  # "increased"|"decreased"|None


@dataclass
class ComparisonResult:
    """Résultat structuré d'une comparaison entre deux QS."""

    comparison_type: ComparisonType
    comparability: ComparabilityVerdict

    # Les deux QS comparées
    qs_a_id: str
    qs_b_id: str
    qs_a_claim_id: str
    qs_b_claim_id: str
    qs_a_doc_id: str
    qs_b_doc_id: str

    # Dimension commune
    dimension_id: Optional[str] = None
    dimension_key: str = ""
    canonical_question: str = ""

    # Différence de valeur
    value_diff: Optional[ValueDiff] = None

    # Scope
    scope_a_label: Optional[str] = None
    scope_b_label: Optional[str] = None
    same_scope: bool = False

    # Confiance et audit
    confidence: float = 0.0
    explanation: str = ""

    def to_dict(self) -> Dict[str, Any]:
        """Sérialise pour export/audit."""
        result = {
            "comparison_type": self.comparison_type.value,
            "comparability_level": self.comparability.level.value,
            "qs_a_id": self.qs_a_id,
            "qs_b_id": self.qs_b_id,
            "qs_a_doc_id": self.qs_a_doc_id,
            "qs_b_doc_id": self.qs_b_doc_id,
            "dimension_key": self.dimension_key,
            "canonical_question": self.canonical_question,
            "same_scope": self.same_scope,
            "confidence": self.confidence,
            "explanation": self.explanation,
        }
        if self.value_diff:
            result["value_a"] = self.value_diff.value_a
            result["value_b"] = self.value_diff.value_b
            result["values_equal"] = self.value_diff.values_equal
            result["direction"] = self.value_diff.direction
        if self.scope_a_label:
            result["scope_a"] = self.scope_a_label
        if self.scope_b_label:
            result["scope_b"] = self.scope_b_label
        return result


def _compute_value_diff(qs_a: QuestionSignature, qs_b: QuestionSignature) -> ValueDiff:
    """Calcule la différence de valeur entre deux QS."""
    val_a = qs_a.extracted_value
    val_b = qs_b.extracted_value
    norm_a = qs_a.value_normalized
    norm_b = qs_b.value_normalized

    # Comparaison : préférer les valeurs normalisées
    compare_a = (norm_a or val_a).strip().lower()
    compare_b = (norm_b or val_b).strip().lower()
    values_equal = compare_a == compare_b

    # Direction pour les numériques
    direction = None
    if not values_equal:
        try:
            num_a = float(norm_a or val_a)
            num_b = float(norm_b or val_b)
            direction = "increased" if num_b > num_a else "decreased"
        except (ValueError, TypeError):
            pass

    return ValueDiff(
        value_a=val_a,
        value_b=val_b,
        normalized_a=norm_a,
        normalized_b=norm_b,
        operator_a=qs_a.operator,
        operator_b=qs_b.operator,
        values_equal=values_equal,
        direction=direction,
    )


def _have_same_anchor(qs_a: QuestionSignature, qs_b: QuestionSignature) -> bool:
    """Vérifie si deux QS ont le même anchor (même produit/sujet)."""
    from knowbase.claimfirst.models.comparability_verdict import _scope_get

    scope_a = getattr(qs_a, 'scope', None)
    scope_b = getattr(qs_b, 'scope', None)
    if not scope_a or not scope_b:
        return False
    anchor_a = _scope_get(scope_a, 'primary_anchor_id')
    anchor_b = _scope_get(scope_b, 'primary_anchor_id')
    if anchor_a and anchor_b:
        return anchor_a == anchor_b
    # Fallback sur le label
    label_a = _scope_get(scope_a, 'primary_anchor_label')
    label_b = _scope_get(scope_b, 'primary_anchor_label')
    if label_a and label_b:
        return label_a.lower().strip() == label_b.lower().strip()
    return False


def _get_scope_label(qs: QuestionSignature) -> Optional[str]:
    """Extrait le label du scope d'une QS."""
    scope = qs.get_resolved_scope()
    if scope:
        return scope.primary_anchor_label
    return qs.scope_subject  # fallback legacy


def _is_same_scope(verdict: ComparabilityVerdict) -> bool:
    """Détermine si le verdict indique un scope identique (STRICT uniquement)."""
    return verdict.level == ComparabilityLevel.COMPARABLE_STRICT


def _is_comparable_scope(verdict: ComparabilityVerdict) -> bool:
    """Détermine si le verdict indique un scope comparable (STRICT ou LOOSE)."""
    return verdict.level in (
        ComparabilityLevel.COMPARABLE_STRICT,
        ComparabilityLevel.COMPARABLE_LOOSE,
    )


def _classify_comparison(
    qs_a: QuestionSignature,
    qs_b: QuestionSignature,
    verdict: ComparabilityVerdict,
    value_diff: ValueDiff,
) -> Tuple[ComparisonType, float, str]:
    """
    Classifie la comparaison entre deux QS.

    Returns:
        (ComparisonType, confidence, explanation)
    """
    same_scope = _is_same_scope(verdict)
    comparable_scope = _is_comparable_scope(verdict)
    same_doc = qs_a.doc_id == qs_b.doc_id

    # Vérifier si les anchors sont identiques (même si verdict=LOOSE à cause du scope_basis)
    same_anchor = _have_same_anchor(qs_a, qs_b)

    if value_diff.values_equal:
        if same_scope or same_anchor:
            # Même valeur + même scope/anchor = confirmation
            conf = 0.95 if same_scope else 0.80
            return (
                ComparisonType.AGREEMENT,
                conf,
                f"Both documents state {value_diff.value_a} for {qs_a.dimension_key}",
            )
        elif comparable_scope:
            # Même valeur + scopes différents mais comparables = convergence
            return (
                ComparisonType.CONVERGENCE,
                0.75,
                f"Different scopes converge on {value_diff.value_a} for {qs_a.dimension_key}",
            )
        else:
            return (
                ComparisonType.AGREEMENT,
                0.60,
                f"Both documents state {value_diff.value_a} for {qs_a.dimension_key} (weak scope)",
            )

    # Valeurs différentes
    if same_scope or comparable_scope:
        if same_doc:
            # Même doc + scope compatible + valeurs différentes = contradiction
            return (
                ComparisonType.CONTRADICTION,
                0.90,
                f"Same document states {value_diff.value_a} and {value_diff.value_b} "
                f"for {qs_a.dimension_key}",
            )
        else:
            # Docs différents + scope compatible + valeurs différentes = évolution
            direction_info = ""
            if value_diff.direction:
                direction_info = f" ({value_diff.direction})"

            conf = 0.85 if same_scope else 0.70
            return (
                ComparisonType.EVOLUTION,
                conf,
                f"Value changed from {value_diff.value_a} to {value_diff.value_b}"
                f"{direction_info} for {qs_a.dimension_key}",
            )

    # Scopes non comparables + valeurs différentes
    return (
        ComparisonType.UNDETERMINED,
        0.40,
        f"Different scopes and values for {qs_a.dimension_key} — cannot determine relationship",
    )


def compare_pair(
    qs_a: QuestionSignature,
    qs_b: QuestionSignature,
) -> Optional[ComparisonResult]:
    """
    Compare deux QuestionSignatures et produit un résultat structuré.

    Returns:
        ComparisonResult si les QS sont comparables, None si NOT_COMPARABLE.
    """
    verdict = are_comparable(qs_a, qs_b)

    # NOT_COMPARABLE → pas de résultat
    if verdict.level == ComparabilityLevel.NOT_COMPARABLE:
        return None

    value_diff = _compute_value_diff(qs_a, qs_b)
    comp_type, confidence, explanation = _classify_comparison(qs_a, qs_b, verdict, value_diff)

    return ComparisonResult(
        comparison_type=comp_type,
        comparability=verdict,
        qs_a_id=qs_a.qs_id,
        qs_b_id=qs_b.qs_id,
        qs_a_claim_id=qs_a.claim_id,
        qs_b_claim_id=qs_b.claim_id,
        qs_a_doc_id=qs_a.doc_id,
        qs_b_doc_id=qs_b.doc_id,
        dimension_id=qs_a.dimension_id,
        dimension_key=qs_a.dimension_key,
        canonical_question=qs_a.canonical_question or qs_a.question,
        value_diff=value_diff,
        scope_a_label=_get_scope_label(qs_a),
        scope_b_label=_get_scope_label(qs_b),
        same_scope=_is_comparable_scope(verdict),
        confidence=confidence,
        explanation=explanation,
    )


def find_comparable_pairs(
    signatures: List[QuestionSignature],
) -> List[Tuple[QuestionSignature, QuestionSignature]]:
    """
    Groupe les QS par dimension_id et retourne les paires comparables.

    Complexité : O(n²) par dimension mais chaque dimension devrait avoir
    un nombre limité de QS. Total typique : quelques centaines de paires.
    """
    # Grouper par dimension_id
    by_dimension: Dict[str, List[QuestionSignature]] = defaultdict(list)
    for qs in signatures:
        key = qs.dimension_id or qs.dimension_key
        by_dimension[key].append(qs)

    pairs: List[Tuple[QuestionSignature, QuestionSignature]] = []

    for dim_key, group in by_dimension.items():
        if len(group) < 2:
            continue

        # Générer toutes les paires uniques
        for i in range(len(group)):
            for j in range(i + 1, len(group)):
                qs_a, qs_b = group[i], group[j]
                verdict = are_comparable(qs_a, qs_b)
                if verdict.level != ComparabilityLevel.NOT_COMPARABLE:
                    pairs.append((qs_a, qs_b))

    return pairs


def compare_all(
    signatures: List[QuestionSignature],
) -> List[ComparisonResult]:
    """
    Compare toutes les paires comparables dans un ensemble de QS.

    Pipeline :
    1. Grouper par dimension
    2. Trouver les paires comparables
    3. Classifier chaque paire

    Returns:
        Liste de ComparisonResult triée par confiance décroissante
    """
    pairs = find_comparable_pairs(signatures)
    logger.info("Paires comparables trouvées: %d", len(pairs))

    results: List[ComparisonResult] = []
    for qs_a, qs_b in pairs:
        result = compare_pair(qs_a, qs_b)
        if result:
            results.append(result)

    # Trier par confiance décroissante
    results.sort(key=lambda r: r.confidence, reverse=True)

    # Log résumé
    type_counts: Dict[str, int] = defaultdict(int)
    for r in results:
        type_counts[r.comparison_type.value] += 1
    logger.info("Résultats comparaison: %s", dict(type_counts))

    return results


__all__ = [
    "ComparisonType",
    "ComparisonResult",
    "ValueDiff",
    "compare_pair",
    "find_comparable_pairs",
    "compare_all",
]
