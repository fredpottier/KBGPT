# -*- coding: utf-8 -*-
"""
⚠️  DEPRECATED - Utiliser knowbase.common.entity_normalizer à la place

Utilitaires pour normaliser les noms de solutions SAP
a partir des documents ingeres (PPTX, PDF, Excel, etc.).

Ce module est conservé pour compatibilité ascendante mais sera supprimé.
Migration recommandée :

    from knowbase.common.entity_normalizer import get_entity_normalizer
    from knowbase.api.schemas.knowledge_graph import EntityType

    normalizer = get_entity_normalizer()
    entity_id, canonical = normalizer.normalize_entity_name(raw_name, EntityType.SOLUTION)
"""

import warnings

from typing import Iterable, Tuple

from rapidfuzz import fuzz, process
from .solutions_dict import SAP_SOLUTIONS


def _normalize_for_matching(text: str) -> str:
    """
    Normalise un texte pour le fuzzy matching en préservant
    les caractères spéciaux importants comme les chiffres et "/".
    """
    return text.lower().strip()


def normalize_solution_name(raw_name: str, threshold: int = 80) -> Tuple[str, str]:
    """
    ⚠️  DEPRECATED - Utiliser entity_normalizer.normalize_entity_name() à la place

    Normalise un nom de solution trouve dans un document en le mappant
    a un identifiant stable SAP et a son nom canonique.

    Args:
        raw_name (str): Nom brut trouve dans le document (ex: "Private ERP Cloud")
        threshold (int): Score minimum de similarite (0-100)

    Returns:
        tuple: (solution_id, canonical_name)
               solution_id = ID stable (ex: "S4HANA_PCE")
               canonical_name = nom canonique officiel (ex: "SAP S/4HANA Cloud, Private Edition")
               Si aucun match fiable -> ("UNMAPPED", raw_name)
    """
    warnings.warn(
        "normalize_solution_name() est déprécié. "
        "Utiliser entity_normalizer.normalize_entity_name(raw_name, EntityType.SOLUTION) à la place.",
        DeprecationWarning,
        stacklevel=2
    )
    if not raw_name:
        return "UNMAPPED", ""

    # Normaliser l'input pour le matching
    normalized_raw = _normalize_for_matching(raw_name)

    candidates: dict[str, str] = {}
    normalized_candidates: dict[str, str] = {}

    for sol_id, sol in SAP_SOLUTIONS.items():
        # On prend en compte le canonical_name et tous les alias
        candidate_names: list[str] = []
        canonical_name = sol.get("canonical_name")
        if isinstance(canonical_name, str) and canonical_name:
            candidate_names.append(canonical_name)

        aliases_raw = sol.get("aliases")
        alias_iterable: Iterable[str] = []
        if isinstance(aliases_raw, (list, tuple, set)):
            alias_iterable = (a for a in aliases_raw if isinstance(a, str))

        for alias in alias_iterable:
            if alias:
                candidate_names.append(alias)

        for name in candidate_names:
            candidates[name] = sol_id
            # Créer une version normalisée pour le matching
            normalized_name = _normalize_for_matching(name)
            normalized_candidates[normalized_name] = name

    # Recherche du meilleur match sur les versions normalisées
    best_match_tuple = process.extractOne(
        normalized_raw, normalized_candidates.keys(), scorer=fuzz.token_sort_ratio
    )
    if not best_match_tuple:
        return "UNMAPPED", raw_name
    best_normalized_match, score, _ = best_match_tuple

    if score >= threshold:
        # Retrouver le nom original depuis la version normalisée
        original_match = normalized_candidates[best_normalized_match]
        sol_id = candidates[original_match]
        return sol_id, SAP_SOLUTIONS[sol_id]["canonical_name"]

    return "UNMAPPED", raw_name
