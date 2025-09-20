from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any, List, Dict

from knowbase.config.settings import get_settings
from knowbase.ingestion.queue import fetch_job


class ImportHistoryService:
    """Service pour gérer l'historique des imports."""

    def __init__(self):
        self.settings = get_settings()
        self.history_file = self._get_history_file_path()

    def _get_history_file_path(self) -> Path:
        """Retourne le chemin du fichier d'historique."""
        data_dir = self.settings.data_dir
        data_dir.mkdir(parents=True, exist_ok=True)
        return data_dir / "import_history.json"

    def _load_history(self) -> List[Dict[str, Any]]:
        """Charge l'historique depuis le fichier JSON."""
        if not self.history_file.exists():
            return []

        try:
            with open(self.history_file, 'r', encoding='utf-8') as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            return []

    def _save_history(self, history: List[Dict[str, Any]]) -> None:
        """Sauvegarde l'historique dans le fichier JSON."""
        try:
            with open(self.history_file, 'w', encoding='utf-8') as f:
                json.dump(history, f, indent=2, ensure_ascii=False, default=str)
        except IOError as e:
            print(f"Erreur lors de la sauvegarde de l'historique: {e}")

    def add_import_record(
        self,
        uid: str,
        filename: str,
        client: str = None,
        topic: str = None,
        document_type: str = None,
        language: str = None,
        source_date: str = None,
        solution: str = None,
        import_type: str = None
    ) -> None:
        """Ajoute un nouvel enregistrement d'import."""
        history = self._load_history()

        record = {
            "uid": uid,
            "filename": filename,
            "status": "processing",
            "started_at": datetime.now().isoformat(),
            "client": client,
            "topic": topic,
            "document_type": document_type,
            "language": language,
            "source_date": source_date,
            "solution": solution,
            "import_type": import_type
        }

        # Ajouter au début de la liste (plus récent en premier)
        history.insert(0, record)

        # Garder seulement les 1000 derniers enregistrements
        if len(history) > 1000:
            history = history[:1000]

        self._save_history(history)

    def update_import_status(
        self,
        uid: str,
        status: str,
        chunks_inserted: int = None,
        error_message: str = None
    ) -> None:
        """Met à jour le statut d'un import."""
        history = self._load_history()

        for record in history:
            if record["uid"] == uid:
                record["status"] = status
                if status in ["completed", "done", "failed"]:
                    record["completed_at"] = datetime.now().isoformat()
                    if record.get("started_at"):
                        try:
                            started = datetime.fromisoformat(record["started_at"])
                            completed = datetime.now()
                            duration = int((completed - started).total_seconds())
                            record["duration"] = duration
                        except (ValueError, TypeError):
                            pass

                if chunks_inserted is not None:
                    record["chunks_inserted"] = chunks_inserted

                if error_message:
                    record["error_message"] = error_message

                break

        self._save_history(history)

    def get_history(self, limit: int = 100) -> List[Dict[str, Any]]:
        """Récupère l'historique des imports."""
        history = self._load_history()
        return history[:limit]

    def get_active_imports(self) -> List[Dict[str, Any]]:
        """Récupère les imports actifs (en cours de traitement)."""
        history = self._load_history()
        active_statuses = ["processing", "in_progress", "pending", "queued"]

        active_imports = []
        for record in history:
            if record.get("status") in active_statuses:
                # Vérifier le statut réel du job
                job = fetch_job(record["uid"])
                if job:
                    job_status = job.get_status(refresh=True)
                    if job.is_finished:
                        # Mettre à jour le statut si le job est terminé
                        result = job.result if isinstance(job.result, dict) else {}
                        chunks = result.get("chunks_inserted", 0) if result else 0
                        self.update_import_status(
                            record["uid"],
                            "completed",
                            chunks_inserted=chunks
                        )
                    elif job.is_failed:
                        self.update_import_status(
                            record["uid"],
                            "failed",
                            error_message=str(job.exc_info) if job.exc_info else "Erreur inconnue"
                        )
                    else:
                        active_imports.append(record)
                else:
                    # Job non trouvé, considérer comme failed
                    self.update_import_status(record["uid"], "failed", error_message="Job non trouvé")

        return active_imports

    def cleanup_old_records(self, days: int = 30) -> int:
        """Nettoie les anciens enregistrements (plus de X jours)."""
        history = self._load_history()
        cutoff_date = datetime.now().timestamp() - (days * 24 * 60 * 60)

        initial_count = len(history)
        filtered_history = []

        for record in history:
            try:
                started_at = datetime.fromisoformat(record["started_at"])
                if started_at.timestamp() >= cutoff_date:
                    filtered_history.append(record)
            except (ValueError, TypeError, KeyError):
                # Garder les enregistrements avec des dates invalides
                filtered_history.append(record)

        self._save_history(filtered_history)
        return initial_count - len(filtered_history)


# Instance globale du service
import_history_service = ImportHistoryService()


def get_import_history_service() -> ImportHistoryService:
    """Retourne l'instance du service d'historique."""
    return import_history_service


__all__ = ["ImportHistoryService", "get_import_history_service", "import_history_service"]