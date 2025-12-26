"""
Phase 2.12 - Score Cache

Redis cache for pairwise similarity scores.
Avoids expensive re-computation of cross-encoder scores.

Author: Claude Code
Date: 2025-12-26
"""

from __future__ import annotations

import json
import logging
import hashlib
from typing import Optional, Dict, Any, Tuple

import redis

from knowbase.config.settings import get_settings
from .types import SignalBreakdown
from .config import CACHE_CONFIG

logger = logging.getLogger(__name__)


class ScoreCache:
    """
    Redis cache for pairwise similarity scores.

    Key format: er:scores:{pair_id}
    Value: JSON with score and signals breakdown

    Features:
    - TTL-based expiration
    - Bounded cache size
    - Score + signals storage
    """

    def __init__(self, redis_client: Optional[redis.Redis] = None):
        """
        Initialize ScoreCache.

        Args:
            redis_client: Redis client (creates one if None)
        """
        if redis_client is None:
            settings = get_settings()
            redis_client = redis.Redis(
                host=settings.redis_host,
                port=settings.redis_port,
                db=0,
                decode_responses=True
            )
        self.redis = redis_client
        self.prefix = CACHE_CONFIG["redis_prefix"]
        self.ttl_seconds = CACHE_CONFIG["score_cache_ttl_hours"] * 3600

    def _make_key(self, concept_a_id: str, concept_b_id: str) -> str:
        """
        Create cache key for a pair (order-independent).

        Args:
            concept_a_id: First concept ID
            concept_b_id: Second concept ID

        Returns:
            Cache key
        """
        # Sort IDs to make key order-independent
        ids = sorted([concept_a_id, concept_b_id])
        pair_id = f"{ids[0]}|{ids[1]}"
        return f"{self.prefix}{pair_id}"

    def get(
        self,
        concept_a_id: str,
        concept_b_id: str
    ) -> Optional[Tuple[float, SignalBreakdown]]:
        """
        Get cached score for a pair.

        Args:
            concept_a_id: First concept ID
            concept_b_id: Second concept ID

        Returns:
            Tuple of (score, signals) or None if not cached
        """
        key = self._make_key(concept_a_id, concept_b_id)
        try:
            data = self.redis.get(key)
            if data:
                parsed = json.loads(data)
                score = parsed["score"]
                signals = SignalBreakdown(**parsed["signals"])
                logger.debug(f"[ScoreCache] HIT: {key} -> {score:.3f}")
                return score, signals
            logger.debug(f"[ScoreCache] MISS: {key}")
            return None
        except Exception as e:
            logger.warning(f"[ScoreCache] Error getting {key}: {e}")
            return None

    def set(
        self,
        concept_a_id: str,
        concept_b_id: str,
        score: float,
        signals: SignalBreakdown
    ) -> bool:
        """
        Cache score for a pair.

        Args:
            concept_a_id: First concept ID
            concept_b_id: Second concept ID
            score: Similarity score
            signals: Signal breakdown

        Returns:
            True if cached successfully
        """
        key = self._make_key(concept_a_id, concept_b_id)
        data = {
            "score": score,
            "signals": signals.model_dump(),
            "cached_at": __import__("datetime").datetime.utcnow().isoformat()
        }
        try:
            self.redis.setex(key, self.ttl_seconds, json.dumps(data))
            logger.debug(f"[ScoreCache] SET: {key} -> {score:.3f}")
            return True
        except Exception as e:
            logger.warning(f"[ScoreCache] Error setting {key}: {e}")
            return False

    def delete(self, concept_a_id: str, concept_b_id: str) -> bool:
        """
        Delete cached score for a pair.

        Args:
            concept_a_id: First concept ID
            concept_b_id: Second concept ID

        Returns:
            True if deleted
        """
        key = self._make_key(concept_a_id, concept_b_id)
        try:
            return self.redis.delete(key) > 0
        except Exception as e:
            logger.warning(f"[ScoreCache] Error deleting {key}: {e}")
            return False

    def invalidate_concept(self, concept_id: str) -> int:
        """
        Invalidate all cached scores involving a concept.

        Args:
            concept_id: Concept ID to invalidate

        Returns:
            Number of keys deleted
        """
        pattern = f"{self.prefix}*{concept_id}*"
        try:
            keys = list(self.redis.scan_iter(match=pattern))
            if keys:
                return self.redis.delete(*keys)
            return 0
        except Exception as e:
            logger.warning(f"[ScoreCache] Error invalidating {concept_id}: {e}")
            return 0

    def get_stats(self) -> Dict[str, Any]:
        """Get cache statistics."""
        pattern = f"{self.prefix}*"
        try:
            keys = list(self.redis.scan_iter(match=pattern))
            return {
                "cached_pairs": len(keys),
                "ttl_hours": CACHE_CONFIG["score_cache_ttl_hours"],
                "prefix": self.prefix,
            }
        except Exception as e:
            logger.warning(f"[ScoreCache] Error getting stats: {e}")
            return {"cached_pairs": 0, "error": str(e)}

    def clear(self) -> int:
        """
        Clear all cached scores.

        Returns:
            Number of keys deleted
        """
        pattern = f"{self.prefix}*"
        try:
            keys = list(self.redis.scan_iter(match=pattern))
            if keys:
                deleted = self.redis.delete(*keys)
                logger.info(f"[ScoreCache] Cleared {deleted} cached scores")
                return deleted
            return 0
        except Exception as e:
            logger.warning(f"[ScoreCache] Error clearing cache: {e}")
            return 0


# Singleton
_cache_instance: Optional[ScoreCache] = None


def get_score_cache() -> ScoreCache:
    """Get or create ScoreCache instance."""
    global _cache_instance
    if _cache_instance is None:
        _cache_instance = ScoreCache()
    return _cache_instance
