#!/usr/bin/env python3
"""
backfill_canonical_entities.py — Crée les CanonicalEntity et SAME_CANON_AS
pour les entités orphelines existantes dans Neo4j.

Stratégie non-destructive :
  - NE supprime AUCUNE entité
  - NE modifie AUCUNE relation ABOUT existante
  - Crée uniquement des CanonicalEntity + SAME_CANON_AS

Méthodes de regroupement (par ordre de confiance) :
  1. Alias Identity (conf 0.95) — le nom d'une entité est un alias d'une autre
  2. Prefix Dedup (conf 0.90) — "SAP X" / "X" partagent le même suffixe
  3. Normalized Match (conf 0.85) — normalized_name identique

Usage :
    docker compose exec app python scripts/backfill_canonical_entities.py
    docker compose exec app python scripts/backfill_canonical_entities.py --execute
    docker compose exec app python scripts/backfill_canonical_entities.py --execute --tenant-id default
"""

import argparse
import logging
import os
import re
import time
from collections import defaultdict
from typing import Dict, List, Optional, Set, Tuple

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("[OSMOSE] backfill_canonical")


def get_neo4j_driver():
    from neo4j import GraphDatabase

    uri = os.getenv("NEO4J_URI", "bolt://neo4j:7687")
    user = os.getenv("NEO4J_USER", "neo4j")
    password = os.getenv("NEO4J_PASSWORD", "graphiti_neo4j_pass")
    return GraphDatabase.driver(uri, auth=(user, password))


# ── Union-Find ───────────────────────────────────────────────────────────

class UnionFind:
    """Union-Find pour regrouper les entités."""

    def __init__(self):
        self.parent: Dict[str, str] = {}
        self.rank: Dict[str, int] = {}

    def find(self, x: str) -> str:
        if x not in self.parent:
            self.parent[x] = x
            self.rank[x] = 0
        if self.parent[x] != x:
            self.parent[x] = self.find(self.parent[x])
        return self.parent[x]

    def union(self, x: str, y: str) -> None:
        rx, ry = self.find(x), self.find(y)
        if rx == ry:
            return
        if self.rank[rx] < self.rank[ry]:
            rx, ry = ry, rx
        self.parent[ry] = rx
        if self.rank[rx] == self.rank[ry]:
            self.rank[rx] += 1

    def groups(self) -> Dict[str, Set[str]]:
        result: Dict[str, Set[str]] = defaultdict(set)
        for x in self.parent:
            result[self.find(x)].add(x)
        return result


# ── Normalisation ────────────────────────────────────────────────────────

def normalize_name(name: str) -> str:
    """Normalise un nom d'entité (même logique que Entity.normalize)."""
    result = name.lower().strip()
    result = re.sub(r"[^\w\s/]", " ", result)
    result = re.sub(r"\s+", " ", result).strip()
    return result


# ── Prefixes SAP courants ────────────────────────────────────────────────

SAP_PREFIXES = ["sap ", "sap's "]

def strip_sap_prefix(name: str) -> Optional[str]:
    """Retire le préfixe 'SAP ' d'un nom, retourne None si pas de préfixe."""
    lower = name.lower()
    for prefix in SAP_PREFIXES:
        if lower.startswith(prefix) and len(lower) > len(prefix) + 2:
            return name[len(prefix):]
    return None


# ── Élection du nom canonique ────────────────────────────────────────────

def elect_canonical_name(
    entity_ids: Set[str],
    entities_by_id: Dict[str, dict],
) -> Tuple[str, str]:
    """
    Élit le nom canonique d'un groupe.

    Critères (dans l'ordre) :
    1. Préférer la forme avec préfixe "SAP " (plus officielle)
    2. Plus grand nombre de claims
    3. Nom le plus court (sauf si trop court < 3 chars)

    Returns:
        (canonical_name, entity_type)
    """
    candidates = []
    for eid in entity_ids:
        e = entities_by_id.get(eid)
        if not e:
            continue
        has_sap = e["name"].lower().startswith("sap ")
        candidates.append((
            has_sap,                # critère 1: préfixe SAP
            e.get("claim_count", 0),  # critère 2: nb claims
            -len(e["name"]),        # critère 3: plus court (inversé)
            e["name"],
            e.get("entity_type", "concept"),
        ))

    if not candidates:
        return ("unknown", "concept")

    candidates.sort(reverse=True)
    return (candidates[0][3], candidates[0][4])


