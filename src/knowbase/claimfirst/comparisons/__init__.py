# src/knowbase/claimfirst/comparisons/__init__.py
"""
Moteur de comparaison cross-doc basé sur QuestionSignatures.

Détecte :
- Évolutions : même dimension + même scope + valeur différente entre docs/releases
- Contradictions : même dimension + même scope + même release + valeurs incompatibles
- Convergences : même dimension + scopes différents + valeurs identiques
"""

from knowbase.claimfirst.comparisons.qs_comparator import (
    ComparisonType,
    ComparisonResult,
    compare_pair,
    find_comparable_pairs,
    compare_all,
)

__all__ = [
    "ComparisonType",
    "ComparisonResult",
    "compare_pair",
    "find_comparable_pairs",
    "compare_all",
]
