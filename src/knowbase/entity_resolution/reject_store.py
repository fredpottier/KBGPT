"""
Phase 2.12 v1.1 - Reject Store

Stores REJECT decisions to avoid re-scoring the same pairs.
Uses Redis with long TTL (90 days).

Invalidation triggers:
- Concept merged (ID changes)
- Concept fingerprint changed (new aliases, definition update)

Author: Claude Code
Date: 2025-12-26
"""

from __future__ import annotations

import json
import logging
import hashlib
from datetime import datetime
from typing import Optional, Dict, Any, Set, List

import redis

from knowbase.config.settings import get_settings
from .config import REJECT_STORE_CONFIG

logger = logging.getLogger(__name__)


class RejectStore:
    """
    Redis store for REJECT decisions.

    Key format: er:reject:{pair_id}
    Value: JSON with score, timestamp, fingerprints

    Features:
    - Long TTL (90 days default)
    - Fingerprint-based invalidation
    - Bulk operations for efficiency
    """

    def __init__(self, redis_client: Optional[redis.Redis] = None):
        """
        Initialize RejectStore.

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
        self.prefix = REJECT_STORE_CONFIG["redis_prefix"]
        self.ttl_seconds = REJECT_STORE_CONFIG["ttl_days"] * 86400

    def _make_key(self, concept_a_id: str, concept_b_id: str) -> str:
        """Create cache key for a pair (order-independent)."""
        ids = sorted([concept_a_id, concept_b_id])
        pair_id = f"{ids[0]}|{ids[1]}"
        return f"{self.prefix}{pair_id}"

    def _compute_fingerprint(self, name: str, aliases: List[str] = None) -> str:
        """
        Compute fingerprint for invalidation detection.

        Changes in name or aliases should trigger re-evaluation.
        """
        data = name.lower().strip()
        if aliases:
            data += "|" + "|".join(sorted(a.lower().strip() for a in aliases))
        return hashlib.md5(data.encode()).hexdigest()[:16]

    def is_rejected(
        self,
        concept_a_id: str,
        concept_b_id: str,
        fingerprint_a: Optional[str] = None,
        fingerprint_b: Optional[str] = None
    ) -> bool:
        """
        Check if pair was previously rejected.

        Args:
            concept_a_id: First concept ID
            concept_b_id: Second concept ID
            fingerprint_a: Current fingerprint of concept A (for invalidation)
            fingerprint_b: Current fingerprint of concept B (for invalidation)

        Returns:
            True if pair is in reject store and fingerprints match
        """
        key = self._make_key(concept_a_id, concept_b_id)
        try:
            data = self.redis.get(key)
            if not data:
                return False

            parsed = json.loads(data)

            # Check fingerprint invalidation
            if fingerprint_a and fingerprint_b:
                stored_fp_a = parsed.get("fingerprint_a")
                stored_fp_b = parsed.get("fingerprint_b")

                # If fingerprints changed, invalidate
                if stored_fp_a != fingerprint_a or stored_fp_b != fingerprint_b:
                    logger.debug(
                        f"[RejectStore] Fingerprint changed for {key}, invalidating"
                    )
                    self.redis.delete(key)
                    return False

            return True

        except Exception as e:
            logger.warning(f"[RejectStore] Error checking {key}: {e}")
            return False

    def add_reject(
        self,
        concept_a_id: str,
        concept_b_id: str,
        score: float,
        fingerprint_a: str,
        fingerprint_b: str,
        reason: str = ""
    ) -> bool:
        """
        Add a rejected pair.

        Args:
            concept_a_id: First concept ID
            concept_b_id: Second concept ID
            score: The similarity score that led to rejection
            fingerprint_a: Fingerprint of concept A
            fingerprint_b: Fingerprint of concept B
            reason: Optional rejection reason

        Returns:
            True if stored successfully
        """
        key = self._make_key(concept_a_id, concept_b_id)
        data = {
            "score": score,
            "fingerprint_a": fingerprint_a,
            "fingerprint_b": fingerprint_b,
            "reason": reason,
            "rejected_at": datetime.utcnow().isoformat()
        }
        try:
            self.redis.setex(key, self.ttl_seconds, json.dumps(data))
            logger.debug(f"[RejectStore] Added reject: {key} (score={score:.3f})")
            return True
        except Exception as e:
            logger.warning(f"[RejectStore] Error adding {key}: {e}")
            return False

    def add_rejects_batch(
        self,
        rejects: List[Dict[str, Any]]
    ) -> int:
        """
        Add multiple rejected pairs in batch.

        Args:
            rejects: List of dicts with concept_a_id, concept_b_id, score, fingerprints

        Returns:
            Number of successfully stored
        """
        stored = 0
        pipe = self.redis.pipeline()

        for reject in rejects:
            key = self._make_key(reject["concept_a_id"], reject["concept_b_id"])
            data = {
                "score": reject.get("score", 0.0),
                "fingerprint_a": reject.get("fingerprint_a", ""),
                "fingerprint_b": reject.get("fingerprint_b", ""),
                "reason": reject.get("reason", ""),
                "rejected_at": datetime.utcnow().isoformat()
            }
            pipe.setex(key, self.ttl_seconds, json.dumps(data))
            stored += 1

        try:
            pipe.execute()
            logger.info(f"[RejectStore] Batch added {stored} rejects")
            return stored
        except Exception as e:
            logger.warning(f"[RejectStore] Batch error: {e}")
            return 0

    def remove(self, concept_a_id: str, concept_b_id: str) -> bool:
        """Remove a rejected pair (e.g., for re-evaluation)."""
        key = self._make_key(concept_a_id, concept_b_id)
        try:
            return self.redis.delete(key) > 0
        except Exception as e:
            logger.warning(f"[RejectStore] Error removing {key}: {e}")
            return False

    def invalidate_concept(self, concept_id: str) -> int:
        """
        Invalidate all rejects involving a concept.

        Called when concept is merged or significantly changed.

        Args:
            concept_id: Concept ID to invalidate

        Returns:
            Number of keys deleted
        """
        pattern = f"{self.prefix}*{concept_id}*"
        try:
            keys = list(self.redis.scan_iter(match=pattern))
            if keys:
                deleted = self.redis.delete(*keys)
                logger.info(f"[RejectStore] Invalidated {deleted} rejects for {concept_id}")
                return deleted
            return 0
        except Exception as e:
            logger.warning(f"[RejectStore] Error invalidating {concept_id}: {e}")
            return 0

    def get_stats(self) -> Dict[str, Any]:
        """Get store statistics."""
        pattern = f"{self.prefix}*"
        try:
            keys = list(self.redis.scan_iter(match=pattern))
            return {
                "rejected_pairs": len(keys),
                "ttl_days": REJECT_STORE_CONFIG["ttl_days"],
                "prefix": self.prefix,
            }
        except Exception as e:
            logger.warning(f"[RejectStore] Error getting stats: {e}")
            return {"rejected_pairs": 0, "error": str(e)}

    def clear(self) -> int:
        """Clear all rejected pairs."""
        pattern = f"{self.prefix}*"
        try:
            keys = list(self.redis.scan_iter(match=pattern))
            if keys:
                deleted = self.redis.delete(*keys)
                logger.info(f"[RejectStore] Cleared {deleted} rejected pairs")
                return deleted
            return 0
        except Exception as e:
            logger.warning(f"[RejectStore] Error clearing: {e}")
            return 0


# Singleton
_reject_store_instance: Optional[RejectStore] = None


def get_reject_store() -> RejectStore:
    """Get or create RejectStore instance."""
    global _reject_store_instance
    if _reject_store_instance is None:
        _reject_store_instance = RejectStore()
    return _reject_store_instance
