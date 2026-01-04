"""
Cache versionné pour Extraction V2.

Format cache v2 avec versioning explicite.
Invalidation automatique si version incompatible.
"""

from knowbase.extraction_v2.cache.versioned_cache import (
    VersionedCache,
    CURRENT_CACHE_VERSION,
)

__all__ = [
    "VersionedCache",
    "CURRENT_CACHE_VERSION",
]
