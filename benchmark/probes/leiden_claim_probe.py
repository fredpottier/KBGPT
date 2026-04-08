"""
Probe exploratoire — community detection structurelle sur Claim ↔ Claim.

OBJECTIF
────────
Valider empiriquement si le signal STRUCTUREL (Claims reliés via Entities
partagées) produit des communautés cohérentes et exploitables dans OSMOSIS,
comme complement (ou alternative) au clustering SEMANTIQUE actuel de la
couche Perspective V2 (HDBSCAN sur embeddings).

Question de recherche : est-ce qu'un graphe Claim ↔ Claim pondéré par le
nombre d'entités communes donne une topologie riche, ou au contraire une
giant component inutilisable ?

MÉTHODE
───────
1. Charger tous les Claims du tenant default depuis Neo4j, avec leurs Entities
2. Construire le graphe Claim ↔ Claim : arête si au moins MIN_SHARED_ENTITIES
   entités partagées, poids = nombre d'entités partagées
3. Analyse topologique : taille de la giant component, distribution des degrés,
   densité, modularité intuitive
4. Community detection via Louvain (networkx 3.x built-in, proxy raisonnable
   pour Leiden à ce stade exploratoire)
5. Comparer la distribution des tailles de communautés obtenues avec la
   distribution des tailles des Perspectives V2 actuelles
6. Pour les 3-5 plus grosses communautés, afficher un échantillon de Claims
   pour évaluation qualitative humaine

USAGE
─────
    docker exec knowbase-app python benchmark/probes/leiden_claim_probe.py
    docker exec knowbase-app python benchmark/probes/leiden_claim_probe.py --min-shared 5
    docker exec knowbase-app python benchmark/probes/leiden_claim_probe.py --max-claims 5000

SORTIE
──────
Rapport texte sur stdout + dump JSON des résultats dans
data/benchmark/results/leiden_probe_<timestamp>.json.

NOTE : ce n'est pas du Leiden, c'est du Louvain (NetworkX built-in). Le
signal qu'on cherche (structure exploitable ou non) ne dépend pas de la
garantie well-connectedness spécifique à Leiden. Si le probe est concluant,
on installera leidenalg pour un second passage plus rigoureux.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import random
import sys
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any

import networkx as nx
from networkx.algorithms import community as nx_community

# Ajouter le root du projet au path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from neo4j import GraphDatabase

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)

NEO4J_URI = os.getenv("NEO4J_URI", "bolt://neo4j:7687")
NEO4J_USER = os.getenv("NEO4J_USER", "neo4j")
NEO4J_PASSWORD = os.getenv("NEO4J_PASSWORD", "graphiti_neo4j_pass")
TENANT_ID = os.getenv("TENANT_ID", "default")


# ────────────────────────────────────────────────────────────────────────
# Collecte des données
# ────────────────────────────────────────────────────────────────────────


def load_claims_with_entities(driver, tenant_id: str, max_claims: int | None = None) -> dict[str, dict]:
    """
    Charge les Claims et leurs Entities depuis Neo4j.

    Retourne : {claim_id: {"text": ..., "entity_ids": [...], "doc_id": ...}}
    """
    limit_clause = f"LIMIT {max_claims}" if max_claims else ""

    # Note : la relation Claim -> Entity est `ABOUT` dans ce schema (pas MENTIONS).
    # Le doc_id est stocke en propriete directe sur le Claim (pas de relation
    # explicite Claim -> Document dans notre modele).
    query = f"""
    MATCH (c:Claim)
    WHERE c.tenant_id = $tenant_id
    OPTIONAL MATCH (c)-[:ABOUT]->(e:Entity)
    WITH c, collect(DISTINCT e.entity_id) AS entity_ids
    RETURN c.claim_id AS claim_id,
           c.text AS text,
           c.doc_id AS doc_id,
           entity_ids
    {limit_clause}
    """

    claims = {}
    with driver.session() as session:
        result = session.run(query, tenant_id=tenant_id)
        for record in result:
            cid = record["claim_id"]
            if not cid:
                continue
            claims[cid] = {
                "text": record["text"] or "",
                "doc_id": record["doc_id"] or "",
                "entity_ids": [e for e in record["entity_ids"] if e],
            }

    logger.info(f"Loaded {len(claims)} claims from Neo4j")
    return claims


def load_existing_perspectives(driver, tenant_id: str) -> list[dict]:
    """Charge les Perspectives V2 existantes pour comparer les distributions."""
    query = """
    MATCH (p:Perspective)
    WHERE p.tenant_id = $tenant_id
    RETURN p.label AS label, p.claim_count AS claim_count
    ORDER BY p.claim_count DESC
    """
    perspectives = []
    with driver.session() as session:
        for record in session.run(query, tenant_id=tenant_id):
            perspectives.append({
                "label": record["label"],
                "claim_count": record["claim_count"] or 0,
            })
    return perspectives


# ────────────────────────────────────────────────────────────────────────
# Construction du graphe
# ────────────────────────────────────────────────────────────────────────


def build_claim_graph(claims: dict[str, dict], min_shared: int = 2) -> nx.Graph:
    """
    Construit le graphe Claim ↔ Claim via entités partagées.

    Arête (c1, c2) si |entities(c1) ∩ entities(c2)| >= min_shared.
    Poids de l'arête = nombre d'entités partagées.

    Implémentation efficace : index inversé Entity → [Claims], puis pour
    chaque entité on génère des candidats et on compte les partages.
    """
    # Index inversé Entity → set(claim_ids)
    entity_to_claims: dict[str, set[str]] = defaultdict(set)
    for cid, claim in claims.items():
        for eid in claim["entity_ids"]:
            entity_to_claims[eid].add(cid)

    # Filtrer les entités trop génériques (présentes dans > 30% des claims)
    # pour éviter qu'elles inondent tout
    n_claims = len(claims)
    generic_threshold = max(int(n_claims * 0.30), 50)
    generic_entities = {eid for eid, cids in entity_to_claims.items() if len(cids) > generic_threshold}
    logger.info(
        f"Filtering {len(generic_entities)} generic entities "
        f"(present in > {generic_threshold} claims out of {n_claims})"
    )

    # Compter les partages entre paires de claims
    pair_shared: dict[tuple[str, str], int] = defaultdict(int)
    for eid, cids in entity_to_claims.items():
        if eid in generic_entities:
            continue
        if len(cids) < 2:
            continue
        cid_list = sorted(cids)
        for i in range(len(cid_list)):
            for j in range(i + 1, len(cid_list)):
                pair_shared[(cid_list[i], cid_list[j])] += 1

    logger.info(f"Computed {len(pair_shared)} candidate pairs")

    # Construire le graphe NetworkX
    G = nx.Graph()
    for cid in claims.keys():
        G.add_node(cid)

    n_edges = 0
    for (c1, c2), weight in pair_shared.items():
        if weight >= min_shared:
            G.add_edge(c1, c2, weight=weight)
            n_edges += 1

    logger.info(f"Built graph: {G.number_of_nodes()} nodes, {n_edges} edges "
                f"(min_shared={min_shared})")
    return G


# ────────────────────────────────────────────────────────────────────────
# Analyse topologique
# ────────────────────────────────────────────────────────────────────────


def analyze_topology(G: nx.Graph) -> dict[str, Any]:
    """Analyse topologique du graphe avant community detection."""
    n = G.number_of_nodes()
    m = G.number_of_edges()

    # Composantes connexes
    components = list(nx.connected_components(G))
    components.sort(key=len, reverse=True)

    giant_size = len(components[0]) if components else 0
    giant_ratio = giant_size / n if n > 0 else 0

    # Isolated nodes
    isolated = sum(1 for size in (len(c) for c in components) if size == 1)

    # Densité
    density = nx.density(G)

    # Distribution des degrés (hors isolés)
    degrees = [d for _, d in G.degree() if d > 0]
    avg_degree = sum(degrees) / len(degrees) if degrees else 0
    max_degree = max(degrees) if degrees else 0

    return {
        "n_nodes": n,
        "n_edges": m,
        "n_components": len(components),
        "giant_component_size": giant_size,
        "giant_component_ratio": round(giant_ratio, 3),
        "n_isolated_nodes": isolated,
        "density": round(density, 6),
        "avg_degree_non_isolated": round(avg_degree, 2),
        "max_degree": max_degree,
        "component_sizes_top10": [len(c) for c in components[:10]],
    }


# ────────────────────────────────────────────────────────────────────────
# Community detection
# ────────────────────────────────────────────────────────────────────────


def detect_communities(G: nx.Graph, seed: int = 42) -> list[set[str]]:
    """
    Louvain community detection (proxy exploratoire pour Leiden).

    On travaille uniquement sur la giant component, les isolés et petites
    composantes ne rentrent dans aucune communauté.
    """
    components = list(nx.connected_components(G))
    components.sort(key=len, reverse=True)

    if not components or len(components[0]) < 10:
        logger.warning("Graph too fragmented for meaningful community detection")
        return []

    giant = G.subgraph(components[0]).copy()
    logger.info(
        f"Running Louvain on giant component "
        f"({giant.number_of_nodes()} nodes, {giant.number_of_edges()} edges)..."
    )

    communities = nx_community.louvain_communities(
        giant, weight="weight", resolution=1.0, seed=seed
    )
    communities = sorted(communities, key=len, reverse=True)
    logger.info(f"Louvain found {len(communities)} communities")

    return communities


# ────────────────────────────────────────────────────────────────────────
# Analyse qualitative
# ────────────────────────────────────────────────────────────────────────


def summarize_community(
    community: set[str],
    claims: dict[str, dict],
    sample_size: int = 5,
) -> dict[str, Any]:
    """Résumé qualitatif d'une communauté : taille, docs couverts, échantillon."""
    cids = list(community)

    # Distribution des docs
    doc_counter: Counter[str] = Counter()
    entity_counter: Counter[str] = Counter()
    for cid in cids:
        claim = claims.get(cid, {})
        if claim.get("doc_id"):
            doc_counter[claim["doc_id"]] += 1
        for eid in claim.get("entity_ids", []):
            entity_counter[eid] += 1

    # Échantillon de claims représentatifs
    random.seed(42)
    sample_cids = random.sample(cids, min(sample_size, len(cids)))
    sample_texts = [
        claims.get(cid, {}).get("text", "")[:200] for cid in sample_cids
    ]

    return {
        "size": len(cids),
        "n_distinct_docs": len(doc_counter),
        "top_docs": doc_counter.most_common(5),
        "top_entities": entity_counter.most_common(8),
        "sample_claims": sample_texts,
    }


