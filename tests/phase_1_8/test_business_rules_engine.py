"""
Tests Phase 1.8.4 - Business Rules Engine

Valide le moteur de règles métier custom par tenant.
Différenciateur marché vs Microsoft Copilot / Google Gemini.
"""

import pytest
from unittest.mock import Mock, patch
from pathlib import Path
import tempfile
import yaml

from knowbase.rules.engine import (
    BusinessRulesEngine,
    Rule,
    RuleType,
    RuleAction,
    RuleCondition,
    ConditionOperator,
    RuleResult,
    create_pharma_compliance_rules,
    create_sap_validation_rules
)
from knowbase.rules.loader import RulesLoader, load_engine_with_rules


# =========================================================================
# Test: Rule Conditions
# =========================================================================

class TestRuleConditions:
    """Tests for RuleCondition evaluation."""

    def test_equals_condition(self):
        """EQUALS operator works correctly."""
        condition = RuleCondition(
            field="domain",
            operator=ConditionOperator.EQUALS,
            value="SAP"
        )

        assert condition.evaluate({"domain": "SAP"}) is True
        assert condition.evaluate({"domain": "sap"}) is True  # Case insensitive
        assert condition.evaluate({"domain": "Oracle"}) is False

    def test_not_equals_condition(self):
        """NOT_EQUALS operator works correctly."""
        condition = RuleCondition(
            field="status",
            operator=ConditionOperator.NOT_EQUALS,
            value="deprecated"
        )

        assert condition.evaluate({"status": "active"}) is True
        assert condition.evaluate({"status": "deprecated"}) is False

    def test_contains_condition_string(self):
        """CONTAINS operator works with strings."""
        condition = RuleCondition(
            field="canonical_name",
            operator=ConditionOperator.CONTAINS,
            value="hana"
        )

        assert condition.evaluate({"canonical_name": "SAP HANA Cloud"}) is True
        assert condition.evaluate({"canonical_name": "SAP ERP"}) is False

    def test_contains_condition_list(self):
        """CONTAINS operator works with lists."""
        condition = RuleCondition(
            field="tags",
            operator=ConditionOperator.CONTAINS,
            value="regulatory"
        )

        assert condition.evaluate({"tags": ["regulatory", "pharma"]}) is True
        assert condition.evaluate({"tags": ["technical", "sap"]}) is False

    def test_matches_regex_condition(self):
        """MATCHES operator works with regex."""
        condition = RuleCondition(
            field="name",
            operator=ConditionOperator.MATCHES,
            value=r"Phase\s+[IViv1-4]"
        )

        assert condition.evaluate({"name": "Phase I Clinical Trial"}) is True
        assert condition.evaluate({"name": "Phase 3 Study"}) is True
        assert condition.evaluate({"name": "Clinical Trial"}) is False

    def test_in_list_condition(self):
        """IN_LIST operator works correctly."""
        condition = RuleCondition(
            field="concept_type",
            operator=ConditionOperator.IN_LIST,
            value=["Product", "Platform", "Service"]
        )

        assert condition.evaluate({"concept_type": "Product"}) is True
        assert condition.evaluate({"concept_type": "Organization"}) is False

    def test_greater_than_condition(self):
        """GREATER_THAN operator works correctly."""
        condition = RuleCondition(
            field="confidence",
            operator=ConditionOperator.GREATER_THAN,
            value=0.8
        )

        assert condition.evaluate({"confidence": 0.9}) is True
        assert condition.evaluate({"confidence": 0.7}) is False

    def test_exists_condition(self):
        """EXISTS operator works correctly."""
        condition = RuleCondition(
            field="gxp_classification",
            operator=ConditionOperator.EXISTS,
            value=None
        )

        assert condition.evaluate({"gxp_classification": "GMP"}) is True
        assert condition.evaluate({"other_field": "value"}) is False

    def test_nested_field_access(self):
        """Supports nested field access with dot notation."""
        condition = RuleCondition(
            field="metadata.source",
            operator=ConditionOperator.EQUALS,
            value="fda"
        )

        assert condition.evaluate({"metadata": {"source": "FDA"}}) is True
        assert condition.evaluate({"metadata": {"source": "SAP"}}) is False

    def test_case_sensitive_option(self):
        """Case sensitive option works."""
        condition = RuleCondition(
            field="code",
            operator=ConditionOperator.EQUALS,
            value="ABC",
            case_sensitive=True
        )

        assert condition.evaluate({"code": "ABC"}) is True
        assert condition.evaluate({"code": "abc"}) is False


# =========================================================================
# Test: Rule Evaluation
# =========================================================================

