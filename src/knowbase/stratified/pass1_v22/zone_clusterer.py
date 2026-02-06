"""
OSMOSE Pipeline V2.2 - Pass 1.B: Clustering Zone-First
=======================================================
Clustering HDBSCAN intra-zone puis fusion inter-zones.

Invariant I2: JAMAIS de clustering global flat.
Le code DOIT structurellement parcourir zone par zone, puis fusionner.

Pattern prouvé: logique de topic_segmenter.py:_cluster_with_min_topics()
"""

import logging
from collections import defaultdict
from typing import Dict, List, Optional, Tuple

import numpy as np

from knowbase.stratified.pass09.models import Zone
from knowbase.stratified.pass1_v22.models import AssertionCluster, ZonedAssertion

logger = logging.getLogger(__name__)


def _cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
    """Cosine similarity entre deux vecteurs."""
    dot = np.dot(a, b)
    norm_a = np.linalg.norm(a)
    norm_b = np.linalg.norm(b)
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return float(dot / (norm_a * norm_b))


def _jaccard_similarity(set_a: set, set_b: set) -> float:
    """Jaccard similarity entre deux ensembles."""
    if not set_a and not set_b:
        return 0.0
    intersection = set_a & set_b
    union = set_a | set_b
    return len(intersection) / len(union) if union else 0.0


