"""
Phase 1.8.4 - Business Rules Engine

Moteur de règles métier custom par tenant.
Permet validation et enrichissement selon règles configurables.

Architecture:
1. Rules: Définition déclarative (YAML/JSON)
2. Conditions: Matchers flexibles (regex, domain, type, etc.)
3. Actions: Validate, Enrich, Flag, Skip
4. Engine: Exécution prioritisée des règles

Différenciateur vs Copilot/Gemini: Customisation métier profonde.
"""

import logging
import re
from typing import List, Dict, Any, Optional, Callable
from dataclasses import dataclass, field
from enum import Enum
from datetime import datetime

from knowbase.config.feature_flags import is_feature_enabled, get_feature_config

logger = logging.getLogger(__name__)


# =========================================================================
# Types and Enums
# =========================================================================

class RuleType(Enum):
    """Types de règles métier."""
    CONCEPT_VALIDATION = "concept_validation"
    CONCEPT_ENRICHMENT = "concept_enrichment"
    RELATION_VALIDATION = "relation_validation"
    RELATION_ENRICHMENT = "relation_enrichment"
    DOCUMENT_CLASSIFICATION = "document_classification"
    ENTITY_NORMALIZATION = "entity_normalization"


class RuleAction(Enum):
    """Actions possibles pour une règle."""
    ACCEPT = "accept"           # Accepter l'élément
    REJECT = "reject"           # Rejeter l'élément
    FLAG = "flag"               # Marquer pour review
    ENRICH = "enrich"           # Enrichir avec metadata
    TRANSFORM = "transform"     # Transformer la valeur
    SKIP = "skip"               # Passer sans traitement
    REQUIRE_REVIEW = "require_review"  # Requiert validation humaine


class ConditionOperator(Enum):
    """Opérateurs pour conditions de règles."""
    EQUALS = "equals"
    NOT_EQUALS = "not_equals"
    CONTAINS = "contains"
    NOT_CONTAINS = "not_contains"
    MATCHES = "matches"         # Regex match
    IN_LIST = "in_list"
    NOT_IN_LIST = "not_in_list"
    GREATER_THAN = "greater_than"
    LESS_THAN = "less_than"
    EXISTS = "exists"
    NOT_EXISTS = "not_exists"


@dataclass
class RuleCondition:
    """Condition pour déclencher une règle."""
    field: str                              # Champ à évaluer (ex: "domain", "concept_type")
    operator: ConditionOperator             # Opérateur de comparaison
    value: Any                              # Valeur à comparer
    case_sensitive: bool = False            # Sensibilité casse

    def evaluate(self, data: Dict[str, Any]) -> bool:
        """
        Évalue la condition sur les données fournies.

        Args:
            data: Dictionnaire avec les données à évaluer

        Returns:
            True si condition satisfaite
        """
        field_value = self._get_nested_value(data, self.field)

        # Normaliser pour comparaison case-insensitive
        if not self.case_sensitive and isinstance(field_value, str):
            field_value = field_value.lower()
        if not self.case_sensitive and isinstance(self.value, str):
            compare_value = self.value.lower()
        else:
            compare_value = self.value

        # Évaluer selon opérateur
        if self.operator == ConditionOperator.EQUALS:
            return field_value == compare_value

        elif self.operator == ConditionOperator.NOT_EQUALS:
            return field_value != compare_value

        elif self.operator == ConditionOperator.CONTAINS:
            if isinstance(field_value, str):
                return compare_value in field_value
            elif isinstance(field_value, list):
                return compare_value in field_value
            return False

        elif self.operator == ConditionOperator.NOT_CONTAINS:
            if isinstance(field_value, str):
                return compare_value not in field_value
            elif isinstance(field_value, list):
                return compare_value not in field_value
            return True

        elif self.operator == ConditionOperator.MATCHES:
            if isinstance(field_value, str):
                pattern = re.compile(str(self.value), re.IGNORECASE if not self.case_sensitive else 0)
                return bool(pattern.search(field_value))
            return False

        elif self.operator == ConditionOperator.IN_LIST:
            if isinstance(compare_value, list):
                return field_value in compare_value
            return False

        elif self.operator == ConditionOperator.NOT_IN_LIST:
            if isinstance(compare_value, list):
                return field_value not in compare_value
            return True

        elif self.operator == ConditionOperator.GREATER_THAN:
            try:
                return float(field_value) > float(compare_value)
            except (TypeError, ValueError):
                return False

        elif self.operator == ConditionOperator.LESS_THAN:
            try:
                return float(field_value) < float(compare_value)
            except (TypeError, ValueError):
                return False

        elif self.operator == ConditionOperator.EXISTS:
            return field_value is not None

        elif self.operator == ConditionOperator.NOT_EXISTS:
            return field_value is None

        return False

    def _get_nested_value(self, data: Dict[str, Any], field_path: str) -> Any:
        """Get value from nested dict using dot notation."""
        parts = field_path.split(".")
        value = data

        for part in parts:
            if isinstance(value, dict) and part in value:
                value = value[part]
            else:
                return None

        return value


