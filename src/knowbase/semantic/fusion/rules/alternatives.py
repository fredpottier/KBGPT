"""
🌊 OSMOSE Semantic Intelligence - Alternatives Features Rule

Phase 1.8.1d: Règle 2 - Détecter alternatives/opposés et créer relations (PAS fusion).

Objectif:
- Identifier paires de concepts sémantiquement opposés mais co-occurrents
- Créer relations "alternative_to" (bidirectionnelles)
- Préserver TOUS concepts (pas de fusion)

Critères:
- Présence mots-clés antonymes: "vs", "versus", "instead of", "alternative to"
- Co-occurrence sur ≥ N slides (config: min_co_occurrence: 3)
- Patterns détectés: "Multi-Tenancy" ↔ "Single-Tenant Architecture"

Exemple:
    Input:
    - Concept: "Multi-Tenancy" (mentionné slides 10-20)
    - Concept: "Single-Tenant Architecture" (mentionné slides 10-20)
    - Co-occurrence: 10 slides communs

    Output:
    - Concept("Multi-Tenancy") → PRESERVED
    - Concept("Single-Tenant Architecture") → PRESERVED
    - Relationship: ("Multi-Tenancy", "alternative_to", "Single-Tenant Architecture")
    - metadata.comparison_context = "Architecture deployment options"
"""

from typing import List, Dict, Optional, Tuple, Set
import re

from knowbase.semantic.models import Concept
from ..fusion_rules import FusionRule
from ..models import FusionResult


