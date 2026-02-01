"""
OSMOSE Pipeline V2 - Module Governance
======================================
Ref: doc/ongoing/PLAN_FIX_CONCEPT_ASPIRATEUR.md

Module de gouvernance pour le pipeline d'extraction.
Inclut les vérifications post-import et les linters de qualité.
"""

from .theme_lint import (
    ThemeLintIssue,
    ThemeLintChecker,
)

__all__ = [
    "ThemeLintIssue",
    "ThemeLintChecker",
]
