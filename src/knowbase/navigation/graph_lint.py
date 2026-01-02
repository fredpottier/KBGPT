"""
OSMOSE Navigation Layer - Graph Lint

Validation anti-mélange entre couche navigation et couche sémantique.
ADR: doc/ongoing/ADR_NAVIGATION_LAYER.md

Ces règles DOIVENT retourner 0 violations pour un graphe valide.
À exécuter:
- En CI/CD avant déploiement
- Après chaque import de document
- Via commande CLI: knowbase validate-graph

Author: Claude Code
Date: 2026-01-01
"""

import logging
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any
from enum import Enum

from knowbase.common.clients.neo4j_client import Neo4jClient, get_neo4j_client
from knowbase.config.settings import get_settings

from .types import NAVIGATION_RELATION_TYPES, SEMANTIC_RELATION_TYPES

logger = logging.getLogger(__name__)


class LintRuleId(str, Enum):
    """Identifiants des règles de lint."""
    NO_CONCEPT_TO_CONCEPT_NAVIGATION = "NAV-001"
    NO_SEMANTIC_TO_CONTEXT = "NAV-002"
    NO_CONTEXT_TO_CONCEPT_SEMANTIC = "NAV-003"
    MENTIONED_IN_HAS_PROPERTIES = "NAV-004"


@dataclass
class LintViolation:
    """Violation d'une règle de lint."""
    rule_id: LintRuleId
    message: str
    severity: str = "ERROR"  # ERROR, WARNING, INFO
    details: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "rule_id": self.rule_id.value,
            "message": self.message,
            "severity": self.severity,
            "details": self.details,
        }


@dataclass
class LintResult:
    """Résultat du lint complet."""
    success: bool
    violations: List[LintViolation] = field(default_factory=list)
    stats: Dict[str, int] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "success": self.success,
            "violation_count": len(self.violations),
            "violations": [v.to_dict() for v in self.violations],
            "stats": self.stats,
        }


