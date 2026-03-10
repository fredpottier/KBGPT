#!/usr/bin/env python3
"""
Pass C1.1 — Canonicalisation Cross-Doc des Entités (ultra-strict).

Crée des nœuds pivot CanonicalEntity reliant les Entity variantes via
SAME_CANON_AS. Deux méthodes data-driven :
  - Alias Identity Match (confiance 0.95)
  - Prefix Dedup data-driven (confiance 0.90)

PAS de version_strip (C1.2), PAS de LLM (C1.3).

Usage (dans le conteneur Docker) :
    # Dry-run (défaut) — affiche le rapport sans rien toucher
    python scripts/canonicalize_entities_cross_doc.py --dry-run --tenant default

    # Exécuter la persistance
    python scripts/canonicalize_entities_cross_doc.py --execute --tenant default

    # Sortie JSON
    python scripts/canonicalize_entities_cross_doc.py --dry-run --tenant default --output-json report.json
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from collections import Counter
from datetime import datetime
from typing import Any, Dict, List, Optional, Set, Tuple

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Constantes
# ---------------------------------------------------------------------------

# Alias trop génériques — ne doivent jamais servir de pont entre Entity
ALIAS_NOISE_SET = frozenset({
    "app", "apps", "platform", "system", "service", "solution",
    "tool", "tools", "module", "modules", "component", "components",
})

# Seuil : un prefix doit apparaître dans ≥ N Entity pour être candidat au dedup
PREFIX_FREQUENCY_THRESHOLD = 50

# Matrice de compatibilité des types.
# Clé = frozenset({type_a, type_b}) → compatible
# Si la paire n'est pas dans la matrice → incompatible par défaut
_COMPATIBLE_PAIRS: Set[frozenset] = {
    frozenset({"product", "service"}),
    frozenset({"product", "feature"}),
    frozenset({"concept", "standard"}),
    frozenset({"concept", "legal_term"}),
    frozenset({"standard", "legal_term"}),
    frozenset({"product"}),     # même type
    frozenset({"service"}),
    frozenset({"feature"}),
    frozenset({"actor"}),
    frozenset({"concept"}),
    frozenset({"standard"}),
    frozenset({"legal_term"}),
    frozenset({"other"}),
}

# Types qui ne doivent JAMAIS fusionner avec d'autres types
_NEVER_MIX = {"actor"}


# ---------------------------------------------------------------------------
# Normalisation (réutilise Entity.normalize mais importable sans Pydantic deps)
# ---------------------------------------------------------------------------

import re

def _normalize(name: str) -> str:
    """Normalise un nom d'entité (identique à Entity.normalize)."""
    if not name:
        return ""
    normalized = name.lower().strip()
    normalized = re.sub(r"[^\w\s\-]", "", normalized)
    normalized = re.sub(r"\s+", " ", normalized)
    return normalized


# ---------------------------------------------------------------------------
# Phase 2 — Index de matching
# ---------------------------------------------------------------------------

def _alias_passes_quality(alias: str) -> bool:
    """Vérifie qu'un alias est assez spécifique pour servir de pont."""
    normalized = _normalize(alias)
    if not normalized:
        return False
    # Doit avoir ≥2 tokens OU ≥5 alpha chars
    tokens = normalized.split()
    alpha_chars = sum(1 for c in normalized if c.isalpha())
    if len(tokens) < 2 and alpha_chars < 5:
        return False
    # Ne doit pas être dans la noise set
    if normalized in ALIAS_NOISE_SET:
        return False
    return True


def _types_compatible(type_a: str, type_b: str) -> bool:
    """Vérifie si deux entity_types sont compatibles pour fusion."""
    a = type_a.lower()
    b = type_b.lower()
    if a == b:
        return True
    # OTHER est neutre — ne bloque jamais
    if a == "other" or b == "other":
        return True
    # ACTOR ne fusionne jamais avec un non-ACTOR
    if a in _NEVER_MIX or b in _NEVER_MIX:
        return False
    pair = frozenset({a, b})
    return pair in _COMPATIBLE_PAIRS


