"""
OSMOSE Linguistic Layer - Engines de coréférence

Ce module définit l'interface ICorefEngine et ses implémentations.

Architecture:
- ICorefEngine: Interface commune (Protocol)
- SpacyCorefEngine: Implémentation spaCy (EN, recommandé)
- RuleBasedEngine: Fallback universel (toutes langues)
- CorefereeEngine: Implémentation Coreferee (FR/EN/DE, expérimental)

Stratégie multilingue (engine-per-language):
- EN: spaCy CoreferenceResolver / F-Coref
- FR: Coreferee (expérimental) ou RuleBasedEngine
- DE: Coreferee ou RuleBasedEngine
- IT: RuleBasedEngine only

NOTE: Coreferee doit rester swappable sans douleur (dernier release 2022).

Ref: doc/ongoing/IMPLEMENTATION_PLAN_ADR_COMPLETION.md - Section 10.5
"""

import logging
import re
import threading
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import List, Dict, Optional, Protocol, Tuple, Any
import time

from knowbase.linguistic.coref_models import (
    CoreferenceCluster,
    MentionType,
)

logger = logging.getLogger(__name__)


# Flag pour la disponibilité des engines optionnels
SPACY_COREF_AVAILABLE = False
COREFEREE_AVAILABLE = False
FASTCOREF_AVAILABLE = False

# Singleton pour FastCorefEngine (évite double chargement en mode parallèle)
# OOM Fix: FastCoref charge ~800MB (spaCy + modèle), ne charger qu'une fois
_FASTCOREF_ENGINE_INSTANCE: Optional["FastCorefEngine"] = None
_FASTCOREF_ENGINE_LOCK = None  # Initialisé à l'import threading

try:
    import spacy
    SPACY_COREF_AVAILABLE = True
except ImportError:
    pass

try:
    import coreferee
    COREFEREE_AVAILABLE = True
except ImportError:
    pass

try:
    from fastcoref import spacy_component
    FASTCOREF_AVAILABLE = True
except ImportError:
    pass


class ICorefEngine(Protocol):
    """
    Interface commune pour tous les engines de coréférence.

    Permet le swap d'engine sans impact sur le reste du système.
    """

    def resolve(
        self,
        document_text: str,
        chunks: List[Dict[str, Any]],
        lang: str = "en"
    ) -> List[CoreferenceCluster]:
        """
        Résout les coréférences dans un document.

        Args:
            document_text: Texte complet du document
            chunks: Liste des chunks avec leurs offsets
            lang: Langue du document

        Returns:
            Liste de clusters (chaînes de mentions coréférentes)
        """
        ...

    @property
    def engine_name(self) -> str:
        """Nom de l'engine pour logging/audit."""
        ...

    def is_available(self) -> bool:
        """Vérifie si l'engine est disponible."""
        ...


