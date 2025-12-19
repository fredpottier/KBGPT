"""
KnowWhere Business Rules Engine

Phase 1.8.4: Moteur de règles métier custom par tenant.
Différenciateur marché vs Microsoft Copilot / Google Gemini.

Usage:
    from knowbase.rules import BusinessRulesEngine, RuleType

    engine = BusinessRulesEngine(tenant_id="pharma_tenant")
    validated = engine.validate_concepts(concepts)
    enriched = engine.enrich_relations(relations)
"""

from .engine import (
    BusinessRulesEngine,
    Rule,
    RuleType,
    RuleAction,
    RuleCondition,
    RuleResult
)
from .loader import RulesLoader

__all__ = [
    "BusinessRulesEngine",
    "Rule",
    "RuleType",
    "RuleAction",
    "RuleCondition",
    "RuleResult",
    "RulesLoader"
]
