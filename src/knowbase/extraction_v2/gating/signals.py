"""
Calcul des 5 signaux Vision Gating V4.

- RIS: Raster Image Signal
- VDS: Vector Drawing Signal
- TFS: Text Fragmentation Signal
- SDS: Spatial Dispersion Signal
- VTS: Visual Table Signal

Specification: VISION_GATING_V4_SPEC.md
"""

from __future__ import annotations
from typing import List, Optional, Tuple
import logging
import math

from knowbase.extraction_v2.models import VisionUnit, VisionSignals
from knowbase.extraction_v2.models.elements import TextBlock, VisualElement
from knowbase.extraction_v2.gating.weights import EXPERIMENTAL_THRESHOLDS

logger = logging.getLogger(__name__)


# === Constantes pour les seuils ===

# RIS thresholds (spec: 0.30, 0.20, 0.10)
RIS_THRESHOLD_HIGH = 0.30
RIS_THRESHOLD_MEDIUM = 0.20
RIS_THRESHOLD_LOW = 0.10

# VDS thresholds
VDS_CONNECTOR_THRESHOLD = 3
VDS_AREA_THRESHOLD = 0.35
VDS_DRAWINGS_HIGH = 15
VDS_DRAWINGS_MEDIUM = 8

# TFS thresholds
TFS_SHORT_CHAR_LIMIT = 200
TFS_MIN_BLOCKS = 12
TFS_HIGH_SHORT_RATIO = 0.75
TFS_MEDIUM_SHORT_RATIO = 0.60

# SDS thresholds
SDS_HIGH_VARIANCE = 0.08
SDS_MEDIUM_VARIANCE = 0.04

# VTS thresholds
VTS_MIN_HORIZONTAL_LINES = 3
VTS_MIN_VERTICAL_LINES = 2


def compute_raster_image_signal(unit: VisionUnit) -> float:
    """
    Calcule le signal RIS (Raster Image Signal).

    Detecte les images raster significatives.

    Formule (spec V4):
    - RIS = 1.0 si largest_image_ratio >= 0.30
    - RIS = 0.7 si largest_image_ratio >= 0.20
    - RIS = 0.4 si largest_image_ratio >= 0.10
    - RIS = 0.0 sinon

    Args:
        unit: VisionUnit a analyser

    Returns:
        Signal RIS entre 0.0 et 1.0
    """
    # Filtrer les elements visuels de type raster_image
    raster_images = [
        elem for elem in unit.visual_elements
        if elem.kind == "raster_image"
    ]

    if not raster_images:
        return 0.0

    # Calculer l'aire de la page
    page_width, page_height = unit.dimensions
    page_area = page_width * page_height

    if page_area <= 0:
        return 0.0

    # Trouver le ratio de la plus grande image
    largest_ratio = 0.0

    for img in raster_images:
        if img.bbox is not None:
            img_area = img.bbox.area
            # Si bbox normalisee, multiplier par page_area
            if img.bbox.normalized:
                ratio = img_area  # Deja en ratio
            else:
                ratio = img_area / page_area
            largest_ratio = max(largest_ratio, ratio)

    # Appliquer les seuils de la spec
    if largest_ratio >= RIS_THRESHOLD_HIGH:
        score = 1.0
    elif largest_ratio >= RIS_THRESHOLD_MEDIUM:
        score = 0.7
    elif largest_ratio >= RIS_THRESHOLD_LOW:
        score = 0.4
    else:
        score = 0.0

    logger.debug(
        f"[RIS] unit={unit.id}, largest_ratio={largest_ratio:.3f}, score={score}"
    )

    return score