class RuleBasedEngine:
    """
    Engine de coréférence basé sur des règles heuristiques.

    Fallback universel pour toutes les langues.
    Approche conservative: ne résout que les cas évidents.

    Règles implémentées:
    1. Pronom → nom propre le plus proche (même phrase ou phrase précédente)
    2. Accord genre/nombre (FR) quand détectable
    3. Priorité aux entités capitalisées
    """

    # Pronoms par langue
    PRONOUNS: Dict[str, List[str]] = {
        "en": ["it", "they", "them", "he", "she", "him", "her", "this", "that"],
        "fr": ["il", "elle", "ils", "elles", "celui-ci", "celle-ci"],
        "de": ["er", "sie", "es", "dieser", "diese", "dieses"],
        "it": ["esso", "essa", "essi", "esse", "questo", "questa"],
    }

    # Pattern pour détecter les entités (noms propres, acronymes)
    ENTITY_PATTERN = re.compile(r'\b[A-Z][a-zA-Z]*(?:\s+[A-Z][a-zA-Z]*)*\b')

    # Pattern pour détecter les acronymes
    ACRONYM_PATTERN = re.compile(r'\b[A-Z]{2,}\b')

    def __init__(self):
        self._name = "rule_based"

    @property
    def engine_name(self) -> str:
        return self._name

    def is_available(self) -> bool:
        return True  # Toujours disponible

    def resolve(
        self,
        document_text: str,
        chunks: List[Dict[str, Any]],
        lang: str = "en"
    ) -> List[CoreferenceCluster]:
        """
        Résout les coréférences avec des règles heuristiques.

        Approche conservative: ne crée des clusters que pour les cas évidents.
        """
        start_time = time.time()
        clusters: List[CoreferenceCluster] = []

        # Obtenir les pronoms pour la langue
        pronouns = set(self.PRONOUNS.get(lang, self.PRONOUNS["en"]))

        # Segmenter en phrases
        sentences = self._segment_sentences(document_text)

        # Pour chaque phrase, chercher les pronoms et leurs antécédents potentiels
        for sent_idx, sentence in enumerate(sentences):
            sent_start = sentence["start"]
            sent_text = sentence["text"]

            # Trouver les pronoms dans la phrase
            for word_match in re.finditer(r'\b\w+\b', sent_text):
                word = word_match.group().lower()
                if word not in pronouns:
                    continue

                pronoun_start = sent_start + word_match.start()
                pronoun_end = sent_start + word_match.end()

                # Chercher l'antécédent le plus proche
                antecedent = self._find_nearest_antecedent(
                    sentences,
                    sent_idx,
                    pronoun_start,
                    lang
                )

                if antecedent:
                    # Créer un cluster avec le pronom et l'antécédent
                    cluster = CoreferenceCluster(
                        mentions=[
                            {
                                "start": antecedent["start"],
                                "end": antecedent["end"],
                                "text": antecedent["text"],
                                "sentence_idx": antecedent["sentence_idx"],
                            },
                            {
                                "start": pronoun_start,
                                "end": pronoun_end,
                                "text": word_match.group(),
                                "sentence_idx": sent_idx,
                            },
                        ],
                        representative_idx=0,  # L'antécédent est le représentant
                        confidence=0.7,  # Confiance modérée pour les règles
                        method=self._name,
                    )
                    clusters.append(cluster)

        elapsed = (time.time() - start_time) * 1000
        logger.debug(
            f"[OSMOSE:RuleBasedEngine] Found {len(clusters)} clusters "
            f"in {len(sentences)} sentences ({elapsed:.0f}ms)"
        )

        return clusters

    def _segment_sentences(self, text: str) -> List[Dict]:
        """Segmente le texte en phrases."""
        sentences = []
        # Pattern simple pour la segmentation
        pattern = re.compile(r'[.!?]+\s+|$')

        start = 0
        for match in pattern.finditer(text):
            end = match.end()
            if start < end:
                sent_text = text[start:match.start()].strip()
                if sent_text:
                    sentences.append({
                        "start": start,
                        "end": match.start(),
                        "text": sent_text,
                    })
            start = end

        # Dernière phrase si pas de ponctuation finale
        if start < len(text):
            sent_text = text[start:].strip()
            if sent_text:
                sentences.append({
                    "start": start,
                    "end": len(text),
                    "text": sent_text,
                })

        return sentences

    def _find_nearest_antecedent(
        self,
        sentences: List[Dict],
        current_sent_idx: int,
        pronoun_offset: int,
        lang: str
    ) -> Optional[Dict]:
        """
        Trouve l'antécédent le plus proche d'un pronom.

        Cherche dans la phrase courante puis la phrase précédente.
        Priorité aux entités capitalisées et acronymes.
        """
        # Fenêtre de recherche: phrase courante + phrase précédente
        search_range = range(max(0, current_sent_idx - 1), current_sent_idx + 1)

        candidates = []

        for sent_idx in search_range:
            sentence = sentences[sent_idx]
            sent_start = sentence["start"]
            sent_text = sentence["text"]

            # Chercher les entités (noms propres)
            for match in self.ENTITY_PATTERN.finditer(sent_text):
                entity_start = sent_start + match.start()
                entity_end = sent_start + match.end()

                # Ne pas inclure si c'est après le pronom dans la même phrase
                if sent_idx == current_sent_idx and entity_start >= pronoun_offset:
                    continue

                candidates.append({
                    "start": entity_start,
                    "end": entity_end,
                    "text": match.group(),
                    "sentence_idx": sent_idx,
                    "is_acronym": bool(self.ACRONYM_PATTERN.match(match.group())),
                    "distance": pronoun_offset - entity_start,
                })

        if not candidates:
            return None

        # Trier par distance (le plus proche en premier)
        # Priorité aux acronymes et entités de la même phrase
        candidates.sort(key=lambda c: (
            c["sentence_idx"] != current_sent_idx,  # Même phrase en premier
            not c["is_acronym"],  # Acronymes en priorité
            c["distance"],  # Plus proche
        ))

        return candidates[0] if candidates else None


