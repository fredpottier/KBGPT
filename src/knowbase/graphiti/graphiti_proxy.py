"""
Graphiti Proxy - Workaround API Limitations

Ce proxy enrichit l'API Graphiti pour pallier aux limitations documentées dans:
https://github.com/fredpottier/KBGPT/issues/18

Fonctionnalités ajoutées:
1. add_episode() retourne episode_uuid (pas juste {success: true})
2. get_episode(episode_id) pour récupérer episode par UUID ou custom_id
3. Cache persistant custom_id ↔ episode_uuid (PostgreSQL ou JSON)

ATTENTION: Code temporaire - À SUPPRIMER si API Graphiti corrigée upstream

Backends disponibles:
- PostgreSQLBackend (production - enterprise-grade) ✅
- JSONBackend (dev/test uniquement)

Références:
- migrations/001_graphiti_cache.sql
- src/knowbase/graphiti/cache_backend.py
- doc/GRAPHITI_CACHE_POSTGRESQL_MIGRATION.md
"""

import logging
import os
import re
from typing import Dict, Any, Optional, List
from datetime import datetime
from pathlib import Path

# Import backends
from .cache_backend import (
    CacheBackend,
    PostgreSQLBackend,
    JSONBackend,
    EpisodeCacheEntry
)

logger = logging.getLogger(__name__)


