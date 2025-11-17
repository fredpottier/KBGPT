"""
Utilitaires pour le traitement de texte.

Module extrait de pptx_pipeline.py pour réutilisabilité.
"""

import json
import re
from typing import List
from langdetect import detect, DetectorFactory, LangDetectException


# Initialiser seed pour reproductibilité
DetectorFactory.seed = 0


def clean_gpt_response(raw: str) -> str:
    """
    Nettoie la réponse GPT en extrayant le JSON des markdown code blocks.

    Args:
        raw: Réponse brute de GPT

    Returns:
        String JSON nettoyée

    Example:
        >>> clean_gpt_response("```json\\n{...}\\n```")
        "{...}"
    """
    # Extraire JSON des code blocks markdown
    match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", raw, re.DOTALL)
    if match:
        return match.group(1).strip()

    # Extraire JSON brut si présent
    match = re.search(r"(\{.*\})", raw, re.DOTALL)
    if match:
        return match.group(1).strip()

    return raw.strip()


def get_language_iso2(text: str) -> str:
    """
    Détecte la langue d'un texte et retourne le code ISO 639-1 (2 lettres).

    Args:
        text: Texte à analyser

    Returns:
        Code ISO 639-1 (ex: "en", "fr") ou "en" par défaut

    Example:
        >>> get_language_iso2("Bonjour le monde")
        "fr"
    """
    if not text or len(text.strip()) < 20:
        return "en"  # Défaut si texte trop court

    try:
        return detect(text)
    except LangDetectException:
        return "en"


def estimate_tokens(text: str) -> int:
    """
    Estime le nombre de tokens d'un texte (heuristique simple).

    Args:
        text: Texte à analyser

    Returns:
        Estimation du nombre de tokens

    Note:
        Utilise l'heuristique : 1 token ≈ 4 caractères (moyenne pour l'anglais)
    """
    return len(text) // 4


def recursive_chunk(text: str, max_len: int = 400, overlap_ratio: float = 0.15) -> List[str]:
    """
    Découpe un texte en chunks avec overlap pour préserver le contexte.

    Args:
        text: Texte à découper
        max_len: Longueur maximale d'un chunk (caractères)
        overlap_ratio: Ratio d'overlap entre chunks (0.15 = 15%)

    Returns:
        Liste des chunks

    Example:
        >>> recursive_chunk("A" * 1000, max_len=400, overlap_ratio=0.15)
        # Retourne 3 chunks avec 15% overlap
    """
    if len(text) <= max_len:
        return [text]

    chunks = []
    start = 0
    step = int(max_len * (1 - overlap_ratio))

    while start < len(text):
        end = start + max_len
        chunks.append(text[start:end])
        if end >= len(text):
            break
        start += step

    return chunks
