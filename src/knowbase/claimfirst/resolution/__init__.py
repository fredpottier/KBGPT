# src/knowbase/claimfirst/resolution/__init__.py
"""
Module de résolution de sujets (INV-9).

Résolution conservative des sujets - Anti-Hallucination Alias.
"""

from knowbase.claimfirst.resolution.subject_resolver import (
    SubjectResolver,
    ResolverResult,
)

__all__ = [
    "SubjectResolver",
    "ResolverResult",
]