# ── Main ─────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Backfill CanonicalEntity + SAME_CANON_AS pour entités orphelines"
    )
    parser.add_argument("--execute", action="store_true", help="Exécuter (défaut: dry-run)")
    parser.add_argument("--tenant-id", default="default")
    parser.add_argument("--min-group-size", type=int, default=2,
                        help="Taille minimum d'un groupe pour créer un CanonicalEntity")
    args = parser.parse_args()

    dry_run = not args.execute
    tenant_id = args.tenant_id

    logger.info("=" * 60)
    logger.info(f"BACKFILL CANONICAL ENTITIES {'(DRY-RUN)' if dry_run else '(EXECUTE)'}")
    logger.info(f"Tenant: {tenant_id}")
    logger.info("=" * 60)

    driver = get_neo4j_driver()
    start = time.time()

    stats = {
        "orphan_entities": 0,
        "already_linked": 0,
        "edges_alias_identity": 0,
        "edges_prefix_dedup": 0,
        "edges_normalized_match": 0,
        "groups_formed": 0,
        "singletons_skipped": 0,
        "canonical_entities_created": 0,
        "same_canon_as_created": 0,
    }

    # ── Phase 1 : Charger toutes les entités ─────────────────────────────

    logger.info("Phase 1 : Chargement des entités...")

    with driver.session() as session:
        # Entités orphelines (pas de SAME_CANON_AS)
        result = session.run("""
            MATCH (e:Entity {tenant_id: $tenant_id})
            WHERE NOT (e)-[:SAME_CANON_AS]->(:CanonicalEntity)
            OPTIONAL MATCH (c:Claim)-[:ABOUT]->(e)
            WITH e, count(c) AS claim_count
            RETURN e.entity_id AS entity_id, e.name AS name,
                   e.normalized_name AS normalized_name,
                   e.entity_type AS entity_type,
                   e.aliases AS aliases,
                   claim_count
        """, tenant_id=tenant_id)

        orphans: Dict[str, dict] = {}
        for r in result:
            orphans[r["entity_id"]] = {
                "entity_id": r["entity_id"],
                "name": r["name"],
                "normalized_name": r["normalized_name"] or normalize_name(r["name"]),
                "entity_type": r["entity_type"] or "concept",
                "aliases": r["aliases"] or [],
                "claim_count": r["claim_count"],
            }

        # Entités déjà liées (pour référence lors de l'alias matching)
        result = session.run("""
            MATCH (e:Entity {tenant_id: $tenant_id})-[:SAME_CANON_AS]->(ce:CanonicalEntity)
            RETURN e.entity_id AS entity_id, e.name AS name,
                   e.normalized_name AS normalized_name,
                   ce.canonical_entity_id AS ce_id,
                   ce.canonical_name AS ce_name
        """, tenant_id=tenant_id)

        linked: Dict[str, dict] = {}
        for r in result:
            linked[r["entity_id"]] = {
                "entity_id": r["entity_id"],
                "name": r["name"],
                "normalized_name": r["normalized_name"] or normalize_name(r["name"]),
                "ce_id": r["ce_id"],
                "ce_name": r["ce_name"],
            }

    stats["orphan_entities"] = len(orphans)
    stats["already_linked"] = len(linked)
    logger.info(f"  Orphelines: {len(orphans)}, Déjà liées: {len(linked)}")

    if not orphans:
        logger.info("Aucune entité orpheline — rien à faire.")
        driver.close()
        return

    # ── Phase 2 : Construire les index ───────────────────────────────────

    logger.info("Phase 2 : Construction des index...")

    # Index normalized_name → entity_ids (orphelins)
    norm_to_ids: Dict[str, List[str]] = defaultdict(list)
    for eid, e in orphans.items():
        norm_to_ids[e["normalized_name"]].append(eid)

    # Index name_lower → entity_id (tous, pour alias matching)
    name_to_id: Dict[str, str] = {}
    for eid, e in orphans.items():
        name_to_id[e["name"].lower()] = eid
    for eid, e in linked.items():
        name_to_id[e["name"].lower()] = eid

    # ── Phase 3 : Identifier les edges de regroupement ───────────────────

    logger.info("Phase 3 : Identification des regroupements...")

    uf = UnionFind()
    edges: List[Tuple[str, str, str, float]] = []  # (id1, id2, method, confidence)

    # 3a. Normalized Match — même normalized_name = même entité
    for norm, ids in norm_to_ids.items():
        if len(ids) > 1:
            for i in range(1, len(ids)):
                uf.union(ids[0], ids[i])
                edges.append((ids[0], ids[i], "normalized_match", 0.85))
                stats["edges_normalized_match"] += 1

    # 3b. Alias Identity — le nom d'une entité est dans les aliases d'une autre
    for eid, e in orphans.items():
        aliases = e.get("aliases") or []
        if isinstance(aliases, str):
            aliases = [aliases]
        for alias in aliases:
            alias_lower = alias.lower()
            if alias_lower in name_to_id:
                other_id = name_to_id[alias_lower]
                if other_id != eid and other_id in orphans:
                    uf.union(eid, other_id)
                    edges.append((eid, other_id, "alias_identity", 0.95))
                    stats["edges_alias_identity"] += 1

    # 3c. Prefix Dedup — "SAP X" ↔ "X"
    for eid, e in orphans.items():
        stripped = strip_sap_prefix(e["name"])
        if stripped:
            stripped_lower = stripped.lower()
            if stripped_lower in name_to_id:
                other_id = name_to_id[stripped_lower]
                if other_id != eid and other_id in orphans:
                    uf.union(eid, other_id)
                    edges.append((eid, other_id, "prefix_dedup", 0.90))
                    stats["edges_prefix_dedup"] += 1

    # 3d. Rattachement aux CanonicalEntity existantes (orphelin → linked)
    orphan_to_existing_ce: Dict[str, str] = {}  # orphan_id → ce_id
    for eid, e in orphans.items():
        # Vérifier si le nom normalisé matche une entité déjà liée
        for lid, le in linked.items():
            if e["normalized_name"] == le["normalized_name"]:
                orphan_to_existing_ce[eid] = le["ce_id"]
                break
        # Vérifier aliases
        if eid not in orphan_to_existing_ce:
            aliases = e.get("aliases") or []
            if isinstance(aliases, str):
                aliases = [aliases]
            for alias in aliases:
                alias_norm = normalize_name(alias)
                for lid, le in linked.items():
                    if alias_norm == le["normalized_name"]:
                        orphan_to_existing_ce[eid] = le["ce_id"]
                        break
                if eid in orphan_to_existing_ce:
                    break

    # ── Phase 4 : Former les groupes ─────────────────────────────────────

    logger.info("Phase 4 : Formation des groupes...")

    # Initialiser tous les orphelins dans l'UF
    for eid in orphans:
        uf.find(eid)

    raw_groups = uf.groups()
    groups_to_create: List[dict] = []

    for root, members in raw_groups.items():
        if len(members) < args.min_group_size:
            # Singleton — vérifier s'il peut se rattacher à un CE existant
            eid = list(members)[0]
            if eid in orphan_to_existing_ce:
                groups_to_create.append({
                    "entity_ids": members,
                    "existing_ce_id": orphan_to_existing_ce[eid],
                    "canonical_name": None,  # pas besoin, on rattache
                    "entity_type": None,
                })
            else:
                stats["singletons_skipped"] += 1
            continue

        # Élire le nom canonique
        canonical_name, entity_type = elect_canonical_name(members, orphans)

        # Vérifier si un des membres se rattache à un CE existant
        existing_ce = None
        for eid in members:
            if eid in orphan_to_existing_ce:
                existing_ce = orphan_to_existing_ce[eid]
                break

        groups_to_create.append({
            "entity_ids": members,
            "existing_ce_id": existing_ce,
            "canonical_name": canonical_name,
            "entity_type": entity_type,
        })

    stats["groups_formed"] = len(groups_to_create)
    logger.info(f"  Groupes à traiter: {len(groups_to_create)}")
    logger.info(f"  Singletons ignorés: {stats['singletons_skipped']}")
    logger.info(f"  Edges: alias={stats['edges_alias_identity']}, "
                f"prefix={stats['edges_prefix_dedup']}, "
                f"norm={stats['edges_normalized_match']}")

    # Aperçu des plus gros groupes
    groups_to_create.sort(key=lambda g: len(g["entity_ids"]), reverse=True)
    for g in groups_to_create[:10]:
        names = [orphans[eid]["name"] for eid in g["entity_ids"] if eid in orphans][:5]
        ce_note = f" → CE existant" if g["existing_ce_id"] else ""
        logger.info(f"  [{len(g['entity_ids'])} entités] "
                     f"canon='{g['canonical_name']}'{ce_note} : {names}")

    if dry_run:
        logger.info("\n=== DRY-RUN — aucune modification. Relancer avec --execute ===")
        driver.close()
        return

    # ── Phase 5 : Persistance ────────────────────────────────────────────

    logger.info("Phase 5 : Persistance...")

    from knowbase.claimfirst.models.canonical_entity import CanonicalEntity

    with driver.session() as session:
        for g in groups_to_create:
            entity_ids = list(g["entity_ids"])

            if g["existing_ce_id"]:
                # Rattacher à un CanonicalEntity existant
                ce_id = g["existing_ce_id"]
            else:
                # Créer un nouveau CanonicalEntity
                ce_id = CanonicalEntity.make_id(tenant_id, g["canonical_name"])
                session.run("""
                    MERGE (ce:CanonicalEntity {canonical_entity_id: $ce_id})
                    ON CREATE SET
                        ce.canonical_name = $canonical_name,
                        ce.tenant_id = $tenant_id,
                        ce.entity_type = $entity_type,
                        ce.method = 'backfill_script',
                        ce.created_at = datetime()
                    ON MATCH SET
                        ce.canonical_name = $canonical_name
                """,
                    ce_id=ce_id,
                    canonical_name=g["canonical_name"],
                    tenant_id=tenant_id,
                    entity_type=g["entity_type"] or "concept",
                )
                stats["canonical_entities_created"] += 1

            # Créer les SAME_CANON_AS pour chaque entité du groupe
            for eid in entity_ids:
                e = orphans.get(eid)
                if not e:
                    continue
                # Déterminer la méthode la plus forte pour cette entité
                method = "backfill_normalized"
                for edge in edges:
                    if eid in (edge[0], edge[1]):
                        method = f"backfill_{edge[2]}"
                        break

                session.run("""
                    MATCH (e:Entity {entity_id: $eid})
                    MATCH (ce:CanonicalEntity {canonical_entity_id: $ce_id})
                    MERGE (e)-[r:SAME_CANON_AS]->(ce)
                    ON CREATE SET r.method = $method, r.confidence = $confidence,
                                  r.created_at = datetime()
                """,
                    eid=eid,
                    ce_id=ce_id,
                    method=method,
                    confidence=0.85,
                )
                stats["same_canon_as_created"] += 1

    driver.close()

    elapsed = time.time() - start
    logger.info(f"\n{'=' * 60}")
    logger.info(f"BACKFILL CANONICAL ENTITIES — TERMINÉ")
    logger.info(f"{'=' * 60}")
    for key, value in stats.items():
        logger.info(f"  {key:.<45} {value}")
    logger.info(f"  {'duration':.<45} {elapsed:.1f}s")


if __name__ == "__main__":
    main()
