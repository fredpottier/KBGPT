"""
FacetEngine V2 — Clustering Emergent (Pass F2b).

Pipeline :
  1. Reduction de dimension (PCA → UMAP)
  2. Clustering HDBSCAN
  3. Post-processing (merge quasi-doublons, re-attach bruit)
  4. Labellisation LLM (label + description + frontiere negative)
  5. Filtrage qualite (taille, diversite, genericity)

Les clusters deviennent des FacetCandidate, pas des Facet directement.
La promotion en Facet est geree par la governance.
"""
from __future__ import annotations

import logging
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple

import numpy as np

logger = logging.getLogger(__name__)

# Les parametres ne sont plus hardcodes ici.
# Ils sont generes par le CorpusGeometryProfiler → AdaptiveClusteringPlanner.
# Voir corpus_profiler.py pour les valeurs par regime.
MIN_FACET_SIZE = 20
MIN_FACET_DOCS = 2
MAX_DOC_CONCENTRATION = 0.85
MAX_FACETS_PER_CLAIM = 3


@dataclass
class ClusterCandidate:
    """Cluster brut issu de HDBSCAN."""
    cluster_id: int
    member_indices: List[int] = field(default_factory=list)
    centroid_full: Optional[np.ndarray] = None  # 1024d
    centroid_reduced: Optional[np.ndarray] = None
    size: int = 0
    persistence: float = 0.0
    top_entity_ids: List[str] = field(default_factory=list)
    doc_distribution: Dict[str, int] = field(default_factory=dict)


@dataclass
class EmergentFacet:
    """Facette emergente issue du clustering + labellisation."""
    facet_id: str
    canonical_label: str
    description: str
    negative_boundary: str = ""
    aliases: List[str] = field(default_factory=list)
    facet_family: str = "cross_cutting_concern"
    centroid: Optional[np.ndarray] = None
    member_count: int = 0
    doc_count: int = 0
    quality: str = "good"  # good | weak | too_generic
    genericity_score: float = 0.0
    prototype_claim_indices: List[int] = field(default_factory=list)


def cluster_claims(
    claim_embeddings: np.ndarray,
    claim_ids: List[str],
    claim_doc_ids: List[str],
    claim_entity_map: Optional[Dict[str, List[str]]] = None,
    plan: Optional[Any] = None,
) -> Tuple[List[ClusterCandidate], np.ndarray]:
    """
    Phase 1+2 : Reduction + HDBSCAN clustering.

    Args:
        claim_embeddings: Matrice (N, 1024) normalisee
        claim_ids: IDs des claims
        claim_doc_ids: doc_id de chaque claim
        claim_entity_map: mapping claim_id → [entity_ids]
        plan: ClusteringPlan adaptatif (si None, valeurs par defaut)

    Returns:
        (clusters, labels) ou labels est le vecteur HDBSCAN (-1 = bruit)
    """
    import hdbscan
    from sklearn.decomposition import PCA

    # Parametres depuis le plan adaptatif ou defaults
    if plan is None:
        from knowbase.facets.corpus_profiler import ClusteringPlan
        plan = ClusteringPlan()

    n_claims = len(claim_embeddings)
    logger.info(
        f"[FacetEngine:Cluster] Starting clustering on {n_claims} claims "
        f"(regime={plan.regime})"
    )

    # Phase 1a : PCA
    pca_dim = min(plan.pca_dim, n_claims - 1)
    logger.info(f"[FacetEngine:Cluster] PCA {claim_embeddings.shape[1]} → {pca_dim}")
    pca = PCA(n_components=pca_dim)
    embeddings_pca = pca.fit_transform(claim_embeddings)
    variance_explained = pca.explained_variance_ratio_.sum()
    logger.info(f"[FacetEngine:Cluster] PCA variance explained: {variance_explained:.2%}")

    # Phase 1b : UMAP
    try:
        import umap
        umap_dim = plan.umap_n_components
        logger.info(
            f"[FacetEngine:Cluster] UMAP {embeddings_pca.shape[1]} → {umap_dim} "
            f"(n_neighbors={plan.umap_n_neighbors}, min_dist={plan.umap_min_dist})"
        )
        reducer = umap.UMAP(
            n_components=umap_dim,
            n_neighbors=plan.umap_n_neighbors,
            min_dist=plan.umap_min_dist,
            metric="cosine",
            random_state=42,
        )
        embeddings_reduced = reducer.fit_transform(embeddings_pca)
    except ImportError:
        logger.warning("[FacetEngine:Cluster] UMAP not available, using PCA directly")
        embeddings_reduced = embeddings_pca

    # Phase 2 : HDBSCAN
    logger.info(
        f"[FacetEngine:Cluster] HDBSCAN min_cluster_size={plan.hdbscan_min_cluster_size}, "
        f"min_samples={plan.hdbscan_min_samples}"
    )
    clusterer = hdbscan.HDBSCAN(
        min_cluster_size=plan.hdbscan_min_cluster_size,
        min_samples=plan.hdbscan_min_samples,
        cluster_selection_method="eom",
        metric="euclidean",
    )
    labels = clusterer.fit_predict(embeddings_reduced)

    n_clusters = len(set(labels)) - (1 if -1 in labels else 0)
    n_noise = (labels == -1).sum()
    logger.info(
        f"[FacetEngine:Cluster] HDBSCAN: {n_clusters} clusters, "
        f"{n_noise} noise points ({n_noise * 100 // n_claims}%)"
    )

    # Construire les ClusterCandidate
    clusters: List[ClusterCandidate] = []
    for cid in range(n_clusters):
        indices = np.where(labels == cid)[0].tolist()
        if not indices:
            continue

        # Centroid dans l'espace original 1024d
        centroid_full = claim_embeddings[indices].mean(axis=0)
        norm = np.linalg.norm(centroid_full)
        if norm > 0:
            centroid_full = centroid_full / norm

        # Distribution par document
        doc_dist = Counter()
        for idx in indices:
            doc_dist[claim_doc_ids[idx]] += 1

        # Top entities
        top_entities = []
        if claim_entity_map:
            entity_counter = Counter()
            for idx in indices:
                cid_str = claim_ids[idx]
                for eid in claim_entity_map.get(cid_str, []):
                    entity_counter[eid] += 1
            top_entities = [eid for eid, _ in entity_counter.most_common(10)]

        clusters.append(ClusterCandidate(
            cluster_id=cid,
            member_indices=indices,
            centroid_full=centroid_full,
            centroid_reduced=embeddings_reduced[indices].mean(axis=0) if len(indices) > 0 else None,
            size=len(indices),
            top_entity_ids=top_entities,
            doc_distribution=dict(doc_dist),
        ))

    # Trier par taille decroissante
    clusters.sort(key=lambda c: c.size, reverse=True)

    return clusters, labels