class FastCorefEngine:
    """
    Engine de coréférence basé sur FastCoref.

    Utilise le modèle F-COREF (Fast Coreference Resolution).
    Haute précision (~85%+) et compatible avec spaCy 3.7+.

    Ref: https://github.com/shon-otmazgin/fastcoref
    """

    def __init__(self, model_name: str = "en_core_web_md"):
        """
        Initialise l'engine FastCoref.

        Args:
            model_name: Modèle spaCy de base (md installé dans Docker)
        """
        self._name = "fastcoref"
        self._model_name = model_name
        self._nlp = None
        self._load_attempted = False

    @property
    def engine_name(self) -> str:
        return self._name

    def is_available(self) -> bool:
        if not FASTCOREF_AVAILABLE or not SPACY_COREF_AVAILABLE:
            return False

        if not self._load_attempted:
            self._load_model()

        return self._nlp is not None

    def _load_model(self):
        """Charge le pipeline spaCy + FastCoref."""
        self._load_attempted = True
        try:
            import spacy
            from fastcoref import spacy_component

            # Charger un modèle spaCy léger (FastCoref n'utilise que le POS tagger)
            self._nlp = spacy.load(
                self._model_name,
                exclude=["parser", "lemmatizer", "ner", "textcat"]
            )
            # Ajouter le composant FastCoref
            self._nlp.add_pipe("fastcoref")
            logger.info(f"[OSMOSE:FastCorefEngine] Loaded with {self._model_name}")
        except Exception as e:
            logger.warning(f"[OSMOSE:FastCorefEngine] Failed to load: {e}")
            self._nlp = None

    def resolve(
        self,
        document_text: str,
        chunks: List[Dict[str, Any]],
        lang: str = "en"
    ) -> List[CoreferenceCluster]:
        """
        Résout les coréférences avec FastCoref.
        """
        if not self.is_available():
            logger.warning("[OSMOSE:FastCorefEngine] Not available, returning empty")
            return []

        start_time = time.time()
        clusters: List[CoreferenceCluster] = []

        try:
            doc = self._nlp(document_text)

            # FastCoref stocke les clusters dans doc._.coref_clusters
            # Format: [[(start1, end1), (start2, end2), ...], ...]
            if hasattr(doc._, 'coref_clusters') and doc._.coref_clusters:
                for cluster_spans in doc._.coref_clusters:
                    mentions = []
                    for span_start, span_end in cluster_spans:
                        span_text = document_text[span_start:span_end]
                        mentions.append({
                            "start": span_start,
                            "end": span_end,
                            "text": span_text,
                            "sentence_idx": 0,  # TODO: calculer
                        })

                    if len(mentions) >= 2:
                        # Le premier mention est généralement le représentant
                        cluster = CoreferenceCluster(
                            mentions=mentions,
                            representative_idx=0,
                            confidence=0.85,
                            method=self._name,
                        )
                        clusters.append(cluster)

        except Exception as e:
            logger.error(f"[OSMOSE:FastCorefEngine] Error: {e}")

        elapsed = (time.time() - start_time) * 1000
        logger.debug(
            f"[OSMOSE:FastCorefEngine] Found {len(clusters)} clusters ({elapsed:.0f}ms)"
        )

        return clusters


