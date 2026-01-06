"""
Vision Path pour Extraction V2.

VisionAnalyzer: Analyse d'images via GPT-4o Vision.
Prompts: Prompt Vision canonique avec Domain Context injectable.
TextGenerator: Génération de vision_text descriptif pour OSMOSE.
DiagramInterpreter: QW-3 - Extraction structurée avec routing adaptatif LITE/FULL.
"""

from knowbase.extraction_v2.vision.analyzer import VisionAnalyzer
from knowbase.extraction_v2.vision.prompts import (
    build_vision_prompt,
    VISION_SYSTEM_PROMPT,
    VISION_JSON_SCHEMA,
    # QW-3: VISION_LITE
    build_vision_lite_prompt,
    VISION_LITE_SYSTEM_PROMPT,
    VISION_LITE_JSON_SCHEMA,
)
from knowbase.extraction_v2.vision.text_generator import VisionTextGenerator
from knowbase.extraction_v2.vision.diagram_interpreter import (
    DiagramInterpreter,
    InterpretationResult,
    ExtractionMethod,
    get_diagram_interpreter,
)

__all__ = [
    "VisionAnalyzer",
    "build_vision_prompt",
    "VISION_SYSTEM_PROMPT",
    "VISION_JSON_SCHEMA",
    "VisionTextGenerator",
    # QW-3: DiagramInterpreter
    "DiagramInterpreter",
    "InterpretationResult",
    "ExtractionMethod",
    "get_diagram_interpreter",
    "build_vision_lite_prompt",
    "VISION_LITE_SYSTEM_PROMPT",
    "VISION_LITE_JSON_SCHEMA",
]