# ---------------------------------------------------------------------------
# Phase 3 — Edges candidats (fonctions pures, testables)
# ---------------------------------------------------------------------------

def build_candidate_edges(
    entities: List[dict],
    norm_index: Dict[str, List[str]],
    alias_index: Dict[str, List[str]],
    prefix_freq: Counter,
    prefix_threshold: int = PREFIX_FREQUENCY_THRESHOLD,
) -> List[Tuple[str, str, str, float]]:
    """
    Construit les edges candidats entre Entity.

    Deux méthodes C1.1 :
      A) Alias Identity Match (confiance 0.95)
      B) Prefix Dedup data-driven (confiance 0.90)

    Returns:
        Liste de (entity_id_1, entity_id_2, method, confidence)
    """
    entities_by_id = {e["entity_id"]: e for e in entities}
    edges: List[Tuple[str, str, str, float]] = []
    seen_pairs: Set[frozenset] = set()

    def _add_edge(eid1: str, eid2: str, method: str, conf: float):
        pair = frozenset({eid1, eid2})
        if pair not in seen_pairs:
            seen_pairs.add(pair)
            edges.append((eid1, eid2, method, conf))

    # --- Méthode A : Alias Identity Match ---
    for e in entities:
        aliases = e.get("aliases") or []
        for alias in aliases:
            if not _alias_passes_quality(alias):
                continue
            norm_alias = _normalize(alias)
            # L'alias normalisé correspond-il au normalized_name d'une autre Entity ?
            targets = norm_index.get(norm_alias, [])
            for target_id in targets:
                if target_id == e["entity_id"]:
                    continue
                target = entities_by_id.get(target_id)
                if not target:
                    continue
                if not _types_compatible(e["entity_type"], target["entity_type"]):
                    continue
                _add_edge(e["entity_id"], target_id, "alias_identity", 0.95)

    # Alias bidirectionnel : aussi vérifier alias_index → normalized_name
    for e in entities:
        norm_name = e["normalized_name"]
        # Quelles Entity ont un alias qui se normalise en notre normalized_name ?
        matching_eids = alias_index.get(norm_name, [])
        for other_id in matching_eids:
            if other_id == e["entity_id"]:
                continue
            other = entities_by_id.get(other_id)
            if not other:
                continue
            if not _types_compatible(e["entity_type"], other["entity_type"]):
                continue
            _add_edge(e["entity_id"], other_id, "alias_identity", 0.95)

    # --- Méthode B : Prefix Dedup data-driven ---
    for e in entities:
        tokens = e["normalized_name"].split()
        if len(tokens) < 2:
            continue
        first_token = tokens[0]
        if prefix_freq.get(first_token, 0) < prefix_threshold:
            continue
        stripped = " ".join(tokens[1:])
        if not stripped:
            continue
        targets = norm_index.get(stripped, [])
        for target_id in targets:
            if target_id == e["entity_id"]:
                continue
            target = entities_by_id.get(target_id)
            if not target:
                continue
            if not _types_compatible(e["entity_type"], target["entity_type"]):
                continue
            _add_edge(e["entity_id"], target_id, "prefix_dedup", 0.90)

    return edges


# ---------------------------------------------------------------------------
# Phase 4 — Union-Find
# ---------------------------------------------------------------------------

class _UnionFind:
    """Union-Find (Disjoint Set Union) simple."""

    def __init__(self):
        self.parent: Dict[str, str] = {}
        self.rank: Dict[str, int] = {}

    def find(self, x: str) -> str:
        if x not in self.parent:
            self.parent[x] = x
            self.rank[x] = 0
        if self.parent[x] != x:
            self.parent[x] = self.find(self.parent[x])  # path compression
        return self.parent[x]

    def union(self, x: str, y: str):
        rx, ry = self.find(x), self.find(y)
        if rx == ry:
            return
        # union by rank
        if self.rank[rx] < self.rank[ry]:
            rx, ry = ry, rx
        self.parent[ry] = rx
        if self.rank[rx] == self.rank[ry]:
            self.rank[rx] += 1


