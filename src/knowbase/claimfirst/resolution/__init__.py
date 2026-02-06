# src/knowbase/claimfirst/resolution/__init__.py
"""
Module de résolution de sujets.

- SubjectResolver (v1): Résolution conservative INV-9
- SubjectResolverV2: Résolution domain-agnostic INV-25 avec ComparableSubject
"""

from knowbase.claimfirst.resolution.subject_resolver import (
    SubjectResolver,
    ResolverResult,
)
from knowbase.claimfirst.resolution.subject_resolver_v2 import (
    SubjectResolverV2,
    SYSTEM_PROMPT_V2,
    USER_PROMPT_TEMPLATE,
)

__all__ = [
    # V1 - Conservative resolution (INV-9)
    "SubjectResolver",
    "ResolverResult",
    # V2 - Domain-agnostic with ComparableSubject (INV-25)
    "SubjectResolverV2",
    "SYSTEM_PROMPT_V2",
    "USER_PROMPT_TEMPLATE",
]
