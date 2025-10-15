"""
🌊 OSMOSE Semantic Intelligence V2.1 - NER Multilingue

Gestionnaire Named Entity Recognition multilingue avec spaCy
"""

import spacy
from typing import List, Dict, Optional
from functools import lru_cache
import logging

logger = logging.getLogger(__name__)


class MultilingualNER:
    """
    Gestionnaire NER multilingue avec cache.

    Supporte:
    - EN: en_core_web_trf (transformer anglais)
    - FR: fr_core_news_trf (transformer français)
    - DE: de_core_news_trf (transformer allemand)
    - XX: xx_ent_wiki_sm (multi-langue fallback)

    Phase 1 V2.1 - Semaine 1
    """

    def __init__(self, config):
        """
        Initialise le gestionnaire NER.

        Args:
            config: Configuration SemanticConfig avec config.ner
        """
        self.config = config
        self._models = {}
        self._load_models()

    def _load_models(self):
        """
        Charge les modèles spaCy (lazy loading).

        Ne charge que les modèles configurés disponibles.
        Si un modèle n'est pas trouvé, log un warning et continue.
        """
        # Charger tous les modèles configurés
        for lang in ["en", "fr", "de", "xx"]:
            model_name = self.config.ner.models.get(lang)
            if model_name:
                try:
                    self._models[lang] = spacy.load(model_name)
                    logger.info(f"[OSMOSE] ✅ NER model loaded: {lang} ({model_name})")
                except OSError:
                    logger.warning(
                        f"[OSMOSE] ⚠️ NER model not found: {lang} ({model_name}). "
                        f"Run: python -m spacy download {model_name}"
                    )

        if not self._models:
            logger.error("[OSMOSE] ❌ No NER models loaded! Install at least one model.")
        else:
            logger.info(f"[OSMOSE] Loaded {len(self._models)} NER models: {list(self._models.keys())}")

    def _is_valid_entity(self, entity_text: str) -> bool:
        """
        Filtre entités NER de mauvaise qualité.

        Rejette:
        - Fragments courts (< 3 chars)
        - Fragments courants (ized, ial, ing, tion, ness, ment)
        - Articles/prépositions (the, and, or, of, in, on, at, to, a, an)
        - Entités commençant par minuscule (sauf acronymes)
        - Entités avec caractères étranges (guillemets non fermés, etc.)

        Returns:
            True si entité valide, False sinon
        """
        text = entity_text.strip()

        # Rejeter si trop court
        if len(text) < 3:
            return False

        # Rejeter fragments connus
        fragments = {"ized", "ial", "ing", "tion", "ness", "ment", "able", "ful", "less"}
        if text.lower() in fragments:
            return False

        # Rejeter stopwords
        stopwords = {"the", "and", "or", "of", "in", "on", "at", "to", "a", "an", "for", "with"}
        if text.lower() in stopwords:
            return False

        # Rejeter si commence par article
        if text.lower().startswith(("the ", "a ", "an ")):
            return False

        # Rejeter si commence par minuscule (sauf acronymes all-caps)
        if text[0].islower() and not text.isupper():
            return False

        # Rejeter si contient guillemets non fermés
        if text.count('"') % 2 != 0:
            return False

        return True

    def extract_entities(
        self,
        text: str,
        language: str
    ) -> List[Dict]:
        """
        Extrait entités nommées avec NER adapté à la langue.

        Args:
            text: Texte à analyser
            language: Code langue ISO 639-1 (en, fr, de, etc.)

        Returns:
            List[Dict]: Liste d'entités avec {text, label, start, end}
        """
        # Sélectionner modèle approprié
        # Si langue non supportée → fallback xx (multilingual)
        model = self._models.get(language, self._models.get("xx"))

        if not model:
            logger.warning(
                f"[OSMOSE] No NER model available for language '{language}', skipping NER"
            )
            return []

        # Extraction NER
        doc = model(text)

        # Filtrer types pertinents (ORG, PRODUCT, TECH, LAW, MISC)
        relevant_types = self.config.ner.entity_types

        entities = []
        filtered_count = 0
        for ent in doc.ents:
            if ent.label_ in relevant_types:
                # Filtrer entités de mauvaise qualité
                if not self._is_valid_entity(ent.text):
                    filtered_count += 1
                    continue

                entities.append({
                    "text": ent.text,
                    "label": ent.label_,
                    "start": ent.start_char,
                    "end": ent.end_char,
                    "confidence": 1.0  # spaCy ne fournit pas de score, assume 1.0
                })

        logger.debug(
            f"[OSMOSE] NER extracted {len(entities)} entities "
            f"from {len(text)} chars (language: {language}), filtered {filtered_count}"
        )

        return entities

    def extract_entities_batch(
        self,
        texts: List[str],
        language: str
    ) -> List[List[Dict]]:
        """
        Extraction batch pour performance.

        Args:
            texts: Liste de textes à analyser
            language: Code langue ISO 639-1

        Returns:
            List[List[Dict]]: Liste d'entités pour chaque texte
        """
        model = self._models.get(language, self._models.get("xx"))

        if not model:
            logger.warning(
                f"[OSMOSE] No NER model available for language '{language}', skipping batch NER"
            )
            return [[] for _ in texts]

        # Traitement batch avec spaCy pipe
        results = []
        relevant_types = self.config.ner.entity_types

        total_filtered = 0
        for doc in model.pipe(texts, batch_size=self.config.ner.batch_size):
            entities = []
            for ent in doc.ents:
                if ent.label_ in relevant_types:
                    # Filtrer entités de mauvaise qualité
                    if not self._is_valid_entity(ent.text):
                        total_filtered += 1
                        continue

                    entities.append({
                        "text": ent.text,
                        "label": ent.label_,
                        "start": ent.start_char,
                        "end": ent.end_char,
                        "confidence": 1.0
                    })
            results.append(entities)

        logger.debug(
            f"[OSMOSE] NER batch processed {len(texts)} texts "
            f"(total entities: {sum(len(r) for r in results)}, filtered: {total_filtered})"
        )

        return results

    def is_model_available(self, language: str) -> bool:
        """
        Vérifie si un modèle NER est disponible pour une langue.

        Args:
            language: Code langue ISO 639-1

        Returns:
            bool: True si modèle disponible
        """
        return language in self._models or "xx" in self._models

    def get_available_languages(self) -> List[str]:
        """
        Retourne la liste des langues supportées.

        Returns:
            List[str]: Codes ISO 639-1 des langues disponibles
        """
        return list(self._models.keys())


# ===================================
# FACTORY PATTERN
# ===================================

_ner_instance: Optional[MultilingualNER] = None


def get_ner_manager(config) -> MultilingualNER:
    """
    Récupère l'instance singleton du gestionnaire NER.

    Args:
        config: Configuration SemanticConfig

    Returns:
        MultilingualNER: Instance unique
    """
    global _ner_instance

    if _ner_instance is None:
        _ner_instance = MultilingualNER(config)

    return _ner_instance
