#!/usr/bin/env python3
"""
Canonicalisation rétroactive des entities dans Neo4j.

Fusionne les variantes d'entities existantes :
1. Version stripping : "S/4HANA 2023" → fusionne avec "S/4HANA"
2. Containment : "Product" ⊂ "Vendor Product" → canonical = "Vendor Product"
3. Annotation des hubs (entities avec >50 claims ABOUT)

Domain-agnostic (INV-25) : fonctionne pour tout domaine.

Usage (dans le conteneur Docker) :
    python scripts/canonicalize_existing_entities.py [--dry-run] [--tenant default]
    python scripts/canonicalize_existing_entities.py --execute
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
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


def load_all_entities(session, tenant_id: str) -> List[dict]:
    """Charge toutes les entities d'un tenant depuis Neo4j."""
    result = session.run(
        """
        MATCH (e:Entity {tenant_id: $tenant_id})
        OPTIONAL MATCH (e)<-[:ABOUT]-(c:Claim)
        WITH e, count(c) AS claim_count
        RETURN e.entity_id AS entity_id,
               e.name AS name,
               e.normalized_name AS normalized_name,
               e.aliases AS aliases,
               e.entity_type AS entity_type,
               claim_count
        ORDER BY e.name
        """,
        tenant_id=tenant_id,
    )
    return [dict(record) for record in result]


def find_version_groups(
    entities: List[dict],
) -> Dict[str, List[dict]]:
    """
    Identifie les groupes d'entities qui diffèrent par un suffixe version.

    Returns:
        Dict base_name_normalized → [entities_with_that_base]
    """
    from knowbase.claimfirst.models.entity import Entity, strip_version_qualifier

    groups: Dict[str, List[Tuple[dict, Optional[str]]]] = defaultdict(list)

    for e in entities:
        name = e["name"]
        base_name, version = strip_version_qualifier(name)
        base_normalized = Entity.normalize(base_name)
        groups[base_normalized].append((e, version))

    # Ne garder que les groupes avec des variantes versionnées
    merge_groups: Dict[str, List[dict]] = {}
    for base_norm, members in groups.items():
        if len(members) > 1:
            # Il y a plusieurs entities avec la même base
            merge_groups[base_norm] = [m[0] for m in members]
        elif len(members) == 1 and members[0][1] is not None:
            # Une seule entity mais avec un suffixe version → chercher la base
            if base_norm in groups and base_norm != Entity.normalize(members[0][0]["name"]):
                continue  # sera traité par le groupe existant
            # Entity seule avec version mais sans base → garder pour report
            merge_groups[base_norm] = [members[0][0]]

    return merge_groups


def find_containment_groups(
    entities: List[dict],
    min_short_len: int = 4,
) -> List[Tuple[dict, dict]]:
    """
    Identifie les paires containment : "Product" ⊂ "Vendor Product".

    Contraintes pour éviter les faux positifs :
    - Le nom court doit faire >= min_short_len caractères (évite "AI" → "Embedded AI")
    - Le court doit être un suffixe de mots du long (pas un sous-mot)
    - Ne garde que les paires uniques (1 seul parent par enfant)

    Returns:
        Liste de tuples (entity_contenue, entity_canonique)
    """
    from knowbase.claimfirst.models.entity import Entity

    # Index par normalized_name
    by_norm: Dict[str, dict] = {}
    for e in entities:
        norm = e.get("normalized_name") or Entity.normalize(e["name"])
        by_norm[norm] = e

    # Collecter tous les parents possibles par enfant
    parents_by_child: Dict[str, List[str]] = defaultdict(list)
    norms = sorted(by_norm.keys(), key=len)  # du plus court au plus long

    for i, short_norm in enumerate(norms):
        # Ignorer les noms trop courts (acronymes 2-3 lettres → trop ambigus)
        if len(short_norm) < min_short_len:
            continue

        for long_norm in norms[i + 1:]:
            # Le long ne doit pas avoir trop de mots de plus que le court
            words_long = long_norm.split()
            words_short = short_norm.split()
            extra_words = len(words_long) - len(words_short)
            if extra_words > 2 or extra_words < 1:
                continue

            # Le court doit être un suffixe de mots du long
            # Ex: "s4hana" is suffix of "sap s4hana"
            if words_long[-len(words_short):] == words_short:
                parents_by_child[short_norm].append(long_norm)

    # Ne garder que les enfants avec exactement 1 parent (évite ambiguïté)
    pairs: List[Tuple[dict, dict]] = []
    for child_norm, parent_norms in parents_by_child.items():
        if len(parent_norms) == 1:
            pairs.append((by_norm[child_norm], by_norm[parent_norms[0]]))
        else:
            logger.debug(
                f"  SKIP containment ambigu: '{child_norm}' → {len(parent_norms)} parents"
            )

    return pairs