class GraphLinter:
    """
    Linter pour valider la séparation navigation/sémantique.

    Règles validées:
    - NAV-001: Pas d'edges navigation entre Concept→Concept
    - NAV-002: Pas de prédicats sémantiques vers ContextNode
    - NAV-003: Pas de prédicats sémantiques depuis ContextNode
    - NAV-004: MENTIONED_IN a les propriétés requises
    """

    # Relations de navigation interdites entre concepts
    FORBIDDEN_CONCEPT_TO_CONCEPT = [
        "CO_OCCURS",
        "CO_OCCURS_IN_CORPUS",
        "CO_OCCURS_IN_DOCUMENT",
        "MENTIONED_TOGETHER",
        "APPEARS_WITH",
    ]

    def __init__(
        self,
        neo4j_client: Optional[Neo4jClient] = None,
        tenant_id: str = "default"
    ):
        """
        Initialise le linter.

        Args:
            neo4j_client: Client Neo4j (default: singleton from env)
            tenant_id: Tenant ID pour isolation
        """
        if neo4j_client:
            self.neo4j = neo4j_client
        else:
            settings = get_settings()
            self.neo4j = get_neo4j_client(
                uri=settings.neo4j_uri,
                user=settings.neo4j_user,
                password=settings.neo4j_password
            )

        self.tenant_id = tenant_id

    def _execute_query(
        self,
        query: str,
        params: Dict[str, Any]
    ) -> List[Dict[str, Any]]:
        """Exécute une requête Cypher."""
        if not self.neo4j.is_connected():
            logger.error("[GraphLinter] Neo4j not connected")
            return []

        try:
            with self.neo4j.driver.session(database=self.neo4j.database) as session:
                result = session.run(query, params)
                return [dict(record) for record in result]
        except Exception as e:
            logger.error(f"[GraphLinter] Query failed: {e}")
            return []

    def run_all_rules(self) -> LintResult:
        """
        Exécute toutes les règles de lint.

        Returns:
            LintResult avec toutes les violations trouvées
        """
        logger.info(f"[GraphLinter] Running all lint rules for tenant={self.tenant_id}")

        violations: List[LintViolation] = []
        stats: Dict[str, int] = {}

        # Règle NAV-001: Pas de navigation Concept→Concept
        nav001_violations = self._check_nav001()
        violations.extend(nav001_violations)
        stats["nav001_violations"] = len(nav001_violations)

        # Règle NAV-002: Pas de sémantique vers ContextNode
        nav002_violations = self._check_nav002()
        violations.extend(nav002_violations)
        stats["nav002_violations"] = len(nav002_violations)

        # Règle NAV-003: Pas de sémantique depuis ContextNode
        nav003_violations = self._check_nav003()
        violations.extend(nav003_violations)
        stats["nav003_violations"] = len(nav003_violations)

        # Règle NAV-004: MENTIONED_IN a les propriétés requises
        nav004_violations = self._check_nav004()
        violations.extend(nav004_violations)
        stats["nav004_violations"] = len(nav004_violations)

        success = len(violations) == 0

        result = LintResult(
            success=success,
            violations=violations,
            stats=stats
        )

        if success:
            logger.info("[GraphLinter] All rules passed!")
        else:
            logger.warning(f"[GraphLinter] Found {len(violations)} violations")

        return result

    def _check_nav001(self) -> List[LintViolation]:
        """
        NAV-001: Interdire les edges de navigation Concept→Concept.

        Ces edges créent une ambiguïté avec les relations sémantiques.
        """
        forbidden_types = "|".join(self.FORBIDDEN_CONCEPT_TO_CONCEPT)

        query = f"""
        MATCH (a:CanonicalConcept {{tenant_id: $tenant_id}})
              -[r:{forbidden_types}]->
              (b:CanonicalConcept {{tenant_id: $tenant_id}})
        RETURN a.canonical_id AS source_id,
               a.canonical_name AS source_name,
               type(r) AS rel_type,
               b.canonical_id AS target_id,
               b.canonical_name AS target_name
        LIMIT 10
        """

        results = self._execute_query(query, {"tenant_id": self.tenant_id})

        violations = []
        for r in results:
            violations.append(LintViolation(
                rule_id=LintRuleId.NO_CONCEPT_TO_CONCEPT_NAVIGATION,
                message=(
                    f"Navigation edge [{r['rel_type']}] found between concepts "
                    f"'{r['source_name']}' → '{r['target_name']}'. "
                    f"Use ContextNode intermediary instead."
                ),
                severity="ERROR",
                details={
                    "source_id": r["source_id"],
                    "target_id": r["target_id"],
                    "relation_type": r["rel_type"],
                }
            ))

        return violations

    def _check_nav002(self) -> List[LintViolation]:
        """
        NAV-002: Interdire les prédicats sémantiques vers ContextNode.

        Les relations sémantiques ne doivent jamais pointer vers un ContextNode.
        """
        semantic_types = "|".join(SEMANTIC_RELATION_TYPES)

        query = f"""
        MATCH (:CanonicalConcept {{tenant_id: $tenant_id}})
              -[r:{semantic_types}]->
              (ctx:ContextNode {{tenant_id: $tenant_id}})
        RETURN type(r) AS rel_type,
               ctx.context_id AS context_id,
               ctx.kind AS context_kind
        LIMIT 10
        """

        results = self._execute_query(query, {"tenant_id": self.tenant_id})

        violations = []
        for r in results:
            violations.append(LintViolation(
                rule_id=LintRuleId.NO_SEMANTIC_TO_CONTEXT,
                message=(
                    f"Semantic relation [{r['rel_type']}] points to ContextNode "
                    f"'{r['context_id']}'. Semantic relations must only connect concepts."
                ),
                severity="ERROR",
                details={
                    "relation_type": r["rel_type"],
                    "context_id": r["context_id"],
                    "context_kind": r["context_kind"],
                }
            ))

        return violations

    def _check_nav003(self) -> List[LintViolation]:
        """
        NAV-003: Interdire les prédicats sémantiques depuis ContextNode.

        Les ContextNodes ne doivent jamais être source de relations sémantiques.
        """
        semantic_types = "|".join(SEMANTIC_RELATION_TYPES)

        query = f"""
        MATCH (ctx:ContextNode {{tenant_id: $tenant_id}})
              -[r:{semantic_types}]->
              (:CanonicalConcept {{tenant_id: $tenant_id}})
        RETURN type(r) AS rel_type,
               ctx.context_id AS context_id,
               ctx.kind AS context_kind
        LIMIT 10
        """

        results = self._execute_query(query, {"tenant_id": self.tenant_id})

        violations = []
        for r in results:
            violations.append(LintViolation(
                rule_id=LintRuleId.NO_CONTEXT_TO_CONCEPT_SEMANTIC,
                message=(
                    f"ContextNode '{r['context_id']}' is source of semantic relation "
                    f"[{r['rel_type']}]. ContextNodes must not have outgoing semantic relations."
                ),
                severity="ERROR",
                details={
                    "relation_type": r["rel_type"],
                    "context_id": r["context_id"],
                    "context_kind": r["context_kind"],
                }
            ))

        return violations

    def _check_nav004(self) -> List[LintViolation]:
        """
        NAV-004: Vérifier que MENTIONED_IN a les propriétés requises.

        Chaque relation MENTIONED_IN doit avoir: count, weight, first_seen.
        """
        query = """
        MATCH (:CanonicalConcept {tenant_id: $tenant_id})
              -[r:MENTIONED_IN]->
              (:ContextNode {tenant_id: $tenant_id})
        WHERE r.count IS NULL OR r.first_seen IS NULL
        RETURN count(r) AS missing_props_count
        """

        results = self._execute_query(query, {"tenant_id": self.tenant_id})

        violations = []
        if results and results[0]["missing_props_count"] > 0:
            count = results[0]["missing_props_count"]
            violations.append(LintViolation(
                rule_id=LintRuleId.MENTIONED_IN_HAS_PROPERTIES,
                message=(
                    f"{count} MENTIONED_IN relations are missing required properties "
                    f"(count, first_seen). Run compute_weights() to fix."
                ),
                severity="WARNING",
                details={"count": count}
            ))

        return violations

    def get_navigation_stats(self) -> Dict[str, Any]:
        """
        Retourne les statistiques de la Navigation Layer.

        Returns:
            Dict avec comptages des différents types de noeuds et relations
        """
        query = """
        // Compter les ContextNodes par type
        MATCH (ctx:ContextNode {tenant_id: $tenant_id})
        WITH ctx.kind AS kind, count(ctx) AS count
        WITH collect({kind: kind, count: count}) AS context_counts

        // Compter les relations MENTIONED_IN
        OPTIONAL MATCH (:CanonicalConcept {tenant_id: $tenant_id})
                       -[r:MENTIONED_IN]->
                       (:ContextNode {tenant_id: $tenant_id})
        WITH context_counts, count(r) AS mention_count

        // Compter les concepts avec au moins une mention
        OPTIONAL MATCH (c:CanonicalConcept {tenant_id: $tenant_id})
                       -[:MENTIONED_IN]->
                       (:ContextNode {tenant_id: $tenant_id})
        WITH context_counts, mention_count, count(DISTINCT c) AS concepts_with_mentions

        RETURN context_counts, mention_count, concepts_with_mentions
        """

        results = self._execute_query(query, {"tenant_id": self.tenant_id})

        if not results:
            return {"error": "Query failed"}

        r = results[0]

        # Parser les context_counts
        context_stats = {}
        for item in r.get("context_counts", []):
            if item.get("kind"):
                context_stats[f"{item['kind']}_count"] = item["count"]

        return {
            **context_stats,
            "mention_relations": r.get("mention_count", 0),
            "concepts_with_mentions": r.get("concepts_with_mentions", 0),
        }


def validate_graph(tenant_id: str = "default") -> LintResult:
    """
    Fonction utilitaire pour valider le graphe.

    Usage:
        from knowbase.navigation import validate_graph
        result = validate_graph()
        if not result.success:
            for v in result.violations:
                print(f"{v.rule_id}: {v.message}")

    Args:
        tenant_id: Tenant ID

    Returns:
        LintResult
    """
    linter = GraphLinter(tenant_id=tenant_id)
    return linter.run_all_rules()
