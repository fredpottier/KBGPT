"""
OSMOSE Concept Classifier - Types et Modèles

Phase 2.9.2: Classification domain-agnostic des concepts pour filtrage KG.
"""

from enum import Enum
from typing import Optional, List
from pydantic import BaseModel, Field


class ConceptKind(str, Enum):
    """
    Types de concepts universels (domain-agnostic).

    Définitions:
    - entity: Objet identifiable (personne, orga, système, produit, composant, lieu, artefact)
    - abstract: Notion stable définissable (principe, propriété, capacité, risque, méthode, métrique)
    - rule_like: Contenu prescriptif/contrainte (exigence, condition, obligation, interdiction, seuil, règle)
    - structural: Structure documentaire/logique (chapitre, section, annexe, article, tableau, figure)
    - generic: Terme trop vague/transversal pour être utile comme nœud
    - fragment: Fragment linguistique non autonome, morceau de définition, clause trop longue
    """
    ENTITY = "entity"
    ABSTRACT = "abstract"
    RULE_LIKE = "rule_like"
    STRUCTURAL = "structural"
    GENERIC = "generic"
    FRAGMENT = "fragment"


# Concepts "keepable" = participent aux relations factuelles
KEEPABLE_KINDS = {ConceptKind.ENTITY, ConceptKind.ABSTRACT, ConceptKind.RULE_LIKE}

# Concepts "non-keepable" = exclus des relations factuelles (mais peuvent avoir des liens structurels)
NON_KEEPABLE_KINDS = {ConceptKind.STRUCTURAL, ConceptKind.GENERIC, ConceptKind.FRAGMENT}


class ConceptClassification(BaseModel):
    """Résultat de classification d'un concept."""
    id: str = Field(..., description="ID du concept")
    concept_kind: ConceptKind = Field(..., description="Type de concept classifié")
    confidence: float = Field(..., ge=0.0, le=1.0, description="Score de confiance [0-1]")
    is_keepable: bool = Field(..., description="True si le concept doit participer aux relations factuelles")
    relabel_suggestion: Optional[str] = Field(
        None,
        description="Suggestion de relabel si le concept peut être amélioré"
    )


class ClassificationBatchResult(BaseModel):
    """Résultat de classification batch."""
    results: List[ConceptClassification] = Field(default_factory=list)
    total_processed: int = 0
    keepable_count: int = 0
    non_keepable_count: int = 0

    def get_keepable_ids(self) -> List[str]:
        """Retourne les IDs des concepts keepable."""
        return [r.id for r in self.results if r.is_keepable]

    def get_non_keepable_ids(self) -> List[str]:
        """Retourne les IDs des concepts non-keepable."""
        return [r.id for r in self.results if not r.is_keepable]

    def get_by_kind(self, kind: ConceptKind) -> List[ConceptClassification]:
        """Retourne les classifications d'un type donné."""
        return [r for r in self.results if r.concept_kind == kind]


class ConceptForClassification(BaseModel):
    """Concept à classifier (input)."""
    id: str = Field(..., description="ID unique du concept")
    label: str = Field(..., description="Label/nom du concept")
    context: Optional[str] = Field(None, description="Contexte optionnel (définition, phrase source)")
