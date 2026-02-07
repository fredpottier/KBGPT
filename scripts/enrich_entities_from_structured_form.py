#!/usr/bin/env python3
"""
Enrichissement rétroactif : créer des entities depuis structured_form.

Cible les claims orphelines (sans relation ABOUT vers une Entity)
qui possèdent un structured_form avec subject/object exploitables.

Domain-agnostic (INV-25).

Usage (dans le conteneur Docker) :
    python scripts/enrich_entities_from_structured_form.py [--dry-run]
    python scripts/enrich_entities_from_structured_form.py --execute
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import uuid
from collections import defaultdict
from typing import Dict, List, Optional, Set, Tuple

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)


def get_neo4j_driver():
    """Crée une connexion Neo4j."""
    from neo4j import GraphDatabase

    neo4j_uri = os.getenv("NEO4J_URI", "bolt://neo4j:7687")
    neo4j_user = os.getenv("NEO4J_USER", "neo4j")
    neo4j_password = os.getenv("NEO4J_PASSWORD", "graphiti_neo4j_pass")
    return GraphDatabase.driver(neo4j_uri, auth=(neo4j_user, neo4j_password))


def load_orphan_claims_with_sf(session, tenant_id: str) -> List[dict]:
    """
    Charge les claims qui ont un structured_form mais PAS de relation ABOUT.
    """
    result = session.run(
        """
        MATCH (c:Claim {tenant_id: $tenant_id})
        WHERE c.structured_form_json IS NOT NULL
          AND NOT EXISTS { MATCH (c)-[:ABOUT]->(:Entity) }
        RETURN c.claim_id AS claim_id,
               c.structured_form_json AS sf_json,
               c.doc_id AS doc_id
        """,
        tenant_id=tenant_id,
    )
    return [dict(record) for record in result]


def load_existing_entities(session, tenant_id: str) -> Dict[str, str]:
    """
    Charge les entities existantes (normalized_name → entity_id).
    """
    result = session.run(
        """
        MATCH (e:Entity {tenant_id: $tenant_id})
        RETURN e.entity_id AS entity_id, e.normalized_name AS normalized_name
        """,
        tenant_id=tenant_id,
    )
    return {record["normalized_name"]: record["entity_id"] for record in result}


def extract_entities_from_sf(
    claims: List[dict],
) -> List[Tuple[str, str, str]]:
    """
    Extrait des candidats entity depuis les structured_form des claims.

    Returns:
        Liste de (claim_id, entity_name_normalized, entity_name_original)
    """
    from knowbase.claimfirst.models.entity import (
        Entity,
        is_valid_entity_name,
        strip_version_qualifier,
    )

    candidates = []

    for claim in claims:
        sf_json = claim.get("sf_json")
        if not sf_json:
            continue

        try:
            sf = json.loads(sf_json)
        except (json.JSONDecodeError, TypeError):
            continue

        for field in ("subject", "object"):
            value = sf.get(field)
            if not value or not isinstance(value, str):
                continue

            name = value.strip()
            if len(name) < 2:
                continue

            # Version stripping
            base_name, _ = strip_version_qualifier(name)

            # Validation
            if not is_valid_entity_name(base_name):
                continue

            normalized = Entity.normalize(base_name)
            candidates.append((claim["claim_id"], normalized, base_name))

    return candidates


def create_entities_and_links(
    session,
    candidates: List[Tuple[str, str, str]],
    existing_entities: Dict[str, str],
    tenant_id: str,
    batch_size: int = 200,
) -> Tuple[int, int]:
    """
    Crée les entities manquantes et les relations ABOUT.

    Returns:
        Tuple (entities_created, links_created)
    """
    entities_created = 0
    links_created = 0

    # Grouper par normalized_name pour éviter les doublons
    by_norm: Dict[str, Tuple[str, Set[str]]] = {}  # norm → (best_name, {claim_ids})
    for claim_id, normalized, original in candidates:
        if normalized not in by_norm:
            by_norm[normalized] = (original, set())
        by_norm[normalized][1].add(claim_id)

    # Préparer les opérations
    ops = []  # (entity_id, normalized_name, display_name, claim_ids, is_new)
    for normalized, (display_name, claim_ids) in by_norm.items():
        if normalized in existing_entities:
            entity_id = existing_entities[normalized]
            ops.append((entity_id, normalized, display_name, list(claim_ids), False))
        else:
            entity_id = f"entity_{uuid.uuid4().hex[:12]}"
            ops.append((entity_id, normalized, display_name, list(claim_ids), True))
            existing_entities[normalized] = entity_id  # Pour les suivants

    # Exécuter par batch
    for i in range(0, len(ops), batch_size):
        batch = ops[i:i + batch_size]

        for entity_id, normalized, display_name, claim_ids, is_new in batch:
            if is_new:
                # Créer l'entity
                session.run(
                    """
                    CREATE (e:Entity {
                        entity_id: $entity_id,
                        tenant_id: $tenant_id,
                        name: $name,
                        normalized_name: $normalized,
                        entity_type: 'concept',
                        mention_count: $mention_count
                    })
                    """,
                    entity_id=entity_id,
                    tenant_id=tenant_id,
                    name=display_name,
                    normalized=normalized,
                    mention_count=len(claim_ids),
                )
                entities_created += 1

            # Créer les relations ABOUT
            for claim_id in claim_ids:
                session.run(
                    """
                    MATCH (c:Claim {claim_id: $claim_id})
                    MATCH (e:Entity {entity_id: $entity_id})
                    MERGE (c)-[:ABOUT]->(e)
                    """,
                    claim_id=claim_id,
                    entity_id=entity_id,
                )
                links_created += 1

        logger.info(f"  Batch {i // batch_size + 1}: "
                     f"{sum(1 for _, _, _, _, n in batch if n)} entities, "
                     f"{sum(len(c) for _, _, _, c, _ in batch)} liens")

    return entities_created, links_created


def main():
    parser = argparse.ArgumentParser(
        description="Enrichir les entities depuis structured_form des claims orphelines"
    )
    parser.add_argument("--dry-run", action="store_true", default=True,
                        help="Afficher sans modifier (défaut)")
    parser.add_argument("--execute", action="store_true",
                        help="Exécuter les modifications")
    parser.add_argument("--tenant", default="default",
                        help="Tenant ID (default: 'default')")
    args = parser.parse_args()

    if args.execute:
        args.dry_run = False

    driver = get_neo4j_driver()

    try:
        with driver.session() as session:
            # 1. Charger les claims orphelines avec SF
            logger.info(f"[OSMOSE] Chargement des claims orphelines (tenant={args.tenant})...")
            orphan_claims = load_orphan_claims_with_sf(session, args.tenant)
            logger.info(f"  → {len(orphan_claims)} claims orphelines avec structured_form")

            if not orphan_claims:
                logger.info("Aucune claim orpheline à enrichir.")
                return

            # 2. Charger les entities existantes
            logger.info("[OSMOSE] Chargement des entities existantes...")
            existing = load_existing_entities(session, args.tenant)
            logger.info(f"  → {len(existing)} entities existantes")

            # 3. Extraire les candidats depuis SF
            logger.info("[OSMOSE] Extraction entities depuis structured_form...")
            candidates = extract_entities_from_sf(orphan_claims)
            logger.info(f"  → {len(candidates)} candidats entity valides")

            # Stats
            unique_norms = {c[1] for c in candidates}
            new_entities = unique_norms - set(existing.keys())
            reuse_entities = unique_norms & set(existing.keys())
            unique_claims = {c[0] for c in candidates}

            logger.info(f"\n{'='*60}")
            logger.info("RÉSUMÉ ENRICHISSEMENT")
            logger.info(f"{'='*60}")
            logger.info(f"Claims orphelines traitées : {len(orphan_claims)}")
            logger.info(f"Claims enrichissables     : {len(unique_claims)}")
            logger.info(f"Entities à créer          : {len(new_entities)}")
            logger.info(f"Entities existantes liées : {len(reuse_entities)}")

            # Exemples
            if new_entities:
                logger.info(f"\nExemples d'entities à créer:")
                for n in sorted(new_entities)[:10]:
                    logger.info(f"  • {n}")
                if len(new_entities) > 10:
                    logger.info(f"  ... et {len(new_entities) - 10} autres")

            if args.dry_run:
                logger.info("\n[DRY-RUN] Aucune modification effectuée.")
                logger.info("    Utilisez --execute pour appliquer.")
                return

            # 4. Créer et lier
            logger.info(f"\n[OSMOSE] Création des entities et relations ABOUT...")
            created, linked = create_entities_and_links(
                session, candidates, existing, args.tenant
            )
            logger.info(f"  → {created} entities créées, {linked} relations ABOUT ajoutées")

            # 5. Vérification
            remaining = session.run(
                """
                MATCH (c:Claim {tenant_id: $tenant_id})
                WHERE NOT EXISTS { MATCH (c)-[:ABOUT]->(:Entity) }
                RETURN count(c) AS orphans
                """,
                tenant_id=args.tenant,
            ).single()["orphans"]
            logger.info(f"  → Claims encore orphelines : {remaining}")

            logger.info("\n[OSMOSE] Enrichissement terminé.")

    finally:
        driver.close()


if __name__ == "__main__":
    main()