def compare_with_perspectives(
    communities: list[set[str]],
    perspectives: list[dict],
) -> dict[str, Any]:
    """Compare les distributions de tailles Louvain vs Perspective V2 actuelles."""
    louvain_sizes = sorted([len(c) for c in communities], reverse=True)
    persp_sizes = sorted([p["claim_count"] for p in perspectives], reverse=True)

    def stats(sizes):
        if not sizes:
            return {"n": 0, "min": 0, "max": 0, "median": 0, "total_covered": 0}
        n = len(sizes)
        return {
            "n": n,
            "min": sizes[-1],
            "max": sizes[0],
            "median": sizes[n // 2],
            "total_covered": sum(sizes),
        }

    return {
        "louvain": stats(louvain_sizes),
        "perspective_v2": stats(persp_sizes),
        "louvain_size_distribution_top20": louvain_sizes[:20],
        "perspective_size_distribution_top20": persp_sizes[:20],
    }


# ────────────────────────────────────────────────────────────────────────
# Main
# ────────────────────────────────────────────────────────────────────────


def main():
    parser = argparse.ArgumentParser(description="Probe community detection on Claim graph")
    parser.add_argument("--min-shared", type=int, default=3,
                        help="Min shared entities for an edge (default: 3)")
    parser.add_argument("--max-claims", type=int, default=None,
                        help="Max claims to load (default: all)")
    parser.add_argument("--sample-size", type=int, default=5,
                        help="Claims per community in qualitative sample (default: 5)")
    parser.add_argument("--top-communities", type=int, default=10,
                        help="Top N communities to detail (default: 10)")
    args = parser.parse_args()

    driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))

    try:
        # ── 1. Chargement
        claims = load_claims_with_entities(driver, TENANT_ID, args.max_claims)
        if not claims:
            logger.error("No claims loaded — aborting")
            return 1

        perspectives = load_existing_perspectives(driver, TENANT_ID)
        logger.info(f"Loaded {len(perspectives)} existing Perspectives for comparison")

        # ── 2. Construction du graphe
        G = build_claim_graph(claims, min_shared=args.min_shared)

        # ── 3. Analyse topologique
        topology = analyze_topology(G)
        logger.info(f"Topology: {json.dumps(topology, indent=2)}")

        # ── 4. Community detection
        communities = detect_communities(G)

        # ── 5. Comparaison distributions
        comparison = compare_with_perspectives(communities, perspectives)

        # ── 6. Qualitatif sur top N communautés
        top_summaries = []
        for i, comm in enumerate(communities[:args.top_communities]):
            summary = summarize_community(comm, claims, sample_size=args.sample_size)
            summary["rank"] = i + 1
            top_summaries.append(summary)

        # ── Rapport texte
        print("\n" + "=" * 76)
        print(" LEIDEN/LOUVAIN PROBE — Community detection on Claim graph")
        print("=" * 76)
        print(f"\nParameters: min_shared_entities={args.min_shared}, "
              f"max_claims={args.max_claims or 'all'}")
        print(f"\nTopology:")
        for k, v in topology.items():
            print(f"  {k:<32} = {v}")

        print(f"\nDistribution comparison:")
        print(f"  Louvain communities       : n={comparison['louvain']['n']}, "
              f"median={comparison['louvain']['median']}, "
              f"max={comparison['louvain']['max']}, "
              f"total_covered={comparison['louvain']['total_covered']}")
        print(f"  Perspective V2 (existing) : n={comparison['perspective_v2']['n']}, "
              f"median={comparison['perspective_v2']['median']}, "
              f"max={comparison['perspective_v2']['max']}, "
              f"total_covered={comparison['perspective_v2']['total_covered']}")
        print(f"  Top-20 Louvain sizes      : {comparison['louvain_size_distribution_top20']}")
        print(f"  Top-20 Perspective sizes  : {comparison['perspective_size_distribution_top20']}")

        print(f"\nTop {len(top_summaries)} Louvain communities (qualitative sample):")
        for s in top_summaries:
            print(f"\n  ── Community #{s['rank']} — {s['size']} claims, "
                  f"{s['n_distinct_docs']} docs ──")
            print(f"    Top docs     : {s['top_docs'][:3]}")
            print(f"    Top entities : {[e[0] for e in s['top_entities'][:5]]}")
            print(f"    Samples:")
            for txt in s["sample_claims"]:
                print(f"      • {txt}")

        # ── Dump JSON
        out_dir = Path("/app/data/benchmark/results")
        out_dir.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        out_file = out_dir / f"leiden_probe_{timestamp}.json"

        with open(out_file, "w", encoding="utf-8") as f:
            json.dump({
                "timestamp": timestamp,
                "parameters": {
                    "min_shared": args.min_shared,
                    "max_claims": args.max_claims,
                },
                "topology": topology,
                "comparison": comparison,
                "top_communities": top_summaries,
            }, f, indent=2, default=str)

        print(f"\n[OK] Full report saved to: {out_file}")
        print("=" * 76 + "\n")

        return 0

    finally:
        driver.close()


if __name__ == "__main__":
    sys.exit(main())
