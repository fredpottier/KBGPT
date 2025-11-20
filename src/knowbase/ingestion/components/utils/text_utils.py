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


def clean_gpt_response(raw: str, logger=None) -> str:
    """
    Nettoie la réponse GPT et répare le JSON tronqué si nécessaire.

    LOGIQUE ORIGINALE RESTAURÉE: Inclut réparation automatique de JSON tronqué
    pour gérer les cas de timeouts LLM ou réponses incomplètes.

    Args:
        raw: Réponse brute de GPT
        logger: Logger optionnel pour diagnostic

    Returns:
        String JSON nettoyée et réparée

    Example:
        >>> clean_gpt_response("```json\\n{...}\\n```")
        "{...}"
    """
    import logging
    if logger is None:
        logger = logging.getLogger(__name__)

    s = (raw or "").strip()
    # Retirer les markdown code blocks
    s = re.sub(r"^```(?:json)?\s*", "", s)
    s = re.sub(r"\s*```$", "", s)
    s = s.strip()

    # Validation et réparation basique du JSON tronqué
    if s:
        try:
            # Test si le JSON est valide
            json.loads(s)
            return s
        except json.JSONDecodeError as e:
            logger.warning(
                f"JSON invalide détecté, tentative de réparation: {str(e)[:100]}"
            )

            # Tentative de réparation simple pour JSON tronqué
            if s.endswith('"'):
                # JSON tronqué au milieu d'une string
                s = s + "}"
                if s.count("[") > s.count("]"):
                    s = s + "]"
            elif s.endswith(","):
                # JSON tronqué après une virgule
                s = s[:-1]  # Retirer la virgule
                if s.count("[") > s.count("]"):
                    s = s + "]"
                if s.count("{") > s.count("}"):
                    s = s + "}"
            elif not s.endswith(("]", "}")):
                # JSON clairement tronqué
                if s.count("[") > s.count("]"):
                    s = s + "]"
                if s.count("{") > s.count("}"):
                    s = s + "}"

            # Test final de la réparation
            try:
                json.loads(s)
                logger.info("JSON réparé avec succès")
                return s
            except json.JSONDecodeError:
                logger.error("Impossible de réparer le JSON, retour d'un array vide")
                return "[]"
    else:
        logger.error("❌ Réponse LLM vide")
        return "[]"

    return s


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

    LOGIQUE ORIGINALE RESTAURÉE: Découpage par TOKENS (mots), pas par caractères.
    C'est critique pour respecter max_tokens dans les appels LLM.

    Args:
        text: Texte à découper
        max_len: Longueur maximale d'un chunk (en TOKENS/mots)
        overlap_ratio: Ratio d'overlap entre chunks (0.15 = 15%)

    Returns:
        Liste des chunks

    Example:
        >>> recursive_chunk("word " * 1000, max_len=400, overlap_ratio=0.15)
        # Retourne chunks de ~400 tokens avec 15% overlap
    """
    tokens = text.split()
    step = int(max_len * (1 - overlap_ratio))
    chunks = []

    for i in range(0, len(tokens), step):
        chunk = tokens[i : i + max_len]
        chunks.append(" ".join(chunk))
        if i + max_len >= len(tokens):
            break

    return chunks