def union_find_groups(
    edges: List[Tuple[str, str, str, float]],
) -> List[Set[str]]:
    """
    Fusionne les edges en groupes disjoints via Union-Find.

    Ignore les groupes de taille 1 (pas de CanonicalEntity à créer).

    Returns:
        Liste de sets d'entity_ids (groupes de taille ≥2)
    """
    uf = _UnionFind()
    for eid1, eid2, _, _ in edges:
        uf.union(eid1, eid2)

    # Collecter les groupes
    groups_map: Dict[str, Set[str]] = {}
    for eid in uf.parent:
        root = uf.find(eid)
        if root not in groups_map:
            groups_map[root] = set()
        groups_map[root].add(eid)

    # Garder seulement les groupes ≥2
    return [g for g in groups_map.values() if len(g) >= 2]


# ---------------------------------------------------------------------------
# Phase 5 — Filtrage par compatibilité entity_type
# ---------------------------------------------------------------------------

def split_by_type(
    group: Set[str],
    entities_by_id: Dict[str, dict],
) -> List[Set[str]]:
    """
    Scinde un groupe si des types incompatibles coexistent.

    Règle OTHER : ne colle pas de types incompatibles ensemble.
    OTHER est assigné au sous-groupe le plus large.

    Returns:
        Liste de sous-groupes compatibles (taille ≥2)
    """
    # Séparer OTHER des non-OTHER
    other_eids: Set[str] = set()
    typed_eids: Dict[str, Set[str]] = {}  # type → set of eids

    for eid in group:
        etype = entities_by_id[eid]["entity_type"].lower()
        if etype == "other":
            other_eids.add(eid)
        else:
            if etype not in typed_eids:
                typed_eids[etype] = set()
            typed_eids[etype].add(eid)

    if not typed_eids:
        # Que des OTHER → un seul groupe
        if len(group) >= 2:
            return [group]
        return []

    # Construire des sous-groupes de types compatibles
    # Greedy : fusionner les types compatibles entre eux
    type_list = list(typed_eids.keys())
    merged_type_groups: List[Set[str]] = []

    assigned_types: Set[str] = set()
    for i, t1 in enumerate(type_list):
        if t1 in assigned_types:
            continue
        current_types = {t1}
        current_eids = set(typed_eids[t1])

        for j in range(i + 1, len(type_list)):
            t2 = type_list[j]
            if t2 in assigned_types:
                continue
            # t2 compatible avec TOUS les types déjà dans current_types ?
            if all(_types_compatible(t2, ct) for ct in current_types):
                current_types.add(t2)
                current_eids |= typed_eids[t2]
                assigned_types.add(t2)

        assigned_types.add(t1)
        merged_type_groups.append(current_eids)

    # Assigner les OTHER au sous-groupe le plus large
    if other_eids and merged_type_groups:
        largest_idx = max(range(len(merged_type_groups)),
                         key=lambda i: len(merged_type_groups[i]))
        merged_type_groups[largest_idx] |= other_eids
    elif other_eids:
        merged_type_groups.append(other_eids)

    # Filtrer les sous-groupes de taille <2
    return [g for g in merged_type_groups if len(g) >= 2]


# ---------------------------------------------------------------------------
# Phase 6 — Élection du canonical_name et entity_type
# ---------------------------------------------------------------------------

