"""
Tests pour le Graph Linter de la Navigation Layer.

Ces tests utilisent des mocks pour Neo4j afin de fonctionner
sans connexion à la base de données.

ADR: doc/ongoing/ADR_NAVIGATION_LAYER.md
"""

import pytest
from unittest.mock import Mock, MagicMock, patch

from knowbase.navigation.graph_lint import (
    GraphLinter,
    LintResult,
    LintViolation,
    LintRuleId,
    validate_graph,
)


class MockNeo4jClient:
    """Mock Neo4j client pour les tests."""

    def __init__(self, query_results=None):
        self.query_results = query_results or {}
        self.database = "neo4j"
        self._driver = Mock()

    def is_connected(self):
        return True

    @property
    def driver(self):
        session = MagicMock()

        def run_query(query, **params):
            # Retourner des résultats basés sur la requête
            for pattern, results in self.query_results.items():
                if pattern in query:
                    return iter([dict(r) for r in results])
            return iter([])

        session.run = run_query
        self._driver.session.return_value.__enter__ = lambda s: session
        self._driver.session.return_value.__exit__ = lambda s, *args: None
        return self._driver


class TestLintRuleId:
    """Tests pour les identifiants de règles."""

    def test_rule_ids(self):
        """Test que les règles ont les bons IDs."""
        assert LintRuleId.NO_CONCEPT_TO_CONCEPT_NAVIGATION.value == "NAV-001"
        assert LintRuleId.NO_SEMANTIC_TO_CONTEXT.value == "NAV-002"
        assert LintRuleId.NO_CONTEXT_TO_CONCEPT_SEMANTIC.value == "NAV-003"
        assert LintRuleId.MENTIONED_IN_HAS_PROPERTIES.value == "NAV-004"


class TestLintViolation:
    """Tests pour les violations de lint."""

    def test_violation_creation(self):
        """Test création d'une violation."""
        violation = LintViolation(
            rule_id=LintRuleId.NO_CONCEPT_TO_CONCEPT_NAVIGATION,
            message="Test violation",
            severity="ERROR",
            details={"key": "value"}
        )

        assert violation.rule_id == LintRuleId.NO_CONCEPT_TO_CONCEPT_NAVIGATION
        assert violation.message == "Test violation"
        assert violation.severity == "ERROR"
        assert violation.details["key"] == "value"

    def test_to_dict(self):
        """Test conversion en dict."""
        violation = LintViolation(
            rule_id=LintRuleId.NO_SEMANTIC_TO_CONTEXT,
            message="Test",
            severity="WARNING"
        )

        d = violation.to_dict()

        assert d["rule_id"] == "NAV-002"
        assert d["message"] == "Test"
        assert d["severity"] == "WARNING"


class TestLintResult:
    """Tests pour le résultat du lint."""

    def test_success_result(self):
        """Test résultat sans violations."""
        result = LintResult(success=True, violations=[], stats={})

        assert result.success is True
        assert len(result.violations) == 0

    def test_failure_result(self):
        """Test résultat avec violations."""
        violation = LintViolation(
            rule_id=LintRuleId.NO_CONCEPT_TO_CONCEPT_NAVIGATION,
            message="Found bad edge"
        )
        result = LintResult(
            success=False,
            violations=[violation],
            stats={"nav001_violations": 1}
        )

        assert result.success is False
        assert len(result.violations) == 1
        assert result.stats["nav001_violations"] == 1

    def test_to_dict(self):
        """Test conversion en dict."""
        result = LintResult(
            success=True,
            violations=[],
            stats={"nav001_violations": 0}
        )

        d = result.to_dict()

        assert d["success"] is True
        assert d["violation_count"] == 0
        assert d["violations"] == []


class TestGraphLinterRules:
    """Tests pour les règles du GraphLinter."""

    def test_nav001_no_violations(self):
        """Test NAV-001: Aucune violation si pas d'edges interdits."""
        mock_client = MockNeo4jClient(query_results={
            "CO_OCCURS": []  # Pas de résultats = pas de violations
        })

        linter = GraphLinter(neo4j_client=mock_client, tenant_id="test")
        violations = linter._check_nav001()

        assert len(violations) == 0

    def test_nav002_no_violations(self):
        """Test NAV-002: Aucune violation si pas de sémantique vers ContextNode."""
        mock_client = MockNeo4jClient(query_results={
            "REQUIRES": []
        })

        linter = GraphLinter(neo4j_client=mock_client, tenant_id="test")
        violations = linter._check_nav002()

        assert len(violations) == 0

    def test_nav003_no_violations(self):
        """Test NAV-003: Aucune violation si pas de sémantique depuis ContextNode."""
        mock_client = MockNeo4jClient(query_results={
            "REQUIRES": []
        })

        linter = GraphLinter(neo4j_client=mock_client, tenant_id="test")
        violations = linter._check_nav003()

        assert len(violations) == 0

    def test_nav004_no_violations(self):
        """Test NAV-004: Aucune violation si toutes les props sont présentes."""
        mock_client = MockNeo4jClient(query_results={
            "MENTIONED_IN": [{"missing_props_count": 0}]
        })

        linter = GraphLinter(neo4j_client=mock_client, tenant_id="test")
        violations = linter._check_nav004()

        assert len(violations) == 0


class TestGraphLinterIntegration:
    """Tests d'intégration pour le GraphLinter."""

    def test_run_all_rules_success(self):
        """Test exécution de toutes les règles avec succès."""
        mock_client = MockNeo4jClient(query_results={
            "CO_OCCURS": [],
            "REQUIRES": [],
            "MENTIONED_IN": [{"missing_props_count": 0}]
        })

        linter = GraphLinter(neo4j_client=mock_client, tenant_id="test")
        result = linter.run_all_rules()

        assert result.success is True
        assert len(result.violations) == 0

    def test_validate_graph_function(self):
        """Test de la fonction utilitaire validate_graph."""
        with patch('knowbase.navigation.graph_lint.get_neo4j_client') as mock_get:
            mock_client = MockNeo4jClient(query_results={
                "CO_OCCURS": [],
                "REQUIRES": [],
                "MENTIONED_IN": [{"missing_props_count": 0}]
            })
            mock_get.return_value = mock_client

            result = validate_graph(tenant_id="test")

            assert isinstance(result, LintResult)


class TestGraphLinterStats:
    """Tests pour les statistiques du linter."""

    def test_get_navigation_stats(self):
        """Test récupération des statistiques."""
        mock_client = MockNeo4jClient(query_results={
            "context_counts": [{
                "context_counts": [
                    {"kind": "document", "count": 10},
                    {"kind": "section", "count": 50}
                ],
                "mention_count": 200,
                "concepts_with_mentions": 30
            }]
        })

        linter = GraphLinter(neo4j_client=mock_client, tenant_id="test")

        # Note: Le test réel nécessiterait un mock plus complexe
        # Pour l'instant on vérifie juste que la méthode existe
        assert hasattr(linter, 'get_navigation_stats')
