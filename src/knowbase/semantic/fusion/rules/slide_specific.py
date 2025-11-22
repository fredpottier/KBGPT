"""
🌊 OSMOSE Semantic Intelligence - Slide Specific Preserve Rule

Phase 1.8.1d: Règle 3 - Préserver détails techniques slide-specific (mentions uniques).

Objectif:
- Identifier concepts mentionnés UNE SEULE FOIS (détails slide-specific)
- Préserver sans fusion (traçabilité slide précis)
- Catégoriser comme "rare" dans metadata

Critères:
- Occurrence ≤ max_occurrence (config: 2)
- Type concept = METRIC, DETAIL, TECHNICAL, VALUE
- Longueur nom > min_name_length (config: 10 chars) → détails précis

Exemple:
    Input:
    - Concept: "Response Time < 200ms (P95)" (slide 42 uniquement)
    - Concept: "Database Connection Pool Size: 50" (slide 67 uniquement)

    Output:
    - CanonicalConcept("Response Time < 200ms (P95)")
      - metadata.source_slides = [42]
      - metadata.frequency = "rare"
    - CanonicalConcept("Database Connection Pool Size: 50")
      - metadata.source_slides = [67]
      - metadata.frequency = "rare"
"""

from typing import List, Dict, Optional
from collections import Counter

from knowbase.semantic.models import Concept, CanonicalConcept
from ..fusion_rules import FusionRule
from ..models import FusionResult


class SlideSpecificPreserveRule(FusionRule):
    """
    Règle 3: Préserver détails slide-specific (mentions rares).

    Phase 1.8.1d Sprint 1.8.1d Task T1.8.1d.4
    """

    @property
    def name(self) -> str:
        return "slide_specific_preserve"

    def should_apply(
        self,
        concepts: List[Concept],
        context: Optional[Dict] = None
    ) -> bool:
        """
        Toujours appliquer (règle de préservation par défaut).

        Args:
            concepts: Concepts candidats
            context: Contexte (optionnel)

        Returns:
            bool: True (toujours applicable)
        """
        return len(concepts) > 0

    async def apply(
        self,
        concepts: List[Concept],
        context: Optional[Dict] = None
    ) -> FusionResult:
        """
        Applique préservation des détails slide-specific.

        Args:
            concepts: Concepts à analyser
            context: Contexte document

        Returns:
            FusionResult: Concepts préservés individuellement

        Process:
            1. Filtrer concepts rares (≤ max_occurrence)
            2. Filtrer par type (METRIC, DETAIL, TECHNICAL, VALUE)
            3. Filtrer par longueur nom (détails précis)
            4. Créer CanonicalConcept individuel pour chacun
            5. Préserver metadata source_slides (traçabilité)
        """
        max_occurrence = self.config.get("max_occurrence", 2)
        preserve_types_str = self.config.get("preserve_types", [
            "metric", "detail", "technical", "value"
        ])
        min_name_length = self.config.get("min_name_length", 10)

        # Normaliser types (lowercase pour comparaison)
        preserve_types = [t.lower() for t in preserve_types_str]

        self.logger.info(
            f"[OSMOSE:Fusion:SlideSpecific] Applying to {len(concepts)} concepts "
            f"(max_occurrence={max_occurrence}, min_name_length={min_name_length})"
        )

        # Étape 1: Compter occurrences par concept name
        concept_counts = Counter(c.name for c in concepts)

        # Étape 2: Filtrer concepts rares
        rare_concepts = []
        for concept in concepts:
            occurrence = concept_counts[concept.name]

            # Vérifier occurrence
            if occurrence > max_occurrence:
                continue

            # Vérifier type (si preserve_types configuré, normaliser en lowercase)
            if preserve_types and concept.type.lower() not in preserve_types:
                # Type non éligible, mais garder si nom long (détail précis)
                if len(concept.name) < min_name_length:
                    continue

            # Vérifier longueur nom (détails précis ont noms longs)
            if len(concept.name) < min_name_length:
                continue

            rare_concepts.append(concept)

        if not rare_concepts:
            self.logger.debug(
                "[OSMOSE:Fusion:SlideSpecific] No rare/specific concepts found"
            )
            return FusionResult(
                merged_concepts=[],
                preserved_concepts=[],
                rule_name=self.name,
                reason="No rare/specific concepts detected"
            )

        self.logger.info(
            f"[OSMOSE:Fusion:SlideSpecific] Found {len(rare_concepts)} rare/specific concepts"
        )

        # Étape 3: Créer CanonicalConcepts individuels
        canonical_list = []
        processed_names = set()

        for concept in rare_concepts:
            if concept.name in processed_names:
                continue  # Éviter duplicatas

            # Créer CanonicalConcept
            canonical = self._create_canonical_from_concept(concept)
            canonical_list.append(canonical)

            processed_names.add(concept.name)

        result = FusionResult(
            merged_concepts=canonical_list,  # Techniquement "préservés" mais retournés comme merged
            preserved_concepts=[],  # Déjà inclus dans merged_concepts
            rule_name=self.name,
            reason=f"Preserved {len(canonical_list)} rare/specific concepts (≤ {max_occurrence} occurrences)",
            metadata={
                "total_concepts": len(concepts),
                "rare_concepts": len(rare_concepts),
                "canonical_created": len(canonical_list)
            }
        )

        return result

    def _create_canonical_from_concept(
        self,
        concept: Concept
    ) -> CanonicalConcept:
        """
        Crée CanonicalConcept depuis Concept individuel.

        Args:
            concept: Concept source

        Returns:
            CanonicalConcept: Concept canonique créé
        """
        # Source slides
        source_slides = []
        if concept.metadata and "source_slides" in concept.metadata:
            source_slides = concept.metadata["source_slides"]
        elif concept.metadata and "slide_index" in concept.metadata:
            source_slides = [concept.metadata["slide_index"]]

        # Metadata enrichie
        metadata = (concept.metadata or {}).copy()
        metadata["frequency"] = "rare"
        metadata["fusion_rule"] = self.name

        canonical = CanonicalConcept(
            canonical_name=concept.name,
            aliases=[],  # Pas d'aliases pour concepts uniques
            languages=[concept.language],  # Liste de langues
            type=concept.type,
            definition=concept.definition if hasattr(concept, "definition") else "",
            source_concepts=[concept],  # Liste des concepts sources
            support=1,  # Concept unique = support 1
            confidence=concept.confidence
        )

        return canonical
