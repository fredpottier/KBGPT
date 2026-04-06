#!/usr/bin/env python3
"""
Pass C1.2 — Canonicalisation par Token Blocking.

Strategie :
1. Tokeniser chaque entite orpheline en mots significatifs
2. Index inverse : token → [entity_ids]
3. Pour chaque paire partageant >= 2 tokens significatifs : calculer similarite
4. Regrouper par composantes connexes (Union-Find)
5. Pour chaque groupe : elire le representant (le plus de claims)
6. Creer/mettre a jour les CanonicalEntity

Usage :
    python scripts/canonicalize_token_blocking.py --dry-run --tenant default
    python scripts/canonicalize_token_blocking.py --execute --tenant default
"""

from __future__ import annotations

import argparse
import logging
import os
import re
import sys
from collections import Counter, defaultdict
from typing import Any

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

# Stopwords — mots trop generiques qui ne devraient pas servir de pont
STOP_TOKENS = frozenset({
    "sap", "the", "and", "for", "with", "from", "system", "systems",
    "management", "manager", "service", "services", "based", "data",
    "integration", "process", "processing", "application", "applications",
    "app", "apps", "tool", "tools", "module", "function", "functions",
    "standard", "general", "new", "configuration", "report", "reports",
    "check", "checks", "control", "type", "types", "user", "number",
    "table", "tables", "field", "fields", "role", "roles", "object",
    "objects", "view", "views", "custom", "specific", "support",
    "activation", "creation", "maintenance", "monitor", "monitoring",
})

# Tokens trop courts ou numeriques seuls
MIN_TOKEN_LEN = 3


def tokenize(name: str) -> set[str]:
    """Extrait les tokens significatifs d'un nom d'entite."""
    # Normaliser : lowercase, supprimer ponctuation sauf / et _
    cleaned = re.sub(r"[().,;:!?\"'\[\]{}]", " ", name.lower())
    words = cleaned.split()
    tokens = set()
    for w in words:
        if len(w) < MIN_TOKEN_LEN:
            continue
        if w in STOP_TOKENS:
            continue
        if w.isdigit():
            # Garder les annees (2020-2030) et versions (4 chiffres)
            if len(w) == 4 and 2000 <= int(w) <= 2030:
                tokens.add(w)
            continue
        tokens.add(w)
    return tokens


def jaccard_similarity(set_a: set, set_b: set) -> float:
    """Similarite de Jaccard entre deux ensembles de tokens."""
    if not set_a or not set_b:
        return 0.0
    intersection = set_a & set_b
    union = set_a | set_b
    return len(intersection) / len(union)


class UnionFind:
    """Union-Find pour regrouper les entites similaires."""

    def __init__(self):
        self.parent = {}

    def find(self, x):
        if x not in self.parent:
            self.parent[x] = x
        if self.parent[x] != x:
            self.parent[x] = self.find(self.parent[x])
        return self.parent[x]

    def union(self, x, y):
        rx, ry = self.find(x), self.find(y)
        if rx != ry:
            self.parent[rx] = ry

    def groups(self) -> dict[str, list[str]]:
        clusters = defaultdict(list)
        for x in self.parent:
            clusters[self.find(x)].append(x)
        return {k: v for k, v in clusters.items() if len(v) > 1}


def load_orphan_entities(driver, tenant_id: str) -> list[dict]:
    """Charge les entites non rattachees a un CanonicalEntity."""
    query = """
    MATCH (e:Entity {tenant_id: $tid})
    WHERE NOT (e)-[:SAME_CANON_AS]->(:CanonicalEntity)
    OPTIONAL MATCH (e)<-[:ABOUT]-(c:Claim)
    WITH e, count(c) AS claim_count
    RETURN e.name AS name, elementId(e) AS eid, claim_count
    ORDER BY claim_count DESC
    """
    with driver.session() as session:
        result = session.run(query, tid=tenant_id)
        return [dict(r) for r in result]