def choose_canonical(
    group: Set[str],
    entities_by_id: Dict[str, dict],
    edges: List[Tuple[str, str, str, float]],
) -> Tuple[str, str, str]:
    """
    Élit le canonical_name et entity_type pour un groupe.

    Scoring multi-critères :
      +2 si nom contient un prefix de marque ET la version sans prefix est dans le groupe
      +1 si nom a plus de tokens que la médiane du groupe
      +1 si plus grand doc_count
      +claim_count_normalized (claim_count / max_claim_count, poids 0.5)

    Returns:
        (canonical_name, entity_type, best_method)
    """
    from knowbase.claimfirst.models.entity import EntityType
    from knowbase.claimfirst.models.canonical_entity import CanonicalEntity

    members = [entities_by_id[eid] for eid in group]

    # Nom normalisé de chaque membre
    norm_names_in_group = {m["normalized_name"] for m in members}

    # Token counts
    token_counts = [len(m["normalized_name"].split()) for m in members]
    median_tokens = sorted(token_counts)[len(token_counts) // 2]

    # Max doc_count et claim_count
    max_doc_count = max((len(m.get("source_doc_ids") or []) for m in members), default=1)
    max_claim_count = max((m.get("claim_count", 0) for m in members), default=1)
    if max_claim_count == 0:
        max_claim_count = 1

    scores: Dict[str, float] = {}
    for m in members:
        score = 0.0
        tokens = m["normalized_name"].split()

        # +2 si prefix de marque avec la variante sans prefix dans le groupe
        if len(tokens) >= 2:
            stripped = " ".join(tokens[1:])
            if stripped in norm_names_in_group:
                score += 2.0

        # +1 si plus de tokens que la médiane
        if len(tokens) > median_tokens:
            score += 1.0

        # +1 si plus grand doc_count
        doc_count = len(m.get("source_doc_ids") or [])
        if doc_count == max_doc_count and max_doc_count > 0:
            score += 1.0

        # +claim_count normalisé (poids 0.5)
        claim_count = m.get("claim_count", 0)
        score += 0.5 * (claim_count / max_claim_count)

        scores[m["entity_id"]] = score

    # Élu = score max (en cas d'égalité, le name le plus long gagne)
    best_eid = max(
        group,
        key=lambda eid: (scores.get(eid, 0), len(entities_by_id[eid]["name"])),
    )
    best = entities_by_id[best_eid]
    canonical_name = best["name"]

    # Entity type = vote majoritaire (hors OTHER)
    types = [EntityType(m["entity_type"]) for m in members]
    entity_type = CanonicalEntity.majority_vote_type(types)

    # Meilleure méthode du groupe
    group_methods = set()
    for eid1, eid2, method, _ in edges:
        if eid1 in group or eid2 in group:
            group_methods.add(method)
    # alias_identity > prefix_dedup
    if "alias_identity" in group_methods:
        best_method = "alias_identity"
    elif "prefix_dedup" in group_methods:
        best_method = "prefix_dedup"
    else:
        best_method = "unknown"

    return canonical_name, entity_type.value, best_method


# ---------------------------------------------------------------------------
# Neo4j helpers
# ---------------------------------------------------------------------------

def get_neo4j_driver():
    """Crée une connexion Neo4j."""
    from neo4j import GraphDatabase

    neo4j_uri = os.getenv("NEO4J_URI", "bolt://neo4j:7687")
    neo4j_user = os.getenv("NEO4J_USER", "neo4j")
    neo4j_password = os.getenv("NEO4J_PASSWORD", "graphiti_neo4j_pass")
    return GraphDatabase.driver(neo4j_uri, auth=(neo4j_user, neo4j_password))


def load_entities(session, tenant_id: str) -> List[dict]:
    """Phase 1 — Charger toutes les Entity depuis Neo4j."""
    result = session.run(
        """
        MATCH (e:Entity {tenant_id: $tenant_id})
        OPTIONAL MATCH (e)<-[:ABOUT]-(c:Claim)
        RETURN e.entity_id AS entity_id,
               e.name AS name,
               e.normalized_name AS normalized_name,
               e.entity_type AS entity_type,
               e.aliases AS aliases,
               e.source_doc_ids AS source_doc_ids,
               count(c) AS claim_count
        """,
        tenant_id=tenant_id,
    )
    entities = []
    for record in result:
        entities.append({
            "entity_id": record["entity_id"],
            "name": record["name"],
            "normalized_name": record["normalized_name"] or _normalize(record["name"]),
            "entity_type": record["entity_type"] or "other",
            "aliases": record["aliases"] or [],
            "source_doc_ids": record["source_doc_ids"] or [],
            "claim_count": record["claim_count"],
        })
    return entities


def build_indexes(
    entities: List[dict],
) -> Tuple[Dict[str, List[str]], Dict[str, List[str]], Counter]:
    """
    Phase 2 — Construire les index de matching.

    Returns:
        (norm_index, alias_index, prefix_freq)
    """
    # a) norm_index : normalized_name → [entity_ids]
    norm_index: Dict[str, List[str]] = {}
    for e in entities:
        nn = e["normalized_name"]
        if nn not in norm_index:
            norm_index[nn] = []
        norm_index[nn].append(e["entity_id"])

    # b) alias_index : normalize(alias) → [entity_ids] (avec filtre qualité)
    alias_index: Dict[str, List[str]] = {}
    for e in entities:
        for alias in (e.get("aliases") or []):
            if not _alias_passes_quality(alias):
                continue
            na = _normalize(alias)
            if na not in alias_index:
                alias_index[na] = []
            alias_index[na].append(e["entity_id"])

    # c) prefix_freq : fréquence du 1er token parmi toutes les Entity
    prefix_freq = Counter()
    for e in entities:
        tokens = e["normalized_name"].split()
        if tokens:
            prefix_freq[tokens[0]] += 1

    return norm_index, alias_index, prefix_freq


# ---------------------------------------------------------------------------
# Phase 7 — Rapport
# ---------------------------------------------------------------------------

def _build_group_details(
    final_groups: List[dict],
    entities_by_id: Dict[str, dict],
    edges: List[Tuple[str, str, str, float]],
    top_n: int = 20,
) -> List[dict]:
    """Construit les détails des top N groupes pour le rapport."""
    # Index des méthodes par paire
    edge_methods: Dict[frozenset, str] = {}
    for eid1, eid2, method, _ in edges:
        edge_methods[frozenset({eid1, eid2})] = method

    details = []
    for g in final_groups[:top_n]:
        members_info = []
        for eid in sorted(g["entity_ids"], key=lambda x: entities_by_id[x].get("claim_count", 0), reverse=True):
            e = entities_by_id[eid]
            # Trouver la méthode qui a lié cette entity
            method_used = ""
            if e["name"] != g["canonical_name"]:
                for other_eid in g["entity_ids"]:
                    if other_eid == eid:
                        continue
                    pair = frozenset({eid, other_eid})
                    if pair in edge_methods:
                        method_used = edge_methods[pair]
                        break
            members_info.append({
                "name": e["name"],
                "entity_type": e["entity_type"],
                "claim_count": e.get("claim_count", 0),
                "method": method_used,
            })
        details.append({
            "canonical_name": g["canonical_name"],
            "entity_type": g["entity_type"],
            "member_count": len(g["entity_ids"]),
            "members": members_info,
        })
    return details


def print_report(
    entities: List[dict],
    edges: List[Tuple[str, str, str, float]],
    groups_before_split: List[Set[str]],
    final_groups: List[dict],
    entities_by_id: Dict[str, dict],
):
    """Phase 7 — Affiche le rapport en console."""
    # Stats des edges par méthode
    method_counts = Counter(e[2] for e in edges)

    total_in_groups = sum(len(g["entity_ids"]) for g in final_groups)

    logger.info("")
    logger.info("=" * 60)
    logger.info("=== Pass C1.1 Report ===")
    logger.info("=" * 60)
    logger.info(f"Entities loaded: {len(entities)}")
    logger.info(f"Edges found: {dict(method_counts)}")
    logger.info(f"Groups formed: {len(groups_before_split)} (after union-find)")
    logger.info(f"Groups after type-split: {len(final_groups)}")
    logger.info(
        f"Entities in groups: {total_in_groups} / {len(entities)} "
        f"({100*total_in_groups/len(entities):.1f}%)" if entities else "0"
    )

    # Top 20 groupes (par taille décroissante)
    sorted_groups = sorted(final_groups, key=lambda g: len(g["entity_ids"]), reverse=True)
    details = _build_group_details(sorted_groups, entities_by_id, edges, top_n=20)

    logger.info(f"\nTop {min(20, len(details))} groups:")
    for i, d in enumerate(details, 1):
        logger.info(
            f'#{i}  canonical="{d["canonical_name"]}" '
            f'type={d["entity_type"]} members={d["member_count"]}'
        )
        for m in d["members"]:
            method_tag = f" [{m['method']}]" if m["method"] else ""
            logger.info(
                f'    - {m["name"]} ({m["entity_type"]}, {m["claim_count"]} claims){method_tag}'
            )

    # Avertissements
    warnings = []
    for g in final_groups:
        if len(g["entity_ids"]) > 50:
            warnings.append(
                f'Hub suspect: "{g["canonical_name"]}" avec {len(g["entity_ids"])} entités'
            )
    if warnings:
        logger.info(f"\n⚠ Avertissements:")
        for w in warnings:
            logger.info(f"  {w}")

    return sorted_groups, details, warnings


def write_json_report(
    output_path: str,
    final_groups: List[dict],
    entities_by_id: Dict[str, dict],
    edges: List[Tuple[str, str, str, float]],
    stats: dict,
    warnings: List[str],
):
    """Écrit le rapport au format JSON."""
    details = _build_group_details(
        sorted(final_groups, key=lambda g: len(g["entity_ids"]), reverse=True),
        entities_by_id,
        edges,
        top_n=len(final_groups),
    )
    report = {
        "stats": stats,
        "groups": details,
        "warnings": warnings,
    }
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)
    logger.info(f"\n[OSMOSE] Rapport JSON écrit : {output_path}")


