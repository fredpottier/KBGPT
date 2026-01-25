"""OSMOSE Pipeline V2 - Modèles Pydantic et Dataclasses."""

from .schemas import (
    # Enums
    DocumentStructure,
    ConceptRole,
    AssertionType,
    AssertionStatus,
    AssertionLogReason,
    DocItemType,
    # Structures documentaires
    DocumentMeta,
    Section,
    DocItem,
    # Structures sémantiques
    Subject,
    Theme,
    Concept,
    Anchor,
    Information,
    # Journal
    AssertionLogEntry,
    # Résultat Pass 1
    Pass1Stats,
    Pass1Result,
    # Pass 3 (stubs)
    CanonicalConcept,
    CanonicalTheme,
)

# MVP V1 - Nouveaux modèles pour Usage B (Challenge de Texte)
from .information import (
    InformationMVP,
    InformationType,
    RhetoricalRole,
    PromotionStatus,
    ValueKind,
    ValueComparable,
    InheritanceMode,
    ValueInfo,
    SpanInfo,
    ContextInfo,
)

from .claimkey import (
    ClaimKey,
    ClaimKeyStatus,
)

from .contradiction import (
    Contradiction,
    ContradictionNature,
    TensionLevel,
)

__all__ = [
    # Existants (schemas.py)
    "DocumentStructure",
    "ConceptRole",
    "AssertionType",
    "AssertionStatus",
    "AssertionLogReason",
    "DocItemType",
    "DocumentMeta",
    "Section",
    "DocItem",
    "Subject",
    "Theme",
    "Concept",
    "Anchor",
    "Information",
    "AssertionLogEntry",
    "Pass1Stats",
    "Pass1Result",
    "CanonicalConcept",
    "CanonicalTheme",
    # MVP V1 - Nouveaux modèles
    "InformationMVP",
    "InformationType",
    "RhetoricalRole",
    "PromotionStatus",
    "ValueKind",
    "ValueComparable",
    "InheritanceMode",
    "ValueInfo",
    "SpanInfo",
    "ContextInfo",
    "ClaimKey",
    "ClaimKeyStatus",
    "Contradiction",
    "ContradictionNature",
    "TensionLevel",
]
