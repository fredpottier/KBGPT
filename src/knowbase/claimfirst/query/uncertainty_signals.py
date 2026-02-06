# src/knowbase/claimfirst/query/uncertainty_signals.py
"""
UncertaintySignals - Signaux d'incertitude pour les réponses temporelles.

Utilisé pour "Still applicable?" quand la réponse n'est pas binaire.

Les signaux ne sont PAS des "likelihood" (probabilités) mais des
heuristic_confidence_hints pour guider l'utilisateur.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional

from pydantic import BaseModel, Field


class UncertaintySignalType(str, Enum):
    """Types de signaux d'incertitude."""

    OLDER_ONLY = "older_only"
    """La claim n'apparaît que dans des contextes plus anciens."""

    REPLACEMENT_MENTIONED = "replacement_mentioned"
    """Un remplacement est mentionné dans un contexte plus récent."""

    RELATED_CLAIMS_PRESENT = "related_claims_present"
    """Des claims connexes existent dans le contexte latest."""

    CONTRADICTING_CLAIM = "contradicting_claim"
    """Une claim contradictoire existe dans un contexte plus récent."""

    ABSENT_IN_LATEST = "absent_in_latest"
    """La claim est absente du contexte latest (≠ removed)."""

    PARTIAL_OVERLAP = "partial_overlap"
    """Chevauchement partiel avec une claim dans le latest."""

    QUALIFIER_MISMATCH = "qualifier_mismatch"
    """Les qualificateurs ne correspondent pas exactement."""

    TEMPORAL_AMBIGUITY = "temporal_ambiguity"
    """L'ordre temporel des contextes est ambigu."""


@dataclass
class UncertaintySignal:
    """
    Signal d'incertitude individuel.

    Attributes:
        signal_type: Type de signal
        description: Description lisible
        evidence_claim_ids: Claims sources du signal
        heuristic_confidence_hint: Indice de confiance heuristique [0-1]
        context_info: Informations de contexte additionnelles
    """

    signal_type: UncertaintySignalType
    description: str
    evidence_claim_ids: List[str] = field(default_factory=list)
    heuristic_confidence_hint: float = 0.5  # Pas une probabilité, juste un hint
    context_info: Dict[str, str] = field(default_factory=dict)


