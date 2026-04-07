"""
Phase A4 — Probe diagnostic : clustering GLOBAL du corpus.

Question testee :
> Si on lance HDBSCAN sur TOUS les claims du corpus (15566), sans aucun
  filtre par sujet ni par facet, est-ce que des themes thematiques
  emergent naturellement par densite ?

Methode :
1. Charge tous les claims du corpus avec embeddings
2. Reduction dimension via UMAP (1024 -> 10-20 dim) — necessaire pour HDBSCAN
3. Clustering HDBSCAN avec min_cluster_size adapte
4. Pour chaque cluster significatif :
   - Echantillon de claims
   - Facets dominantes
   - Documents sources
5. Verdict : combien de clusters coherents emergent ? Quel % en noise ?

Si emergence reussie -> Option C (theme-scoped) techniquement viable.
Sinon -> il faudra explorer BERTopic ou repenser plus en profondeur.

⚠️ DIAGNOSTIC SEULEMENT — script exploratoire, pas pour la prod.
"""

import json
import os
import time
from collections import Counter
from datetime import datetime

import numpy as np
from neo4j import GraphDatabase

NEO4J_URI = "bolt://neo4j:7687"
NEO4J_USER = "neo4j"
NEO4J_PASSWORD = "graphiti_neo4j_pass"


def fetch_all_claims_with_embeddings(driver) -> list:
    """Charge tous les claims du corpus avec leurs embeddings."""
    print("Chargement des claims...")
    with driver.session() as session:
        result = session.run("""
            MATCH (c:Claim {tenant_id: 'default'})
            WHERE c.embedding IS NOT NULL
            OPTIONAL MATCH (c)-[:BELONGS_TO_FACET]->(f:Facet)
            RETURN c.claim_id AS cid,
                   c.text AS text,
                   c.doc_id AS doc_id,
                   c.embedding AS embedding,
                   collect(DISTINCT f.facet_name) AS facet_names
        """)
        claims = []
        for r in result:
            claims.append({
                "claim_id": r["cid"],
                "text": r["text"] or "",
                "doc_id": r["doc_id"] or "",
                "embedding": r["embedding"],
                "facet_names": [f for f in r["facet_names"] if f],
            })
    print(f"  Charges : {len(claims)} claims")
    return claims


def reduce_dimension_umap(embeddings: np.ndarray, target_dim: int = 15) -> np.ndarray:
    """Reduit la dimension via UMAP."""
    import umap
    print(f"Reduction UMAP : {embeddings.shape[1]} -> {target_dim} dimensions...")
    start = time.time()
    reducer = umap.UMAP(
        n_components=target_dim,
        n_neighbors=30,
        min_dist=0.0,
        metric="cosine",
        random_state=42,
    )
    reduced = reducer.fit_transform(embeddings)
    print(f"  UMAP termine en {time.time() - start:.1f}s")
    return reduced


def cluster_hdbscan(reduced: np.ndarray, min_cluster_size: int = 30) -> np.ndarray:
    """Clustering HDBSCAN."""
    import hdbscan
    print(f"HDBSCAN min_cluster_size={min_cluster_size}...")
    start = time.time()
    clusterer = hdbscan.HDBSCAN(
        min_cluster_size=min_cluster_size,
        min_samples=5,
        metric="euclidean",
        cluster_selection_method="eom",
    )
    labels = clusterer.fit_predict(reduced)
    print(f"  HDBSCAN termine en {time.time() - start:.1f}s")
    return labels


def analyze_cluster(claims: list, cluster_id: int) -> dict:
    """Analyse un cluster : facets, docs, echantillon."""
    facet_counter = Counter()
    doc_counter = Counter()
    for c in claims:
        for fn in c.get("facet_names", []):
            facet_counter[fn] += 1
        if c.get("doc_id"):
            doc_counter[c["doc_id"]] += 1

    sample_size = min(7, len(claims))
    if len(claims) <= sample_size:
        sample = claims
    else:
        step = len(claims) // sample_size
        sample = [claims[i * step] for i in range(sample_size)]

    return {
        "cluster_id": cluster_id,
        "size": len(claims),
        "n_docs": len(doc_counter),
        "top_facets": facet_counter.most_common(5),
        "top_docs": [d[:60] for d, _ in doc_counter.most_common(3)],
        "samples": [c["text"][:200] for c in sample],
    }