def get_fastcoref_engine() -> Optional[FastCorefEngine]:
    """
    Retourne l'instance singleton de FastCorefEngine.

    OOM Fix: FastCoref charge ~800MB (spaCy en_core_web_md + modèle F-COREF).
    En mode burst avec 2+ documents parallèles, chaque document chargeait
    sa propre instance, causant des OOM (exit 137).

    Ce singleton garantit qu'un seul modèle est chargé en mémoire.

    Returns:
        FastCorefEngine instance ou None si non disponible
    """
    global _FASTCOREF_ENGINE_INSTANCE, _FASTCOREF_ENGINE_LOCK

    if not FASTCOREF_AVAILABLE:
        return None

    # Lazy init du lock (évite problème au module load)
    if _FASTCOREF_ENGINE_LOCK is None:
        _FASTCOREF_ENGINE_LOCK = threading.Lock()

    # Double-checked locking pattern
    if _FASTCOREF_ENGINE_INSTANCE is None:
        with _FASTCOREF_ENGINE_LOCK:
            if _FASTCOREF_ENGINE_INSTANCE is None:
                logger.info("[OSMOSE:FastCorefEngine] Creating singleton instance")
                _FASTCOREF_ENGINE_INSTANCE = FastCorefEngine()
                # Force le chargement immédiat pour éviter les race conditions
                _FASTCOREF_ENGINE_INSTANCE.is_available()

    return _FASTCOREF_ENGINE_INSTANCE


class SpacyCorefEngine:
    """
    Engine de coréférence basé sur spaCy Transformer.

    Utilise le modèle en_coreference_web_trf avec coréférence native.
    Haute précision (~85-90%) pour documents techniques.

    Note: Nécessite le modèle en_coreference_web_trf (installé via Dockerfile).
    DEPRECATED: Incompatible avec spaCy >= 3.5. Utiliser FastCorefEngine.
    """

    def __init__(self, model_name: str = "en_coreference_web_trf"):
        """
        Initialise l'engine spaCy.

        Args:
            model_name: Nom du modèle spaCy à charger
        """
        self._name = "spacy_coref"
        self._model_name = model_name
        self._nlp = None
        self._load_attempted = False

    @property
    def engine_name(self) -> str:
        return self._name

    def is_available(self) -> bool:
        if not SPACY_COREF_AVAILABLE:
            return False

        # Tenter de charger le modèle si pas encore fait
        if not self._load_attempted:
            self._load_model()

        return self._nlp is not None

    def _load_model(self):
        """Charge le modèle spaCy."""
        self._load_attempted = True
        try:
            import spacy
            self._nlp = spacy.load(self._model_name)
            logger.info(f"[OSMOSE:SpacyCorefEngine] Loaded model {self._model_name}")
        except OSError as e:
            logger.warning(
                f"[OSMOSE:SpacyCorefEngine] Model {self._model_name} not found: {e}. "
                f"Falling back to rule-based."
            )
            self._nlp = None

    def resolve(
        self,
        document_text: str,
        chunks: List[Dict[str, Any]],
        lang: str = "en"
    ) -> List[CoreferenceCluster]:
        """
        Résout les coréférences avec spaCy.

        Note: Si le modèle n'a pas de composant coref, utilise les entités
        comme fallback pour créer des clusters basiques.
        """
        if not self.is_available():
            logger.warning("[OSMOSE:SpacyCorefEngine] Not available, returning empty")
            return []

        start_time = time.time()
        clusters: List[CoreferenceCluster] = []

        try:
            doc = self._nlp(document_text)

            # Vérifier si le doc a des span groups de coréférence
            if hasattr(doc, 'spans') and 'coref_clusters' in doc.spans:
                # Modèle avec coréférence native
                for cluster_spans in doc.spans['coref_clusters']:
                    mentions = []
                    for span in cluster_spans:
                        mentions.append({
                            "start": span.start_char,
                            "end": span.end_char,
                            "text": span.text,
                            "sentence_idx": span.sent.start if span.sent else 0,
                        })

                    if len(mentions) >= 2:
                        cluster = CoreferenceCluster(
                            mentions=mentions,
                            representative_idx=0,
                            confidence=0.85,
                            method=self._name,
                        )
                        clusters.append(cluster)
            else:
                # Fallback: utiliser les entités nommées
                # Grouper les entités avec le même texte
                entity_groups: Dict[str, List[Dict]] = {}
                for ent in doc.ents:
                    key = ent.text.lower()
                    if key not in entity_groups:
                        entity_groups[key] = []
                    entity_groups[key].append({
                        "start": ent.start_char,
                        "end": ent.end_char,
                        "text": ent.text,
                        "sentence_idx": ent.sent.start if ent.sent else 0,
                    })

                for key, mentions in entity_groups.items():
                    if len(mentions) >= 2:
                        cluster = CoreferenceCluster(
                            mentions=mentions,
                            representative_idx=0,
                            confidence=0.7,
                            method=f"{self._name}_ner_fallback",
                        )
                        clusters.append(cluster)

        except Exception as e:
            logger.error(f"[OSMOSE:SpacyCorefEngine] Error: {e}")

        elapsed = (time.time() - start_time) * 1000
        logger.debug(
            f"[OSMOSE:SpacyCorefEngine] Found {len(clusters)} clusters ({elapsed:.0f}ms)"
        )

        return clusters


