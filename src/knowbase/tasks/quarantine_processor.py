"""
Quarantine Processor: Job automatique pour traiter merges en quarantine
Exécute backfill Qdrant après délai quarantine (défaut 24h)
"""

import logging
from datetime import datetime
from typing import List, Dict, Any

from knowbase.audit.audit_logger import AuditLogger, MergeAuditEntry
from knowbase.tasks.backfill import QdrantBackfillService
from knowbase.common.redis_lock import create_lock

logger = logging.getLogger(__name__)


class QuarantineProcessor:
    """
    Processor pour merges en quarantine

    Fonctionnement:
    1. Récupère merges avec quarantine_until dépassé
    2. Applique backfill Qdrant pour chaque merge
    3. Met à jour status → approved
    4. Logger audit trail

    Job prévu pour exécution toutes les heures (configurable)
    """

    def __init__(self):
        """Initialize quarantine processor"""
        self.audit_logger = AuditLogger()
        self.backfill_service = QdrantBackfillService()

    async def process_quarantine_merges(self) -> Dict[str, Any]:
        """
        Traite tous les merges prêts à sortir de quarantine

        P0.2 PROTECTION: Lock distribué Redis prévient traitement concurrent

        Returns:
            Statistiques traitement (processed, approved, failed)

        Raises:
            TimeoutError: Si lock non acquis (processor déjà en cours ailleurs)
        """
        logger.info("🔄 Démarrage traitement quarantine merges")

        # P0.2: Acquérir lock distribué pour éviter processing concurrent
        # TTL 30min (processing peut prendre plusieurs minutes si 100+ merges)
        lock = create_lock(
            redis_url="redis://redis:6379/5",
            lock_key="quarantine:processor:global",
            ttl_seconds=1800  # 30min
        )

        with lock.context(timeout=30):
            logger.info("🔒 Lock quarantine processor acquis - début traitement")

            try:
                # Récupérer merges prêts
                ready_merges = self.audit_logger.get_quarantine_ready_merges()

                if not ready_merges:
                    logger.info("✅ Aucun merge en quarantine ready (quarantine vide)")
                    logger.info("🔓 Lock quarantine processor libéré")
                    return {
                        "status": "completed",
                        "processed": 0,
                        "approved": 0,
                        "failed": 0,
                        "duration_seconds": 0
                    }

                logger.info(f"📋 {len(ready_merges)} merges prêts pour backfill Qdrant")

                # Traiter chaque merge
                approved_count = 0
                failed_count = 0

                start_time = datetime.utcnow()

                for merge in ready_merges:
                    try:
                        await self._process_single_merge(merge)
                        approved_count += 1

                    except Exception as e:
                        logger.error(
                            f"Erreur traitement merge {merge.merge_id[:12]}...: {e}",
                            exc_info=True
                        )
                        failed_count += 1

                end_time = datetime.utcnow()
                duration = (end_time - start_time).total_seconds()

                result = {
                    "status": "completed",
                    "processed": len(ready_merges),
                    "approved": approved_count,
                    "failed": failed_count,
                    "duration_seconds": round(duration, 2)
                }

                logger.info(
                    f"✅ Quarantine processing terminé: "
                    f"{approved_count} approved, {failed_count} failed "
                    f"(durée {duration:.2f}s)"
                )
                logger.info("🔓 Lock quarantine processor libéré automatiquement")

                return result

            except Exception as e:
                logger.error(f"Erreur critique quarantine processor: {e}", exc_info=True)
                logger.info("🔓 Lock quarantine processor libéré automatiquement (après erreur)")
                return {
                    "status": "failed",
                    "error": str(e),
                    "processed": 0,
                    "approved": 0,
                    "failed": 0
                }

    async def _process_single_merge(self, merge: MergeAuditEntry) -> None:
        """
        Traite un merge individuel

        Args:
            merge: Entrée audit merge à traiter

        Raises:
            Exception: Si traitement échoue
        """
        merge_id = merge.merge_id
        canonical_id = merge.canonical_entity_id
        candidates = merge.candidate_ids

        logger.info(
            f"🔄 Traitement merge {merge_id[:12]}... "
            f"(canonical={canonical_id[:8]}..., {len(candidates)} candidates)"
        )

        # Appeler QdrantBackfillService pour backfill réel
        backfill_result = await self.backfill_service.backfill_canonical_entity(
            canonical_entity_id=canonical_id,
            candidate_ids=candidates,
            merge_id=merge_id
        )

        # Vérifier succès backfill
        if backfill_result["status"] not in ["completed", "skipped"]:
            raise RuntimeError(
                f"Backfill échoué pour merge {merge_id}: "
                f"status={backfill_result['status']} "
                f"success_rate={backfill_result.get('success_rate', 0)}%"
            )

        logger.info(
            f"📦 Backfill terminé: {backfill_result['chunks_updated']} chunks updated "
            f"(p95={backfill_result.get('p95_latency_ms', 0)}ms)"
        )

        # Mettre à jour status → approved
        success = self.audit_logger.update_merge_status(merge_id, "approved")

        if not success:
            raise RuntimeError(f"Échec mise à jour status merge {merge_id}")

        logger.info(f"✅ Merge {merge_id[:12]}... approved (backfill appliqué)")

    def _simulate_qdrant_backfill(self, canonical_id: str, candidate_ids: List[str]) -> None:
        """
        Simule backfill Qdrant (Phase 0)

        En Phase 0.5, sera remplacé par appel QdrantBackfillService réel:
        - Récupérer chunks liés aux candidates
        - Mettre à jour metadata canonical_entity_id
        - Batching 100 chunks/requête
        - Retries exponentiels

        Args:
            canonical_id: ID entité canonique
            candidate_ids: IDs candidates à backfiller
        """
        logger.info(
            f"🔨 [SIMULÉ] Backfill Qdrant: "
            f"canonical={canonical_id[:8]}..., candidates={len(candidate_ids)}"
        )

        # Simulation: ne fait rien en Phase 0
        # En Phase 0.5:
        # backfill_service = QdrantBackfillService()
        # await backfill_service.backfill_canonical_entity(canonical_id, candidate_ids)

    def get_quarantine_stats(self) -> Dict[str, Any]:
        """
        Récupère statistiques quarantine actuelle

        Returns:
            Statistiques (total, ready, waiting)
        """
        try:
            ready_merges = self.audit_logger.get_quarantine_ready_merges()

            # TODO: Compter merges still waiting (quarantine_until > now)
            # Pour l'instant, retourne seulement ready count

            return {
                "quarantine_ready": len(ready_merges),
                "quarantine_waiting": 0,  # TODO: Implémenter count waiting
                "last_check": datetime.utcnow().isoformat()
            }

        except Exception as e:
            logger.error(f"Erreur stats quarantine: {e}", exc_info=True)
            return {
                "quarantine_ready": 0,
                "quarantine_waiting": 0,
                "error": str(e)
            }
