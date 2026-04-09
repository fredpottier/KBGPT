"""
Constantes partagees du pipeline ClaimFirst.

Centralise les definitions utilisees par plusieurs modules pour eviter
les doublons et les divergences silencieuses.
"""

from __future__ import annotations

from typing import Optional

# ── Predicats canoniques (whitelist) ──────────────────────────────────────────
# Les seuls predicats autorises dans le KG. Tout predicat LLM non-canonique
# est normalise via PREDICATE_NORMALIZATION_MAP ou rejete.

CANONICAL_PREDICATES = frozenset({
    "USES", "REQUIRES", "BASED_ON", "SUPPORTS", "ENABLES",
    "PROVIDES", "EXTENDS", "REPLACES", "PART_OF",
    "INTEGRATED_IN", "COMPATIBLE_WITH", "CONFIGURES",
})

# ── Normalisation des predicats (Layer B) ─────────────────────────────────────
# Le prompt durci (Layer A) capture 90%+, ce mapping rattrape le reste.

PREDICATE_NORMALIZATION_MAP = {
    # → USES
    "USE": "USES", "CAN_USE": "USES", "LEVERAGES": "USES",
    "ADOPTS": "USES", "USED_FOR": "USES", "ARE_USED_TO": "USES",
    "CAN_BE_USED_VIA": "USES", "ACHIEVED_VIA": "USES",
    # → REQUIRES
    "DEPENDS_ON": "REQUIRES", "RELIES_ON": "REQUIRES", "NEEDS": "REQUIRES",
    "COMPLIES_WITH": "REQUIRES",
    # → BASED_ON
    "IS_BASED_ON": "BASED_ON", "RUNS_ON": "BASED_ON",
    "RUNS_IN": "BASED_ON", "HOSTED_IN": "BASED_ON",
    # → SUPPORTS
    "SUPPORTED_BY": "SUPPORTS",
    # → ENABLES
    "ACTIVATES": "ENABLES", "ALLOW": "ENABLES", "ALLOWS": "ENABLES",
    "ENABLING": "ENABLES",
    # → PROVIDES
    "OFFERS": "PROVIDES", "DELIVERS": "PROVIDES", "BRINGS": "PROVIDES",
    "IS_OFFERED_BY": "PROVIDES", "OFFERED_BY": "PROVIDES",
    "IS_PROVIDED_BY": "PROVIDES",
    # → INTEGRATED_IN
    "IS_INTEGRATED_IN": "INTEGRATED_IN", "INTEGRATES": "INTEGRATED_IN",
    "INTEGRATED_WITH": "INTEGRATED_IN", "INTEGRATES_WITH": "INTEGRATED_IN",
    "EMBEDDED_IN": "INTEGRATED_IN", "INSTALLED_ON": "INTEGRATED_IN",
    # → PART_OF
    "IS_PART_OF": "PART_OF", "IS_A_MODULE_IN": "PART_OF",
    "IS_A_COMPONENT_OF": "PART_OF", "INCLUDED_IN": "PART_OF",
    "IS_INCLUDED_IN": "PART_OF", "IS_A_FEATURE_IN": "PART_OF",
    "IS_A_FEATURE_OF": "PART_OF", "ARE_FEATURES_OF": "PART_OF",
    "IS_A_NEW_FEATURE_IN": "PART_OF", "FOUND_IN": "PART_OF",
    # → REPLACES
    "SUPERSEDES": "REPLACES", "MIGRATES": "REPLACES",
    "CAN_BE_MIGRATED_TO": "REPLACES", "CONVERTED_TO": "REPLACES",
    # → EXTENDS
    "IS_AN_ADD_ON_FOR": "EXTENDS",
    # → COMPATIBLE_WITH
    "CO-DEPLOYED_WITH": "COMPATIBLE_WITH", "CONNECTS_WITH": "COMPATIBLE_WITH",
    # → CONFIGURES
    "MANAGED_BY": "CONFIGURES", "MANAGES": "CONFIGURES",
}

# ── Priorite des predicats (pour ranking cross-doc) ──────────────────────────
# Plus le score est haut, plus le predicat est structurant

PREDICATE_PRIORITY = {
    "REQUIRES": 4, "REPLACES": 4, "PART_OF": 4, "INTEGRATED_IN": 4,
    "BASED_ON": 3, "EXTENDS": 3, "COMPATIBLE_WITH": 3,
    "USES": 2, "SUPPORTS": 2, "ENABLES": 2,
    "PROVIDES": 1, "CONFIGURES": 1,
}


def normalize_predicate(raw_predicate: str) -> Optional[str]:
    """Normalise un predicat vers la whitelist canonique.

    Returns:
        Le predicat canonique, ou None si non-mappable.
    """
    upper = raw_predicate.strip().upper().replace(" ", "_")
    if upper in CANONICAL_PREDICATES:
        return upper
    return PREDICATE_NORMALIZATION_MAP.get(upper)
