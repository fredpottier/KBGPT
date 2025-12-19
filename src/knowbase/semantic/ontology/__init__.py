"""
🌊 OSMOSE Phase 2.3 - Living Ontology

Module de gestion dynamique de l'ontologie.

Composants:
- PatternDiscoveryService: Détection automatique de nouveaux types
- LivingOntologyManager: Gestion du cycle de vie des types
- TypeHierarchyBuilder: Construction de hiérarchies de types

Workflow:
1. PatternDiscoveryService analyse le KG périodiquement
2. Détecte patterns récurrents (>20 occurrences) non couverts par types existants
3. Propose nouveaux types avec confidence score
4. LivingOntologyManager gère validation (auto/human)
5. Types validés intégrés dans l'ontologie active
"""

from knowbase.semantic.ontology.pattern_discovery import (
    PatternDiscoveryService,
    DiscoveredPattern,
    PatternType,
    get_pattern_discovery_service,
)
from knowbase.semantic.ontology.living_ontology_manager import (
    LivingOntologyManager,
    OntologyChange,
    ChangeType,
    TypeProposal,
    get_living_ontology_manager,
)

__all__ = [
    "PatternDiscoveryService",
    "DiscoveredPattern",
    "PatternType",
    "get_pattern_discovery_service",
    "LivingOntologyManager",
    "OntologyChange",
    "ChangeType",
    "TypeProposal",
    "get_living_ontology_manager",
]
