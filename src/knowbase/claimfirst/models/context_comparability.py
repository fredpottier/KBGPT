# src/knowbase/claimfirst/models/context_comparability.py
"""
Modèles pour la comparabilité des contextes documentaires.

ComparabilityResult: Résultat de comparaison entre contextes
LatestSelectionCriteria: Critères de gouvernance pour sélection "latest"

INV-20: Authority unknown → ask, pas score (fallback si axis CERTAIN)
S5: Fallback déclaré si primary axis CERTAIN

Ces modèles supportent les questions temporelles du type:
- "Encore applicable aujourd'hui?" (sélection du latest)
- "Différences entre contexte A et B?" (comparaison)
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class ComparabilityStatus(str, Enum):
    """Statut de comparabilité entre deux contextes."""

    COMPARABLE = "comparable"
    """Les contextes peuvent être comparés sur au moins un axe."""

    INCOMPARABLE = "incomparable"
    """Aucun axe commun permettant la comparaison."""

    EQUIVALENT = "equivalent"
    """Les contextes sont équivalents (mêmes valeurs sur tous les axes)."""

    PARTIAL = "partial"
    """Comparaison partielle (certains axes comparables, d'autres non)."""


class ContextOrdering(str, Enum):
    """Résultat de l'ordonnancement de deux contextes."""

    BEFORE = "before"
    """Contexte A est avant contexte B (plus ancien)."""

    AFTER = "after"
    """Contexte A est après contexte B (plus récent)."""

    SAME = "same"
    """Contextes au même niveau."""

    UNKNOWN = "unknown"
    """Ordre inconnu (axes non ordonnables ou manquants)."""


class ComparabilityResult(BaseModel):
    """
    Résultat de comparaison entre deux contextes documentaires.

    Attributes:
        status: Statut de comparabilité
        comparable_axes: Axes sur lesquels la comparaison est possible
        ordering: Résultat de l'ordonnancement global
        axis_orderings: Ordonnancement par axe
        confidence: Confiance globale dans la comparaison
        reason: Explication du résultat
    """

    status: ComparabilityStatus = Field(
        ...,
        description="Statut de comparabilité"
    )

    comparable_axes: List[str] = Field(
        default_factory=list,
        description="Clés des axes permettant la comparaison"
    )

    ordering: ContextOrdering = Field(
        default=ContextOrdering.UNKNOWN,
        description="Ordonnancement global des contextes"
    )

    axis_orderings: Dict[str, ContextOrdering] = Field(
        default_factory=dict,
        description="Ordonnancement par axe: {axis_key: ordering}"
    )

    confidence: float = Field(
        default=0.0,
        ge=0.0,
        le=1.0,
        description="Confiance globale dans la comparaison [0-1]"
    )

    reason: Optional[str] = Field(
        default=None,
        description="Explication du résultat de comparaison"
    )

    def is_orderable(self) -> bool:
        """Vérifie si les contextes peuvent être ordonnés."""
        return self.ordering != ContextOrdering.UNKNOWN

    def get_primary_ordering(self) -> Optional[ContextOrdering]:
        """
        Retourne l'ordonnancement sur l'axe principal.

        Returns:
            Ordonnancement ou None si aucun axe comparable
        """
        if self.comparable_axes and self.axis_orderings:
            primary = self.comparable_axes[0]
            return self.axis_orderings.get(primary)
        return None


class DocumentAuthority(str, Enum):
    """Niveau d'autorité d'un document."""

    OFFICIAL = "official"
    """Document officiel (ex: documentation produit)."""

    VERIFIED = "verified"
    """Document vérifié par un expert."""

    COMMUNITY = "community"
    """Document communautaire (moins fiable)."""

    UNKNOWN = "unknown"
    """Autorité inconnue."""


class TieBreakingStrategy(str, Enum):
    """Stratégie de départage en cas d'égalité."""

    LATEST_WINS = "latest_wins"
    """Le plus récent l'emporte."""

    HIGHEST_AUTHORITY = "highest_authority"
    """La plus haute autorité l'emporte."""

    ASK_USER = "ask_user"
    """Demander à l'utilisateur."""

    RETURN_ALL = "return_all"
    """Retourner tous les candidats."""


class LatestSelectionCriteria(BaseModel):
    """
    Critères de gouvernance pour la sélection du contexte "latest".

    INV-20: Authority unknown → ask, pas score
    S5: Fallback axis ordering si primary axis CERTAIN

    Attributes:
        primary_axis: Axe principal pour l'ordonnancement
        authority_ranking: Ordre de priorité des autorités
        required_status: Statut requis (ex: "active", "published")
        excluded_types: Types de documents exclus
        on_tie: Stratégie de départage
        allow_axis_fallback: Autoriser le fallback sur l'axe si authority unknown
        min_authority_known_ratio: Ratio minimum d'autorités connues avant ask
    """

    primary_axis: str = Field(
        default="release_id",
        description="Clé de l'axe principal pour l'ordonnancement"
    )

    authority_ranking: List[DocumentAuthority] = Field(
        default_factory=lambda: [
            DocumentAuthority.OFFICIAL,
            DocumentAuthority.VERIFIED,
            DocumentAuthority.COMMUNITY,
        ],
        description="Ordre de priorité des autorités"
    )

    required_status: Optional[str] = Field(
        default=None,
        description="Statut requis pour le document (ex: 'active')"
    )

    excluded_types: List[str] = Field(
        default_factory=list,
        description="Types de documents exclus (ex: ['draft', 'deprecated'])"
    )

    on_tie: TieBreakingStrategy = Field(
        default=TieBreakingStrategy.ASK_USER,
        description="Stratégie de départage en cas d'égalité"
    )

    # S5: Fallback si authority unknown
    allow_axis_fallback: bool = Field(
        default=True,
        description="Si True, utiliser l'axe si authority unknown et axis CERTAIN"
    )

    min_authority_known_ratio: float = Field(
        default=0.5,
        ge=0.0,
        le=1.0,
        description="Ratio minimum d'autorités connues avant fallback/ask"
    )


class LatestSelectionResult(BaseModel):
    """
    Résultat de la sélection du contexte "latest".

    Attributes:
        selected_doc_id: Document sélectionné comme latest
        selected_context_value: Valeur du contexte sélectionné
        why_selected: Explication de la sélection (INV-23)
        candidates_count: Nombre de candidats évalués
        fallback_used: Si un fallback a été utilisé
        fallback_reason: Raison du fallback (si applicable)
        alternatives: Alternatives possibles (si disambiguation)
        ask_user_needed: Si une question utilisateur est nécessaire
        ask_user_reason: Raison de la question (si applicable)
    """

    selected_doc_id: Optional[str] = Field(
        default=None,
        description="Document ID sélectionné comme latest"
    )

    selected_context_value: Optional[str] = Field(
        default=None,
        description="Valeur du contexte sélectionné (ex: '2023', '3.0')"
    )

    why_selected: str = Field(
        ...,
        description="Explication de la sélection (INV-23 traçabilité)"
    )

    candidates_count: int = Field(
        default=0,
        ge=0,
        description="Nombre de candidats évalués"
    )

    # S5: Fallback tracking
    fallback_used: bool = Field(
        default=False,
        description="Si un fallback a été utilisé"
    )

    fallback_reason: Optional[str] = Field(
        default=None,
        description="Raison du fallback (si applicable)"
    )

    alternatives: List[Dict[str, Any]] = Field(
        default_factory=list,
        description="Alternatives possibles avec leurs contextes"
    )

    # INV-20: Ask user si authority unknown
    ask_user_needed: bool = Field(
        default=False,
        description="Si une question utilisateur est nécessaire"
    )

    ask_user_reason: Optional[str] = Field(
        default=None,
        description="Raison de la question utilisateur"
    )

    def is_definitive(self) -> bool:
        """Vérifie si la sélection est définitive (pas de question user)."""
        return not self.ask_user_needed and self.selected_doc_id is not None


__all__ = [
    "ComparabilityResult",
    "ComparabilityStatus",
    "ContextOrdering",
    "DocumentAuthority",
    "LatestSelectionCriteria",
    "LatestSelectionResult",
    "TieBreakingStrategy",
]
