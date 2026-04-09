"""
Stopwords multilingues via spaCy — remplace les listes figees FR+EN.

Charge dynamiquement les stopwords des langues detectees dans le corpus
(ou specifiees explicitement). 74 langues disponibles via spaCy built-in.

Usage :
    from knowbase.common.stopwords import get_stopwords, is_stopword

    # Charger EN + FR (defaut)
    sw = get_stopwords()
    assert "the" in sw
    assert "ce" in sw

    # Charger EN + FR + IT + DE
    sw = get_stopwords(["en", "fr", "it", "de"])
    assert "delle" in sw
"""

from __future__ import annotations

import logging
from typing import Optional

logger = logging.getLogger(__name__)

# Cache : union des stopwords des langues chargees
_cache: Optional[frozenset[str]] = None
_cached_langs: Optional[tuple[str, ...]] = None

# Langues par defaut (comportement identique a l'ancien systeme)
DEFAULT_LANGS = ("en", "fr")


def _load_stopwords_for_lang(lang_code: str) -> set[str]:
    """Charge les stopwords d'une langue via spaCy.lang.XX.stop_words."""
    try:
        from importlib import import_module
        mod = import_module(f"spacy.lang.{lang_code}.stop_words")
        words = getattr(mod, "STOP_WORDS", set())
        return set(words)
    except (ImportError, ModuleNotFoundError):
        logger.debug(f"[STOPWORDS] No spaCy stopwords for lang '{lang_code}'")
        return set()


class SpacyUnavailableError(RuntimeError):
    """Raised when spaCy is not installed and stopwords cannot be loaded."""
    pass


def get_stopwords(lang_codes: list[str] | tuple[str, ...] | None = None) -> frozenset[str]:
    """Retourne l'union des stopwords pour les langues demandees.

    Resultat cache : si on redemande les memes langues, retourne le cache.

    Args:
        lang_codes: Liste de codes ISO 639-1 (ex: ["en", "fr", "it"]).
                    Si None, utilise DEFAULT_LANGS ("en", "fr").

    Raises:
        SpacyUnavailableError: si spaCy n'est pas installe (permet au
            caller de tomber dans son fallback)
    """
    global _cache, _cached_langs

    langs = tuple(sorted(lang_codes or DEFAULT_LANGS))

    if _cache is not None and _cached_langs == langs:
        return _cache

    combined: set[str] = set()
    any_loaded = False
    for lang in langs:
        words = _load_stopwords_for_lang(lang)
        if words:
            combined.update(words)
            any_loaded = True
            logger.debug(f"[STOPWORDS] Loaded {len(words)} stopwords for '{lang}'")

    if not any_loaded:
        raise SpacyUnavailableError(
            f"No stopwords loaded for {langs} — spaCy may not be installed"
        )

    _cache = frozenset(combined)
    _cached_langs = langs

    logger.info(f"[STOPWORDS] {len(_cache)} stopwords loaded for {langs}")
    return _cache


def _detect_corpus_languages() -> list[str]:
    """Detecte les langues presentes dans le corpus.

    Strategie en 2 etapes :
    1. Query Neo4j DocumentContext.language (si le champ existe)
    2. Sinon, echantillonne des chunks Qdrant et detecte via fasttext

    Retourne la liste des codes ISO 639-1 detectes, ou DEFAULT_LANGS en fallback.
    """
    # Tentative 1 : Neo4j (si le champ language est persiste)
    try:
        from knowbase.common.clients.neo4j_client import get_neo4j_client
        driver = get_neo4j_client().driver
        with driver.session() as session:
            result = session.run(
                "MATCH (dc:DocumentContext) "
                "WHERE dc.language IS NOT NULL "
                "RETURN collect(DISTINCT dc.language) AS langs"
            )
            record = result.single()
            if record and record["langs"]:
                langs = [l for l in record["langs"] if isinstance(l, str) and len(l) == 2]
                if langs:
                    logger.info(f"[STOPWORDS] Corpus languages from Neo4j: {langs}")
                    return langs
    except Exception as e:
        logger.debug(f"[STOPWORDS] Neo4j language detection failed: {e}")

    # Tentative 2 : echantillonner des chunks Qdrant + fasttext
    try:
        from knowbase.retrieval.qdrant_layer_r import get_qdrant_client
        from knowbase.config.settings import get_settings

        settings = get_settings()
        client = get_qdrant_client()
        collection = settings.qdrant_collection

        results, _ = client.scroll(
            collection_name=collection,
            limit=50,  # petit echantillon
            with_payload=True,
            with_vectors=False,
        )

        if not results:
            return list(DEFAULT_LANGS)

        # Detection de langue sur les textes des chunks
        from collections import Counter
        lang_counts: Counter = Counter()

        try:
            from knowbase.semantic.utils.language_detector import get_language_detector
            detector = get_language_detector(settings.semantic)
            for point in results:
                text = point.payload.get("text", "")
                if text and len(text) > 30:
                    lang = detector.detect(text)
                    if lang and len(lang) == 2:
                        lang_counts[lang] += 1
        except Exception:
            # fasttext indisponible — fallback simple par heuristique
            for point in results:
                text = (point.payload.get("text", "") or "").lower()
                if any(w in text for w in ["le ", "la ", "les ", "des ", "une "]):
                    lang_counts["fr"] += 1
                if any(w in text for w in ["the ", "and ", "for ", "with "]):
                    lang_counts["en"] += 1

        if lang_counts:
            # Garder les langues qui representent > 5% des chunks
            total = sum(lang_counts.values())
            langs = [lang for lang, count in lang_counts.items()
                     if count / total > 0.05]
            if langs:
                logger.info(f"[STOPWORDS] Corpus languages from Qdrant sampling: {langs} (from {lang_counts})")
                return langs

    except Exception as e:
        logger.debug(f"[STOPWORDS] Qdrant language detection failed: {e}")

    return list(DEFAULT_LANGS)


def get_corpus_stopwords() -> frozenset[str]:
    """Charge les stopwords pour les langues effectivement presentes dans le corpus.

    Detecte automatiquement les langues des documents ingeres (via Neo4j)
    et charge les stopwords correspondantes. Si le corpus contient des docs
    EN + FR + IT + DE, les stopwords des 4 langues sont charges.

    Resultat cache : un seul appel Neo4j, puis cache en memoire.
    """
    langs = _detect_corpus_languages()
    return get_stopwords(langs)


def is_stopword(word: str, lang_codes: list[str] | None = None) -> bool:
    """True si le mot est un stopword dans les langues demandees."""
    return word.lower() in get_stopwords(lang_codes)


def invalidate_cache() -> None:
    """Force le rechargement au prochain appel."""
    global _cache, _cached_langs
    _cache = None
    _cached_langs = None
