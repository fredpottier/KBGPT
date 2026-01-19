"""
Hybrid Anchor Model - Anchor-Based Scorer (Phase 3)

Remplace EmbeddingsContextualScorer par un scoring simplifié basé sur:
1. TF-IDF sur label/définition
2. Fréquence anchors (nombre d'occurrences)
3. Centralité basique (si graphe existant)

Objectif: Réduire GATE_CHECK de 10 min à ~2 min
(suppression des 2,297 contexts × embeddings)

ADR: doc/ongoing/ADR_HYBRID_ANCHOR_MODEL.md

Author: OSMOSE Phase 2
Date: 2024-12
"""

import logging
import math
from typing import List, Dict, Any, Optional
from collections import Counter
import re

from knowbase.api.schemas.concepts import (
    ProtoConcept,
    CanonicalConcept,
    ConceptStability,
    HighSignalCheck,
)
from knowbase.semantic.anchor_resolver import check_high_signal
from knowbase.config.feature_flags import get_hybrid_anchor_config

logger = logging.getLogger(__name__)


class AnchorBasedScorer:
    """
    Scorer simplifié pour le Hybrid Anchor Model.

    Remplace EmbeddingsContextualScorer (Phase 1.5) par un scoring
    basé sur les anchors, sans calcul d'embeddings contextuels.

    Critères de scoring:
    1. TF-IDF du label dans le corpus
    2. Fréquence d'anchors (robustesse)
    3. Rôles des anchors (high-signal boost)
    4. Centralité graphe (si disponible)
    """

    def __init__(
        self,
        tenant_id: str = "default"
    ):
        """
        Initialise le scorer.

        Args:
            tenant_id: ID tenant pour configuration
        """
        self.tenant_id = tenant_id
        self.promotion_config = get_hybrid_anchor_config(
            "promotion_config", tenant_id
        ) or {}

        # Seuils de promotion
        self.min_proto_for_stable = self.promotion_config.get(
            "min_proto_concepts_for_stable", 2
        )
        self.min_sections_for_stable = self.promotion_config.get(
            "min_anchor_sections_for_stable", 2
        )
        self.allow_singleton_high_signal = self.promotion_config.get(
            "allow_singleton_if_high_signal", True
        )

        logger.info(
            f"[OSMOSE:AnchorBasedScorer] Initialized "
            f"(min_proto={self.min_proto_for_stable}, "
            f"min_sections={self.min_sections_for_stable})"
        )

    def score_proto_concepts(
        self,
        proto_concepts: List[ProtoConcept],
        corpus_labels: Optional[List[str]] = None
    ) -> List[Dict[str, Any]]:
        """
        Score une liste de ProtoConcepts pour promotion.

        Args:
            proto_concepts: ProtoConcepts à scorer
            corpus_labels: Tous les labels du corpus (pour TF-IDF)

        Returns:
            Liste de dicts avec scores et recommandation de promotion
        """
        if not proto_concepts:
            return []

        # Construire corpus pour TF-IDF si non fourni
        if corpus_labels is None:
            corpus_labels = [pc.concept_name for pc in proto_concepts]

        # Calculer IDF pour chaque label
        idf_scores = self._compute_idf(corpus_labels)

        results = []
        for pc in proto_concepts:
            score_details = self._score_single_proto(pc, idf_scores, corpus_labels)
            results.append(score_details)

        logger.info(
            f"[OSMOSE:AnchorBasedScorer] Scored {len(proto_concepts)} proto-concepts"
        )

        return results

    def _score_single_proto(
        self,
        proto: ProtoConcept,
        idf_scores: Dict[str, float],
        corpus_labels: List[str]
    ) -> Dict[str, Any]:
        """
        Score un seul ProtoConcept.

        Args:
            proto: ProtoConcept à scorer
            idf_scores: Scores IDF pré-calculés
            corpus_labels: Labels du corpus

        Returns:
            Dict avec scores détaillés
        """
        # 1. Score TF-IDF
        tf = corpus_labels.count(proto.concept_name) / len(corpus_labels) if corpus_labels else 0
        idf = idf_scores.get(proto.concept_name, 1.0)
        tfidf_score = tf * idf

        # 2. Score fréquence anchors
        anchor_count = len(proto.anchors)
        anchor_score = min(1.0, anchor_count / 3.0)  # Normalize: 3 anchors = 1.0

        # 3. Score rôles (high-signal boost)
        role_score = 0.0
        high_signal_reasons = []

        for anchor in proto.anchors:
            hs_check = check_high_signal(
                quote=anchor.surface_form,
                anchor_role=anchor.role.value if hasattr(anchor.role, 'value') else str(anchor.role),
                section_type=None,  # TODO: ajouter si disponible
                domain=None,  # TODO: ajouter si disponible
                tenant_id=self.tenant_id
            )
            if hs_check.is_high_signal:
                role_score = max(role_score, 0.3)  # Boost
                high_signal_reasons.extend(hs_check.reasons)

        # 4. Score sections (diversité)
        unique_sections = len(set(
            a.section_id for a in proto.anchors if a.section_id
        ))
        section_score = min(1.0, unique_sections / 2.0)  # 2 sections = 1.0

        # Score combiné (pondéré)
        combined_score = (
            0.2 * tfidf_score +
            0.3 * anchor_score +
            0.2 * role_score +
            0.3 * section_score
        )

        return {
            "proto_concept_id": proto.concept_id,
            "label": proto.concept_name,
            "scores": {
                "tfidf": round(tfidf_score, 3),
                "anchor_frequency": round(anchor_score, 3),
                "role_boost": round(role_score, 3),
                "section_diversity": round(section_score, 3),
                "combined": round(combined_score, 3)
            },
            "anchor_count": anchor_count,
            "unique_sections": unique_sections,
            "high_signal_reasons": high_signal_reasons,
            "proto_concept": proto
        }

    def _compute_idf(self, corpus_labels: List[str]) -> Dict[str, float]:
        """
        Calcule IDF pour chaque label unique.

        Args:
            corpus_labels: Tous les labels du corpus

        Returns:
            Dict label → IDF score
        """
        if not corpus_labels:
            return {}

        # Document frequency
        label_counts = Counter(corpus_labels)
        n_docs = len(corpus_labels)

        idf_scores = {}
        for label, count in label_counts.items():
            # IDF = log(N / df) + 1
            idf_scores[label] = math.log(n_docs / count) + 1

        return idf_scores

    def determine_promotion(
        self,
        scored_protos: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """
        Détermine quels ProtoConcepts promouvoir en CanonicalConcept.

        Applique la règle des 3 statuts:
        1. ≥2 ProtoConcepts OU ≥2 sections → "stable"
        2. 1 seul mais high-signal → "singleton"
        3. Sinon → pas de promotion (reste ProtoConcept)

        Args:
            scored_protos: ProtoConcepts scorés

        Returns:
            Liste avec décision de promotion pour chaque proto
        """
        # Grouper par label (case-insensitive) pour déduplication
        label_groups = {}
        for scored in scored_protos:
            label_key = scored["label"].lower().strip()
            if label_key not in label_groups:
                label_groups[label_key] = []
            label_groups[label_key].append(scored)

        results = []
        for label_key, group in label_groups.items():
            # Compter occurrences et sections
            proto_count = len(group)
            all_sections = set()
            is_high_signal = False
            high_signal_reasons = []

            for scored in group:
                all_sections.update(
                    a.section_id for a in scored["proto_concept"].anchors
                    if a.section_id
                )
                if scored["high_signal_reasons"]:
                    is_high_signal = True
                    high_signal_reasons.extend(scored["high_signal_reasons"])

            section_count = len(all_sections)

            # Appliquer règles de promotion
            if proto_count >= self.min_proto_for_stable:
                stability = ConceptStability.STABLE
                promote = True
                reason = f"≥{self.min_proto_for_stable} proto-concepts"
            elif section_count >= self.min_sections_for_stable:
                stability = ConceptStability.STABLE
                promote = True
                reason = f"≥{self.min_sections_for_stable} sections"
            elif proto_count == 1 and is_high_signal and self.allow_singleton_high_signal:
                stability = ConceptStability.SINGLETON
                promote = True
                reason = f"singleton high-signal: {high_signal_reasons[:2]}"
            else:
                stability = None
                promote = False
                reason = "insufficient occurrences/sections, not high-signal"

            # Sélectionner le meilleur proto du groupe
            best_proto = max(group, key=lambda x: x["scores"]["combined"])

            results.append({
                "label": best_proto["label"],
                "promote": promote,
                "stability": stability.value if stability else None,
                "reason": reason,
                "proto_count": proto_count,
                "section_count": section_count,
                "is_high_signal": is_high_signal,
                "needs_confirmation": stability == ConceptStability.SINGLETON,
                "best_proto_id": best_proto["proto_concept_id"],
                "combined_score": best_proto["scores"]["combined"],
                "all_proto_ids": [s["proto_concept_id"] for s in group]
            })

            if promote:
                logger.debug(
                    f"[OSMOSE:Promotion] '{best_proto['label']}' → {stability.value} ({reason})"
                )

        # Stats
        promoted = [r for r in results if r["promote"]]
        stable_count = len([r for r in promoted if r["stability"] == "stable"])
        singleton_count = len([r for r in promoted if r["stability"] == "singleton"])

        logger.info(
            f"[OSMOSE:AnchorBasedScorer] Promotion decisions: "
            f"{len(promoted)}/{len(results)} promoted "
            f"(stable={stable_count}, singleton={singleton_count})"
        )

        return results


def create_canonical_from_protos(
    proto_concepts: List[ProtoConcept],
    stability: ConceptStability,
    canonical_id: Optional[str] = None
) -> CanonicalConcept:
    """
    Crée un CanonicalConcept à partir de ProtoConcepts groupés.

    Args:
        proto_concepts: ProtoConcepts à fusionner
        stability: Niveau de stabilité (stable/singleton)
        canonical_id: ID optionnel (généré si non fourni)

    Returns:
        CanonicalConcept consolidé
    """
    import uuid
    import numpy as np

    if not proto_concepts:
        raise ValueError("Cannot create canonical from empty proto list")

    # Sélectionner le meilleur label (le plus fréquent ou le premier)
    labels = [pc.concept_name for pc in proto_concepts]
    best_label = max(set(labels), key=labels.count)

    # Consolider les définitions (prendre la plus longue)
    definitions = [pc.definition for pc in proto_concepts if pc.definition]
    best_definition = max(definitions, key=len) if definitions else ""

    # Calculer embedding centroïde (Pass 1)
    embeddings = [
        np.array(pc.embedding)
        for pc in proto_concepts
        if pc.embedding is not None
    ]
    if embeddings:
        centroid_embedding = np.mean(embeddings, axis=0).tolist()
    else:
        centroid_embedding = None

    # Créer CanonicalConcept
    canonical = CanonicalConcept(
        canonical_id=canonical_id or f"cc_{uuid.uuid4().hex[:12]}",
        canonical_name=best_label,
        unified_definition=best_definition,
        type_fine=None,  # Sera enrichi en Pass 2
        stability=stability,
        needs_confirmation=(stability == ConceptStability.SINGLETON),
        embedding=centroid_embedding,
        proto_concept_ids=[pc.concept_id for pc in proto_concepts],
        tenant_id=proto_concepts[0].tenant_id
    )

    return canonical