@dataclass
class RuleResult:
    """Résultat de l'application d'une règle."""
    rule_id: str
    rule_name: str
    action: RuleAction
    matched: bool
    message: str = ""
    enrichment: Dict[str, Any] = field(default_factory=dict)
    transformed_value: Any = None


@dataclass
class Rule:
    """Définition d'une règle métier."""
    rule_id: str
    name: str
    description: str
    rule_type: RuleType
    conditions: List[RuleCondition]
    action: RuleAction
    priority: int = 100                     # Plus bas = plus prioritaire
    enabled: bool = True
    tenant_id: str = "default"              # Tenant spécifique ou "default"
    enrichment_data: Dict[str, Any] = field(default_factory=dict)
    message: str = ""                       # Message pour flag/reject
    match_all: bool = True                  # True = AND, False = OR

    def evaluate(self, data: Dict[str, Any]) -> RuleResult:
        """
        Évalue la règle sur les données.

        Args:
            data: Données à évaluer

        Returns:
            RuleResult avec action et metadata
        """
        if not self.enabled:
            return RuleResult(
                rule_id=self.rule_id,
                rule_name=self.name,
                action=RuleAction.SKIP,
                matched=False,
                message="Rule disabled"
            )

        # Évaluer conditions
        if self.match_all:
            # AND: Toutes les conditions doivent matcher
            matched = all(cond.evaluate(data) for cond in self.conditions)
        else:
            # OR: Au moins une condition doit matcher
            matched = any(cond.evaluate(data) for cond in self.conditions)

        if matched:
            return RuleResult(
                rule_id=self.rule_id,
                rule_name=self.name,
                action=self.action,
                matched=True,
                message=self.message,
                enrichment=self.enrichment_data
            )
        else:
            return RuleResult(
                rule_id=self.rule_id,
                rule_name=self.name,
                action=RuleAction.SKIP,
                matched=False,
                message=""
            )


# =========================================================================
# Business Rules Engine
# =========================================================================

