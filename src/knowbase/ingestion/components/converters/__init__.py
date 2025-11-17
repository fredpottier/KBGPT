"""
Converters pour transformation de formats de documents.

Modules extraits de pptx_pipeline.py pour réutilisabilité.
"""

from .pptx_to_pdf import convert_pptx_to_pdf, resolve_soffice_path
from .pdf_to_images import convert_pdf_to_images_pymupdf

__all__ = [
    "convert_pptx_to_pdf",
    "resolve_soffice_path",
    "convert_pdf_to_images_pymupdf",
]