class CorefereeEngine:
    """
    Engine de coréférence basé sur Coreferee.

    Supporte FR, EN, DE. Classé expérimental (dernier release 2022).

    ⚠️ CONTRAINTE SWAPPABILITÉ: Doit rester swappable sans douleur.
    Aucune dépendance fonctionnelle critique sur Coreferee.
    """

    # Modèles par langue (md = medium, disponibles dans le container)
    MODELS: Dict[str, str] = {
        "en": "en_core_web_md",
        "fr": "fr_core_news_md",
        "de": "de_core_news_md",
    }

    def __init__(self, lang: str = "en"):
        """
        Initialise l'engine Coreferee.

        Args:
            lang: Langue (en, fr, de)
        """
        self._name = "coreferee"
        self._lang = lang
        self._nlp = None
        self._load_attempted = False

    @property
    def engine_name(self) -> str:
        return self._name

    def is_available(self) -> bool:
        if not COREFEREE_AVAILABLE:
            return False

        if not self._load_attempted:
            self._load_model()

        return self._nlp is not None

    def _load_model(self):
        """Charge le modèle spaCy + Coreferee."""
        self._load_attempted = True

        model_name = self.MODELS.get(self._lang)
        if not model_name:
            logger.warning(f"[OSMOSE:CorefereeEngine] No model for lang={self._lang}")
            return

        try:
            import spacy
            import coreferee

            self._nlp = spacy.load(model_name)
            self._nlp.add_pipe("coreferee")
            logger.info(
                f"[OSMOSE:CorefereeEngine] Loaded {model_name} with coreferee "
                f"for lang={self._lang}"
            )
        except Exception as e:
            logger.warning(f"[OSMOSE:CorefereeEngine] Failed to load: {e}")
            self._nlp = None

    def resolve(
        self,
        document_text: str,
        chunks: List[Dict[str, Any]],
        lang: str = "en"
    ) -> List[CoreferenceCluster]:
        """
        Résout les coréférences avec Coreferee.
        """
        if not self.is_available():
            logger.warning("[OSMOSE:CorefereeEngine] Not available, returning empty")
            return []

        start_time = time.time()
        clusters: List[CoreferenceCluster] = []

        try:
            doc = self._nlp(document_text)

            if hasattr(doc._, 'coref_chains') and doc._.coref_chains:
                for chain in doc._.coref_chains:
                    mentions = []
                    for mention in chain:
                        # Coreferee retourne des indices de tokens
                        token_indices = mention.token_indexes
                        if not token_indices:
                            continue

                        start_token = doc[token_indices[0]]
                        end_token = doc[token_indices[-1]]

                        mentions.append({
                            "start": start_token.idx,
                            "end": end_token.idx + len(end_token.text),
                            "text": doc[token_indices[0]:token_indices[-1]+1].text,
                            "sentence_idx": start_token.sent.start if start_token.sent else 0,
                        })

                    if len(mentions) >= 2:
                        # Trouver le représentant (mention la plus longue)
                        rep_idx = max(range(len(mentions)), key=lambda i: len(mentions[i]["text"]))

                        cluster = CoreferenceCluster(
                            mentions=mentions,
                            representative_idx=rep_idx,
                            confidence=0.8,
                            method=self._name,
                        )
                        clusters.append(cluster)

        except Exception as e:
            logger.error(f"[OSMOSE:CorefereeEngine] Error: {e}")

        elapsed = (time.time() - start_time) * 1000
        logger.debug(
            f"[OSMOSE:CorefereeEngine] Found {len(clusters)} clusters ({elapsed:.0f}ms)"
        )

        return clusters


