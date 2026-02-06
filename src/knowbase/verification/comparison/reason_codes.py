"""
OSMOSE Verification - Reason Codes

Codes structurés pour les raisons de comparaison.
Permet stats et debug sans parser les logs.

Author: Claude Code
Date: 2026-02-03
Version: 1.1
"""

from enum import Enum
from typing import Dict, Any, Optional


class ReasonCode(str, Enum):
    """
    Codes structurés pour expliquer les résultats de comparaison.

    Avantages vs texte libre:
    - Metrics et statistiques faciles
    - Debug déterministe
    - Localisation (i18n) possible
    - Tests unitaires précis
    """

    # Matches
    EXACT_MATCH = "EXACT_MATCH"
    EQUIVALENT_MATCH = "EQUIVALENT_MATCH"  # Après normalisation (e.g., 99.5% vs 0.995)

    # Interval comparisons
    VALUE_IN_INTERVAL = "VALUE_IN_INTERVAL"
    VALUE_OUTSIDE_INTERVAL = "VALUE_OUTSIDE_INTERVAL"
    INTERVALS_OVERLAP = "INTERVALS_OVERLAP"
    INTERVALS_DISJOINT = "INTERVALS_DISJOINT"

    # Set comparisons
    VALUE_IN_SET = "VALUE_IN_SET"
    VALUE_IN_SET_INCOMPLETE = "VALUE_IN_SET_INCOMPLETE"  # 30 ∈ {0,30} mais manque 0
    VALUE_NOT_IN_SET = "VALUE_NOT_IN_SET"
    SETS_EQUAL = "SETS_EQUAL"
    SET_SUBSET = "SET_SUBSET"
    SETS_OVERLAP = "SETS_OVERLAP"
    SETS_DISJOINT = "SETS_DISJOINT"

    # Inequality comparisons
    SATISFIES_INEQUALITY = "SATISFIES_INEQUALITY"
    VIOLATES_INEQUALITY = "VIOLATES_INEQUALITY"

    # Boolean comparisons
    BOOLEAN_MATCH = "BOOLEAN_MATCH"
    BOOLEAN_MISMATCH = "BOOLEAN_MISMATCH"

    # Version comparisons
    VERSION_MATCH = "VERSION_MATCH"
    VERSION_MISMATCH = "VERSION_MISMATCH"
    VERSION_COMPATIBLE = "VERSION_COMPATIBLE"  # Supérieur mais compatible
    VERSION_INCOMPATIBLE = "VERSION_INCOMPATIBLE"

    # Scope issues
    SCOPE_MISMATCH = "SCOPE_MISMATCH"
    SCOPE_MISSING = "SCOPE_MISSING"  # Vérité indexée, scope non fourni
    SCOPE_PARTIAL = "SCOPE_PARTIAL"  # Scope partiellement spécifié

    # Property issues
    PROPERTY_MISMATCH = "PROPERTY_MISMATCH"
    PROPERTY_UNKNOWN = "PROPERTY_UNKNOWN"  # claim_key None des deux côtés

    # Value issues
    NO_COMPARABLE_VALUE = "NO_COMPARABLE_VALUE"
    INCOMPATIBLE_TYPES = "INCOMPATIBLE_TYPES"
    UNIT_MISMATCH = "UNIT_MISMATCH"

    # Multi-claim issues
    CONFLICTING_EVIDENCE = "CONFLICTING_EVIDENCE"  # Claims se contredisent
    LOW_AUTHORITY_ONLY = "LOW_AUTHORITY_ONLY"  # Que des sources LOW authority
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"

    # Fallback
    LLM_CLASSIFICATION = "LLM_CLASSIFICATION"  # Fallback au LLM
    UNKNOWN_REASON = "UNKNOWN_REASON"


