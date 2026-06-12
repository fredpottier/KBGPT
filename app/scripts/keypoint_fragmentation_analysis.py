"""Analyse la fragmentation des KeyPoints : questions quasi-identiques qui auraient
dû être un seul bucket (« minimizes health risk » vs « minimizes health loss »).
Embed les questions (e5), trouve les paires cosine >= seuil, affiche les clusters.
Données pour décider seuil + méthode de fusion (remédiation étape 3). LECTURE SEULE.
"""
from __future__ import annotations
import os, sys
from neo4j import GraphDatabase
import numpy as np


def main():
    thr = float(sys.argv[1]) if len(sys.argv) > 1 else 0.95
    tenant = sys.argv[2] if len(sys.argv) > 2 else "alcohol_health"
    drv = GraphDatabase.driver(os.getenv("NEO4J_URI", "bolt://neo4j:7687"),
                               auth=(os.getenv("NEO4J_USER", "neo4j"), os.getenv("NEO4J_PASSWORD", "password")))
    with drv.session() as s:
        rows = [dict(r) for r in s.run(
            "MATCH (k:KeyPoint {tenant_id:$t}) RETURN k.kp_id AS id, k.question AS q, "
            "coalesce(k.claim_count,0) AS n, coalesce(k.is_debate,false) AS deb ORDER BY n DESC", t=tenant)]
    drv.close()
    print(f"{len(rows)} KeyPoints (tenant={tenant}, seuil={thr})", flush=True)

    from knowbase.common.clients.embeddings import EmbeddingModelManager
    mgr = EmbeddingModelManager()
    qs = [r["q"] for r in rows]
    embs = mgr.encode([f"query: {q}" for q in qs])
    embs = np.array(embs, dtype=np.float32)
    embs /= (np.linalg.norm(embs, axis=1, keepdims=True) + 1e-9)
    sim = embs @ embs.T

    # clustering union-find par paires >= seuil
    parent = list(range(len(rows)))
    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]; x = parent[x]
        return x
    n_pairs = 0
    for i in range(len(rows)):
        for j in range(i + 1, len(rows)):
            if sim[i, j] >= thr:
                n_pairs += 1
                ri, rj = find(i), find(j)
                if ri != rj:
                    parent[ri] = rj
    from collections import defaultdict
    clusters = defaultdict(list)
    for i in range(len(rows)):
        clusters[find(i)].append(i)
    multi = {k: v for k, v in clusters.items() if len(v) > 1}
    print(f"{n_pairs} paires >= {thr} | {len(multi)} clusters multi-KeyPoints "
          f"(=> {sum(len(v) for v in multi.values())} KP fusionnables en {len(multi)})", flush=True)
    # afficher les plus gros clusters
    for k, idxs in sorted(multi.items(), key=lambda kv: -sum(rows[i]['n'] for i in kv[1]))[:12]:
        idxs = sorted(idxs, key=lambda i: -rows[i]['n'])
        print(f"  cluster ({len(idxs)} KP, {sum(rows[i]['n'] for i in idxs)} claims, "
              f"sim min={min(sim[i,j] for i in idxs for j in idxs if i<j):.3f}):", flush=True)
        for i in idxs[:5]:
            print(f"      [{rows[i]['n']:3d}c deb={rows[i]['deb']}] {rows[i]['q'][:70]}", flush=True)


if __name__ == "__main__":
    main()
