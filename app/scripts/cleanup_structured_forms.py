#!/usr/bin/env python3
"""
Assainissement rétroactif des structured_forms bruiteux dans Neo4j.

Valide chaque structured_form_json existant contre les règles actuelles :
1. Prédicat canonique (CANONICAL_PREDICATES + normalisation)
2. Sujet valide (is_valid_entity_name)
3. Objet valide (is_valid_entity_name)

Actions :
- FIXABLE : prédicat normalisable → corrigé in-place
- INVALID : sujet/objet invalide ou prédicat non-mappable → structured_form_json supprimé
- VALID : rien à faire

Usage (dans le conteneur Docker) :
    python scripts/cleanup_structured_forms.py --dry-run --tenant default
    python scripts/cleanup_structured_forms.py --execute --tenant default
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from collections import defaultdict
from typing import Dict, List, Optional, Tuple

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constantes dupliquées depuis claim_extractor.py (évite import YAML lourd)
# ---------------------------------------------------------------------------

CANONICAL_PREDICATES = frozenset({
    "USES", "REQUIRES", "BASED_ON", "SUPPORTS", "ENABLES",
    "PROVIDES", "EXTENDS", "REPLACES", "PART_OF",
    "INTEGRATED_IN", "COMPATIBLE_WITH", "CONFIGURES",
})

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


def normalize_predicate(raw_predicate: str) -> Optional[str]:
    """Normalise un prédicat vers la whitelist canonique."""
    pred = raw_predicate.strip().upper().replace(" ", "_")
    if pred in CANONICAL_PREDICATES:
        return pred
    mapped = PREDICATE_NORMALIZATION_MAP.get(pred)
    if mapped:
        return mapped
    return None


# ---------------------------------------------------------------------------
# Import léger : is_valid_entity_name (pydantic seulement, pas de deps lourdes)
# ---------------------------------------------------------------------------

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
from knowbase.claimfirst.models.entity import is_valid_entity_name  # noqa: E402


# ---------------------------------------------------------------------------
# Neo4j
# ---------------------------------------------------------------------------

def get_neo4j_driver():
    """Crée une connexion Neo4j."""
    from neo4j import GraphDatabase

    neo4j_uri = os.getenv("NEO4J_URI", "bolt://neo4j:7687")
    neo4j_user = os.getenv("NEO4J_USER", "neo4j")
    neo4j_password = os.getenv("NEO4J_PASSWORD", "graphiti_neo4j_pass")
    return GraphDatabase.driver(neo4j_uri, auth=(neo4j_user, neo4j_password))


def load_claims_with_sf(session, tenant_id: str) -> List[dict]:
    """Charge tous les claims avec structured_form_json depuis Neo4j."""
    result = session.run(
        """
        MATCH (c:Claim {tenant_id: $tenant_id})
        WHERE c.structured_form_json IS NOT NULL
        RETURN c.claim_id AS claim_id,
               c.structured_form_json AS sf_json
        ORDER BY c.claim_id
        """,
        tenant_id=tenant_id,
    )
    claims = []
    for record in result:
        try:
            sf = json.loads(record["sf_json"])
        except (json.JSONDecodeError, TypeError):
            claims.append({
                "claim_id": record["claim_id"],
                "sf": None,
                "raw_json": record["sf_json"],
                "parse_error": True,
            })
            continue
        claims.append({
            "claim_id": record["claim_id"],
            "sf": sf,
            "raw_json": record["sf_json"],
            "parse_error": False,
        })
    return claims


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

def validate_claim_sf(sf: dict) -> Tuple[str, List[str], Optional[dict]]:
    """
    Valide un structured_form.

    Returns:
        (category, reasons, fixed_sf)
        - category: "valid", "fixable", "invalid"
        - reasons: liste de raisons de rejet
        - fixed_sf: le SF corrigé si fixable, sinon None
    """
    subject = sf.get("subject", "")
    predicate = sf.get("predicate", "")
    obj = sf.get("object", "")

    reasons = []
    fixed_predicate = None

    # --- Valider le prédicat ---
    normalized_pred = normalize_predicate(predicate)
    if normalized_pred is None:
        reasons.append(f"non-canonical predicate: {predicate}")
    elif normalized_pred != predicate:
        fixed_predicate = normalized_pred

    # --- Valider le sujet ---
    if not subject or not is_valid_entity_name(subject):
        reasons.append(f"invalid subject: {subject!r}")

    # --- Valider l'objet ---
    if not obj or not is_valid_entity_name(obj):
        reasons.append(f"invalid object: {obj!r}")

    # --- Catégoriser ---
    if reasons:
        return "invalid", reasons, None

    if fixed_predicate:
        fixed_sf = {**sf, "predicate": fixed_predicate}
        return "fixable", [f"predicate normalized: {predicate} → {fixed_predicate}"], fixed_sf

    return "valid", [], None


# ---------------------------------------------------------------------------
# Actions Neo4j
# ---------------------------------------------------------------------------

def nullify_sf(session, claim_id: str, tenant_id: str) -> bool:
    """Supprime le structured_form_json d'un claim."""
    result = session.run(
        """
        MATCH (c:Claim {claim_id: $claim_id, tenant_id: $tenant_id})
        REMOVE c.structured_form_json
        RETURN c.claim_id AS updated
        """,
        claim_id=claim_id,
        tenant_id=tenant_id,
    )
    return result.single() is not None


