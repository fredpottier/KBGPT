"""
🌊 OSMOSE Semantic Intelligence - SmartConceptMerger

Phase 1.8.1d: Orchestrateur de fusion contextuelle basée sur règles.

Architecture:
- Flatten concepts locaux (par slide) avec metadata
- Application séquentielle des règles (par priorité)
- Fallback pour concepts non traités

Usage:
    merger = SmartConceptMerger(rules=[rule1, rule2], config=fusion_config)
    canonical_concepts = await merger.merge(local_concepts, document_context)
"""

from typing import List, Dict, Optional, Any
import logging
import time

from knowbase.semantic.models import Concept
from .fusion_rules import FusionRule
from .models import FusionResult, FusionConfig


logger = logging.getLogger(__name__)


class SmartConceptMerger:
    """
    Orchestrateur de fusion contextuelle basée sur règles.

    Phase 1.8.1d: Résout le problème de segmentation pour documents structurés (PPTX).
    Au lieu de fusionner via TopicSegmenter (perte de granularité), on:
    1. Extrait localement (par slide) avec granularité fine
    2. Fusionne intelligemment via règles contextuelles

    Architecture:
    - Flatten concepts locaux (preserve metadata source)
    - Application règles par priorité (ordre configuré)
    - Fallback pour concepts non traités
    """

    def __init__(
        self,
        rules: List[FusionRule],
        config: FusionConfig
    ):
        """
        Initialise SmartConceptMerger.

        Args:
            rules: Liste des règles de fusion (ordre = priorité)
            config: Configuration fusion
        """
        self.rules = sorted(rules, key=lambda r: r.priority)  # Trier par priorité
        self.config = config
        self.logger = logging.getLogger(__name__)

        # Stats
        self.stats = {
            "total_applications": 0,
            "rules_applied": {},
            "total_concepts_merged": 0,
            "total_concepts_preserved": 0,
        }

        self.logger.info(
            f"[OSMOSE:Fusion] SmartConceptMerger initialized with {len(self.rules)} rules"
        )

    async def merge(
        self,
        local_concepts: List[List[Concept]],
        document_context: Optional[str] = None,
        context_metadata: Optional[Dict[str, Any]] = None
    ) -> List[Any]:  # List[CanonicalConcept]
        """
        Fusion intelligente des concepts locaux.

        Args:
            local_concepts: Liste de listes de concepts (1 liste par slide)
            document_context: Contexte global du document (optionnel)
            context_metadata: Metadata contexte (total_slides, document_type, etc.)

        Returns:
            List[CanonicalConcept]: Concepts fusionnés + préservés

        Process:
            1. Flatten concepts locaux (avec metadata source)
            2. Pour chaque règle (ordre priorité):
               - Identifier groupes éligibles
               - Appliquer règle
               - Marquer concepts traités
            3. Fallback: Concepts non fusionnés → CanonicalConcepts individuels
        """
        start_time = time.time()

        if not self.config.enabled:
            self.logger.warning("[OSMOSE:Fusion] Fusion disabled, returning concepts as-is")
            return self._flatten_to_canonical(local_concepts)

        self.logger.info(
            f"[OSMOSE:Fusion] Starting merge of {len(local_concepts)} local concept groups"
        )

        # Étape 1: Flatten concepts locaux
        flat_concepts = self._flatten_concepts(local_concepts)
        self.logger.info(
            f"[OSMOSE:Fusion] Flattened {len(flat_concepts)} total concepts "
            f"from {len(local_concepts)} groups"
        )

        # Contexte pour règles
        context = context_metadata or {}
        if "total_slides" not in context and local_concepts:
            context["total_slides"] = len(local_concepts)

        # Étape 2: Application règles par priorité
        remaining_concepts = flat_concepts.copy()
        all_canonical = []
        all_relationships = []

        for rule in self.rules:
            if not rule.enabled:
                self.logger.debug(f"[OSMOSE:Fusion] Rule {rule.name} disabled, skipping")
                continue

            # Vérifier si règle applicable
            if not rule.should_apply(remaining_concepts, context):
                self.logger.debug(
                    f"[OSMOSE:Fusion] Rule {rule.name} not applicable, skipping"
                )
                continue

            # Appliquer règle
            rule_start = time.time()
            try:
                result = await rule.apply(remaining_concepts, context)

                # Stats
                self.stats["total_applications"] += 1
                self.stats["rules_applied"][rule.name] = self.stats["rules_applied"].get(rule.name, 0) + 1
                self.stats["total_concepts_merged"] += len(result.merged_concepts)
                self.stats["total_concepts_preserved"] += len(result.preserved_concepts)

                # Log
                duration_ms = (time.time() - rule_start) * 1000
                rule._log_application(remaining_concepts, result, duration_ms)

                # Collecter résultats
                all_canonical.extend(result.merged_concepts)
                all_relationships.extend(result.relationships)

                # Retirer concepts traités de la liste remaining
                # (concepts fusionnés ou préservés par cette règle)
                processed_concept_names = set()
                for c in result.merged_concepts:
                    if hasattr(c, "aliases"):
                        processed_concept_names.update(c.aliases)
                    processed_concept_names.add(c.name if hasattr(c, "name") else str(c))

                for c in result.preserved_concepts:
                    processed_concept_names.add(c.name)

                remaining_concepts = [
                    c for c in remaining_concepts
                    if c.name not in processed_concept_names
                ]

                self.logger.debug(
                    f"[OSMOSE:Fusion] {len(remaining_concepts)} concepts remaining after {rule.name}"
                )

            except Exception as e:
                self.logger.error(
                    f"[OSMOSE:Fusion] Error applying rule {rule.name}: {e}",
                    exc_info=True
                )
                # Continue avec règles suivantes

        # Étape 3: Fallback pour concepts non traités
        if remaining_concepts:
            self.logger.info(
                f"[OSMOSE:Fusion] Fallback: {len(remaining_concepts)} concepts not processed by rules"
            )

            if self.config.fallback_strategy == "preserve_all":
                # Stratégie par défaut: préserver tous concepts non traités
                fallback_canonical = self._concepts_to_canonical(remaining_concepts)
                all_canonical.extend(fallback_canonical)
                self.logger.info(
                    f"[OSMOSE:Fusion] Preserved {len(fallback_canonical)} concepts (fallback)"
                )
            else:
                # TODO: Implémenter "merge_similar" fallback (clustering simple)
                self.logger.warning(
                    f"[OSMOSE:Fusion] Fallback strategy '{self.config.fallback_strategy}' not implemented, "
                    "using preserve_all"
                )
                fallback_canonical = self._concepts_to_canonical(remaining_concepts)
                all_canonical.extend(fallback_canonical)

        # Stats finales
        duration_s = time.time() - start_time
        self.logger.info(
            f"[OSMOSE:Fusion] ✅ Merge complete: {len(flat_concepts)} concepts → "
            f"{len(all_canonical)} canonical ({duration_s:.2f}s)"
        )
        self.logger.info(
            f"[OSMOSE:Fusion] Stats: {self.stats['total_applications']} rule applications, "
            f"{self.stats['total_concepts_merged']} merged, "
            f"{self.stats['total_concepts_preserved']} preserved"
        )

        # 📊 Grafana Metric: Fusion Rate
        if len(flat_concepts) > 0:
            merged_count = self.stats['total_concepts_merged']
            fusion_rate = (merged_count / len(flat_concepts)) * 100
            self.logger.info(f"[OSMOSE:Fusion] fusion_rate={fusion_rate:.1f}%")

        # 📊 Grafana Metric: Concepts by Type Distribution
        # Log chaque concept individuellement pour permettre count_over_time de Loki
        for concept in all_canonical:
            if hasattr(concept, 'concept_type') and concept.concept_type:
                self.logger.debug(f"[OSMOSE:Concept] type={concept.concept_type}")

        return all_canonical

    def _flatten_concepts(self, local_concepts: List[List[Concept]]) -> List[Concept]:
        """
        Aplatit liste de listes de concepts en liste unique.

        Args:
            local_concepts: Liste de listes (1 liste par slide)

        Returns:
            List[Concept]: Concepts aplatis avec metadata source préservée
        """
        flat = []
        for i, concept_group in enumerate(local_concepts):
            for concept in concept_group:
                # Préserver index slide si pas déjà présent
                if not concept.metadata:
                    concept.metadata = {}
                if "slide_index" not in concept.metadata:
                    concept.metadata["slide_index"] = i

                # Ajouter à liste de slides sources (pour fusion)
                if "source_slides" not in concept.metadata:
                    concept.metadata["source_slides"] = [i]
                elif i not in concept.metadata["source_slides"]:
                    concept.metadata["source_slides"].append(i)

                flat.append(concept)

        return flat

    def _flatten_to_canonical(self, local_concepts: List[List[Concept]]) -> List[Any]:
        """
        Convertit concepts locaux en CanonicalConcepts sans fusion (fallback).

        Args:
            local_concepts: Liste de listes de concepts

        Returns:
            List[CanonicalConcept]: Concepts individuels
        """
        flat = self._flatten_concepts(local_concepts)
        return self._concepts_to_canonical(flat)

    def _concepts_to_canonical(self, concepts: List[Concept]) -> List[Any]:
        """
        Convertit liste Concepts en liste CanonicalConcepts individuels.

        Args:
            concepts: Concepts à convertir

        Returns:
            List[CanonicalConcept]: Concepts canoniques créés

        Note:
            Utilise import dynamique pour éviter dépendance circulaire
        """
        from knowbase.semantic.models import CanonicalConcept

        canonical_list = []
        for concept in concepts:
            canonical = CanonicalConcept(
                canonical_name=concept.name,
                aliases=[],
                languages=[concept.language],
                type=concept.type,
                definition=concept.definition if hasattr(concept, "definition") else "",
                source_concepts=[concept],
                support=1,
                confidence=concept.confidence
            )
            canonical_list.append(canonical)

        return canonical_list

    def get_stats(self) -> Dict[str, Any]:
        """
        Retourne statistiques d'application des règles.

        Returns:
            Dict: Statistiques
        """
        return self.stats.copy()

    def reset_stats(self):
        """Reset statistiques."""
        self.stats = {
            "total_applications": 0,
            "rules_applied": {},
            "total_concepts_merged": 0,
            "total_concepts_preserved": 0,
        }