def post_process_clusters(
    clusters: List[ClusterCandidate],
    claim_embeddings: np.ndarray,
    labels: np.ndarray,
    claim_doc_ids: List[str],
    plan: Optional[Any] = None,
) -> List[ClusterCandidate]:
    """
    Phase 3 : Merge quasi-doublons + re-attach bruit.
    """
    from knowbase.facets.scorer import cosine_similarity

    merge_thresh = 0.95
    noise_thresh = 0.87
    if plan:
        merge_thresh = plan.merge_similarity_threshold
        noise_thresh = plan.noise_reassign_threshold

    # 3.1 Merge quasi-doublons
    merged = set()
    for i in range(len(clusters)):
        if i in merged:
            continue
        for j in range(i + 1, len(clusters)):
            if j in merged:
                continue
            if clusters[i].centroid_full is None or clusters[j].centroid_full is None:
                continue
            sim = cosine_similarity(clusters[i].centroid_full, clusters[j].centroid_full)
            if sim >= merge_thresh:
                # Fusionner j dans i
                clusters[i].member_indices.extend(clusters[j].member_indices)
                clusters[i].size = len(clusters[i].member_indices)
                # Recalculer le centroid
                centroid = claim_embeddings[clusters[i].member_indices].mean(axis=0)
                norm = np.linalg.norm(centroid)
                if norm > 0:
                    centroid = centroid / norm
                clusters[i].centroid_full = centroid
                # Fusionner doc distribution
                for doc, cnt in clusters[j].doc_distribution.items():
                    clusters[i].doc_distribution[doc] = clusters[i].doc_distribution.get(doc, 0) + cnt
                merged.add(j)
                logger.debug(
                    f"[FacetEngine:Cluster] Merged cluster {j} into {i} (sim={sim:.3f})"
                )

    result = [c for i, c in enumerate(clusters) if i not in merged]

    if merged:
        logger.info(
            f"[FacetEngine:Cluster] Merged {len(merged)} quasi-duplicate clusters, "
            f"{len(result)} remaining"
        )

    # 3.2 Re-attach noise points (WEAK assignment)
    noise_indices = np.where(labels == -1)[0]
    reattached = 0
    for idx in noise_indices:
        emb = claim_embeddings[idx]
        best_sim = 0
        best_cluster = None
        for c in result:
            if c.centroid_full is None:
                continue
            sim = cosine_similarity(emb, c.centroid_full)
            if sim > best_sim:
                best_sim = sim
                best_cluster = c
        if best_cluster and best_sim >= noise_thresh:
            best_cluster.member_indices.append(int(idx))
            best_cluster.size += 1
            reattached += 1

    if reattached > 0:
        logger.info(
            f"[FacetEngine:Cluster] Re-attached {reattached}/{len(noise_indices)} noise points"
        )

    return result


