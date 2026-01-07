"""
OSMOSE Graph Governance - Budget Layer

ADR_GRAPH_GOVERNANCE_LAYERS - Phase B

Ce service implémente la couche Budget/Usage Control du framework de gouvernance.
Il contrôle l'expansion du graphe À LA REQUÊTE pour éviter l'explosion combinatoire.

IMPORTANT (garde-fous ADR):
- Les règles de budget ne modifient JAMAIS l'état persistant du graphe
- Aucune suppression, aucun masquage définitif
- Le graphe complet reste TOUJOURS accessible si besoin
- C'est un mécanisme de FILTRAGE query-time, pas de MODIFICATION

Paramètres de contrôle:
- max_hops: Profondeur maximale de traversée (défaut: 2)
- max_relations_per_hop: Relations par nœud par niveau (défaut: 10)
- min_confidence_tier: Tier minimum pour traversée (défaut: MEDIUM)
- include_weak_links: Inclure CO_OCCURS_IN_CORPUS (défaut: False)
- max_total_nodes: Limite absolue de nœuds (défaut: 100)
- timeout_ms: Timeout de requête (défaut: 5000)

Date: 2026-01-07
"""

import logging
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any, Tuple
from enum import Enum

logger = logging.getLogger(__name__)


class BudgetPreset(str, Enum):
    """Presets de budget prédéfinis."""
    STRICT = "strict"       # Très restrictif - HIGH only, max 50 nœuds
    STANDARD = "standard"   # Défaut - MEDIUM+, max 100 nœuds
    EXPLORATORY = "exploratory"  # Large - LOW+, max 200 nœuds
    UNLIMITED = "unlimited"  # Pas de limite (attention!)


@dataclass
class QueryBudget:
    """
    Configuration de budget pour une requête.

    IMPORTANT: Ces paramètres contrôlent UNIQUEMENT la traversée,
    ils ne modifient jamais l'état persistant du graphe.
    """
    max_hops: int = 2
    max_relations_per_hop: int = 10
    min_confidence_tier: str = "MEDIUM"  # HIGH, MEDIUM, LOW, WEAK
    include_weak_links: bool = False     # CO_OCCURS_IN_CORPUS
    max_total_nodes: int = 100
    timeout_ms: int = 5000

    def to_dict(self) -> Dict[str, Any]:
        return {
            "max_hops": self.max_hops,
            "max_relations_per_hop": self.max_relations_per_hop,
            "min_confidence_tier": self.min_confidence_tier,
            "include_weak_links": self.include_weak_links,
            "max_total_nodes": self.max_total_nodes,
            "timeout_ms": self.timeout_ms,
        }

    @classmethod
    def from_preset(cls, preset: BudgetPreset) -> "QueryBudget":
        """Crée un budget depuis un preset."""
        presets = {
            BudgetPreset.STRICT: cls(
                max_hops=1,
                max_relations_per_hop=5,
                min_confidence_tier="HIGH",
                include_weak_links=False,
                max_total_nodes=50,
                timeout_ms=3000,
            ),
            BudgetPreset.STANDARD: cls(
                max_hops=2,
                max_relations_per_hop=10,
                min_confidence_tier="MEDIUM",
                include_weak_links=False,
                max_total_nodes=100,
                timeout_ms=5000,
            ),
            BudgetPreset.EXPLORATORY: cls(
                max_hops=3,
                max_relations_per_hop=15,
                min_confidence_tier="LOW",
                include_weak_links=True,
                max_total_nodes=200,
                timeout_ms=10000,
            ),
            BudgetPreset.UNLIMITED: cls(
                max_hops=5,
                max_relations_per_hop=50,
                min_confidence_tier="WEAK",
                include_weak_links=True,
                max_total_nodes=1000,
                timeout_ms=30000,
            ),
        }
        return presets.get(preset, presets[BudgetPreset.STANDARD])


# Mapping des tiers vers leur niveau numérique (pour filtrage >=)
TIER_LEVELS = {
    "HIGH": 4,
    "MEDIUM": 3,
    "LOW": 2,
    "WEAK": 1,
}


@dataclass
class BudgetedQueryResult:
    """Résultat d'une requête budgétée."""
    nodes: List[Dict[str, Any]]
    edges: List[Dict[str, Any]]
    budget_applied: QueryBudget
    budget_exceeded: bool = False
    nodes_truncated: int = 0    # Nœuds non retournés car dépassement
    warning: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "nodes": self.nodes,
            "edges": self.edges,
            "budget_applied": self.budget_applied.to_dict(),
            "budget_exceeded": self.budget_exceeded,
            "nodes_truncated": self.nodes_truncated,
            "warning": self.warning,
        }


