"""
Transformers pour enrichissement LLM des documents.

Modules extraits de pptx_pipeline.py pour réutilisabilité.
"""

from .chunker import chunk_slides_by_tokens, recursive_chunk
from .deck_summarizer import summarize_large_pptx
from .llm_analyzer import analyze_deck_summary, ask_gpt_slide_analysis_text_only
from .vision_analyzer import ask_gpt_slide_analysis, ask_gpt_vision_summary
from .vision_gating import (
    VisionDecision,
    GatingResult,
    should_use_vision,
    estimate_vision_savings,
)

__all__ = [
    # Chunking
    "chunk_slides_by_tokens",
    "recursive_chunk",
    # Summarization
    "summarize_large_pptx",
    # LLM Analysis
    "analyze_deck_summary",
    "ask_gpt_slide_analysis_text_only",
    # Vision Analysis
    "ask_gpt_slide_analysis",
    "ask_gpt_vision_summary",
    # Vision Gating
    "VisionDecision",
    "GatingResult",
    "should_use_vision",
    "estimate_vision_savings",
]
