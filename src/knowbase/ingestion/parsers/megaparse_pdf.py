"""
Parser PDF intelligent utilisant MegaParse pour découpage en blocs sémantiques cohérents.

MegaParse permet de :
- Découper le PDF en sections/paragraphes/tableaux/listes (pas en pages arbitraires)
- Préserver la structure du document (titres, hiérarchie)
- Identifier les blocs de contenu cohérents
- Extraire les tableaux de manière structurée
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import List, Dict, Any, Optional

logger = logging.getLogger(__name__)

# Import conditionnel de MegaParse (comme dans pptx_pipeline.py)
try:
    from megaparse import MegaParse
    MEGAPARSE_AVAILABLE = True
    logger.info("✅ MegaParse disponible pour PDF")
except ImportError as e:
    MEGAPARSE_AVAILABLE = False
    MegaParse = None
    logger.warning(f"⚠️ MegaParse non disponible pour PDF, fallback pdftotext: {e}")


def parse_pdf_with_megaparse(
    pdf_path: Path,
    use_vision: bool = False
) -> List[Dict[str, Any]]:
    """
    Utilise MegaParse pour découper un PDF en blocs sémantiques cohérents.

    Args:
        pdf_path: Chemin vers le fichier PDF
        use_vision: Si True, utilise la version Vision de MegaParse (plus précis mais plus lent)

    Returns:
        List of semantic blocks with:
        - block_type: "section" | "paragraph" | "table" | "list" | "text"
        - title: Optional heading (for sections)
        - content: Text content
        - page_range: (start_page, end_page)
        - metadata: Additional structural info (level, style, etc.)

    Raises:
        Exception: Si l'extraction échoue
    """
    # Si MegaParse n'est pas disponible, utiliser directement le fallback
    if not MEGAPARSE_AVAILABLE:
        logger.warning(f"⚠️ MegaParse non disponible, fallback pour {pdf_path.name}")
        return _fallback_simple_extraction(pdf_path)

    logger.info(f"🔍 MegaParse: analyse {pdf_path.name}")

    try:
        # Initialiser le parser
        # Note: Pour l'instant, use_vision est ignoré car MegaParseVision n'existe pas dans cette version
        if use_vision:
            logger.warning("⚠️ Mode VISION demandé mais non disponible dans cette version de MegaParse")
            logger.info("📄 MegaParse STANDARD utilisé à la place")
        else:
            logger.info("📄 MegaParse STANDARD: extraction texte structurée")

        parser = MegaParse()

        # Parser le document
        document = parser.load(str(pdf_path))

        # Convertir les résultats MegaParse en notre format standardisé
        blocks = []
        current_page = 1

        # MegaParse retourne un objet avec des chunks/sections
        # L'API peut varier selon la version, on gère plusieurs formats
        if hasattr(document, 'chunks'):
            # Format avec chunks
            for idx, chunk in enumerate(document.chunks):
                block = _convert_chunk_to_block(chunk, idx, current_page)
                blocks.append(block)
                # Estimer la page (approximatif)
                if hasattr(chunk, 'page'):
                    current_page = chunk.page
                elif len(chunk.text) > 500:  # Approximation: gros chunk = nouvelle page
                    current_page += 1

        elif hasattr(document, 'sections'):
            # Format avec sections
            for idx, section in enumerate(document.sections):
                block = _convert_section_to_block(section, idx, current_page)
                blocks.append(block)
                if hasattr(section, 'page_end'):
                    current_page = section.page_end

        elif hasattr(document, 'text'):
            # Format simple: juste le texte complet
            # On découpe intelligemment en paragraphes
            logger.warning("⚠️ MegaParse retourne format simple, découpage manuel en paragraphes")
            blocks = _split_text_into_blocks(document.text)

        elif isinstance(document, str):
            # MegaParse retourne directement un string (API simplifiée)
            logger.info("📄 MegaParse retourne directement le texte, découpage intelligent en blocs")
            blocks = _split_text_into_blocks(document)

        else:
            raise ValueError(f"Format MegaParse non reconnu: {type(document)}")

        logger.info(f"✅ MegaParse: {len(blocks)} blocs sémantiques extraits")

        # Log des statistiques
        block_types = {}
        for block in blocks:
            block_type = block.get('block_type', 'unknown')
            block_types[block_type] = block_types.get(block_type, 0) + 1

        logger.info(f"📊 Répartition des blocs: {block_types}")

        return blocks

    except Exception as e:
        logger.error(f"❌ Erreur MegaParse sur {pdf_path.name}: {e}")
        # Fallback: découpage simple du texte
        logger.warning("⚠️ Fallback: extraction texte simple via pdftotext")
        return _fallback_simple_extraction(pdf_path)


def _convert_chunk_to_block(chunk: Any, idx: int, current_page: int) -> Dict[str, Any]:
    """Convertit un chunk MegaParse en notre format de bloc."""
    block_type = "text"
    title = None

    # Détecter le type de bloc selon les propriétés du chunk
    if hasattr(chunk, 'type'):
        chunk_type = str(chunk.type).lower()
        if 'heading' in chunk_type or 'title' in chunk_type:
            block_type = "section"
            title = chunk.text.strip()
        elif 'table' in chunk_type:
            block_type = "table"
        elif 'list' in chunk_type:
            block_type = "list"
        elif 'paragraph' in chunk_type:
            block_type = "paragraph"

    # Extraire le contenu
    content = chunk.text if hasattr(chunk, 'text') else str(chunk)

    # Détecter automatiquement les titres (heuristique)
    if block_type == "text" and len(content) < 100 and content.isupper():
        block_type = "section"
        title = content.strip()

    # Page range
    page_start = chunk.page if hasattr(chunk, 'page') else current_page
    page_end = chunk.page_end if hasattr(chunk, 'page_end') else page_start

    return {
        "block_type": block_type,
        "block_index": idx,
        "title": title,
        "content": content.strip(),
        "page_range": (page_start, page_end),
        "metadata": {
            "level": getattr(chunk, 'level', 0),
            "style": getattr(chunk, 'style', None),
            "font": getattr(chunk, 'font', None),
            "length": len(content),
        }
    }


def _convert_section_to_block(section: Any, idx: int, current_page: int) -> Dict[str, Any]:
    """Convertit une section MegaParse en notre format de bloc."""
    return {
        "block_type": "section",
        "block_index": idx,
        "title": getattr(section, 'title', None),
        "content": section.text if hasattr(section, 'text') else str(section),
        "page_range": (
            getattr(section, 'page_start', current_page),
            getattr(section, 'page_end', current_page)
        ),
        "metadata": {
            "level": getattr(section, 'level', 0),
            "subsections": len(getattr(section, 'subsections', [])),
        }
    }


def _split_text_into_blocks(text: str) -> List[Dict[str, Any]]:
    """
    Découpe intelligent du texte en blocs cohérents (fallback si MegaParse retourne texte brut).
    Utilise des heuristiques simples : double saut de ligne = nouveau bloc.
    """
    blocks = []
    paragraphs = text.split('\n\n')

    for idx, para in enumerate(paragraphs):
        para = para.strip()
        if not para or len(para) < 20:  # Ignorer les blocs trop courts
            continue

        # Détecter les titres (heuristique : court, majuscules, ou commence par chiffre/bullet)
        is_title = (
            len(para) < 100 and
            (para.isupper() or para[0].isdigit() or para.startswith('•') or para.startswith('-'))
        )

        block_type = "section" if is_title else "paragraph"
        title = para if is_title else None

        blocks.append({
            "block_type": block_type,
            "block_index": idx,
            "title": title,
            "content": para,
            "page_range": (1, 1),  # Page inconnue
            "metadata": {
                "level": 1 if is_title else 0,
                "length": len(para),
                "fallback": True,
            }
        })

    logger.info(f"📝 Découpage simple: {len(blocks)} paragraphes extraits")
    return blocks


def _fallback_simple_extraction(pdf_path: Path) -> List[Dict[str, Any]]:
    """
    Extraction de secours si MegaParse échoue.
    Utilise pdftotext pour extraire le texte brut puis découpe en paragraphes.
    """
    import subprocess

    try:
        txt_output = pdf_path.with_suffix(".txt")
        logger.info(f"📑 Fallback pdftotext: {pdf_path.name}")

        # Supprimer les warnings stderr (comme "Invalid Font Weight")
        subprocess.run(
            ["pdftotext", str(pdf_path), str(txt_output)],
            check=True,
            stderr=subprocess.DEVNULL
        )

        text = txt_output.read_text(encoding="utf-8", errors="ignore")
        logger.debug(f"Extracted text length: {len(text)}")

        # Nettoyer le fichier temporaire
        txt_output.unlink(missing_ok=True)

        return _split_text_into_blocks(text)

    except Exception as e:
        logger.error(f"❌ Fallback extraction échouée: {e}")
        # Dernier recours : bloc unique vide
        return [{
            "block_type": "text",
            "block_index": 0,
            "title": None,
            "content": "",
            "page_range": (1, 1),
            "metadata": {"error": str(e)}
        }]