def filter_clusters(
    clusters: List[ClusterCandidate],
    claim_doc_ids: List[str],
) -> List[ClusterCandidate]:
    """
    Phase 5 : Filtrage qualite des clusters.
    """
    filtered = []
    for c in clusters:
        # Taille minimum
        if c.size < MIN_FACET_SIZE:
            continue
        # Diversite documentaire
        if len(c.doc_distribution) < MIN_FACET_DOCS:
            continue
        # Concentration max
        top_doc_pct = max(c.doc_distribution.values()) / c.size if c.doc_distribution else 0
        if top_doc_pct > MAX_DOC_CONCENTRATION:
            continue
        filtered.append(c)

    logger.info(
        f"[FacetEngine:Cluster] Quality filter: {len(clusters)} → {len(filtered)} clusters"
    )
    return filtered


def label_clusters_with_llm(
    clusters: List[ClusterCandidate],
    claim_texts: List[str],
    claim_ids: List[str],
    claim_entity_map: Optional[Dict[str, List[str]]] = None,
    entity_names: Optional[Dict[str, str]] = None,
    llm_fn: Optional[Callable] = None,
) -> List[EmergentFacet]:
    """
    Phase 4 : Labellisation LLM de chaque cluster.
    """
    if not llm_fn:
        # Fallback : labels generiques
        return _label_clusters_generic(clusters, claim_texts)

    system_prompt = """You are a document analyst. Given a cluster of claims from a technical document corpus,
you must name and describe the cross-cutting dimension (facet) it represents.

Output JSON:
{
  "canonical_label": "short name (1-3 words)",
  "description": "what this facet covers (1-2 sentences)",
  "negative_boundary": "what this facet does NOT include (1 sentence)",
  "family": "thematic | normative | operational",
  "quality": "good | weak | too_generic",
  "genericity_score": 0.0-1.0
}"""

    facets: List[EmergentFacet] = []

    for i, cluster in enumerate(clusters):
        # Construire le contexte pour le LLM
        central_indices = cluster.member_indices[:8]
        border_indices = cluster.member_indices[-4:] if len(cluster.member_indices) > 12 else []

        central_texts = [claim_texts[idx][:150] for idx in central_indices]
        border_texts = [claim_texts[idx][:150] for idx in border_indices]

        # Top entities
        top_ents = ""
        if claim_entity_map and entity_names:
            ent_counter = Counter()
            for idx in cluster.member_indices[:50]:
                for eid in claim_entity_map.get(claim_ids[idx], []):
                    name = entity_names.get(eid, eid)
                    ent_counter[name] += 1
            top_ents = ", ".join([n for n, _ in ent_counter.most_common(10)])

        user_prompt = (
            f"Cluster {i + 1} ({cluster.size} claims, {len(cluster.doc_distribution)} docs):\n\n"
            f"Central claims:\n" + "\n".join(f"- {t}" for t in central_texts) + "\n\n"
        )
        if border_texts:
            user_prompt += f"Border claims:\n" + "\n".join(f"- {t}" for t in border_texts) + "\n\n"
        if top_ents:
            user_prompt += f"Top entities: {top_ents}\n\n"
        user_prompt += "Name and describe this facet."

        try:
            response = llm_fn(system_prompt, user_prompt)
            facet = _parse_llm_label(response, cluster, i)
            if facet:
                facets.append(facet)
                logger.info(
                    f"[FacetEngine:Label] Cluster {i}: '{facet.canonical_label}' "
                    f"({cluster.size} claims, quality={facet.quality})"
                )
            else:
                # Fallback generic
                facet = _make_generic_facet(cluster, i, claim_texts)
                facets.append(facet)
        except Exception as e:
            logger.warning(f"[FacetEngine:Label] LLM failed for cluster {i}: {e}")
            facet = _make_generic_facet(cluster, i, claim_texts)
            facets.append(facet)

    return facets


