"""
Factory Graphiti - Service Selection

Fournit le service Graphiti approprié selon configuration:
- GraphitiProxy (enrichi) si GRAPHITI_USE_PROXY=true
- GraphitiClient (standard) si GRAPHITI_USE_PROXY=false

Usage:
    from knowbase.graphiti.graphiti_factory import get_graphiti_service

    # Retourne proxy OU client standard selon config
    graphiti = get_graphiti_service()

    # add_episode retourne episode_uuid (si proxy)
    result = graphiti.add_episode(...)
"""

import os
import logging
from typing import Union
from pathlib import Path

from knowbase.graphiti.graphiti_client import get_graphiti_client
from knowbase.graphiti.graphiti_proxy import GraphitiProxy

logger = logging.getLogger(__name__)


def get_graphiti_service(
    use_proxy: bool = None,
    cache_dir: Path = None
) -> Union[GraphitiProxy, object]:
    """
    Factory pour obtenir service Graphiti

    Retourne GraphitiProxy (enrichi) OU GraphitiClient (standard) selon config.

    Args:
        use_proxy: Forcer utilisation proxy (None = lire depuis env GRAPHITI_USE_PROXY)
        cache_dir: Dossier cache pour proxy (défaut: /data/graphiti_cache)

    Returns:
        GraphitiProxy si use_proxy=True, GraphitiClient sinon

    Environment Variables:
        GRAPHITI_USE_PROXY: "true" pour activer proxy, "false" pour client standard (défaut: true)
        GRAPHITI_CACHE_DIR: Dossier cache (défaut: /data/graphiti_cache)
        GRAPHITI_CACHE_ENABLED: "true" pour activer cache disque (défaut: true)

    Example:
        # Via env var
        os.environ["GRAPHITI_USE_PROXY"] = "true"
        graphiti = get_graphiti_service()  # Retourne GraphitiProxy

        # Via paramètre
        graphiti = get_graphiti_service(use_proxy=False)  # Force client standard
    """

    # 1. Déterminer si proxy activé
    if use_proxy is None:
        use_proxy_env = os.getenv("GRAPHITI_USE_PROXY", "true").lower()
        use_proxy = use_proxy_env in ("true", "1", "yes")

    # 2. Obtenir client Graphiti standard
    base_client = get_graphiti_client()

    # 3. Retourner proxy ou client selon config
    if use_proxy:
        # Configuration cache
        if cache_dir is None:
            cache_dir_env = os.getenv("GRAPHITI_CACHE_DIR", "/data/graphiti_cache")
            cache_dir = Path(cache_dir_env)

        cache_enabled_env = os.getenv("GRAPHITI_CACHE_ENABLED", "true").lower()
        cache_enabled = cache_enabled_env in ("true", "1", "yes")

        # Créer proxy
        proxy = GraphitiProxy(
            graphiti_client=base_client,
            cache_dir=cache_dir,
            enable_cache=cache_enabled
        )

        logger.info(
            f"[GraphitiFactory] Using GraphitiProxy (enriched) - "
            f"cache_enabled={cache_enabled}, cache_dir={cache_dir}"
        )

        return proxy
    else:
        # Client standard
        logger.info("[GraphitiFactory] Using GraphitiClient (standard)")
        return base_client


def is_proxy_enabled() -> bool:
    """
    Vérifier si proxy Graphiti est activé

    Returns:
        True si GRAPHITI_USE_PROXY=true
    """
    use_proxy_env = os.getenv("GRAPHITI_USE_PROXY", "true").lower()
    return use_proxy_env in ("true", "1", "yes")


__all__ = ["get_graphiti_service", "is_proxy_enabled"]
