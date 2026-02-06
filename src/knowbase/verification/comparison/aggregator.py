"""
OSMOSE Verification - Aggregator Policy

Agrégation des résultats de comparaison assertion vs N claims.
Gère les conflits, priorité par autorité, et verdict final.

Author: Claude Code
Date: 2026-02-03
Version: 1.1
"""

from dataclasses import dataclass, field
from typing import List, Optional, Any, Dict
from enum import Enum

from knowbase.verification.comparison.reason_codes import ReasonCode
from knowbase.verification.comparison.value_algebra import AuthorityLevel


class ComparisonResult(str, Enum):
    """
    Résultats possibles d'une comparaison.

    Mapping vers UI:
    - SUPPORTS → 🟢 Vert (CONFIRMED)
    - CONTRADICTS → 🔴 Rouge (CONTRADICTED)
    - PARTIAL → 🟠 Orange (INCOMPLETE)
    - NEEDS_SCOPE → 🟠 Orange (INCOMPLETE, reason différente)
    - UNKNOWN → ⬜ Gris (UNKNOWN)
    """
    SUPPORTS = "SUPPORTS"
    CONTRADICTS = "CONTRADICTS"
    PARTIAL = "PARTIAL"
    NEEDS_SCOPE = "NEEDS_SCOPE"  # Vérité indexée, impossible de conclure
    UNKNOWN = "UNKNOWN"


@dataclass
class ComparisonExplanation:
    """Explication détaillée d'une comparaison."""
    result: ComparisonResult
    reason_code: ReasonCode
    confidence: float  # 0.0 - 1.0
    details: Dict[str, Any] = field(default_factory=dict)

    def get_display_reason(self, locale: str = "fr") -> str:
        """Génère le message lisible."""
        from knowbase.verification.comparison.reason_codes import get_reason_message
        return get_reason_message(self.reason_code, self.details, locale)


@dataclass
class ClaimComparison:
    """Résultat de comparaison assertion vs un claim."""
    claim: Dict[str, Any]  # Données du claim (from Neo4j)
    claim_form: Any  # ClaimForm
    explanation: ComparisonExplanation
    authority: AuthorityLevel = AuthorityLevel.MEDIUM
    scope_match_score: float = 1.0  # 1.0 = scope parfait, 0.5 = partiel


@dataclass
class AggregatedResult:
    """Résultat agrégé de toutes les comparaisons."""
    result: ComparisonResult
    reason_code: ReasonCode
    confidence: float
    details: Dict[str, Any] = field(default_factory=dict)

    # Claims utilisés pour le verdict
    primary_claim: Optional[ClaimComparison] = None
    supporting_claims: List[ClaimComparison] = field(default_factory=list)
    conflicting_claims: List[ClaimComparison] = field(default_factory=list)

    def get_display_reason(self, locale: str = "fr") -> str:
        """Génère le message lisible."""
        from knowbase.verification.comparison.reason_codes import get_reason_message
        return get_reason_message(self.reason_code, self.details, locale)


