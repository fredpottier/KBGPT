"""
Signaux Vision Gating V4.

Les 5 signaux du Vision Gating v4:
- RIS: Raster Image Signal (images raster significatives)
- VDS: Vector Drawing Signal (dessins vectoriels, connecteurs)
- TFS: Text Fragmentation Signal (texte fragmenté, labels courts)
- SDS: Spatial Dispersion Signal (dispersion spatiale du texte)
- VTS: Visual Table Signal (pseudo-tables graphiques)

Chaque signal est un float entre 0.0 et 1.0.

Spécification: VISION_GATING_V4_SPEC.md
"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any, Dict, List


@dataclass
class VisionSignals:
    """
    Les 5 signaux du Vision Gating v4.

    Chaque signal est un float entre 0.0 et 1.0.

    Signaux:
    - RIS (Raster Image Signal): Détecte les images raster significatives
      - 1.0 si image > 15% de la page
      - Proportionnel si image entre 5% et 15%
      - 0.0 si pas d'image ou image < 5%

    - VDS (Vector Drawing Signal): Détecte les dessins vectoriels
      - 1.0 si connecteurs détectés
      - Basé sur la densité de shapes sinon
      - 0.0 si pas de shapes vectoriels

    - TFS (Text Fragmentation Signal): Détecte la fragmentation du texte
      - Haut si beaucoup de blocs courts (< 200 chars)
      - Typique des diagrammes avec labels

    - SDS (Spatial Dispersion Signal): Détecte la dispersion spatiale
      - Variance normalisée des positions des blocs texte
      - Haut si texte dispersé (diagramme)
      - Bas si texte linéaire (document classique)

    - VTS (Visual Table Signal): Détecte les pseudo-tables graphiques
      - Tables non détectées par Docling
      - Grilles visuelles créées avec shapes/lignes
    """
    RIS: float = 0.0  # Raster Image Signal
    VDS: float = 0.0  # Vector Drawing Signal
    TFS: float = 0.0  # Text Fragmentation Signal
    SDS: float = 0.0  # Spatial Dispersion Signal
    VTS: float = 0.0  # Visual Table Signal

    def __post_init__(self):
        """Validation des valeurs."""
        for signal_name in ["RIS", "VDS", "TFS", "SDS", "VTS"]:
            value = getattr(self, signal_name)
            if not isinstance(value, (int, float)):
                raise ValueError(f"{signal_name} doit être un nombre, reçu: {type(value)}")
            # Clamp entre 0 et 1
            setattr(self, signal_name, max(0.0, min(1.0, float(value))))

    def to_dict(self) -> Dict[str, float]:
        """Sérialise en dictionnaire."""
        return {
            "RIS": round(self.RIS, 4),
            "VDS": round(self.VDS, 4),
            "TFS": round(self.TFS, 4),
            "SDS": round(self.SDS, 4),
            "VTS": round(self.VTS, 4),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, float]) -> "VisionSignals":
        """Désérialise depuis un dictionnaire."""
        return cls(
            RIS=data.get("RIS", 0.0),
            VDS=data.get("VDS", 0.0),
            TFS=data.get("TFS", 0.0),
            SDS=data.get("SDS", 0.0),
            VTS=data.get("VTS", 0.0),
        )

    def compute_weighted_score(self, weights: Dict[str, float]) -> float:
        """
        Calcule le score pondéré VNS (Vision Need Score).

        Args:
            weights: Poids pour chaque signal (doivent sommer à 1.0)

        Returns:
            Score VNS entre 0.0 et 1.0

        Formula:
            VNS = w_RIS * RIS + w_VDS * VDS + w_TFS * TFS + w_SDS * SDS + w_VTS * VTS
        """
        return (
            weights.get("RIS", 0.30) * self.RIS +
            weights.get("VDS", 0.30) * self.VDS +
            weights.get("TFS", 0.15) * self.TFS +
            weights.get("SDS", 0.15) * self.SDS +
            weights.get("VTS", 0.10) * self.VTS
        )

    def has_mandatory_vision_trigger(self) -> bool:
        """
        Vérifie si un signal déclenche Vision de manière obligatoire.

        Règle de sécurité:
        - RIS = 1.0 (image > 15%) → VISION_REQUIRED
        - VDS = 1.0 (connecteurs détectés) → VISION_REQUIRED
        """
        return self.RIS >= 1.0 or self.VDS >= 1.0

    @property
    def max_signal(self) -> str:
        """Retourne le nom du signal le plus élevé."""
        signals = {
            "RIS": self.RIS,
            "VDS": self.VDS,
            "TFS": self.TFS,
            "SDS": self.SDS,
            "VTS": self.VTS,
        }
        return max(signals, key=signals.get)

    @property
    def max_value(self) -> float:
        """Retourne la valeur du signal le plus élevé."""
        return max(self.RIS, self.VDS, self.TFS, self.SDS, self.VTS)

    def get_active_signals(self, threshold: float = 0.3) -> List[str]:
        """
        Retourne la liste des signaux actifs (au-dessus du seuil).

        Args:
            threshold: Seuil d'activation (défaut: 0.3)

        Returns:
            Liste des noms de signaux actifs
        """
        active = []
        if self.RIS >= threshold:
            active.append("RIS")
        if self.VDS >= threshold:
            active.append("VDS")
        if self.TFS >= threshold:
            active.append("TFS")
        if self.SDS >= threshold:
            active.append("SDS")
        if self.VTS >= threshold:
            active.append("VTS")
        return active

    def __repr__(self) -> str:
        return (
            f"VisionSignals(RIS={self.RIS:.2f}, VDS={self.VDS:.2f}, "
            f"TFS={self.TFS:.2f}, SDS={self.SDS:.2f}, VTS={self.VTS:.2f})"
        )