class AlternativesFeaturesRule(FusionRule):
    """
    Règle 2: Détecter alternatives/opposés et créer relations.

    Phase 1.8.1d Sprint 1.8.1d Task T1.8.1d.4
    """

    @property
    def name(self) -> str:
        return "alternatives_features"

    def should_apply(
        self,
        concepts: List[Concept],
        context: Optional[Dict] = None
    ) -> bool:
        """
        Vérifie si des concepts avec mots-clés antonymes existent.

        Args:
            concepts: Concepts candidats
            context: Contexte (optionnel)

        Returns:
            bool: True si au moins une paire d'alternatives détectée
        """
        if not concepts or len(concepts) < 2:
            return False

        antonym_keywords = self.config.get("antonym_keywords", [
            "vs", "versus", "instead of", "alternative", "compared to"
        ])

        # Rechercher concepts avec keywords antonymes
        for concept in concepts:
            concept_text = (concept.name + " " + (concept.definition if hasattr(concept, "definition") else "")).lower()
            if any(kw in concept_text for kw in antonym_keywords):
                return True

        return False

    async def apply(
        self,
        concepts: List[Concept],
        context: Optional[Dict] = None
    ) -> FusionResult:
        """
        Applique détection alternatives et création relations.

        Args:
            concepts: Concepts à analyser
            context: Contexte document

        Returns:
            FusionResult: Relations créées, concepts préservés

        Process:
            1. Identifier paires alternatives potentielles (keywords, co-occurrence)
            2. Créer relations "alternative_to" bidirectionnelles
            3. Préserver TOUS concepts (pas de fusion)
            4. Enrichir metadata avec contexte comparaison
        """
        min_co_occurrence = self.config.get("min_co_occurrence", 3)
        antonym_keywords = self.config.get("antonym_keywords", [
            "vs", "versus", "instead of", "alternative", "compared to"
        ])

        self.logger.info(
            f"[OSMOSE:Fusion:Alternatives] Applying to {len(concepts)} concepts "
            f"(min_co_occurrence={min_co_occurrence})"
        )

        # Étape 1: Identifier paires alternatives
        alternative_pairs = self._identify_alternative_pairs(
            concepts,
            antonym_keywords,
            min_co_occurrence
        )

        if not alternative_pairs:
            self.logger.debug(
                "[OSMOSE:Fusion:Alternatives] No alternative pairs found"
            )
            return FusionResult(
                merged_concepts=[],
                preserved_concepts=[],
                relationships=[],
                rule_name=self.name,
                reason="No alternative pairs detected"
            )

        self.logger.info(
            f"[OSMOSE:Fusion:Alternatives] Found {len(alternative_pairs)} alternative pairs"
        )

        # Étape 2: Créer relations bidirectionnelles
        relationships = []
        concepts_in_pairs = set()

        for concept1, concept2, comparison_context in alternative_pairs:
            # Relation bidirectionnelle
            relationships.append((concept1.name, "alternative_to", concept2.name))
            relationships.append((concept2.name, "alternative_to", concept1.name))

            # Enrichir metadata
            if not concept1.metadata:
                concept1.metadata = {}
            if not concept2.metadata:
                concept2.metadata = {}

            concept1.metadata["alternative_to"] = concept1.metadata.get("alternative_to", [])
            concept1.metadata["alternative_to"].append(concept2.name)

            concept2.metadata["alternative_to"] = concept2.metadata.get("alternative_to", [])
            concept2.metadata["alternative_to"].append(concept1.name)

            if comparison_context:
                concept1.metadata["comparison_context"] = comparison_context
                concept2.metadata["comparison_context"] = comparison_context

            concepts_in_pairs.add(concept1.name)
            concepts_in_pairs.add(concept2.name)

        # Étape 3: Préserver TOUS concepts (pas de fusion)
        preserved = [c for c in concepts if c.name in concepts_in_pairs]

        result = FusionResult(
            merged_concepts=[],  # Pas de fusion, seulement relations
            preserved_concepts=preserved,
            relationships=relationships,
            rule_name=self.name,
            reason=f"Detected {len(alternative_pairs)} alternative pairs (preserved, not merged)",
            metadata={
                "total_concepts": len(concepts),
                "alternative_pairs": len(alternative_pairs),
                "relationships_created": len(relationships)
            }
        )

        return result

    def _identify_alternative_pairs(
        self,
        concepts: List[Concept],
        antonym_keywords: List[str],
        min_co_occurrence: int
    ) -> List[Tuple[Concept, Concept, Optional[str]]]:
        """
        Identifie paires de concepts alternatives.

        Args:
            concepts: Concepts à analyser
            antonym_keywords: Mots-clés antonymes
            min_co_occurrence: Co-occurrence minimale requise

        Returns:
            List[Tuple]: Paires (concept1, concept2, comparison_context)
        """
        pairs = []

        # Filtrer concepts avec keywords antonymes
        concepts_with_keywords = []
        for concept in concepts:
            concept_text = (concept.name + " " + (concept.definition if hasattr(concept, "definition") else "")).lower()
            if any(kw in concept_text for kw in antonym_keywords):
                concepts_with_keywords.append(concept)

        # Rechercher paires co-occurrentes
        for i, concept1 in enumerate(concepts_with_keywords):
            for concept2 in concepts_with_keywords[i+1:]:
                # Vérifier co-occurrence
                co_occurrence = self._count_co_occurrence(concept1, concept2)

                if co_occurrence >= min_co_occurrence:
                    # Paire alternative trouvée
                    comparison_context = self._extract_comparison_context(concept1, concept2)
                    pairs.append((concept1, concept2, comparison_context))

        # Ajouter paires détectées par patterns linguistiques (opposés classiques)
        linguistic_pairs = self._detect_linguistic_opposites(concepts)
        for concept1, concept2 in linguistic_pairs:
            co_occurrence = self._count_co_occurrence(concept1, concept2)
            if co_occurrence >= min_co_occurrence:
                # Vérifier si pas déjà dans pairs
                if not any((c1.name == concept1.name and c2.name == concept2.name) for c1, c2, _ in pairs):
                    pairs.append((concept1, concept2, "Linguistic opposites"))

        return pairs

    def _count_co_occurrence(
        self,
        concept1: Concept,
        concept2: Concept
    ) -> int:
        """
        Compte co-occurrences entre deux concepts (slides communs).

        Args:
            concept1: Premier concept
            concept2: Deuxième concept

        Returns:
            int: Nombre de slides communs
        """
        slides1 = set(concept1.metadata.get("source_slides", [])) if concept1.metadata else set()
        slides2 = set(concept2.metadata.get("source_slides", [])) if concept2.metadata else set()

        return len(slides1.intersection(slides2))

    def _extract_comparison_context(
        self,
        concept1: Concept,
        concept2: Concept
    ) -> Optional[str]:
        """
        Extrait contexte de comparaison depuis définitions.

        Args:
            concept1: Premier concept
            concept2: Deuxième concept

        Returns:
            str: Contexte de comparaison (ou None)
        """
        # Patterns de comparaison
        patterns = [
            r"(deployment|architecture|approach|model|strategy) options?",
            r"(comparing|versus|vs) (\w+)",
            r"alternative to (\w+)"
        ]

        # Chercher dans définitions
        for concept in [concept1, concept2]:
            if hasattr(concept, "definition") and concept.definition:
                for pattern in patterns:
                    match = re.search(pattern, concept.definition.lower())
                    if match:
                        return match.group(0)

        return None

    def _detect_linguistic_opposites(
        self,
        concepts: List[Concept]
    ) -> List[Tuple[Concept, Concept]]:
        """
        Détecte paires d'opposés linguistiques classiques.

        Args:
            concepts: Concepts à analyser

        Returns:
            List[Tuple]: Paires opposées
        """
        # Patterns opposés classiques
        opposite_patterns = [
            (r"multi[- ]?tenant(cy)?", r"single[- ]?tenant"),
            (r"cloud", r"on[- ]?premise"),
            (r"public", r"private"),
            (r"centralized", r"distributed"),
            (r"synchronous", r"asynchronous"),
            (r"horizontal", r"vertical"),
            (r"push", r"pull"),
            (r"stateful", r"stateless"),
        ]

        pairs = []

        for pattern1, pattern2 in opposite_patterns:
            # Chercher concepts matchant pattern1
            concepts1 = [c for c in concepts if re.search(pattern1, c.name.lower())]
            # Chercher concepts matchant pattern2
            concepts2 = [c for c in concepts if re.search(pattern2, c.name.lower())]

            # Créer paires
            for c1 in concepts1:
                for c2 in concepts2:
                    pairs.append((c1, c2))

        return pairs
