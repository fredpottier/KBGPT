# src/knowbase/claimfirst/linkers/__init__.py
"""
Linkers Claim-First Pipeline.

Module de linking déterministe (pas de LLM):
- PassageLinker: Claim → Passage
- EntityLinker: Claim → Entity
- FacetMatcher: Claim → Facet
"""

from knowbase.claimfirst.linkers.passage_linker import (
    PassageLinker,
)
from knowbase.claimfirst.linkers.entity_linker import (
    EntityLinker,
)
from knowbase.claimfirst.linkers.facet_matcher import (
    FacetMatcher,
)

__all__ = [
    "PassageLinker",
    "EntityLinker",
    "FacetMatcher",
]
