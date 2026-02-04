"""
OSMOSE Pipeline V2.2 - Pass 1 Extract-then-Structure
=====================================================
ADR: doc/ongoing/ADR_HYBRID_EXTRACT_THEN_STRUCTURE_2026-02-01.md

Approche bottom-up guidée:
- Pass 1.A: Extraction assertions brutes + embeddings
- Pass 1.B: Clustering zone-first (HDBSCAN)
- Pass 1.C: Nommage LLM post-clustering (concepts, thèmes, sujet)
- Pass 1.D: Purity gate + budget gate

Invariants:
- I1 Set-before-Name: les ensembles sont formés avant d'être nommés
- I2 Zone-First: clustering intra-zone puis fusion inter-zones
- I3 Budget adaptatif: nombre de concepts adapté à la taille du document
- I4 No Empty Nodes: pas de concept sans assertions
- I5 Purity Gate: validation de cohérence interne
- I6 Abstention normale: UNLINKED est un statut normal, pas un échec

EXPERIMENTAL: Pipeline Extract-then-Structure en cours de validation.
L'API peut changer sans préavis. À utiliser uniquement pour les tests.
"""

from knowbase.common.deprecation import deprecated_module, DeprecationKind

deprecated_module(
    kind=DeprecationKind.EXPERIMENTAL,
    reason="Pipeline V2.2 Extract-then-Structure en cours de validation",
    alternative="knowbase.stratified.pass1 pour le pipeline stable",
)

from knowbase.stratified.pass1_v22.models import (
    ZonedAssertion,
    AssertionCluster,
    ConceptStatus,
)
from knowbase.stratified.pass1_v22.orchestrator import Pass1OrchestratorV22

__all__ = [
    "ZonedAssertion",
    "AssertionCluster",
    "ConceptStatus",
    "Pass1OrchestratorV22",
]
