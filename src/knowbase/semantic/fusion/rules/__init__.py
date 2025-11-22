"""
🌊 OSMOSE Semantic Intelligence - Fusion Rules

Phase 1.8.1d: Règles concrètes de fusion de concepts.

MVP (3 règles):
1. MainEntitiesMergeRule: Fusionner entités principales répétées
2. AlternativesFeaturesRule: Détecter alternatives/opposés (créer relations)
3. SlideSpecificPreserveRule: Préserver détails slide-specific

Usage:
    from knowbase.semantic.fusion.rules import MainEntitiesMergeRule

    rule = MainEntitiesMergeRule(config)
    result = await rule.apply(concepts, context)
"""

from .main_entities import MainEntitiesMergeRule
from .alternatives import AlternativesFeaturesRule
from .slide_specific import SlideSpecificPreserveRule

__all__ = [
    "MainEntitiesMergeRule",
    "AlternativesFeaturesRule",
    "SlideSpecificPreserveRule",
]