def merge_entities_in_neo4j(
    session,
    source_entity_id: str,
    target_entity_id: str,
    tenant_id: str,
) -> dict:
    """
    Fusionne source_entity dans target_entity dans Neo4j.

    - Transfère les relations ABOUT de source vers target
    - Ajoute le nom de source comme alias de target
    - Supprime source_entity
    """
    result = session.run(
        """
        MATCH (source:Entity {entity_id: $source_id, tenant_id: $tenant_id})
        MATCH (target:Entity {entity_id: $target_id, tenant_id: $tenant_id})

        // Transférer les relations ABOUT vers target
        OPTIONAL MATCH (c:Claim)-[r:ABOUT]->(source)
        WITH source, target, collect(c) AS claims, collect(r) AS rels
        FOREACH (r IN rels | DELETE r)
        WITH source, target, claims
        UNWIND claims AS c
        MERGE (c)-[:ABOUT]->(target)

        WITH source, target
        // Ajouter le nom de source comme alias
        SET target.aliases = CASE
            WHEN target.aliases IS NULL THEN [source.name]
            WHEN NOT source.name IN target.aliases THEN target.aliases + source.name
            ELSE target.aliases
        END

        // Supprimer source
        WITH source, target
        DETACH DELETE source

        RETURN target.entity_id AS target_id, target.name AS target_name
        """,
        source_id=source_entity_id,
        target_id=target_entity_id,
        tenant_id=tenant_id,
    )
    record = result.single()
    return dict(record) if record else {}


def annotate_hubs(session, tenant_id: str, threshold: int = 50) -> int:
    """Annote les entities hub (>threshold claims ABOUT)."""
    result = session.run(
        """
        MATCH (e:Entity {tenant_id: $tenant_id})<-[:ABOUT]-(c:Claim)
        WITH e, count(c) AS degree
        WHERE degree > $threshold
        SET e.is_hub = true, e.hub_degree = degree
        RETURN count(e) AS hubs_annotated
        """,
        tenant_id=tenant_id,
        threshold=threshold,
    )
    record = result.single()
    return record["hubs_annotated"] if record else 0


