# src/knowbase/claimfirst/linkers/facet_registry.py
"""
FacetRegistry — Tier 2 du Facet Registry émergent.

Registre gouverné avec lifecycle (candidate → validated → deprecated).
Promotion automatique à ≥3 documents + diversité minimale des sources.
Near-duplicate detection sans merge auto (INV-9).
Seed facets injectées au premier load si registre vide.
"""

from __future__ import annotations

import logging
from typing import Dict, List, Optional, Tuple

from knowbase.claimfirst.models.facet import (
    Facet,
    FacetFamily,
    FacetLifecycle,
    _now_iso,
    get_seed_facets,
)
from knowbase.claimfirst.extractors.facet_candidate_extractor import FacetCandidate

logger = logging.getLogger("[OSMOSE] facet_registry")


def _levenshtein_distance(s1: str, s2: str) -> int:
    """Distance de Levenshtein entre deux chaînes."""
    if len(s1) < len(s2):
        return _levenshtein_distance(s2, s1)
    if len(s2) == 0:
        return len(s1)

    prev_row = list(range(len(s2) + 1))
    for i, c1 in enumerate(s1):
        curr_row = [i + 1]
        for j, c2 in enumerate(s2):
            cost = 0 if c1 == c2 else 1
            curr_row.append(min(
                curr_row[j] + 1,
                prev_row[j + 1] + 1,
                prev_row[j] + cost,
            ))
        prev_row = curr_row

    return prev_row[-1]


def _keywords_overlap(kw1: List[str], kw2: List[str]) -> float:
    """Pourcentage de chevauchement entre deux listes de keywords."""
    if not kw1 or not kw2:
        return 0.0
    s1 = set(k.lower() for k in kw1)
    s2 = set(k.lower() for k in kw2)
    intersection = len(s1 & s2)
    union = len(s1 | s2)
    return intersection / union if union > 0 else 0.0


