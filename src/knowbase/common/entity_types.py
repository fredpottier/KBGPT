"""
Types d'entités et relations Knowledge Graph.
Module léger sans dépendances Pydantic pour import rapide.
"""
from enum import Enum


class EntityType(str, Enum):
    """
    Types d'entités de base dans le Knowledge Graph.

    Note: Le système supporte des types dynamiques découverts automatiquement.
    Cette enum contient uniquement les types de bootstrap initiaux.
    Les nouveaux types découverts par le LLM sont stockés en base et validés manuellement.
    """
    SOLUTION = "SOLUTION"
    COMPONENT = "COMPONENT"
    ORGANIZATION = "ORGANIZATION"
    PERSON = "PERSON"
    TECHNOLOGY = "TECHNOLOGY"
    CONCEPT = "CONCEPT"


class RelationType(str, Enum):
    """Types de relations dans le Knowledge Graph."""
    INTEGRATES_WITH = "INTEGRATES_WITH"
    PART_OF = "PART_OF"
    USES = "USES"
    PROVIDES = "PROVIDES"
    REPLACES = "REPLACES"
    REQUIRES = "REQUIRES"
    INTERACTS_WITH = "INTERACTS_WITH"


__all__ = ["EntityType", "RelationType"]
