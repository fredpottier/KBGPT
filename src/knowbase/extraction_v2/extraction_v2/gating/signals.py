"""
Calcul des 5 signaux Vision Gating V4.

- RIS: Raster Image Signal
- VDS: Vector Drawing Signal
- TFS: Text Fragmentation Signal
- SDS: Spatial Dispersion Signal
- VTS: Visual Table Signal

Spécification: VISION_GATING_V4_SPEC.md

Implémentation complète en Phase 3.
"""

from __future__ import annotations
from typing import Optional
import logging

from knowbase.extraction_v2.models import VisionUnit, VisionSignals

logger = logging.getLogger(__name__)


def compute_raster_image_signal(unit: VisionUnit) -> float:
    """
    Calcule le signal RIS (Raster Image Signal).

    Détecte les images raster significatives.

    Formule:
    - RIS = 1.0 si largest_image_ratio > 0.15 (15% de la page)
    - RIS = (ratio - 0.05) / 0.10 si 0.05 < ratio <= 0.15
    - RIS = 0.0 si ratio <= 0.05 ou pas d'image

    Args:
        unit: VisionUnit à analyser

    Returns:
        Signal RIS entre 0.0 et 1.0

    Raises:
        NotImplementedError: Implémentation en Phase 3
    """
    raise NotImplementedError(
        "compute_raster_image_signal() sera implémenté en Phase 3."
    )


def compute_vector_drawing_signal(unit: VisionUnit) -> float:
    """
    Calcule le signal VDS (Vector Drawing Signal).

    Détecte les dessins vectoriels et connecteurs.

    Formule:
    - VDS = 1.0 si connectors_count >= 1 (connecteurs détectés)
    - VDS = min(vector_density * 2, 1.0) sinon (basé sur densité shapes)
    - VDS = 0.0 si pas de shapes vectoriels

    Args:
        unit: VisionUnit à analyser

    Returns:
        Signal VDS entre 0.0 et 1.0

    Raises:
        NotImplementedError: Implémentation en Phase 3
    """
    raise NotImplementedError(
        "compute_vector_drawing_signal() sera implémenté en Phase 3."
    )


def compute_text_fragmentation_signal(unit: VisionUnit) -> float:
    """
    Calcule le signal TFS (Text Fragmentation Signal).

    Détecte la fragmentation du texte (labels courts typiques des diagrammes).

    Formule:
    - TFS = short_blocks_ratio si text_blocks >= MIN_BLOCKS
    - TFS = short_blocks_ratio * (text_blocks / MIN_BLOCKS) sinon
    - short_blocks_ratio = short_blocks_count / text_blocks_count

    Args:
        unit: VisionUnit à analyser

    Returns:
        Signal TFS entre 0.0 et 1.0

    Raises:
        NotImplementedError: Implémentation en Phase 3
    """
    raise NotImplementedError(
        "compute_text_fragmentation_signal() sera implémenté en Phase 3."
    )


def compute_spatial_dispersion_signal(unit: VisionUnit) -> float:
    """
    Calcule le signal SDS (Spatial Dispersion Signal).

    Détecte la dispersion spatiale du texte.

    Formule:
    - SDS = normalized_variance des positions des blocs texte
    - Variance calculée sur les centres des bounding boxes
    - Normalisée par rapport à la variance max théorique (0.25)

    Args:
        unit: VisionUnit à analyser

    Returns:
        Signal SDS entre 0.0 et 1.0

    Raises:
        NotImplementedError: Implémentation en Phase 3
    """
    raise NotImplementedError(
        "compute_spatial_dispersion_signal() sera implémenté en Phase 3."
    )


def compute_visual_table_signal(unit: VisionUnit) -> float:
    """
    Calcule le signal VTS (Visual Table Signal).

    Détecte les pseudo-tables graphiques (tables non structurées).

    Formule:
    - VTS = 0.0 si unit.has_structured_tables (Docling a détecté la table)
    - VTS = detect_visual_grid_pattern(unit) sinon

    Args:
        unit: VisionUnit à analyser

    Returns:
        Signal VTS entre 0.0 et 1.0

    Raises:
        NotImplementedError: Implémentation en Phase 3
    """
    raise NotImplementedError(
        "compute_visual_table_signal() sera implémenté en Phase 3."
    )


def compute_all_signals(unit: VisionUnit) -> VisionSignals:
    """
    Calcule tous les signaux pour une VisionUnit.

    Args:
        unit: VisionUnit à analyser

    Returns:
        VisionSignals avec les 5 valeurs

    Raises:
        NotImplementedError: Implémentation en Phase 3
    """
    raise NotImplementedError(
        "compute_all_signals() sera implémenté en Phase 3."
    )


__all__ = [
    "compute_raster_image_signal",
    "compute_vector_drawing_signal",
    "compute_text_fragmentation_signal",
    "compute_spatial_dispersion_signal",
    "compute_visual_table_signal",
    "compute_all_signals",
]
