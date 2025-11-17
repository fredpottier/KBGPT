"""
Extractors pour l'ingestion de documents PPTX.

Modules extraits de pptx_pipeline.py pour réutilisabilité.
"""

from .checksum_calculator import calculate_checksum
from .metadata_extractor import extract_pptx_metadata
from .slide_cleaner import (
    get_hidden_slides,
    remove_hidden_slides_inplace,
    validate_pptx_media,
    strip_animated_gifs_from_pptx,
)
from .binary_parser import (
    extract_notes_and_text,
    extract_with_megaparse,
    extract_with_python_pptx,
)

__all__ = [
    # Checksum
    "calculate_checksum",
    # Metadata
    "extract_pptx_metadata",
    # Slide cleaning
    "get_hidden_slides",
    "remove_hidden_slides_inplace",
    "validate_pptx_media",
    "strip_animated_gifs_from_pptx",
    # Binary parsing
    "extract_notes_and_text",
    "extract_with_megaparse",
    "extract_with_python_pptx",
]