# Registry des engines par langue
_ENGINE_REGISTRY: Dict[str, type] = {}


def register_engine(lang: str, engine_class: type):
    """Enregistre un engine pour une langue."""
    _ENGINE_REGISTRY[lang] = engine_class


def get_engine_for_language(lang: str) -> ICorefEngine:
    """
    Retourne l'engine approprié pour la langue.

    Stratégie (mise à jour pour FastCoref):
    - EN: FastCorefEngine (~85%+) → CorefereeEngine → RuleBasedEngine
    - FR: CorefereeEngine (si disponible) → RuleBasedEngine
    - DE: CorefereeEngine (si disponible) → RuleBasedEngine
    - Autres: RuleBasedEngine

    Args:
        lang: Code langue (en, fr, de, it, etc.)

    Returns:
        Instance de ICorefEngine
    """
    lang = lang.lower()

    # Anglais: priorité à FastCoref (haute qualité, compatible spaCy 3.7+)
    if lang == "en":
        # 1. FastCoref SINGLETON (évite OOM en mode parallèle)
        # OOM Fix: get_fastcoref_engine() garantit une seule instance en mémoire
        if FASTCOREF_AVAILABLE:
            fastcoref_engine = get_fastcoref_engine()
            if fastcoref_engine and fastcoref_engine.is_available():
                logger.info("[OSMOSE:CorefEngine] Using FastCoref singleton for EN")
                return fastcoref_engine

        # 2. Fallback Coreferee
        if COREFEREE_AVAILABLE:
            coreferee_engine = CorefereeEngine(lang="en")
            if coreferee_engine.is_available():
                logger.info("[OSMOSE:CorefEngine] Using Coreferee for EN (fallback)")
                return coreferee_engine

        # 3. Rule-based
        logger.info("[OSMOSE:CorefEngine] Using rule-based for EN (fallback)")
        return RuleBasedEngine()

    # Français/Allemand: Coreferee ou rule-based
    if lang in ("fr", "de"):
        if COREFEREE_AVAILABLE:
            engine = CorefereeEngine(lang=lang)
            if engine.is_available():
                logger.info(f"[OSMOSE:CorefEngine] Using Coreferee for {lang}")
                return engine

        logger.info(f"[OSMOSE:CorefEngine] Using rule-based for {lang}")
        return RuleBasedEngine()

    # Autres langues: rule-based uniquement
    logger.info(f"[OSMOSE:CorefEngine] No specialized engine for {lang}, using rule-based")
    return RuleBasedEngine()


def get_available_engines() -> Dict[str, bool]:
    """
    Retourne la disponibilité des engines.

    Returns:
        Dict avec engine_name → is_available
    """
    return {
        "fastcoref": FASTCOREF_AVAILABLE,
        "spacy_coref": SPACY_COREF_AVAILABLE,
        "coreferee": COREFEREE_AVAILABLE,
        "rule_based": True,
    }