def load_existing_canonicals(driver, tenant_id: str) -> list[dict]:
    """Charge les CanonicalEntity existants avec leurs entites."""
    query = """
    MATCH (ce:CanonicalEntity {tenant_id: $tid})
    WHERE ce.name IS NOT NULL
    OPTIONAL MATCH (e:Entity)-[:SAME_CANON_AS]->(ce)
    WITH ce, collect(e.name) AS entity_names, count(e) AS entity_count
    RETURN ce.name AS name, elementId(ce) AS ceid, entity_names, entity_count
    """
    with driver.session() as session:
        result = session.run(query, tid=tenant_id)
        return [dict(r) for r in result]


def persist_merges(driver, tenant_id: str, groups: list[dict[str, Any]]):
    """Persiste les groupes de merge dans Neo4j."""
    query_link = """
    MATCH (e:Entity {tenant_id: $tid})
    WHERE elementId(e) = $eid
    MATCH (ce:CanonicalEntity {tenant_id: $tid})
    WHERE elementId(ce) = $ceid
    MERGE (e)-[:SAME_CANON_AS]->(ce)
    """
    query_create_canon = """
    CREATE (ce:CanonicalEntity {
        tenant_id: $tid,
        name: $name,
        source: 'c1.2_token_blocking',
        created_at: datetime()
    })
    RETURN elementId(ce) AS ceid
    """
    with driver.session() as session:
        created = 0
        linked = 0
        for group in groups:
            winner = group["winner"]
            members = group["members"]

            # Verifier si le winner a deja un canonical
            canon_eid = group.get("existing_canon_eid")

            if not canon_eid:
                # Creer un nouveau CanonicalEntity
                result = session.run(query_create_canon, tid=tenant_id, name=winner["name"])
                canon_eid = result.single()["ceid"]
                created += 1

            # Lier tous les membres au canonical
            for member in members:
                session.run(query_link, tid=tenant_id, eid=member["eid"], ceid=canon_eid)
                linked += 1

        return created, linked


