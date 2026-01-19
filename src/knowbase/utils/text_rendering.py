"""
Utilitaires de rendu texte pour OSMOSE.

Fonctions pour nettoyer les marqueurs Docling lors du rendu UI
sans modifier le texte de référence (source-of-truth).

Architecture:
- Le texte avec marqueurs reste la source de vérité pour spans/chunks
- Ces fonctions nettoient UNIQUEMENT pour l'affichage ou les embeddings
- Les positions (char_start, char_end) restent basées sur le texte brut

Marqueurs Docling gérés:
- [PAGE n | TYPE=xxx]
- [TITLE level=n]
- [PARAGRAPH]
- [TABLE_START id=x], [TABLE_END], [TABLE_SUMMARY], [TABLE_RAW]
- [VISUAL_ENRICHMENT id=x confidence=y], [END_VISUAL_ENRICHMENT]

Voir: doc/ongoing/ADR_DUAL_CHUNKING_ARCHITECTURE.md
"""

import re
from typing import Optional, Tuple

# Pattern pour tous les marqueurs OSMOSE/Docling
# Capture les lignes entières commençant par un marqueur
MARKER_LINE_PATTERN = re.compile(
    r"^\[(PAGE|TITLE|PARAGRAPH|TABLE_START|TABLE_END|TABLE_SUMMARY|TABLE_RAW|"
    r"VISUAL_ENRICHMENT|END_VISUAL_ENRICHMENT)[^\]]*\]\s*$",
    re.MULTILINE
)

# Pattern pour marqueurs inline (dans une ligne de texte)
MARKER_INLINE_PATTERN = re.compile(
    r"\[(PAGE|TITLE|PARAGRAPH|TABLE_START|TABLE_END|TABLE_SUMMARY|TABLE_RAW|"
    r"VISUAL_ENRICHMENT|END_VISUAL_ENRICHMENT)[^\]]*\]"
)

# Pattern pour blocs VISUAL_ENRICHMENT complets (multi-lignes)
VISUAL_BLOCK_PATTERN = re.compile(
    r"\[VISUAL_ENRICHMENT[^\]]*\].*?\[END_VISUAL_ENRICHMENT\]",
    re.DOTALL
)

# Lignes de métadonnées Vision à supprimer (dans les blocs VISUAL_ENRICHMENT)
VISION_METADATA_PATTERNS = [
    re.compile(r"^diagram_type:\s*.*$", re.MULTILINE),
    re.compile(r"^visible_elements:\s*$", re.MULTILINE),
    re.compile(r"^\s*-\s*\[E\d+\|[^\]]+\].*$", re.MULTILINE),  # - [E1|box] "label"
]


def strip_markers(text: str, preserve_content: bool = True) -> str:
    """
    Supprime les marqueurs Docling d'un texte.

    Args:
        text: Texte avec marqueurs Docling
        preserve_content: Si True, garde le contenu entre marqueurs.
                         Si False, supprime aussi les blocs VISUAL_ENRICHMENT complets.

    Returns:
        Texte nettoyé sans marqueurs

    Example:
        >>> text = "[PARAGRAPH]\\nThis is content.\\n[TABLE_START id=1]"
        >>> strip_markers(text)
        'This is content.'
    """
    if not text:
        return ""

    result = text

    # Option: supprimer les blocs VISUAL_ENRICHMENT complets
    if not preserve_content:
        result = VISUAL_BLOCK_PATTERN.sub("", result)

    # Supprimer les lignes de marqueurs seuls
    result = MARKER_LINE_PATTERN.sub("", result)

    # Supprimer les marqueurs inline restants
    result = MARKER_INLINE_PATTERN.sub("", result)

    # Supprimer les métadonnées Vision orphelines
    for pattern in VISION_METADATA_PATTERNS:
        result = pattern.sub("", result)

    # Nettoyer les lignes vides multiples
    result = re.sub(r"\n{3,}", "\n\n", result)

    # Trim
    return result.strip()