class FacetRegistry:
    """
    Registre gouverné de facettes avec lifecycle et promotion automatique.

    PROMOTION : source_doc_count >= 3 ET au moins 2 titres de docs distincts.
    NEAR-DUPLICATES : détectés mais PAS mergés (INV-9).
    """

    PROMOTION_THRESHOLD = 3
    DIVERSITY_MIN_FAMILIES = 2  # titres de documents distincts minimum

    NEAR_DUP_LEVENSHTEIN_MAX = 3
    NEAR_DUP_KEYWORDS_OVERLAP_MIN = 0.6

    def __init__(self, tenant_id: str):
        self._cache: Dict[str, Facet] = {}  # dimension_key → Facet
        self._near_duplicates: List[Tuple[str, str, float]] = []  # (key1, key2, score)
        self._modified_keys: set = set()  # dimension_keys modifiées depuis load
        self.tenant_id = tenant_id

    def load_from_neo4j(self, neo4j_driver=None) -> None:
        """
        Charge facettes existantes depuis Neo4j.
        Si registre vide, injecte seed facets.
        """
        if neo4j_driver:
            try:
                with neo4j_driver.session() as session:
                    result = session.run(
                        """
                        MATCH (f:Facet {tenant_id: $tid})
                        RETURN f
                        """,
                        tid=self.tenant_id,
                    )
                    for record in result:
                        node = record["f"]
                        try:
                            facet = Facet.from_neo4j_record(dict(node))
                            self._cache[facet.domain] = facet
                        except Exception as e:
                            logger.debug(f"Skipping facet: {e}")
                            continue

                logger.info(
                    f"[OSMOSE:FacetRegistry] Loaded {len(self._cache)} facets from Neo4j"
                )
            except Exception as e:
                logger.error(f"[OSMOSE:FacetRegistry] Failed to load from Neo4j: {e}")

        # Seed si vide
        if not self._cache:
            self._inject_seeds()

    def _inject_seeds(self) -> None:
        """Injecte les seed facets si le registre est vide."""
        seeds = get_seed_facets(self.tenant_id)
        for seed in seeds:
            self._cache[seed.domain] = seed
        logger.info(
            f"[OSMOSE:FacetRegistry] Injected {len(seeds)} seed facets"
        )

    def register_candidates(
        self,
        candidates: List[FacetCandidate],
    ) -> List[Facet]:
        """
        Enregistre des candidates dans le registre.

        1. Match exact dimension_key → incrémente source_doc_count
        2. Nouveau → crée CANDIDATE
        3. Détection near-duplicates → ajoute à review queue, SANS merge
        4. Check promotion : ≥3 docs ET ≥2 titres distincts

        Returns:
            Liste des Facet (nouvelles ou mises à jour)
        """
        updated = []

        for candidate in candidates:
            dim_key = candidate.dimension_key
            if not dim_key:
                continue

            if dim_key in self._cache:
                # Mise à jour : incrémente source_doc_count
                facet = self._cache[dim_key]
                if candidate.source_doc_id and candidate.source_doc_id not in facet.source_doc_ids:
                    facet.source_doc_ids.append(candidate.source_doc_id)
                    facet.source_doc_count = len(facet.source_doc_ids)
                facet.last_seen_at = _now_iso()

                # Enrichir les keywords
                for kw in candidate.keywords:
                    if kw and kw not in facet.keywords:
                        facet.keywords.append(kw)

                # Check promotion
                self._check_promotion(facet)
                self._modified_keys.add(dim_key)
                updated.append(facet)
            else:
                # Nouvelle facette candidate
                family_enum = FacetFamily.THEMATIC
                try:
                    family_enum = FacetFamily(candidate.facet_family)
                except ValueError:
                    pass

                facet = Facet.create_from_candidate(
                    dimension_key=dim_key,
                    canonical_name=candidate.canonical_name,
                    facet_family=family_enum,
                    tenant_id=self.tenant_id,
                    keywords=candidate.keywords,
                    source_doc_id=candidate.source_doc_id,
                )
                self._cache[dim_key] = facet
                self._modified_keys.add(dim_key)
                updated.append(facet)

                # Détection near-duplicates
                self._detect_near_duplicates(dim_key, candidate.keywords)

        return updated

    def _check_promotion(self, facet: Facet) -> None:
        """Vérifie si une facette candidate peut être promue."""
        if facet.lifecycle != FacetLifecycle.CANDIDATE:
            return

        if facet.source_doc_count < self.PROMOTION_THRESHOLD:
            return

        # Vérifier diversité : au moins 2 doc_ids distincts
        # (les doc_ids sont déjà distincts dans source_doc_ids)
        distinct_docs = len(facet.source_doc_ids)
        if distinct_docs < self.DIVERSITY_MIN_FAMILIES:
            return

        # Promotion
        facet.lifecycle = FacetLifecycle.VALIDATED
        facet.promoted_at = _now_iso()
        facet.promotion_reason = (
            f"{facet.source_doc_count} docs ({distinct_docs} sources distinctes)"
        )

        logger.info(
            f"[OSMOSE:FacetRegistry] PROMOTED '{facet.domain}' → VALIDATED "
            f"({facet.promotion_reason})"
        )

    def _detect_near_duplicates(
        self,
        new_key: str,
        new_keywords: List[str],
    ) -> None:
        """Détecte les quasi-doublons sans merger (INV-9)."""
        for existing_key, existing_facet in self._cache.items():
            if existing_key == new_key:
                continue

            # Levenshtein sur dimension_key
            lev_dist = _levenshtein_distance(new_key, existing_key)
            if lev_dist <= self.NEAR_DUP_LEVENSHTEIN_MAX:
                score = 1.0 - (lev_dist / max(len(new_key), len(existing_key), 1))
                self._near_duplicates.append((new_key, existing_key, score))
                logger.info(
                    f"[OSMOSE:FacetRegistry] Near-duplicate détecté: "
                    f"'{new_key}' ≈ '{existing_key}' (lev={lev_dist}, score={score:.2f})"
                )
                continue

            # Keywords overlap
            kw_overlap = _keywords_overlap(new_keywords, existing_facet.keywords)
            if kw_overlap >= self.NEAR_DUP_KEYWORDS_OVERLAP_MIN:
                self._near_duplicates.append((new_key, existing_key, kw_overlap))
                logger.info(
                    f"[OSMOSE:FacetRegistry] Near-duplicate détecté (keywords): "
                    f"'{new_key}' ≈ '{existing_key}' (overlap={kw_overlap:.2f})"
                )

    def get_validated_facets(self) -> List[Facet]:
        """Retourne uniquement les facettes VALIDATED."""
        return [
            f for f in self._cache.values()
            if f.lifecycle == FacetLifecycle.VALIDATED
        ]

    def get_all_facets(self) -> List[Facet]:
        """Retourne toutes les facettes (debug/admin)."""
        return list(self._cache.values())

    def get_near_duplicate_queue(self) -> List[Tuple[str, str, float]]:
        """Retourne les paires quasi-doublons à revoir manuellement."""
        return list(self._near_duplicates)

    def get_facet_by_key(self, dimension_key: str) -> Optional[Facet]:
        """Retourne une facette par sa dimension_key."""
        return self._cache.get(dimension_key)

    def persist_to_neo4j(self, neo4j_driver=None) -> int:
        """
        MERGE les facettes modifiées dans Neo4j.

        Returns:
            Nombre de facettes persistées
        """
        if not neo4j_driver or not self._modified_keys:
            return 0

        persisted = 0
        try:
            with neo4j_driver.session() as session:
                batch = []
                for dim_key in self._modified_keys:
                    facet = self._cache.get(dim_key)
                    if not facet:
                        continue
                    props = facet.to_neo4j_properties()
                    # Filtrer les valeurs None
                    props = {k: v for k, v in props.items() if v is not None}
                    batch.append(props)

                if batch:
                    session.run("""
                        UNWIND $batch AS item
                        MERGE (f:Facet {facet_id: item.facet_id, tenant_id: item.tenant_id})
                        SET f += item
                    """, batch=batch)
                    persisted = len(batch)

                # Persister les relations DISCOVERED_IN
                doc_links = []
                for dim_key in self._modified_keys:
                    facet = self._cache.get(dim_key)
                    if not facet:
                        continue
                    for doc_id in facet.source_doc_ids:
                        doc_links.append({
                            "facet_id": facet.facet_id,
                            "doc_id": doc_id,
                        })

                if doc_links:
                    session.run("""
                        UNWIND $links AS item
                        MATCH (f:Facet {facet_id: item.facet_id})
                        MATCH (d:Document {doc_id: item.doc_id})
                        MERGE (f)-[:DISCOVERED_IN]->(d)
                    """, links=doc_links)

            logger.info(
                f"[OSMOSE:FacetRegistry] Persisted {persisted} facets to Neo4j"
            )
        except Exception as e:
            logger.error(f"[OSMOSE:FacetRegistry] Failed to persist: {e}")

        self._modified_keys.clear()
        return persisted

    def get_stats(self) -> dict:
        """Statistiques du registre."""
        by_lifecycle = {"candidate": 0, "validated": 0, "deprecated": 0}
        by_family = {"thematic": 0, "normative": 0, "operational": 0}
        for f in self._cache.values():
            by_lifecycle[f.lifecycle.value] = by_lifecycle.get(f.lifecycle.value, 0) + 1
            by_family[f.facet_family.value] = by_family.get(f.facet_family.value, 0) + 1

        return {
            "total": len(self._cache),
            "by_lifecycle": by_lifecycle,
            "by_family": by_family,
            "near_duplicates": len(self._near_duplicates),
            "modified_pending": len(self._modified_keys),
        }


__all__ = [
    "FacetRegistry",
]
