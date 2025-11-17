"""
Écriture de chunks enrichis dans Qdrant.

Module wrapper extrait de pptx_pipeline.py.
Pour l'instant, importe la fonction du pipeline original.
TODO: Extraire complètement la fonction ingest_chunks avec toute sa logique métier
"""

from pathlib import Path
from typing import List, Dict, Any, Optional
import logging

# Import temporaire depuis le pipeline original
import sys
parent_dir = Path(__file__).parent.parent / "pipelines"
sys.path.insert(0, str(parent_dir))

try:
    from pptx_pipeline import ingest_chunks, embed_texts
except ImportError:
    # Fallback si l'import échoue
    def ingest_chunks(*args, **kwargs):
        raise NotImplementedError("ingest_chunks not yet extracted from pptx_pipeline")

    def embed_texts(*args, **kwargs):
        raise NotImplementedError("embed_texts not yet extracted from pptx_pipeline")


__all__ = [
    "ingest_chunks",
    "embed_texts",
]