class TestRuleEvaluation:
    """Tests for Rule evaluation."""

    def test_rule_matches_all_conditions(self):
        """Rule with match_all=True requires all conditions."""
        rule = Rule(
            rule_id="test-1",
            name="Test Rule",
            description="Test",
            rule_type=RuleType.CONCEPT_VALIDATION,
            conditions=[
                RuleCondition("domain", ConditionOperator.EQUALS, "SAP"),
                RuleCondition("concept_type", ConditionOperator.EQUALS, "Product")
            ],
            action=RuleAction.FLAG,
            match_all=True
        )

        # Both match
        result = rule.evaluate({"domain": "SAP", "concept_type": "Product"})
        assert result.matched is True

        # Only one matches
        result = rule.evaluate({"domain": "SAP", "concept_type": "Service"})
        assert result.matched is False

    def test_rule_matches_any_condition(self):
        """Rule with match_all=False requires any condition."""
        rule = Rule(
            rule_id="test-2",
            name="Test Rule OR",
            description="Test",
            rule_type=RuleType.CONCEPT_VALIDATION,
            conditions=[
                RuleCondition("domain", ConditionOperator.EQUALS, "FDA"),
                RuleCondition("domain", ConditionOperator.EQUALS, "EMA")
            ],
            action=RuleAction.FLAG,
            match_all=False
        )

        assert rule.evaluate({"domain": "FDA"}).matched is True
        assert rule.evaluate({"domain": "EMA"}).matched is True
        assert rule.evaluate({"domain": "SAP"}).matched is False

    def test_disabled_rule_skips(self):
        """Disabled rule returns SKIP action."""
        rule = Rule(
            rule_id="test-3",
            name="Disabled Rule",
            description="Test",
            rule_type=RuleType.CONCEPT_VALIDATION,
            conditions=[
                RuleCondition("domain", ConditionOperator.EQUALS, "SAP")
            ],
            action=RuleAction.FLAG,
            enabled=False
        )

        result = rule.evaluate({"domain": "SAP"})
        assert result.action == RuleAction.SKIP

    def test_rule_returns_enrichment_data(self):
        """Rule with ENRICH action returns enrichment data."""
        rule = Rule(
            rule_id="test-4",
            name="Enrich Rule",
            description="Test",
            rule_type=RuleType.CONCEPT_ENRICHMENT,
            conditions=[
                RuleCondition("domain", ConditionOperator.EQUALS, "Pharma")
            ],
            action=RuleAction.ENRICH,
            enrichment_data={"audit_required": True, "compliance_level": "high"}
        )

        result = rule.evaluate({"domain": "Pharma"})
        assert result.matched is True
        assert result.enrichment["audit_required"] is True
        assert result.enrichment["compliance_level"] == "high"


# =========================================================================
# Test: Business Rules Engine
# =========================================================================