def compute_vector_drawing_signal(unit: VisionUnit) -> float:
    """
    Calcule le signal VDS (Vector Drawing Signal).

    Detecte les diagrammes en shapes vectoriels.

    Formule (spec V4):
    - VDS = 1.0 si num_connectors >= 3 OU drawing_area_ratio >= 0.35
    - VDS = 0.7 si num_drawings >= 15
    - VDS = 0.4 si num_drawings >= 8
    - VDS = 0.0 sinon

    Args:
        unit: VisionUnit a analyser

    Returns:
        Signal VDS entre 0.0 et 1.0
    """
    # Filtrer les elements visuels
    vector_elements = [
        elem for elem in unit.visual_elements
        if elem.kind in ("vector_shape", "connector", "drawing", "line", "arrow")
    ]

    # Compter les connecteurs (lignes, fleches)
    connectors = [
        elem for elem in unit.visual_elements
        if elem.kind in ("connector", "line", "arrow")
    ]
    num_connectors = len(connectors)

    # Compter tous les drawings (shapes)
    drawings = [
        elem for elem in unit.visual_elements
        if elem.kind in ("vector_shape", "drawing", "rectangle", "oval", "shape")
    ]
    num_drawings = len(drawings)

    # Calculer le ratio de surface des drawings
    page_width, page_height = unit.dimensions
    page_area = page_width * page_height

    drawing_area = 0.0
    if page_area > 0:
        for elem in vector_elements:
            if elem.bbox is not None:
                if elem.bbox.normalized:
                    drawing_area += elem.bbox.area * page_area
                else:
                    drawing_area += elem.bbox.area
        drawing_area_ratio = drawing_area / page_area
    else:
        drawing_area_ratio = 0.0

    # Appliquer les seuils de la spec
    if num_connectors >= VDS_CONNECTOR_THRESHOLD or drawing_area_ratio >= VDS_AREA_THRESHOLD:
        score = 1.0
    elif num_drawings >= VDS_DRAWINGS_HIGH:
        score = 0.7
    elif num_drawings >= VDS_DRAWINGS_MEDIUM:
        score = 0.4
    else:
        score = 0.0

    logger.debug(
        f"[VDS] unit={unit.id}, connectors={num_connectors}, "
        f"drawings={num_drawings}, area_ratio={drawing_area_ratio:.3f}, score={score}"
    )

    return score


def compute_text_fragmentation_signal(unit: VisionUnit) -> float:
    """
    Calcule le signal TFS (Text Fragmentation Signal).

    Detecte la fragmentation du texte (indicateur de diagramme).

    Formule (spec V4):
    - TFS = 1.0 si short_block_ratio >= 0.75 ET num_blocks >= 12
    - TFS = 0.6 si short_block_ratio >= 0.60
    - TFS = 0.0 sinon

    Short block = bloc < 200 caracteres

    Args:
        unit: VisionUnit a analyser

    Returns:
        Signal TFS entre 0.0 et 1.0
    """
    blocks = unit.blocks

    if not blocks:
        return 0.0

    num_text_blocks = len(blocks)

    # Compter les blocs courts (< 200 chars)
    short_blocks = [b for b in blocks if b.char_count < TFS_SHORT_CHAR_LIMIT]
    num_short_blocks = len(short_blocks)

    if num_text_blocks == 0:
        return 0.0

    short_block_ratio = num_short_blocks / num_text_blocks

    # Appliquer les seuils de la spec
    if short_block_ratio >= TFS_HIGH_SHORT_RATIO and num_text_blocks >= TFS_MIN_BLOCKS:
        score = 1.0
    elif short_block_ratio >= TFS_MEDIUM_SHORT_RATIO:
        score = 0.6
    else:
        score = 0.0

    logger.debug(
        f"[TFS] unit={unit.id}, blocks={num_text_blocks}, "
        f"short={num_short_blocks}, ratio={short_block_ratio:.2f}, score={score}"
    )

    return score


