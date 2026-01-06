"""
Décisions de Gating pour Extraction V2.

ExtractionAction: Enum des décisions possibles.
GatingDecision: Résultat complet du Vision Gating v4.

Spécification: VISION_GATING_V4_CLASS_SCHEMA.py
"""

from __future__ import annotations
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

from knowbase.extraction_v2.models.signals import VisionSignals


class ExtractionAction(str, Enum):
    """
    Décision de gating - aligné avec Vision Gating v4.

    Valeurs:
    - NONE: Pas de Vision nécessaire (texte structuré suffit)
    - OCR_ONLY: Extraction texte sans Vision (image avec texte simple)
    - VISION_RECOMMENDED: Vision recommandée mais optionnelle (budget-dependent)
    - VISION_REQUIRED: Vision obligatoire (diagramme, architecture, etc.)
    """
    NONE = "none"                      # NO_VISION
    OCR_ONLY = "ocr_only"              # Extraction texte sans vision
    VISION_REQUIRED = "vision_required"
    VISION_RECOMMENDED = "vision_recommended"

    @classmethod
    def from_score(
        cls,
        vns: float,
        has_mandatory_trigger: bool = False,
        threshold_required: float = 0.60,
        threshold_recommended: float = 0.40
    ) -> "ExtractionAction":
        """
        Détermine l'action à partir du score VNS.

        Args:
            vns: Vision Need Score (0.0 - 1.0)
            has_mandatory_trigger: Si True, force VISION_REQUIRED
            threshold_required: Seuil pour VISION_REQUIRED (défaut: 0.60)
            threshold_recommended: Seuil pour VISION_RECOMMENDED (défaut: 0.40)

        Returns:
            ExtractionAction appropriée
        """
        # Règle de sécurité: trigger obligatoire
        if has_mandatory_trigger:
            return cls.VISION_REQUIRED

        # Seuils standards
        if vns >= threshold_required:
            return cls.VISION_REQUIRED
        elif vns >= threshold_recommended:
            return cls.VISION_RECOMMENDED
        else:
            return cls.NONE


@dataclass
class GatingDecision:
    """
    Résultat du Vision Gating v4.

    Toujours explicable avec scores et raisons.
    Utilisé pour l'audit et le debugging.
    """
    # Index de la page/slide
    index: int

    # Identifiant unique de l'unité (ex: "PDF_PAGE_6", "PPTX_SLIDE_12")
    unit_id: str

    # Décision finale
    action: ExtractionAction

    # Score VNS (Vision Need Score) entre 0.0 et 1.0
    vision_need_score: float

    # Signaux détaillés
    signals: VisionSignals = field(default_factory=VisionSignals)

    # Raisons explicatives de la décision
    reasons: List[str] = field(default_factory=list)

    # Poids utilisés pour le calcul (pour audit)
    weights_used: Optional[Dict[str, float]] = None

    # Métadonnées additionnelles
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        """Validation et génération automatique des raisons si vide."""
        if not self.reasons:
            self.reasons = self._generate_reasons()

    def _generate_reasons(self) -> List[str]:
        """Génère automatiquement les raisons basées sur les signaux."""
        reasons = []

        # Triggers obligatoires
        if self.signals.RIS >= 1.0:
            reasons.append("Image raster significative (>15% page)")
        if self.signals.VDS >= 1.0:
            reasons.append("Connecteurs vectoriels détectés")

        # Signaux contributifs
        if self.signals.RIS >= 0.5:
            reasons.append(f"RIS={self.signals.RIS:.2f}: images présentes")
        if self.signals.VDS >= 0.5:
            reasons.append(f"VDS={self.signals.VDS:.2f}: shapes vectoriels")
        if self.signals.TFS >= 0.5:
            reasons.append(f"TFS={self.signals.TFS:.2f}: texte fragmenté")
        if self.signals.SDS >= 0.5:
            reasons.append(f"SDS={self.signals.SDS:.2f}: texte dispersé spatialement")
        if self.signals.VTS >= 0.5:
            reasons.append(f"VTS={self.signals.VTS:.2f}: pseudo-table graphique")

        # Score final
        if self.action == ExtractionAction.VISION_REQUIRED:
            reasons.append(f"VNS={self.vision_need_score:.2f} >= seuil REQUIRED")
        elif self.action == ExtractionAction.VISION_RECOMMENDED:
            reasons.append(f"VNS={self.vision_need_score:.2f} >= seuil RECOMMENDED")
        elif self.action == ExtractionAction.NONE:
            reasons.append(f"VNS={self.vision_need_score:.2f} < seuil minimum")

        return reasons if reasons else ["Décision par défaut"]

    @property
    def requires_vision(self) -> bool:
        """Indique si Vision est obligatoire."""
        return self.action == ExtractionAction.VISION_REQUIRED

    @property
    def recommends_vision(self) -> bool:
        """Indique si Vision est recommandée."""
        return self.action in (
            ExtractionAction.VISION_REQUIRED,
            ExtractionAction.VISION_RECOMMENDED
        )

    @property
    def skip_vision(self) -> bool:
        """Indique si Vision peut être ignorée."""
        return self.action in (ExtractionAction.NONE, ExtractionAction.OCR_ONLY)

    def to_dict(self) -> Dict[str, Any]:
        """Sérialise en dictionnaire pour JSON/audit."""
        return {
            "index": self.index,
            "unit_id": self.unit_id,
            "decision": self.action.value,
            "vision_need_score": round(self.vision_need_score, 4),
            "signals": self.signals.to_dict(),
            "reasons": self.reasons,
            "weights_used": self.weights_used,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "GatingDecision":
        """Désérialise depuis un dictionnaire."""
        return cls(
            index=data["index"],
            unit_id=data["unit_id"],
            action=ExtractionAction(data["decision"]),
            vision_need_score=data["vision_need_score"],
            signals=VisionSignals.from_dict(data.get("signals", {})),
            reasons=data.get("reasons", []),
            weights_used=data.get("weights_used"),
            metadata=data.get("metadata", {}),
        )

    def __repr__(self) -> str:
        return (
            f"GatingDecision({self.unit_id}: {self.action.value}, "
            f"VNS={self.vision_need_score:.2f})"
        )
