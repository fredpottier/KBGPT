"""
Utilitaires réutilisables pour l'ingestion de documents.

Modules extraits de pptx_pipeline.py pour modularité.
"""

from .subprocess_utils import run_cmd
from .image_utils import encode_image_base64, normalize_public_url
from .text_utils import (
    clean_gpt_response,
    get_language_iso2,
    estimate_tokens,
    recursive_chunk,
)

__all__ = [
    # Subprocess
    "run_cmd",
    # Images
    "encode_image_base64",
    "normalize_public_url",
    # Text
    "clean_gpt_response",
    "get_language_iso2",
    "estimate_tokens",
    "recursive_chunk",
]