class AggregatorPolicy:
    """
    Agrège les résultats de comparaison assertion vs N claims.

    Stratégie:
    1. Trier par (authority DESC, scope_match DESC, confidence DESC)
    2. Détecter conflits entre claims de même autorité/scope
    3. Utiliser le "best claim" pour le verdict
    4. Accumuler evidence supportante/conflictuelle
    """

    def __init__(self):
        # Poids pour le scoring
        self.authority_weights = {
            AuthorityLevel.HIGH: 3.0,
            AuthorityLevel.MEDIUM: 2.0,
            AuthorityLevel.LOW: 1.0,
        }

    def aggregate(
        self,
        assertion_form: Any,  # ClaimForm
        comparisons: List[ClaimComparison]
    ) -> AggregatedResult:
        """
        Agrège les comparaisons pour produire un verdict final.

        Args:
            assertion_form: Forme structurée de l'assertion
            comparisons: Liste des comparaisons claim par claim

        Returns:
            AggregatedResult avec verdict, raison, et claims utilisés
        """
        if not comparisons:
            return AggregatedResult(
                result=ComparisonResult.UNKNOWN,
                reason_code=ReasonCode.INSUFFICIENT_EVIDENCE,
                confidence=0.0,
                details={"message": "Aucun claim comparable trouvé"}
            )

        # 1. Filtrer les comparaisons UNKNOWN (non comparables)
        valid_comparisons = [
            c for c in comparisons
            if c.explanation.result != ComparisonResult.UNKNOWN
        ]

        if not valid_comparisons:
            # Tous UNKNOWN = fallback au meilleur guess
            return self._handle_all_unknown(comparisons)

        # 2. Trier par priorité
        sorted_comparisons = self._sort_by_priority(valid_comparisons)

        # 3. Détecter conflits entre claims de même autorité
        has_conflicts, conflict_details = self._detect_conflicts(sorted_comparisons)

        if has_conflicts:
            return AggregatedResult(
                result=ComparisonResult.UNKNOWN,
                reason_code=ReasonCode.CONFLICTING_EVIDENCE,
                confidence=0.5,
                details=conflict_details,
                conflicting_claims=sorted_comparisons[:2]  # Top 2 en conflit
            )

        # 4. Vérifier si que des sources LOW authority
        if all(c.authority == AuthorityLevel.LOW for c in sorted_comparisons):
            best = sorted_comparisons[0]
            return AggregatedResult(
                result=best.explanation.result,
                reason_code=ReasonCode.LOW_AUTHORITY_ONLY,
                confidence=best.explanation.confidence * 0.7,  # Pénalité
                details={
                    "warning": "Seules des sources de faible autorité disponibles",
                    **best.explanation.details
                },
                primary_claim=best
            )

        # 5. Utiliser le best claim pour le verdict
        best = sorted_comparisons[0]

        # Collecter les claims supportants et conflictuels
        supporting = [
            c for c in sorted_comparisons[1:]
            if c.explanation.result == best.explanation.result
        ]
        conflicting = [
            c for c in sorted_comparisons[1:]
            if c.explanation.result != best.explanation.result and
               c.explanation.result != ComparisonResult.UNKNOWN
        ]

        return AggregatedResult(
            result=best.explanation.result,
            reason_code=best.explanation.reason_code,
            confidence=self._compute_aggregate_confidence(best, supporting),
            details=best.explanation.details,
            primary_claim=best,
            supporting_claims=supporting,
            conflicting_claims=conflicting
        )

    def _sort_by_priority(
        self,
        comparisons: List[ClaimComparison]
    ) -> List[ClaimComparison]:
        """
        Trie les comparaisons par priorité décroissante.

        Priority = authority_weight * scope_match * confidence
        """
        def priority_key(c: ClaimComparison) -> tuple:
            authority_score = self.authority_weights.get(c.authority, 1.0)
            return (
                -authority_score,  # Négatif pour DESC
                -c.scope_match_score,
                -c.explanation.confidence
            )

        return sorted(comparisons, key=priority_key)

    def _detect_conflicts(
        self,
        sorted_comparisons: List[ClaimComparison]
    ) -> tuple[bool, Dict[str, Any]]:
        """
        Détecte les conflits entre claims de même autorité.

        Conflit = même autorité et résultats opposés (SUPPORTS vs CONTRADICTS).
        """
        if len(sorted_comparisons) < 2:
            return False, {}

        # Grouper par autorité
        by_authority: Dict[AuthorityLevel, List[ClaimComparison]] = {}
        for c in sorted_comparisons:
            if c.authority not in by_authority:
                by_authority[c.authority] = []
            by_authority[c.authority].append(c)

        # Chercher conflits dans chaque groupe d'autorité
        for authority, group in by_authority.items():
            if len(group) < 2:
                continue

            results = {c.explanation.result for c in group}

            # SUPPORTS et CONTRADICTS ensemble = conflit
            if ComparisonResult.SUPPORTS in results and ComparisonResult.CONTRADICTS in results:
                return True, {
                    "authority": authority.value,
                    "conflicting_results": [r.value for r in results],
                    "claim_count": len(group)
                }

        return False, {}

    def _handle_all_unknown(
        self,
        comparisons: List[ClaimComparison]
    ) -> AggregatedResult:
        """Gère le cas où toutes les comparaisons sont UNKNOWN."""
        # Prendre le claim avec la meilleure confiance de parsing
        best = max(comparisons, key=lambda c: c.explanation.confidence)

        return AggregatedResult(
            result=ComparisonResult.UNKNOWN,
            reason_code=best.explanation.reason_code,
            confidence=best.explanation.confidence * 0.5,  # Forte pénalité
            details={
                "message": "Aucune comparaison structurée possible",
                **best.explanation.details
            },
            primary_claim=best
        )

    def _compute_aggregate_confidence(
        self,
        primary: ClaimComparison,
        supporting: List[ClaimComparison]
    ) -> float:
        """
        Calcule la confiance agrégée.

        Formule:
        - Base: confiance du primary claim
        - Bonus: +5% par claim supportant (max +20%)
        - Multiplicateur authority: HIGH=1.0, MEDIUM=0.9, LOW=0.8
        """
        base = primary.explanation.confidence

        # Bonus claims supportants
        support_bonus = min(0.20, len(supporting) * 0.05)

        # Multiplicateur autorité
        authority_mult = {
            AuthorityLevel.HIGH: 1.0,
            AuthorityLevel.MEDIUM: 0.9,
            AuthorityLevel.LOW: 0.8,
        }.get(primary.authority, 0.9)

        confidence = (base + support_bonus) * authority_mult

        return min(1.0, confidence)  # Cap à 1.0
