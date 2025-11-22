"""
🌊 OSMOSE Semantic Intelligence - Main Entities Merge Rule

Phase 1.8.1d: Règle 1 - Fusionner entités principales répétées dans le document.

Objectif:
- Identifier concepts répétés dans ≥ X% des slides (ex: "SAP S/4HANA" répété 15× sur 87 slides)
- Fusionner en CanonicalConcept unique avec aliases
- Préserver traçabilité (source_slides)

Critères:
- Occurrence ratio ≥ min_occurrence_ratio (config: 0.15 = 15%)
- Similarity ≥ similarity_threshold (config: 0.88)
- Type concept = ENTITY, PRODUCT, TECHNOLOGY

Exemple:
    Input:
    - Slide 1: "SAP S/4HANA"
    - Slide 5: "SAP S/4HANA Cloud"
    - Slide 12: "S/4HANA"
    ... (15 mentions sur 87 slides = 17% occurrence)

    Output:
    - CanonicalConcept("SAP S/4HANA", aliases=["S/4HANA", "SAP S/4HANA Cloud"])
    - metadata.source_slides = [1, 5, 12, ...]
"""

from typing import List, Dict, Optional, Set
from collections import Counter
import numpy as np
import logging

# Phase 1.8.1d: Heuristiques de canonicalization
from knowbase.semantic.fusion.canonicalization_heuristics import apply_heuristics

logger = logging.getLogger(__name__)

# Phase 1.8.1d: Ontologie adaptive
from knowbase.ontology.adaptive_ontology_manager import AdaptiveOntologyManager

from knowbase.semantic.models import Concept, CanonicalConcept
from ..fusion_rules import FusionRule
from ..models import FusionResult, ConceptCluster
from knowbase.semantic.utils.embeddings import get_embedder
from sklearn.metrics.pairwise import cosine_similarity