def fix_sf(session, claim_id: str, tenant_id: str, new_sf: dict) -> bool:
    """Met à jour le structured_form_json d'un claim."""
    result = session.run(
        """
        MATCH (c:Claim {claim_id: $claim_id, tenant_id: $tenant_id})
        SET c.structured_form_json = $sf_json
        RETURN c.claim_id AS updated
        """,
        claim_id=claim_id,
        tenant_id=tenant_id,
        sf_json=json.dumps(new_sf, ensure_ascii=False),
    )
    return result.single() is not None


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Assainissement rétroactif des structured_forms bruiteux"
    )
    parser.add_argument(
        "--dry-run", action="store_true", default=True,
        help="Afficher sans modifier (défaut)",
    )
    parser.add_argument(
        "--execute", action="store_true",
        help="Exécuter les modifications",
    )
    parser.add_argument(
        "--tenant", default="default",
        help="Tenant ID (default: 'default')",
    )
    args = parser.parse_args()

    if args.execute:
        args.dry_run = False

    mode = "DRY-RUN" if args.dry_run else "EXECUTE"
    logger.info(f"=== Assainissement Structured Forms [{mode}] ===")
    logger.info(f"Tenant: {args.tenant}")

    driver = get_neo4j_driver()
    try:
        with driver.session() as session:
            # --- Chargement ---
            logger.info("Chargement des claims avec structured_form...")
            claims = load_claims_with_sf(session, args.tenant)
            logger.info(f"  → {len(claims)} claims avec SF chargés")

            if not claims:
                logger.info("Aucun claim avec SF trouvé. Fin.")
                return

            # --- Compteurs ---
            stats = {
                "total": len(claims),
                "valid": 0,
                "fixable": 0,
                "invalid": 0,
                "parse_error": 0,
                "fixed_ok": 0,
                "nullified_ok": 0,
            }

            # Détails des rejets pour le rapport
            invalid_subjects: Dict[str, int] = defaultdict(int)
            invalid_objects: Dict[str, int] = defaultdict(int)
            invalid_predicates: Dict[str, int] = defaultdict(int)
            fix_details: Dict[str, int] = defaultdict(int)

            # --- Validation ---
            to_fix: List[Tuple[str, dict]] = []       # (claim_id, fixed_sf)
            to_nullify: List[Tuple[str, List[str]]] = []  # (claim_id, reasons)

            for claim in claims:
                if claim["parse_error"]:
                    stats["parse_error"] += 1
                    to_nullify.append((claim["claim_id"], ["JSON parse error"]))
                    continue

                sf = claim["sf"]
                category, reasons, fixed_sf = validate_claim_sf(sf)

                if category == "valid":
                    stats["valid"] += 1

                elif category == "fixable":
                    stats["fixable"] += 1
                    to_fix.append((claim["claim_id"], fixed_sf))
                    for r in reasons:
                        fix_details[r] += 1

                elif category == "invalid":
                    stats["invalid"] += 1
                    to_nullify.append((claim["claim_id"], reasons))
                    for r in reasons:
                        if r.startswith("invalid subject:"):
                            val = r.split(": ", 1)[1]
                            invalid_subjects[val] += 1
                        elif r.startswith("invalid object:"):
                            val = r.split(": ", 1)[1]
                            invalid_objects[val] += 1
                        elif r.startswith("non-canonical predicate:"):
                            val = r.split(": ", 1)[1]
                            invalid_predicates[val] += 1

            # --- Exécution ---
            if not args.dry_run:
                logger.info("Application des corrections...")

                for claim_id, fixed_sf in to_fix:
                    ok = fix_sf(session, claim_id, args.tenant, fixed_sf)
                    if ok:
                        stats["fixed_ok"] += 1

                for claim_id, reasons in to_nullify:
                    ok = nullify_sf(session, claim_id, args.tenant)
                    if ok:
                        stats["nullified_ok"] += 1

                logger.info(
                    f"  → {stats['fixed_ok']} fixés, {stats['nullified_ok']} nullifiés"
                )

            # --- Rapport ---
            print()
            print("=" * 60)
            print(f"  RÉSUMÉ ASSAINISSEMENT STRUCTURED_FORMS [{mode}]")
            print("=" * 60)
            print(f"Total claims avec SF  : {stats['total']}")
            print(f"  - Valides           : {stats['valid']}")
            print(f"  - Fixables (predic) : {stats['fixable']}")
            print(f"  - Invalides         : {stats['invalid']}")
            print(f"  - Erreurs JSON      : {stats['parse_error']}")

            if not args.dry_run:
                print(f"  → Fixés appliqués   : {stats['fixed_ok']}")
                print(f"  → Nullifiés         : {stats['nullified_ok']}")

            remaining = stats["valid"] + stats["fixable"]
            print(f"\nCouverture SF après   : {remaining} / {stats['total']} "
                  f"({100 * remaining / stats['total']:.1f}%)")

            if stats["fixable"] > 0:
                print(f"\n--- Corrections de prédicats ({stats['fixable']}) ---")
                for detail, count in sorted(fix_details.items(), key=lambda x: -x[1]):
                    print(f"  {detail} : {count}")

            total_nullify = stats["invalid"] + stats["parse_error"]
            if total_nullify > 0:
                print(f"\n--- Raisons de nullification ({total_nullify} claims) ---")

                if invalid_predicates:
                    print(f"\n  Prédicats non-canoniques ({sum(invalid_predicates.values())}) :")
                    for pred, count in sorted(invalid_predicates.items(), key=lambda x: -x[1]):
                        print(f"    {pred} : {count}")

                if invalid_subjects:
                    print(f"\n  Sujets invalides ({sum(invalid_subjects.values())}) :")
                    for subj, count in sorted(invalid_subjects.items(), key=lambda x: -x[1])[:20]:
                        print(f"    {subj} : {count}")

                if invalid_objects:
                    print(f"\n  Objets invalides ({sum(invalid_objects.values())}) :")
                    for obj, count in sorted(invalid_objects.items(), key=lambda x: -x[1])[:20]:
                        print(f"    {obj} : {count}")

            print("=" * 60)

    finally:
        driver.close()


if __name__ == "__main__":
    main()
