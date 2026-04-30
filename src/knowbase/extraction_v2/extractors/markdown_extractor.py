"""
MarkdownExtractor — P3.1 fix.

Extracteur dédié pour fichiers .md / .markdown qui contourne le bug Docling
où le full_text était vide. Lecture directe du fichier source + parsing
sections par headers `#`/`##`/etc.

Domain-agnostic, structurellement minimal.
"""
from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class MarkdownExtractor:
    """Extracteur léger pour markdown source.

    Lit le fichier .md, retourne un dict compatible avec le pipeline V2 :
    {
        "document_id": str,
        "full_text": str,
        "pages": [{"page_no": int, "text_content": str}],
        "metrics": {"total_pages": int, "n_chars": int}
    }
    """

    SUPPORTED_EXTENSIONS = {".md", ".markdown"}

    @staticmethod
    def is_supported(file_path: Path) -> bool:
        return file_path.suffix.lower() in MarkdownExtractor.SUPPORTED_EXTENSIONS

    @staticmethod
    def extract(file_path: Path, document_id: str | None = None) -> dict[str, Any]:
        """Extrait le contenu d'un fichier .md.

        Args:
            file_path: Path vers le .md
            document_id: id du doc (sinon dérivé du filename)

        Returns:
            dict compatible structure ExtractionResult avec full_text non-vide.
        """
        if not file_path.exists():
            raise FileNotFoundError(f"Markdown file not found: {file_path}")
        if not MarkdownExtractor.is_supported(file_path):
            raise ValueError(f"Not a markdown file: {file_path.suffix}")

        try:
            content = file_path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            content = file_path.read_text(encoding="latin-1")

        if not content.strip():
            logger.warning(f"Markdown file empty: {file_path}")
            return {
                "document_id": document_id or file_path.stem,
                "full_text": "",
                "pages": [],
                "metrics": {"total_pages": 0, "n_chars": 0},
            }

        # Découpe par sections (## headers de niveau 2)
        # Domain-agnostic : on fait juste un découpage structurel, pas de regex domaine.
        sections = re.split(r"\n(?=#{1,3}\s)", content)
        pages = []
        for i, section in enumerate(sections):
            section = section.strip()
            if not section:
                continue
            pages.append({
                "page_no": i + 1,
                "text_content": section,
                "section_id": f"section_{i + 1}",
            })

        # Si aucune section identifiée → 1 seule "page" avec tout le contenu
        if not pages:
            pages = [{
                "page_no": 1,
                "text_content": content,
                "section_id": "section_1",
            }]

        return {
            "document_id": document_id or file_path.stem,
            "full_text": content,  # Le markdown source est utilisable as-is comme full_text
            "pages": pages,
            "metrics": {
                "total_pages": len(pages),
                "n_chars": len(content),
                "n_sections": len(pages),
            },
        }
