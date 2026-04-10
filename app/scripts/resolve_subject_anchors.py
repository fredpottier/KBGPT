"""
Resolve SubjectAnchors — applique les canonical_aliases du domain pack.

Les SubjectAnchors sont crees a l'ingestion avec le nom brut du document.
Ce script les normalise via le gazetteer du domain pack actif, exactement
comme resolve_subjects.py le fait pour les ComparableSubjects.

Exemples de resolution :
  "RISE with SAP" → merge dans "SAP S/4HANA Cloud Private Edition"
  "Cloud ALM" → merge dans "SAP Cloud ALM"
  "ILM" → merge dans "SAP Information Lifecycle Management (ILM)"

Usage (dans Docker):
    python scripts/resolve_subject_anchors.py
    python scripts/resolve_subject_anchors.py --dry-run
"""

from __future__ import annotations

import argparse
import logging
import os
import sys

sys.path.insert(0, "/app/src")

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("resolve-subject-anchors")


def main():
    parser = argparse.ArgumentParser(description="Resolve SubjectAnchors via domain pack aliases")
    parser.add_argument("--tenant", default="default")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    from neo4j import GraphDatabase
    from knowbase.domain_packs.registry import get_pack_registry

    uri = os.environ.get("NEO4J_URI", "bolt://neo4j:7687")
    user = os.environ.get("NEO4J_USER", "neo4j")
    password = os.environ.get("NEO4J_PASSWORD", "graphiti_neo4j_pass")
    driver = GraphDatabase.driver(uri, auth=(user, password))

    # Charger les aliases du domain pack actif
    registry = get_pack_registry()
    packs = registry.get_active_packs(args.tenant)
    if not packs:
        logger.warning("No active domain pack — nothing to resolve")
        return

    all_aliases = {}
    for pack in packs:
        aliases = pack.get_canonical_aliases()
        all_aliases.update(aliases)
        logger.info(f"Pack {pack.name}: {len(aliases)} aliases loaded")

    if not all_aliases:
        logger.info("No aliases to apply")
        return

    # Charger les SubjectAnchors
    with driver.session() as session:
        result = session.run("MATCH (sa:SubjectAnchor) RETURN sa.subject_id AS sid, sa.canonical_name AS name")
        anchors = [(rec["sid"], rec["name"]) for rec in result]

    logger.info(f"SubjectAnchors: {len(anchors)}")

    # Determiner les merges a faire
    # Un merge = un SubjectAnchor dont le canonical_name est un alias
    # Il faut le fusionner dans le SubjectAnchor cible (le canonical)
    merges = []  # (source_sid, source_name, target_name)
    anchor_by_name = {name: sid for sid, name in anchors}

    for sid, name in anchors:
        canonical = all_aliases.get(name)
        if canonical and canonical != name:
            merges.append((sid, name, canonical))

    if not merges:
        logger.info("No SubjectAnchors to resolve — all already canonical")
        driver.close()
        return

    logger.info(f"\nMerges to apply: {len(merges)}")
    for src_sid, src_name, target_name in merges:
        target_sid = anchor_by_name.get(target_name)
        status = "→ exists" if target_sid else "→ NEW"
        logger.info(f'  "{src_name}" → "{target_name}" {status}')

    if args.dry_run:
        logger.info("\n[DRY RUN] No changes applied")
        driver.close()
        return

    # Appliquer les merges
    stats = {"merged": 0, "rels_moved": 0, "created": 0}

    with driver.session() as session:
        for src_sid, src_name, target_name in merges:
            target_sid = anchor_by_name.get(target_name)

            if not target_sid:
                # Le canonical n'existe pas comme SubjectAnchor → renommer le source
                session.run("""
                    MATCH (sa:SubjectAnchor {subject_id: $sid})
                    SET sa.canonical_name = $new_name,
                        sa.aliases_explicit = sa.aliases_explicit + [$old_name]
                """, sid=src_sid, new_name=target_name, old_name=src_name)
                anchor_by_name[target_name] = src_sid
                del anchor_by_name[src_name]
                stats["merged"] += 1
                logger.info(f'  Renamed "{src_name}" → "{target_name}"')
            else:
                # Le canonical existe → transferer les relations du source vers le target
                # puis supprimer le source

                # 1. Transferer TOUCHES_SUBJECT (Perspective → SubjectAnchor)
                moved = session.run("""
                    MATCH (p)-[r:TOUCHES_SUBJECT]->(sa:SubjectAnchor {subject_id: $src_sid})
                    MATCH (target:SubjectAnchor {subject_id: $target_sid})
                    WHERE NOT EXISTS { (p)-[:TOUCHES_SUBJECT]->(target) }
                    CREATE (p)-[:TOUCHES_SUBJECT {weight: r.weight}]->(target)
                    DELETE r
                    RETURN count(r) AS cnt
                """, src_sid=src_sid, target_sid=target_sid).single()["cnt"]
                stats["rels_moved"] += moved

                # 2. Transferer HAS_AXIS_VALUE (DocumentContext → SubjectAnchor)
                moved2 = session.run("""
                    MATCH (dc)-[r:HAS_AXIS_VALUE]->(sa:SubjectAnchor {subject_id: $src_sid})
                    MATCH (target:SubjectAnchor {subject_id: $target_sid})
                    WHERE NOT EXISTS { (dc)-[:HAS_AXIS_VALUE]->(target) }
                    CREATE (dc)-[:HAS_AXIS_VALUE]->(target)
                    DELETE r
                    RETURN count(r) AS cnt
                """, src_sid=src_sid, target_sid=target_sid).single()["cnt"]
                stats["rels_moved"] += moved2

                # 3. Transferer toute autre relation entrante
                moved3 = session.run("""
                    MATCH (source)-[r]->(sa:SubjectAnchor {subject_id: $src_sid})
                    WHERE NOT type(r) IN ['TOUCHES_SUBJECT', 'HAS_AXIS_VALUE']
                    DETACH DELETE r
                    RETURN count(r) AS cnt
                """, src_sid=src_sid).single()["cnt"]

                # 4. Ajouter l'alias dans le target
                session.run("""
                    MATCH (sa:SubjectAnchor {subject_id: $target_sid})
                    SET sa.aliases_explicit = sa.aliases_explicit + [$alias]
                """, target_sid=target_sid, alias=src_name)

                # 5. Supprimer le source
                session.run("""
                    MATCH (sa:SubjectAnchor {subject_id: $src_sid})
                    DETACH DELETE sa
                """, src_sid=src_sid)

                stats["merged"] += 1
                logger.info(f'  Merged "{src_name}" into "{target_name}" ({moved + moved2} rels moved)')

    logger.info(f"\nDone: {stats}")
    driver.close()


if __name__ == "__main__":
    main()
