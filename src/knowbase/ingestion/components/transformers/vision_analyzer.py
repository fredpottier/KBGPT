"""
Analyse de slides via GPT-4 Vision (mode VISION avec images).

Module wrapper extrait de pptx_pipeline.py.
Pour l'instant, importe les fonctions du pipeline original.
TODO: Extraire complètement les fonctions ask_gpt_slide_analysis et ask_gpt_vision_summary
"""

from pathlib import Path
from typing import List, Dict, Any, Optional
import logging

# Import temporaire depuis le pipeline original
import sys
parent_dir = Path(__file__).parent.parent / "pipelines"
sys.path.insert(0, str(parent_dir))

try:
    from pptx_pipeline import (
        ask_gpt_slide_analysis,
        ask_gpt_vision_summary,
    )
except ImportError:
    # Fallback si l'import échoue
    def ask_gpt_slide_analysis(*args, **kwargs):
        raise NotImplementedError("ask_gpt_slide_analysis not yet extracted")

    def ask_gpt_vision_summary(*args, **kwargs):
        raise NotImplementedError("ask_gpt_vision_summary not yet extracted")


__all__ = [
    "ask_gpt_slide_analysis",
    "ask_gpt_vision_summary",
]
