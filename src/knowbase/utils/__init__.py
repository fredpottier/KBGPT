"""
Utilitaires OSMOSE.

Ce module contient des fonctions utilitaires partagées par les différents
composants du système OSMOSE.
"""

from .normalize import normalize_canonical_key
from .text_rendering import (
    strip_markers,
    render_quote,
    make_embedding_text,
    make_embedding_text_aggressive,
)

__all__ = [
    "normalize_canonical_key",
    "strip_markers",
    "render_quote",
    "make_embedding_text",
    "make_embedding_text_aggressive",
]
