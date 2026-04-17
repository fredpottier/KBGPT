"""
Module commun de détection de langue.

Wrappe le détecteur fasttext (lid.176) de `knowbase.semantic.utils` et ajoute
des méthodes pragmatiques adaptées aux cas d'usage du KG :

- Entités courtes (1-3 mots) : trop peu de signal pour fasttext → utiliser le
  contexte des claims/passages où l'entité apparaît
- Textes longs (docs, passages) : fasttext direct, très fiable
- Multi-langue (textes qui contiennent plusieurs langues) : top-k

Supporte 176 langues via le modèle fasttext lid.176.bin.
Retourne les codes ISO 639-1 (en, fr, de, es, zh, ar, etc.).

Design :
- Singleton partagé (un seul chargement du modèle)
- Retourne None quand la confiance est trop basse (pas de fallback hardcodé)
- Cache LRU hérité du détecteur sous-jacent
"""

from __future__ import annotations

import logging
from typing import List, Optional, Tuple

logger = logging.getLogger("[OSMOSE] language_detector")


# ── Singleton ──────────────────────────────────────────────────────────


class _DetectorSingleton:
    """Singleton paresseux pour le détecteur fasttext sous-jacent."""

    _instance = None
    _failed_init = False

    @classmethod
    def get(cls):
        if cls._failed_init:
            return None
        if cls._instance is None:
            try:
                # Charge la SemanticConfig directement (le Settings principal
                # n'expose pas `.semantic` — design historique du module
                # semantic marque deprecated mais ses utilities sont stables).
                from knowbase.semantic.config import load_semantic_config
                from knowbase.semantic.utils.language_detector import (
                    get_language_detector,
                )

                semantic_config = load_semantic_config()
                cls._instance = get_language_detector(semantic_config)
                if cls._instance.model is None:
                    logger.warning(
                        "[LANG] fasttext model not loaded — detection disabled. "
                        "Download lid.176.bin per config.language_detection.model_path"
                    )
                    cls._failed_init = True
                    return None
            except Exception as e:
                logger.warning(f"[LANG] Detector init failed: {e}")
                cls._failed_init = True
                return None
        return cls._instance


# ── API publique ───────────────────────────────────────────────────────


def detect_language(
    text: str, min_confidence: float = 0.75
) -> Optional[str]:
    """
    Détecte la langue d'un texte.

    Fonctionne de manière fiable sur des textes > 20 caractères. Pour les
    textes plus courts (noms d'entités), la fiabilité baisse ; dans ce cas
    préférer `detect_language_with_context()` qui agrège du contexte.

    Args:
        text: Texte à analyser.
        min_confidence: Seuil minimum de confiance fasttext.

    Returns:
        Code ISO 639-1 (ex: "en", "fr") ou None si confiance < seuil.
        None est intentionnel : pas de fallback silencieux biaisant les
        traitements aval.
    """
    if not text or len(text.strip()) < 2:
        return None
    detector = _DetectorSingleton.get()
    if detector is None:
        return None
    try:
        lang_code, confidence = detector.detect_with_confidence(text)
        if confidence < min_confidence:
            return None
        return lang_code
    except Exception as e:
        logger.debug(f"[LANG] detect_language error: {e}")
        return None


def detect_language_with_context(
    short_name: str,
    context_texts: List[str],
    min_confidence: float = 0.75,
    min_context_length: int = 20,
) -> Optional[str]:
    """
    Détecte la langue en combinant un nom court avec ses contextes longs.

    Cas typique : une Entity dont le `name` fait 1-3 tokens. La détection
    directe est peu fiable. Cette fonction agrège les claims/passages où
    l'entité apparaît pour obtenir un texte long et fiable à analyser.

    Args:
        short_name: Le nom court (ex: nom d'entité).
        context_texts: Textes longs où l'entité apparaît (claim.text,
            passage.text, etc.). Seront concaténés et limités à 2000 chars.
        min_confidence: Seuil minimum sur le contexte long.
        min_context_length: Longueur minimale du contexte agrégé pour
            privilégier la détection contextuelle sur le nom seul.

    Returns:
        Code ISO 639-1 ou None si aucune source n'est fiable.
    """
    combined = " ".join(t for t in context_texts if t).strip()
    if len(combined) >= min_context_length:
        lang = detect_language(combined[:2000], min_confidence=min_confidence)
        if lang is not None:
            return lang
    # Fallback : tenter le nom lui-même (moins fiable, mais mieux que rien)
    return detect_language(short_name, min_confidence=min_confidence)


def detect_top_k(
    text: str, k: int = 3, min_confidence: float = 0.1
) -> List[Tuple[str, float]]:
    """
    Retourne les top-k langues candidates avec leur confiance.

    Utile pour textes multilingues ou vérifications de confiance.

    Args:
        text: Texte à analyser.
        k: Nombre de candidats à retourner.
        min_confidence: Filtre les candidats sous ce seuil.

    Returns:
        Liste de tuples (lang_code, confidence), triée par confiance desc.
        Liste vide si détecteur indisponible ou texte trop court.
    """
    if not text or len(text.strip()) < 2:
        return []
    detector = _DetectorSingleton.get()
    if detector is None:
        return []
    try:
        results = detector.detect_multiple(text, top_k=k)
        return [(lang, conf) for lang, conf in results if conf >= min_confidence]
    except Exception as e:
        logger.debug(f"[LANG] detect_top_k error: {e}")
        return []


def is_multilingual(text: str, second_min: float = 0.15) -> bool:
    """
    Détecte si un texte est multilingue (deuxième langue significative).

    Args:
        text: Texte à analyser.
        second_min: Seuil minimum pour considérer la 2e langue comme présente.

    Returns:
        True si la 2e langue la plus probable dépasse `second_min`.
    """
    top = detect_top_k(text, k=2)
    if len(top) < 2:
        return False
    return top[1][1] >= second_min


# ── Helpers pour Entity + claim context ────────────────────────────────


def detect_entity_language(
    entity_name: str,
    claim_texts: List[str],
    min_confidence: float = 0.75,
) -> Optional[str]:
    """
    Détecte la langue d'une entité en utilisant les textes de ses claims.

    Raccourci métier : plus lisible que `detect_language_with_context` pour
    le cas où l'entité a des claims liés (`entity <- ABOUT <- claim`).

    Args:
        entity_name: Le nom de l'entité (peut être court, 1-3 mots).
        claim_texts: Liste de textes de claims où l'entité est sujet/objet.
        min_confidence: Seuil fasttext.

    Returns:
        Code ISO 639-1 ou None si confiance insuffisante sur toutes sources.
    """
    return detect_language_with_context(
        short_name=entity_name,
        context_texts=claim_texts,
        min_confidence=min_confidence,
    )
