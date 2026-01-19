"""
🌊 OSMOSE Semantic Intelligence V2.1 - NER Multilingue

Gestionnaire Named Entity Recognition multilingue avec spaCy

Phase 1.8 - EntityRuler Integration:
- Dictionnaires métier préchargés (SAP, Salesforce, Pharma)
- Améliore precision NER de 70% → 85-90%
- Alternative pragmatique au fine-tuning
"""

import spacy
from spacy.pipeline import EntityRuler
from typing import List, Dict, Optional
from functools import lru_cache
from pathlib import Path
import json
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

    def __init__(self, config, tenant_id: str = "default"):
        """
        Initialise le gestionnaire NER.

        Args:
            config: Configuration SemanticConfig avec config.ner
            tenant_id: ID tenant pour dictionnaires custom (Phase 1.8)
        """
        self.config = config
        self.tenant_id = tenant_id
        self._models = {}
        self._entity_ruler_loaded = False
        self._load_models()

        # Phase 1.8: Charger dictionnaires métier si activé
        if getattr(self.config.ner, 'enable_entity_ruler', True):
            self._load_entity_ruler_patterns()

    def _load_models(self):
        """
        Initialise la config des modèles (lazy loading réel).

        OOM Fix: Ne charge plus tous les modèles à l'init.
        Les modèles sont chargés à la demande dans _get_model().
        """
        # Stocker la config des modèles, pas les modèles eux-mêmes
        self._model_configs = {}
        for lang in ["en", "fr", "de", "xx"]:
            model_name = self.config.ner.models.get(lang)
            if model_name:
                self._model_configs[lang] = model_name

        logger.info(f"[OSMOSE] NER configured for {len(self._model_configs)} languages: {list(self._model_configs.keys())} (lazy-load)")

    def _get_model(self, lang: str):
        """
        Charge un modèle à la demande (lazy loading).

        OOM Fix: Évite de charger 3 modèles spaCy (~650MB) au démarrage.
        Charge uniquement le modèle nécessaire quand requis.

        Args:
            lang: Code langue (en, fr, de, xx)

        Returns:
            Modèle spaCy ou None si non disponible
        """
        # Déjà chargé ?
        if lang in self._models:
            return self._models[lang]

        # Config existe ?
        model_name = self._model_configs.get(lang)
        if not model_name:
            return None

        # Charger le modèle
        try:
            self._models[lang] = spacy.load(model_name)
            logger.info(f"[OSMOSE] ✅ NER model loaded: {lang} ({model_name})")
            return self._models[lang]
        except OSError:
            logger.warning(
                f"[OSMOSE] ⚠️ NER model not found: {lang} ({model_name}). "
                f"Run: python -m spacy download {model_name}"
            )
            return None

    # =========================================================================
    # Phase 1.8 - EntityRuler Integration
    # =========================================================================

    def _load_entity_ruler_patterns(self):
        """
        Charge les dictionnaires métier comme patterns EntityRuler.

        Phase 1.8: Améliore precision NER via dictionnaires prépackagés.

        Charge:
        1. Dictionnaires globaux (config/ontologies/*.json)
        2. Dictionnaires custom tenant (config/ontologies/custom/{tenant_id}/*.json)
        """
        patterns = []

        # Chemin de base pour les ontologies
        base_path = Path("config/ontologies")

        # 1. Ontologies statiques DÉSACTIVÉES (2024-12-30)
        # Ces dictionnaires pré-définis (Salesforce, Pharma/FDA, SAP) sont incompatibles
        # avec l'architecture OSMOSE domain-agnostic. Le système découvre les concepts
        # dynamiquement via HybridAnchorExtractor (LLM-based).
        #
        # Les ontologies statiques causaient des faux positifs (ex: "GMP" classé FDA
        # au lieu de concept EU dans des documents de régulation européenne).
        #
        # global_ontologies = [
        #     "sap_products.json",
        #     "salesforce_concepts.json",
        #     "pharma_fda_terms.json"
        # ]
        global_ontologies = []  # OSMOSE: extraction dynamique uniquement

        for ontology_file in global_ontologies:
            ontology_path = base_path / ontology_file
            if ontology_path.exists():
                file_patterns = self._load_ontology_file(ontology_path)
                patterns.extend(file_patterns)

        # 2. Charger dictionnaires custom tenant
        tenant_path = base_path / "custom" / self.tenant_id
        if tenant_path.exists():
            for ontology_file in tenant_path.glob("*.json"):
                file_patterns = self._load_ontology_file(ontology_file)
                patterns.extend(file_patterns)

        if not patterns:
            logger.debug("[NER:EntityRuler] No domain dictionaries found")
            return

        # 3. Ajouter EntityRuler à chaque modèle chargé
        for lang, model in self._models.items():
            try:
                # Vérifier si EntityRuler existe déjà
                if "entity_ruler" not in model.pipe_names:
                    # Créer EntityRuler AVANT le NER natif pour priorité
                    ruler = model.add_pipe("entity_ruler", before="ner")
                    ruler.add_patterns(patterns)
                    logger.info(
                        f"[NER:EntityRuler] Added {len(patterns)} patterns to {lang} model"
                    )
            except Exception as e:
                logger.warning(
                    f"[NER:EntityRuler] Failed to add EntityRuler to {lang} model: {e}"
                )

        self._entity_ruler_loaded = True
        logger.info(
            f"[NER:EntityRuler] ✅ Loaded {len(patterns)} domain patterns "
            f"(tenant={self.tenant_id})"
        )

    def _load_ontology_file(self, file_path: Path) -> List[Dict]:
        """
        Charge un fichier ontologie JSON et convertit en patterns EntityRuler.

        Args:
            file_path: Chemin vers le fichier JSON

        Returns:
            Liste de patterns EntityRuler
        """
        patterns = []

        try:
            with open(file_path, "r", encoding="utf-8") as f:
                entities = json.load(f)

            for entity in entities:
                name = entity.get("name", "")
                entity_type = entity.get("type", "CONCEPT")
                entity_id = entity.get("entity_id", name)
                aliases = entity.get("aliases", [])

                if not name:
                    continue

                # Pattern pour le nom principal
                patterns.append({
                    "label": entity_type,
                    "pattern": name,
                    "id": entity_id
                })

                # Patterns pour les aliases
                for alias in aliases:
                    if alias:
                        patterns.append({
                            "label": entity_type,
                            "pattern": alias,
                            "id": entity_id
                        })

            logger.debug(
                f"[NER:EntityRuler] Loaded {len(patterns)} patterns from {file_path.name}"
            )

        except json.JSONDecodeError as e:
            logger.error(f"[NER:EntityRuler] JSON error in {file_path}: {e}")
        except Exception as e:
            logger.error(f"[NER:EntityRuler] Error loading {file_path}: {e}")

        return patterns

    def reload_entity_ruler(self, tenant_id: Optional[str] = None):
        """
        Recharge les patterns EntityRuler (utile après modification dictionnaires).

        Args:
            tenant_id: Nouveau tenant_id (optionnel)
        """
        if tenant_id:
            self.tenant_id = tenant_id

        # Réinitialiser les modèles pour enlever l'ancien EntityRuler
        self._load_models()
        self._load_entity_ruler_patterns()

        logger.info(f"[NER:EntityRuler] Reloaded patterns for tenant={self.tenant_id}")

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
        # Sélectionner modèle approprié (lazy-load)
        # Si langue non supportée → fallback xx (multilingual)
        model = self._get_model(language) or self._get_model("xx")

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
        model = self._get_model(language) or self._get_model("xx")

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
        Vérifie si un modèle NER est configuré pour une langue.

        Args:
            language: Code langue ISO 639-1

        Returns:
            bool: True si modèle configuré (sera chargé à la demande)
        """
        return language in self._model_configs or "xx" in self._model_configs

    def get_available_languages(self) -> List[str]:
        """
        Retourne la liste des langues configurées.

        Returns:
            List[str]: Codes ISO 639-1 des langues disponibles
        """
        return list(self._model_configs.keys())


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
