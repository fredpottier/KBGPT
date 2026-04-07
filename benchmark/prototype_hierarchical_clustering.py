"""
Prototype Phase A2 : sous-clustering hierarchique des meta-Perspectives.

Hypothese a tester (H1) :
> Le probleme actuel vient d'un clustering trop plat. En sous-cluterisant
  les meta-Perspectives, on devrait faire emerger des sous-axes coherents
  (Securite reseau, Authentification, Outils migration, etc.)

Methode :
1. Charge les claims d'une meta-Perspective via Neo4j (avec leurs embeddings)
2. Sous-clusterise ces claims avec clustering agglomeratif (target k=6-10)
3. Pour chaque sous-cluster :
   - Echantillonne les claims representatifs
   - Affiche les facets dominantes
   - Permet une evaluation manuelle de coherence thematique

Output : prototype_clustering_report.json + affichage console
"""

import json
import os
import sys
from collections import Counter
from datetime import datetime

import numpy as np
from neo4j import GraphDatabase
from scipy.cluster.hierarchy import fcluster, linkage
from scipy.spatial.distance import pdist

NEO4J_URI = "bolt://localhost:7687"
NEO4J_USER = "neo4j"
NEO4J_PASSWORD = "graphiti_neo4j_pass"

# Meta-Perspectives a tester (les plus grosses identifiees au diagnostic A1)
META_PERSPECTIVES_TO_TEST = [
    "Gestion et Conformité Système",  # ABAP, 4508 claims
    "Migration vers S/4HANA",          # SAP, 4199 claims
    "Migration et modernisation ERP",  # SAP S/4HANA, 4167 claims
]


def load_claims_for_perspective(driver, perspective_label: str) -> list:
    """Charge tous les claims d'une Perspective avec leurs embeddings et facets."""
    with driver.session() as session:
        # Trouver la Perspective par label
        result = session.run("""
            MATCH (p:Perspective {tenant_id: 'default', label: $label})
            RETURN p.perspective_id AS pid, p.subject_name AS subject, p.claim_count AS n
            LIMIT 1
        """, label=perspective_label)
        rec = result.single()
        if not rec:
            print(f"  Perspective '{perspective_label}' non trouvee")
            return []

        pid = rec["pid"]
        subject = rec["subject"]
        n_expected = rec["n"]
        print(f"  Perspective trouvee : {pid} (sujet={subject}, claims={n_expected})")

        # Charger les claims via INCLUDES_CLAIM
        result = session.run("""
            MATCH (p:Perspective {perspective_id: $pid})-[:INCLUDES_CLAIM]->(c:Claim)
            WHERE c.embedding IS NOT NULL
            OPTIONAL MATCH (c)-[:BELONGS_TO_FACET]->(f:Facet)
            RETURN c.claim_id AS cid,
                   c.text AS text,
                   c.doc_id AS doc_id,
                   c.embedding AS embedding,
                   collect(DISTINCT f.facet_name) AS facet_names
        """, pid=pid)

        claims = []
        for r in result:
            claims.append({
                "claim_id": r["cid"],
                "text": r["text"] or "",
                "doc_id": r["doc_id"] or "",
                "embedding": r["embedding"],
                "facet_names": [f for f in r["facet_names"] if f],
            })

        print(f"  Claims charges : {len(claims)} (avec embeddings)")
        return claims


