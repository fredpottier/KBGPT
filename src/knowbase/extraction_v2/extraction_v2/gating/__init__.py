"""
Vision Gating V4 pour Extraction V2.

5 signaux:
- RIS: Raster Image Signal
- VDS: Vector Drawing Signal
- TFS: Text Fragmentation Signal
- SDS: Spatial Dispersion Signal
- VTS: Visual Table Signal

Scoring pondéré avec seuils configurables.
"""

from knowbase.extraction_v2.gating.signals import (
    compute_raster_image_signal,
    compute_vector_drawing_signal,
    compute_text_fragmentation_signal,
    compute_spatial_dispersion_signal,
    compute_visual_table_signal,
    compute_all_signals,
)
from knowbase.extraction_v2.gating.engine import GatingEngine
from knowbase.extraction_v2.gating.weights import (
    DEFAULT_GATING_WEIGHTS,
    GATING_THRESHOLDS,
    EXPERIMENTAL_THRESHOLDS,
)

__all__ = [
    # Signaux
    "compute_raster_image_signal",
    "compute_vector_drawing_signal",
    "compute_text_fragmentation_signal",
    "compute_spatial_dispersion_signal",
    "compute_visual_table_signal",
    "compute_all_signals",
    # Engine
    "GatingEngine",
    # Configuration
    "DEFAULT_GATING_WEIGHTS",
    "GATING_THRESHOLDS",
    "EXPERIMENTAL_THRESHOLDS",
]