def compute_spatial_dispersion_signal(unit: VisionUnit) -> float:
    """
    Calcule le signal SDS (Spatial Dispersion Signal).

    Mesure la dispersion spatiale du texte.

    Formule (spec V4):
    - SDS = 1.0 si variance >= 0.08 (HIGH)
    - SDS = 0.5 si variance >= 0.04 (MEDIUM)
    - SDS = 0.0 sinon

    Args:
        unit: VisionUnit a analyser

    Returns:
        Signal SDS entre 0.0 et 1.0
    """
    blocks = unit.blocks

    # Besoin d'au moins 3 blocs pour une variance significative
    if len(blocks) < 3:
        return 0.0

    page_width, page_height = unit.dimensions

    if page_width <= 0 or page_height <= 0:
        return 0.0

    # Calculer les centres normalises des blocs
    centers_x = []
    centers_y = []

    for block in blocks:
        if block.bbox is not None:
            cx, cy = block.bbox.center

            # Normaliser par dimensions page
            if block.bbox.normalized:
                centers_x.append(cx)
                centers_y.append(cy)
            else:
                centers_x.append(cx / page_width)
                centers_y.append(cy / page_height)

    if len(centers_x) < 3:
        return 0.0

    # Calculer la variance
    def variance(values: List[float]) -> float:
        if len(values) < 2:
            return 0.0
        mean = sum(values) / len(values)
        return sum((v - mean) ** 2 for v in values) / len(values)

    var_x = variance(centers_x)
    var_y = variance(centers_y)

    # Variance totale
    total_variance = var_x + var_y

    # Appliquer les seuils de la spec
    if total_variance >= SDS_HIGH_VARIANCE:
        score = 1.0
    elif total_variance >= SDS_MEDIUM_VARIANCE:
        score = 0.5
    else:
        score = 0.0

    logger.debug(
        f"[SDS] unit={unit.id}, blocks={len(blocks)}, "
        f"variance={total_variance:.4f}, score={score}"
    )

    return score


def compute_visual_table_signal(unit: VisionUnit) -> float:
    """
    Calcule le signal VTS (Visual Table Signal).

    Detecte les tables visuelles non structurees.

    Formule (spec V4):
    - VTS = 1.0 si pattern de grille detecte (H lines >= 3 ET V lines >= 2)
    - VTS = 1.0 si pattern de texte en grille detecte
    - VTS = 0.0 sinon

    Note: Si Docling a deja detecte des tables structurees, le signal
    devrait etre bas car pas besoin de Vision pour les interpreter.

    Args:
        unit: VisionUnit a analyser

    Returns:
        Signal VTS entre 0.0 et 1.0
    """
    # Si des tables structurees existent deja, pas besoin de Vision
    if unit.tables and len(unit.tables) > 0:
        # Verifier si les tables sont bien structurees
        for table in unit.tables:
            if table.is_structured and table.num_rows > 0 and table.num_cols > 0:
                # Table deja structuree, pas besoin de VTS
                logger.debug(
                    f"[VTS] unit={unit.id}, structured_table found, score=0.0"
                )
                return 0.0

    # Chercher des patterns de grille dans les elements visuels
    lines = [
        elem for elem in unit.visual_elements
        if elem.kind in ("line", "connector", "horizontal_line", "vertical_line")
    ]

    horizontal_lines = []
    vertical_lines = []

    page_width, page_height = unit.dimensions

    for line in lines:
        if line.bbox is None:
            continue

        # Determiner si la ligne est horizontale ou verticale
        width = line.bbox.width
        height = line.bbox.height

        # Si normalisee, convertir
        if not line.bbox.normalized and page_width > 0:
            width_ratio = width / page_width
            height_ratio = height / page_height
        else:
            width_ratio = width
            height_ratio = height

        # Ligne horizontale: beaucoup plus large que haute
        if width_ratio > height_ratio * 5:
            horizontal_lines.append(line)
        # Ligne verticale: beaucoup plus haute que large
        elif height_ratio > width_ratio * 5:
            vertical_lines.append(line)

    # Verifier le pattern de grille
    if len(horizontal_lines) >= VTS_MIN_HORIZONTAL_LINES and len(vertical_lines) >= VTS_MIN_VERTICAL_LINES:
        logger.debug(
            f"[VTS] unit={unit.id}, H_lines={len(horizontal_lines)}, "
            f"V_lines={len(vertical_lines)}, score=1.0 (grid pattern)"
        )
        return 1.0

    # Chercher un pattern de texte en grille
    if _detect_text_grid_pattern(unit.blocks, page_width, page_height):
        logger.debug(f"[VTS] unit={unit.id}, text grid pattern detected, score=1.0")
        return 1.0

    logger.debug(f"[VTS] unit={unit.id}, no pattern, score=0.0")
    return 0.0


