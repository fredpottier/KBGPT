"""
🌊 OSMOSE Semantic Intelligence - Fusion Models

Phase 1.8.1d: Modèles de données pour la fusion de concepts.
"""

from dataclasses import dataclass, field
from typing import List, Dict, Any, Tuple, Optional
from knowbase.semantic.models import Concept


@dataclass
class FusionResult:
    """
    Résultat de l'application d'une règle de fusion.

    Attributes:
        merged_concepts: Concepts fusionnés (CanonicalConcepts créés)
        preserved_concepts: Concepts préservés tels quels
        relationships: Relations créées entre concepts (concept1, rel_type, concept2)
        rule_name: Nom de la règle appliquée
        reason: Explication de pourquoi la règle a été appliquée
        metadata: Métadonnées additionnelles (stats, debug)
    """
    merged_concepts: List[Any] = field(default_factory=list)  # List[CanonicalConcept]
    preserved_concepts: List[Concept] = field(default_factory=list)
    relationships: List[Tuple[str, str, str]] = field(default_factory=list)
    rule_name: str = ""
    reason: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class FusionConfig:
    """
    Configuration pour SmartConceptMerger.

    Attributes:
        enabled: Activer fusion intelligente
        local_extraction_types: Types de documents éligibles pour extraction locale
        fallback_strategy: Stratégie si aucune règle appliquée ("preserve_all" ou "merge_similar")
        min_cluster_size: Taille min cluster pour fusion (éviter fusions uniques)
        rules_config: Configuration spécifique par règle
    """
    enabled: bool = True
    local_extraction_types: List[str] = field(default_factory=lambda: ["PPTX", "PPTX_SLIDES"])
    fallback_strategy: str = "preserve_all"  # preserve_all | merge_similar
    min_cluster_size: int = 2
    rules_config: Dict[str, Dict[str, Any]] = field(default_factory=dict)

    @classmethod
    def from_yaml(cls, yaml_data: Dict[str, Any]) -> "FusionConfig":
        """
        Crée FusionConfig depuis données YAML.

        Args:
            yaml_data: Données YAML parsées

        Returns:
            FusionConfig: Configuration créée
        """
        return cls(
            enabled=yaml_data.get("enabled", True),
            local_extraction_types=yaml_data.get("local_extraction_types", ["PPTX", "PPTX_SLIDES"]),
            fallback_strategy=yaml_data.get("fallback_strategy", "preserve_all"),
            min_cluster_size=yaml_data.get("min_cluster_size", 2),
            rules_config=yaml_data.get("rules", {})
        )


@dataclass
class ConceptCluster:
    """
    Cluster de concepts similaires pour fusion.

    Attributes:
        concepts: Concepts du cluster
        centroid_name: Nom canonique du cluster (concept le plus fréquent)
        similarity_scores: Scores de similarité intra-cluster
        occurrences: Nombre d'occurrences par concept
        source_slides: Slides sources pour traçabilité
    """
    concepts: List[Concept] = field(default_factory=list)
    centroid_name: str = ""
    similarity_scores: Dict[str, float] = field(default_factory=dict)
    occurrences: Dict[str, int] = field(default_factory=dict)
    source_slides: List[int] = field(default_factory=list)

    @property
    def size(self) -> int:
        """Taille du cluster"""
        return len(self.concepts)

    @property
    def avg_similarity(self) -> float:
        """Similarité moyenne intra-cluster"""
        if not self.similarity_scores:
            return 0.0
        return sum(self.similarity_scores.values()) / len(self.similarity_scores)