def run(tenant_id: str, dry_run: bool = True, min_jaccard: float = 0.5, min_shared_tokens: int = 2):
    """Execute la canonicalisation par token blocking."""
    from neo4j import GraphDatabase

    neo4j_uri = os.getenv("NEO4J_URI", "bolt://localhost:7687")
    neo4j_user = os.getenv("NEO4J_USER", "neo4j")
    neo4j_pass = os.getenv("NEO4J_PASSWORD", "graphiti_neo4j_pass")

    driver = GraphDatabase.driver(neo4j_uri, auth=(neo4j_user, neo4j_pass))

    # 1. Charger les orphelins
    logger.info("[C1.2] Loading orphan entities...")
    orphans = load_orphan_entities(driver, tenant_id)
    logger.info(f"[C1.2] {len(orphans)} orphan entities loaded")

    # 2. Charger les canonicals existants (pour rattacher plutot que creer)
    canonicals = load_existing_canonicals(driver, tenant_id)
    canon_by_token = defaultdict(list)  # token → [(canon_name, canon_eid)]
    for ce in canonicals:
        for tok in tokenize(ce["name"]):
            canon_by_token[tok].append((ce["name"], ce["ceid"]))
    logger.info(f"[C1.2] {len(canonicals)} existing canonicals loaded, {len(canon_by_token)} token index entries")

    # 3. Tokeniser et indexer
    entity_tokens = {}  # eid → set of tokens
    token_index = defaultdict(set)  # token → set of eids

    for ent in orphans:
        tokens = tokenize(ent["name"])
        if not tokens:
            continue
        entity_tokens[ent["eid"]] = tokens
        for tok in tokens:
            token_index[tok].add(ent["eid"])

    logger.info(f"[C1.2] Tokenized {len(entity_tokens)} entities, {len(token_index)} unique tokens")

    # Filtrer les tokens trop frequents (> 100 entites) — trop generiques
    MAX_TOKEN_FREQ = 100
    filtered_out = 0
    for tok in list(token_index.keys()):
        if len(token_index[tok]) > MAX_TOKEN_FREQ:
            filtered_out += 1
            del token_index[tok]
    if filtered_out:
        logger.info(f"[C1.2] Filtered {filtered_out} tokens with > {MAX_TOKEN_FREQ} entities")

    # 4. Trouver les paires candidates (partagent >= min_shared_tokens)
    uf = UnionFind()
    pair_count = 0
    eid_to_entity = {e["eid"]: e for e in orphans}

    for tok, eids in token_index.items():
        eids_list = list(eids)
        if len(eids_list) > 50:
            continue  # Skip tokens too broad
        for i in range(len(eids_list)):
            for j in range(i + 1, len(eids_list)):
                a, b = eids_list[i], eids_list[j]
                if a not in entity_tokens or b not in entity_tokens:
                    continue
                shared = entity_tokens[a] & entity_tokens[b]
                if len(shared) >= min_shared_tokens:
                    jac = jaccard_similarity(entity_tokens[a], entity_tokens[b])
                    if jac >= min_jaccard:
                        uf.union(a, b)
                        pair_count += 1

    logger.info(f"[C1.2] Found {pair_count} candidate pairs")

    # 5. Extraire les groupes
    raw_groups = uf.groups()
    logger.info(f"[C1.2] {len(raw_groups)} merge groups formed")

    # 6. Pour chaque groupe, trouver le canon existant ou elire un winner
    merge_groups = []
    for root, member_eids in raw_groups.items():
        members = [eid_to_entity[eid] for eid in member_eids if eid in eid_to_entity]
        if len(members) < 2:
            continue

        # Chercher si un des membres a deja un matching canonical
        existing_canon_eid = None
        for m in members:
            m_tokens = entity_tokens.get(m["eid"], set())
            for tok in m_tokens:
                for canon_name, canon_eid in canon_by_token.get(tok, []):
                    canon_tokens = tokenize(canon_name)
                    if jaccard_similarity(m_tokens, canon_tokens) >= min_jaccard:
                        existing_canon_eid = canon_eid
                        break
                if existing_canon_eid:
                    break

        # Elire le winner (le plus de claims)
        winner = max(members, key=lambda m: m["claim_count"])

        merge_groups.append({
            "winner": winner,
            "members": members,
            "existing_canon_eid": existing_canon_eid,
            "size": len(members),
        })

    # Trier par taille decroissante
    merge_groups.sort(key=lambda g: g["size"], reverse=True)

    # 7. Rapport
    total_to_link = sum(g["size"] for g in merge_groups)
    logger.info(f"[C1.2] {len(merge_groups)} valid groups, {total_to_link} entities to link")
    logger.info("")

    for g in merge_groups[:20]:
        w = g["winner"]
        names = sorted([m["name"] for m in g["members"]])
        existing = "→ existing canon" if g["existing_canon_eid"] else "→ NEW canon"
        logger.info(f"  Group ({g['size']}): winner='{w['name']}' ({w['claim_count']} claims) {existing}")
        for n in names[:5]:
            if n != w["name"]:
                logger.info(f"    - {n}")
        if len(names) > 5:
            logger.info(f"    ... +{len(names) - 5} more")

    if len(merge_groups) > 20:
        logger.info(f"  ... +{len(merge_groups) - 20} more groups")

    # 8. Executer ou dry-run
    if dry_run:
        logger.info(f"\n[C1.2] DRY-RUN: {len(merge_groups)} groups, {total_to_link} entities would be linked")
        logger.info("  → Relancer avec --execute pour appliquer.")
    else:
        created, linked = persist_merges(driver, tenant_id, merge_groups)
        logger.info(f"\n[C1.2] EXECUTED: {created} new canonicals created, {linked} entities linked")

    driver.close()
    return merge_groups


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="C1.2 — Token Blocking Canonicalization")
    parser.add_argument("--tenant", default="default")
    parser.add_argument("--dry-run", action="store_true", default=True)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--min-jaccard", type=float, default=0.5, help="Seuil Jaccard minimum (defaut: 0.5)")
    parser.add_argument("--min-shared", type=int, default=2, help="Tokens partages minimum (defaut: 2)")
    args = parser.parse_args()

    if args.execute:
        args.dry_run = False

    run(
        tenant_id=args.tenant,
        dry_run=args.dry_run,
        min_jaccard=args.min_jaccard,
        min_shared_tokens=args.min_shared,
    )