def _detect_text_grid_pattern(
    blocks: List[TextBlock],
    page_width: float,
    page_height: float,
) -> bool:
    """
    Detecte un pattern de grille dans les positions des blocs texte.

    Cherche des alignements multiples sur les axes X et Y.

    Args:
        blocks: Liste des blocs texte
        page_width: Largeur de la page
        page_height: Hauteur de la page

    Returns:
        True si pattern de grille detecte
    """
    if len(blocks) < 6:  # Minimum pour une grille 2x3
        return False

    if page_width <= 0 or page_height <= 0:
        return False

    # Collecter les positions X et Y des centres
    x_positions = []
    y_positions = []

    for block in blocks:
        if block.bbox is None:
            continue

        cx, cy = block.bbox.center

        if not block.bbox.normalized:
            cx = cx / page_width
            cy = cy / page_height

        x_positions.append(cx)
        y_positions.append(cy)

    if len(x_positions) < 6:
        return False

    # Chercher des clusters de positions alignees
    x_clusters = _find_aligned_clusters(x_positions, tolerance=0.05)
    y_clusters = _find_aligned_clusters(y_positions, tolerance=0.05)

    # Pattern de grille: au moins 2 colonnes distinctes et 2 lignes
    num_columns = len(x_clusters)
    num_rows = len(y_clusters)

    return num_columns >= 2 and num_rows >= 2


def _find_aligned_clusters(
    positions: List[float],
    tolerance: float = 0.05,
) -> List[List[float]]:
    """
    Trouve les clusters de positions alignees.

    Args:
        positions: Liste de positions normalisees (0-1)
        tolerance: Tolerance pour considerer 2 positions alignees

    Returns:
        Liste de clusters (liste de positions)
    """
    if not positions:
        return []

    sorted_positions = sorted(positions)
    clusters = []
    current_cluster = [sorted_positions[0]]

    for pos in sorted_positions[1:]:
        if pos - current_cluster[-1] <= tolerance:
            current_cluster.append(pos)
        else:
            if len(current_cluster) >= 2:  # Cluster significatif
                clusters.append(current_cluster)
            current_cluster = [pos]

    # Ne pas oublier le dernier cluster
    if len(current_cluster) >= 2:
        clusters.append(current_cluster)

    return clusters


def compute_all_signals(unit: VisionUnit) -> VisionSignals:
    """
    Calcule tous les signaux pour une VisionUnit.

    Args:
        unit: VisionUnit a analyser

    Returns:
        VisionSignals avec les 5 valeurs
    """
    ris = compute_raster_image_signal(unit)
    vds = compute_vector_drawing_signal(unit)
    tfs = compute_text_fragmentation_signal(unit)
    sds = compute_spatial_dispersion_signal(unit)
    vts = compute_visual_table_signal(unit)

    signals = VisionSignals(
        RIS=ris,
        VDS=vds,
        TFS=tfs,
        SDS=sds,
        VTS=vts,
    )

    logger.info(
        f"[Signals] unit={unit.id}: RIS={ris:.2f}, VDS={vds:.2f}, "
        f"TFS={tfs:.2f}, SDS={sds:.2f}, VTS={vts:.2f}"
    )

    return signals


__all__ = [
    "compute_raster_image_signal",
    "compute_vector_drawing_signal",
    "compute_text_fragmentation_signal",
    "compute_spatial_dispersion_signal",
    "compute_visual_table_signal",
    "compute_all_signals",
]
