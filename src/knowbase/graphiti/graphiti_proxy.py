"""
Graphiti Proxy - Workaround API Limitations

Ce proxy enrichit l'API Graphiti pour pallier aux limitations documentées dans:
https://github.com/fredpottier/KBGPT/issues/18

Fonctionnalités ajoutées:
1. add_episode() retourne episode_uuid (pas juste {success: true})
2. get_episode(episode_id) pour récupérer episode par UUID ou custom_id
3. Cache persistant custom_id ↔ episode_uuid

ATTENTION: Code temporaire - À SUPPRIMER si API Graphiti corrigée upstream
"""

import logging
import json
import re
from typing import Dict, Any, Optional, List
from datetime import datetime
from pathlib import Path
from dataclasses import dataclass, asdict

logger = logging.getLogger(__name__)


@dataclass
class EpisodeCacheEntry:
    """Entrée cache pour episode"""
    custom_id: str
    episode_uuid: str
    group_id: str
    created_at: str
    cached_at: str
    metadata: Dict[str, Any]

    def to_dict(self) -> Dict[str, Any]:
        """Convertir en dict pour serialization"""
        return asdict(self)


class GraphitiProxy:
    """
    Proxy enrichi pour API Graphiti

    Workaround pour limitations API Graphiti (GitHub #18):
    - POST /messages ne retourne pas episode_uuid
    - GET /episode/{uuid} n'existe pas
    - Pas de mapping custom_id ↔ graphiti_uuid

    Solution:
    - Intercepte add_episode(), récupère UUID via get_episodes(last_n=1)
    - Maintient cache persistant custom_id ↔ episode_uuid
    - Fournit get_episode() par UUID ou custom_id

    Usage:
        proxy = GraphitiProxy(graphiti_client)

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
        cache_dir: Optional[Path] = None,
        enable_cache: bool = True
    ):
        """
        Initialiser proxy Graphiti

        Args:
            graphiti_client: Client Graphiti standard (GraphitiClient instance)
            cache_dir: Dossier cache (défaut: /data/graphiti_cache)
            enable_cache: Activer cache persistant (défaut: True)
        """
        self.client = graphiti_client
        self.enable_cache = enable_cache

        # Cache directory
        self.cache_dir = cache_dir or Path("/data/graphiti_cache")
        if self.enable_cache:
            self.cache_dir.mkdir(parents=True, exist_ok=True)

        # Cache en mémoire (custom_id → EpisodeCacheEntry)
        self._cache: Dict[str, EpisodeCacheEntry] = {}

        # Charger cache depuis disque
        if self.enable_cache:
            self._load_cache()

        # Log avertissement
        logger.warning(
            "GraphitiProxy actif - Workaround temporaire pour limitations API Graphiti. "
            "Surveiller https://github.com/fredpottier/KBGPT/issues/18 pour suppression si corrigé upstream"
        )

    def add_episode(
        self,
        group_id: str,
        messages: List[Dict[str, Any]],
        custom_id: Optional[str] = None,
        name: Optional[str] = None,
        reference_time: Optional[str] = None,
        **kwargs
    ) -> Dict[str, Any]:
        """
        Créer episode Graphiti avec retour enrichi

        Enrichit la réponse standard {"success": true} avec episode_uuid

        Args:
            group_id: ID groupe/tenant
            messages: Liste messages (format Graphiti)
            custom_id: ID custom pour mapping (optionnel, auto-généré si absent)
            name: Nom episode (optionnel)
            reference_time: Timestamp référence (optionnel)
            **kwargs: Autres paramètres Graphiti

        Returns:
            {
                "success": true,
                "episode_uuid": "abc-123-def",  # ← ENRICHI
                "custom_id": "my_custom_id",
                "group_id": "tenant_1",
                "created_at": "2025-10-02T...",
                "name": "Episode name",
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

        # 2. Appel API Graphiti standard
        try:
            result = self.client.add_episode(
                group_id=group_id,
                name=name,
                episode_body=messages,
                reference_time=reference_time,
                **kwargs
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
                "name": episode_data.get("name", name),
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
        Sauvegarder mapping custom_id ↔ episode dans cache

        Args:
            custom_id: ID custom
            episode_uuid: UUID Graphiti
            group_id: ID groupe
            episode_data: Données episode depuis API
        """
        if not self.enable_cache:
            return

        try:
            cache_entry = EpisodeCacheEntry(
                custom_id=custom_id,
                episode_uuid=episode_uuid,
                group_id=group_id,
                created_at=episode_data.get("created_at", datetime.now().isoformat()),
                cached_at=datetime.now().isoformat(),
                metadata={
                    "name": episode_data.get("name", ""),
                    "source_description": episode_data.get("source_description", ""),
                    "content_length": len(episode_data.get("content", "")),
                    "entity_edges_count": len(episode_data.get("entity_edges", []))
                }
            )

            # Cache mémoire
            self._cache[custom_id] = cache_entry

            # Cache disque (JSON)
            cache_file = self.cache_dir / f"{custom_id}.json"
            cache_file.write_text(json.dumps(cache_entry.to_dict(), indent=2))

            logger.debug(f"[GraphitiProxy] Cached episode: {custom_id} → {episode_uuid}")

        except Exception as e:
            logger.error(f"[GraphitiProxy] Failed to cache episode: {e}")

    def _get_from_cache(self, custom_id: str) -> Optional[EpisodeCacheEntry]:
        """
        Récupérer depuis cache mémoire ou disque

        Args:
            custom_id: ID custom

        Returns:
            EpisodeCacheEntry OU None si non trouvé
        """
        if not self.enable_cache:
            return None

        # Cache mémoire
        if custom_id in self._cache:
            return self._cache[custom_id]

        # Cache disque
        cache_file = self.cache_dir / f"{custom_id}.json"
        if cache_file.exists():
            try:
                data = json.loads(cache_file.read_text())
                entry = EpisodeCacheEntry(**data)
                self._cache[custom_id] = entry
                return entry
            except Exception as e:
                logger.warning(f"[GraphitiProxy] Failed to load cache file {cache_file}: {e}")

        return None

    def _load_cache(self):
        """Charger tous les fichiers cache depuis disque au démarrage"""
        if not self.enable_cache or not self.cache_dir.exists():
            return

        loaded_count = 0
        for cache_file in self.cache_dir.glob("*.json"):
            try:
                data = json.loads(cache_file.read_text())
                entry = EpisodeCacheEntry(**data)
                self._cache[entry.custom_id] = entry
                loaded_count += 1
            except Exception as e:
                logger.warning(f"[GraphitiProxy] Failed to load cache {cache_file}: {e}")

        logger.info(f"[GraphitiProxy] Loaded {loaded_count} episodes from cache")

    def clear_cache(self, custom_id: Optional[str] = None):
        """
        Nettoyer cache (mémoire + disque)

        Args:
            custom_id: ID custom à supprimer (None = tout supprimer)
        """
        if not self.enable_cache:
            return

        if custom_id:
            # Supprimer entry spécifique
            self._cache.pop(custom_id, None)
            cache_file = self.cache_dir / f"{custom_id}.json"
            if cache_file.exists():
                cache_file.unlink()
            logger.info(f"[GraphitiProxy] Cleared cache for {custom_id}")
        else:
            # Supprimer tout le cache
            self._cache.clear()
            for cache_file in self.cache_dir.glob("*.json"):
                cache_file.unlink()
            logger.info(f"[GraphitiProxy] Cleared all cache")

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