# ---------------------------------------------------------------------------
# Phase 8 — Persistance Neo4j
# ---------------------------------------------------------------------------

def persist_to_neo4j(
    session,
    final_groups: List[dict],
    entities_by_id: Dict[str, dict],
    edges: List[Tuple[str, str, str, float]],
    tenant_id: str,
):
    """Phase 8 — Persiste les CanonicalEntity et SAME_CANON_AS dans Neo4j."""
    from knowbase.claimfirst.models.canonical_entity import CanonicalEntity
    from knowbase.claimfirst.models.entity import EntityType

    # 8a. Constraint
    session.run(
        """
        CREATE CONSTRAINT ce_id_unique IF NOT EXISTS
        FOR (ce:CanonicalEntity) REQUIRE ce.canonical_entity_id IS UNIQUE
        """
    )
    logger.info("[OSMOSE] Constraint ce_id_unique créée/vérifiée.")

    # Index des confidences par paire
    edge_conf: Dict[frozenset, Tuple[str, float]] = {}
    for eid1, eid2, method, conf in edges:
        pair = frozenset({eid1, eid2})
        if pair not in edge_conf or conf > edge_conf[pair][1]:
            edge_conf[pair] = (method, conf)

    created_ce = 0
    created_rel = 0
    skipped_rel = 0
    warnings = []

    for g in final_groups:
        ce_id = CanonicalEntity.make_id(tenant_id, g["canonical_name"])

        # Compter doc_count et total_mention_count
        all_doc_ids: Set[str] = set()
        total_mentions = 0
        for eid in g["entity_ids"]:
            e = entities_by_id[eid]
            all_doc_ids.update(e.get("source_doc_ids") or [])
            total_mentions += e.get("claim_count", 0)

        ce = CanonicalEntity(
            canonical_entity_id=ce_id,
            canonical_name=g["canonical_name"],
            tenant_id=tenant_id,
            entity_type=EntityType(g["entity_type"]),
            source_entity_ids=list(g["entity_ids"]),
            doc_count=len(all_doc_ids),
            total_mention_count=total_mentions,
            method=g["method"],
        )

        # 8c. MERGE CanonicalEntity
        props = ce.to_neo4j_properties()
        session.run(
            """
            MERGE (ce:CanonicalEntity {canonical_entity_id: $id})
            SET ce += $props
            """,
            id=ce_id,
            props=props,
        )
        created_ce += 1

        # 8d. Créer relations SAME_CANON_AS
        for eid in g["entity_ids"]:
            # Trouver la meilleure confidence pour cette entity
            best_method = g["method"]
            best_conf = 0.90
            for other_eid in g["entity_ids"]:
                if other_eid == eid:
                    continue
                pair = frozenset({eid, other_eid})
                if pair in edge_conf:
                    m, c = edge_conf[pair]
                    if c > best_conf:
                        best_conf = c
                        best_method = m

            # 8b. Garde anti-régression
            existing = session.run(
                """
                MATCH (e:Entity {entity_id: $eid})-[r:SAME_CANON_AS]->(ce:CanonicalEntity)
                RETURN ce.canonical_entity_id AS existing_ce_id,
                       r.confidence AS existing_conf
                """,
                eid=eid,
            ).single()

            if existing:
                if existing["existing_ce_id"] != ce_id:
                    warnings.append(
                        f'Entity "{entities_by_id[eid]["name"]}" ({eid}) '
                        f'pointe déjà vers CanonicalEntity {existing["existing_ce_id"]}'
                    )
                    continue
                if (existing["existing_conf"] or 0) >= best_conf:
                    skipped_rel += 1
                    continue

            session.run(
                """
                MATCH (e:Entity {entity_id: $eid})
                MATCH (ce:CanonicalEntity {canonical_entity_id: $ce_id})
                MERGE (e)-[r:SAME_CANON_AS]->(ce)
                SET r.method = $method,
                    r.confidence = $confidence,
                    r.created_at = datetime()
                """,
                eid=eid,
                ce_id=ce_id,
                method=best_method,
                confidence=best_conf,
            )
            created_rel += 1

    logger.info(f"\n[OSMOSE] Persistance terminée:")
    logger.info(f"  CanonicalEntity créés/mis à jour : {created_ce}")
    logger.info(f"  Relations SAME_CANON_AS créées   : {created_rel}")
    logger.info(f"  Relations skippées (anti-régression) : {skipped_rel}")
    if warnings:
        logger.info(f"  ⚠ Avertissements ({len(warnings)}):")
        for w in warnings:
            logger.info(f"    {w}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Pass C1.1 — Canonicalisation Cross-Doc des Entités"
    )
    parser.add_argument("--dry-run", action="store_true", default=True,
                        help="Afficher le rapport sans modifier (défaut)")
    parser.add_argument("--execute", action="store_true",
                        help="Persister dans Neo4j")
    parser.add_argument("--tenant", default="default",
                        help="Tenant ID (default: 'default')")
    parser.add_argument("--output-json", type=str, default=None,
                        help="Chemin du fichier JSON de rapport")
    parser.add_argument("--prefix-threshold", type=int,
                        default=PREFIX_FREQUENCY_THRESHOLD,
                        help=f"Seuil de fréquence prefix (default: {PREFIX_FREQUENCY_THRESHOLD})")
    args = parser.parse_args()

    if args.execute:
        args.dry_run = False

    prefix_threshold = args.prefix_threshold

    driver = get_neo4j_driver()

    try:
        with driver.session() as session:
            # Phase 1 — Charger les Entity
            logger.info(f"[OSMOSE] Phase 1 — Chargement des Entity (tenant={args.tenant})...")
            entities = load_entities(session, args.tenant)
            logger.info(f"  → {len(entities)} Entity chargées")

            if not entities:
                logger.info("Aucune Entity trouvée.")
                return

            entities_by_id = {e["entity_id"]: e for e in entities}

            # Phase 2 — Index
            logger.info("[OSMOSE] Phase 2 — Construction des index...")
            norm_index, alias_index, prefix_freq = build_indexes(entities)
            logger.info(f"  → norm_index: {len(norm_index)} noms normalisés")
            logger.info(f"  → alias_index: {len(alias_index)} alias qualifiés")
            top_prefixes = prefix_freq.most_common(5)
            logger.info(f"  → Top prefixes: {top_prefixes}")

            # Phase 3 — Edges candidats
            logger.info("[OSMOSE] Phase 3 — Recherche des edges candidats...")
            edges = build_candidate_edges(
                entities, norm_index, alias_index, prefix_freq,
                prefix_threshold=prefix_threshold,
            )
            method_counts = Counter(e[2] for e in edges)
            logger.info(f"  → {len(edges)} edges trouvés: {dict(method_counts)}")

            if not edges:
                logger.info("Aucun edge trouvé. Rien à canonicaliser.")
                return

            # Phase 4 — Union-Find
            logger.info("[OSMOSE] Phase 4 — Union-Find...")
            groups_before_split = union_find_groups(edges)
            logger.info(f"  → {len(groups_before_split)} groupes (avant type-split)")

            # Phase 5 — Filtrage par type
            logger.info("[OSMOSE] Phase 5 — Filtrage par compatibilité de type...")
            final_group_sets: List[Set[str]] = []
            for group in groups_before_split:
                sub_groups = split_by_type(group, entities_by_id)
                final_group_sets.extend(sub_groups)
            logger.info(f"  → {len(final_group_sets)} groupes (après type-split)")

            # Phase 6 — Élection
            logger.info("[OSMOSE] Phase 6 — Élection canonical_name + entity_type...")
            final_groups: List[dict] = []
            for group_set in final_group_sets:
                cname, etype, method = choose_canonical(group_set, entities_by_id, edges)
                final_groups.append({
                    "canonical_name": cname,
                    "entity_type": etype,
                    "method": method,
                    "entity_ids": group_set,
                })

            # Phase 7 — Rapport
            sorted_groups, details, warnings = print_report(
                entities, edges, groups_before_split, final_groups, entities_by_id,
            )

            stats = {
                "entities_loaded": len(entities),
                "edges": dict(method_counts),
                "groups_before_split": len(groups_before_split),
                "groups_after_split": len(final_groups),
                "entities_in_groups": sum(len(g["entity_ids"]) for g in final_groups),
            }

            if args.output_json:
                write_json_report(
                    args.output_json, final_groups, entities_by_id,
                    edges, stats, warnings,
                )

            # Phase 8 — Persistance ou dry-run
            if args.dry_run:
                logger.info(f"\n{'='*60}")
                logger.info("[DRY-RUN] Aucune modification effectuée.")
                logger.info(f"  → {len(final_groups)} CanonicalEntity seraient créés")
                total_rels = sum(len(g["entity_ids"]) for g in final_groups)
                logger.info(f"  → {total_rels} relations SAME_CANON_AS seraient créées")
                logger.info("  → Relancer avec --execute pour appliquer.")
                logger.info(f"{'='*60}")
                return

            logger.info(f"\n[OSMOSE] Phase 8 — Persistance Neo4j...")
            persist_to_neo4j(session, final_groups, entities_by_id, edges, args.tenant)
            logger.info("\n[OSMOSE] Pass C1.1 terminé avec succès.")

    finally:
        driver.close()


if __name__ == "__main__":
    main()
