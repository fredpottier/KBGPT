"""
OSMOSE Pipeline V2 - Pass 3 Entity Resolver
============================================
Ref: doc/ongoing/ARCH_STRATIFIED_PIPELINE_V2.md

Résolution d'entités cross-documents:
- Clustering de concepts similaires
- Création de CanonicalConcept (SAME_AS)
- Alignement de thèmes (ALIGNED_TO)

Pass 3 consolide le graphe sémantique au niveau corpus.
"""

import logging
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set, Tuple
import uuid

from knowbase.stratified.models import (
    Concept,
    Theme,
    CanonicalConcept,
    CanonicalTheme,
)

logger = logging.getLogger(__name__)


# ============================================================================
# DATA CLASSES
# ============================================================================

@dataclass
class ConceptCluster:
    """Cluster de concepts similaires."""
    cluster_id: str
    concept_ids: List[str] = field(default_factory=list)
    representative_name: str = ""
    similarity_scores: Dict[str, float] = field(default_factory=dict)


@dataclass
class ThemeCluster:
    """Cluster de thèmes alignés."""
    cluster_id: str
    theme_ids: List[str] = field(default_factory=list)
    representative_name: str = ""


@dataclass
class Pass3Stats:
    """Statistiques Pass 3."""
    concepts_processed: int = 0
    themes_processed: int = 0
    concept_clusters: int = 0
    theme_clusters: int = 0
    canonical_concepts_created: int = 0
    canonical_themes_created: int = 0


@dataclass
class Pass3Result:
    """Résultat Pass 3."""
    canonical_concepts: List[CanonicalConcept] = field(default_factory=list)
    canonical_themes: List[CanonicalTheme] = field(default_factory=list)
    concept_clusters: List[ConceptCluster] = field(default_factory=list)
    theme_clusters: List[ThemeCluster] = field(default_factory=list)
    stats: Pass3Stats = field(default_factory=Pass3Stats)


# ============================================================================
# ENTITY RESOLVER
# ============================================================================