def run_probe(min_cluster_size: int = 30, target_dim: int = 15):
    print("=" * 80)
    print("PROBE A4 — Clustering GLOBAL HDBSCAN du corpus")
    print("=" * 80)
    print(f"Config : min_cluster_size={min_cluster_size}, UMAP target_dim={target_dim}")
    print()

    driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))

    # 1. Charger tous les claims
    claims = fetch_all_claims_with_embeddings(driver)
    if not claims:
        print("Aucun claim trouve")
        return

    # 2. Construire la matrice d'embeddings
    embeddings = np.array([c["embedding"] for c in claims])
    print(f"Matrice embeddings : {embeddings.shape}")

    # 3. Reduction UMAP
    reduced = reduce_dimension_umap(embeddings, target_dim=target_dim)

    # 4. HDBSCAN
    labels = cluster_hdbscan(reduced, min_cluster_size=min_cluster_size)

    # 5. Analyser
    unique_labels = set(labels)
    n_clusters = len(unique_labels) - (1 if -1 in unique_labels else 0)
    n_noise = int(np.sum(labels == -1))
    noise_ratio = n_noise / len(claims)

    print()
    print("=" * 80)
    print("RESULTATS")
    print("=" * 80)
    print(f"Total claims    : {len(claims)}")
    print(f"Clusters trouves: {n_clusters}")
    print(f"Noise (outliers): {n_noise} ({noise_ratio:.1%})")

    # Distribution des tailles
    cluster_sizes = []
    for label in unique_labels:
        if label != -1:
            size = int(np.sum(labels == label))
            cluster_sizes.append((label, size))
    cluster_sizes.sort(key=lambda x: -x[1])

    if cluster_sizes:
        sizes_only = [s for _, s in cluster_sizes]
        print(f"Tailles min/max : {min(sizes_only)} / {max(sizes_only)}")
        print(f"Taille mediane  : {sorted(sizes_only)[len(sizes_only)//2]}")
        print(f"Distribution top 20 : {sizes_only[:20]}")

    # Analyser les top clusters
    print()
    print("=" * 80)
    print("TOP 15 CLUSTERS — Echantillon thematique")
    print("=" * 80)

    cluster_analyses = []
    for cluster_id, size in cluster_sizes[:15]:
        cluster_claims = [claims[i] for i in range(len(claims)) if labels[i] == cluster_id]
        analysis = analyze_cluster(cluster_claims, int(cluster_id))
        cluster_analyses.append(analysis)

        facets_str = ", ".join(f"{f}({n})" for f, n in analysis["top_facets"][:3])
        print()
        print(f"── Cluster {analysis['cluster_id']} : {analysis['size']} claims, {analysis['n_docs']} docs")
        print(f"   Facets : {facets_str}")
        print(f"   Echantillon :")
        for s in analysis["samples"][:5]:
            print(f"     - {s}")

    driver.close()

    # Sauvegarde
    output = {
        "timestamp": datetime.utcnow().isoformat(),
        "config": {
            "min_cluster_size": min_cluster_size,
            "target_dim": target_dim,
        },
        "summary": {
            "total_claims": len(claims),
            "n_clusters": n_clusters,
            "n_noise": n_noise,
            "noise_ratio": round(noise_ratio, 3),
            "cluster_sizes_top20": [s for _, s in cluster_sizes[:20]],
        },
        "top_clusters": cluster_analyses,
    }
    output_path = "global_clustering_report.json"
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    print(f"\nRapport sauvegarde : {output_path}")


if __name__ == "__main__":
    import sys
    min_cluster = int(sys.argv[1]) if len(sys.argv) > 1 else 30
    target_dim = int(sys.argv[2]) if len(sys.argv) > 2 else 15
    run_probe(min_cluster_size=min_cluster, target_dim=target_dim)
