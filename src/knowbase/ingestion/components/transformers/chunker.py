"""
Chunking de slides et textes pour optimisation tokens LLM.

Module extrait de pptx_pipeline.py pour réutilisabilité.
"""

from typing import List, Dict, Any


def chunk_slides_by_tokens(
    slides_data: List[Dict[str, Any]],
    max_tokens: int
) -> List[List[Dict[str, Any]]]:
    """
    Découpe les slides en chunks selon une limite de tokens.

    Args:
        slides_data: Liste des slides extraits
        max_tokens: Nombre maximum de tokens par chunk

    Returns:
        List[List[Dict]]: Liste de chunks de slides

    Note:
        Utilise une estimation simple : 1 token ≈ 4 caractères
    """
    chunks = []
    current_chunk = []
    current_tokens = 0

    for slide in slides_data:
        text = slide.get("text", "") or ""
        notes = slide.get("notes", "") or ""
        content = f"{text}\n{notes}"

        # Estimation tokens : 1 token ≈ 4 caractères
        slide_tokens = len(content) // 4

        if current_tokens + slide_tokens > max_tokens and current_chunk:
            # Chunk courant plein, commencer un nouveau
            chunks.append(current_chunk)
            current_chunk = [slide]
            current_tokens = slide_tokens
        else:
            current_chunk.append(slide)
            current_tokens += slide_tokens

    # Ajouter le dernier chunk
    if current_chunk:
        chunks.append(current_chunk)

    return chunks


def recursive_chunk(
    text: str,
    max_len: int = 400,
    overlap_ratio: float = 0.15
) -> List[str]:
    """
    Découpe un texte en chunks avec overlap pour préserver le contexte.

    Args:
        text: Texte à découper
        max_len: Longueur maximale d'un chunk (caractères)
        overlap_ratio: Ratio d'overlap entre chunks (0.15 = 15%)

    Returns:
        List[str]: Liste des chunks

    Note:
        Importé depuis utils.text_utils pour compatibilité legacy
    """
    from ..utils.text_utils import recursive_chunk as rc
    return rc(text, max_len, overlap_ratio)
