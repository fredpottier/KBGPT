"""
Phase A3 — Probe diagnostic : isolation thematique des claims.

⚠️ DIAGNOSTIC ONLY — ce script utilise des listes de mots cles a but exclusivement
exploratoire pour comprendre la structure semantique du corpus. Ces listes ne
doivent JAMAIS etre integrees au pipeline de production. C'est un microscope,
pas un composant.

Question testee :
> Si on isole les claims qui parlent vraiment de [theme], forment-ils un cluster
  semantique coherent quand on regarde leurs embeddings ?

Si oui : Option C (Perspectives transversales theme-scoped) est viable.
Si non : le probleme est en amont (claims trop atomiques, ou embeddings inadequats).

Methode :
1. Pour chaque theme probe, recuperer les claims contenant les mots cles du theme
2. Mesurer le volume et la dispersion documentaire
3. Recuperer leurs embeddings
4. Sub-clusteriser ce sous-ensemble pour voir si des sous-themes coherents emergent
5. Verifier la coherence semantique (distance moyenne au centroide vs dispersion)
"""

import json
import os
from collections import Counter
from datetime import datetime

import numpy as np
from neo4j import GraphDatabase
from scipy.cluster.hierarchy import fcluster, linkage
from scipy.spatial.distance import pdist

NEO4J_URI = "bolt://localhost:7687"
NEO4J_USER = "neo4j"
NEO4J_PASSWORD = "graphiti_neo4j_pass"


# ⚠️ DIAGNOSTIC PROBES — pas pour la prod
# Ces listes servent UNIQUEMENT a recuperer un sous-corpus thematique
# pour mesurer si la structure semantique sous-jacente existe.
PROBES = {
    "security_authentication": {
        "description": "Tout ce qui concerne l'authentification utilisateur",
        "keywords": ["authentication", "SSO", "single sign-on", "password",
                     "logon", "login", "credential", "user identity"],
    },
    "security_authorization": {
        "description": "Tout ce qui concerne les autorisations et roles",
        "keywords": ["authorization object", "role assignment", "S_TABU",
                     "PFCG", "auth check", "authorization profile"],
    },
    "security_encryption": {
        "description": "Chiffrement, TLS, SNC, secure communication",
        "keywords": ["TLS", "SNC", "encryption", "encrypted", "SSL",
                     "Secure Network Communications", "cipher"],
    },
    "migration_tools": {
        "description": "Outils techniques de migration et conversion",
        "keywords": ["Migration Cockpit", "Software Update Manager", "SUM",
                     "Readiness Check", "Custom Code Migration", "SI-Check",
                     "Simplification Item", "Maintenance Planner"],
    },
    "data_governance": {
        "description": "Gouvernance des donnees, ILM, archivage",
        "keywords": ["ILM", "Information Lifecycle", "data archiving",
                     "retention period", "data destruction", "data privacy",
                     "GDPR", "personal data"],
    },
}


def fetch_claims_for_probe(driver, keywords: list) -> list:
    """Recupere les claims contenant au moins un mot cle (case insensitive)."""
    # Construire le filtre WHERE avec OR de toLower CONTAINS
    where_clauses = " OR ".join([
        f"toLower(c.text) CONTAINS toLower('{kw}')" for kw in keywords
    ])

    cypher = f"""
        MATCH (c:Claim {{tenant_id: 'default'}})
        WHERE c.embedding IS NOT NULL AND ({where_clauses})
        OPTIONAL MATCH (c)-[:BELONGS_TO_FACET]->(f:Facet)
        RETURN c.claim_id AS cid,
               c.text AS text,
               c.doc_id AS doc_id,
               c.embedding AS embedding,
               collect(DISTINCT f.facet_name) AS facet_names
        LIMIT 2000
    """

    with driver.session() as session:
        result = session.run(cypher)
        claims = []
        for r in result:
            claims.append({
                "claim_id": r["cid"],
                "text": r["text"] or "",
                "doc_id": r["doc_id"] or "",
                "embedding": r["embedding"],
                "facet_names": [f for f in r["facet_names"] if f],
            })
    return claims


def measure_semantic_cohesion(claims: list) -> dict:
    """Mesure la coherence semantique d'un sous-corpus.

    - Distance moyenne au centroide
    - Distance max au centroide
    - Variance des distances
    """
    if len(claims) < 2:
        return {"n": len(claims), "mean_dist_to_centroid": 0, "max_dist": 0}

    embeddings = np.array([c["embedding"] for c in claims if c.get("embedding")])
    centroid = np.mean(embeddings, axis=0)

    # Cosine distance au centroide
    distances = []
    centroid_norm = np.linalg.norm(centroid)
    for emb in embeddings:
        emb_norm = np.linalg.norm(emb)
        if centroid_norm > 0 and emb_norm > 0:
            cos_sim = np.dot(emb, centroid) / (emb_norm * centroid_norm)
            distances.append(1 - cos_sim)

    distances = np.array(distances)
    return {
        "n": len(claims),
        "mean_dist_to_centroid": round(float(np.mean(distances)), 4),
        "max_dist": round(float(np.max(distances)), 4),
        "std_dist": round(float(np.std(distances)), 4),
    }