# Templates de messages localisés
REASON_TEMPLATES: Dict[str, Dict[str, str]] = {
    "fr": {
        ReasonCode.EXACT_MATCH: "Valeur identique: {value}",
        ReasonCode.EQUIVALENT_MATCH: "Valeurs équivalentes: {assertion_value} ≈ {claim_value}",

        ReasonCode.VALUE_IN_INTERVAL: "Valeur {value} dans l'intervalle [{low}, {high}]",
        ReasonCode.VALUE_OUTSIDE_INTERVAL: "Valeur {value} hors de l'intervalle [{low}, {high}]",
        ReasonCode.INTERVALS_OVERLAP: "Intervalles se chevauchent: [{a_low}, {a_high}] ∩ [{c_low}, {c_high}]",
        ReasonCode.INTERVALS_DISJOINT: "Intervalles disjoints: [{a_low}, {a_high}] et [{c_low}, {c_high}]",

        ReasonCode.VALUE_IN_SET: "Valeur {value} présente dans {set_values}",
        ReasonCode.VALUE_IN_SET_INCOMPLETE: "Valeur {value} valide mais manque {missing}",
        ReasonCode.VALUE_NOT_IN_SET: "Valeur {value} absente de {set_values}",
        ReasonCode.SETS_EQUAL: "Ensembles identiques: {set_values}",
        ReasonCode.SET_SUBSET: "Assertion est un sous-ensemble: {assertion_set} ⊂ {claim_set}",
        ReasonCode.SETS_OVERLAP: "Ensembles se chevauchent: {common} en commun",
        ReasonCode.SETS_DISJOINT: "Ensembles disjoints: {assertion_set} et {claim_set}",

        ReasonCode.SATISFIES_INEQUALITY: "Valeur {value} satisfait {operator} {bound}",
        ReasonCode.VIOLATES_INEQUALITY: "Valeur {value} viole {operator} {bound}",

        ReasonCode.BOOLEAN_MATCH: "Valeurs booléennes identiques: {value}",
        ReasonCode.BOOLEAN_MISMATCH: "Valeurs booléennes opposées: {assertion} vs {claim}",

        ReasonCode.VERSION_MATCH: "Versions identiques: {version}",
        ReasonCode.VERSION_MISMATCH: "Versions différentes: {assertion_version} vs {claim_version}",
        ReasonCode.VERSION_COMPATIBLE: "Version {assertion_version} compatible avec {claim_version}",
        ReasonCode.VERSION_INCOMPATIBLE: "Version {assertion_version} incompatible avec {claim_version}",

        ReasonCode.SCOPE_MISMATCH: "Contextes différents: {assertion_scope} vs {claim_scope}",
        ReasonCode.SCOPE_MISSING: "Vérité dépend du contexte ({scope_key}) non spécifié",
        ReasonCode.SCOPE_PARTIAL: "Contexte partiellement spécifié: manque {missing_scope}",

        ReasonCode.PROPERTY_MISMATCH: "Propriétés différentes: {assertion_prop} vs {claim_prop}",
        ReasonCode.PROPERTY_UNKNOWN: "Propriétés non canonisées: impossible de comparer strictement",

        ReasonCode.NO_COMPARABLE_VALUE: "Pas de valeur comparable extraite",
        ReasonCode.INCOMPATIBLE_TYPES: "Types incompatibles: {assertion_type} vs {claim_type}",
        ReasonCode.UNIT_MISMATCH: "Unités différentes: {assertion_unit} vs {claim_unit}",

        ReasonCode.CONFLICTING_EVIDENCE: "Claims de même autorité se contredisent",
        ReasonCode.LOW_AUTHORITY_ONLY: "Seules des sources de faible autorité disponibles",
        ReasonCode.INSUFFICIENT_EVIDENCE: "Preuves insuffisantes pour conclure",

        ReasonCode.LLM_CLASSIFICATION: "Classification par analyse sémantique (LLM)",
        ReasonCode.UNKNOWN_REASON: "Raison inconnue",
    },
    "en": {
        ReasonCode.EXACT_MATCH: "Exact match: {value}",
        ReasonCode.EQUIVALENT_MATCH: "Equivalent values: {assertion_value} ≈ {claim_value}",

        ReasonCode.VALUE_IN_INTERVAL: "Value {value} within interval [{low}, {high}]",
        ReasonCode.VALUE_OUTSIDE_INTERVAL: "Value {value} outside interval [{low}, {high}]",
        ReasonCode.INTERVALS_OVERLAP: "Intervals overlap: [{a_low}, {a_high}] ∩ [{c_low}, {c_high}]",
        ReasonCode.INTERVALS_DISJOINT: "Disjoint intervals: [{a_low}, {a_high}] and [{c_low}, {c_high}]",

        ReasonCode.VALUE_IN_SET: "Value {value} present in {set_values}",
        ReasonCode.VALUE_IN_SET_INCOMPLETE: "Value {value} valid but missing {missing}",
        ReasonCode.VALUE_NOT_IN_SET: "Value {value} not in {set_values}",
        ReasonCode.SETS_EQUAL: "Equal sets: {set_values}",
        ReasonCode.SET_SUBSET: "Assertion is a subset: {assertion_set} ⊂ {claim_set}",
        ReasonCode.SETS_OVERLAP: "Sets overlap: {common} in common",
        ReasonCode.SETS_DISJOINT: "Disjoint sets: {assertion_set} and {claim_set}",

        ReasonCode.SATISFIES_INEQUALITY: "Value {value} satisfies {operator} {bound}",
        ReasonCode.VIOLATES_INEQUALITY: "Value {value} violates {operator} {bound}",

        ReasonCode.BOOLEAN_MATCH: "Matching boolean values: {value}",
        ReasonCode.BOOLEAN_MISMATCH: "Opposite boolean values: {assertion} vs {claim}",

        ReasonCode.VERSION_MATCH: "Matching versions: {version}",
        ReasonCode.VERSION_MISMATCH: "Different versions: {assertion_version} vs {claim_version}",
        ReasonCode.VERSION_COMPATIBLE: "Version {assertion_version} compatible with {claim_version}",
        ReasonCode.VERSION_INCOMPATIBLE: "Version {assertion_version} incompatible with {claim_version}",

        ReasonCode.SCOPE_MISMATCH: "Different contexts: {assertion_scope} vs {claim_scope}",
        ReasonCode.SCOPE_MISSING: "Truth depends on unspecified context ({scope_key})",
        ReasonCode.SCOPE_PARTIAL: "Partially specified context: missing {missing_scope}",

        ReasonCode.PROPERTY_MISMATCH: "Different properties: {assertion_prop} vs {claim_prop}",
        ReasonCode.PROPERTY_UNKNOWN: "Non-canonized properties: cannot compare strictly",

        ReasonCode.NO_COMPARABLE_VALUE: "No comparable value extracted",
        ReasonCode.INCOMPATIBLE_TYPES: "Incompatible types: {assertion_type} vs {claim_type}",
        ReasonCode.UNIT_MISMATCH: "Different units: {assertion_unit} vs {claim_unit}",

        ReasonCode.CONFLICTING_EVIDENCE: "Same-authority claims contradict each other",
        ReasonCode.LOW_AUTHORITY_ONLY: "Only low-authority sources available",
        ReasonCode.INSUFFICIENT_EVIDENCE: "Insufficient evidence to conclude",

        ReasonCode.LLM_CLASSIFICATION: "Classification by semantic analysis (LLM)",
        ReasonCode.UNKNOWN_REASON: "Unknown reason",
    }
}


def get_reason_message(
    reason_code: ReasonCode,
    details: Dict[str, Any],
    locale: str = "fr"
) -> str:
    """
    Génère un message lisible à partir d'un ReasonCode et ses détails.

    Args:
        reason_code: Le code de raison
        details: Dictionnaire des paramètres pour le template
        locale: Langue du message ("fr" ou "en")

    Returns:
        Message formaté
    """
    templates = REASON_TEMPLATES.get(locale, REASON_TEMPLATES["fr"])
    template = templates.get(reason_code, f"Code: {reason_code.value}")

    try:
        return template.format(**details)
    except KeyError as e:
        # Fallback si paramètre manquant
        return f"{reason_code.value}: {details}"