def hierarchical_subcluster(
    claims: list,
    target_k: int = 8,
) -> dict:
    """Sous-clusterise les claims en target_k clusters (agglomeratif).

    Returns:
        Dict cluster_id -> liste de claims
    """
    if len(claims) < target_k * 2:
        target_k = max(2, len(claims) // 5)

    # Construire la matrice d'embeddings
    embeddings = np.array([c["embedding"] for c in claims if c.get("embedding")])
    valid_claims = [c for c in claims if c.get("embedding")]

    if len(embeddings) < target_k:
        return {0: valid_claims}

    print(f"  Clustering {len(embeddings)} claims en {target_k} sous-clusters...")

    # Clustering agglomeratif (cosine + average linkage, comme builder.py)
    distances = pdist(embeddings, metric="cosine")
    distances = np.nan_to_num(distances, nan=1.0)
    Z = linkage(distances, method="average")
    labels = fcluster(Z, t=target_k, criterion="maxclust")

    # Regrouper
    clusters = {}
    for claim, label in zip(valid_claims, labels):
        clusters.setdefault(int(label), []).append(claim)

    return clusters


def analyze_subcluster(claims: list, cluster_id: int) -> dict:
    """Analyse un sous-cluster : facets dominantes, claims representatifs, docs."""
    facet_counter = Counter()
    doc_counter = Counter()
    for c in claims:
        for fn in c.get("facet_names", []):
            facet_counter[fn] += 1
        if c.get("doc_id"):
            doc_counter[c["doc_id"]] += 1

    # Echantillonner 7 claims diversifies (pas que les premiers)
    sample_size = min(7, len(claims))
    if len(claims) <= sample_size:
        sample = claims
    else:
        # Prendre claims a intervalles reguliers pour diversite
        step = len(claims) // sample_size
        sample = [claims[i * step] for i in range(sample_size)]

    return {
        "cluster_id": cluster_id,
        "size": len(claims),
        "top_facets": facet_counter.most_common(5),
        "n_docs": len(doc_counter),
        "top_docs": [d[:60] for d, _ in doc_counter.most_common(3)],
        "sample_claims": [c["text"][:180] for c in sample],
    }


def run_prototype():
    print("=" * 80)
    print("PROTOTYPE PHASE A2 — Sous-clustering hierarchique")
    print("=" * 80)

    driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))

    full_report = {
        "timestamp": datetime.utcnow().isoformat(),
        "meta_perspectives": [],
    }

    for meta_label in META_PERSPECTIVES_TO_TEST:
        print(f"\n{'━' * 80}")
        print(f"META-PERSPECTIVE : {meta_label}")
        print(f"{'━' * 80}")

        claims = load_claims_for_perspective(driver, meta_label)
        if not claims:
            continue

        # Sous-clustering avec target k=8
        subclusters = hierarchical_subcluster(claims, target_k=8)
        print(f"  Resultat : {len(subclusters)} sous-clusters")
        sizes = sorted([len(v) for v in subclusters.values()], reverse=True)
        print(f"  Tailles : {sizes}")

        cluster_analyses = []
        for cluster_id, cluster_claims in sorted(subclusters.items(), key=lambda x: -len(x[1])):
            analysis = analyze_subcluster(cluster_claims, cluster_id)
            cluster_analyses.append(analysis)

        full_report["meta_perspectives"].append({
            "label": meta_label,
            "n_claims": len(claims),
            "subclusters": cluster_analyses,
        })

        # Afficher l'analyse
        print(f"\n  ANALYSE DES SOUS-CLUSTERS :")
        for analysis in cluster_analyses:
            print(f"\n  ── Sous-cluster {analysis['cluster_id']} ({analysis['size']} claims, {analysis['n_docs']} docs)")
            facets_str = ", ".join(f"{f}({n})" for f, n in analysis["top_facets"][:3])
            print(f"     Facets dominantes : {facets_str}")
            print(f"     Echantillon de claims (7) :")
            for i, claim in enumerate(analysis["sample_claims"], 1):
                print(f"       {i}. {claim}")

    driver.close()

    # Sauvegarde
    output_path = "prototype_clustering_report.json"
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(full_report, f, ensure_ascii=False, indent=2)
    print(f"\n{'=' * 80}")
    print(f"Rapport sauvegarde : {output_path}")
    print(f"Taille : {os.path.getsize(output_path) / 1024:.1f} KB")


if __name__ == "__main__":
    run_prototype()
