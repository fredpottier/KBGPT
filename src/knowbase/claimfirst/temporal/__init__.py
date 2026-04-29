"""
Module temporal — extraction TemporalFrame claim-level (V3.3).

Cascade simplifiée post-audit Phase A (cf. plan zazzy-beaming-crane.md S1b) :

  Tier 5 (default) : Claim.publication_date = DocumentContext.publication_date
                     (Cypher pure inherit — 100% des claims)
                     Claim.validity_start = NULL (NE PAS hériter publication_date)

  Tier 3 (pre-filter) : claims dont passage_text contient un pattern numérique
                        de date (universel, pas de keywords lexicaux)
                        → 8.5% des claims (3 401 sur 40 196)

  Tier 4 (LLM evidence-locked) : sur les candidats Tier 3, LLM Qwen2.5-14B
                                 extrait validity_start/end avec date_role +
                                 evidence_quote. Validator V3.3 applique.
                                 Override le default si role ∈ {effective, applicable_from, expiry}.

Lifecycle claim-level reste UNKNOWN par défaut (déféré S3 — sera dérivé via
SUPERSEDES detection cross-doc par le 12-class classifier).
"""

from knowbase.claimfirst.temporal.temporal_extractor import (
    ClaimTemporalResult,
    TemporalExtractor,
    has_temporal_signal,
)

__all__ = [
    "ClaimTemporalResult",
    "TemporalExtractor",
    "has_temporal_signal",
]
