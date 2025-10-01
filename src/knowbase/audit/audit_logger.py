"""
Audit Logger pour tracking opérations canonicalization
Stocke historique merges/undo dans Redis pour traçabilité
"""

import json
import logging
import hashlib
from datetime import datetime, timedelta
from typing import Optional, Dict, Any, List
from dataclasses import dataclass, asdict
import redis

logger = logging.getLogger(__name__)


@dataclass
class MergeAuditEntry:
    """Entrée audit trail pour un merge"""
    merge_id: str
    canonical_entity_id: str
    candidate_ids: List[str]
    user_id: Optional[str]
    executed_at: str
    operation: str  # "merge", "undo_merge"
    reason: Optional[str] = None  # Pour undo
    idempotency_key: Optional[str] = None
    version_metadata: Optional[Dict[str, Any]] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dict for JSON serialization"""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "MergeAuditEntry":
        """Create from dict"""
        return cls(**data)


class AuditLogger:
    """
    Logger audit trail pour opérations canonicalization

    Stockage Redis:
    - Key: audit:merge:{merge_id}
    - TTL: 30 jours (plus long que limite undo 7j)
    - Format: JSON MergeAuditEntry
    """

    def __init__(self, redis_url: str = "redis://redis:6379/3"):
        """
        Initialize audit logger

        Args:
            redis_url: Redis connection (DB 3 pour audit trail)
        """
        self.redis_client = redis.Redis.from_url(redis_url, decode_responses=True)
        self.ttl_seconds = 30 * 24 * 60 * 60  # 30 jours

    def generate_merge_id(self, canonical_id: str, timestamp: str) -> str:
        """
        Génère ID unique pour merge

        Args:
            canonical_id: ID entité canonique
            timestamp: Timestamp ISO

        Returns:
            merge_id (format: merge_<hash>)
        """
        combined = f"{canonical_id}:{timestamp}"
        hash_hex = hashlib.sha256(combined.encode()).hexdigest()[:16]
        return f"merge_{hash_hex}"

    def log_merge(
        self,
        canonical_entity_id: str,
        candidate_ids: List[str],
        user_id: Optional[str],
        idempotency_key: Optional[str] = None,
        version_metadata: Optional[Dict[str, Any]] = None
    ) -> str:
        """
        Log une opération merge dans audit trail

        Args:
            canonical_entity_id: ID entité canonique cible
            candidate_ids: Liste IDs candidates mergées
            user_id: Utilisateur ayant effectué merge
            idempotency_key: Clé idempotence utilisée
            version_metadata: Metadata versioning

        Returns:
            merge_id généré
        """
        timestamp = datetime.utcnow().isoformat()
        merge_id = self.generate_merge_id(canonical_entity_id, timestamp)

        entry = MergeAuditEntry(
            merge_id=merge_id,
            canonical_entity_id=canonical_entity_id,
            candidate_ids=candidate_ids,
            user_id=user_id,
            executed_at=timestamp,
            operation="merge",
            idempotency_key=idempotency_key,
            version_metadata=version_metadata
        )

        try:
            key = f"audit:merge:{merge_id}"
            self.redis_client.setex(
                key,
                self.ttl_seconds,
                json.dumps(entry.to_dict())
            )

            logger.info(
                f"Audit LOG: merge_id={merge_id[:12]}... "
                f"canonical={canonical_entity_id[:8]}... "
                f"candidates={len(candidate_ids)} user={user_id}"
            )

            return merge_id

        except Exception as e:
            logger.error(f"Erreur logging audit merge: {e}", exc_info=True)
            # Ne pas bloquer opération si audit fail
            return merge_id

    def log_undo(
        self,
        merge_id: str,
        reason: str,
        user_id: str
    ) -> str:
        """
        Log une opération undo dans audit trail

        Args:
            merge_id: ID du merge annulé
            reason: Raison annulation
            user_id: Utilisateur ayant effectué undo

        Returns:
            undo_entry_id généré
        """
        timestamp = datetime.utcnow().isoformat()
        undo_id = f"undo_{merge_id}_{hashlib.sha256(timestamp.encode()).hexdigest()[:8]}"

        # Récupérer merge original pour context
        original_merge = self.get_merge_entry(merge_id)

        if not original_merge:
            logger.warning(f"Undo logged mais merge original {merge_id} introuvable")

        entry = MergeAuditEntry(
            merge_id=undo_id,
            canonical_entity_id=original_merge.canonical_entity_id if original_merge else "unknown",
            candidate_ids=original_merge.candidate_ids if original_merge else [],
            user_id=user_id,
            executed_at=timestamp,
            operation="undo_merge",
            reason=reason
        )

        try:
            key = f"audit:undo:{undo_id}"
            self.redis_client.setex(
                key,
                self.ttl_seconds,
                json.dumps(entry.to_dict())
            )

            logger.info(
                f"Audit LOG: undo_id={undo_id[:16]}... "
                f"merge_id={merge_id[:12]}... "
                f"reason='{reason[:50]}...' user={user_id}"
            )

            return undo_id

        except Exception as e:
            logger.error(f"Erreur logging audit undo: {e}", exc_info=True)
            return undo_id

    def get_merge_entry(self, merge_id: str) -> Optional[MergeAuditEntry]:
        """
        Récupère entrée audit pour un merge

        Args:
            merge_id: ID du merge

        Returns:
            MergeAuditEntry ou None si introuvable
        """
        try:
            key = f"audit:merge:{merge_id}"
            data = self.redis_client.get(key)

            if not data:
                logger.warning(f"Audit entry merge {merge_id} introuvable")
                return None

            entry_dict = json.loads(data)
            return MergeAuditEntry.from_dict(entry_dict)

        except Exception as e:
            logger.error(f"Erreur récupération audit merge: {e}", exc_info=True)
            return None

    def is_undo_allowed(self, merge_id: str, max_age_days: int = 7) -> tuple[bool, Optional[str]]:
        """
        Vérifie si undo est autorisé pour un merge

        Args:
            merge_id: ID du merge
            max_age_days: Âge maximum en jours (défaut: 7)

        Returns:
            (allowed: bool, reason: Optional[str])
        """
        entry = self.get_merge_entry(merge_id)

        if not entry:
            return False, f"Merge {merge_id} introuvable dans audit trail"

        # Vérifier âge
        executed_at = datetime.fromisoformat(entry.executed_at)
        age = datetime.utcnow() - executed_at
        max_age = timedelta(days=max_age_days)

        if age > max_age:
            return False, f"Merge trop ancien ({age.days}j > {max_age_days}j max)"

        return True, None

    def get_merge_history(self, canonical_entity_id: str, limit: int = 10) -> List[MergeAuditEntry]:
        """
        Récupère historique merges pour une entité canonique

        Args:
            canonical_entity_id: ID entité canonique
            limit: Nombre max résultats

        Returns:
            Liste MergeAuditEntry triée par date desc
        """
        try:
            # Scan toutes les clés audit:merge:*
            pattern = "audit:merge:*"
            entries = []

            for key in self.redis_client.scan_iter(match=pattern, count=100):
                data = self.redis_client.get(key)
                if data:
                    entry_dict = json.loads(data)
                    entry = MergeAuditEntry.from_dict(entry_dict)

                    if entry.canonical_entity_id == canonical_entity_id:
                        entries.append(entry)

            # Trier par date desc
            entries.sort(key=lambda e: e.executed_at, reverse=True)

            return entries[:limit]

        except Exception as e:
            logger.error(f"Erreur récupération historique: {e}", exc_info=True)
            return []