class EntityResolverV2:
    """
    Résolveur d'entités cross-documents pour Pipeline V2.

    Fusionne les concepts identiques provenant de différents documents
    en créant des CanonicalConcept.
    """

    # Seuil de similarité pour clustering
    SIMILARITY_THRESHOLD = 0.85

    def __init__(
        self,
        llm_client=None,
        embedding_client=None,
        allow_fallback: bool = False
    ):
        """
        Args:
            llm_client: Client LLM pour validation des ambigus
            embedding_client: Client pour embeddings (similarité sémantique)
            allow_fallback: Autorise fallback heuristique
        """
        self.llm_client = llm_client
        self.embedding_client = embedding_client
        self.allow_fallback = allow_fallback

    def resolve(
        self,
        concepts: List[Concept],
        themes: List[Theme]
    ) -> Pass3Result:
        """
        Résout les entités et crée les canoniques.

        Args:
            concepts: Tous les concepts du corpus
            themes: Tous les thèmes du corpus

        Returns:
            Pass3Result avec les entités canoniques
        """
        logger.info(
            f"[OSMOSE:Pass3] Résolution: {len(concepts)} concepts, {len(themes)} thèmes"
        )

        # 1. Clustering des concepts
        concept_clusters = self._cluster_concepts(concepts)
        logger.info(f"[OSMOSE:Pass3] {len(concept_clusters)} clusters de concepts")

        # 2. Création des CanonicalConcept
        canonical_concepts = self._create_canonical_concepts(concept_clusters, concepts)

        # 3. Clustering des thèmes
        theme_clusters = self._cluster_themes(themes)
        logger.info(f"[OSMOSE:Pass3] {len(theme_clusters)} clusters de thèmes")

        # 4. Création des CanonicalTheme
        canonical_themes = self._create_canonical_themes(theme_clusters, themes)

        # Stats
        stats = Pass3Stats(
            concepts_processed=len(concepts),
            themes_processed=len(themes),
            concept_clusters=len(concept_clusters),
            theme_clusters=len(theme_clusters),
            canonical_concepts_created=len(canonical_concepts),
            canonical_themes_created=len(canonical_themes)
        )

        logger.info(
            f"[OSMOSE:Pass3] TERMINÉ: {stats.canonical_concepts_created} canonical concepts, "
            f"{stats.canonical_themes_created} canonical themes"
        )

        return Pass3Result(
            canonical_concepts=canonical_concepts,
            canonical_themes=canonical_themes,
            concept_clusters=concept_clusters,
            theme_clusters=theme_clusters,
            stats=stats
        )

    def _cluster_concepts(self, concepts: List[Concept]) -> List[ConceptCluster]:
        """
        Regroupe les concepts similaires.

        Stratégies:
        1. Matching exact lex_key
        2. Matching variantes
        3. Similarité embeddings (si disponible)
        """
        clusters: List[ConceptCluster] = []
        assigned: Set[str] = set()

        # Index par lex_key
        by_lex_key: Dict[str, List[Concept]] = {}
        for concept in concepts:
            if concept.lex_key:
                if concept.lex_key not in by_lex_key:
                    by_lex_key[concept.lex_key] = []
                by_lex_key[concept.lex_key].append(concept)

        # Créer clusters par lex_key exact
        for lex_key, group in by_lex_key.items():
            if len(group) >= 1:
                cluster = ConceptCluster(
                    cluster_id=f"cluster_{uuid.uuid4().hex[:8]}",
                    concept_ids=[c.concept_id for c in group],
                    representative_name=group[0].name
                )
                clusters.append(cluster)
                assigned.update(c.concept_id for c in group)

        # Concepts non assignés: essayer matching par variantes
        unassigned = [c for c in concepts if c.concept_id not in assigned]

        for concept in unassigned:
            # Chercher un cluster existant avec variante commune
            matched_cluster = None
            for cluster in clusters:
                if self._has_variant_match(concept, clusters, concepts):
                    matched_cluster = cluster
                    break

            if matched_cluster:
                matched_cluster.concept_ids.append(concept.concept_id)
                assigned.add(concept.concept_id)
            else:
                # Créer nouveau cluster singleton
                cluster = ConceptCluster(
                    cluster_id=f"cluster_{uuid.uuid4().hex[:8]}",
                    concept_ids=[concept.concept_id],
                    representative_name=concept.name
                )
                clusters.append(cluster)
                assigned.add(concept.concept_id)

        return clusters

    def _has_variant_match(
        self,
        concept: Concept,
        clusters: List[ConceptCluster],
        all_concepts: List[Concept]
    ) -> bool:
        """Vérifie si un concept matche par variante avec un cluster existant."""
        concept_map = {c.concept_id: c for c in all_concepts}

        for cluster in clusters:
            for cid in cluster.concept_ids:
                other = concept_map.get(cid)
                if not other:
                    continue

                # Vérifier les variantes
                concept_names = {concept.name.lower()} | {v.lower() for v in concept.variants}
                other_names = {other.name.lower()} | {v.lower() for v in other.variants}

                if concept_names & other_names:  # Intersection non vide
                    return True

        return False

    def _create_canonical_concepts(
        self,
        clusters: List[ConceptCluster],
        concepts: List[Concept]
    ) -> List[CanonicalConcept]:
        """Crée les CanonicalConcept à partir des clusters."""
        canonical = []

        for cluster in clusters:
            if len(cluster.concept_ids) > 1:  # Seulement si fusion
                cc = CanonicalConcept(
                    canonical_id=f"canonical_{cluster.cluster_id}",
                    name=cluster.representative_name,
                    merged_from=cluster.concept_ids
                )
                canonical.append(cc)

        return canonical

    def _cluster_themes(self, themes: List[Theme]) -> List[ThemeCluster]:
        """Regroupe les thèmes similaires par nom."""
        clusters: List[ThemeCluster] = []
        assigned: Set[str] = set()

        # Index par nom normalisé
        by_name: Dict[str, List[Theme]] = {}
        for theme in themes:
            norm_name = theme.name.lower().strip()
            if norm_name not in by_name:
                by_name[norm_name] = []
            by_name[norm_name].append(theme)

        for name, group in by_name.items():
            cluster = ThemeCluster(
                cluster_id=f"theme_cluster_{uuid.uuid4().hex[:8]}",
                theme_ids=[t.theme_id for t in group],
                representative_name=group[0].name
            )
            clusters.append(cluster)

        return clusters

    def _create_canonical_themes(
        self,
        clusters: List[ThemeCluster],
        themes: List[Theme]
    ) -> List[CanonicalTheme]:
        """Crée les CanonicalTheme à partir des clusters."""
        canonical = []

        for cluster in clusters:
            if len(cluster.theme_ids) > 1:  # Seulement si fusion
                ct = CanonicalTheme(
                    canonical_id=f"canonical_{cluster.cluster_id}",
                    name=cluster.representative_name,
                    aligned_from=cluster.theme_ids
                )
                canonical.append(ct)

        return canonical

    def resolve_incremental(
        self,
        new_concepts: List[Concept],
        existing_canonical: List[CanonicalConcept]
    ) -> Tuple[List[CanonicalConcept], Dict[str, str]]:
        """
        Résolution incrémentale pour un nouveau document.

        Args:
            new_concepts: Concepts du nouveau document
            existing_canonical: CanonicalConcept existants

        Returns:
            (updated_canonical, mapping new_concept_id → canonical_id)
        """
        mapping: Dict[str, str] = {}

        # Index des canoniques par nom/variantes
        canonical_index: Dict[str, CanonicalConcept] = {}
        for cc in existing_canonical:
            canonical_index[cc.name.lower()] = cc

        updated = list(existing_canonical)

        for concept in new_concepts:
            matched = None

            # Chercher match par nom
            if concept.name.lower() in canonical_index:
                matched = canonical_index[concept.name.lower()]

            # Chercher match par variantes
            if not matched:
                for variant in concept.variants:
                    if variant.lower() in canonical_index:
                        matched = canonical_index[variant.lower()]
                        break

            if matched:
                # Fusionner avec existant
                if concept.concept_id not in matched.merged_from:
                    matched.merged_from.append(concept.concept_id)
                mapping[concept.concept_id] = matched.canonical_id
            else:
                # Nouveau canonical (singleton pour l'instant)
                # Pas de création si singleton - attendre le prochain batch
                pass

        return updated, mapping
