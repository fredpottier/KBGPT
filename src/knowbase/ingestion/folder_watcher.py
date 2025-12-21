"""
🌊 OSMOSE Phase 3 - Folder Watcher Service

Service de surveillance de répertoire pour ingestion automatique.
Surveille data/watch/ et copie les fichiers vers data/docs_in/ pour traitement.

Flux simplifié:
    watch/ → docs_in/ → [worker] → docs_done/

Usage:
    python -m knowbase.ingestion.folder_watcher

Formats supportés:
    - PDF (.pdf)
    - PowerPoint (.pptx, .ppt)
    - Excel (.xlsx, .xls)
"""

from __future__ import annotations

import logging
import shutil
import time
import uuid
from pathlib import Path
from typing import Optional

from watchdog.observers.polling import PollingObserver
from watchdog.events import FileSystemEventHandler, FileCreatedEvent, FileMovedEvent

# Configuration logging
logging.basicConfig(
    level=logging.INFO,
    format="[OSMOSE] %(asctime)s - %(levelname)s - %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)

# Répertoires
WATCH_DIR = Path("/data/watch")
DOCS_IN_DIR = Path("/data/docs_in")

# Extensions supportées par type
SUPPORTED_EXTENSIONS = {
    ".pdf": "pdf",
    ".pptx": "pptx",
    ".ppt": "pptx",
    ".xlsx": "excel",
    ".xls": "excel",
}

# Délai avant traitement (pour s'assurer que le fichier est complètement copié)
STABILIZATION_DELAY_SECONDS = 2


def get_file_type(file_path: Path) -> Optional[str]:
    """Détermine le type de fichier basé sur l'extension."""
    ext = file_path.suffix.lower()
    return SUPPORTED_EXTENSIONS.get(ext)


def generate_job_id(file_path: Path) -> str:
    """Génère un job_id unique pour le fichier."""
    return f"watch-{file_path.stem}-{uuid.uuid4().hex[:8]}"


def wait_for_file_stability(file_path: Path, delay: float = STABILIZATION_DELAY_SECONDS) -> bool:
    """
    Attend que le fichier soit stable (taille ne change plus).
    Retourne True si le fichier est stable, False si disparu.
    """
    if not file_path.exists():
        return False

    initial_size = file_path.stat().st_size
    time.sleep(delay)

    if not file_path.exists():
        return False

    final_size = file_path.stat().st_size
    return initial_size == final_size


def enqueue_file(file_path: Path) -> bool:
    """
    Met un fichier en queue d'ingestion.
    Le fichier doit être dans docs_in/.
    Retourne True si succès, False sinon.
    """
    from knowbase.ingestion.queue.dispatcher import (
        enqueue_pdf_ingestion,
        enqueue_pptx_ingestion,
        enqueue_excel_ingestion,
    )
    from knowbase.api.services.import_history_redis import get_redis_import_history_service

    file_type = get_file_type(file_path)
    if not file_type:
        logger.warning(f"Type non supporté: {file_path.name}")
        return False

    job_id = generate_job_id(file_path)
    file_str = str(file_path)

    # Enregistrer dans l'historique Redis AVANT l'enqueue
    try:
        history_service = get_redis_import_history_service()
        history_service.add_import_record(
            uid=job_id,
            filename=file_path.name,
            document_type=file_type,
            import_type="folder_watcher"
        )
        logger.info(f"Import enregistré dans l'historique: {job_id}")
    except Exception as hist_error:
        logger.warning(f"Erreur enregistrement historique (non bloquant): {hist_error}")

    try:
        if file_type == "pdf":
            enqueue_pdf_ingestion(
                job_id=job_id,
                file_path=file_str,
                use_vision=True,
            )
            logger.info(f"PDF ajouté à la queue: {file_path.name} (job_id={job_id})")

        elif file_type == "pptx":
            enqueue_pptx_ingestion(
                job_id=job_id,
                file_path=file_str,
                use_vision=True,
            )
            logger.info(f"PPTX ajouté à la queue: {file_path.name} (job_id={job_id})")

        elif file_type == "excel":
            enqueue_excel_ingestion(
                job_id=job_id,
                file_path=file_str,
            )
            logger.info(f"Excel ajouté à la queue: {file_path.name} (job_id={job_id})")

        return True

    except Exception as e:
        logger.error(f"Erreur enqueue {file_path.name}: {e}")
        return False


class WatchHandler(FileSystemEventHandler):
    """Handler pour les événements fichier dans le répertoire surveillé."""

    def __init__(self):
        super().__init__()
        self._processing_files: set[str] = set()

    def _should_process(self, file_path: Path) -> bool:
        """Vérifie si le fichier doit être traité."""
        if file_path.name.startswith("."):
            return False
        if file_path.name.startswith("~"):
            return False
        if file_path.name.endswith(".tmp"):
            return False
        return get_file_type(file_path) is not None

    def _process_file(self, file_path: Path) -> None:
        """Traite un nouveau fichier détecté."""
        path_str = str(file_path)

        if path_str in self._processing_files:
            return
        self._processing_files.add(path_str)

        try:
            logger.info(f"Nouveau fichier détecté: {file_path.name}")

            if not wait_for_file_stability(file_path):
                logger.warning(f"Fichier disparu ou instable: {file_path.name}")
                return

            # Copier vers docs_in/
            DOCS_IN_DIR.mkdir(parents=True, exist_ok=True)
            dest_path = DOCS_IN_DIR / file_path.name

            if dest_path.exists():
                base = file_path.stem
                ext = file_path.suffix
                dest_path = DOCS_IN_DIR / f"{base}_{uuid.uuid4().hex[:6]}{ext}"

            shutil.copy2(str(file_path), str(dest_path))
            logger.info(f"Copié vers docs_in/: {dest_path.name}")

            # Enqueue pour ingestion
            success = enqueue_file(dest_path)

            if success:
                file_path.unlink()
                logger.info(f"Fichier traité: {file_path.name} -> queue")
            else:
                dest_path.unlink()
                logger.error(f"Échec enqueue, fichier conservé: {file_path.name}")

        except Exception as e:
            logger.error(f"Erreur traitement {file_path.name}: {e}")

        finally:
            self._processing_files.discard(path_str)

    def on_created(self, event: FileCreatedEvent) -> None:
        if event.is_directory:
            return
        file_path = Path(event.src_path)
        if self._should_process(file_path):
            self._process_file(file_path)

    def on_moved(self, event: FileMovedEvent) -> None:
        if event.is_directory:
            return
        file_path = Path(event.dest_path)
        if self._should_process(file_path):
            self._process_file(file_path)


def process_existing_files() -> int:
    """Traite les fichiers existants dans le répertoire watch."""
    if not WATCH_DIR.exists():
        return 0

    count = 0
    handler = WatchHandler()

    for file_path in WATCH_DIR.iterdir():
        if file_path.is_file() and handler._should_process(file_path):
            logger.info(f"Fichier existant trouvé: {file_path.name}")
            handler._process_file(file_path)
            count += 1

    return count


def run_watcher() -> None:
    """Lance le service de surveillance."""
    logger.info("=" * 60)
    logger.info("OSMOSE Folder Watcher - Démarrage")
    logger.info("=" * 60)

    WATCH_DIR.mkdir(parents=True, exist_ok=True)
    DOCS_IN_DIR.mkdir(parents=True, exist_ok=True)

    logger.info(f"Répertoire surveillé: {WATCH_DIR}")
    logger.info(f"Destination: {DOCS_IN_DIR}")
    logger.info(f"Formats supportés: {', '.join(SUPPORTED_EXTENSIONS.keys())}")

    existing_count = process_existing_files()
    if existing_count > 0:
        logger.info(f"Fichiers existants traités: {existing_count}")

    handler = WatchHandler()
    observer = PollingObserver(timeout=5)  # Polling toutes les 5s (requis pour Docker/Windows)
    observer.schedule(handler, str(WATCH_DIR), recursive=False)
    observer.start()

    logger.info("Surveillance active - En attente de fichiers...")
    logger.info("Déposez vos fichiers dans: data/watch/")

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        logger.info("Arrêt demandé...")
        observer.stop()

    observer.join()
    logger.info("Folder Watcher arrêté")


if __name__ == "__main__":
    run_watcher()
