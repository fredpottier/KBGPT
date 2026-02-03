# src/knowbase/claimfirst/extractors/__init__.py
"""
Extracteurs Claim-First Pipeline.

Module d'extraction des Claims, Entities et Context.

INV-8: ContextExtractor pour extraction du scope documentaire
INV-9: Subject resolution conservative (pas d'auto-fusion)
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

__all__ = [
    "ClaimExtractor",
    "EntityExtractor",
    "ContextExtractor",
]
