"""
GatingEngine - Moteur de decision Vision Gating V4.

Calcule le VNS (Vision Need Score) et decide si Vision est necessaire.

Specification: VISION_GATING_V4_SPEC.md
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
from knowbase.extraction_v2.gating.signals import compute_all_signals
from knowbase.extraction_v2.gating.weights import (
    DEFAULT_GATING_WEIGHTS,
    GATING_THRESHOLDS,
    get_weights_for_domain,
)

logger = logging.getLogger(__name__)


class GatingEngine:
    """
    Moteur de decision Vision Gating V4.

    Calcule les signaux, le VNS, et decide si Vision est necessaire.

    Usage:
        >>> engine = GatingEngine()
        >>> decision = engine.gate(unit)
        >>> if decision.requires_vision:
        ...     run_vision(unit)

    Poids par defaut:
    - RIS: 0.30 (images raster)
    - VDS: 0.30 (dessins vectoriels)
    - TFS: 0.15 (fragmentation texte)
    - SDS: 0.15 (dispersion spatiale)
    - VTS: 0.10 (pseudo-tables)

    Seuils:
    - VISION_REQUIRED: VNS >= 0.60
    - VISION_RECOMMENDED: VNS >= 0.40
    - NONE: VNS < 0.40

    Regle de securite:
    - Si RIS == 1.0 OU VDS == 1.0 -> VISION_REQUIRED (quel que soit VNS)
    """

    def __init__(
        self,
        weights: Optional[Dict[str, float]] = None,
        thresholds: Optional[Dict[str, float]] = None,
    ):
        """
        Initialise le moteur de gating.

        Args:
            weights: Poids personnalises pour les signaux
            thresholds: Seuils personnalises pour les decisions
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
            unit: VisionUnit a analyser

        Returns:
            VisionSignals avec les 5 valeurs
        """
        return compute_all_signals(unit)

    def compute_vision_need_score(
        self,
        signals: VisionSignals,
        domain_context: Optional[VisionDomainContext] = None,
    ) -> float:
        """
        Calcule le VNS (Vision Need Score).

        Formula:
            VNS = sum(weight_i * signal_i)

        Le Domain Context peut ajuster les poids de +-10% max.

        Args:
            signals: Signaux calcules
            domain_context: Contexte pour ajuster les poids (optionnel)

        Returns:
            VNS entre 0.0 et 1.0
        """
        # Recuperer les poids
        weights = self.weights.copy()

        # Ajuster les poids selon le domain context si fourni
        if domain_context and domain_context.name:
            domain_weights = get_weights_for_domain(domain_context.name)
            # Appliquer avec limite de +-10%
            for key in weights:
                if key in domain_weights:
                    original = self.weights.get(key, 0.0)
                    adjusted = domain_weights[key]
                    # Limiter l'ajustement a +-10%
                    max_delta = original * 0.10
                    delta = adjusted - original
                    if abs(delta) > max_delta:
                        delta = max_delta if delta > 0 else -max_delta
                    weights[key] = original + delta

        # Calculer le score pondere
        vns = signals.compute_weighted_score(weights)

        # Clamp entre 0 et 1
        vns = max(0.0, min(1.0, vns))

        logger.debug(
            f"[GatingEngine] VNS={vns:.3f} with weights={weights}"
        )

        return vns

    def gate(
        self,
        unit: VisionUnit,
        domain_context: Optional[VisionDomainContext] = None,
    ) -> GatingDecision:
        """
        Decide si Vision est necessaire pour cette unit.

        Args:
            unit: VisionUnit a analyser
            domain_context: Contexte pour guider la decision

        Returns:
            GatingDecision avec action, score et raisons
        """
        # Calculer les signaux
        signals = self.compute_signals(unit)

        # Calculer le VNS
        vns = self.compute_vision_need_score(signals, domain_context)

        # Collecter les raisons
        reasons = []

        # === Regle de securite ===
        # Si RIS == 1.0 OU VDS == 1.0 -> VISION_REQUIRED
        if signals.RIS == 1.0 or signals.VDS == 1.0:
            action = ExtractionAction.VISION_REQUIRED

            if signals.RIS == 1.0:
                reasons.append("large raster image detected (RIS=1.0)")
            if signals.VDS == 1.0:
                reasons.append("significant vector drawings/connectors detected (VDS=1.0)")

        # === Decision basee sur VNS ===
        else:
            threshold_required = self.thresholds.get("VISION_REQUIRED", 0.60)
            threshold_recommended = self.thresholds.get("VISION_RECOMMENDED", 0.40)

            if vns >= threshold_required:
                action = ExtractionAction.VISION_REQUIRED
                reasons.append(f"high vision need score (VNS={vns:.2f} >= {threshold_required})")
            elif vns >= threshold_recommended:
                action = ExtractionAction.VISION_RECOMMENDED
                reasons.append(f"moderate vision need score (VNS={vns:.2f} >= {threshold_recommended})")
            else:
                action = ExtractionAction.NONE
                reasons.append(f"low vision need score (VNS={vns:.2f} < {threshold_recommended})")

        # Ajouter les raisons des signaux elevees
        if signals.TFS >= 0.6 and "fragmentation" not in str(reasons):
            reasons.append(f"high text fragmentation (TFS={signals.TFS:.2f})")
        if signals.SDS >= 0.5 and "dispersion" not in str(reasons):
            reasons.append(f"high spatial dispersion (SDS={signals.SDS:.2f})")
        if signals.VTS >= 1.0 and "table" not in str(reasons):
            reasons.append(f"visual table detected (VTS={signals.VTS:.2f})")

        # Construire la decision
        decision = GatingDecision(
            index=unit.index,
            unit_id=unit.id,
            action=action,
            vision_need_score=round(vns, 3),
            signals=signals,
            reasons=reasons,
        )

        logger.info(
            f"[GatingEngine] {unit.id}: {action.value} (VNS={vns:.2f}), "
            f"reasons={reasons}"
        )

        return decision

    def gate_document(
        self,
        units: List[VisionUnit],
        domain_context: Optional[VisionDomainContext] = None,
    ) -> List[GatingDecision]:
        """
        Gate toutes les units d'un document.

        Args:
            units: Liste de VisionUnits
            domain_context: Contexte pour guider les decisions

        Returns:
            Liste de GatingDecisions (une par unit)
        """
        decisions = []

        for unit in units:
            decision = self.gate(unit, domain_context)
            decisions.append(decision)

        # Log summary
        counts = {
            "VISION_REQUIRED": 0,
            "VISION_RECOMMENDED": 0,
            "NONE": 0,
        }
        for d in decisions:
            counts[d.action.value] = counts.get(d.action.value, 0) + 1

        logger.info(
            f"[GatingEngine] Document gating complete: "
            f"{len(units)} units, "
            f"REQUIRED={counts['VISION_REQUIRED']}, "
            f"RECOMMENDED={counts['VISION_RECOMMENDED']}, "
            f"NONE={counts['NONE']}"
        )

        return decisions

    def get_vision_candidates(
        self,
        decisions: List[GatingDecision],
        include_recommended: bool = True,
    ) -> List[int]:
        """
        Retourne les indices des units necessitant Vision.

        Args:
            decisions: Liste des decisions de gating
            include_recommended: Inclure VISION_RECOMMENDED (defaut: True)

        Returns:
            Liste des indices des units a envoyer a Vision
        """
        indices = []

        for decision in decisions:
            if decision.action == ExtractionAction.VISION_REQUIRED:
                indices.append(decision.index)
            elif include_recommended and decision.action == ExtractionAction.VISION_RECOMMENDED:
                indices.append(decision.index)

        return indices

    def summary(self, decisions: List[GatingDecision]) -> Dict[str, any]:
        """
        Genere un resume des decisions de gating.

        Args:
            decisions: Liste des decisions

        Returns:
            Dict avec statistiques
        """
        if not decisions:
            return {
                "total_units": 0,
                "vision_required": 0,
                "vision_recommended": 0,
                "no_vision": 0,
                "avg_vns": 0.0,
                "max_vns": 0.0,
            }

        vision_required = sum(1 for d in decisions if d.action == ExtractionAction.VISION_REQUIRED)
        vision_recommended = sum(1 for d in decisions if d.action == ExtractionAction.VISION_RECOMMENDED)
        no_vision = sum(1 for d in decisions if d.action == ExtractionAction.NONE)

        vns_scores = [d.vision_need_score for d in decisions]
        avg_vns = sum(vns_scores) / len(vns_scores)
        max_vns = max(vns_scores)

        return {
            "total_units": len(decisions),
            "vision_required": vision_required,
            "vision_recommended": vision_recommended,
            "no_vision": no_vision,
            "avg_vns": round(avg_vns, 3),
            "max_vns": round(max_vns, 3),
            "vision_ratio": round((vision_required + vision_recommended) / len(decisions), 3),
        }


__all__ = ["GatingEngine"]
