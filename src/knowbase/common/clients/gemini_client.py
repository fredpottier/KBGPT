"""
🌊 OSMOSE - Google Gemini Client

Client pour appels LLM Gemini avec support cache optionnel.

Phase 1.8.1e - Migration Gemini
"""
import os
import logging
from typing import Optional

logger = logging.getLogger(__name__)

# Import optionnel (peut ne pas être installé)
try:
    import google.generativeai as genai
    GEMINI_AVAILABLE = True
except ImportError:
    GEMINI_AVAILABLE = False
    logger.warning("[OSMOSE:Gemini] google-generativeai not installed")


def get_gemini_client():
    """
    Initialise le client Google Gemini.

    Raises:
        ValueError: Si GOOGLE_API_KEY manquante ou google-generativeai non installé
    """
    if not GEMINI_AVAILABLE:
        raise ValueError("google-generativeai package not installed. Run: pip install google-generativeai")

    api_key = os.getenv("GOOGLE_API_KEY")
    if not api_key:
        raise ValueError("GOOGLE_API_KEY not found in environment")

    genai.configure(api_key=api_key)
    logger.info("[OSMOSE:Gemini] ✅ Client configured")

    return genai


def is_gemini_available() -> bool:
    """Vérifie si Gemini est disponible (package + API key)."""
    if not GEMINI_AVAILABLE:
        return False

    api_key = os.getenv("GOOGLE_API_KEY")
    return api_key is not None and len(api_key) > 0


def get_gemini_model(model_name: str, cache_id: Optional[str] = None):
    """
    Obtient une instance de modèle Gemini.

    Args:
        model_name: Nom du modèle (ex: "gemini-1.5-flash-8b")
        cache_id: ID de cache Gemini (optionnel, pour Context Caching)

    Returns:
        genai.GenerativeModel instance
    """
    if not GEMINI_AVAILABLE:
        raise ValueError("google-generativeai package not installed")

    client = get_gemini_client()

    if cache_id:
        # Utiliser cache existant
        try:
            from google.generativeai import caching
            cached_content = caching.CachedContent.get(cache_id)
            model = client.GenerativeModel.from_cached_content(cached_content)
            logger.debug(f"[OSMOSE:Gemini] Using cached model: {cache_id}")
            return model
        except Exception as e:
            logger.warning(f"[OSMOSE:Gemini] Failed to load cache {cache_id}: {e}, using non-cached model")
            # Fallback sur modèle sans cache
            return client.GenerativeModel(model_name)
    else:
        # Modèle standard sans cache
        return client.GenerativeModel(model_name)