class GovernanceBudgetService:
    """
    Service de contrôle budgétaire pour les requêtes KG.

    IMPORTANT: Ce service ne modifie JAMAIS le graphe.
    Il fournit des utilitaires pour construire des requêtes Cypher
    qui respectent les contraintes de budget.
    """

    # Budget par défaut
    DEFAULT_BUDGET = QueryBudget()

    def __init__(self, tenant_id: str = "default"):
        self.tenant_id = tenant_id

    def get_tier_filter_clause(self, min_tier: str) -> str:
        """
        Génère la clause WHERE pour filtrer par tier minimum.

        Args:
            min_tier: Tier minimum accepté (HIGH, MEDIUM, LOW, WEAK)

        Returns:
            Clause Cypher pour le filtrage
        """
        min_level = TIER_LEVELS.get(min_tier.upper(), 3)

        if min_level >= 4:
            return "r.confidence_tier = 'HIGH'"
        elif min_level >= 3:
            return "r.confidence_tier IN ['HIGH', 'MEDIUM']"
        elif min_level >= 2:
            return "r.confidence_tier IN ['HIGH', 'MEDIUM', 'LOW']"
        else:
            return "r.confidence_tier IS NOT NULL"

    def get_weak_links_clause(self, include_weak: bool) -> str:
        """
        Génère la clause pour inclure/exclure CO_OCCURS_IN_CORPUS.

        Args:
            include_weak: True pour inclure les liens faibles

        Returns:
            Clause Cypher
        """
        if include_weak:
            return ""  # Pas de filtre
        return "AND type(r) <> 'CO_OCCURS_IN_CORPUS'"

    def build_budgeted_traversal_query(
        self,
        start_concept_id: str,
        budget: Optional[QueryBudget] = None,
        direction: str = "BOTH"  # OUT, IN, BOTH
    ) -> Tuple[str, Dict[str, Any]]:
        """
        Construit une requête Cypher de traversée budgétée.

        Args:
            start_concept_id: ID du concept de départ
            budget: Configuration de budget (défaut: STANDARD)
            direction: Direction de traversée (OUT, IN, BOTH)

        Returns:
            Tuple (query_string, parameters)
        """
        budget = budget or self.DEFAULT_BUDGET

        # Direction pattern
        if direction == "OUT":
            rel_pattern = "-[r]->"
        elif direction == "IN":
            rel_pattern = "<-[r]-"
        else:
            rel_pattern = "-[r]-"

        # Construire les clauses de filtrage
        tier_clause = self.get_tier_filter_clause(budget.min_confidence_tier)
        weak_clause = self.get_weak_links_clause(budget.include_weak_links)

        # Requête avec budget appliqué
        query = f"""
        // Traversée budgétée - ADR Graph Governance Layers
        // Budget: max_hops={budget.max_hops}, max_nodes={budget.max_total_nodes}
        MATCH (start:CanonicalConcept {{canonical_id: $concept_id, tenant_id: $tenant_id}})

        CALL apoc.path.subgraphNodes(start, {{
            relationshipFilter: "{rel_pattern.replace('[r]', '')}",
            minLevel: 1,
            maxLevel: $max_hops,
            limit: $max_nodes
        }}) YIELD node AS related

        // Récupérer les relations entre start et related
        WITH start, collect(DISTINCT related) AS related_nodes
        UNWIND related_nodes AS related

        MATCH (start){rel_pattern}(related)
        WHERE {tier_clause}
        {weak_clause}

        // Limiter par hop
        WITH start, related, r,
             CASE
                WHEN r.confidence_tier = 'HIGH' THEN 4
                WHEN r.confidence_tier = 'MEDIUM' THEN 3
                WHEN r.confidence_tier = 'LOW' THEN 2
                ELSE 1
             END AS tier_score
        ORDER BY tier_score DESC, r.evidence_count DESC

        // Retourner les résultats
        RETURN DISTINCT
            related.canonical_id AS concept_id,
            related.canonical_name AS name,
            related.concept_type AS type,
            type(r) AS predicate,
            r.confidence_tier AS confidence_tier,
            r.evidence_count AS evidence_count,
            r.evidence_strength AS evidence_strength
        LIMIT $max_nodes
        """

        params = {
            "concept_id": start_concept_id,
            "tenant_id": self.tenant_id,
            "max_hops": budget.max_hops,
            "max_nodes": budget.max_total_nodes,
            "min_tier": budget.min_confidence_tier,
        }

        return query, params

    def build_simple_budgeted_query(
        self,
        start_concept_id: str,
        budget: Optional[QueryBudget] = None,
    ) -> Tuple[str, Dict[str, Any]]:
        """
        Construit une requête simple de traversée budgétée (sans APOC).

        Version compatible avec Neo4j standard sans plugins.

        Args:
            start_concept_id: ID du concept de départ
            budget: Configuration de budget (défaut: STANDARD)

        Returns:
            Tuple (query_string, parameters)
        """
        budget = budget or self.DEFAULT_BUDGET

        # Construire les clauses de filtrage
        tier_clause = self.get_tier_filter_clause(budget.min_confidence_tier)
        weak_clause = self.get_weak_links_clause(budget.include_weak_links)

        # Pattern de profondeur variable
        hop_range = f"*1..{budget.max_hops}"

        query = f"""
        // Traversée budgétée simple - ADR Graph Governance Layers
        // Budget: max_hops={budget.max_hops}, min_tier={budget.min_confidence_tier}
        MATCH path = (start:CanonicalConcept {{canonical_id: $concept_id, tenant_id: $tenant_id}})
                     -[r{hop_range}]-(related:CanonicalConcept)
        WHERE related.tenant_id = $tenant_id
          AND ALL(rel IN relationships(path) WHERE
              ({tier_clause.replace('r.', 'rel.')})
              {weak_clause.replace('r)', 'rel)').replace('(r)', '(rel)')}
          )

        WITH DISTINCT related,
             relationships(path) AS rels,
             length(path) AS depth

        // Scorer et trier
        WITH related, rels, depth,
             reduce(s = 0, rel IN rels |
                s + CASE
                    WHEN rel.confidence_tier = 'HIGH' THEN 4
                    WHEN rel.confidence_tier = 'MEDIUM' THEN 3
                    WHEN rel.confidence_tier = 'LOW' THEN 2
                    ELSE 1
                END
             ) AS total_tier_score

        ORDER BY depth ASC, total_tier_score DESC

        // Retourner avec limite
        RETURN
            related.canonical_id AS concept_id,
            related.canonical_name AS name,
            related.concept_type AS type,
            depth,
            total_tier_score AS score,
            [rel IN rels | {{
                predicate: type(rel),
                tier: rel.confidence_tier,
                evidence: rel.evidence_count
            }}] AS path_relations
        LIMIT $max_nodes
        """

        params = {
            "concept_id": start_concept_id,
            "tenant_id": self.tenant_id,
            "max_nodes": budget.max_total_nodes,
        }

        return query, params

    def get_budget_stats(self, budget: QueryBudget) -> Dict[str, Any]:
        """
        Calcule les statistiques attendues pour un budget donné.

        Utile pour afficher des warnings dans l'UI.

        Args:
            budget: Configuration de budget

        Returns:
            Dict avec estimations
        """
        # Estimation grossière du nombre max de nœuds possibles
        # Formule: sum(relations_per_hop^i for i in 1..max_hops)
        max_theoretical = sum(
            budget.max_relations_per_hop ** i
            for i in range(1, budget.max_hops + 1)
        )

        return {
            "budget": budget.to_dict(),
            "max_theoretical_nodes": max_theoretical,
            "actual_limit": budget.max_total_nodes,
            "is_limited": max_theoretical > budget.max_total_nodes,
            "tier_filter": budget.min_confidence_tier,
            "includes_weak_links": budget.include_weak_links,
        }


# Presets disponibles pour l'API
BUDGET_PRESETS = {
    preset.value: QueryBudget.from_preset(preset).to_dict()
    for preset in BudgetPreset
}


def get_governance_budget_service(tenant_id: str = "default") -> GovernanceBudgetService:
    """Récupère le service de gouvernance budget."""
    return GovernanceBudgetService(tenant_id)


__all__ = [
    "BudgetPreset",
    "QueryBudget",
    "BudgetedQueryResult",
    "GovernanceBudgetService",
    "get_governance_budget_service",
    "BUDGET_PRESETS",
]
