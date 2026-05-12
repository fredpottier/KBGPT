"""
Detect Thematic Axes — clustering sur les embeddings des Perspectives.

Detecte les axes thematiques transversaux (ex: Securite, Integration,
Operations...) sans aucun mot-cle predetermine. 100% emergent.

L'axe 1 (produit) est donne par build_narrative_topics.py (community
detection sur le graphe biparti Perspective x Subject).

L'axe 2 (theme) est donne par ce script : clustering sur les embeddings
des Perspectives, independamment de leurs sujets.

Un theme transversal = un cluster de Perspectives semantiquement proches
qui traversent plusieurs topics/produits.

Usage (dans Docker):
    python scripts/detect_thematic_axes.py
    python scripts/detect_thematic_axes.py --n-themes 8
    python scripts/detect_thematic_axes.py --dry-run
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
from dataclasses import dataclass, field
from typing import Any

import numpy as np

sys.path.insert(0, "/app/src")

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("thematic-axes")

DEFAULT_N_THEMES = 8
TENANT_ID = "default"


@dataclass
class ThematicAxis:
    axis_id: str
    label: str = ""  # genere par LLM a partir des labels des perspectives membres
    perspective_ids: list[str] = field(default_factory=list)
    perspective_labels: list[str] = field(default_factory=list)
    claim_count: int = 0
    # Quels topics (axe produit) ce theme traverse
    topic_ids: list[str] = field(default_factory=list)
    topic_coverage: int = 0  # nombre de topics touches


def load_perspective_embeddings(driver, tenant_id: str) -> list[dict]:
    """Charge les Perspectives avec leurs embeddings."""
    with driver.session() as session:
        result = session.run("""
            MATCH (p:Perspective {tenant_id: $tid})
            WHERE p.embedding_json IS NOT NULL
            RETURN p.perspective_id AS pid, p.label AS label,
                   p.claim_count AS claims, p.embedding_json AS emb_json
        """, tid=tenant_id)

        perspectives = []
        for rec in result:
            emb = json.loads(rec["emb_json"])
            perspectives.append({
                "pid": rec["pid"],
                "label": rec["label"],
                "claims": rec["claims"],
                "embedding": np.array(emb, dtype=np.float32),
            })

    logger.info(f"Loaded {len(perspectives)} perspectives with {perspectives[0]['embedding'].shape[0]}D embeddings")
    return perspectives


def auto_select_k_themes(embeddings_norm: np.ndarray, k_min: int = 3, k_max: int = 15) -> int:
    """Determine le K optimal pour KMeans via silhouette score.

    Essaie K dans [k_min, k_max] borne par n_samples / 3 (eviter clusters
    de taille 1-2 sans valeur narrative), et garde le K qui maximise le
    silhouette score (separation/compacite des clusters).

    Tie-break : a score equivalent (delta < 0.005), preferer le K plus eleve
    pour une vue plus granulaire — sauf si la difference est triviale.
    """
    from sklearn.cluster import KMeans
    from sklearn.metrics import silhouette_score

    n_samples = len(embeddings_norm)
    k_max_eff = min(k_max, max(k_min, n_samples // 3))
    if k_max_eff <= k_min:
        return k_min

    scores: list[tuple[int, float]] = []
    for k in range(k_min, k_max_eff + 1):
        try:
            km = KMeans(n_clusters=k, random_state=42, n_init=10)
            lbls = km.fit_predict(embeddings_norm)
            # silhouette necessite >=2 clusters distincts
            if len(set(lbls)) < 2:
                continue
            score = silhouette_score(embeddings_norm, lbls, metric="cosine")
            scores.append((k, float(score)))
        except Exception as e:
            logger.warning(f"  silhouette K={k} failed: {e}")

    if not scores:
        return k_min

    # Choisir le K avec meilleur score, tie-break = K plus eleve
    best_score = max(s for _, s in scores)
    candidates = [k for k, s in scores if abs(s - best_score) < 0.005]
    chosen = max(candidates)

    logger.info(f"  silhouette scan K={k_min}..{k_max_eff}:")
    for k, s in scores:
        marker = " <-- chosen" if k == chosen else ""
        logger.info(f"    K={k:2d}: score={s:.4f}{marker}")
    return chosen


def cluster_themes(perspectives: list[dict], n_themes) -> list[ThematicAxis]:
    """Clustering KMeans sur les embeddings des Perspectives.

    Args:
        perspectives: liste de {pid, label, claims, embedding}
        n_themes: int (K fixe) OR "auto"/None (silhouette scan K=3..15)

    KMeans est prefere a HDBSCAN car on veut des clusters denses pour la
    visualisation atlas, pas une detection avec noise points.
    """
    from sklearn.cluster import KMeans

    embeddings = np.stack([p["embedding"] for p in perspectives])

    # Normaliser (cosine similarity → distance euclidienne)
    norms = np.linalg.norm(embeddings, axis=1, keepdims=True)
    norms[norms == 0] = 1
    embeddings_norm = embeddings / norms

    # Resoudre n_themes
    if n_themes is None or (isinstance(n_themes, str) and n_themes.lower() == "auto"):
        n_themes_eff = auto_select_k_themes(embeddings_norm)
        logger.info(f"  auto-K selected: {n_themes_eff}")
    else:
        n_themes_eff = int(n_themes)

    kmeans = KMeans(n_clusters=n_themes_eff, random_state=42, n_init=10)
    labels = kmeans.fit_predict(embeddings_norm)

    # Construire les ThematicAxes
    axes = {}
    for i, p in enumerate(perspectives):
        cluster = int(labels[i])
        if cluster not in axes:
            axes[cluster] = ThematicAxis(axis_id=f"theme_{cluster:03d}")
        ax = axes[cluster]
        ax.perspective_ids.append(p["pid"])
        ax.perspective_labels.append(p["label"])
        ax.claim_count += p["claims"]

    result = sorted(axes.values(), key=lambda a: a.claim_count, reverse=True)

    # Re-index
    for i, ax in enumerate(result):
        ax.axis_id = f"theme_{i:03d}"

    logger.info(f"Clustered into {len(result)} thematic axes")
    return result


def label_axes_llm(axes: list[ThematicAxis], skip_llm: bool = False) -> None:
    """Generer un label court pour chaque axe thematique via LLM."""
    if skip_llm:
        for ax in axes:
            # Fallback : mots les plus frequents dans les labels
            from collections import Counter
            words = Counter()
            for label in ax.perspective_labels:
                for w in label.split():
                    if len(w) > 4:
                        words[w] += 1
            top = [w for w, _ in words.most_common(3)]
            ax.label = " & ".join(top) if top else f"Theme {ax.axis_id}"
        return

    try:
        from knowbase.common.llm_router import get_llm_router, TaskType
        router = get_llm_router()
    except Exception:
        logger.warning("LLM router unavailable, using fallback labels")
        label_axes_llm(axes, skip_llm=True)
        return

    for ax in axes:
        prompt = (
            f"These {len(ax.perspective_labels)} document analysis perspectives "
            f"form a thematic cluster:\n"
            f"{json.dumps(ax.perspective_labels, indent=2)}\n\n"
            f"Generate a short thematic label (2-4 words) that captures the "
            f"common thread. Return ONLY the label, nothing else."
        )
        try:
            raw = router.complete(
                task_type=TaskType.KNOWLEDGE_EXTRACTION,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.0,
                max_tokens=30,
            )
            ax.label = raw.strip().strip('"').strip("'")
            logger.info(f"  {ax.axis_id}: {ax.label} ({len(ax.perspective_ids)}P, {ax.claim_count} claims)")
        except Exception as e:
            logger.warning(f"  {ax.axis_id}: LLM failed: {e}")
            label_axes_llm([ax], skip_llm=True)


def build_matrix(axes: list[ThematicAxis], topics: list[dict]) -> None:
    """Calcule la matrice theme x topic et l'affiche."""
    # Mapper perspective → topic
    persp_to_topic = {}
    for t in topics:
        for pid in t["pids"]:
            persp_to_topic[pid] = t

    # Pour chaque axe, quels topics il traverse
    for ax in axes:
        touched_topics = set()
        for pid in ax.perspective_ids:
            t = persp_to_topic.get(pid)
            if t:
                touched_topics.add(id(t))
        ax.topic_coverage = len(touched_topics)

    # Matrice
    logger.info(f"\n{'='*70}")
    logger.info(f"MATRICE THEME x TOPIC (claims)")
    logger.info(f"{'='*70}")

    header = "  " + "Theme".ljust(25) + "".join(
        (", ".join(t["subjects"][:1])[:12]).rjust(13) for t in topics
    ) + "  TOTAL".rjust(8)
    logger.info(header)
    logger.info("-" * len(header))

    for ax in axes:
        row = "  " + ax.label[:23].ljust(25)
        total = 0
        for t in topics:
            t_pids = set(t["pids"])
            claims = sum(
                p_claims for pid, p_claims in zip(ax.perspective_ids,
                    [next((pp["claims"] for pp in perspectives_global if pp["pid"] == pid), 0) for pid in ax.perspective_ids])
                if pid in t_pids
            )
            total += claims
            row += str(claims).rjust(13) if claims > 0 else ".".rjust(13)
        row += str(total).rjust(8)
        logger.info(row)


