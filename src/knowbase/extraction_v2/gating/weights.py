"""
Poids et seuils pour Vision Gating V4.

Seuils expérimentaux à calibrer sur corpus réel.

Spécification: VISION_GATING_V4_SPEC.md, OSMOSIS_EXTRACTION_V2_DECISIONS.md
"""

from typing import Dict

# === Poids par défaut pour le calcul du VNS ===

DEFAULT_GATING_WEIGHTS: Dict[str, float] = {
    "RIS": 0.30,  # Raster Image Signal - images significatives
    "VDS": 0.30,  # Vector Drawing Signal - shapes, connecteurs
    "TFS": 0.15,  # Text Fragmentation Signal - labels courts
    "SDS": 0.15,  # Spatial Dispersion Signal - dispersion texte
    "VTS": 0.10,  # Visual Table Signal - pseudo-tables
}

# === Seuils de décision ===

GATING_THRESHOLDS: Dict[str, float] = {
    "VISION_REQUIRED": 0.60,     # VNS >= 0.60 → Vision obligatoire
    "VISION_RECOMMENDED": 0.40,  # 0.40 <= VNS < 0.60 → Vision recommandée
    # VNS < 0.40 → NO_VISION
}

# === Seuils expérimentaux pour les signaux individuels ===
# À calibrer sur corpus réel (Phase 7)

EXPERIMENTAL_THRESHOLDS: Dict[str, float] = {
    # RIS thresholds
    "RIS_HIGH": 0.15,      # Image > 15% page → RIS = 1.0
    "RIS_LOW": 0.05,       # Image < 5% page → RIS = 0.0

    # VDS thresholds
    "VDS_CONNECTOR_MIN": 1,  # >= 1 connecteur → VDS = 1.0

    # TFS thresholds
    "TFS_MIN_BLOCKS": 12,    # Minimum blocs pour TFS significatif
    "TFS_SHORT_CHAR": 200,   # Bloc < 200 chars = "court"
    "TFS_HIGH_RATIO": 0.75,  # > 75% courts = fragmenté

    # SDS thresholds
    "SDS_HIGH": 0.08,        # Variance > 0.08 = dispersé
    "SDS_MEDIUM": 0.04,      # Variance > 0.04 = modérément dispersé

    # VTS thresholds
    "VTS_MIN_LINES": 3,      # Minimum lignes horizontales
    "VTS_MIN_COLS": 2,       # Minimum colonnes détectées
}

# === Poids par domaine (optionnel) ===
# Permet d'ajuster les poids selon le contexte métier

DOMAIN_WEIGHT_ADJUSTMENTS: Dict[str, Dict[str, float]] = {
    "SAP": {
        # SAP a beaucoup de diagrammes d'architecture
        "VDS": 0.35,  # Plus de poids sur les shapes
        "RIS": 0.25,  # Moins sur les images raster
    },
    "pharmaceutical": {
        # Documents réglementaires avec tables complexes
        "VTS": 0.20,  # Plus de poids sur les tables
        "TFS": 0.10,  # Moins sur la fragmentation
    },
    "retail": {
        # Documents marketing avec images
        "RIS": 0.40,  # Plus de poids sur les images
        "VDS": 0.20,  # Moins sur les shapes
    },
}


def get_weights_for_domain(domain: str) -> Dict[str, float]:
    """
    Retourne les poids ajustés pour un domaine.

    Args:
        domain: Nom du domaine

    Returns:
        Poids ajustés (copie de DEFAULT + ajustements)
    """
    weights = DEFAULT_GATING_WEIGHTS.copy()

    if domain.lower() in DOMAIN_WEIGHT_ADJUSTMENTS:
        adjustments = DOMAIN_WEIGHT_ADJUSTMENTS[domain.lower()]
        weights.update(adjustments)

        # Renormaliser pour que la somme = 1.0
        total = sum(weights.values())
        if total > 0:
            weights = {k: v / total for k, v in weights.items()}

    return weights


__all__ = [
    "DEFAULT_GATING_WEIGHTS",
    "GATING_THRESHOLDS",
    "EXPERIMENTAL_THRESHOLDS",
    "DOMAIN_WEIGHT_ADJUSTMENTS",
    "get_weights_for_domain",
]