class TestBusinessRulesEngine:
    """Tests for BusinessRulesEngine."""

    @pytest.fixture
    def engine(self):
        """Create engine with feature flag enabled."""
        with patch("knowbase.rules.engine.is_feature_enabled") as mock:
            mock.return_value = True
            return BusinessRulesEngine(tenant_id="default")

    def test_add_and_get_stats(self, engine):
        """Engine tracks added rules."""
        rule = Rule(
            rule_id="test-1",
            name="Test",
            description="",
            rule_type=RuleType.CONCEPT_VALIDATION,
            conditions=[RuleCondition("x", ConditionOperator.EQUALS, "y")],
            action=RuleAction.ACCEPT
        )

        engine.add_rule(rule)
        stats = engine.get_stats()

        assert stats["total_rules"] == 1
        assert stats["rules_count"]["concept_validation"] == 1

    def test_validate_concepts_applies_rules(self, engine):
        """validate_concepts applies validation rules."""
        rule = Rule(
            rule_id="flag-sap",
            name="Flag SAP",
            description="Flag SAP concepts",
            rule_type=RuleType.CONCEPT_VALIDATION,
            conditions=[RuleCondition("domain", ConditionOperator.EQUALS, "SAP")],
            action=RuleAction.FLAG,
            message="SAP concept flagged"
        )
        engine.add_rule(rule)

        concepts = [
            {"name": "S/4HANA", "domain": "SAP"},
            {"name": "Oracle ERP", "domain": "Oracle"}
        ]

        validated = engine.validate_concepts(concepts)

        # SAP concept should be flagged
        assert "_business_flags" in validated[0]
        assert validated[0]["_business_flags"][0]["rule_name"] == "Flag SAP"

        # Oracle concept should not be flagged
        assert "_business_flags" not in validated[1]

    def test_validate_concepts_rejects(self, engine):
        """validate_concepts can reject concepts."""
        rule = Rule(
            rule_id="reject-deprecated",
            name="Reject Deprecated",
            description="",
            rule_type=RuleType.CONCEPT_VALIDATION,
            conditions=[RuleCondition("status", ConditionOperator.EQUALS, "deprecated")],
            action=RuleAction.REJECT,
            message="Deprecated concept rejected"
        )
        engine.add_rule(rule)

        concepts = [{"name": "Old System", "status": "deprecated"}]
        validated = engine.validate_concepts(concepts)

        assert validated[0]["_rejected"] is True
        assert validated[0]["_rejection_reason"] == "Deprecated concept rejected"

    def test_enrich_concepts(self, engine):
        """enrich_concepts adds metadata."""
        rule = Rule(
            rule_id="enrich-pharma",
            name="Enrich Pharma",
            description="",
            rule_type=RuleType.CONCEPT_ENRICHMENT,
            conditions=[RuleCondition("domain", ConditionOperator.EQUALS, "Pharma")],
            action=RuleAction.ENRICH,
            enrichment_data={"compliance": "required", "audit_trail": True}
        )
        engine.add_rule(rule)

        concepts = [{"name": "Drug X", "domain": "Pharma"}]
        enriched = engine.enrich_concepts(concepts)

        assert "_business_metadata" in enriched[0]
        assert enriched[0]["_business_metadata"]["compliance"] == "required"

    def test_validate_relations_filters_rejected(self, engine):
        """validate_relations removes rejected relations."""
        rule = Rule(
            rule_id="reject-weak",
            name="Reject Weak Relations",
            description="",
            rule_type=RuleType.RELATION_VALIDATION,
            conditions=[
                RuleCondition("confidence", ConditionOperator.LESS_THAN, 0.5)
            ],
            action=RuleAction.REJECT,
            message="Low confidence relation rejected"
        )
        engine.add_rule(rule)

        relations = [
            {"id": "rel-1", "confidence": 0.9},
            {"id": "rel-2", "confidence": 0.3}
        ]

        validated = engine.validate_relations(relations)

        assert len(validated) == 1
        assert validated[0]["id"] == "rel-1"

    def test_rules_sorted_by_priority(self, engine):
        """Rules are applied in priority order."""
        # Lower priority = higher precedence
        rule_high = Rule(
            rule_id="high-priority",
            name="High Priority",
            description="",
            rule_type=RuleType.CONCEPT_VALIDATION,
            conditions=[RuleCondition("domain", ConditionOperator.EQUALS, "SAP")],
            action=RuleAction.ACCEPT,
            priority=10
        )
        rule_low = Rule(
            rule_id="low-priority",
            name="Low Priority",
            description="",
            rule_type=RuleType.CONCEPT_VALIDATION,
            conditions=[RuleCondition("domain", ConditionOperator.EQUALS, "SAP")],
            action=RuleAction.REJECT,
            priority=100
        )

        engine.add_rule(rule_low)
        engine.add_rule(rule_high)

        # High priority rule (ACCEPT) should be applied first
        concepts = [{"name": "Test", "domain": "SAP"}]
        validated = engine.validate_concepts(concepts)

        # Should NOT be rejected (high priority ACCEPT wins)
        assert "_rejected" not in validated[0]


# =========================================================================
# Test: Built-in Rules
# =========================================================================

class TestBuiltinRules:
    """Tests for built-in rule templates."""

    def test_pharma_rules_created(self):
        """Pharma compliance rules are created."""
        rules = create_pharma_compliance_rules()

        assert len(rules) >= 3
        assert any(r.rule_id == "pharma-001" for r in rules)
        assert any(r.rule_id == "pharma-002" for r in rules)

    def test_sap_rules_created(self):
        """SAP validation rules are created."""
        rules = create_sap_validation_rules()

        assert len(rules) >= 2
        assert any(r.rule_id == "sap-001" for r in rules)
        assert any(r.rule_id == "sap-002" for r in rules)

    def test_pharma_fda_rule_flags(self):
        """Pharma FDA rule flags regulatory terms."""
        rules = create_pharma_compliance_rules()
        fda_rule = next(r for r in rules if r.rule_id == "pharma-001")

        result = fda_rule.evaluate({"domain": "FDA"})

        assert result.matched is True
        assert result.action == RuleAction.REQUIRE_REVIEW

    def test_sap_ecc_rule_flags(self):
        """SAP ECC rule flags migration context."""
        rules = create_sap_validation_rules()
        ecc_rule = next(r for r in rules if r.rule_id == "sap-002")

        result = ecc_rule.evaluate({"canonical_name": "SAP ECC 6.0"})

        assert result.matched is True
        assert result.action == RuleAction.FLAG


