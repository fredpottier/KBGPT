"""
identifier_guard.py — Garde-fou identifiants (production).

Extrait les identifiants « protégés » d'un texte pour ne JAMAIS filtrer/fusionner à tort
un claim/unité portant un identifiant précis qu'un utilisateur pourrait rechercher
(transaction SAP, code objet, n° réglement, chemin, version...). Domain-agnostic
(heuristiques de FORME, aucun dictionnaire de codes).

Deux niveaux (validés empiriquement, cf probes dédup + filtre utilité) :
- `protected_identifiers()` : LARGE — pour la DÉDUP (err vers garder ; au pire on garde
  un near-dup). Inclut les acronymes ALL_CAPS courts (SAP, HR...).
- `specific_identifiers()` : STRICT — pour le FILTRE UTILITÉ / SÉLECTION (ne doit pas
  sauver le boilerplate via le nom du produit). Ne garde que digit / underscore / chemin /
  ALL_CAPS≥4. (Au smoke utilité : la version large sauvait à tort « SAP shall not be
  liable » via `sap` ; la version stricte corrige.)
"""

from __future__ import annotations

import re
from typing import List

# ALL_CAPS / acronymes / codes (≥2 chars, commence par majuscule) : SAP, HANA, WWI, CG5Z, SE80
_ALLCAPS_RE = re.compile(r"\b[A-Z][A-Z0-9]{1,}\b")
# snake_case / identifiants techniques : valid_from, ANA_PAI_PS_SRV, structured_form_json
_SNAKE_RE = re.compile(r"\b\w+_\w+\b")
# tout token porteur d'un chiffre : 2021/821, v3.1, S/4HANA, CG5Z
_DIGIT_TOKEN_RE = re.compile(r"\b[\w/.\-]*\d[\w/.\-]*\b")


def protected_identifiers(text: str) -> "frozenset[str]":
    """Ensemble LARGE d'identifiants protégés (pour la dédup). Casse normalisée."""
    if not text:
        return frozenset()
    toks: set[str] = set()
    for m in _ALLCAPS_RE.findall(text):
        toks.add(m.lower())
    for m in _SNAKE_RE.findall(text):
        toks.add(m.lower())
    for m in _DIGIT_TOKEN_RE.findall(text):
        if re.search(r"\d", m) and len(m) >= 2:
            toks.add(m.lower())
    return frozenset(toks)


def specific_identifiers(text: str) -> List[str]:
    """Sous-ensemble STRICT (spécificité-aware) pour filtre utilité / sélection.

    Ne protège QUE les identifiants rares/précis : digit, underscore, séparateur de
    chemin, ou ALL_CAPS pur ≥4 chars. PAS les acronymes alpha ≤3 (sap, hr, tm, eu...)
    ni les noms de produit — sinon le garde-fou sauve à tort le boilerplate.
    """
    out: List[str] = []
    for tok in protected_identifiers(text):
        has_digit = bool(re.search(r"\d", tok))
        has_sep = ("_" in tok) or ("/" in tok) or ("." in tok) or ("-" in tok)
        pure_alpha = tok.isalpha()
        if has_digit or has_sep:
            out.append(tok)
        elif pure_alpha and len(tok) >= 4:
            out.append(tok)
    return sorted(set(out))


def has_specific_identifier(text: str) -> bool:
    """True si le texte porte au moins un identifiant précis (→ ne jamais jeter)."""
    return len(specific_identifiers(text)) > 0
