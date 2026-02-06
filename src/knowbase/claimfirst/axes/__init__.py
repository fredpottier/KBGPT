# src/knowbase/claimfirst/axes/__init__.py
"""
Composants de détection et gestion des axes d'applicabilité.

INV-25: Axis keys neutres + display_name optionnel
INV-26: Toute axis_value a evidence (passage_id ou snippet_ref)

Composants:
- ApplicabilityAxisDetector: Détecte les axes depuis le corpus
- AxisOrderInferrer: Infère l'ordre des valeurs d'un axe
- AxisValueValidator: Valide les valeurs via LLM (Extract-then-Validate)
"""

from knowbase.claimfirst.axes.axis_detector import (
    ApplicabilityAxisDetector,
    AxisObservation,
)
from knowbase.claimfirst.axes.axis_order_inferrer import (
    AxisOrderInferrer,
    OrderInferenceResult,
)
from knowbase.claimfirst.axes.axis_value_validator import (
    AxisValueValidator,
    ValidationResult,
)

__all__ = [
    "ApplicabilityAxisDetector",
    "AxisObservation",
    "AxisOrderInferrer",
    "OrderInferenceResult",
    "AxisValueValidator",
    "ValidationResult",
]