class GraphitiProxy:
    """
    Proxy enrichi pour API Graphiti avec backend de cache configurable

    Workaround pour limitations API Graphiti (GitHub #18):
    - POST /messages ne retourne pas episode_uuid
    - GET /episode/{uuid} n'existe pas
    - Pas de mapping custom_id ↔ graphiti_uuid

    Solution:
    - Intercepte add_episode(), récupère UUID via get_episodes(last_n=1)
    - Maintient cache persistant custom_id ↔ episode_uuid
    - Fournit get_episode() par UUID ou custom_id

    Backends:
    - PostgreSQL (production) via GRAPHITI_CACHE_BACKEND=postgresql
    - JSON (dev/test) via GRAPHITI_CACHE_BACKEND=json

    Usage:
        # Auto-configuration depuis .env
        proxy = GraphitiProxy(graphiti_client)

        # Configuration manuelle
        proxy = GraphitiProxy(
            graphiti_client,
            cache_backend="postgresql",
            postgres_dsn="postgresql://user:pass@host/db"
        )

        # add_episode retourne episode_uuid
        result = proxy.add_episode(
            group_id="tenant_1",
            messages=[...],
            custom_id="my_episode_001"
        )
        # result = {"success": true, "episode_uuid": "abc-123", ...}

        # get_episode par custom_id OU uuid
        episode = proxy.get_episode("my_episode_001")
        episode = proxy.get_episode("abc-123")
    """

    def __init__(
        self,
        graphiti_client,
        cache_backend: Optional[str] = None,
        cache_dir: Optional[Path] = None,
        postgres_dsn: Optional[str] = None,
        enable_cache: bool = True
    ):
        """
        Initialiser proxy Graphiti avec backend configurable

        Args:
            graphiti_client: Client Graphiti standard (GraphitiClient instance)
            cache_backend: Type backend ("postgresql" ou "json", défaut: depuis env)
            cache_dir: Dossier cache JSON (si backend=json)
            postgres_dsn: DSN PostgreSQL (si backend=postgresql, défaut: depuis env)
            enable_cache: Activer cache persistant (défaut: True)
        """
        self.client = graphiti_client
        self.enable_cache = enable_cache

        if not self.enable_cache:
            logger.warning("[GraphitiProxy] Cache désactivé - fonctionnalités limitées")
            self._backend = None
            return

        # Déterminer backend depuis config ou env
        backend_type = cache_backend or os.getenv("GRAPHITI_CACHE_BACKEND", "json")

        # Initialiser backend
        if backend_type == "postgresql":
            # PostgreSQL backend (production)
            dsn = postgres_dsn or os.getenv(
                "GRAPHITI_CACHE_POSTGRES_DSN",
                os.getenv("ZEP_STORE_POSTGRES_DSN", "")
            )

            if not dsn:
                logger.error(
                    "[GraphitiProxy] PostgreSQL backend requis mais DSN non configuré. "
                    "Définir GRAPHITI_CACHE_POSTGRES_DSN ou ZEP_STORE_POSTGRES_DSN. "
                    "Fallback vers JSON backend."
                )
                backend_type = "json"
            else:
                try:
                    self._backend = PostgreSQLBackend(postgres_dsn=dsn)
                    logger.info(
                        "[GraphitiProxy] PostgreSQL backend initialisé (enterprise-grade)"
                    )
                except Exception as e:
                    logger.error(
                        f"[GraphitiProxy] Échec initialisation PostgreSQL: {e}. "
                        "Fallback vers JSON backend."
                    )
                    backend_type = "json"

        if backend_type == "json":
            # JSON backend (dev/test uniquement)
            json_dir = cache_dir or Path(os.getenv("GRAPHITI_CACHE_DIR", "/data/graphiti_cache"))
            self._backend = JSONBackend(cache_dir=json_dir)
            logger.warning(
                "[GraphitiProxy] JSON backend actif - NON recommandé pour production. "
                "Utiliser GRAPHITI_CACHE_BACKEND=postgresql."
            )

        # Charger cache en mémoire (pour performance)
        self._cache: Dict[str, EpisodeCacheEntry] = {}
        if self._backend:
            self._cache = self._backend.load_all()
            logger.info(f"[GraphitiProxy] Cache chargé: {len(self._cache)} entrées")

        # Log avertissement
        logger.warning(
            "GraphitiProxy actif - Workaround temporaire pour limitations API Graphiti. "
            "Surveiller https://github.com/fredpottier/KBGPT/issues/18 pour suppression si corrigé upstream"
        )

    def add_episode(
        self,
        group_id: str,
        messages: List[Dict[str, Any]],
        custom_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Créer episode Graphiti avec retour enrichi

        Enrichit la réponse standard {"success": true} avec episode_uuid

        Args:
            group_id: ID groupe/tenant
            messages: Liste messages (format Graphiti)
            custom_id: ID custom pour mapping (optionnel, auto-généré si absent)

        Returns:
            {
                "success": true,
                "episode_uuid": "abc-123-def",  # ← ENRICHI
                "custom_id": "my_custom_id",
                "group_id": "tenant_1",
                "created_at": "2025-10-02T...",
                "content_preview": "First 200 chars..."
            }

        Raises:
            Exception: Si création episode échoue
        """

        # 1. Générer custom_id si non fourni
        if not custom_id:
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S_%f')
            custom_id = f"{group_id}_episode_{timestamp}"

        logger.debug(f"[GraphitiProxy] Creating episode custom_id={custom_id}, group_id={group_id}")

        # 2. Appel API Graphiti standard (signature: group_id, messages uniquement)
        try:
            result = self.client.add_episode(
                group_id=group_id,
                messages=messages
            )
        except Exception as e:
            logger.error(f"[GraphitiProxy] Failed to create episode: {e}")
            raise

        # 3. Récupérer episode créé via get_episodes (workaround API limitation)
        try:
            episode_uuid, episode_data = self._fetch_latest_episode(group_id)

            if not episode_uuid:
                logger.warning(
                    f"[GraphitiProxy] Could not retrieve episode_uuid for custom_id={custom_id}. "
                    "Returning standard result without enrichment."
                )
                return {**result, "custom_id": custom_id}

            # 4. Enrichir résultat
            enriched_result = {
                "success": result.get("success", True),
                "episode_uuid": episode_uuid,
                "custom_id": custom_id,
                "group_id": group_id,
                "created_at": episode_data.get("created_at"),
                "name": episode_data.get("name", ""),
                "content_preview": self._truncate_content(episode_data.get("content", "")),
                "entity_edges_count": len(episode_data.get("entity_edges", [])),
                "source_description": episode_data.get("source_description"),
                "metadata": {
                    "retrieved_via": "get_episodes_workaround",
                    "cache_enabled": self.enable_cache
                }
            }

            # 5. Sauvegarder dans cache
            if self.enable_cache:
                self._cache_episode(
                    custom_id=custom_id,
                    episode_uuid=episode_uuid,
                    group_id=group_id,
                    episode_data=episode_data
                )

            logger.info(
                f"[GraphitiProxy] Episode created successfully - "
                f"custom_id={custom_id}, episode_uuid={episode_uuid}"
            )

            return enriched_result

        except Exception as e:
            logger.error(f"[GraphitiProxy] Failed to enrich episode response: {e}", exc_info=True)
            # Fallback: retourner résultat standard sans enrichissement
            return {**result, "custom_id": custom_id}

    def get_episode(
        self,
        episode_id: str,
        id_type: str = "auto"
    ) -> Optional[Dict[str, Any]]:
        """
        Récupérer episode par UUID OU custom_id

        Fonctionnalité NON disponible dans API Graphiti standard (GitHub #18)

        Args:
            episode_id: UUID Graphiti OU custom_id
            id_type: Type ID ("uuid", "custom", "auto" pour détection auto)

        Returns:
            Episode data OU None si non trouvé
            {
                "uuid": "abc-123",
                "custom_id": "my_episode_001",
                "group_id": "tenant_1",
                "name": "Episode name",
                "content": "Full content...",
                "created_at": "2025-10-02T...",
                "entity_edges": [...],
                "source_description": "..."
            }

        Example:
            # Par custom_id
            episode = proxy.get_episode("my_episode_001")

            # Par UUID
            episode = proxy.get_episode("abc-123-def-456")
        """

        logger.debug(f"[GraphitiProxy] Getting episode: episode_id={episode_id}, id_type={id_type}")

        # 1. Déterminer type ID
        if id_type == "auto":
            id_type = "uuid" if self._is_uuid(episode_id) else "custom"

        episode_uuid = None
        custom_id = None

        # 2. Résoudre UUID selon type
        if id_type == "custom":
            custom_id = episode_id

            # Chercher dans cache
            cached = self._get_from_cache(custom_id)
            if cached:
                episode_uuid = cached.episode_uuid
                logger.debug(f"[GraphitiProxy] Found in cache: {custom_id} → {episode_uuid}")
            else:
                logger.warning(
                    f"[GraphitiProxy] custom_id={custom_id} not found in cache. "
                    "Cannot retrieve episode (API limitation)."
                )
                return None
        else:
            episode_uuid = episode_id

        # 3. Récupérer episode par UUID
        if episode_uuid:
            episode_data = self._fetch_episode_by_uuid(episode_uuid)

            if episode_data and custom_id:
                # Enrichir avec custom_id depuis cache
                episode_data["custom_id"] = custom_id

            return episode_data

        return None

    def get_episode_uuid(self, custom_id: str) -> Optional[str]:
        """
        Récupérer UUID Graphiti depuis custom_id

        Args:
            custom_id: ID custom

        Returns:
            UUID Graphiti OU None si non trouvé
        """
        cached = self._get_from_cache(custom_id)
        return cached.episode_uuid if cached else None

    def _fetch_latest_episode(self, group_id: str) -> tuple[Optional[str], Dict[str, Any]]:
        """
        Récupérer dernier episode créé pour un groupe

        Workaround car API ne retourne pas UUID après création

        Args:
            group_id: ID groupe

        Returns:
            (episode_uuid, episode_data) OU (None, {}) si échec
        """
        try:
            # Récupérer dernier episode via get_episodes
            episodes = self.client.get_episodes(
                group_id=group_id,
                last_n=1
            )

            if episodes and len(episodes) > 0:
                latest = episodes[0]
                episode_uuid = latest.get("uuid")
                return episode_uuid, latest

            logger.warning(f"[GraphitiProxy] No episodes found for group_id={group_id}")
            return None, {}

        except Exception as e:
            logger.error(f"[GraphitiProxy] Failed to fetch latest episode: {e}")
            return None, {}

    def _fetch_episode_by_uuid(self, episode_uuid: str) -> Optional[Dict[str, Any]]:
        """
        Récupérer episode par UUID

        Workaround car GET /episode/{uuid} n'existe pas
        Utilise search ou list episodes (limite 100 derniers)

        Args:
            episode_uuid: UUID Graphiti

        Returns:
            Episode data OU None si non trouvé
        """
        try:
            # Option: Parcourir episodes récents (limite 100)
            # TODO: Si performance problème, utiliser search Graphiti

            episodes = self.client.get_episodes(last_n=100)

            for ep in episodes:
                if ep.get("uuid") == episode_uuid:
                    logger.debug(f"[GraphitiProxy] Found episode uuid={episode_uuid}")
                    return ep

            logger.warning(
                f"[GraphitiProxy] Episode uuid={episode_uuid} not found in last 100 episodes. "
                "Consider increasing search range or using Graphiti search API."
            )
            return None

        except Exception as e:
            logger.error(f"[GraphitiProxy] Failed to fetch episode by UUID: {e}")
            return None

    def _cache_episode(
        self,
        custom_id: str,
        episode_uuid: str,
        group_id: str,
        episode_data: Dict[str, Any]
    ):
        """
        Sauvegarder mapping custom_id ↔ episode dans cache (backend-agnostic)

        Args:
            custom_id: ID custom
            episode_uuid: UUID Graphiti
            group_id: ID groupe
            episode_data: Données episode depuis API
        """
        if not self.enable_cache or not self._backend:
            return

        try:
            # Sauvegarder via backend
            success = self._backend.save(
                custom_id=custom_id,
                episode_uuid=episode_uuid,
                group_id=group_id,
                episode_data=episode_data
            )

            if success:
                # Mettre à jour cache mémoire
                entry = self._backend.get(custom_id)
                if entry:
                    self._cache[custom_id] = entry
                    logger.debug(f"[GraphitiProxy] Cached episode: {custom_id} → {episode_uuid}")
            else:
                logger.warning(f"[GraphitiProxy] Failed to cache episode: {custom_id}")

        except Exception as e:
            logger.error(f"[GraphitiProxy] Failed to cache episode: {e}")

    def _get_from_cache(self, custom_id: str) -> Optional[EpisodeCacheEntry]:
        """
        Récupérer depuis cache mémoire ou backend

        Args:
            custom_id: ID custom

        Returns:
            EpisodeCacheEntry OU None si non trouvé
        """
        if not self.enable_cache or not self._backend:
            return None

        # Cache mémoire (performance)
        if custom_id in self._cache:
            return self._cache[custom_id]

        # Backend (PostgreSQL ou JSON)
        try:
            entry = self._backend.get(custom_id)
            if entry:
                # Mettre à jour cache mémoire
                self._cache[custom_id] = entry
            return entry
        except Exception as e:
            logger.warning(f"[GraphitiProxy] Failed to get from cache: {e}")
            return None

    def clear_cache(self, custom_id: Optional[str] = None):
        """
        Nettoyer cache (mémoire + backend)

        Args:
            custom_id: ID custom à supprimer (None = tout supprimer)
        """
        if not self.enable_cache or not self._backend:
            return

        try:
            if custom_id:
                # Supprimer entry spécifique
                self._cache.pop(custom_id, None)
                self._backend.delete(custom_id)
                logger.info(f"[GraphitiProxy] Cleared cache for {custom_id}")
            else:
                # Supprimer tout le cache
                self._cache.clear()
                count = self._backend.clear()
                logger.info(f"[GraphitiProxy] Cleared all cache ({count} entries)")
        except Exception as e:
            logger.error(f"[GraphitiProxy] Failed to clear cache: {e}")

    def get_cache_stats(self) -> Dict[str, Any]:
        """
        Statistiques du cache

        Returns:
            Dict avec stats (backend, total_entries, by_group, etc.)
        """
        if not self.enable_cache or not self._backend:
            return {"enabled": False}

        try:
            stats = self._backend.get_stats()
            stats["memory_cache_entries"] = len(self._cache)
            return stats
        except Exception as e:
            logger.error(f"[GraphitiProxy] Failed to get cache stats: {e}")
            return {"enabled": True, "error": str(e)}

    @staticmethod
    def _is_uuid(value: str) -> bool:
        """
        Détecter si string est un UUID (format standard)

        Args:
            value: String à tester

        Returns:
            True si UUID valide
        """
        uuid_pattern = r'^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$'
        return bool(re.match(uuid_pattern, value.lower()))

    @staticmethod
    def _truncate_content(content: str, max_chars: int = 200) -> str:
        """
        Tronquer contenu pour preview

        Args:
            content: Contenu complet
            max_chars: Limite caractères

        Returns:
            Contenu tronqué avec "..."
        """
        if len(content) <= max_chars:
            return content
        return content[:max_chars] + "..."

    # Proxy transparente pour autres méthodes Graphiti
    def __getattr__(self, name):
        """
        Déléguer appels non-interceptés au client Graphiti standard

        Permet utilisation transparente:
            proxy.search(...) → graphiti_client.search(...)
        """
        return getattr(self.client, name)


__all__ = ["GraphitiProxy", "EpisodeCacheEntry"]