def subcluster_isolated(claims: list, target_k: int = 5) -> dict:
    """Sub-clusterise un sous-corpus isole."""
    if len(claims) < target_k * 2:
        target_k = max(2, len(claims) // 3)

    embeddings = np.array([c["embedding"] for c in claims if c.get("embedding")])
    if len(embeddings) < 4:
        return {0: claims}

    distances = pdist(embeddings, metric="cosine")
    distances = np.nan_to_num(distances, nan=1.0)
    Z = linkage(distances, method="average")
    labels = fcluster(Z, t=target_k, criterion="maxclust")

    clusters = {}
    for claim, label in zip(claims, labels):
        clusters.setdefault(int(label), []).append(claim)
    return clusters


def analyze_subcluster_simple(claims: list, cluster_id: int) -> dict:
    facets = Counter()
    docs = Counter()
    for c in claims:
        for fn in c.get("facet_names", []):
            facets[fn] += 1
        if c.get("doc_id"):
            docs[c["doc_id"]] += 1

    sample_size = min(5, len(claims))
    if len(claims) <= sample_size:
        sample = claims
    else:
        step = len(claims) // sample_size
        sample = [claims[i * step] for i in range(sample_size)]

    return {
        "cluster_id": cluster_id,
        "size": len(claims),
        "n_docs": len(docs),
        "top_facets": facets.most_common(3),
        "samples": [c["text"][:160] for c in sample],
    }


def run_probe():
    print("=" * 80)
    print("PROBE A3 — Isolation thematique des claims")
    print("=" * 80)
    print("⚠️  DIAGNOSTIC SEULEMENT — listes de mots utilisees comme microscope")
    print()

    driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))

    full_report = {
        "timestamp": datetime.utcnow().isoformat(),
        "probes": [],
    }

    for probe_name, probe_def in PROBES.items():
        print(f"\n{'━' * 80}")
        print(f"PROBE : {probe_name}")
        print(f"  Description : {probe_def['description']}")
        print(f"  Keywords : {probe_def['keywords']}")

        claims = fetch_claims_for_probe(driver, probe_def["keywords"])
        print(f"  Claims trouves : {len(claims)}")

        if not claims:
            print("  ⚠️  Aucun claim trouve — theme absent du corpus")
            full_report["probes"].append({
                "name": probe_name,
                "n_claims": 0,
                "verdict": "absent_du_corpus",
            })
            continue

        # Dispersion documentaire
        doc_counter = Counter(c.get("doc_id", "") for c in claims if c.get("doc_id"))
        n_docs = len(doc_counter)
        print(f"  Documents distincts : {n_docs}")
        print(f"  Top docs : {[d[:50] for d, _ in doc_counter.most_common(3)]}")

        # Coherence semantique globale
        cohesion = measure_semantic_cohesion(claims)
        print(f"  Coherence semantique :")
        print(f"    - distance moyenne au centroide : {cohesion['mean_dist_to_centroid']}")
        print(f"    - distance max : {cohesion['max_dist']}")
        print(f"    - ecart-type : {cohesion['std_dist']}")

        # Verdict cohesion : si dist moyenne < 0.15 -> tres serre, < 0.25 -> moyen, > 0.25 -> diffus
        if cohesion["mean_dist_to_centroid"] < 0.15:
            cohesion_verdict = "tres_coherent"
        elif cohesion["mean_dist_to_centroid"] < 0.25:
            cohesion_verdict = "moyennement_coherent"
        else:
            cohesion_verdict = "diffus"
        print(f"    - verdict : {cohesion_verdict}")

        # Sub-cluster pour voir si des sous-themes emergent
        subclusters = subcluster_isolated(claims, target_k=5)
        sizes = sorted([len(v) for v in subclusters.values()], reverse=True)
        print(f"  Sub-clusters (target=5) : {sizes}")

        # Critere : si le plus gros cluster fait > 80% du total, c'est mauvais (1 seul theme)
        # Si la repartition est equilibree, c'est bon (vrais sous-themes)
        max_cluster_ratio = sizes[0] / len(claims) if claims else 0
        if max_cluster_ratio > 0.85:
            distribution_verdict = "domine_par_un_cluster"
        elif max_cluster_ratio > 0.6:
            distribution_verdict = "moderement_concentre"
        else:
            distribution_verdict = "bien_distribue"
        print(f"    - distribution : {distribution_verdict} (top1 = {max_cluster_ratio:.0%})")

        cluster_analyses = []
        for cid, ccs in sorted(subclusters.items(), key=lambda x: -len(x[1])):
            cluster_analyses.append(analyze_subcluster_simple(ccs, cid))

        # Afficher les 3 plus gros sous-clusters
        print(f"\n  TOP 3 sous-clusters :")
        for ca in cluster_analyses[:3]:
            facets_str = ", ".join(f"{f}({n})" for f, n in ca["top_facets"][:2])
            print(f"\n    [Cluster {ca['cluster_id']}] {ca['size']} claims, {ca['n_docs']} docs")
            print(f"    Facets : {facets_str}")
            print(f"    Echantillon :")
            for s in ca["samples"][:5]:
                print(f"      - {s}")

        full_report["probes"].append({
            "name": probe_name,
            "description": probe_def["description"],
            "n_claims": len(claims),
            "n_docs": n_docs,
            "cohesion": cohesion,
            "cohesion_verdict": cohesion_verdict,
            "distribution": sizes,
            "max_cluster_ratio": round(max_cluster_ratio, 3),
            "distribution_verdict": distribution_verdict,
            "subclusters": cluster_analyses,
        })

    driver.close()

    # Synthese globale
    print(f"\n{'=' * 80}")
    print("SYNTHESE")
    print(f"{'=' * 80}")
    for p in full_report["probes"]:
        if p.get("verdict") == "absent_du_corpus":
            print(f"  {p['name']}: ABSENT")
            continue
        print(f"  {p['name']}: {p['n_claims']} claims, {p['n_docs']} docs, "
              f"cohesion={p['cohesion_verdict']}, distrib={p['distribution_verdict']}")

    output_path = "probe_thematic_report.json"
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(full_report, f, ensure_ascii=False, indent=2)
    print(f"\nRapport sauvegarde : {output_path}")


if __name__ == "__main__":
    run_probe()