class MainEntitiesMergeRule(FusionRule):
    """
    Règle 1: Fusionner entités principales répétées.

    Phase 1.8.1d Sprint 1.8.1d Task T1.8.1d.4
    """

    @property
    def name(self) -> str:
        return "main_entities_merge"

    def should_apply(
        self,
        concepts: List[Concept],
        context: Optional[Dict] = None
    ) -> bool:
        """
        Vérifie si au moins un concept répété ≥ seuil adaptatif.

        Args:
            concepts: Concepts candidats
            context: Contexte (total_slides, etc.)

        Returns:
            bool: True si au moins un concept répété trouvé

        Note Phase 1.8.1d:
            Utilise seuil ADAPTATIF au lieu de pourcentage fixe:
            - Documents courts (≤20 slides): min 2 occurrences
            - Documents moyens (21-100): min 3 occurrences OU 5%
            - Documents longs (>100): min 5 occurrences OU 3%
        """
        if not concepts or not context:
            return False

        total_slides = context.get("total_slides", 1)

        # Phase 1.8.1d: Seuil adaptatif selon taille document
        if total_slides <= 20:
            min_occurrences = 2
        elif total_slides <= 100:
            min_occurrences = max(3, int(total_slides * 0.05))  # 5% ou min 3
        else:
            min_occurrences = max(5, int(total_slides * 0.03))  # 3% ou min 5

        # Compter occurrences par concept name
        concept_counts = Counter(c.name for c in concepts)

        # Vérifier si au moins un concept répété ≥ min_occurrences
        for count in concept_counts.values():
            if count >= min_occurrences:
                logger.debug(
                    f"[MainEntitiesMerge] should_apply=True: found concept with {count} occurrences "
                    f"(threshold={min_occurrences}, total_slides={total_slides})"
                )
                return True

        return False

    async def apply(
        self,
        concepts: List[Concept],
        context: Optional[Dict] = None
    ) -> FusionResult:
        """
        Applique fusion des entités principales répétées.

        Args:
            concepts: Concepts à fusionner
            context: Contexte document

        Returns:
            FusionResult: Entités fusionnées

        Process:
            1. Filtrer concepts éligibles (types, occurrence ratio)
            2. Calculer embeddings + cosine similarity
            3. Cluster concepts similaires (≥ threshold)
            4. Pour chaque cluster: créer CanonicalConcept
            5. Préserver concepts non fusionnés
        """
        total_slides = context.get("total_slides", 1) if context else 1
        min_ratio = self.config.get("min_occurrence_ratio", 0.15)
        similarity_threshold = self.config.get("similarity_threshold", 0.88)
        eligible_types_str = self.config.get("eligible_types", ["entity", "product", "technology"])

        # Normaliser types (lowercase pour comparaison)
        eligible_types = [t.lower() for t in eligible_types_str]

        self.logger.info(
            f"[OSMOSE:Fusion:MainEntities] Applying to {len(concepts)} concepts "
            f"(min_ratio={min_ratio}, threshold={similarity_threshold})"
        )

        # Étape 1: Filtrer concepts éligibles
        eligible_concepts = []
        concept_counts = Counter()

        for concept in concepts:
            # Compter occurrences (par name)
            concept_counts[concept.name] += 1

            # Filtrer par type (normaliser en lowercase)
            if concept.type.lower() in eligible_types:
                eligible_concepts.append(concept)

        # Filtrer par occurrence ratio
        repeated_concepts = []
        for concept in eligible_concepts:
            ratio = concept_counts[concept.name] / total_slides
            if ratio >= min_ratio:
                repeated_concepts.append(concept)

        if not repeated_concepts:
            self.logger.debug(
                f"[OSMOSE:Fusion:MainEntities] No repeated concepts found (min_ratio={min_ratio})"
            )
            return FusionResult(
                merged_concepts=[],
                preserved_concepts=[],
                rule_name=self.name,
                reason="No repeated concepts above threshold"
            )

        self.logger.info(
            f"[OSMOSE:Fusion:MainEntities] Found {len(repeated_concepts)} repeated concepts"
        )

        # Étape 2: Calculer embeddings
        embedder = get_embedder(None)  # Use default embedder
        concept_texts = [c.name for c in repeated_concepts]
        embeddings = embedder.encode(concept_texts)

        # Étape 3: Cluster concepts similaires (greedy clustering)
        clusters = self._cluster_similar_concepts(
            repeated_concepts,
            embeddings,
            similarity_threshold
        )

        self.logger.info(
            f"[OSMOSE:Fusion:MainEntities] Created {len(clusters)} clusters"
        )

        # Étape 4: Créer CanonicalConcepts pour chaque cluster
        merged_canonical = []
        processed_names = set()

        for cluster in clusters:
            if cluster.size < 2:
                # Cluster trop petit, préserver concept individuel
                continue

            # Créer CanonicalConcept
            canonical = self._create_canonical_from_cluster(cluster)
            merged_canonical.append(canonical)

            # Marquer concepts comme traités
            for concept in cluster.concepts:
                processed_names.add(concept.name)

        # Étape 5: Préserver concepts non fusionnés
        preserved = [c for c in concepts if c.name not in processed_names]

        result = FusionResult(
            merged_concepts=merged_canonical,
            preserved_concepts=preserved,
            rule_name=self.name,
            reason=f"Merged {len(merged_canonical)} repeated entities (ratio ≥ {min_ratio})",
            metadata={
                "total_concepts": len(concepts),
                "repeated_concepts": len(repeated_concepts),
                "clusters_created": len(clusters),
                "concepts_merged": len(processed_names)
            }
        )

        return result

    def _cluster_similar_concepts(
        self,
        concepts: List[Concept],
        embeddings: np.ndarray,
        threshold: float
    ) -> List[ConceptCluster]:
        """
        Cluster concepts par similarité (greedy clustering).

        Args:
            concepts: Concepts à clusterer
            embeddings: Embeddings des concepts
            threshold: Seuil similarité

        Returns:
            List[ConceptCluster]: Clusters créés
        """
        if len(concepts) == 0:
            return []

        # Calculer matrice similarité
        sim_matrix = cosine_similarity(embeddings)

        # Greedy clustering
        clusters = []
        used = set()

        for i, concept_i in enumerate(concepts):
            if i in used:
                continue

            # Créer nouveau cluster avec concept_i
            cluster_concepts = [concept_i]
            cluster_indices = [i]
            used.add(i)

            # Trouver concepts similaires
            for j, concept_j in enumerate(concepts):
                if j in used:
                    continue

                if sim_matrix[i][j] >= threshold:
                    cluster_concepts.append(concept_j)
                    cluster_indices.append(j)
                    used.add(j)

            # Créer ConceptCluster
            cluster = ConceptCluster(concepts=cluster_concepts)

            # Déterminer nom canonique (concept le plus fréquent)
            concept_counts = Counter(c.name for c in cluster_concepts)
            cluster.centroid_name = concept_counts.most_common(1)[0][0]

            # Source slides
            cluster.source_slides = []
            for concept in cluster_concepts:
                if concept.metadata and "source_slides" in concept.metadata:
                    cluster.source_slides.extend(concept.metadata["source_slides"])
            cluster.source_slides = list(set(cluster.source_slides))  # Dédupliquer

            # Similarity scores
            for idx in cluster_indices:
                cluster.similarity_scores[concepts[idx].name] = float(sim_matrix[i][idx])

            clusters.append(cluster)

        return clusters

    def _create_canonical_from_cluster(
        self,
        cluster: ConceptCluster
    ) -> CanonicalConcept:
        """
        Crée CanonicalConcept depuis ConceptCluster.

        Args:
            cluster: Cluster de concepts

        Returns:
            CanonicalConcept: Concept canonique créé
        """
        # Phase 1.8.1d: Canonicalization intelligente (heuristiques)
        variant_names = [c.name for c in cluster.concepts]

        # Essayer heuristiques d'abord (80% des cas)
        canonical_name = apply_heuristics(variant_names)

        if not canonical_name:
            # Fallback: concept le plus fréquent (logique originale)
            canonical_name = cluster.centroid_name
            logger.debug(
                f"[MainEntitiesMerge] Heuristics inconclusive, using most frequent: {canonical_name}"
            )

        # Aliases = autres variations
        aliases = [c.name for c in cluster.concepts if c.name != canonical_name]
        aliases = list(set(aliases))  # Dédupliquer

        # Type = type le plus fréquent
        type_counts = Counter(c.concept_type for c in cluster.concepts)
        canonical_type = type_counts.most_common(1)[0][0]

        # Définition = définition du concept canonique (si existe)
        definition = ""
        for concept in cluster.concepts:
            if concept.name == canonical_name and hasattr(concept, "definition"):
                definition = concept.definition
                break

        # Confiance = moyenne des confidences
        confidences = [c.confidence for c in cluster.concepts]
        avg_confidence = sum(confidences) / len(confidences) if confidences else 0.8

        # Langue = langue majoritaire
        language_counts = Counter(c.language for c in cluster.concepts)
        canonical_language = language_counts.most_common(1)[0][0]

        # Metadata
        metadata = {
            "source_slides": cluster.source_slides,
            "occurrences": len(cluster.concepts),
            "avg_similarity": cluster.avg_similarity,
            "fusion_rule": self.name
        }

        canonical = CanonicalConcept(
            name=canonical_name,
            aliases=aliases,
            concept_type=canonical_type,
            definition=definition,
            confidence=avg_confidence,
            language=canonical_language,
            metadata=metadata
        )

        return canonical
