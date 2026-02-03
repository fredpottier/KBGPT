# src/knowbase/claimfirst/clustering/__init__.py
"""
Clustering Claim-First Pipeline.

Module de clustering et détection de relations entre claims:
- ClaimClusterer: Agrégation inter-documents
- RelationDetector: CONTRADICTS, REFINES, QUALIFIES
"""

from knowbase.claimfirst.clustering.claim_clusterer import (
    ClaimClusterer,
)
from knowbase.claimfirst.clustering.relation_detector import (
    RelationDetector,
)

__all__ = [
    "ClaimClusterer",
    "RelationDetector",
]