def render_quote(
    text_with_markers: str,
    span_start: int,
    span_end: int,
    context_chars: int = 0
) -> str:
    """
    Extrait et nettoie une quote pour affichage UI.

    Cette fonction extrait un span du texte brut (avec marqueurs),
    puis nettoie les marqueurs pour un affichage propre.
    Les positions span_start/span_end sont basées sur le texte brut.

    Args:
        text_with_markers: Texte source complet (avec marqueurs)
        span_start: Position de début dans le texte brut
        span_end: Position de fin dans le texte brut
        context_chars: Caractères de contexte à ajouter avant/après (optionnel)

    Returns:
        Quote nettoyée pour affichage UI

    Example:
        >>> text = "[PARAGRAPH]\\nSAP BTP enables integration.\\n[TABLE_START]"
        >>> # Supposons que "SAP BTP enables integration" commence à pos 13
        >>> render_quote(text, 13, 40)
        'SAP BTP enables integration.'
    """
    if not text_with_markers or span_start < 0 or span_end <= span_start:
        return ""

    # Ajuster les bornes avec contexte
    actual_start = max(0, span_start - context_chars)
    actual_end = min(len(text_with_markers), span_end + context_chars)

    # Extraire le span brut
    raw_quote = text_with_markers[actual_start:actual_end]

    # Nettoyer les marqueurs
    clean_quote = strip_markers(raw_quote, preserve_content=True)

    # Ajouter ellipses si contexte tronqué
    prefix = "..." if actual_start > 0 and context_chars > 0 else ""
    suffix = "..." if actual_end < len(text_with_markers) and context_chars > 0 else ""

    return f"{prefix}{clean_quote}{suffix}"


def make_embedding_text(text_with_markers: str) -> str:
    """
    Prépare le texte pour calcul d'embeddings.

    Supprime les marqueurs Docling qui sont du "bruit" répétitif
    pouvant dégrader la qualité des embeddings vectoriels.

    Note: Cette fonction est optionnelle. À utiliser si vous observez
    un impact sur la qualité du retrieval.

    Args:
        text_with_markers: Texte source avec marqueurs Docling

    Returns:
        Texte nettoyé optimisé pour embeddings

    Example:
        >>> text = "[PAGE 1]\\n[PARAGRAPH]\\nImportant content here.\\n[TABLE_START]\\n| A | B |"
        >>> make_embedding_text(text)
        'Important content here.\\n| A | B |'
    """
    if not text_with_markers:
        return ""

    # Supprimer marqueurs mais garder le contenu (tables, etc.)
    result = strip_markers(text_with_markers, preserve_content=True)

    return result


def make_embedding_text_aggressive(text_with_markers: str) -> str:
    """
    Version agressive du nettoyage pour embeddings.

    Supprime également les blocs VISUAL_ENRICHMENT complets
    car leur contenu structuré (diagram_type, visible_elements)
    n'est pas optimal pour les embeddings sémantiques.

    À utiliser pour les chunks de type "retrieval" où la qualité
    sémantique prime sur la complétude.

    Args:
        text_with_markers: Texte source avec marqueurs Docling

    Returns:
        Texte fortement nettoyé pour embeddings
    """
    if not text_with_markers:
        return ""

    # Supprimer marqueurs ET blocs VISUAL_ENRICHMENT complets
    result = strip_markers(text_with_markers, preserve_content=False)

    return result


def extract_span_with_mapping(
    text_with_markers: str,
    span_start: int,
    span_end: int
) -> Tuple[str, int, int]:
    """
    Extrait un span et calcule les nouvelles positions dans le texte nettoyé.

    Utile si vous avez besoin de mapper des positions du texte brut
    vers le texte nettoyé (cas avancé).

    Args:
        text_with_markers: Texte source avec marqueurs
        span_start: Position début dans texte brut
        span_end: Position fin dans texte brut

    Returns:
        Tuple (texte_nettoyé, nouveau_start, nouveau_end)

    Note: Les nouvelles positions sont approximatives car le nettoyage
    peut modifier la structure du texte de manière non-linéaire.
    """
    if not text_with_markers or span_start < 0:
        return ("", 0, 0)

    # Texte avant le span
    before = text_with_markers[:span_start]
    before_clean = strip_markers(before, preserve_content=True)

    # Le span lui-même
    span_text = text_with_markers[span_start:span_end]
    span_clean = strip_markers(span_text, preserve_content=True)

    # Nouvelles positions
    new_start = len(before_clean)
    new_end = new_start + len(span_clean)

    return (span_clean, new_start, new_end)


__all__ = [
    "strip_markers",
    "render_quote",
    "make_embedding_text",
    "make_embedding_text_aggressive",
    "extract_span_with_mapping",
    "MARKER_LINE_PATTERN",
    "MARKER_INLINE_PATTERN",
]
