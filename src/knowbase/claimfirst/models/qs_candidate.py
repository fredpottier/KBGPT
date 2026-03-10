# src/knowbase/claimfirst/models/qs_candidate.py
"""
QSCandidate — Objet intermédiaire entre extraction LLM et stabilisation.

Sortie de l'étape 2 (extraction structurée LLM), avant :
- Mapping vers QuestionDimension (étape 3a)
- Résolution du scope (étape 3b)
- Normalisation de la valeur (étape 3c)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional

from knowbase.claimfirst.models.question_dimension import (
    VALID_OPERATORS,
    VALID_VALUE_TYPES,
)


@dataclass
class QSCandidate:
    """Sortie brute de l'extraction LLM (étape 2)."""

    claim_id: str
    doc_id: str

    # Question (brouillon — sera normalisé par le Dimension Mapper)
    candidate_question: str
    candidate_dimension_key: str

    # Value (contrat strict — listes fermées)
    value_type: str       # number|version|boolean|percent|enum|string
    value_raw: str
    value_normalized: Optional[str] = None
    operator: str = "="   # =|>=|<=|>|<|approx|in

    # Scope evidence (brut, pas encore résolu)
    scope_evidence: Optional[str] = None
    scope_basis: str = "claim_explicit"

    # Meta
    confidence: float = 0.0
    abstain_reason: Optional[str] = None

    # Gate info (traçabilité)
    gate_label: str = ""
    gating_signals: List[str] = field(default_factory=list)

    def is_valid(self) -> bool:
        """Vérifie que les listes fermées sont respectées."""
        return (
            self.value_type in VALID_VALUE_TYPES
            and self.operator in VALID_OPERATORS
            and self.abstain_reason is None
        )


__all__ = [
    "QSCandidate",
]
