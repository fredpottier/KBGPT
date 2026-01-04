"""
VersionedCache - Cache versionné pour Extraction V2.

Format cache v2 avec versioning explicite.
Invalidation automatique si version incompatible.

Spécification: OSMOSIS_EXTRACTION_V2_DECISIONS.md - Décision 10

Implémentation complète en Phase 6.
"""

from __future__ import annotations
from typing import Any, Dict, Optional
import json
import hashlib
import logging
from pathlib import Path
from datetime import datetime

from knowbase.extraction_v2.models import ExtractionResult

logger = logging.getLogger(__name__)


# Version actuelle du cache
CURRENT_CACHE_VERSION = "v2"


class VersionedCache:
    """
    Cache versionné pour les résultats d'extraction.

    Format cache v2:
    ```json
    {
      "cache_version": "v2",
      "created_at": "2026-01-02T14:30:00Z",
      "source_file_hash": "abc123...",
      "extraction": {
        "full_text": "...",
        "structure": { ... },
        "page_index": [ ... ]
      },
      "gating_decisions": [ ... ],
      "vision_results": [ ... ]
    }
    ```

    Invalidation:
    - Si cache_version != CURRENT_CACHE_VERSION → invalide
    - Si source_file_hash différent → invalide

    Usage:
        >>> cache = VersionedCache(cache_dir="/path/to/cache")
        >>> result = cache.get("doc123", "/path/to/doc.pdf")
        >>> if result is None:
        ...     result = extract_document(...)
        ...     cache.set("doc123", "/path/to/doc.pdf", result)

    Note: Implémentation complète en Phase 6.
    """

    def __init__(
        self,
        cache_dir: Optional[str] = None,
        version: str = CURRENT_CACHE_VERSION,
    ):
        """
        Initialise le cache.

        Args:
            cache_dir: Répertoire de cache (défaut: data/extraction_cache)
            version: Version du cache
        """
        self.cache_dir = Path(cache_dir) if cache_dir else Path("data/extraction_cache")
        self.version = version

        # Créer le répertoire si nécessaire
        self.cache_dir.mkdir(parents=True, exist_ok=True)

        logger.info(
            f"[VersionedCache] Initialized: dir={self.cache_dir}, version={version}"
        )

    def _get_cache_path(self, document_id: str) -> Path:
        """Retourne le chemin du fichier cache."""
        return self.cache_dir / f"{document_id}.v2cache.json"

    def _compute_file_hash(self, file_path: str) -> str:
        """Calcule le hash SHA256 d'un fichier."""
        sha256 = hashlib.sha256()
        with open(file_path, "rb") as f:
            for chunk in iter(lambda: f.read(8192), b""):
                sha256.update(chunk)
        return sha256.hexdigest()

    def is_valid(self, cache_data: Dict[str, Any]) -> bool:
        """
        Vérifie si le cache est valide.

        Args:
            cache_data: Données du cache

        Returns:
            True si valide, False sinon
        """
        return cache_data.get("cache_version") == CURRENT_CACHE_VERSION

    def get(
        self,
        document_id: str,
        source_path: str,
    ) -> Optional[ExtractionResult]:
        """
        Récupère un résultat depuis le cache.

        Args:
            document_id: ID du document
            source_path: Chemin du fichier source (pour vérification hash)

        Returns:
            ExtractionResult si cache valide, None sinon

        Raises:
            NotImplementedError: Implémentation en Phase 6
        """
        raise NotImplementedError(
            "VersionedCache.get() sera implémenté en Phase 6."
        )

    def set(
        self,
        document_id: str,
        source_path: str,
        result: ExtractionResult,
    ) -> None:
        """
        Sauvegarde un résultat dans le cache.

        Args:
            document_id: ID du document
            source_path: Chemin du fichier source
            result: Résultat d'extraction à cacher

        Raises:
            NotImplementedError: Implémentation en Phase 6
        """
        raise NotImplementedError(
            "VersionedCache.set() sera implémenté en Phase 6."
        )

    def invalidate(self, document_id: str) -> bool:
        """
        Invalide le cache pour un document.

        Args:
            document_id: ID du document

        Returns:
            True si cache supprimé, False si non trouvé
        """
        cache_path = self._get_cache_path(document_id)
        if cache_path.exists():
            cache_path.unlink()
            logger.info(f"[VersionedCache] Invalidated: {document_id}")
            return True
        return False

    def clear_all(self) -> int:
        """
        Supprime tous les fichiers cache.

        Returns:
            Nombre de fichiers supprimés
        """
        count = 0
        for cache_file in self.cache_dir.glob("*.v2cache.json"):
            cache_file.unlink()
            count += 1
        logger.info(f"[VersionedCache] Cleared {count} cache files")
        return count


__all__ = [
    "CURRENT_CACHE_VERSION",
    "VersionedCache",
]
