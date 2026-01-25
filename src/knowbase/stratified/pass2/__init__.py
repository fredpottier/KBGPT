"""
OSMOSE Pipeline V2 - Pass 2 (Enrichissement)
=============================================
Ref: doc/ongoing/ARCH_STRATIFIED_PIPELINE_V2.md

Pass 2 enrichit le graphe sémantique avec les relations entre concepts.

Usage:
    from knowbase.stratified.pass2 import Pass2OrchestratorV2, run_pass2

    result = run_pass2(pass1_result, llm_client=my_client)
"""

from knowbase.stratified.pass2.relation_extractor import (
    RelationExtractorV2,
    ConceptRelation,
    Pass2Result,
    Pass2Stats,
    RelationType,
    VALID_RELATION_TYPES,
)
from knowbase.stratified.pass2.persister import (
    Pass2PersisterV2,
    persist_pass2_result,
)
from knowbase.stratified.pass2.orchestrator import (
    Pass2OrchestratorV2,
    run_pass2,
)

__all__ = [
    # Orchestrator
    "Pass2OrchestratorV2",
    "run_pass2",
    # Extractor
    "RelationExtractorV2",
    "ConceptRelation",
    "Pass2Result",
    "Pass2Stats",
    # Types
    "RelationType",
    "VALID_RELATION_TYPES",
    # Persistence
    "Pass2PersisterV2",
    "persist_pass2_result",
]
