"""
OSMOSE Pipeline V2 - Pass 3 (Consolidation Corpus)
===================================================
Ref: doc/ongoing/ARCH_STRATIFIED_PIPELINE_V2.md

Pass 3 consolide le graphe sémantique au niveau corpus:
- Résolution d'entités cross-documents
- Création de CanonicalConcept (SAME_AS)
- Alignement de thèmes (ALIGNED_TO)

Modes:
- BATCH: Traitement complet du corpus
- INCREMENTAL: Intégration d'un nouveau document

Usage:
    from knowbase.stratified.pass3 import run_pass3_batch, run_pass3_incremental

    # Mode batch
    result = run_pass3_batch(neo4j_driver=driver)

    # Mode incrémental
    result = run_pass3_incremental(new_concepts, neo4j_driver=driver)
"""

from knowbase.stratified.pass3.entity_resolver import (
    EntityResolverV2,
    ConceptCluster,
    ThemeCluster,
    Pass3Result,
    Pass3Stats,
)
from knowbase.stratified.pass3.persister import (
    Pass3PersisterV2,
    persist_pass3_result,
)
from knowbase.stratified.pass3.orchestrator import (
    Pass3OrchestratorV2,
    Pass3Mode,
    run_pass3_batch,
    run_pass3_incremental,
)

__all__ = [
    # Orchestrator
    "Pass3OrchestratorV2",
    "Pass3Mode",
    "run_pass3_batch",
    "run_pass3_incremental",
    # Resolver
    "EntityResolverV2",
    "ConceptCluster",
    "ThemeCluster",
    "Pass3Result",
    "Pass3Stats",
    # Persistence
    "Pass3PersisterV2",
    "persist_pass3_result",
]
