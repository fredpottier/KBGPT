"""
🌊 OSMOSE - LLM Cache Manager

Gestion du cache LLM par provider:
- Gemini: Context Caching API (cache prompts système réutilisés)
- OpenAI: No-op (pas de cache natif)
- Anthropic: Prompt Caching (si activé)

Architecture:
- Cache OPTIONNEL par provider
- Transparent pour providers sans cache
- Configuration via llm_models.yaml

Phase 1.8.1e - Migration Gemini
"""
import logging
import os
from typing import Dict, List, Any, Optional
from abc import ABC, abstractmethod
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)


class LLMCacheProvider(ABC):
    """Interface abstraite pour cache LLM."""

    @abstractmethod
    def cache_content(
        self,
        cache_key: str,
        content: Any,
        ttl_hours: int = 1
    ) -> Optional[str]:
        """
        Cache du contenu réutilisable.

        Args:
            cache_key: Clé unique identifiant le contenu
            content: Contenu à cacher (prompt système, context doc, etc.)
            ttl_hours: Durée de vie du cache en heures

        Returns:
            Cache ID si succès, None sinon
        """
        pass

    @abstractmethod
    def get_cached_content(self, cache_id: str) -> Optional[Any]:
        """Récupère contenu caché."""
        pass

    @abstractmethod
    def delete_cache(self, cache_id: str) -> bool:
        """Supprime un cache."""
        pass

    @abstractmethod
    def is_cache_enabled(self) -> bool:
        """Vérifie si le cache est activé pour ce provider."""
        pass


class GeminiCacheProvider(LLMCacheProvider):
    """
    Cache provider pour Google Gemini.

    Utilise Context Caching API:
    - Cache prompts système, deck summary, instructions JSON
    - Réduit coûts input de 75% sur tokens cachés
    - TTL configurable (1h par défaut)

    Docs: https://ai.google.dev/gemini-api/docs/caching
    """

    def __init__(self, enabled: bool = True):
        self.enabled = enabled
        self._cache_registry: Dict[str, str] = {}  # cache_key -> cache_id

        if self.enabled:
            try:
                import google.generativeai as genai
                from google.generativeai import caching
                self.genai = genai
                self.caching = caching
                logger.info("[OSMOSE:GeminiCache] ✅ Enabled")
            except ImportError:
                logger.warning("[OSMOSE:GeminiCache] google-generativeai not installed, disabling cache")
                self.enabled = False

    def cache_content(
        self,
        cache_key: str,
        content: Any,
        ttl_hours: int = 1
    ) -> Optional[str]:
        """
        Cache contenu Gemini (prompt système + contexte doc).

        Args:
            cache_key: Identifiant unique (ex: "doc_12345_system_prompt")
            content: Dict avec:
                - model: str (ex: "gemini-1.5-flash-8b")
                - system_instruction: str (prompt système)
                - contents: List (contexte à cacher, ex: deck summary)
            ttl_hours: Durée de vie (défaut 1h)

        Returns:
            Cache ID Gemini si succès
        """
        if not self.enabled:
            return None

        # Vérifier si déjà caché
        if cache_key in self._cache_registry:
            existing_id = self._cache_registry[cache_key]
            logger.debug(f"[OSMOSE:GeminiCache] Cache hit: {cache_key} -> {existing_id}")
            return existing_id

        try:
            # Créer cached content
            cached_content = self.caching.CachedContent.create(
                model=content["model"],
                system_instruction=content.get("system_instruction"),
                contents=content.get("contents", []),
                ttl=timedelta(hours=ttl_hours)
            )

            cache_id = cached_content.name
            self._cache_registry[cache_key] = cache_id

            logger.info(
                f"[OSMOSE:GeminiCache] ✅ Cached: {cache_key} "
                f"(ID: {cache_id}, TTL: {ttl_hours}h)"
            )

            return cache_id

        except Exception as e:
            logger.warning(f"[OSMOSE:GeminiCache] Failed to cache {cache_key}: {e}")
            return None

    def get_cached_content(self, cache_id: str) -> Optional[Any]:
        """Récupère cached content Gemini."""
        if not self.enabled:
            return None

        try:
            cached = self.caching.CachedContent.get(cache_id)
            return cached
        except Exception as e:
            logger.warning(f"[OSMOSE:GeminiCache] Failed to get cache {cache_id}: {e}")
            return None

    def delete_cache(self, cache_id: str) -> bool:
        """Supprime cache Gemini."""
        if not self.enabled:
            return False

        try:
            cached = self.caching.CachedContent.get(cache_id)
            cached.delete()

            # Supprimer du registry local
            self._cache_registry = {
                k: v for k, v in self._cache_registry.items() if v != cache_id
            }

            logger.info(f"[OSMOSE:GeminiCache] ✅ Deleted cache: {cache_id}")
            return True

        except Exception as e:
            logger.warning(f"[OSMOSE:GeminiCache] Failed to delete cache {cache_id}: {e}")
            return False

    def is_cache_enabled(self) -> bool:
        return self.enabled


