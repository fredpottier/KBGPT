"""
Règles structurelles pré-LLM — Phase D du plan Contradiction Intelligence.

Règles domain-agnostiques basées uniquement sur la structure des claims,
pas sur leur contenu métier. Ces règles servent de pré-filtre rapide
avant l'appel LLM du ContradictionClassifier.

Principes :
- Seules les patterns structurels sont exploités (opérateurs, unités, types)
- Les signaux contextuels (doc_type, doc_date) restent des features LLM
- Chaque règle retourne Optional[tuple[TensionNature, TensionLevel]]
  ou None si elle ne s'applique pas
"""

from __future__ import annotations

import re
from typing import Optional, Tuple

from knowbase.claimfirst.clustering.tension_enums import TensionLevel, TensionNature


def apply_structural_rules(
    sf_a: dict,
    sf_b: dict,
    text_a: str = "",
    text_b: str = "",
) -> Optional[Tuple[TensionNature, TensionLevel, str]]:
    """
    Applique les règles structurelles sur une paire de claims.

    Args:
        sf_a: structured_form du claim A
        sf_b: structured_form du claim B
        text_a: texte brut du claim A
        text_b: texte brut du claim B

    Returns:
        (TensionNature, TensionLevel, explanation) ou None si aucune règle ne s'applique.
    """
    # Règle 1 : Opposition ≤/≥ sur même ClaimKey → COMPLEMENTARY
    result = _rule_inequality_complementary(sf_a, sf_b, text_a, text_b)
    if result:
        return result

    # Règle 2 : Unités convertibles → METHODOLOGICAL
    result = _rule_convertible_units(sf_a, sf_b)
    if result:
        return result

    return None


# ── Règle 1 : Opposition d'inégalités ─────────────────────────────────

# Patterns d'opérateurs dans les textes de claims
_LE_PATTERNS = re.compile(r"≤|<=|at most|no more than|up to|maximum|max\.?", re.IGNORECASE)
_GE_PATTERNS = re.compile(r"≥|>=|at least|no less than|minimum|min\.?", re.IGNORECASE)


def _rule_inequality_complementary(
    sf_a: dict,
    sf_b: dict,
    text_a: str,
    text_b: str,
) -> Optional[Tuple[TensionNature, TensionLevel, str]]:
    """
    Si les deux claims expriment des bornes opposées (≤ vs ≥) sur le même
    ClaimKey, ils sont complémentaires (borne inf + borne sup), pas contradictoires.
    """
    a_has_le = bool(_LE_PATTERNS.search(text_a) or _LE_PATTERNS.search(sf_a.get("object", "")))
    a_has_ge = bool(_GE_PATTERNS.search(text_a) or _GE_PATTERNS.search(sf_a.get("object", "")))
    b_has_le = bool(_LE_PATTERNS.search(text_b) or _LE_PATTERNS.search(sf_b.get("object", "")))
    b_has_ge = bool(_GE_PATTERNS.search(text_b) or _GE_PATTERNS.search(sf_b.get("object", "")))

    # A ≤ et B ≥ (ou inverse)
    if (a_has_le and b_has_ge) or (a_has_ge and b_has_le):
        return (
            TensionNature.COMPLEMENTARY,
            TensionLevel.SOFT,
            "Bornes complémentaires (borne inférieure vs borne supérieure)",
        )

    return None


# ── Règle 2 : Unités convertibles ─────────────────────────────────────

# Familles d'unités mutuellement convertibles
_UNIT_FAMILIES = [
    {"mg", "g", "kg", "µg", "mcg"},
    {"ml", "l", "dl", "cl"},
    {"mg/dl", "mmol/l", "g/l"},
    {"mg/24h", "g/g", "mg/g"},
    {"ms", "s", "min", "h", "hr", "hrs"},
    {"mm", "cm", "m", "km"},
    {"%", "pct", "percent"},
]


def _normalize_unit(unit: str) -> str:
    """Normalise une unité pour la comparaison."""
    return unit.strip().lower().replace(" ", "")


def _same_unit_family(unit_a: str, unit_b: str) -> bool:
    """Vérifie si deux unités appartiennent à la même famille convertible."""
    a = _normalize_unit(unit_a)
    b = _normalize_unit(unit_b)
    if a == b:
        return False  # Même unité = pas un problème de conversion
    for family in _UNIT_FAMILIES:
        norm_family = {_normalize_unit(u) for u in family}
        if a in norm_family and b in norm_family:
            return True
    return False


# Regex pour extraire l'unité d'un texte d'objet
_UNIT_EXTRACT = re.compile(
    r"\d+(?:[.,]\d+)?\s*(mg/dl|mmol/l|mg/24h|g/g|mg/g|g/l|"
    r"GB|MB|KB|TB|GiB|MiB|mg|g|kg|µg|mcg|"
    r"ml|dl|cl|l|mm|cm|m|km|ms|min|hrs?|h|s|%)\b",
    re.IGNORECASE,
)


def _extract_unit(text: str) -> Optional[str]:
    """Extrait la première unité détectée dans un texte."""
    match = _UNIT_EXTRACT.search(text)
    return match.group(1) if match else None


def _rule_convertible_units(
    sf_a: dict,
    sf_b: dict,
) -> Optional[Tuple[TensionNature, TensionLevel, str]]:
    """
    Si les deux claims utilisent des unités de la même famille de conversion,
    la divergence est probablement méthodologique (mesure différente).
    """
    obj_a = sf_a.get("object", "")
    obj_b = sf_b.get("object", "")

    unit_a = _extract_unit(obj_a)
    unit_b = _extract_unit(obj_b)

    if unit_a and unit_b and _same_unit_family(unit_a, unit_b):
        return (
            TensionNature.METHODOLOGICAL,
            TensionLevel.SOFT,
            f"Unités convertibles ({unit_a} vs {unit_b}) — divergence de mesure probable",
        )

    return None