class BusinessRulesEngine:
    """
    Moteur de règles métier pour KnowWhere.

    Phase 1.8.4: Customisation métier par tenant.

    Usage:
        engine = BusinessRulesEngine(tenant_id="pharma_tenant")
        engine.load_rules()  # Charge règles depuis config

        # Validation concepts
        results = engine.validate_concepts(concepts)

        # Enrichissement relations
        enriched = engine.enrich_relations(relations)
    """

    def __init__(self, tenant_id: str = "default"):
        """
        Initialize Business Rules Engine.

        Args:
            tenant_id: Tenant for loading specific rules
        """
        self.tenant_id = tenant_id
        self.rules: Dict[RuleType, List[Rule]] = {rt: [] for rt in RuleType}
        self._load_config()

        logger.info(
            f"[OSMOSE:BusinessRulesEngine] Initialized for tenant={tenant_id}"
        )

    def _load_config(self):
        """Load configuration from feature flags."""
        self.enabled = is_feature_enabled(
            "enable_business_rules_engine",
            self.tenant_id,
            default=False
        )

    def add_rule(self, rule: Rule):
        """
        Add a rule to the engine.

        Args:
            rule: Rule to add
        """
        if rule.tenant_id not in ["default", self.tenant_id]:
            logger.debug(
                f"[BusinessRulesEngine] Skipping rule {rule.rule_id} "
                f"(tenant mismatch: {rule.tenant_id} != {self.tenant_id})"
            )
            return

        self.rules[rule.rule_type].append(rule)
        # Sort by priority
        self.rules[rule.rule_type].sort(key=lambda r: r.priority)

        logger.debug(
            f"[BusinessRulesEngine] Added rule '{rule.name}' "
            f"(type={rule.rule_type.value}, priority={rule.priority})"
        )

    def clear_rules(self, rule_type: Optional[RuleType] = None):
        """Clear rules (optionally by type)."""
        if rule_type:
            self.rules[rule_type] = []
        else:
            self.rules = {rt: [] for rt in RuleType}

    def validate_concepts(
        self,
        concepts: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """
        Validate concepts against business rules.

        Args:
            concepts: List of concepts to validate

        Returns:
            Validated concepts (may have flags/enrichment)
        """
        if not self.enabled:
            return concepts

        rules = self.rules[RuleType.CONCEPT_VALIDATION]
        if not rules:
            return concepts

        validated = []
        for concept in concepts:
            result = self._apply_rules(concept, rules)
            concept = self._process_result(concept, result)
            validated.append(concept)

        logger.info(
            f"[BusinessRulesEngine] Validated {len(concepts)} concepts "
            f"with {len(rules)} rules"
        )

        return validated

    def enrich_concepts(
        self,
        concepts: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """
        Enrich concepts with business metadata.

        Args:
            concepts: List of concepts to enrich

        Returns:
            Enriched concepts
        """
        if not self.enabled:
            return concepts

        rules = self.rules[RuleType.CONCEPT_ENRICHMENT]
        if not rules:
            return concepts

        enriched = []
        for concept in concepts:
            result = self._apply_rules(concept, rules)
            concept = self._process_enrichment(concept, result)
            enriched.append(concept)

        return enriched

    def validate_relations(
        self,
        relations: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """
        Validate relations against business rules.

        Args:
            relations: List of relations to validate

        Returns:
            Validated relations
        """
        if not self.enabled:
            return relations

        rules = self.rules[RuleType.RELATION_VALIDATION]
        if not rules:
            return relations

        validated = []
        for relation in relations:
            result = self._apply_rules(relation, rules)
            relation = self._process_result(relation, result)

            # Skip rejected relations
            if result.action != RuleAction.REJECT:
                validated.append(relation)

        rejected_count = len(relations) - len(validated)
        if rejected_count > 0:
            logger.info(
                f"[BusinessRulesEngine] Rejected {rejected_count} relations "
                f"via business rules"
            )

        return validated

    def enrich_relations(
        self,
        relations: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """
        Enrich relations with business metadata.

        Args:
            relations: List of relations to enrich

        Returns:
            Enriched relations
        """
        if not self.enabled:
            return relations

        rules = self.rules[RuleType.RELATION_ENRICHMENT]
        if not rules:
            return relations

        enriched = []
        for relation in relations:
            result = self._apply_rules(relation, rules)
            relation = self._process_enrichment(relation, result)
            enriched.append(relation)

        return enriched

    def classify_document(
        self,
        document: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Classify document type using business rules.

        Args:
            document: Document metadata to classify

        Returns:
            Document with classification
        """
        if not self.enabled:
            return document

        rules = self.rules[RuleType.DOCUMENT_CLASSIFICATION]
        if not rules:
            return document

        result = self._apply_rules(document, rules)
        return self._process_enrichment(document, result)

    def _apply_rules(
        self,
        data: Dict[str, Any],
        rules: List[Rule]
    ) -> RuleResult:
        """
        Apply rules to data (stop at first match).

        Args:
            data: Data to evaluate
            rules: Rules to apply (already sorted by priority)

        Returns:
            Result from first matching rule
        """
        for rule in rules:
            result = rule.evaluate(data)
            if result.matched:
                logger.debug(
                    f"[BusinessRulesEngine] Rule '{rule.name}' matched: "
                    f"action={result.action.value}"
                )
                return result

        # No rule matched
        return RuleResult(
            rule_id="",
            rule_name="",
            action=RuleAction.ACCEPT,
            matched=False
        )

    def _process_result(
        self,
        data: Dict[str, Any],
        result: RuleResult
    ) -> Dict[str, Any]:
        """Process validation result (add flags, etc.)."""
        if not result.matched:
            return data

        if result.action == RuleAction.FLAG:
            data["_business_flags"] = data.get("_business_flags", [])
            data["_business_flags"].append({
                "rule_id": result.rule_id,
                "rule_name": result.rule_name,
                "message": result.message
            })

        elif result.action == RuleAction.REQUIRE_REVIEW:
            data["_require_review"] = True
            data["_review_reason"] = result.message

        elif result.action == RuleAction.REJECT:
            data["_rejected"] = True
            data["_rejection_reason"] = result.message

        return data

    def _process_enrichment(
        self,
        data: Dict[str, Any],
        result: RuleResult
    ) -> Dict[str, Any]:
        """Process enrichment result (add metadata)."""
        if not result.matched:
            return data

        if result.action == RuleAction.ENRICH and result.enrichment:
            data["_business_metadata"] = data.get("_business_metadata", {})
            data["_business_metadata"].update(result.enrichment)

        elif result.action == RuleAction.TRANSFORM and result.transformed_value:
            # Store original and transformed
            data["_original_value"] = data.get("value")
            data["value"] = result.transformed_value

        return data

    def get_stats(self) -> Dict[str, Any]:
        """Get engine statistics."""
        return {
            "tenant_id": self.tenant_id,
            "enabled": self.enabled,
            "rules_count": {
                rt.value: len(rules) for rt, rules in self.rules.items()
            },
            "total_rules": sum(len(rules) for rules in self.rules.values())
        }


# =========================================================================
# Pre-built Rule Factories
# =========================================================================

def create_pharma_compliance_rules() -> List[Rule]:
    """
    Create pre-built pharma compliance rules.

    Returns:
        List of pharma-specific business rules
    """
    rules = []

    # Rule 1: Flag FDA regulatory terms for review
    rules.append(Rule(
        rule_id="pharma-001",
        name="FDA Regulatory Term Review",
        description="Flag FDA regulatory terms for compliance review",
        rule_type=RuleType.CONCEPT_VALIDATION,
        conditions=[
            RuleCondition(
                field="domain",
                operator=ConditionOperator.EQUALS,
                value="FDA"
            )
        ],
        action=RuleAction.REQUIRE_REVIEW,
        priority=10,
        tenant_id="default",
        message="FDA regulatory term requires compliance review"
    ))

    # Rule 2: Enrich clinical trial concepts with phase info
    rules.append(Rule(
        rule_id="pharma-002",
        name="Clinical Trial Phase Detection",
        description="Enrich clinical trial concepts with phase classification",
        rule_type=RuleType.CONCEPT_ENRICHMENT,
        conditions=[
            RuleCondition(
                field="canonical_name",
                operator=ConditionOperator.MATCHES,
                value=r"Phase\s+[IViv1-4]"
            )
        ],
        action=RuleAction.ENRICH,
        priority=20,
        enrichment_data={
            "regulatory_category": "clinical_trial",
            "requires_audit_trail": True
        }
    ))

    # Rule 3: Reject concepts without GxP classification
    rules.append(Rule(
        rule_id="pharma-003",
        name="GxP Classification Required",
        description="Reject quality concepts without GxP classification",
        rule_type=RuleType.CONCEPT_VALIDATION,
        conditions=[
            RuleCondition(
                field="domain",
                operator=ConditionOperator.EQUALS,
                value="Quality"
            ),
            RuleCondition(
                field="gxp_classification",
                operator=ConditionOperator.NOT_EXISTS,
                value=None
            )
        ],
        action=RuleAction.FLAG,
        priority=30,
        message="Quality concept requires GxP classification"
    ))

    # Rule 4: Flag deprecated regulatory terms
    rules.append(Rule(
        rule_id="pharma-004",
        name="Deprecated Term Detection",
        description="Flag deprecated regulatory terminology",
        rule_type=RuleType.CONCEPT_VALIDATION,
        conditions=[
            RuleCondition(
                field="canonical_name",
                operator=ConditionOperator.IN_LIST,
                value=["EMEA", "21 CFR Part 820", "ICH E6"]  # Old versions
            )
        ],
        action=RuleAction.FLAG,
        priority=40,
        message="Term may be deprecated, verify current terminology"
    ))

    return rules


def create_sap_validation_rules() -> List[Rule]:
    """
    Create pre-built SAP validation rules.

    Returns:
        List of SAP-specific business rules
    """
    rules = []

    # Rule 1: Enrich SAP products with lifecycle info
    rules.append(Rule(
        rule_id="sap-001",
        name="SAP Product Lifecycle",
        description="Enrich SAP products with lifecycle status",
        rule_type=RuleType.CONCEPT_ENRICHMENT,
        conditions=[
            RuleCondition(
                field="domain",
                operator=ConditionOperator.EQUALS,
                value="SAP"
            ),
            RuleCondition(
                field="concept_type",
                operator=ConditionOperator.EQUALS,
                value="Product"
            )
        ],
        action=RuleAction.ENRICH,
        priority=10,
        enrichment_data={
            "vendor": "SAP SE",
            "support_required": True
        }
    ))

    # Rule 2: Flag ECC mentions (being replaced by S/4HANA)
    rules.append(Rule(
        rule_id="sap-002",
        name="ECC Migration Alert",
        description="Flag ECC references for S/4HANA migration context",
        rule_type=RuleType.CONCEPT_VALIDATION,
        conditions=[
            RuleCondition(
                field="canonical_name",
                operator=ConditionOperator.CONTAINS,
                value="ECC"
            )
        ],
        action=RuleAction.FLAG,
        priority=20,
        message="ECC reference detected - consider S/4HANA migration context"
    ))

    # Rule 3: Validate integration patterns
    rules.append(Rule(
        rule_id="sap-003",
        name="Integration Pattern Validation",
        description="Validate SAP integration relations",
        rule_type=RuleType.RELATION_VALIDATION,
        conditions=[
            RuleCondition(
                field="relation_type",
                operator=ConditionOperator.EQUALS,
                value="INTEGRATES_WITH"
            ),
            RuleCondition(
                field="source_domain",
                operator=ConditionOperator.EQUALS,
                value="SAP"
            )
        ],
        action=RuleAction.REQUIRE_REVIEW,
        priority=30,
        message="SAP integration requires architecture review"
    ))

    return rules
