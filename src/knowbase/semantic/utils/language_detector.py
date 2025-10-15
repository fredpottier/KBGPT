"""
🌊 OSMOSE Semantic Intelligence V2.1 - Détection Langue

Détection automatique de langue avec fasttext lid.176.bin
"""

import fasttext
from functools import lru_cache
from typing import Optional, Tuple
import logging
import os

logger = logging.getLogger(__name__)


class LanguageDetector:
    """
    Détection automatique de langue avec fasttext.

    Supporte 176 langues avec le modèle lid.176.bin.
    Retourne codes ISO 639-1 (en, fr, de, es, etc.).

    Phase 1 V2.1 - Semaine 1
    """

    def __init__(self, config):
        """
        Initialise le détecteur de langue.

        Args:
            config: Configuration SemanticConfig avec config.language_detection
        """
        self.config = config
        self.model_path = config.language_detection.model_path
        self.confidence_threshold = config.language_detection.confidence_threshold
        self.fallback_language = config.language_detection.fallback_language
        self.supported_languages = config.language_detection.supported_languages

        # Charger le modèle fasttext
        if not os.path.exists(self.model_path):
            logger.error(
                f"[OSMOSE] ❌ Language detection model not found: {self.model_path}\n"
                f"Download with:\n"
                f"  wget https://dl.fbaipublicfiles.com/fasttext/supervised-models/lid.176.bin\n"
                f"  mv lid.176.bin {self.model_path}"
            )
            self.model = None
        else:
            try:
                # Charger avec fasttext (supprime le warning verbose)
                self.model = fasttext.load_model(self.model_path)
                logger.info(f"[OSMOSE] ✅ Language detection model loaded: {self.model_path}")
            except Exception as e:
                logger.error(f"[OSMOSE] ❌ Error loading language model: {e}")
                self.model = None

    @lru_cache(maxsize=500)
    def detect(self, text: str) -> str:
        """
        Détecte la langue d'un texte (ISO 639-1).

        Cache LRU pour éviter de détecter plusieurs fois le même texte.

        Args:
            text: Texte à analyser

        Returns:
            str: Code langue ISO 639-1 (ex: "en", "fr", "de")
        """
        if self.model is None:
            logger.warning("[OSMOSE] Language detection model not loaded, using fallback")
            return self.fallback_language

        # Nettoyer le texte (supprimer newlines, limiter à 1000 chars)
        text_clean = text.replace('\n', ' ').strip()[:1000]

        if not text_clean:
            return self.fallback_language

        try:
            # Prédire avec fasttext (k=1 pour top-1)
            predictions = self.model.predict(text_clean, k=1)
            lang_label = predictions[0][0]  # '__label__en'
            confidence = predictions[1][0]  # 0.95

            # Extraire code langue (ISO 639-1)
            lang_code = lang_label.replace('__label__', '')

            # Vérifier confiance et langue supportée
            if confidence < self.confidence_threshold:
                logger.debug(
                    f"[OSMOSE] Language detection confidence too low: {confidence:.2f} < {self.confidence_threshold}, "
                    f"using fallback '{self.fallback_language}'"
                )
                return self.fallback_language

            if lang_code not in self.supported_languages:
                logger.debug(
                    f"[OSMOSE] Language '{lang_code}' not in supported languages, "
                    f"using fallback '{self.fallback_language}'"
                )
                return self.fallback_language

            logger.debug(
                f"[OSMOSE] Language detected: {lang_code} (confidence: {confidence:.2f})"
            )

            return lang_code

        except Exception as e:
            logger.error(f"[OSMOSE] Error during language detection: {e}")
            return self.fallback_language

    def detect_with_confidence(self, text: str) -> Tuple[str, float]:
        """
        Détecte la langue avec le score de confiance.

        Args:
            text: Texte à analyser

        Returns:
            Tuple[str, float]: (lang_code, confidence)
        """
        if self.model is None:
            return (self.fallback_language, 0.0)

        text_clean = text.replace('\n', ' ').strip()[:1000]

        if not text_clean:
            return (self.fallback_language, 0.0)

        try:
            predictions = self.model.predict(text_clean, k=1)
            lang_label = predictions[0][0]
            confidence = float(predictions[1][0])

            lang_code = lang_label.replace('__label__', '')

            # Retourner même si confiance faible ou langue non supportée
            # (appelant décide quoi faire)
            return (lang_code, confidence)

        except Exception as e:
            logger.error(f"[OSMOSE] Error during language detection: {e}")
            return (self.fallback_language, 0.0)

    def detect_multiple(self, text: str, top_k: int = 3) -> list:
        """
        Détecte les top-k langues possibles.

        Utile pour textes multilingues ou ambigus.

        Args:
            text: Texte à analyser
            top_k: Nombre de langues à retourner

        Returns:
            list: Liste de (lang_code, confidence) triée par confiance
        """
        if self.model is None:
            return [(self.fallback_language, 0.0)]

        text_clean = text.replace('\n', ' ').strip()[:1000]

        if not text_clean:
            return [(self.fallback_language, 0.0)]

        try:
            predictions = self.model.predict(text_clean, k=top_k)
            lang_labels = predictions[0]
            confidences = predictions[1]

            results = []
            for label, conf in zip(lang_labels, confidences):
                lang_code = label.replace('__label__', '')
                results.append((lang_code, float(conf)))

            return results

        except Exception as e:
            logger.error(f"[OSMOSE] Error during language detection: {e}")
            return [(self.fallback_language, 0.0)]

    def is_supported(self, lang_code: str) -> bool:
        """
        Vérifie si une langue est supportée.

        Args:
            lang_code: Code langue ISO 639-1

        Returns:
            bool: True si supportée
        """
        return lang_code in self.supported_languages

    def clear_cache(self):
        """
        Vide le cache LRU.
        """
        self.detect.cache_clear()
        logger.info("[OSMOSE] Language detection cache cleared")


# ===================================
# FACTORY PATTERN
# ===================================

_detector_instance: Optional[LanguageDetector] = None


def get_language_detector(config) -> LanguageDetector:
    """
    Récupère l'instance singleton du détecteur de langue.

    Args:
        config: Configuration SemanticConfig

    Returns:
        LanguageDetector: Instance unique
    """
    global _detector_instance

    if _detector_instance is None:
        _detector_instance = LanguageDetector(config)

    return _detector_instance