class NoOpCacheProvider(LLMCacheProvider):
    """
    Cache provider no-op pour providers sans cache natif.

    Utilisé pour:
    - OpenAI (pas de cache API)
    - SageMaker
    - Autres providers sans support cache
    """

    def cache_content(self, cache_key: str, content: Any, ttl_hours: int = 1) -> Optional[str]:
        """No-op: retourne None (pas de cache)."""
        return None

    def get_cached_content(self, cache_id: str) -> Optional[Any]:
        """No-op: retourne None."""
        return None

    def delete_cache(self, cache_id: str) -> bool:
        """No-op: retourne False."""
        return False

    def is_cache_enabled(self) -> bool:
        return False


class AnthropicCacheProvider(LLMCacheProvider):
    """
    Cache provider pour Anthropic Claude.

    Utilise Prompt Caching (si activé):
    - Cache system prompts longs
    - Réduit coûts input sur tokens cachés
    - Activation via paramètre cache_control

    Note: Pas encore implémenté (placeholder pour futur)
    """

    def __init__(self, enabled: bool = False):
        self.enabled = enabled
        # TODO: Implémenter quand Anthropic Prompt Caching sera activé

    def cache_content(self, cache_key: str, content: Any, ttl_hours: int = 1) -> Optional[str]:
        # TODO: Implémenter Anthropic caching
        return None

    def get_cached_content(self, cache_id: str) -> Optional[Any]:
        return None

    def delete_cache(self, cache_id: str) -> bool:
        return False

    def is_cache_enabled(self) -> bool:
        return self.enabled


class LLMCacheManager:
    """
    Gestionnaire central de cache LLM.

    Coordonne les caches par provider:
    - Gemini: Context Caching actif
    - OpenAI: No-op (transparent)
    - Anthropic: Prompt Caching (futur)

    Usage:
        manager = LLMCacheManager()
        cache_id = manager.cache_for_provider("gemini", "doc_123", content)
        if cache_id:
            # Utiliser cache dans appel LLM
    """

    def __init__(self, config: Optional[Dict] = None):
        """
        Initialise le cache manager.

        Args:
            config: Configuration cache (depuis llm_models.yaml)
        """
        self.config = config or {}
        self._providers: Dict[str, LLMCacheProvider] = {}

        # Initialiser providers de cache
        self._init_cache_providers()

    def _init_cache_providers(self):
        """Initialise les providers de cache selon config."""
        # Gemini cache
        gemini_cache_enabled = self.config.get("gemini", {}).get("cache_enabled", True)
        self._providers["gemini"] = GeminiCacheProvider(enabled=gemini_cache_enabled)
        self._providers["google"] = self._providers["gemini"]  # Alias

        # OpenAI no-op
        self._providers["openai"] = NoOpCacheProvider()

        # Anthropic (futur)
        anthropic_cache_enabled = self.config.get("anthropic", {}).get("cache_enabled", False)
        self._providers["anthropic"] = AnthropicCacheProvider(enabled=anthropic_cache_enabled)

        # SageMaker no-op
        self._providers["sagemaker"] = NoOpCacheProvider()

        logger.info(
            f"[OSMOSE:CacheManager] Initialized: "
            f"Gemini={self._providers['gemini'].is_cache_enabled()}, "
            f"OpenAI={self._providers['openai'].is_cache_enabled()}, "
            f"Anthropic={self._providers['anthropic'].is_cache_enabled()}"
        )

    def get_provider(self, provider_name: str) -> LLMCacheProvider:
        """Obtient le cache provider pour un provider LLM."""
        return self._providers.get(provider_name, NoOpCacheProvider())

    def cache_for_provider(
        self,
        provider_name: str,
        cache_key: str,
        content: Any,
        ttl_hours: int = 1
    ) -> Optional[str]:
        """
        Cache du contenu pour un provider spécifique.

        Args:
            provider_name: Nom du provider ("gemini", "openai", etc.)
            cache_key: Clé unique du cache
            content: Contenu à cacher
            ttl_hours: Durée de vie du cache

        Returns:
            Cache ID si succès, None si provider sans cache ou erreur
        """
        provider = self.get_provider(provider_name)

        if not provider.is_cache_enabled():
            logger.debug(f"[OSMOSE:CacheManager] Cache disabled for {provider_name}")
            return None

        return provider.cache_content(cache_key, content, ttl_hours)

    def get_cached(self, provider_name: str, cache_id: str) -> Optional[Any]:
        """Récupère contenu caché."""
        provider = self.get_provider(provider_name)
        return provider.get_cached_content(cache_id)

    def delete_cache(self, provider_name: str, cache_id: str) -> bool:
        """Supprime un cache."""
        provider = self.get_provider(provider_name)
        return provider.delete_cache(cache_id)

    def is_cache_enabled(self, provider_name: str) -> bool:
        """Vérifie si cache activé pour un provider."""
        provider = self.get_provider(provider_name)
        return provider.is_cache_enabled()


# Instance singleton
_cache_manager: Optional[LLMCacheManager] = None


def get_cache_manager(config: Optional[Dict] = None) -> LLMCacheManager:
    """Obtient l'instance singleton du cache manager."""
    global _cache_manager
    if _cache_manager is None:
        _cache_manager = LLMCacheManager(config)
    return _cache_manager