def main():
    parser = argparse.ArgumentParser(
        description="Canonicalisation rétroactive des entities Neo4j"
    )
    parser.add_argument("--dry-run", action="store_true", default=True,
                        help="Afficher sans modifier (défaut)")
    parser.add_argument("--execute", action="store_true",
                        help="Exécuter les modifications")
    parser.add_argument("--tenant", default="default",
                        help="Tenant ID (default: 'default')")
    parser.add_argument("--hub-threshold", type=int, default=50,
                        help="Seuil de claims pour annoter un hub (default: 50)")
    parser.add_argument("--skip-containment", action="store_true",
                        help="Ne pas exécuter les fusions containment (version + hubs seulement)")
    args = parser.parse_args()

    if args.execute:
        args.dry_run = False

    driver = get_neo4j_driver()

    try:
        with driver.session() as session:
            # 1. Charger les entities
            logger.info(f"[OSMOSE] Chargement des entities (tenant={args.tenant})...")
            entities = load_all_entities(session, args.tenant)
            logger.info(f"  → {len(entities)} entities chargées")

            if not entities:
                logger.info("Aucune entity à traiter.")
                return

            # 2. Identifier les groupes version
            logger.info("[OSMOSE] Recherche des variantes version...")
            version_groups = find_version_groups(entities)
            version_merge_count = sum(
                len(members) - 1
                for members in version_groups.values()
                if len(members) > 1
            )
            logger.info(f"  → {len(version_groups)} groupes version, "
                         f"{version_merge_count} fusions potentielles")

            # Afficher les groupes version
            for base_norm, members in sorted(version_groups.items()):
                if len(members) > 1:
                    names = [m["name"] for m in members]
                    counts = [m["claim_count"] for m in members]
                    logger.info(f"  VERSION GROUP: {names} (claims: {counts})")

            # 3. Identifier les containments
            containment_pairs = []
            if not args.skip_containment:
                from knowbase.claimfirst.models.entity import is_valid_entity_name
                logger.info("[OSMOSE] Recherche des containments...")
                raw_pairs = find_containment_groups(entities)
                # Filtrer : les deux entities doivent être valides
                for source, target in raw_pairs:
                    if is_valid_entity_name(source["name"]) and is_valid_entity_name(target["name"]):
                        containment_pairs.append((source, target))
                    else:
                        logger.debug(
                            f"  SKIP containment (entity invalide): "
                            f"\"{source['name']}\" → \"{target['name']}\""
                        )
                logger.info(f"  → {len(containment_pairs)} paires containment valides "
                            f"(sur {len(raw_pairs)} brutes)")

                for source, target in containment_pairs[:15]:
                    logger.info(
                        f"  CONTAINMENT: \"{source['name']}\" → \"{target['name']}\" "
                        f"(claims: {source['claim_count']} → {target['claim_count']})"
                    )
                if len(containment_pairs) > 15:
                    logger.info(f"  ... et {len(containment_pairs) - 15} autres")
            else:
                logger.info("[OSMOSE] Containment ignoré (--skip-containment)")

            # 4. Résumé
            logger.info(f"\n{'='*60}")
            logger.info("RÉSUMÉ CANONICALISATION")
            logger.info(f"{'='*60}")
            logger.info(f"Entities initiales : {len(entities)}")
            logger.info(f"Fusions version    : {version_merge_count}")
            logger.info(f"Fusions containment: {len(containment_pairs)}")

            if args.dry_run:
                logger.info("\n[DRY-RUN] Aucune modification effectuée.")
                logger.info("    Utilisez --execute pour appliquer.")
                return

            # 5. Exécuter les fusions version
            if version_merge_count > 0:
                logger.info(f"\n[OSMOSE] Fusion des variantes version...")
                merged = 0
                for base_norm, members in version_groups.items():
                    if len(members) <= 1:
                        continue
                    # Choisir le canonical : entity sans version, ou la plus mentionnée
                    from knowbase.claimfirst.models.entity import strip_version_qualifier
                    canonical = None
                    for m in members:
                        _, version = strip_version_qualifier(m["name"])
                        if version is None:
                            canonical = m
                            break
                    if canonical is None:
                        canonical = max(members, key=lambda m: m["claim_count"])

                    for m in members:
                        if m["entity_id"] != canonical["entity_id"]:
                            merge_entities_in_neo4j(
                                session, m["entity_id"], canonical["entity_id"], args.tenant
                            )
                            merged += 1
                logger.info(f"  → {merged} entities fusionnées (version)")

            # 6. Exécuter les fusions containment
            if containment_pairs:
                logger.info(f"\n[OSMOSE] Fusion des containments...")
                merged = 0
                for source, target in containment_pairs:
                    merge_entities_in_neo4j(
                        session, source["entity_id"], target["entity_id"], args.tenant
                    )
                    merged += 1
                logger.info(f"  → {merged} entities fusionnées (containment)")

            # 7. Annoter les hubs
            logger.info(f"\n[OSMOSE] Annotation des hubs (seuil: {args.hub_threshold})...")
            hubs = annotate_hubs(session, args.tenant, args.hub_threshold)
            logger.info(f"  → {hubs} entities annotées comme hubs")

            logger.info("\n[OSMOSE] Canonicalisation terminée.")

    finally:
        driver.close()


if __name__ == "__main__":
    main()
