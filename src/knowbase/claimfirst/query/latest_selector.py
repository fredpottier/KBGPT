# src/knowbase/claimfirst/query/latest_selector.py
"""
LatestSelector - Sélection du contexte "latest" avec gouvernance.

INV-20: Authority unknown → ask, pas score (fallback si axis CERTAIN)
S5: Fallback déclaré si primary axis CERTAIN et >50% authority unknown

Séparation des responsabilités:
- LatestSelector: Mécanique de sélection
- LatestPolicy: Règles de gouvernance déclaratives
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from knowbase.claimfirst.models.applicability_axis import (
    ApplicabilityAxis,
    OrderingConfidence,
)
from knowbase.claimfirst.models.context_comparability import (
    DocumentAuthority,
    LatestSelectionCriteria,
    LatestSelectionResult,
    TieBreakingStrategy,
)

logger = logging.getLogger(__name__)


@dataclass
class DocumentCandidate:
    """
    Candidat pour la sélection "latest".

    Attributes:
        doc_id: ID du document
        context_value: Valeur du contexte (ex: "2023", "3.0")
        axis_key: Clé de l'axe
        authority: Niveau d'autorité du document
        status: Statut du document
        document_type: Type de document
        metadata: Métadonnées additionnelles
    """
    doc_id: str
    context_value: str
    axis_key: str
    authority: DocumentAuthority = DocumentAuthority.UNKNOWN
    status: Optional[str] = None
    document_type: Optional[str] = None
    metadata: Dict[str, Any] = None

    def __post_init__(self):
        if self.metadata is None:
            self.metadata = {}


class LatestPolicy:
    """
    Politique de gouvernance pour la sélection "latest".

    S5: Fallback axis ordering si authority unknown et axis CERTAIN.
    """

    def __init__(
        self,
        primary_axis: str = "release_id",
        authority_ranking: Optional[List[DocumentAuthority]] = None,
        required_status: Optional[str] = None,
        excluded_types: Optional[List[str]] = None,
        on_tie: TieBreakingStrategy = TieBreakingStrategy.ASK_USER,
        allow_axis_fallback: bool = True,
        min_authority_known_ratio: float = 0.5,
    ):
        """
        Initialise la politique.

        Args:
            primary_axis: Axe principal pour l'ordonnancement
            authority_ranking: Ordre de priorité des autorités
            required_status: Statut requis (ex: "active")
            excluded_types: Types de documents exclus
            on_tie: Stratégie de départage
            allow_axis_fallback: Autoriser fallback sur l'axe si authority unknown
            min_authority_known_ratio: Ratio minimum d'autorités connues
        """
        self.primary_axis = primary_axis
        self.authority_ranking = authority_ranking or [
            DocumentAuthority.OFFICIAL,
            DocumentAuthority.VERIFIED,
            DocumentAuthority.COMMUNITY,
        ]
        self.required_status = required_status
        self.excluded_types = excluded_types or []
        self.on_tie = on_tie
        self.allow_axis_fallback = allow_axis_fallback
        self.min_authority_known_ratio = min_authority_known_ratio

    def to_criteria(self) -> LatestSelectionCriteria:
        """Convertit en LatestSelectionCriteria."""
        return LatestSelectionCriteria(
            primary_axis=self.primary_axis,
            authority_ranking=self.authority_ranking,
            required_status=self.required_status,
            excluded_types=self.excluded_types,
            on_tie=self.on_tie,
            allow_axis_fallback=self.allow_axis_fallback,
            min_authority_known_ratio=self.min_authority_known_ratio,
        )


class LatestSelector:
    """
    Sélectionne le contexte "latest" parmi les candidats.

    INV-20: Authority unknown → ask, pas score
    S5: Fallback to axis ordering si:
        - >50% authority unknown
        - ET primary axis ordering_confidence == CERTAIN
        - ET allow_axis_fallback == True

    La réponse inclut toujours `why_selected` pour traçabilité.
    """

    def __init__(
        self,
        default_policy: Optional[LatestPolicy] = None,
    ):
        """
        Initialise le sélecteur.

        Args:
            default_policy: Politique par défaut
        """
        self.default_policy = default_policy or LatestPolicy()

        self.stats = {
            "selections_made": 0,
            "authority_based": 0,
            "axis_fallback": 0,
            "ask_user": 0,
            "ties_resolved": 0,
        }

    def select_latest(
        self,
        candidates: List[DocumentCandidate],
        axes: Dict[str, ApplicabilityAxis],
        policy: Optional[LatestPolicy] = None,
        subject_filter: Optional[str] = None,
    ) -> LatestSelectionResult:
        """
        Sélectionne le document "latest" parmi les candidats.

        Args:
            candidates: Documents candidats
            axes: Axes d'applicabilité disponibles
            policy: Politique de gouvernance (ou default)
            subject_filter: Filtre optionnel sur le sujet

        Returns:
            LatestSelectionResult avec why_selected
        """
        self.stats["selections_made"] += 1
        policy = policy or self.default_policy

        if not candidates:
            return LatestSelectionResult(
                selected_doc_id=None,
                why_selected="No candidates provided",
                candidates_count=0,
            )

        # Filtrer par statut et type exclus
        filtered = self._apply_filters(candidates, policy)

        if not filtered:
            return LatestSelectionResult(
                selected_doc_id=None,
                why_selected=f"All {len(candidates)} candidates filtered out by policy",
                candidates_count=len(candidates),
            )

        # Calculer le ratio d'autorités connues
        known_authorities = [
            c for c in filtered
            if c.authority != DocumentAuthority.UNKNOWN
        ]
        authority_ratio = len(known_authorities) / len(filtered)

        # INV-20 + S5: Décider de la stratégie
        primary_axis = axes.get(policy.primary_axis)
        axis_is_certain = (
            primary_axis is not None and
            primary_axis.ordering_confidence == OrderingConfidence.CERTAIN and
            primary_axis.value_order is not None
        )

        # Cas 1: Assez d'autorités connues → sélection par autorité
        if authority_ratio >= policy.min_authority_known_ratio:
            return self._select_by_authority(filtered, policy, primary_axis)

        # Cas 2: S5 - Fallback axis si CERTAIN et autorisé
        if policy.allow_axis_fallback and axis_is_certain:
            return self._select_by_axis_fallback(filtered, primary_axis, policy)

        # Cas 3: INV-20 - Ask user
        return self._ask_user(filtered, policy, authority_ratio)

    def _apply_filters(
        self,
        candidates: List[DocumentCandidate],
        policy: LatestPolicy,
    ) -> List[DocumentCandidate]:
        """
        Applique les filtres de la politique.

        Args:
            candidates: Candidats à filtrer
            policy: Politique de gouvernance

        Returns:
            Candidats filtrés
        """
        filtered = candidates

        # Filtrer par statut requis
        if policy.required_status:
            filtered = [
                c for c in filtered
                if c.status == policy.required_status
            ]

        # Filtrer par types exclus
        if policy.excluded_types:
            filtered = [
                c for c in filtered
                if c.document_type not in policy.excluded_types
            ]

        return filtered

    def _select_by_authority(
        self,
        candidates: List[DocumentCandidate],
        policy: LatestPolicy,
        axis: Optional[ApplicabilityAxis],
    ) -> LatestSelectionResult:
        """
        Sélectionne par autorité + axe en cas d'égalité.

        Args:
            candidates: Candidats filtrés
            policy: Politique de gouvernance
            axis: Axe pour départage

        Returns:
            LatestSelectionResult
        """
        self.stats["authority_based"] += 1

        # Trier par autorité (meilleure en premier)
        def authority_rank(c: DocumentCandidate) -> int:
            try:
                return policy.authority_ranking.index(c.authority)
            except ValueError:
                return len(policy.authority_ranking)  # Unknown = dernier

        sorted_by_authority = sorted(candidates, key=authority_rank)

        # Grouper par autorité égale
        best_authority = sorted_by_authority[0].authority
        same_authority = [c for c in sorted_by_authority if c.authority == best_authority]

        if len(same_authority) == 1:
            selected = same_authority[0]
            return LatestSelectionResult(
                selected_doc_id=selected.doc_id,
                selected_context_value=selected.context_value,
                why_selected=f"Highest authority ({selected.authority.value})",
                candidates_count=len(candidates),
                fallback_used=False,
            )

        # Égalité d'autorité → départager par axe
        if axis and axis.value_order:
            self.stats["ties_resolved"] += 1
            return self._tiebreak_by_axis(same_authority, axis, policy)

        # Pas d'axe → appliquer stratégie on_tie
        return self._apply_tie_strategy(same_authority, policy)

    def _select_by_axis_fallback(
        self,
        candidates: List[DocumentCandidate],
        axis: ApplicabilityAxis,
        policy: LatestPolicy,
    ) -> LatestSelectionResult:
        """
        S5: Fallback to axis ordering car >50% authority unknown.

        Args:
            candidates: Candidats filtrés
            axis: Axe CERTAIN pour l'ordre
            policy: Politique

        Returns:
            LatestSelectionResult avec fallback déclaré
        """
        self.stats["axis_fallback"] += 1

        # Trier par position dans value_order (dernier = latest)
        def axis_position(c: DocumentCandidate) -> int:
            try:
                return axis.value_order.index(c.context_value)
            except (ValueError, TypeError):
                return -1  # Valeur inconnue = début

        valid_candidates = [
            c for c in candidates
            if c.context_value in (axis.value_order or [])
        ]

        if not valid_candidates:
            return LatestSelectionResult(
                selected_doc_id=None,
                why_selected="No candidates match known axis values",
                candidates_count=len(candidates),
                fallback_used=True,
                fallback_reason="Axis fallback attempted but no matching values",
            )

        sorted_by_axis = sorted(valid_candidates, key=axis_position, reverse=True)
        selected = sorted_by_axis[0]

        return LatestSelectionResult(
            selected_doc_id=selected.doc_id,
            selected_context_value=selected.context_value,
            why_selected=(
                f"Selected by axis ordering (fallback): "
                f"{axis.axis_key}={selected.context_value} is latest"
            ),
            candidates_count=len(candidates),
            fallback_used=True,
            fallback_reason=(
                f">50% authority unknown, using {axis.axis_key} "
                f"(confidence={axis.ordering_confidence.value})"
            ),
            alternatives=[
                {"doc_id": c.doc_id, "context_value": c.context_value}
                for c in sorted_by_axis[1:4]
            ],
        )

    def _ask_user(
        self,
        candidates: List[DocumentCandidate],
        policy: LatestPolicy,
        authority_ratio: float,
    ) -> LatestSelectionResult:
        """
        INV-20: Demander à l'utilisateur car authority unknown.

        Args:
            candidates: Candidats
            policy: Politique
            authority_ratio: Ratio d'autorités connues

        Returns:
            LatestSelectionResult avec ask_user_needed=True
        """
        self.stats["ask_user"] += 1

        return LatestSelectionResult(
            selected_doc_id=None,
            why_selected="Cannot determine latest automatically",
            candidates_count=len(candidates),
            ask_user_needed=True,
            ask_user_reason=(
                f"Only {authority_ratio*100:.0f}% of document authorities are known. "
                f"Axis fallback not available or not allowed. "
                f"Please select which document represents the 'latest' context."
            ),
            alternatives=[
                {
                    "doc_id": c.doc_id,
                    "context_value": c.context_value,
                    "authority": c.authority.value,
                    "document_type": c.document_type,
                }
                for c in candidates[:5]
            ],
        )

    def _tiebreak_by_axis(
        self,
        candidates: List[DocumentCandidate],
        axis: ApplicabilityAxis,
        policy: LatestPolicy,
    ) -> LatestSelectionResult:
        """
        Départage par axe en cas d'égalité d'autorité.

        Args:
            candidates: Candidats à égalité d'autorité
            axis: Axe pour départage
            policy: Politique

        Returns:
            LatestSelectionResult
        """
        def axis_position(c: DocumentCandidate) -> int:
            try:
                return axis.value_order.index(c.context_value)
            except (ValueError, TypeError):
                return -1

        sorted_candidates = sorted(candidates, key=axis_position, reverse=True)
        selected = sorted_candidates[0]

        return LatestSelectionResult(
            selected_doc_id=selected.doc_id,
            selected_context_value=selected.context_value,
            why_selected=(
                f"Highest authority ({selected.authority.value}), "
                f"tiebreak by {axis.axis_key}={selected.context_value}"
            ),
            candidates_count=len(candidates),
            fallback_used=False,
        )

    def _apply_tie_strategy(
        self,
        candidates: List[DocumentCandidate],
        policy: LatestPolicy,
    ) -> LatestSelectionResult:
        """
        Applique la stratégie de départage de la politique.

        Args:
            candidates: Candidats à égalité
            policy: Politique

        Returns:
            LatestSelectionResult
        """
        if policy.on_tie == TieBreakingStrategy.LATEST_WINS:
            # Prendre arbitrairement le premier
            selected = candidates[0]
            return LatestSelectionResult(
                selected_doc_id=selected.doc_id,
                selected_context_value=selected.context_value,
                why_selected="Tie resolved by LATEST_WINS strategy (arbitrary selection)",
                candidates_count=len(candidates),
            )

        elif policy.on_tie == TieBreakingStrategy.RETURN_ALL:
            return LatestSelectionResult(
                selected_doc_id=None,
                why_selected="Tie: returning all candidates",
                candidates_count=len(candidates),
                alternatives=[
                    {"doc_id": c.doc_id, "context_value": c.context_value}
                    for c in candidates
                ],
            )

        else:  # ASK_USER or HIGHEST_AUTHORITY (already tried)
            return LatestSelectionResult(
                selected_doc_id=None,
                why_selected="Tie: user selection needed",
                candidates_count=len(candidates),
                ask_user_needed=True,
                ask_user_reason="Multiple candidates with same authority, please select.",
                alternatives=[
                    {"doc_id": c.doc_id, "context_value": c.context_value}
                    for c in candidates
                ],
            )

    def get_stats(self) -> Dict[str, int]:
        """Retourne les statistiques."""
        return dict(self.stats)

    def reset_stats(self) -> None:
        """Réinitialise les statistiques."""
        self.stats = {
            "selections_made": 0,
            "authority_based": 0,
            "axis_fallback": 0,
            "ask_user": 0,
            "ties_resolved": 0,
        }


__all__ = [
    "LatestSelector",
    "LatestPolicy",
    "DocumentCandidate",
]