# =========================================================================
# Test: Rules Loader
# =========================================================================

class TestRulesLoader:
    """Tests for RulesLoader."""

    @pytest.fixture
    def temp_rules_dir(self):
        """Create temporary rules directory."""
        with tempfile.TemporaryDirectory() as tmpdir:
            yield Path(tmpdir)

    def test_load_from_yaml_file(self, temp_rules_dir):
        """Loads rules from YAML file."""
        # Create test YAML file
        rules_yaml = {
            "rules": [
                {
                    "id": "yaml-rule-1",
                    "name": "Test YAML Rule",
                    "description": "Test rule from YAML",
                    "type": "concept_validation",
                    "action": "flag",
                    "priority": 50,
                    "conditions": [
                        {
                            "field": "domain",
                            "operator": "equals",
                            "value": "Test"
                        }
                    ],
                    "message": "Test flag"
                }
            ]
        }

        yaml_path = temp_rules_dir / "test_rules.yaml"
        with open(yaml_path, "w") as f:
            yaml.dump(rules_yaml, f)

        loader = RulesLoader(str(temp_rules_dir))
        rules = loader._load_from_file(yaml_path)

        assert len(rules) == 1
        assert rules[0].rule_id == "yaml-rule-1"
        assert rules[0].name == "Test YAML Rule"
        assert rules[0].action == RuleAction.FLAG

    def test_load_rules_for_tenant(self, temp_rules_dir):
        """Loads all rules for a tenant."""
        loader = RulesLoader(str(temp_rules_dir))

        # Load with builtins only (no files)
        rules = loader.load_rules_for_tenant(
            "pharma_tenant",
            include_global=False,
            include_builtins=True
        )

        # Should include pharma rules
        assert len(rules) > 0
        assert any("pharma" in r.rule_id for r in rules)

    def test_save_and_load_rules(self, temp_rules_dir):
        """Can save and reload rules."""
        loader = RulesLoader(str(temp_rules_dir))

        original_rules = [
            Rule(
                rule_id="save-test-1",
                name="Save Test",
                description="Test saving",
                rule_type=RuleType.CONCEPT_VALIDATION,
                conditions=[
                    RuleCondition("field", ConditionOperator.EQUALS, "value")
                ],
                action=RuleAction.ACCEPT,
                priority=25
            )
        ]

        # Save
        save_path = temp_rules_dir / "saved_rules.yaml"
        success = loader.save_rules_to_file(original_rules, save_path)
        assert success is True

        # Load
        loaded_rules = loader._load_from_file(save_path)
        assert len(loaded_rules) == 1
        assert loaded_rules[0].rule_id == "save-test-1"
        assert loaded_rules[0].priority == 25


# =========================================================================
# Test: Feature Flag Integration
# =========================================================================

class TestFeatureFlagIntegration:
    """Tests for feature flag integration."""

    def test_engine_disabled_passes_through(self):
        """Disabled engine passes data through unchanged."""
        with patch("knowbase.rules.engine.is_feature_enabled") as mock:
            mock.return_value = False
            engine = BusinessRulesEngine(tenant_id="default")

        # Add a rule that would normally flag
        rule = Rule(
            rule_id="test",
            name="Test",
            description="",
            rule_type=RuleType.CONCEPT_VALIDATION,
            conditions=[RuleCondition("x", ConditionOperator.EQUALS, "y")],
            action=RuleAction.FLAG
        )
        engine.add_rule(rule)

        concepts = [{"x": "y"}]
        result = engine.validate_concepts(concepts)

        # Should pass through unchanged (no flags)
        assert "_business_flags" not in result[0]


# =========================================================================
# Test: Integration with Engine
# =========================================================================

class TestEngineIntegration:
    """Integration tests for full engine workflow."""

    def test_full_workflow(self):
        """Complete workflow: load rules, validate, enrich."""
        with patch("knowbase.rules.engine.is_feature_enabled") as mock:
            mock.return_value = True
            engine = BusinessRulesEngine(tenant_id="pharma_tenant")

        # Add pharma rules
        for rule in create_pharma_compliance_rules():
            engine.add_rule(rule)

        # Test concepts
        concepts = [
            {"name": "IND Application", "domain": "FDA"},
            {"name": "Phase II Clinical Trial", "canonical_name": "Phase II Study"},
            {"name": "SAP Module", "domain": "SAP"}
        ]

        # Validate
        validated = engine.validate_concepts(concepts)

        # FDA concept should require review
        assert validated[0].get("_require_review") is True

        # Phase II should be enriched (if enrichment rules added)
        # SAP should pass through


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
