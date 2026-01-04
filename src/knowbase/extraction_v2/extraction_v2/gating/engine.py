"""
GatingEngine - Moteur de décision Vision Gating V4.

Calcule le VNS (Vision Need Score) et décide si Vision est nécessaire.

Spécification: VISION_GATING_V4_SPEC.md

Implémentation complète en Phase 3.
"""

from __future__ import annotations
from typing import Dict, List, Optional
import logging

from knowbase.extraction_v2.models import (
    VisionUnit,
    VisionSignals,
    GatingDecision,
    ExtractionAction,
    VisionDomainContext,
)
from knowbase.extraction_v2.gating.weights import (
    DEFAULT_GATING_WEIGHTS,
    GATING_THRESHOLDS,
)

logger = logging.getLogger(__name__)


class GatingEngine:
    """
    Moteur de décision Vision Gating V4.

    Calcule les signaux, le VNS, et décide si Vision est nécessaire.

    Usage:
        >>> engine = GatingEngine()
        >>> decision = engine.gate(unit)
        >>> if decision.requires_vision:
        ...     run_vision(unit)

    Poids par défaut:
    - RIS: 0.30 (images raster)
    - VDS: 0.30 (dessins vectoriels)
    - TFS: 0.15 (fragmentation texte)
    - SDS: 0.15 (dispersion spatiale)
    - VTS: 0.10 (pseudo-tables)

    Seuils:
    - VISION_REQUIRED: VNS >= 0.60
    - VISION_RECOMMENDED: VNS >= 0.40
    - NONE: VNS < 0.40

    Note: Implémentation complète en Phase 3.
    """

    def __init__(
        self,
        weights: Optional[Dict[str, float]] = None,
        thresholds: Optional[Dict[str, float]] = None,
    ):
        """
        Initialise le moteur de gating.

        Args:
            weights: Poids personnalisés pour les signaux
            thresholds: Seuils personnalisés pour les décisions
        """
        self.weights = weights or DEFAULT_GATING_WEIGHTS.copy()
        self.thresholds = thresholds or GATING_THRESHOLDS.copy()

        logger.info(
            f"[GatingEngine] Initialized with weights={self.weights}, "
            f"thresholds={self.thresholds}"
        )

    def compute_signals(self, unit: VisionUnit) -> VisionSignals:
        """
        Calcule les 5 signaux pour une unit.

        Args:
            unit: VisionUnit à analyser

        Returns:
            VisionSignals avec les 5 valeurs

        Raises:
            NotImplementedError: Implémentation en Phase 3
        """
        raise NotImplementedError(
            "GatingEngine.compute_signals() sera implémenté en Phase 3."
        )

    def compute_vision_need_score(
        self,
        signals: VisionSignals,
        domain_context: Optional[VisionDomainContext] = None,
    ) -> float:
        """
        Calcule le VNS (Vision Need Score).

        Formula:
            VNS = sum(weight_i * signal_i)

        Args:
            signals: Signaux calculés
            domain_context: Contexte pour ajuster les poids (optionnel)

        Returns:
            VNS entre 0.0 et 1.0

        Raises:
            NotImplementedError: Implémentation en Phase 3
        """
        raise NotImplementedError(
            "GatingEngine.compute_vision_need_score() sera implémenté en Phase 3."
        )

    def gate(
        self,
        unit: VisionUnit,
        domain_context: Optional[VisionDomainContext] = None,
    ) -> GatingDecision:
        """
        Décide si Vision est nécessaire pour cette unit.

        Args:
            unit: VisionUnit à analyser
            domain_context: Contexte pour guider la décision

        Returns:
            GatingDecision avec action, score et raisons

        Raises:
            NotImplementedError: Implémentation en Phase 3
        """
        raise NotImplementedError(
            "GatingEngine.gate() sera implémenté en Phase 3."
        )

    def gate_document(
        self,
        units: List[VisionUnit],
        domain_context: Optional[VisionDomainContext] = None,
    ) -> List[GatingDecision]:
        """
        Gate toutes les units d'un document.

        Args:
            units: Liste de VisionUnits
            domain_context: Contexte pour guider les décisions

        Returns:
            Liste de GatingDecisions (une par unit)

        Raises:
            NotImplementedError: Implémentation en Phase 3
        """
        raise NotImplementedError(
            "GatingEngine.gate_document() sera implémenté en Phase 3."
        )


__all__ = ["GatingEngine"]
