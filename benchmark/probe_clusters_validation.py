"""
Phase A4-bis — Validation finale du clustering global :
1. Labellisation LLM des top clusters (Haiku)
2. Analyse de couverture sur questions cross-doc reelles

Question critique :
> Si on pose "quelles sont les differences sur la securite dans les
  Security Guides 2021/2022/2023", est-ce que les clusters thematiques
  captent suffisamment la matiere de ces 3 documents pour repondre ?

Methode :
1. Re-clusterer le corpus (HDBSCAN global)
2. Labelliser les top 30 clusters via Haiku
3. Pour les 3 Security Guides identifies dans le corpus :
   - Combien de leurs claims sont dans des clusters (vs noise) ?
   - Combien de clusters distincts contiennent leurs claims ?
   - Quels clusters dominent (couverture cross-doc) ?
4. Verdict : la couverture est-elle suffisante pour une question cross-doc ?
"""

import json
import os
import sys
import time
from collections import Counter, defaultdict
from datetime import datetime

import numpy as np
from neo4j import GraphDatabase

NEO4J_URI = "bolt://neo4j:7687"
NEO4J_USER = "neo4j"
NEO4J_PASSWORD = "graphiti_neo4j_pass"

# Documents Security Guide identifies dans le corpus pour le test cross-doc
SECURITY_GUIDE_PATTERNS = [
    "Security_Guide",  # matche tous les Security Guides
]


def fetch_all_claims(driver) -> list:
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


def reduce_and_cluster(claims: list, target_dim=15, min_cluster_size=30):
    import umap
    import hdbscan

    embeddings = np.array([c["embedding"] for c in claims])
    print(f"UMAP {embeddings.shape[1]} -> {target_dim} dim...")
    start = time.time()
    reducer = umap.UMAP(
        n_components=target_dim, n_neighbors=30, min_dist=0.0,
        metric="cosine", random_state=42,
    )
    reduced = reducer.fit_transform(embeddings)
    print(f"  UMAP : {time.time() - start:.1f}s")

    print(f"HDBSCAN min_cluster_size={min_cluster_size}...")
    start = time.time()
    clusterer = hdbscan.HDBSCAN(
        min_cluster_size=min_cluster_size, min_samples=5,
        metric="euclidean", cluster_selection_method="eom",
    )
    labels = clusterer.fit_predict(reduced)
    print(f"  HDBSCAN : {time.time() - start:.1f}s")
    return labels


def label_cluster_with_llm(sample_claims: list, top_facets: list) -> dict:
    """Demande a Haiku de labelliser un cluster."""
    import os
    anthropic_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not anthropic_key:
        return {"label": "?", "description": "no_api_key"}

    claims_text = "\n".join(f"- {c[:200]}" for c in sample_claims[:7])
    facets_str = ", ".join(f"{f}({n})" for f, n in top_facets[:3]) or "none"

    prompt = f"""Analyze these claims and identify the THEMATIC AXIS that unites them.

Sample claims:
{claims_text}

Associated facets: {facets_str}

Respond in strict JSON:
{{"label": "thematic axis in 3-6 words", "scope": "narrow|medium|broad"}}

RULES:
- Label MUST be a thematic axis (Security, Migration tools, Logistics, etc.), NOT a product name
- Avoid SAP-specific terms unless they describe the theme itself
- "narrow" = single sub-topic, "medium" = focused area, "broad" = multiple sub-topics
- Respond ONLY with the JSON, no extra text"""

    try:
        import anthropic
        client = anthropic.Anthropic(api_key=anthropic_key)
        resp = client.messages.create(
            model=os.environ.get("OSMOSIS_SYNTHESIS_MODEL", "claude-haiku-4-5-20251001"),
            max_tokens=150,
            temperature=0.0,
            messages=[{"role": "user", "content": prompt}],
        )
        text = resp.content[0].text if resp.content else ""
        import re
        m = re.search(r'\{[\s\S]*\}', text)
        if m:
            return json.loads(m.group())
    except Exception as e:
        return {"label": "?", "description": f"error: {e}"}
    return {"label": "?", "description": "parse_failed"}


def find_security_guides(claims: list) -> list:
    """Identifie les doc_ids correspondant aux Security Guides."""
    sec_docs = set()
    for c in claims:
        doc_id = c.get("doc_id", "")
        if any(pattern in doc_id for pattern in SECURITY_GUIDE_PATTERNS):
            sec_docs.add(doc_id)
    return sorted(sec_docs)


