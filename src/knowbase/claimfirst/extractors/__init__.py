# src/knowbase/claimfirst/extractors/__init__.py
"""
Extracteurs Claim-First Pipeline.

Module d'extraction des Claims, Entities et Context.

INV-8: ContextExtractor pour extraction du scope documentaire
INV-9: Subject resolution conservative (pas d'auto-fusion)
QS Cross-Doc v1: comparability_gate, scope_resolver, qs_llm_extractor, dimension_mapper
"""

from knowbase.claimfirst.extractors.claim_extractor import (
    ClaimExtractor,
)
from knowbase.claimfirst.extractors.entity_extractor import (
    EntityExtractor,
)
from knowbase.claimfirst.extractors.context_extractor import (
    ContextExtractor,
)
from knowbase.claimfirst.extractors.comparability_gate import (
    GatingResult,
    candidate_gate,
)
from knowbase.claimfirst.extractors.scope_resolver import (
    resolve_scope,
)
from knowbase.claimfirst.extractors.qs_llm_extractor import (
    llm_comparability_gate,
    llm_extract_qs,
)
from knowbase.claimfirst.extractors.dimension_mapper import (
    map_to_dimension,
)

__all__ = [
    "ClaimExtractor",
    "EntityExtractor",
    "ContextExtractor",
    # QS Cross-Doc v1
    "GatingResult",
    "candidate_gate",
    "resolve_scope",
    "llm_comparability_gate",
    "llm_extract_qs",
    "map_to_dimension",
]
