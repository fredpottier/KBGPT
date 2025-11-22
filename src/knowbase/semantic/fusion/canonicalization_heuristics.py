"""
🌊 OSMOSE Semantic Fusion - Canonicalization Heuristics

Phase 1.8.1d: Heuristiques pour canonicalization rapide (sans appel LLM).

Applique des règles simples pour détecter le nom canonique dans 80% des cas,
réservant le LLM fallback pour les 20% ambigus.
"""

from typing import List, Optional
import re
import logging

logger = logging.getLogger(__name__)


# Marketing prefixes à retirer
MARKETING_PREFIXES = [
    "RISE with ",
    "GROW with ",
    "Transform with ",
    "Powered by ",
    "Based on ",
    "Built on ",
    "Enabled by ",
    "Driven by ",
    "Run with ",
    "Includes ",
    "Contains ",
]

# Suffixes génériques à retirer (sauf si partie du nom officiel)
GENERIC_SUFFIXES = [
    " Solution",
    " Platform",
    " System",
    " Service",
    " Services",
    " Tool",
    " Tools",
    " Application",
    " App",
]


def remove_marketing_prefixes(name: str) -> str:
    """
    Retire les préfixes marketing connus.

    Args:
        name: Nom du concept

    Returns:
        Nom sans préfixe marketing

    Example:
        "RISE with SAP S/4HANA Cloud" → "SAP S/4HANA Cloud"
    """
    for prefix in MARKETING_PREFIXES:
        if name.startswith(prefix):
            return name[len(prefix):]
    return name


def remove_possessives(name: str) -> str:
    """
    Retire les formes possessives ('s, 's).

    Args:
        name: Nom du concept

    Returns:
        Nom sans possessif

    Example:
        "Microsoft's Azure" → "Microsoft Azure"
    """
    # Retirer 's et 's en fin ou au milieu
    name = re.sub(r"'s\b", "", name)
    name = re.sub(r"'s\b", "", name)
    return name.strip()


def is_substring_variant(candidate: str, variants: List[str]) -> bool:
    """
    Vérifie si le candidat est substring de tous les autres variants.

    Args:
        candidate: Nom candidat (le plus court)
        variants: Toutes les variantes

    Returns:
        True si candidate est substring de tous les autres

    Example:
        candidate="SAP S/4HANA"
        variants=["RISE with SAP S/4HANA Cloud", "SAP S/4HANA Cloud Private"]
        → True (SAP S/4HANA apparaît dans tous)
    """
    for variant in variants:
        if variant == candidate:
            continue
        if candidate not in variant:
            return False
    return True


def apply_heuristics(variants: List[str]) -> Optional[str]:
    """
    Applique heuristiques de canonicalization sur liste de variantes.

    Args:
        variants: Liste de noms de concepts similaires

    Returns:
        Nom canonique si heuristique conclut, None sinon (fallback LLM)

    Process:
        1. Nettoyer toutes les variantes (préfixes, possessifs)
        2. Si une variante nettoyée est unique → retourner
        3. Si une variante est substring de toutes → retourner (plus courte)
        4. Sinon → None (besoin LLM)

    Examples:
        ["RISE with SAP S/4HANA", "SAP S/4HANA Cloud", "SAP S/4HANA"]
        → "SAP S/4HANA" (substring de tous)

        ["Microsoft Azure Cloud", "Azure Platform", "Microsoft Azure"]
        → "Microsoft Azure" (plus court après nettoyage)

        ["Oracle Database Enterprise", "Oracle DB Standard"]
        → None (ambiguïté, besoin LLM)
    """
    if not variants or len(variants) == 0:
        return None

    if len(variants) == 1:
        # Un seul variant, nettoyer et retourner
        cleaned = remove_possessives(remove_marketing_prefixes(variants[0]))
        return cleaned.strip()

    # Étape 1: Nettoyer toutes les variantes
    cleaned_variants = []
    for variant in variants:
        cleaned = remove_possessives(remove_marketing_prefixes(variant))
        cleaned = cleaned.strip()
        if cleaned:
            cleaned_variants.append(cleaned)

    if not cleaned_variants:
        return None

    # Dédupliquer (si nettoyage a unifié)
    unique_cleaned = list(set(cleaned_variants))

    # Étape 2: Si nettoyage a unifié tout → succès
    if len(unique_cleaned) == 1:
        logger.debug(
            f"[Heuristics] Unified variants via cleaning: {variants} → {unique_cleaned[0]}"
        )
        return unique_cleaned[0]

    # Étape 3: Trier par longueur (plus court = potentiellement canonique)
    sorted_variants = sorted(unique_cleaned, key=len)
    shortest = sorted_variants[0]

    # Étape 4: Vérifier si le plus court est substring de tous les autres
    if is_substring_variant(shortest, unique_cleaned):
        logger.debug(
            f"[Heuristics] Found substring canonical: {variants} → {shortest}"
        )
        return shortest

    # Étape 5: Vérifier si le plus court + suffixe générique = autres variants
    for suffix in GENERIC_SUFFIXES:
        with_suffix = shortest + suffix
        if with_suffix in unique_cleaned:
            # Le nom sans suffixe est probablement canonique
            logger.debug(
                f"[Heuristics] Removed generic suffix: {with_suffix} → {shortest}"
            )
            return shortest

    # Aucune heuristique concluante → fallback LLM
    logger.debug(
        f"[Heuristics] No conclusive heuristic for variants: {unique_cleaned}, need LLM"
    )
    return None


def canonicalize_single_concept(name: str) -> str:
    """
    Canonicalise un concept unique (pas de variantes à comparer).

    Args:
        name: Nom du concept

    Returns:
        Nom nettoyé

    Note:
        Utilisé quand un concept apparaît une seule fois (pas de cluster)
    """
    cleaned = remove_possessives(remove_marketing_prefixes(name))

    # Retirer suffixes génériques si présents
    for suffix in GENERIC_SUFFIXES:
        if cleaned.endswith(suffix):
            # Vérifier que retirer le suffixe laisse un nom significatif
            without_suffix = cleaned[:-len(suffix)].strip()
            if len(without_suffix) > 3:  # Au moins 4 caractères
                cleaned = without_suffix
                break

    return cleaned.strip()
