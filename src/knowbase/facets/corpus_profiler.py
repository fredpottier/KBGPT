"""
FacetEngine V2 — Corpus Geometry Profiler.

Analyse les proprietes geometriques de l'espace d'embedding
AVANT le clustering, pour adapter automatiquement les parametres.

Signaux mesures :
  A. Similarite globale (mean, std, quantiles)
  B. Structure locale des voisinages (top-K neighbors)
  C. Dominance documentaire (voisins du meme doc ?)
  D. Proto-clusterabilite (silhouette approx sur mini-clustering)

Le profil determine le "regime" du corpus :
  very_homogeneous | homogeneous | mixed | heterogeneous
"""
from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from typing import Dict, List, Optional

import numpy as np

logger = logging.getLogger(__name__)

SAMPLE_SIZE_PAIRWISE = 2000    # Paires aleatoires pour similarite globale
SAMPLE_SIZE_NEIGHBORS = 1000   # Claims pour analyse de voisinage
TOP_K_NEIGHBORS = 20


@dataclass
class CorpusGeometryProfile:
    """Profil geometrique du corpus d'embeddings."""
    n_items: int = 0

    # A. Similarite globale
    mean_pairwise_sim: float = 0.0
    std_pairwise_sim: float = 0.0
    similarity_quantiles: Dict[str, float] = field(default_factory=dict)

    # B. Structure locale
    mean_top5_neighbor_sim: float = 0.0
    mean_top20_neighbor_sim: float = 0.0
    neighbor_stability_score: float = 0.0   # Ecart entre top5 et top20

    # C. Dominance documentaire
    document_dominance_score: float = 0.0   # % voisins du meme doc

    # D. Proto-clusterabilite
    proto_clusterability_score: float = 0.0  # Silhouette approx

    # Regime detecte
    corpus_regime: str = "mixed"


@dataclass
class ClusteringPlan:
    """Plan de parametres adapte au corpus."""
    pca_dim: int = 100
    umap_n_components: int = 30
    umap_n_neighbors: int = 20
    umap_min_dist: float = 0.1
    hdbscan_min_cluster_size: int = 25
    hdbscan_min_samples: int = 8
    merge_similarity_threshold: float = 0.95
    noise_reassign_threshold: float = 0.85
    expected_n_clusters_range: tuple = (15, 80)
    max_iterations: int = 2
    regime: str = "mixed"


