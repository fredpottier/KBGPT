"""
Analyse de slides via LLM (mode text-only).

Module wrapper extrait de pptx_pipeline.py.
Pour l'instant, importe les fonctions du pipeline original.
TODO: Extraire complètement les fonctions analyze_deck_summary et ask_gpt_slide_analysis_text_only
"""

from pathlib import Path
from typing import List, Dict, Any, Optional
import logging

# Import temporaire depuis le pipeline original
# Ces fonctions seront extraites dans une prochaine itération
import sys
parent_dir = Path(__file__).parent.parent / "pipelines"
sys.path.insert(0, str(parent_dir))

try:
    from pptx_pipeline import (
        analyze_deck_summary,
        ask_gpt_slide_analysis_text_only,
    )
except ImportError:
    # Fallback si l'import échoue
    def analyze_deck_summary(*args, **kwargs):
        raise NotImplementedError("analyze_deck_summary not yet extracted")

    def ask_gpt_slide_analysis_text_only(*args, **kwargs):
        raise NotImplementedError("ask_gpt_slide_analysis_text_only not yet extracted")


__all__ = [
    "analyze_deck_summary",
    "ask_gpt_slide_analysis_text_only",
]
