"""
Lifecycle Doc→Doc — V2-S1 (version stricte, evidence-locked).

Conformément à VISION_RECENTREE_OSMOSIS_2026-04-30 §1bis :
- Le KG porte des FAITS documentés, pas des inférences.
- Une LIFECYCLE_RELATION Doc→Doc est persistée UNIQUEMENT si une déclaration
  textuelle explicite est présente dans le doc source ET validée evidence-locked.
- Les inférences (recency, version ordering, KG centrality) sont des indices
  RUNTIME consultés par le Current Resolver — jamais persistés.

Pipeline :
1. DeclarationExtractor — LLM Qwen2.5-14B AWQ sémantique pur sur texte
2. DeclarationValidator — substring match + target resolution vers DocumentContext
3. LifecyclePersister — Neo4j MERGE LIFECYCLE_RELATION

Ref : doc/ongoing/ADR_LIFECYCLE_VS_LOGICAL_RELATIONS.md (version stricte 30/04/2026)
"""

from knowbase.lifecycle.models import (
    LifecycleType,
    LifecycleDeclarationCandidate,
    LifecycleExtractionResult,
    ValidatedLifecycleRelation,
    ValidationOutcome,
)
from knowbase.lifecycle.declaration_extractor import LifecycleDeclarationExtractor
from knowbase.lifecycle.declaration_validator import LifecycleDeclarationValidator
from knowbase.lifecycle.lifecycle_persister import LifecyclePersister

__all__ = [
    "LifecycleType",
    "LifecycleDeclarationCandidate",
    "LifecycleExtractionResult",
    "ValidatedLifecycleRelation",
    "ValidationOutcome",
    "LifecycleDeclarationExtractor",
    "LifecycleDeclarationValidator",
    "LifecyclePersister",
]
