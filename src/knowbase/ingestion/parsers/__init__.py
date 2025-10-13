"""
Parsers pour extraction intelligente de contenu depuis différents formats.
"""
from .megaparse_pdf import parse_pdf_with_megaparse

__all__ = ["parse_pdf_with_megaparse"]