class ZoneFirstClusterer:
    """
    Pass 1.B — Clustering zone-first avec HDBSCAN.

    Phase B.1: Clustering intra-zone (HDBSCAN par zone)
    Phase B.2: Fusion inter-zones (centroïdes, seuils adaptatifs)
    Phase B.3: Filtrage I4 (support_count minimum)

    LIGNE ROUGE I2: assert all(c.zone_ids for c in clusters)
    """

    def cluster(
        self,
        assertions: List[ZonedAssertion],
        embeddings: np.ndarray,
        zones: List[Zone],
        min_cluster_size: int = 3,
        fusion_threshold: float = 0.80,
    ) -> Tuple[List[AssertionCluster], List[int]]:
        """
        Clustering zone-first des assertions.

        Args:
            assertions: Assertions zonées
            embeddings: Embeddings (N, dim)
            zones: Zones documentaires
            min_cluster_size: Taille minimum de cluster HDBSCAN
            fusion_threshold: Seuil par défaut de fusion inter-zones

        Returns:
            (clusters candidats, indices assertions UNLINKED)
        """
        if not assertions or embeddings.shape[0] == 0:
            return [], list(range(len(assertions)))

        logger.info(
            f"[OSMOSE:Pass1:V2.2:1B] Clustering {len(assertions)} assertions "
            f"across {len(zones)} zones"
        )

        # Normaliser L2 tous les embeddings (cosine geometry via distance euclidienne)
        norms = np.linalg.norm(embeddings, axis=1, keepdims=True)
        norms[norms == 0] = 1.0
        normalized = embeddings / norms

        # Construire index par zone
        zone_to_indices: Dict[str, List[int]] = defaultdict(list)
        for idx, assertion in enumerate(assertions):
            zone_to_indices[assertion.zone_id].append(idx)

        # Phase B.1: Clustering intra-zone
        all_clusters: List[AssertionCluster] = []
        all_outliers: List[int] = []
        cluster_counter = 0

        # Construire zone_id → zone pour lookup keywords
        zone_map = {z.zone_id: z for z in zones}

        for zone_id, indices in zone_to_indices.items():
            if len(indices) < min_cluster_size:
                # Zone trop petite: toutes les assertions sont outliers
                all_outliers.extend(indices)
                continue

            zone_embeddings = normalized[indices]

            clusters, outliers = self._cluster_intra_zone(
                zone_id=zone_id,
                indices=indices,
                embeddings=zone_embeddings,
                min_cluster_size=min_cluster_size,
                start_counter=cluster_counter,
            )

            all_clusters.extend(clusters)
            all_outliers.extend(outliers)
            cluster_counter += len(clusters)

        logger.info(
            f"[OSMOSE:Pass1:V2.2:1B] Intra-zone: {len(all_clusters)} clusters, "
            f"{len(all_outliers)} outliers"
        )

        # Phase B.2: Fusion inter-zones
        if len(all_clusters) > 1:
            all_clusters = self._fuse_inter_zones(
                clusters=all_clusters,
                normalized_embeddings=normalized,
                assertions=assertions,
                zone_map=zone_map,
            )

            logger.info(
                f"[OSMOSE:Pass1:V2.2:1B] Post-fusion: {len(all_clusters)} clusters"
            )

        # Phase B.3: Filtrage I4
        active_clusters = []
        newly_unlinked = list(all_outliers)

        for cluster in all_clusters:
            if cluster.support_count < 3:
                # Pas assez de support: UNLINKED
                newly_unlinked.extend(cluster.assertion_indices)
            elif cluster.support_count <= 4 and cluster.intra_similarity < 0.60:
                # Petit cluster avec faible cohésion: UNLINKED
                newly_unlinked.extend(cluster.assertion_indices)
            else:
                active_clusters.append(cluster)

        logger.info(
            f"[OSMOSE:Pass1:V2.2:1B] Final: {len(active_clusters)} clusters, "
            f"{len(newly_unlinked)} unlinked assertions"
        )

        # Invariant I2: vérifier que chaque cluster a au moins un zone_id
        assert all(c.zone_ids for c in active_clusters), \
            "LIGNE ROUGE I2: tous les clusters doivent avoir au moins un zone_id"

        return active_clusters, newly_unlinked

    def _cluster_intra_zone(
        self,
        zone_id: str,
        indices: List[int],
        embeddings: np.ndarray,
        min_cluster_size: int,
        start_counter: int,
    ) -> Tuple[List[AssertionCluster], List[int]]:
        """
        Clustering HDBSCAN sur une zone unique.

        Fallback AgglomerativeClustering si HDBSCAN produit trop d'outliers (>60%).
        """
        labels = self._run_hdbscan(embeddings, min_cluster_size)

        # Vérifier taux d'outliers
        n_outliers = np.sum(labels == -1)
        outlier_ratio = n_outliers / len(labels) if len(labels) > 0 else 1.0

        if outlier_ratio > 0.60:
            logger.info(
                f"[OSMOSE:Pass1:V2.2:1B] Zone {zone_id}: HDBSCAN outlier ratio "
                f"{outlier_ratio:.0%} > 60%, using AgglomerativeClustering fallback"
            )
            labels = self._run_agglomerative(embeddings, min_cluster_size)

        # Construire les clusters
        clusters = []
        outlier_indices = []
        label_to_indices: Dict[int, List[int]] = defaultdict(list)

        for i, label in enumerate(labels):
            if label == -1:
                outlier_indices.append(indices[i])
            else:
                label_to_indices[label].append(i)

        for label, local_indices in label_to_indices.items():
            global_indices = [indices[li] for li in local_indices]
            cluster_embeddings = embeddings[local_indices]

            # Calculer centroïde
            centroid = np.mean(cluster_embeddings, axis=0)
            centroid_norm = np.linalg.norm(centroid)
            if centroid_norm > 0:
                centroid = centroid / centroid_norm

            # Calculer intra_similarity: mean cosine(assertion, centroid)
            similarities = cluster_embeddings @ centroid
            intra_sim = float(np.mean(similarities))

            clusters.append(
                AssertionCluster(
                    cluster_id=f"cl_{start_counter + len(clusters)}",
                    zone_ids=[zone_id],
                    assertion_indices=global_indices,
                    support_count=len(global_indices),
                    centroid=centroid,
                    intra_similarity=intra_sim,
                )
            )

        return clusters, outlier_indices

    def _run_hdbscan(
        self, embeddings: np.ndarray, min_cluster_size: int
    ) -> np.ndarray:
        """Exécute HDBSCAN et retourne les labels."""
        try:
            import hdbscan

            clusterer = hdbscan.HDBSCAN(
                min_cluster_size=min_cluster_size,
                metric="euclidean",
                cluster_selection_method="eom",
            )
            labels = clusterer.fit_predict(embeddings)
            return labels
        except ImportError:
            logger.warning(
                "[OSMOSE:Pass1:V2.2:1B] hdbscan not installed, "
                "using AgglomerativeClustering"
            )
            return self._run_agglomerative(embeddings, min_cluster_size)

    def _run_agglomerative(
        self, embeddings: np.ndarray, min_cluster_size: int
    ) -> np.ndarray:
        """
        Fallback: AgglomerativeClustering.

        Estime le nombre de clusters depuis la taille des données.
        """
        try:
            from sklearn.cluster import AgglomerativeClustering

            n_samples = embeddings.shape[0]
            # Heuristique: max(2, n/min_cluster_size), capped à 15
            n_clusters = max(2, min(15, n_samples // max(min_cluster_size, 1)))

            if n_samples < n_clusters:
                n_clusters = max(1, n_samples)

            clusterer = AgglomerativeClustering(
                n_clusters=n_clusters,
                metric="cosine",
                linkage="average",
            )
            labels = clusterer.fit_predict(embeddings)
            return labels
        except ImportError:
            logger.warning(
                "[OSMOSE:Pass1:V2.2:1B] sklearn not installed, "
                "assigning all to single cluster"
            )
            return np.zeros(embeddings.shape[0], dtype=int)

    def _fuse_inter_zones(
        self,
        clusters: List[AssertionCluster],
        normalized_embeddings: np.ndarray,
        assertions: List[ZonedAssertion],
        zone_map: Dict[str, Zone],
    ) -> List[AssertionCluster]:
        """
        Fusion inter-zones basée sur les centroïdes.

        Seuils adaptatifs:
        - Zones adjacentes: fusion >= 0.75, ou >= 0.60 si Jaccard(keywords) > 0.3
        - Zones non-adjacentes: fusion >= 0.85, ou >= 0.75 si Jaccard(keywords) > 0.5
        """
        if len(clusters) <= 1:
            return clusters

        # Construire les paires candidates pour fusion
        merged = set()  # Indices des clusters déjà fusionnés
        result = list(clusters)

        # Itérer sur toutes les paires
        i = 0
        while i < len(result):
            if i in merged:
                i += 1
                continue

            j = i + 1
            while j < len(result):
                if j in merged:
                    j += 1
                    continue

                ci = result[i]
                cj = result[j]

                if ci.centroid is None or cj.centroid is None:
                    j += 1
                    continue

                sim = _cosine_similarity(ci.centroid, cj.centroid)
                adjacent = self._zones_adjacent(ci.zone_ids, cj.zone_ids)

                # Calculer Jaccard(keywords) pour décision fine
                kw_i = self._get_zone_keywords(ci.zone_ids, zone_map)
                kw_j = self._get_zone_keywords(cj.zone_ids, zone_map)
                jaccard = _jaccard_similarity(kw_i, kw_j)

                should_fuse = False
                if adjacent:
                    if sim >= 0.75:
                        should_fuse = True
                    elif sim >= 0.60 and jaccard > 0.3:
                        should_fuse = True
                else:
                    if sim >= 0.85:
                        should_fuse = True
                    elif sim >= 0.75 and jaccard > 0.5:
                        should_fuse = True

                if should_fuse:
                    # Fusionner j dans i
                    fused = self._merge_clusters(ci, cj, normalized_embeddings)
                    result[i] = fused
                    merged.add(j)

                j += 1
            i += 1

        # Filtrer les clusters fusionnés
        final = [c for idx, c in enumerate(result) if idx not in merged]
        return final

    def _zones_adjacent(
        self, zone_ids_a: List[str], zone_ids_b: List[str]
    ) -> bool:
        """Vérifie si deux ensembles de zones sont adjacents."""

        def _zone_number(zid: str) -> int:
            try:
                return int(zid.lstrip("z"))
            except (ValueError, AttributeError):
                return -1

        nums_a = {_zone_number(z) for z in zone_ids_a}
        nums_b = {_zone_number(z) for z in zone_ids_b}

        for na in nums_a:
            for nb in nums_b:
                if abs(na - nb) <= 1:
                    return True
        return False

    def _get_zone_keywords(
        self, zone_ids: List[str], zone_map: Dict[str, Zone]
    ) -> set:
        """Récupère les keywords agrégés d'un ensemble de zones."""
        keywords = set()
        for zid in zone_ids:
            zone = zone_map.get(zid)
            if zone:
                keywords.update(kw.lower() for kw in zone.keywords)
        return keywords

    def _merge_clusters(
        self,
        a: AssertionCluster,
        b: AssertionCluster,
        normalized_embeddings: np.ndarray,
    ) -> AssertionCluster:
        """Fusionne deux clusters."""
        merged_indices = a.assertion_indices + b.assertion_indices
        merged_zone_ids = list(set(a.zone_ids + b.zone_ids))

        # Recalculer centroïde
        if merged_indices:
            cluster_embeddings = normalized_embeddings[merged_indices]
            centroid = np.mean(cluster_embeddings, axis=0)
            norm = np.linalg.norm(centroid)
            if norm > 0:
                centroid = centroid / norm

            similarities = cluster_embeddings @ centroid
            intra_sim = float(np.mean(similarities))
        else:
            centroid = a.centroid
            intra_sim = (a.intra_similarity + b.intra_similarity) / 2

        return AssertionCluster(
            cluster_id=a.cluster_id,  # Garder l'ID du premier
            zone_ids=merged_zone_ids,
            assertion_indices=merged_indices,
            support_count=len(merged_indices),
            centroid=centroid,
            intra_similarity=intra_sim,
        )