class UncertaintyAnalysis(BaseModel):
    """
    Analyse d'incertitude pour une réponse temporelle.

    Collecte et agrège les signaux d'incertitude pour guider l'utilisateur.
    N'utilise PAS de "likelihood" mais des heuristic_confidence_hints.

    Attributes:
        signals: Liste des signaux détectés
        overall_confidence_hint: Indice de confiance global [0-1]
        recommendation: Recommandation pour l'utilisateur
        needs_user_verification: Si vérification utilisateur nécessaire
    """

    signals: List[UncertaintySignal] = Field(
        default_factory=list,
        description="Signaux d'incertitude détectés"
    )

    overall_confidence_hint: float = Field(
        default=0.5,
        ge=0.0,
        le=1.0,
        description="Indice de confiance global (heuristique, pas probabilité)"
    )

    recommendation: str = Field(
        default="",
        description="Recommandation pour l'utilisateur"
    )

    needs_user_verification: bool = Field(
        default=False,
        description="Si vérification utilisateur recommandée"
    )

    model_config = {"arbitrary_types_allowed": True}

    def add_signal(self, signal: UncertaintySignal) -> None:
        """
        Ajoute un signal et recalcule la confiance globale.

        Args:
            signal: Signal à ajouter
        """
        self.signals.append(signal)
        self._recalculate_confidence()

    def _recalculate_confidence(self) -> None:
        """
        Recalcule l'indice de confiance global.

        Méthode heuristique: moyenne pondérée des signaux.
        """
        if not self.signals:
            self.overall_confidence_hint = 0.5
            return

        # Pondération par type de signal
        weights = {
            UncertaintySignalType.CONTRADICTING_CLAIM: 0.9,
            UncertaintySignalType.REPLACEMENT_MENTIONED: 0.8,
            UncertaintySignalType.ABSENT_IN_LATEST: 0.6,
            UncertaintySignalType.OLDER_ONLY: 0.5,
            UncertaintySignalType.PARTIAL_OVERLAP: 0.4,
            UncertaintySignalType.RELATED_CLAIMS_PRESENT: 0.3,
            UncertaintySignalType.QUALIFIER_MISMATCH: 0.3,
            UncertaintySignalType.TEMPORAL_AMBIGUITY: 0.5,
        }

        total_weight = 0
        weighted_sum = 0

        for signal in self.signals:
            weight = weights.get(signal.signal_type, 0.5)
            total_weight += weight
            # Plus le signal est "négatif", plus la confiance baisse
            weighted_sum += (1 - signal.heuristic_confidence_hint) * weight

        if total_weight > 0:
            uncertainty = weighted_sum / total_weight
            self.overall_confidence_hint = 1 - uncertainty
        else:
            self.overall_confidence_hint = 0.5

    def generate_recommendation(self) -> str:
        """
        Génère une recommandation basée sur les signaux.

        Returns:
            Texte de recommandation
        """
        if not self.signals:
            self.recommendation = "No uncertainty signals detected."
            return self.recommendation

        # Signaux critiques
        critical_signals = [
            s for s in self.signals
            if s.signal_type in [
                UncertaintySignalType.CONTRADICTING_CLAIM,
                UncertaintySignalType.REPLACEMENT_MENTIONED,
            ]
        ]

        if critical_signals:
            self.recommendation = (
                "⚠️ High uncertainty: contradicting or replacement claims found. "
                "Verify with the latest documentation."
            )
            self.needs_user_verification = True
            return self.recommendation

        # Signaux moyens
        medium_signals = [
            s for s in self.signals
            if s.signal_type in [
                UncertaintySignalType.ABSENT_IN_LATEST,
                UncertaintySignalType.OLDER_ONLY,
            ]
        ]

        if medium_signals:
            self.recommendation = (
                "⚡ Moderate uncertainty: claim not found in latest context. "
                "May still be applicable but verification recommended."
            )
            self.needs_user_verification = True
            return self.recommendation

        # Signaux faibles
        self.recommendation = (
            "ℹ️ Low uncertainty: minor signals detected. "
            "Likely still applicable with minor caveats."
        )
        return self.recommendation

    @classmethod
    def analyze(
        cls,
        claim_id: str,
        latest_context_claims: List[str],
        older_context_claims: List[str],
        related_claims: Optional[List[str]] = None,
        contradicting_claims: Optional[List[str]] = None,
    ) -> "UncertaintyAnalysis":
        """
        Factory method pour créer une analyse depuis les données brutes.

        Args:
            claim_id: Claim analysée
            latest_context_claims: Claims du contexte latest
            older_context_claims: Claims des contextes plus anciens
            related_claims: Claims connexes (optionnel)
            contradicting_claims: Claims contradictoires (optionnel)

        Returns:
            UncertaintyAnalysis configurée
        """
        analysis = cls()

        # Signal: Absent in latest
        if claim_id not in latest_context_claims and claim_id in older_context_claims:
            analysis.add_signal(UncertaintySignal(
                signal_type=UncertaintySignalType.ABSENT_IN_LATEST,
                description="Claim not found in latest context documents",
                evidence_claim_ids=[claim_id],
                heuristic_confidence_hint=0.4,
            ))

        # Signal: Older only
        if claim_id in older_context_claims and not latest_context_claims:
            analysis.add_signal(UncertaintySignal(
                signal_type=UncertaintySignalType.OLDER_ONLY,
                description="Claim only found in older context documents",
                evidence_claim_ids=[claim_id],
                heuristic_confidence_hint=0.3,
            ))

        # Signal: Related claims present
        if related_claims:
            analysis.add_signal(UncertaintySignal(
                signal_type=UncertaintySignalType.RELATED_CLAIMS_PRESENT,
                description=f"Found {len(related_claims)} related claims in latest context",
                evidence_claim_ids=related_claims[:5],
                heuristic_confidence_hint=0.7,
            ))

        # Signal: Contradicting claims
        if contradicting_claims:
            analysis.add_signal(UncertaintySignal(
                signal_type=UncertaintySignalType.CONTRADICTING_CLAIM,
                description=f"Found {len(contradicting_claims)} contradicting claims",
                evidence_claim_ids=contradicting_claims[:3],
                heuristic_confidence_hint=0.2,
            ))

        analysis.generate_recommendation()

        return analysis


__all__ = [
    "UncertaintySignal",
    "UncertaintySignalType",
    "UncertaintyAnalysis",
]
