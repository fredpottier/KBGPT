"""
Enums partagés pour la classification des contradictions.

Utilisé par contradiction_classifier.py et contradiction_rules.py.
"""

from __future__ import annotations

from enum import Enum


class TensionNature(str, Enum):
    VALUE_CONFLICT = "value_conflict"
    SCOPE_CONFLICT = "scope_conflict"
    TEMPORAL_CONFLICT = "temporal_conflict"
    METHODOLOGICAL = "methodological"
    COMPLEMENTARY = "complementary"
    UNKNOWN = "unknown"


class TensionLevel(str, Enum):
    HARD = "hard"
    SOFT = "soft"
    NONE = "none"
    UNKNOWN = "unknown"
