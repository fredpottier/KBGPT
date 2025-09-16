# -*- coding: utf-8 -*-
"""
Utilitaires pour normaliser les noms de solutions SAP
a partir des documents ingeres (PPTX, PDF, Excel, etc.).
"""

from typing import Iterable, Tuple

from rapidfuzz import fuzz, process
from utils.sap_solutions_dict import SAP_SOLUTIONS


def normalize_solution_name(raw_name: str, threshold: int = 80) -> Tuple[str, str]:
    """
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
    if not raw_name:
        return "UNMAPPED", ""

    candidates: dict[str, str] = {}
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

    # Recherche du meilleur match
    best_match_tuple = process.extractOne(
        raw_name, candidates.keys(), scorer=fuzz.token_sort_ratio
    )
    if not best_match_tuple:
        return "UNMAPPED", raw_name
    best_match, score, _ = best_match_tuple

    if score >= threshold:
        sol_id = candidates[best_match]
        return sol_id, SAP_SOLUTIONS[sol_id]["canonical_name"]

    return "UNMAPPED", raw_name