def analyze_cluster_coverage_for_docs(
    claims: list, labels: np.ndarray, target_doc_ids: set,
) -> dict:
    """Pour chaque doc cible, calcule la repartition de ses claims dans les clusters."""
    doc_cluster_counts = defaultdict(lambda: Counter())
    doc_total = Counter()
    cluster_doc_overlap = defaultdict(lambda: Counter())

    for i, c in enumerate(claims):
        doc_id = c.get("doc_id", "")
        if doc_id not in target_doc_ids:
            continue
        cluster_id = int(labels[i])
        doc_cluster_counts[doc_id][cluster_id] += 1
        doc_total[doc_id] += 1
        if cluster_id != -1:
            cluster_doc_overlap[cluster_id][doc_id] += 1

    return {
        "doc_cluster_counts": {d: dict(cc) for d, cc in doc_cluster_counts.items()},
        "doc_total": dict(doc_total),
        "cluster_doc_overlap": {c: dict(dc) for c, dc in cluster_doc_overlap.items()},
    }


def run_validation():
    print("=" * 80)
    print("PHASE A4-BIS — Validation finale clusters")
    print("=" * 80)

    driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))
    claims = fetch_all_claims(driver)
    driver.close()

    # Clustering global
    labels = reduce_and_cluster(claims, target_dim=15, min_cluster_size=30)

    unique_labels = set(labels.tolist())
    n_clusters = len(unique_labels) - (1 if -1 in unique_labels else 0)
    n_noise = int(np.sum(labels == -1))
    print(f"\nClusters: {n_clusters}, Noise: {n_noise} ({n_noise/len(claims)*100:.1f}%)")

    # 1. Identifier les Security Guides
    sec_guides = find_security_guides(claims)
    print(f"\nSecurity Guides identifies dans le corpus :")
    for sg in sec_guides:
        print(f"  - {sg}")

    if not sec_guides:
        print("ERREUR : aucun Security Guide trouve")
        return

    sec_doc_set = set(sec_guides)

    # 2. Analyser la couverture des Security Guides par les clusters
    print(f"\n{'=' * 80}")
    print("ANALYSE COUVERTURE DES SECURITY GUIDES")
    print(f"{'=' * 80}")

    coverage = analyze_cluster_coverage_for_docs(claims, labels, sec_doc_set)

    for doc_id in sec_guides:
        total = coverage["doc_total"].get(doc_id, 0)
        cluster_dist = coverage["doc_cluster_counts"].get(doc_id, {})
        in_clusters = sum(cnt for cid, cnt in cluster_dist.items() if cid != -1)
        in_noise = cluster_dist.get(-1, 0)
        coverage_pct = (in_clusters / total * 100) if total > 0 else 0

        print(f"\n  Doc : {doc_id[:60]}")
        print(f"    Total claims      : {total}")
        print(f"    Dans clusters     : {in_clusters} ({coverage_pct:.1f}%)")
        print(f"    Dans noise        : {in_noise} ({(100-coverage_pct):.1f}%)")
        print(f"    Clusters touches  : {len([cid for cid in cluster_dist if cid != -1])}")
        # Top 5 clusters pour ce doc
        top_clusters_for_doc = sorted(
            [(cid, cnt) for cid, cnt in cluster_dist.items() if cid != -1],
            key=lambda x: -x[1]
        )[:5]
        print(f"    Top 5 clusters    : {top_clusters_for_doc}")

    # 3. Identifier les clusters qui touchent PLUSIEURS Security Guides
    print(f"\n{'=' * 80}")
    print("CLUSTERS CROSS-DOC SECURITY GUIDES")
    print(f"{'=' * 80}")

    cross_doc_clusters = []
    for cid, doc_overlap in coverage["cluster_doc_overlap"].items():
        sec_docs_touched = [d for d in doc_overlap if d in sec_doc_set]
        if len(sec_docs_touched) >= 2:
            total_sec_claims = sum(doc_overlap[d] for d in sec_docs_touched)
            cross_doc_clusters.append({
                "cluster_id": cid,
                "n_security_docs_touched": len(sec_docs_touched),
                "n_security_claims": total_sec_claims,
                "doc_overlap": {d: doc_overlap[d] for d in sec_docs_touched},
            })

    cross_doc_clusters.sort(key=lambda x: -x["n_security_claims"])
    print(f"\nClusters touchant >=2 Security Guides : {len(cross_doc_clusters)}")
    for c in cross_doc_clusters[:10]:
        print(f"  Cluster {c['cluster_id']:>4d} : "
              f"{c['n_security_docs_touched']} guides, "
              f"{c['n_security_claims']} claims | "
              f"{c['doc_overlap']}")

    # 4. Labelliser les top clusters via Haiku (top 30 globaux + clusters cross-doc security)
    print(f"\n{'=' * 80}")
    print("LABELLISATION LLM DES CLUSTERS")
    print(f"{'=' * 80}")

    # Top clusters globaux par taille
    cluster_sizes = []
    for cid in unique_labels:
        if cid != -1:
            size = int(np.sum(labels == cid))
            cluster_sizes.append((cid, size))
    cluster_sizes.sort(key=lambda x: -x[1])

    top_global_clusters = [c[0] for c in cluster_sizes[:25]]
    cross_doc_cluster_ids = [c["cluster_id"] for c in cross_doc_clusters[:10]]
    clusters_to_label = list(dict.fromkeys(top_global_clusters + cross_doc_cluster_ids))[:35]

    print(f"\nLabellisation de {len(clusters_to_label)} clusters via Haiku...")

    cluster_labels_map = {}
    for i, cid in enumerate(clusters_to_label, 1):
        cluster_claims = [claims[j] for j in range(len(claims)) if labels[j] == cid]
        size = len(cluster_claims)
        n_docs = len(set(c["doc_id"] for c in cluster_claims if c["doc_id"]))
        facet_counter = Counter()
        for c in cluster_claims:
            for fn in c["facet_names"]:
                facet_counter[fn] += 1
        top_facets = facet_counter.most_common(5)

        # Echantillon
        sample_size = min(7, len(cluster_claims))
        if len(cluster_claims) <= sample_size:
            sample = cluster_claims
        else:
            step = len(cluster_claims) // sample_size
            sample = [cluster_claims[i * step] for i in range(sample_size)]
        sample_texts = [c["text"][:200] for c in sample]

        # Appel LLM
        label_data = label_cluster_with_llm(sample_texts, top_facets)

        # Nb de Security Guides touches
        sec_docs_in_cluster = set(
            c["doc_id"] for c in cluster_claims
            if c["doc_id"] in sec_doc_set
        )

        cluster_labels_map[int(cid)] = {
            "size": size,
            "n_docs": n_docs,
            "top_facets": top_facets,
            "label": label_data.get("label", "?"),
            "scope": label_data.get("scope", "?"),
            "n_security_docs": len(sec_docs_in_cluster),
            "sample": sample_texts[:3],
        }

        marker = "🔒" if len(sec_docs_in_cluster) >= 2 else "  "
        print(f"  {marker} [{i:>2d}/{len(clusters_to_label)}] Cluster {cid:>4d} ({size} claims, {n_docs} docs, {len(sec_docs_in_cluster)} sec) -> {label_data.get('label', '?')}")

    # 5. Verdict cross-doc security
    print(f"\n{'=' * 80}")
    print("VERDICT FINAL")
    print(f"{'=' * 80}")

    total_sec_claims = sum(coverage["doc_total"].get(d, 0) for d in sec_guides)
    total_sec_in_clusters = sum(
        sum(cnt for cid, cnt in coverage["doc_cluster_counts"].get(d, {}).items() if cid != -1)
        for d in sec_guides
    )
    cross_doc_coverage = (total_sec_in_clusters / total_sec_claims * 100) if total_sec_claims > 0 else 0

    print(f"\nClaims totaux des {len(sec_guides)} Security Guides : {total_sec_claims}")
    print(f"Claims dans des clusters thematiques  : {total_sec_in_clusters} ({cross_doc_coverage:.1f}%)")
    print(f"Claims dans noise (non clusterisable) : {total_sec_claims - total_sec_in_clusters} ({100-cross_doc_coverage:.1f}%)")
    print(f"Clusters cross-doc (>=2 Security Guides) : {len(cross_doc_clusters)}")
    if cross_doc_clusters:
        n_cross_claims = sum(c["n_security_claims"] for c in cross_doc_clusters)
        print(f"Claims dans clusters cross-doc       : {n_cross_claims} ({n_cross_claims/total_sec_claims*100:.1f}%)")

    # Sauvegarde
    output = {
        "timestamp": datetime.utcnow().isoformat(),
        "config": {"target_dim": 15, "min_cluster_size": 30},
        "clustering": {
            "total_claims": len(claims),
            "n_clusters": n_clusters,
            "n_noise": n_noise,
            "noise_ratio": round(n_noise / len(claims), 3),
        },
        "security_guides": list(sec_guides),
        "security_coverage": {
            "total_claims": total_sec_claims,
            "in_clusters": total_sec_in_clusters,
            "coverage_pct": round(cross_doc_coverage, 1),
            "cross_doc_clusters_count": len(cross_doc_clusters),
            "cross_doc_clusters": cross_doc_clusters[:10],
        },
        "labelled_clusters": cluster_labels_map,
    }
    output_path = "/app/clusters_validation_report.json"
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    print(f"\nRapport sauvegarde : {output_path}")


if __name__ == "__main__":
    run_validation()
