"""
Fonctions de normalisation pour OSMOSE.

Ce module fournit des fonctions de normalisation utilisées pour la
déduplication des concepts et autres opérations de matching.

Phase 2.8.1 - Canonical Deduplication Fix
"""

import re
import unicodedata
from typing import Optional

# Patterns pré-compilés pour performance
_WEAK_PUNCT_RE = re.compile(r"[.,;:!?()\[\]{}'\"`''""]")
_WS_RE = re.compile(r"\s+")
_DASH_RE = re.compile(r"[—–]")  # Em dash et en dash


def normalize_canonical_key(name: Optional[str]) -> str:
    """
    Génère une clé de déduplication robuste pour les concepts canoniques.

    Cette fonction normalise un nom de concept pour créer une clé stable
    utilisée lors de la déduplication. Elle applique plusieurs transformations
    pour gérer les variations typographiques courantes.

    Transformations appliquées:
    1. Trim + lowercase
    2. Normalisation Unicode NFKC (compatibility decomposition + canonical composition)
    3. Normalisation des tirets (em dash, en dash → hyphen)
    4. Suppression ponctuation faible (.,;:!?()[]{}'"`''")
    5. Normalisation espaces multiples

    Args:
        name: Le nom du concept à normaliser

    Returns:
        La clé normalisée, ou chaîne vide si name est None/vide

    Examples:
        >>> normalize_canonical_key("Legitimate Interests")
        'legitimate interests'
        >>> normalize_canonical_key("GDPR (General Data Protection Regulation)")
        'gdpr general data protection regulation'
        >>> normalize_canonical_key("High-Risk AI System")
        'high-risk ai system'
        >>> normalize_canonical_key("  Multiple   Spaces  ")
        'multiple spaces'
        >>> normalize_canonical_key(None)
        ''
    """
    if not name:
        return ""

    # 1. Trim + lowercase
    key = name.strip().lower()

    # 2. Normalisation Unicode NFKC
    # Convertit les caractères compatibles en leur forme canonique
    # Ex: "ﬁ" (ligature) → "fi", "½" → "1/2"
    key = unicodedata.normalize("NFKC", key)

    # 3. Normalisation des tirets
    # Em dash (—) et en dash (–) → hyphen (-)
    key = _DASH_RE.sub("-", key)

    # 4. Suppression ponctuation faible
    # Garde les tirets normaux car ils sont significatifs (ex: "high-risk")
    key = _WEAK_PUNCT_RE.sub("", key)

    # 5. Normalisation espaces multiples
    key = _WS_RE.sub(" ", key)

    return key.strip()


def compute_canonical_key_fallback(canonical_id: str) -> str:
    """
    Génère une clé fallback pour les concepts avec nom vide/invalide.

    Utilisée lorsque normalize_canonical_key() retourne une chaîne vide.
    La clé fallback utilise l'ID canonique pour garantir l'unicité.

    Args:
        canonical_id: L'ID unique du concept canonique

    Returns:
        Une clé fallback au format "__empty__:{canonical_id}"

    Example:
        >>> compute_canonical_key_fallback("cc_01HZYK7P8D3J6Q0V1KX9Y2A3BC")
        '__empty__:cc_01HZYK7P8D3J6Q0V1KX9Y2A3BC'
    """
    return f"__empty__:{canonical_id}"
