"""
Lexical Utilities for Corpus Entity Resolution

Functions for computing lexical keys and similarity scores.

Author: Claude Code
Date: 2026-01-01
"""

from __future__ import annotations

import re
import unicodedata
from functools import lru_cache
from typing import Optional


def compute_lex_key(canonical_name: str) -> str:
    """
    Compute normalized lexical key for Entity Resolution matching.

    Normalisation forte, agnostique (pas de whitelist métier).

    Steps:
    1. Lowercase
    2. Unicode normalization (NFKD)
    3. Remove diacritics
    4. Remove punctuation
    5. Normalize whitespace
    6. Light singularization (EN/FR)

    Args:
        canonical_name: Original concept name

    Returns:
        Normalized lexical key
    """
    if not canonical_name:
        return ""

    text = canonical_name.lower().strip()

    # Unicode normalization (decompose accents)
    text = unicodedata.normalize('NFKD', text)

    # Remove diacritics (keep only ASCII)
    text = text.encode('ascii', 'ignore').decode('ascii')

    # Remove punctuation (keep alphanumeric and spaces)
    text = re.sub(r'[^\w\s]', ' ', text)

    # Normalize whitespace
    text = ' '.join(text.split())

    # Light singularization (English/French)
    # Remove trailing 's' if word is long enough
    words = text.split()
    normalized_words = []
    for word in words:
        if len(word) > 3 and word.endswith('s'):
            # Don't singularize common exceptions
            if word not in {'analysis', 'process', 'access', 'success', 'business'}:
                word = word[:-1]
        normalized_words.append(word)

    return ' '.join(normalized_words)


@lru_cache(maxsize=10000)
def _jaro_winkler_cached(s1: str, s2: str) -> float:
    """Cached Jaro-Winkler computation."""
    return _jaro_winkler(s1, s2)


def _jaro(s1: str, s2: str) -> float:
    """Compute Jaro similarity between two strings."""
    if not s1 or not s2:
        return 0.0

    if s1 == s2:
        return 1.0

    len1, len2 = len(s1), len(s2)

    # Match window
    match_distance = max(len1, len2) // 2 - 1
    if match_distance < 0:
        match_distance = 0

    s1_matches = [False] * len1
    s2_matches = [False] * len2

    matches = 0
    transpositions = 0

    # Find matches
    for i in range(len1):
        start = max(0, i - match_distance)
        end = min(i + match_distance + 1, len2)

        for j in range(start, end):
            if s2_matches[j] or s1[i] != s2[j]:
                continue
            s1_matches[i] = True
            s2_matches[j] = True
            matches += 1
            break

    if matches == 0:
        return 0.0

    # Count transpositions
    k = 0
    for i in range(len1):
        if not s1_matches[i]:
            continue
        while not s2_matches[k]:
            k += 1
        if s1[i] != s2[k]:
            transpositions += 1
        k += 1

    return (
        (matches / len1 + matches / len2 + (matches - transpositions / 2) / matches)
        / 3
    )


def _jaro_winkler(s1: str, s2: str, winkler_prefix_weight: float = 0.1) -> float:
    """
    Compute Jaro-Winkler similarity between two strings.

    Jaro-Winkler gives extra weight to strings that match from the beginning.

    Args:
        s1: First string
        s2: Second string
        winkler_prefix_weight: Weight for common prefix (default 0.1)

    Returns:
        Similarity score between 0 and 1
    """
    jaro_sim = _jaro(s1, s2)

    # Common prefix (up to 4 characters)
    prefix_len = 0
    for i in range(min(len(s1), len(s2), 4)):
        if s1[i] == s2[i]:
            prefix_len += 1
        else:
            break

    return jaro_sim + prefix_len * winkler_prefix_weight * (1 - jaro_sim)


def lex_score(key1: str, key2: str) -> float:
    """
    Compute lexical similarity between two lex_keys.

    Uses Jaro-Winkler similarity which is well-suited for:
    - Short strings (concept names)
    - Typos and minor variations
    - Prefix matching (important for similar concepts)

    Args:
        key1: First lexical key
        key2: Second lexical key

    Returns:
        Similarity score between 0 and 1
    """
    if not key1 or not key2:
        return 0.0

    if key1 == key2:
        return 1.0

    # Use cached Jaro-Winkler
    return _jaro_winkler_cached(key1, key2)


def compute_exact_match_score(name1: str, name2: str) -> float:
    """
    Check for exact match after normalization.

    Returns 1.0 if exact match, 0.0 otherwise.
    """
    key1 = compute_lex_key(name1)
    key2 = compute_lex_key(name2)
    return 1.0 if key1 == key2 else 0.0


def extract_acronym(text: str) -> Optional[str]:
    """
    Extract acronym from text if present.

    Examples:
    - "GDPR" -> "GDPR"
    - "General Data Protection Regulation (GDPR)" -> "GDPR"
    - "General Data Protection Regulation" -> None
    """
    if not text:
        return None

    text = text.strip()

    # Check if all uppercase and short (2-10 chars)
    if text.isupper() and 2 <= len(text) <= 10:
        return text

    # Check for parenthetical acronym at end
    match = re.search(r'\(([A-Z]{2,10})\)$', text)
    if match:
        return match.group(1)

    return None


def is_acronym_of(acronym: str, full_text: str) -> bool:
    """
    Check if acronym could be derived from full_text.

    Examples:
    - is_acronym_of("GDPR", "General Data Protection Regulation") -> True
    - is_acronym_of("AI", "Artificial Intelligence") -> True
    - is_acronym_of("NIS2", "Network Information Security") -> True
    """
    if not acronym or not full_text:
        return False

    acronym = acronym.upper()
    words = [w for w in full_text.split() if len(w) > 0]

    if len(words) < 2:
        return False

    # Extract first letters
    initials = ''.join(w[0].upper() for w in words if w[0].isalpha())

    # Check if acronym matches initials
    if acronym == initials:
        return True

    # Check if acronym is contained in initials (for partial matches like NIS2 -> NIS)
    acronym_letters = ''.join(c for c in acronym if c.isalpha())
    if acronym_letters and acronym_letters in initials:
        return True

    return False


def normalize_for_comparison(text: str) -> str:
    """
    Simpler normalization for quick comparison.

    Used for blocking, not for final scoring.
    """
    if not text:
        return ""

    text = text.lower().strip()
    text = re.sub(r'[^\w\s]', ' ', text)
    text = ' '.join(text.split())
    return text