def profile_corpus(
    embeddings: np.ndarray,
    doc_ids: List[str],
    sample_seed: int = 42,
) -> CorpusGeometryProfile:
    """
    Analyse la geometrie du corpus d'embeddings.

    Args:
        embeddings: Matrice (N, D) normalisee
        doc_ids: Document ID de chaque item
        sample_seed: Seed pour reproductibilite

    Returns:
        CorpusGeometryProfile
    """
    rng = np.random.RandomState(sample_seed)
    n = len(embeddings)
    profile = CorpusGeometryProfile(n_items=n)

    logger.info(f"[CorpusProfiler] Profiling {n} items...")

    # === A. Similarite globale (echantillon pairwise) ===
    n_pairs = min(SAMPLE_SIZE_PAIRWISE, n * (n - 1) // 2)
    idx_a = rng.randint(0, n, size=n_pairs)
    idx_b = rng.randint(0, n, size=n_pairs)
    # Eviter les auto-paires
    mask = idx_a != idx_b
    idx_a, idx_b = idx_a[mask], idx_b[mask]

    # Cosine similarities (embeddings deja normalises)
    sims = np.sum(embeddings[idx_a] * embeddings[idx_b], axis=1)

    profile.mean_pairwise_sim = float(np.mean(sims))
    profile.std_pairwise_sim = float(np.std(sims))
    profile.similarity_quantiles = {
        "p10": float(np.percentile(sims, 10)),
        "p25": float(np.percentile(sims, 25)),
        "p50": float(np.percentile(sims, 50)),
        "p75": float(np.percentile(sims, 75)),
        "p90": float(np.percentile(sims, 90)),
    }

    logger.info(
        f"[CorpusProfiler] Global sim: mean={profile.mean_pairwise_sim:.3f}, "
        f"std={profile.std_pairwise_sim:.3f}, "
        f"p10={profile.similarity_quantiles['p10']:.3f}, "
        f"p90={profile.similarity_quantiles['p90']:.3f}"
    )

    # === B. Structure locale (top-K neighbors) ===
    sample_idx = rng.choice(n, size=min(SAMPLE_SIZE_NEIGHBORS, n), replace=False)
    sample_emb = embeddings[sample_idx]

    # Batch cosine avec tout le corpus
    # Pour eviter OOM, on fait par batch
    top5_sims = []
    top20_sims = []
    same_doc_ratios = []

    batch_size = 200
    for batch_start in range(0, len(sample_idx), batch_size):
        batch_end = min(batch_start + batch_size, len(sample_idx))
        batch_emb = sample_emb[batch_start:batch_end]
        batch_sample_idx = sample_idx[batch_start:batch_end]

        # Cosine: (batch, N)
        sim_matrix = batch_emb @ embeddings.T

        for i, global_idx in enumerate(batch_sample_idx):
            row = sim_matrix[i].copy()
            row[global_idx] = -1  # Exclure soi-meme

            # Top-K indices
            top_k_idx = np.argpartition(row, -TOP_K_NEIGHBORS)[-TOP_K_NEIGHBORS:]
            top_k_sims = row[top_k_idx]
            top_k_sorted = np.sort(top_k_sims)[::-1]

            top5_sims.append(float(np.mean(top_k_sorted[:5])))
            top20_sims.append(float(np.mean(top_k_sorted[:TOP_K_NEIGHBORS])))

            # Dominance documentaire
            my_doc = doc_ids[global_idx]
            same_doc = sum(1 for idx in top_k_idx if doc_ids[idx] == my_doc)
            same_doc_ratios.append(same_doc / TOP_K_NEIGHBORS)

    profile.mean_top5_neighbor_sim = float(np.mean(top5_sims))
    profile.mean_top20_neighbor_sim = float(np.mean(top20_sims))
    profile.neighbor_stability_score = profile.mean_top5_neighbor_sim - profile.mean_top20_neighbor_sim
    profile.document_dominance_score = float(np.mean(same_doc_ratios))

    logger.info(
        f"[CorpusProfiler] Local: top5={profile.mean_top5_neighbor_sim:.3f}, "
        f"top20={profile.mean_top20_neighbor_sim:.3f}, "
        f"stability={profile.neighbor_stability_score:.3f}, "
        f"doc_dominance={profile.document_dominance_score:.2%}"
    )

    # === D. Proto-clusterabilite (mini KMeans + silhouette approx) ===
    try:
        from sklearn.cluster import MiniBatchKMeans
        from sklearn.metrics import silhouette_score

        # Mini clustering sur l'echantillon avec K=10
        sample_for_sil = embeddings[rng.choice(n, size=min(2000, n), replace=False)]
        kmeans = MiniBatchKMeans(n_clusters=10, random_state=42, n_init=3)
        labels = kmeans.fit_predict(sample_for_sil)
        if len(set(labels)) > 1:
            sil = silhouette_score(sample_for_sil, labels, sample_size=1000)
            profile.proto_clusterability_score = float(sil)
        else:
            profile.proto_clusterability_score = 0.0
    except Exception as e:
        logger.warning(f"[CorpusProfiler] Silhouette failed: {e}")
        profile.proto_clusterability_score = 0.0

    logger.info(
        f"[CorpusProfiler] Proto-clusterability: {profile.proto_clusterability_score:.3f}"
    )

    # === Determiner le regime ===
    profile.corpus_regime = _determine_regime(profile)

    logger.info(
        f"[CorpusProfiler] Corpus regime: {profile.corpus_regime}"
    )

    return profile


def _determine_regime(p: CorpusGeometryProfile) -> str:
    """Determine le regime du corpus a partir du profil."""
    # Score composite
    # Plus la mean est haute et le std bas → plus homogene
    homogeneity = p.mean_pairwise_sim - p.std_pairwise_sim

    # Plus la stabilite est basse → plus continu (pas de vrais clusters)
    clusterability = p.neighbor_stability_score + p.proto_clusterability_score

    # Plus la dominance documentaire est haute → clusters = artefacts de docs
    doc_artefact = p.document_dominance_score

    if homogeneity > 0.78 and p.std_pairwise_sim < 0.05:
        return "very_homogeneous"
    elif homogeneity > 0.72 and p.std_pairwise_sim < 0.08:
        return "homogeneous"
    elif homogeneity < 0.55 or p.std_pairwise_sim > 0.15:
        return "heterogeneous"
    else:
        return "mixed"


def plan_clustering(profile: CorpusGeometryProfile) -> ClusteringPlan:
    """
    Genere un plan de clustering adapte au profil du corpus.

    Args:
        profile: Profil geometrique

    Returns:
        ClusteringPlan avec parametres adaptes
    """
    n = profile.n_items
    regime = profile.corpus_regime

    # Base : sqrt(n) comme reference
    base = math.sqrt(n)

    plan = ClusteringPlan(regime=regime)

    if regime == "very_homogeneous":
        # Corpus tres compact : forcer la separation, clusters fins
        plan.umap_min_dist = 0.20
        plan.umap_n_neighbors = 15
        plan.hdbscan_min_cluster_size = max(10, int(base * 0.08))
        plan.hdbscan_min_samples = max(3, int(base * 0.03))
        plan.merge_similarity_threshold = 0.97
        plan.noise_reassign_threshold = 0.88
        plan.expected_n_clusters_range = (20, 200)

    elif regime == "homogeneous":
        plan.umap_min_dist = 0.10
        plan.umap_n_neighbors = 20
        plan.hdbscan_min_cluster_size = max(15, int(base * 0.12))
        plan.hdbscan_min_samples = max(5, int(base * 0.04))
        plan.merge_similarity_threshold = 0.95
        plan.noise_reassign_threshold = 0.86
        plan.expected_n_clusters_range = (15, 100)

    elif regime == "heterogeneous":
        plan.umap_min_dist = 0.05
        plan.umap_n_neighbors = 30
        plan.hdbscan_min_cluster_size = max(25, int(base * 0.20))
        plan.hdbscan_min_samples = max(10, int(base * 0.08))
        plan.merge_similarity_threshold = 0.90
        plan.noise_reassign_threshold = 0.82
        plan.expected_n_clusters_range = (8, 50)

    else:  # mixed
        plan.umap_min_dist = 0.08
        plan.umap_n_neighbors = 25
        plan.hdbscan_min_cluster_size = max(20, int(base * 0.15))
        plan.hdbscan_min_samples = max(8, int(base * 0.06))
        plan.merge_similarity_threshold = 0.93
        plan.noise_reassign_threshold = 0.85
        plan.expected_n_clusters_range = (10, 80)

    # PCA dim adapte a la taille
    plan.pca_dim = min(100, n - 1)

    logger.info(
        f"[CorpusProfiler] Plan: regime={regime}, "
        f"min_cluster={plan.hdbscan_min_cluster_size}, "
        f"min_samples={plan.hdbscan_min_samples}, "
        f"umap_dist={plan.umap_min_dist}, "
        f"merge_thresh={plan.merge_similarity_threshold}"
    )

    return plan


def validate_clustering_result(
    n_clusters: int,
    n_noise: int,
    n_total: int,
    cluster_sizes: List[int],
    plan: ClusteringPlan,
) -> Dict[str, bool]:
    """
    Valide le resultat du clustering et detecte les problemes.

    Returns:
        Dict de warnings (True = probleme detecte)
    """
    warnings = {}

    # Mega-clusters : 2 clusters captent > 80%
    if len(cluster_sizes) >= 2:
        top2 = sum(sorted(cluster_sizes, reverse=True)[:2])
        if top2 / n_total > 0.80:
            warnings["mega_clusters"] = True
            logger.warning(
                f"[CorpusProfiler:Validate] Top 2 clusters capture {top2/n_total:.0%} — "
                f"corpus too homogeneous for current parameters"
            )

    # Trop de bruit
    noise_ratio = n_noise / n_total
    if noise_ratio > 0.60:
        warnings["high_noise"] = True
        logger.warning(
            f"[CorpusProfiler:Validate] {noise_ratio:.0%} noise — "
            f"parameters may be too strict"
        )

    # Hors range attendu
    lo, hi = plan.expected_n_clusters_range
    if n_clusters < lo:
        warnings["too_few_clusters"] = True
        logger.warning(f"[CorpusProfiler:Validate] {n_clusters} clusters < expected {lo}")
    elif n_clusters > hi * 1.5:
        warnings["too_many_clusters"] = True
        logger.warning(f"[CorpusProfiler:Validate] {n_clusters} clusters > expected {hi}")

    if not warnings:
        logger.info(
            f"[CorpusProfiler:Validate] Clustering OK: {n_clusters} clusters, "
            f"{noise_ratio:.0%} noise"
        )

    return warnings