def _parse_llm_label(response: str, cluster: ClusterCandidate, idx: int) -> Optional[EmergentFacet]:
    """Parse la reponse JSON du LLM."""
    import json, re

    text = response.strip()
    if "```json" in text:
        text = text.split("```json")[1].split("```")[0]
    elif "```" in text:
        text = text.split("```")[1].split("```")[0]

    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r'\{[\s\S]*"canonical_label"[\s\S]*\}', text)
        if match:
            try:
                data = json.loads(match.group())
            except json.JSONDecodeError:
                return None
        else:
            return None

    label = data.get("canonical_label", f"Cluster_{idx}")
    if not label or len(label) < 2:
        return None

    return EmergentFacet(
        facet_id=f"facet_emergent_{label.lower().replace(' ', '_').replace('&', 'and')[:30]}",
        canonical_label=label,
        description=data.get("description", ""),
        negative_boundary=data.get("negative_boundary", ""),
        facet_family=data.get("family", "cross_cutting_concern"),
        centroid=cluster.centroid_full,
        member_count=cluster.size,
        doc_count=len(cluster.doc_distribution),
        quality=data.get("quality", "good"),
        genericity_score=data.get("genericity_score", 0.0),
        prototype_claim_indices=cluster.member_indices[:20],
    )


def _make_generic_facet(cluster: ClusterCandidate, idx: int, claim_texts: List[str]) -> EmergentFacet:
    """Cree une facette generique sans LLM."""
    # Prendre les premiers mots des claims centrales
    sample = " ".join(claim_texts[i][:50] for i in cluster.member_indices[:3])
    label = f"Topic_{idx + 1}"

    return EmergentFacet(
        facet_id=f"facet_emergent_topic_{idx + 1}",
        canonical_label=label,
        description=f"Cluster of {cluster.size} claims",
        centroid=cluster.centroid_full,
        member_count=cluster.size,
        doc_count=len(cluster.doc_distribution),
        quality="weak",
        genericity_score=0.5,
        prototype_claim_indices=cluster.member_indices[:20],
    )


def _label_clusters_generic(
    clusters: List[ClusterCandidate],
    claim_texts: List[str],
) -> List[EmergentFacet]:
    """Labellisation sans LLM (fallback)."""
    return [_make_generic_facet(c, i, claim_texts) for i, c in enumerate(clusters)]


def run_emergent_clustering(
    claim_embeddings: np.ndarray,
    claim_ids: List[str],
    claim_texts: List[str],
    claim_doc_ids: List[str],
    claim_entity_map: Optional[Dict[str, List[str]]] = None,
    entity_names: Optional[Dict[str, str]] = None,
    llm_fn: Optional[Callable] = None,
) -> List[EmergentFacet]:
    """
    Pipeline complet de clustering emergent.

    Inclut la calibration automatique via CorpusGeometryProfiler.

    Returns:
        Liste de EmergentFacet candidates.
    """
    from knowbase.facets.corpus_profiler import (
        profile_corpus, plan_clustering, validate_clustering_result,
    )

    # === Phase 0 : Profiler le corpus ===
    logger.info("[FacetEngine:Cluster] Phase 0: Profiling corpus geometry...")
    profile = profile_corpus(claim_embeddings, claim_doc_ids)
    plan = plan_clustering(profile)

    # === Phase 1+2 : Clustering avec plan adaptatif ===
    clusters, labels = cluster_claims(
        claim_embeddings, claim_ids, claim_doc_ids, claim_entity_map,
        plan=plan,
    )

    # === Validation post-clustering ===
    cluster_sizes = [c.size for c in clusters]
    n_noise = int((labels == -1).sum())
    warnings = validate_clustering_result(
        n_clusters=len(clusters),
        n_noise=n_noise,
        n_total=len(claim_ids),
        cluster_sizes=cluster_sizes,
        plan=plan,
    )

    # Si mega-clusters detectes et on a du budget pour une iteration,
    # on pourrait re-clusteriser avec des params plus stricts.
    # Pour le Sprint 1, on log juste le warning.
    if warnings.get("mega_clusters"):
        logger.warning(
            "[FacetEngine:Cluster] Mega-clusters detected — "
            "consider adjusting UMAP min_dist or HDBSCAN min_cluster_size"
        )

    # === Phase 3 : Post-processing ===
    clusters = post_process_clusters(
        clusters, claim_embeddings, labels, claim_doc_ids, plan=plan,
    )

    # === Phase 5 : Filtrage qualite ===
    clusters = filter_clusters(clusters, claim_doc_ids)

    # Phase 4 : Labellisation
    facets = label_clusters_with_llm(
        clusters, claim_texts, claim_ids,
        claim_entity_map, entity_names, llm_fn
    )

    # Retirer les facettes trop generiques
    good_facets = [f for f in facets if f.quality != "too_generic"]
    if len(good_facets) < len(facets):
        logger.info(
            f"[FacetEngine:Cluster] Removed {len(facets) - len(good_facets)} "
            f"too-generic facets"
        )

    logger.info(
        f"[FacetEngine:Cluster] Final: {len(good_facets)} emergent facets "
        f"from {len(claim_ids)} claims"
    )

    return good_facets
