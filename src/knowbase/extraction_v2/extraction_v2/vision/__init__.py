"""
Vision Path pour Extraction V2.

VisionAnalyzer: Analyse d'images via GPT-4o Vision.
Prompts: Prompt Vision canonique avec Domain Context injectable.
TextGenerator: Génération de vision_text descriptif pour OSMOSE.
"""

from knowbase.extraction_v2.vision.analyzer import VisionAnalyzer
from knowbase.extraction_v2.vision.prompts import (
    build_vision_prompt,
    VISION_SYSTEM_PROMPT,
    VISION_JSON_SCHEMA,
)
from knowbase.extraction_v2.vision.text_generator import VisionTextGenerator

__all__ = [
    "VisionAnalyzer",
    "build_vision_prompt",
    "VISION_SYSTEM_PROMPT",
    "VISION_JSON_SCHEMA",
    "VisionTextGenerator",
]
