"""
Phase 1.8.4 - Business Rules Loader

Charge les règles métier depuis fichiers YAML/JSON.
Supporte règles globales et tenant-spécifiques.

Structure fichiers:
  config/rules/
  ├── global_rules.yaml       # Règles pour tous tenants
  ├── pharma_rules.yaml       # Règles pharma
  └── tenant_{id}/            # Règles tenant-spécifiques
      └── custom_rules.yaml
"""

import logging
import yaml
import json
from pathlib import Path
from typing import List, Dict, Any, Optional

from .engine import (
    Rule,
    RuleType,
    RuleAction,
    RuleCondition,
    ConditionOperator,
    BusinessRulesEngine,
    create_pharma_compliance_rules,
    create_sap_validation_rules
)

logger = logging.getLogger(__name__)


class RulesLoader:
    """
    Loader for business rules from config files.

    Supports:
    - YAML and JSON formats
    - Global rules (all tenants)
    - Tenant-specific rules
    - Built-in rule templates (pharma, SAP)
    """

    def __init__(self, config_path: str = "config/rules"):
        """
        Initialize RulesLoader.

        Args:
            config_path: Path to rules configuration directory
        """
        self.config_path = Path(config_path)
        self.config_path.mkdir(parents=True, exist_ok=True)

        logger.info(
            f"[OSMOSE:RulesLoader] Initialized (path={self.config_path})"
        )

    def load_rules_for_tenant(
        self,
        tenant_id: str,
        include_global: bool = True,
        include_builtins: bool = True
    ) -> List[Rule]:
        """
        Load all rules for a tenant.

        Args:
            tenant_id: Tenant ID
            include_global: Include global rules
            include_builtins: Include built-in rule templates

        Returns:
            List of all applicable rules
        """
        rules = []

        # 1. Load built-in rules if enabled
        if include_builtins:
            rules.extend(self._load_builtin_rules(tenant_id))

        # 2. Load global rules
        if include_global:
            global_rules = self._load_from_file(self.config_path / "global_rules.yaml")
            rules.extend(global_rules)

        # 3. Load domain-specific rules
        domain_files = [
            "pharma_rules.yaml",
            "sap_rules.yaml",
            "crm_rules.yaml"
        ]
        for domain_file in domain_files:
            domain_path = self.config_path / domain_file
            if domain_path.exists():
                domain_rules = self._load_from_file(domain_path)
                # Filter for matching tenant
                domain_rules = [
                    r for r in domain_rules
                    if r.tenant_id in ["default", tenant_id]
                ]
                rules.extend(domain_rules)

        # 4. Load tenant-specific rules
        tenant_path = self.config_path / f"tenant_{tenant_id}"
        if tenant_path.exists():
            for rule_file in tenant_path.glob("*.yaml"):
                tenant_rules = self._load_from_file(rule_file)
                rules.extend(tenant_rules)
            for rule_file in tenant_path.glob("*.json"):
                tenant_rules = self._load_from_file(rule_file)
                rules.extend(tenant_rules)

        # Sort by priority
        rules.sort(key=lambda r: r.priority)

        logger.info(
            f"[RulesLoader] Loaded {len(rules)} rules for tenant={tenant_id}"
        )

        return rules

    def _load_builtin_rules(self, tenant_id: str) -> List[Rule]:
        """Load built-in rule templates based on tenant profile."""
        rules = []

        # Detect tenant type from ID
        if "pharma" in tenant_id.lower():
            rules.extend(create_pharma_compliance_rules())
            logger.debug(f"[RulesLoader] Added pharma compliance rules")

        if "sap" in tenant_id.lower() or tenant_id == "default":
            rules.extend(create_sap_validation_rules())
            logger.debug(f"[RulesLoader] Added SAP validation rules")

        return rules

    def _load_from_file(self, file_path: Path) -> List[Rule]:
        """
        Load rules from a YAML or JSON file.

        Args:
            file_path: Path to rules file

        Returns:
            List of parsed rules
        """
        if not file_path.exists():
            return []

        try:
            with open(file_path, "r", encoding="utf-8") as f:
                if file_path.suffix in [".yaml", ".yml"]:
                    data = yaml.safe_load(f) or {}
                elif file_path.suffix == ".json":
                    data = json.load(f)
                else:
                    logger.warning(f"[RulesLoader] Unsupported file format: {file_path}")
                    return []

            rules_data = data.get("rules", [])
            rules = [self._parse_rule(rd) for rd in rules_data]
            rules = [r for r in rules if r is not None]

            logger.debug(
                f"[RulesLoader] Loaded {len(rules)} rules from {file_path.name}"
            )

            return rules

        except Exception as e:
            logger.error(f"[RulesLoader] Error loading {file_path}: {e}")
            return []

    def _parse_rule(self, rule_data: Dict[str, Any]) -> Optional[Rule]:
        """
        Parse rule data dict into Rule object.

        Args:
            rule_data: Raw rule data from config

        Returns:
            Parsed Rule or None if invalid
        """
        try:
            # Parse rule type
            rule_type = RuleType(rule_data.get("type", "concept_validation"))

            # Parse action
            action = RuleAction(rule_data.get("action", "accept"))

            # Parse conditions
            conditions = []
            for cond_data in rule_data.get("conditions", []):
                condition = self._parse_condition(cond_data)
                if condition:
                    conditions.append(condition)

            if not conditions:
                logger.warning(
                    f"[RulesLoader] Rule '{rule_data.get('name')}' has no valid conditions"
                )
                return None

            # Create rule
            rule = Rule(
                rule_id=rule_data.get("id", f"rule-{hash(rule_data.get('name', ''))}"),
                name=rule_data.get("name", "Unnamed Rule"),
                description=rule_data.get("description", ""),
                rule_type=rule_type,
                conditions=conditions,
                action=action,
                priority=rule_data.get("priority", 100),
                enabled=rule_data.get("enabled", True),
                tenant_id=rule_data.get("tenant_id", "default"),
                enrichment_data=rule_data.get("enrichment", {}),
                message=rule_data.get("message", ""),
                match_all=rule_data.get("match_all", True)
            )

            return rule

        except Exception as e:
            logger.error(
                f"[RulesLoader] Error parsing rule '{rule_data.get('name')}': {e}"
            )
            return None

    def _parse_condition(self, cond_data: Dict[str, Any]) -> Optional[RuleCondition]:
        """
        Parse condition data into RuleCondition.

        Args:
            cond_data: Raw condition data

        Returns:
            Parsed RuleCondition or None
        """
        try:
            operator = ConditionOperator(cond_data.get("operator", "equals"))

            return RuleCondition(
                field=cond_data.get("field", ""),
                operator=operator,
                value=cond_data.get("value"),
                case_sensitive=cond_data.get("case_sensitive", False)
            )

        except Exception as e:
            logger.error(f"[RulesLoader] Error parsing condition: {e}")
            return None

    def save_rules_to_file(
        self,
        rules: List[Rule],
        file_path: Path,
        format: str = "yaml"
    ) -> bool:
        """
        Save rules to a file.

        Args:
            rules: Rules to save
            file_path: Output file path
            format: "yaml" or "json"

        Returns:
            True if successful
        """
        try:
            # Convert rules to dicts
            rules_data = []
            for rule in rules:
                rule_dict = {
                    "id": rule.rule_id,
                    "name": rule.name,
                    "description": rule.description,
                    "type": rule.rule_type.value,
                    "action": rule.action.value,
                    "priority": rule.priority,
                    "enabled": rule.enabled,
                    "tenant_id": rule.tenant_id,
                    "message": rule.message,
                    "match_all": rule.match_all,
                    "conditions": [
                        {
                            "field": c.field,
                            "operator": c.operator.value,
                            "value": c.value,
                            "case_sensitive": c.case_sensitive
                        }
                        for c in rule.conditions
                    ],
                    "enrichment": rule.enrichment_data
                }
                rules_data.append(rule_dict)

            output = {"rules": rules_data}

            file_path.parent.mkdir(parents=True, exist_ok=True)

            with open(file_path, "w", encoding="utf-8") as f:
                if format == "yaml":
                    yaml.dump(output, f, default_flow_style=False, allow_unicode=True)
                else:
                    json.dump(output, f, indent=2, ensure_ascii=False)

            logger.info(f"[RulesLoader] Saved {len(rules)} rules to {file_path}")
            return True

        except Exception as e:
            logger.error(f"[RulesLoader] Error saving rules: {e}")
            return False


def load_engine_with_rules(tenant_id: str) -> BusinessRulesEngine:
    """
    Convenience function to create engine with loaded rules.

    Args:
        tenant_id: Tenant ID

    Returns:
        Configured BusinessRulesEngine
    """
    engine = BusinessRulesEngine(tenant_id=tenant_id)
    loader = RulesLoader()

    rules = loader.load_rules_for_tenant(tenant_id)
    for rule in rules:
        engine.add_rule(rule)

    return engine
