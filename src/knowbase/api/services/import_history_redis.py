from __future__ import annotations

import json
import redis
from datetime import datetime
from typing import Any, List, Dict, Optional

from knowbase.config.settings import get_settings


class RedisImportHistoryService:
    """Service pour gérer l'historique des imports avec Redis."""

    def __init__(self):
        self.settings = get_settings()
        # Utiliser la même URL Redis que pour les jobs
        self.redis_client = redis.Redis.from_url(
            "redis://redis:6379/1",  # DB 1 pour l'historique (DB 0 pour les jobs)
            decode_responses=True
        )

    def _get_import_key(self, uid: str) -> str:
        """Retourne la clé Redis pour un import spécifique."""
        return f"import:{uid}"

    def _get_history_key(self) -> str:
        """Retourne la clé Redis pour la liste d'historique."""
        return "import_history:list"

    def add_import_record(
        self,
        uid: str,
        filename: str,
        client: str = None,
        topic: str = None,
        document_type: str = None,
        language: str = None,
        source_date: str = None
    ) -> None:
        """Ajoute un nouvel enregistrement d'import."""
        import_data = {
            "uid": uid,
            "filename": filename,
            "status": "processing",
            "started_at": datetime.now().isoformat(),
            "client": client or "",
            "topic": topic or "",
            "document_type": document_type or "",
            "language": language or "",
            "source_date": source_date or ""
        }

        # Stocker les détails de l'import
        import_key = self._get_import_key(uid)
        self.redis_client.hset(import_key, mapping=import_data)

        # Ajouter à la liste ordonnée par timestamp (plus récent = score plus élevé)
        timestamp_score = datetime.now().timestamp()
        history_key = self._get_history_key()
        self.redis_client.zadd(history_key, {uid: timestamp_score})

        # Optionnel : expiration après 1 an
        self.redis_client.expire(import_key, 365 * 24 * 60 * 60)  # 1 an

    def update_import_status(
        self,
        uid: str,
        status: str,
        chunks_inserted: int = None,
        error_message: str = None
    ) -> None:
        """Met à jour le statut d'un import."""
        import_key = self._get_import_key(uid)

        # Vérifier si l'import existe
        if not self.redis_client.exists(import_key):
            return

        update_data = {"status": status}

        # Si terminé, calculer la durée
        if status in ["completed", "done", "failed"]:
            update_data["completed_at"] = datetime.now().isoformat()

            # Calculer la durée si on a la date de début
            started_at_str = self.redis_client.hget(import_key, "started_at")
            if started_at_str:
                try:
                    started = datetime.fromisoformat(started_at_str)
                    completed = datetime.now()
                    duration = int((completed - started).total_seconds())
                    update_data["duration"] = str(duration)
                except (ValueError, TypeError):
                    pass

        if chunks_inserted is not None:
            update_data["chunks_inserted"] = str(chunks_inserted)

        if error_message:
            update_data["error_message"] = error_message

        # Mettre à jour les données
        self.redis_client.hset(import_key, mapping=update_data)

    def get_history(self, limit: int = 100) -> List[Dict[str, Any]]:
        """Récupère l'historique des imports (plus récents en premier)."""
        history_key = self._get_history_key()

        # Récupérer les UIDs par ordre décroissant de timestamp
        uids = self.redis_client.zrevrange(history_key, 0, limit - 1)

        history = []
        for uid in uids:
            import_key = self._get_import_key(uid)
            import_data = self.redis_client.hgetall(import_key)

            if import_data:
                # Convertir les strings en types appropriés
                processed_data = dict(import_data)

                # Convertir chunks_inserted en int si présent
                if "chunks_inserted" in processed_data:
                    try:
                        processed_data["chunks_inserted"] = int(processed_data["chunks_inserted"])
                    except (ValueError, TypeError):
                        pass

                # Convertir duration en int si présent
                if "duration" in processed_data:
                    try:
                        processed_data["duration"] = int(processed_data["duration"])
                    except (ValueError, TypeError):
                        pass

                history.append(processed_data)

        return history

    def get_active_imports(self) -> List[Dict[str, Any]]:
        """Récupère les imports actifs (en cours de traitement)."""
        # Importer ici pour éviter les imports circulaires
        from knowbase.ingestion.queue import fetch_job

        # Récupérer tous les imports récents (dernières 24h)
        history_key = self._get_history_key()
        cutoff_timestamp = datetime.now().timestamp() - (24 * 60 * 60)  # 24h
        recent_uids = self.redis_client.zrangebyscore(
            history_key,
            cutoff_timestamp,
            "+inf"
        )

        active_imports = []
        active_statuses = ["processing", "in_progress", "pending", "queued"]

        for uid in recent_uids:
            import_key = self._get_import_key(uid)
            import_data = self.redis_client.hgetall(import_key)

            if import_data and import_data.get("status") in active_statuses:
                # Vérifier le statut réel du job RQ
                job = fetch_job(uid)
                if job:
                    job_status = job.get_status(refresh=True)
                    if job.is_finished:
                        # Mettre à jour le statut si le job est terminé
                        result = job.result if isinstance(job.result, dict) else {}
                        chunks = result.get("chunks_inserted", 0) if result else 0
                        self.update_import_status(
                            uid,
                            "completed",
                            chunks_inserted=chunks
                        )
                        continue  # Ne pas ajouter aux imports actifs
                    elif job.is_failed:
                        # Mettre à jour le statut si le job a échoué
                        error_msg = str(job.exc_info) if job.exc_info else "Erreur inconnue"
                        self.update_import_status(
                            uid,
                            "failed",
                            error_message=error_msg
                        )
                        continue  # Ne pas ajouter aux imports actifs
                else:
                    # Job non trouvé, considérer comme failed
                    self.update_import_status(uid, "failed", error_message="Job non trouvé")
                    continue  # Ne pas ajouter aux imports actifs

                # Convertir en format approprié
                processed_data = dict(import_data)
                if "chunks_inserted" in processed_data:
                    try:
                        processed_data["chunks_inserted"] = int(processed_data["chunks_inserted"])
                    except (ValueError, TypeError):
                        pass

                # Enrichir avec les détails de progression du job RQ
                if job and hasattr(job, 'meta') and job.meta:
                    current_step = job.meta.get("current_step")
                    progress = job.meta.get("progress", 0)
                    total_steps = job.meta.get("total_steps", 0)
                    step_message = job.meta.get("step_message", "")

                    if current_step:
                        processed_data.update({
                            "current_step": current_step,
                            "progress": progress,
                            "total_steps": total_steps,
                            "step_message": step_message,
                            "progress_percentage": round((progress / total_steps) * 100) if total_steps > 0 else 0
                        })

                active_imports.append(processed_data)

        return active_imports

    def cleanup_old_records(self, days: int = 30) -> int:
        """Nettoie les anciens enregistrements (plus de X jours)."""
        history_key = self._get_history_key()
        cutoff_timestamp = datetime.now().timestamp() - (days * 24 * 60 * 60)

        # Récupérer les UIDs anciens
        old_uids = self.redis_client.zrangebyscore(history_key, "-inf", cutoff_timestamp)

        deleted_count = 0
        for uid in old_uids:
            import_key = self._get_import_key(uid)

            # Supprimer les données de l'import
            if self.redis_client.delete(import_key):
                deleted_count += 1

            # Supprimer de la liste d'historique
            self.redis_client.zrem(history_key, uid)

        return deleted_count

    def get_import_by_uid(self, uid: str) -> Optional[Dict[str, Any]]:
        """Récupère un import spécifique par son UID."""
        import_key = self._get_import_key(uid)
        import_data = self.redis_client.hgetall(import_key)

        if not import_data:
            return None

        # Convertir en format approprié
        processed_data = dict(import_data)
        if "chunks_inserted" in processed_data:
            try:
                processed_data["chunks_inserted"] = int(processed_data["chunks_inserted"])
            except (ValueError, TypeError):
                pass

        if "duration" in processed_data:
            try:
                processed_data["duration"] = int(processed_data["duration"])
            except (ValueError, TypeError):
                pass

        return processed_data


# Instance globale du service
redis_import_history_service = RedisImportHistoryService()


def get_redis_import_history_service() -> RedisImportHistoryService:
    """Retourne l'instance du service d'historique Redis."""
    return redis_import_history_service


__all__ = ["RedisImportHistoryService", "get_redis_import_history_service", "redis_import_history_service"]