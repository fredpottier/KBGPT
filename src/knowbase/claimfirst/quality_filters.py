# src/knowbase/claimfirst/quality_filters.py
"""
Filtres qualité post-extraction des claims (Phase 1.6).

3 filtres structurels language-agnostic :
1. Longueur minimale (30 chars) avec exemptions positives
2. Boilerplate universel (regex)
3. Heading-like (signaux structurels)

Contrainte : 100% language-agnostic — pas de listes de verbes
ni de mots dépendants d'une langue.
"""

from __future__ import annotations

import re
from typing import Dict, List, Tuple, TYPE_CHECKING

if TYPE_CHECKING:
    from knowbase.claimfirst.models.claim import Claim

# ── Signaux positifs (preuves qu'une claim courte est valide) ──

TECH_VERSION_PATTERN = re.compile(r'\d+(\.\d+)+')  # versions : 1.2.3
OPERATOR_PATTERN = re.compile(r'[><=!]=?')  # comparateurs
UNIT_PATTERN = re.compile(
    r'\d+\s*(GB|MB|KB|%|ms|TLS|HTTP|HTTPS|TCP|UDP|SSL|IPv[46])',
    re.IGNORECASE,
)
LABEL_VALUE_PATTERN = re.compile(r'.+:\s*\S+')  # "label: value"

# ── Boilerplate universel (language-agnostic) ──

BOILERPLATE_PATTERNS = [
    re.compile(r'^\d+\.?\s*$'),                          # numéro seul : "42." "7"
    re.compile(r'^page\s+\d+', re.IGNORECASE),           # "Page 3 of 10"
    re.compile(r'https?://\S+$'),                        # URL seule
    re.compile(r'copyright|©|all rights reserved', re.IGNORECASE),
    re.compile(r'disclaimer', re.IGNORECASE),
    re.compile(r'SAP\s+Note\s+\d{5,}', re.IGNORECASE),  # "SAP Note 123456"
    re.compile(r'^[\s•\-\*]+$'),                         # bullet vide
]


def has_positive_signal(claim: "Claim") -> bool:
    """
    Détecte les signaux positifs justifiant de garder une claim courte.

    - structured_form complet (S+P+O) et len >= 15
    - Pattern technique (version, opérateur, unité)
    - Pattern "label: value"
    """
    text = claim.text

    # structured_form complet avec longueur minimum
    if claim.structured_form and len(text.strip()) >= 15:
        sf = claim.structured_form
        if sf.get("subject") and sf.get("predicate") and sf.get("object"):
            return True

    # Patterns techniques universels
    if TECH_VERSION_PATTERN.search(text):
        return True
    if OPERATOR_PATTERN.search(text):
        return True
    if UNIT_PATTERN.search(text):
        return True

    # Pattern "label: value"
    if LABEL_VALUE_PATTERN.match(text):
        return True

    return False


def is_heading_like(text: str) -> bool:
    """
    Détecte les titres/headers via signaux structurels, pas linguistiques.

    Un heading = court, pas de ponctuation d'assertion, ratio Title Case élevé.
    """
    # Trop long pour être un heading → pas un heading
    if len(text) > 80:
        return False
    # Trop court pour être évalué (déjà filtré par longueur min)
    if len(text) < 30:
        return False

    # Signaux d'assertion (si présents → PAS un heading)
    has_final_punct = text.rstrip().endswith(('.', ';', ':'))
    has_comma = ',' in text
    has_digit = bool(re.search(r'\d', text))
    has_parenthesis = '(' in text and ')' in text
    has_colon_value = bool(re.search(r':\s*\S', text))

    assertion_signals = sum([
        has_final_punct,
        has_comma,
        has_digit,
        has_parenthesis,
        has_colon_value,
    ])

    # Au moins 1 signal d'assertion → pas un heading
    if assertion_signals >= 1:
        return False

    # Vérifier Title Case : proportion de mots capitalisés
    words = text.split()
    if len(words) < 2:
        return False
    capitalized = sum(1 for w in words if w[0].isupper())
    title_case_ratio = capitalized / len(words)

    return title_case_ratio >= 0.6  # 60%+ des mots capitalisés sans ponctuation


def filter_claims_quality(
    claims: List["Claim"],
) -> Tuple[List["Claim"], Dict[str, int]]:
    """
    Filtrage qualité post-dedup, pré-enrichment (Phase 1.6).

    3 filtres structurels language-agnostic :
    1. Longueur minimale (30 chars) avec exemptions positives
    2. Boilerplate universel (regex)
    3. Heading-like (signaux structurels)
    """
    stats = {
        "kept": 0,
        "filtered_short": 0,
        "filtered_boilerplate": 0,
        "filtered_heading": 0,
    }
    kept = []

    for claim in claims:
        text = claim.text.strip()

        # Filtre 1: Longueur minimale
        if len(text) < 30 and not has_positive_signal(claim):
            stats["filtered_short"] += 1
            continue

        # Filtre 2: Boilerplate
        if any(p.search(text) for p in BOILERPLATE_PATTERNS):
            stats["filtered_boilerplate"] += 1
            continue

        # Filtre 3: Heading-like
        if is_heading_like(text):
            stats["filtered_heading"] += 1
            continue

        stats["kept"] += 1
        kept.append(claim)

    return kept, stats


__all__ = [
    "filter_claims_quality",
    "has_positive_signal",
    "is_heading_like",
    "BOILERPLATE_PATTERNS",
    "TECH_VERSION_PATTERN",
    "OPERATOR_PATTERN",
    "UNIT_PATTERN",
    "LABEL_VALUE_PATTERN",
]
