"""
Constantes partagees du pipeline ClaimFirst.

Centralise les definitions utilisees par plusieurs modules pour eviter
les doublons et les divergences silencieuses.
"""

from __future__ import annotations

import logging
from typing import Dict, FrozenSet, Optional, Tuple

logger = logging.getLogger(__name__)

# ── Predicats canoniques (whitelist) ──────────────────────────────────────────
# Les seuls predicats autorises dans le KG. Tout predicat LLM non-canonique
# est normalise via PREDICATE_NORMALIZATION_MAP ou rejete.
#
# Ceci est le CORE set (SAP/enterprise/regulatory). Les Domain Packs peuvent
# AJOUTER des predicats specifiques via get_canonical_predicates().

CANONICAL_PREDICATES = frozenset({
    "USES", "REQUIRES", "BASED_ON", "SUPPORTS", "ENABLES",
    "PROVIDES", "EXTENDS", "REPLACES", "PART_OF",
    "INTEGRATED_IN", "COMPATIBLE_WITH", "CONFIGURES",
})

# Descriptions core pour injection dans le prompt LLM (Layer A)
CORE_PREDICATE_DESCRIPTIONS: Dict[str, str] = {
    "USES": "X explicitly uses Y as a tool, technology, or component",
    "REQUIRES": "X needs Y to function (includes 'depends on')",
    "BASED_ON": "X is built on, derived from, or runs on Y",
    "SUPPORTS": "X supports or is designed for Y",
    "ENABLES": "X makes possible a specific named capability Y",
    "PROVIDES": "X provides, delivers, or offers Y",
    "EXTENDS": "X extends or adds functionality to Y",
    "REPLACES": "X replaces, supersedes, or succeeds Y",
    "PART_OF": "X is a module, component, or feature of Y",
    "INTEGRATED_IN": "X is integrated or embedded in Y",
    "COMPATIBLE_WITH": "X is compatible with or works alongside Y",
    "CONFIGURES": "X configures, manages, or controls Y",
}

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
    """Normalise un predicat vers la whitelist canonique (CORE uniquement).

    Pour la version domain-aware, utiliser get_effective_predicates(tenant_id)
    puis appeler l'instance method de ClaimExtractor.

    Returns:
        Le predicat canonique, ou None si non-mappable.
    """
    upper = raw_predicate.strip().upper().replace(" ", "_")
    if upper in CANONICAL_PREDICATES:
        return upper
    return PREDICATE_NORMALIZATION_MAP.get(upper)


# ── Resolution domain-aware des predicats effectifs ──────────────────────────
# Merge le core + les predicats apportes par les Domain Packs actifs du tenant.

def get_effective_predicates(
    tenant_id: str,
) -> Tuple[FrozenSet[str], Dict[str, str], Dict[str, str]]:
    """Merge les predicats core avec ceux des Domain Packs actifs pour un tenant.

    Args:
        tenant_id: Identifiant du tenant (ex: "default")

    Returns:
        (predicates_set, descriptions_dict, normalization_map)
        - predicates_set : frozenset de noms de predicats autorises
        - descriptions_dict : nom -> description (pour prompt LLM)
        - normalization_map : alias -> canonique (pour post-processing)
    """
    predicates = set(CANONICAL_PREDICATES)
    descriptions = dict(CORE_PREDICATE_DESCRIPTIONS)
    norm_map = dict(PREDICATE_NORMALIZATION_MAP)

    try:
        from knowbase.domain_packs.registry import get_pack_registry

        registry = get_pack_registry()
        active_packs = registry.get_active_packs(tenant_id)
    except Exception as e:
        logger.warning(
            f"[constants] Could not load active domain packs for {tenant_id}: {e} — "
            f"using core predicates only"
        )
        return frozenset(predicates), descriptions, norm_map

    for pack in active_packs:
        try:
            pack_preds = pack.get_canonical_predicates()
            if pack_preds:
                predicates.update(pack_preds.keys())
                descriptions.update(pack_preds)
                logger.info(
                    f"[constants] Merged {len(pack_preds)} predicates from pack '{pack.name}': "
                    f"{sorted(pack_preds.keys())}"
                )
        except Exception as e:
            logger.warning(
                f"[constants] Pack '{pack.name}' get_canonical_predicates error: {e}"
            )

        try:
            pack_norm = pack.get_predicate_normalization_map()
            if pack_norm:
                # Conflits : les alias du domain pack ecrasent le core
                # (le pack est plus specifique)
                norm_map.update(pack_norm)
        except Exception as e:
            logger.warning(
                f"[constants] Pack '{pack.name}' get_predicate_normalization_map error: {e}"
            )

    return frozenset(predicates), descriptions, norm_map
