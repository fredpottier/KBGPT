#!/usr/bin/env python3
"""
Pass C1.3 — Canonicalisation par Embedding Clustering.

Strategie :
1. Charger les entites orphelines
2. Calculer les embeddings (e5-large) de chaque nom d'entite
3. Clustering par cosine similarity (seuil configurable)
4. Pour chaque cluster > 1 : elire le representant, creer CanonicalEntity
5. Mettre a jour les relations SIMILAR_TO avec le vrai score cosine

Usage :
    python scripts/canonicalize_embedding_clusters.py --dry-run --tenant default
    python scripts/canonicalize_embedding_clusters.py --execute --tenant default
    python scripts/canonicalize_embedding_clusters.py --execute --tenant default --threshold 0.90
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from collections import defaultdict
from typing import Any

import numpy as np

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

# Seuil de similarite cosine — pairs au-dessus sont candidats au clustering.
# Garde un seuil bas (0.88) pour couvrir les synonymies lointaines (personal
# data <> personal information). La validation LLM filtre les faux positifs.
DEFAULT_THRESHOLD = 0.88


def load_orphan_entities(driver, tenant_id: str) -> list[dict]:
    """Charge les entites non rattachees a un CanonicalEntity."""
    query = """
    MATCH (e:Entity {tenant_id: $tid})
    WHERE NOT (e)-[:SAME_CANON_AS]->(:CanonicalEntity)
    OPTIONAL MATCH (e)<-[:ABOUT]-(c:Claim)
    WITH e, count(c) AS claim_count
    RETURN e.name AS name, e.entity_id AS entity_id, elementId(e) AS eid, claim_count
    ORDER BY claim_count DESC
    """
    with driver.session() as session:
        result = session.run(query, tid=tenant_id)
        return [dict(r) for r in result]


def compute_embeddings(names: list[str], batch_size: int = 64) -> np.ndarray:
    """Calcule les embeddings e5-large pour une liste de noms."""
    from sentence_transformers import SentenceTransformer

    logger.info(f"[C1.3] Loading embedding model...")
    model = SentenceTransformer("intfloat/multilingual-e5-large")

    logger.info(f"[C1.3] Computing embeddings for {len(names)} entities...")
    # e5-large attend le prefix "query: " pour les queries
    prefixed = [f"query: {n}" for n in names]
    embeddings = model.encode(prefixed, batch_size=batch_size, show_progress_bar=True)

    return np.array(embeddings)


def cluster_by_cosine(
    embeddings: np.ndarray,
    entities: list[dict],
    threshold: float,
) -> list[list[int]]:
    """Clustering agglomeratif par cosine similarity.

    Retourne des groupes d'indices (1-indexed dans la matrice).
    """
    n = len(entities)
    if n == 0:
        return []

    # Normaliser pour cosine
    norms = np.linalg.norm(embeddings, axis=1, keepdims=True)
    norms[norms == 0] = 1
    normed = embeddings / norms

    # Union-Find
    parent = list(range(n))

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a, b):
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[ra] = rb

    # Comparer par batches pour eviter la matrice complete (n^2 RAM)
    BATCH = 500
    pair_count = 0

    for start_i in range(0, n, BATCH):
        end_i = min(start_i + BATCH, n)
        batch_a = normed[start_i:end_i]

        for start_j in range(start_i, n, BATCH):
            end_j = min(start_j + BATCH, n)
            batch_b = normed[start_j:end_j]

            # Cosine similarity matrix (batch_a x batch_b)
            sim = batch_a @ batch_b.T

            for local_i in range(sim.shape[0]):
                global_i = start_i + local_i
                j_start = local_i + 1 if start_i == start_j else 0
                for local_j in range(j_start, sim.shape[1]):
                    global_j = start_j + local_j
                    if global_i >= global_j:
                        continue
                    if sim[local_i, local_j] >= threshold:
                        union(global_i, global_j)
                        pair_count += 1

    logger.info(f"[C1.3] Found {pair_count} pairs above threshold {threshold}")

    # Extraire les groupes
    groups = defaultdict(list)
    for i in range(n):
        groups[find(i)].append(i)

    # Retourner seulement les groupes > 1
    return [indices for indices in groups.values() if len(indices) > 1]


def persist_clusters(driver, tenant_id: str, clusters: list[dict]):
    """Persiste les clusters dans Neo4j."""
    query_create = """
    CREATE (ce:CanonicalEntity {
        tenant_id: $tid,
        name: $name,
        source: 'c1.3_embedding_cluster',
        created_at: datetime()
    })
    RETURN elementId(ce) AS ceid
    """
    query_link = """
    MATCH (e:Entity {tenant_id: $tid})
    WHERE elementId(e) = $eid
    MATCH (ce:CanonicalEntity {tenant_id: $tid})
    WHERE elementId(ce) = $ceid
    MERGE (e)-[:SAME_CANON_AS]->(ce)
    """
    query_update_similar = """
    MATCH (e1:Entity {tenant_id: $tid})-[r:SIMILAR_TO]-(e2:Entity {tenant_id: $tid})
    WHERE elementId(e1) = $eid1 AND elementId(e2) = $eid2
    SET r.cosine_score = $score
    """

    with driver.session() as session:
        created = 0
        linked = 0
        for cluster in clusters:
            result = session.run(query_create, tid=tenant_id, name=cluster["winner_name"])
            ceid = result.single()["ceid"]
            created += 1

            for member in cluster["members"]:
                session.run(query_link, tid=tenant_id, eid=member["eid"], ceid=ceid)
                linked += 1

            # Update SIMILAR_TO scores between members
            for pair in cluster.get("scored_pairs", []):
                session.run(
                    query_update_similar,
                    tid=tenant_id,
                    eid1=pair["eid1"],
                    eid2=pair["eid2"],
                    score=pair["score"],
                )

    return created, linked


def run(
    tenant_id: str,
    dry_run: bool = True,
    threshold: float = DEFAULT_THRESHOLD,
    skip_llm: bool = False,
    llm_batch_size: int = 8,
    max_cluster_size: int = 10,
):
    """Execute la canonicalisation par embedding clustering avec validation LLM."""
    from neo4j import GraphDatabase

    neo4j_uri = os.getenv("NEO4J_URI", "bolt://localhost:7687")
    neo4j_user = os.getenv("NEO4J_USER", "neo4j")
    neo4j_pass = os.getenv("NEO4J_PASSWORD", "graphiti_neo4j_pass")

    driver = GraphDatabase.driver(neo4j_uri, auth=(neo4j_user, neo4j_pass))

    # 1. Charger les orphelins
    orphans = load_orphan_entities(driver, tenant_id)
    logger.info(f"[C1.3] {len(orphans)} orphan entities loaded")

    if not orphans:
        logger.info("[C1.3] No orphans to process")
        driver.close()
        return

    # 2. Calculer les embeddings
    names = [e["name"] for e in orphans]
    embeddings = compute_embeddings(names)

    # 3. Clustering
    logger.info(f"[C1.3] Clustering with cosine threshold {threshold}...")
    groups = cluster_by_cosine(embeddings, orphans, threshold)
    logger.info(f"[C1.3] {len(groups)} raw clusters formed")

    # Filtrer les clusters trop gros (signal d'une chaine transitive explosive)
    clean_groups = [g for g in groups if 2 <= len(g) <= max_cluster_size]
    if len(clean_groups) < len(groups):
        logger.info(
            f"[C1.3] {len(groups) - len(clean_groups)} clusters filtres "
            f"(taille > {max_cluster_size}, chaine transitive suspecte)"
        )

    # 4. Preparer les merge groups
    norms = np.linalg.norm(embeddings, axis=1, keepdims=True)
    norms[norms == 0] = 1
    normed = embeddings / norms

    clusters_raw = []
    for indices in clean_groups:
        members = [orphans[i] for i in indices]
        winner = max(members, key=lambda m: m["claim_count"])
        scored_pairs = []
        for k in range(len(indices)):
            for l in range(k + 1, len(indices)):
                score = float(normed[indices[k]] @ normed[indices[l]])
                scored_pairs.append({
                    "eid1": orphans[indices[k]]["eid"],
                    "eid2": orphans[indices[l]]["eid"],
                    "score": round(score, 4),
                })
        clusters_raw.append({
            "winner_name": winner["name"],
            "members": members,
            "scored_pairs": scored_pairs,
            "size": len(members),
        })

    # 5. Validation LLM (sauf --skip-llm)
    if skip_llm or not clusters_raw:
        clusters_to_persist = clusters_raw
        logger.info(
            f"[C1.3] LLM validation SKIPPED — {len(clusters_raw)} clusters persisted as-is"
        )
    else:
        clusters_to_persist = _llm_validate_clusters(clusters_raw, llm_batch_size)
        logger.info(
            f"[C1.3] LLM validation : {len(clusters_to_persist)}/{len(clusters_raw)} "
            f"clusters approuves"
        )

    total_entities = sum(c["size"] for c in clusters_to_persist)
    clusters_to_persist.sort(key=lambda c: c["size"], reverse=True)

    # 6. Rapport
    logger.info(
        f"\n[C1.3] {len(clusters_to_persist)} clusters approuves, "
        f"{total_entities} entities to link"
    )
    for c in clusters_to_persist[:20]:
        names_list = sorted([m["name"] for m in c["members"]])
        logger.info(f"  Cluster ({c['size']}): winner='{c['winner_name']}'")
        for n in names_list[:5]:
            if n != c["winner_name"]:
                logger.info(f"    - {n}")
        if len(names_list) > 5:
            logger.info(f"    ... +{len(names_list) - 5} more")
    if len(clusters_to_persist) > 20:
        logger.info(f"  ... +{len(clusters_to_persist) - 20} more clusters")

    # 7. Executer ou dry-run
    if dry_run:
        logger.info(
            f"\n[C1.3] DRY-RUN: {len(clusters_to_persist)} clusters, "
            f"{total_entities} entities would be linked"
        )
        logger.info("  → Relancer avec --execute pour appliquer.")
    else:
        created, linked = persist_clusters(driver, tenant_id, clusters_to_persist)
        logger.info(
            f"\n[C1.3] EXECUTED: {created} new canonicals created, {linked} entities linked"
        )

    driver.close()


def _llm_validate_clusters(
    clusters_raw: list[dict], batch_size: int
) -> list[dict]:
    """Filtre les clusters via LLMMergeValidator. Applique les decisions."""
    from knowbase.claimfirst.canonicalization.merge_validator import (
        LLMMergeValidator,
        MergeCandidate,
        MergeMember,
    )

    candidates = []
    for idx, c in enumerate(clusters_raw):
        members_mc = []
        for m in c["members"]:
            members_mc.append(
                MergeMember(
                    entity_id=m["eid"],
                    name=m["name"],
                    claim_count=m.get("claim_count", 0) or 0,
                    entity_type=m.get("entity_type", "other"),
                )
            )
        candidates.append(
            MergeCandidate(
                group_id=idx,
                members=members_mc,
                source_method="embedding_cluster",
            )
        )

    validator = LLMMergeValidator(batch_size=batch_size)
    decisions = validator.validate_groups(candidates)
    dec_by_gid = {d.group_id: d for d in decisions}

    approved: list[dict] = []
    for idx, c in enumerate(clusters_raw):
        dec = dec_by_gid.get(idx)
        if dec is None:
            continue

        if dec.decision == "merge" and len(dec.approved_entity_ids) >= 2:
            # Garder tous les membres
            if dec.canonical:
                # Override du winner si le LLM propose un nom explicite
                canonical_member = next(
                    (m for m in c["members"] if m["name"] == dec.canonical),
                    None,
                )
                if canonical_member is None:
                    # Le nom LLM n'est pas dans les members — garder un membre
                    # existant avec le nom LLM comme canonique
                    c = {**c, "winner_name": dec.canonical}
                else:
                    c = {**c, "winner_name": canonical_member["name"]}
            approved.append(c)
        elif dec.decision == "partial_merge" and len(dec.approved_entity_ids) >= 2:
            # Filtrer les members au sous-groupe approuve
            approved_members = [
                m for m in c["members"] if m["eid"] in dec.approved_entity_ids
            ]
            approved_pairs = [
                p
                for p in c.get("scored_pairs", [])
                if p["eid1"] in dec.approved_entity_ids
                and p["eid2"] in dec.approved_entity_ids
            ]
            if len(approved_members) >= 2:
                winner = (
                    dec.canonical
                    or max(approved_members, key=lambda m: m["claim_count"])["name"]
                )
                approved.append(
                    {
                        "winner_name": winner,
                        "members": approved_members,
                        "scored_pairs": approved_pairs,
                        "size": len(approved_members),
                    }
                )
        # else: keep_separate → discard

    return approved


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="C1.3 — Embedding Clustering Canonicalization")
    parser.add_argument("--tenant", default="default")
    parser.add_argument("--dry-run", action="store_true", default=True)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--threshold", type=float, default=DEFAULT_THRESHOLD,
                        help=f"Cosine similarity threshold (default: {DEFAULT_THRESHOLD})")
    parser.add_argument("--skip-llm", action="store_true",
                        help="Skip LLM validation (DANGEROUS, tests only)")
    parser.add_argument("--llm-batch-size", type=int, default=8)
    parser.add_argument("--max-cluster-size", type=int, default=10,
                        help="Clusters > N filtres (chaine transitive suspecte)")
    args = parser.parse_args()

    if args.execute:
        args.dry_run = False

    run(
        tenant_id=args.tenant,
        dry_run=args.dry_run,
        threshold=args.threshold,
        skip_llm=args.skip_llm,
        llm_batch_size=args.llm_batch_size,
        max_cluster_size=args.max_cluster_size,
    )
