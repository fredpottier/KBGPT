"""
Qdrant Backfill Service: Mise à jour massive chunks avec canonical_entity_id
Batching 100 chunks/requête + retries exponentiels + exactly-once semantics
"""

import logging
import time
import redis
from datetime import datetime
from typing import List, Dict, Any, Optional
from qdrant_client import QdrantClient
from qdrant_client.models import Filter, FieldCondition, MatchAny

from knowbase.common.clients.qdrant_client import get_qdrant_client
from knowbase.config.settings import get_settings

logger = logging.getLogger(__name__)


class QdrantBackfillService:
    """
    Service backfill Qdrant pour canonicalisation

    Fonctionnalités:
    1. Batching 100 chunks par requête (limite charge Qdrant)
    2. Retries exponentiels (max 3 attempts, backoff 2^n secondes)
    3. Exactly-once semantics via tracking Redis
    4. Monitoring performance (p95 latence <100ms par batch)

    Usage:
        service = QdrantBackfillService()
        result = await service.backfill_canonical_entity(
            canonical_entity_id="canon_123",
            candidate_ids=["cand_1", "cand_2", "cand_3"]
        )
    """

    def __init__(
        self,
        batch_size: int = 100,
        max_retries: int = 3,
        redis_url: str = "redis://redis:6379/4"
    ):
        """
        Initialize backfill service

        Args:
            batch_size: Nombre chunks par batch (défaut: 100)
            max_retries: Nombre max tentatives (défaut: 3)
            redis_url: URL Redis pour tracking (DB 4 dédiée backfill)
        """
        self.qdrant_client = get_qdrant_client()
        self.redis_client = redis.Redis.from_url(redis_url, decode_responses=True)
        self.batch_size = batch_size
        self.max_retries = max_retries

        settings = get_settings()
        self.collection_name = settings.qdrant_collection

        logger.info(
            f"QdrantBackfillService initialized: "
            f"batch_size={batch_size}, max_retries={max_retries}, "
            f"collection={self.collection_name}"
        )

    async def backfill_canonical_entity(
        self,
        canonical_entity_id: str,
        candidate_ids: List[str],
        merge_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Backfill chunks Qdrant avec canonical_entity_id

        Logique:
        1. Pour chaque candidate_id, récupérer chunks liés (via entity_id metadata)
        2. Mettre à jour metadata: ajouter canonical_entity_id
        3. Batching 100 chunks/requête
        4. Tracking Redis pour exactly-once semantics
        5. Retries exponentiels si échec

        Args:
            canonical_entity_id: UUID entité canonique
            candidate_ids: Liste UUIDs candidates sources
            merge_id: ID du merge (pour tracking audit)

        Returns:
            Dict avec statistiques backfill (chunks_updated, batches, duration, etc.)

        Raises:
            RuntimeError: Si backfill échoue après max_retries
        """
        start_time = time.time()

        logger.info(
            f"🔄 Backfill démarré: canonical={canonical_entity_id[:8]}... "
            f"candidates={len(candidate_ids)} merge_id={merge_id[:12] if merge_id else 'none'}..."
        )

        # Vérifier si backfill déjà effectué (exactly-once)
        tracking_key = f"backfill:completed:{canonical_entity_id}"
        if self.redis_client.exists(tracking_key):
            logger.info(
                f"⏭️ Backfill déjà effectué pour canonical={canonical_entity_id[:8]}... (skip)"
            )
            return {
                "status": "skipped",
                "reason": "already_completed",
                "canonical_entity_id": canonical_entity_id,
                "chunks_updated": 0,
                "chunks_total": 0,
                "batches": 0,
                "batches_failed": 0,
                "success_rate": 100.0,
                "duration_seconds": 0,
                "p95_latency_ms": 0.0,
                "avg_latency_ms": 0.0
            }

        # Récupérer chunks liés aux candidates
        all_chunk_ids = []
        for candidate_id in candidate_ids:
            chunk_ids = self._get_chunks_for_entity(candidate_id)
            all_chunk_ids.extend(chunk_ids)
            logger.info(
                f"  Candidate {candidate_id[:8]}... → {len(chunk_ids)} chunks"
            )

        if not all_chunk_ids:
            logger.warning(
                f"⚠️ Aucun chunk trouvé pour candidates {candidate_ids} "
                f"(canonical={canonical_entity_id[:8]}...)"
            )
            # Marquer comme completed même si 0 chunks (exactly-once)
            self.redis_client.setex(
                tracking_key,
                30 * 24 * 60 * 60,  # 30 jours
                datetime.utcnow().isoformat()
            )
            return {
                "status": "completed",
                "canonical_entity_id": canonical_entity_id,
                "chunks_updated": 0,
                "chunks_total": 0,
                "batches": 0,
                "batches_failed": 0,
                "success_rate": 100.0,
                "duration_seconds": round(time.time() - start_time, 2),
                "p95_latency_ms": 0.0,
                "avg_latency_ms": 0.0,
                "warning": "no_chunks_found"
            }

        logger.info(f"📦 Total chunks à backfiller: {len(all_chunk_ids)}")

        # Batching 100 chunks/requête
        batches = self._create_batches(all_chunk_ids, self.batch_size)
        total_updated = 0
        failed_batches = []
        batch_latencies = []

        for batch_idx, batch_chunk_ids in enumerate(batches, start=1):
            try:
                # Mettre à jour batch avec retries exponentiels
                batch_start = time.time()
                updated_count = self._update_batch_with_retries(
                    chunk_ids=batch_chunk_ids,
                    canonical_entity_id=canonical_entity_id
                )
                batch_latency = time.time() - batch_start
                batch_latencies.append(batch_latency)

                total_updated += updated_count

                logger.info(
                    f"  Batch {batch_idx}/{len(batches)}: "
                    f"{updated_count} chunks updated "
                    f"({batch_latency*1000:.1f}ms)"
                )

            except Exception as e:
                logger.error(
                    f"  Batch {batch_idx}/{len(batches)} failed: {e}",
                    exc_info=True
                )
                failed_batches.append(batch_idx)

        # Calculer statistiques
        duration = time.time() - start_time
        success_rate = (
            (len(batches) - len(failed_batches)) / len(batches) * 100
            if batches else 0
        )

        # Calculer p95 latence
        p95_latency = self._calculate_p95(batch_latencies) if batch_latencies else 0

        # Marquer backfill comme completed (TTL 30 jours)
        self.redis_client.setex(
            tracking_key,
            30 * 24 * 60 * 60,  # 30 jours
            datetime.utcnow().isoformat()
        )

        result = {
            "status": "completed" if not failed_batches else "partial",
            "canonical_entity_id": canonical_entity_id,
            "chunks_updated": total_updated,
            "chunks_total": len(all_chunk_ids),
            "batches": len(batches),
            "batches_failed": len(failed_batches),
            "success_rate": round(success_rate, 2),
            "duration_seconds": round(duration, 2),
            "p95_latency_ms": round(p95_latency * 1000, 1),
            "avg_latency_ms": round(sum(batch_latencies) / len(batch_latencies) * 1000, 1) if batch_latencies else 0
        }

        if failed_batches:
            result["failed_batch_indices"] = failed_batches

        logger.info(
            f"✅ Backfill terminé: "
            f"canonical={canonical_entity_id[:8]}... "
            f"updated={total_updated}/{len(all_chunk_ids)} "
            f"batches={len(batches)} "
            f"success_rate={success_rate:.1f}% "
            f"p95={p95_latency*1000:.1f}ms "
            f"duration={duration:.2f}s"
        )

        return result

    def _get_chunks_for_entity(self, entity_id: str) -> List[str]:
        """
        Récupère chunks IDs liés à une entité

        En Phase 0: Simulation (retourne IDs fictifs)
        En Phase 1+: Vraie requête Qdrant avec filtre sur entity_id metadata

        Args:
            entity_id: UUID entité

        Returns:
            Liste chunk IDs
        """
        # TODO Phase 1: Vraie implémentation avec Qdrant scroll
        # filter_condition = Filter(
        #     must=[
        #         FieldCondition(
        #             key="entity_id",
        #             match=MatchAny(any=[entity_id])
        #         )
        #     ]
        # )
        #
        # points, _ = self.qdrant_client.scroll(
        #     collection_name=self.collection_name,
        #     scroll_filter=filter_condition,
        #     limit=10000,  # Max chunks par entité
        #     with_payload=False,  # Seulement IDs
        #     with_vectors=False
        # )
        #
        # return [str(point.id) for point in points]

        # Phase 0: Simulation (10-1000 chunks par entité)
        import hashlib
        hash_val = int(hashlib.sha256(entity_id.encode()).hexdigest(), 16)
        num_chunks = 10 + (hash_val % 990)  # 10-1000 chunks

        return [f"chunk_{entity_id[:8]}_{i}" for i in range(num_chunks)]

    def _create_batches(self, items: List[str], batch_size: int) -> List[List[str]]:
        """
        Découpe liste en batches de taille batch_size

        Args:
            items: Liste items à batching
            batch_size: Taille max batch

        Returns:
            Liste de batches
        """
        return [
            items[i:i + batch_size]
            for i in range(0, len(items), batch_size)
        ]

    def _update_batch_with_retries(
        self,
        chunk_ids: List[str],
        canonical_entity_id: str
    ) -> int:
        """
        Met à jour batch de chunks avec retries exponentiels

        Args:
            chunk_ids: Liste chunk IDs à mettre à jour
            canonical_entity_id: UUID entité canonique

        Returns:
            Nombre chunks mis à jour avec succès

        Raises:
            RuntimeError: Si échec après max_retries
        """
        last_exception = None

        for attempt in range(1, self.max_retries + 1):
            try:
                # Mettre à jour payload Qdrant
                updated_count = self._update_chunks_payload(
                    chunk_ids=chunk_ids,
                    canonical_entity_id=canonical_entity_id
                )

                return updated_count

            except Exception as e:
                last_exception = e

                if attempt < self.max_retries:
                    # Backoff exponentiel: 2^attempt secondes
                    backoff_seconds = 2 ** attempt
                    logger.warning(
                        f"⚠️ Batch update failed (attempt {attempt}/{self.max_retries}): {e}. "
                        f"Retrying in {backoff_seconds}s..."
                    )
                    time.sleep(backoff_seconds)
                else:
                    logger.error(
                        f"❌ Batch update failed after {self.max_retries} attempts: {e}",
                        exc_info=True
                    )

        raise RuntimeError(
            f"Batch update failed after {self.max_retries} attempts: {last_exception}"
        )

    def _update_chunks_payload(
        self,
        chunk_ids: List[str],
        canonical_entity_id: str
    ) -> int:
        """
        Met à jour payload chunks dans Qdrant

        Ajoute champ canonical_entity_id dans metadata

        Args:
            chunk_ids: Liste chunk IDs
            canonical_entity_id: UUID entité canonique

        Returns:
            Nombre chunks mis à jour
        """
        # TODO Phase 1: Vraie implémentation Qdrant set_payload
        # self.qdrant_client.set_payload(
        #     collection_name=self.collection_name,
        #     payload={
        #         "canonical_entity_id": canonical_entity_id,
        #         "backfilled_at": datetime.utcnow().isoformat()
        #     },
        #     points=chunk_ids
        # )

        # Phase 0: Simulation (réussite immédiate)
        logger.debug(
            f"[SIMULÉ] set_payload: {len(chunk_ids)} chunks → "
            f"canonical_entity_id={canonical_entity_id[:8]}..."
        )

        return len(chunk_ids)

    def _calculate_p95(self, latencies: List[float]) -> float:
        """
        Calcule p95 latence

        Args:
            latencies: Liste latences (secondes)

        Returns:
            P95 latence (secondes)
        """
        if not latencies:
            return 0.0

        sorted_latencies = sorted(latencies)
        p95_index = int(len(sorted_latencies) * 0.95)

        return sorted_latencies[p95_index]

    def get_backfill_stats(self, canonical_entity_id: str) -> Dict[str, Any]:
        """
        Récupère statistiques backfill pour une entité

        Args:
            canonical_entity_id: UUID entité canonique

        Returns:
            Dict avec stats (completed, completed_at)
        """
        tracking_key = f"backfill:completed:{canonical_entity_id}"
        completed_at = self.redis_client.get(tracking_key)

        return {
            "canonical_entity_id": canonical_entity_id,
            "backfill_completed": completed_at is not None,
            "completed_at": completed_at
        }