# Global pour la matrice
perspectives_global = []


def main():
    global perspectives_global

    parser = argparse.ArgumentParser(description="Detect thematic axes via embedding clustering")
    parser.add_argument("--tenant", default=TENANT_ID)
    parser.add_argument("--n-themes", type=int, default=DEFAULT_N_THEMES)
    parser.add_argument("--skip-llm", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    from neo4j import GraphDatabase
    uri = os.environ.get("NEO4J_URI", "bolt://neo4j:7687")
    user = os.environ.get("NEO4J_USER", "neo4j")
    password = os.environ.get("NEO4J_PASSWORD", "graphiti_neo4j_pass")
    driver = GraphDatabase.driver(uri, auth=(user, password))

    start = time.time()
    logger.info("=" * 60)
    logger.info(f"THEMATIC AXES DETECTION — {args.n_themes} themes")
    logger.info("=" * 60)

    # 1. Load embeddings
    perspectives_global = load_perspective_embeddings(driver, args.tenant)
    if len(perspectives_global) < args.n_themes:
        logger.warning(f"Only {len(perspectives_global)} perspectives, reducing to {len(perspectives_global) // 2} themes")
        args.n_themes = max(2, len(perspectives_global) // 2)

    # 2. Cluster
    axes = cluster_themes(perspectives_global, args.n_themes)

    # 3. Label
    logger.info(f"\nLabelling {len(axes)} thematic axes...")
    label_axes_llm(axes, skip_llm=args.skip_llm)

    # 4. Load topics (axe produit) pour la matrice
    import networkx as nx
    from networkx.algorithms.community import louvain_communities

    with driver.session() as s:
        r = s.run('MATCH (p:Perspective {tenant_id: $tid})-[r:TOUCHES_SUBJECT]->(sa:SubjectAnchor) WHERE sa.canonical_name IS NOT NULL RETURN p.perspective_id AS p_id, sa.subject_id AS s_id, sa.canonical_name AS s_name, r.weight AS weight', tid=args.tenant)
        edges, subjects = [], {}
        for rec in r:
            edges.append({"p_id": rec["p_id"], "s_id": rec["s_id"], "weight": rec["weight"] or 1.0})
            if rec["s_id"] not in subjects: subjects[rec["s_id"]] = {"name": rec["s_name"], "n_persp": 0}
        for e in edges: subjects[e["s_id"]]["n_persp"] += 1

    n_p = len(perspectives_global)
    filtered = {sid: info for sid, info in subjects.items() if info["n_persp"] / n_p <= 0.80}
    G = nx.Graph()
    for p in perspectives_global: G.add_node(p["pid"], bipartite="perspective", claims=p["claims"])
    for sid, info in filtered.items(): G.add_node(sid, bipartite="subject", label=info["name"])
    for e in [e for e in edges if e["s_id"] in filtered]: G.add_edge(e["p_id"], e["s_id"], weight=e["weight"])

    comms = louvain_communities(G, weight="weight", resolution=1.5, seed=42)
    topics = []
    for comm in sorted(comms, key=len, reverse=True):
        pids = [n for n in comm if G.nodes[n].get("bipartite") == "perspective"]
        sids = [n for n in comm if G.nodes[n].get("bipartite") == "subject"]
        if len(pids) >= 2:
            topics.append({"pids": pids, "subjects": [filtered[s]["name"] for s in sids if s in filtered],
                "claims": sum(G.nodes[p].get("claims", 0) for p in pids)})

    # 5. Display
    logger.info(f"\n{'='*60}")
    logger.info(f"THEMATIC AXES: {len(axes)}")
    logger.info(f"{'='*60}")
    for ax in axes:
        logger.info(f"\n  {ax.axis_id}: {ax.label}")
        logger.info(f"    {len(ax.perspective_ids)}P, {ax.claim_count} claims, crosses {ax.topic_coverage} topics")
        for pl in ax.perspective_labels[:4]:
            logger.info(f"      - {pl[:60]}")
        if len(ax.perspective_labels) > 4:
            logger.info(f"      ... +{len(ax.perspective_labels)-4}")

    # 6. Transversal view
    logger.info(f"\n{'='*60}")
    logger.info(f"VUE TRANSVERSALE (theme → topics)")
    logger.info(f"{'='*60}")
    persp_to_topic = {}
    for t in topics:
        for pid in t["pids"]:
            persp_to_topic[pid] = t

    for ax in axes:
        contribs = {}
        for pid in ax.perspective_ids:
            t = persp_to_topic.get(pid)
            if t:
                key = ", ".join(t["subjects"][:2])[:30]
                p_obj = next((p for p in perspectives_global if p["pid"] == pid), None)
                if p_obj:
                    contribs[key] = contribs.get(key, 0) + p_obj["claims"]
        if contribs:
            sorted_c = sorted(contribs.items(), key=lambda x: x[1], reverse=True)
            total = sum(v for _, v in sorted_c)
            logger.info(f"\n  {ax.label} ({total} claims, {len(sorted_c)} topics):")
            for subj, claims in sorted_c:
                pct = 100 * claims / total
                bar = "#" * min(int(claims / 40), 25)
                logger.info(f"    {claims:>5} ({pct:>4.0f}%) | {subj:<30} {bar}")

    elapsed = round(time.time() - start, 1)
    logger.info(f"\nDone in {elapsed}s")
    driver.close()


if __name__ == "__main__":
    main()
