from __future__ import annotations

import os
import socket
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from rq import get_current_job

from knowbase.config.settings import get_settings
from knowbase.ingestion.pipelines import (
    excel_pipeline,
    pdf_pipeline,
    pptx_pipeline,
)
from knowbase.common.logging import setup_logging


SETTINGS = get_settings()
PRESENTATIONS_DIR = SETTINGS.presentations_dir
logger = setup_logging(SETTINGS.logs_dir, "jobs.log")


def _ensure_exists(path: Path) -> Path:
    if not path.exists():
        raise FileNotFoundError(f"File not found: {path}")
    return path


def send_worker_heartbeat():
    """Envoie un heartbeat pour signaler que le worker est toujours actif."""
    job = get_current_job()
    if job:
        worker_id = f"{socket.gethostname()}:{os.getpid()}"
        job.meta.update({
            "last_heartbeat": datetime.now().timestamp(),
            "worker_id": worker_id
        })
        job.save()


def update_job_progress(step: str, progress: int = 0, total_steps: int = 0, message: str = ""):
    """Met à jour la progression du job actuel et envoie un heartbeat."""
    job = get_current_job()
    if job:
        worker_id = f"{socket.gethostname()}:{os.getpid()}"
        job.meta.update({
            "current_step": step,
            "progress": progress,
            "total_steps": total_steps,
            "step_message": message,
            "detailed_status": "processing",
            "last_heartbeat": datetime.now().timestamp(),
            "worker_id": worker_id
        })
        job.save()


def mark_job_as_processing():
    """Marque le job comme en cours de traitement dans l'historique Redis et initialise le heartbeat."""
    from knowbase.api.services.import_history_redis import get_redis_import_history_service
    from rq import get_current_job

    job = get_current_job()
    if job:
        # Initialiser le heartbeat et worker_id
        send_worker_heartbeat()

        # Mettre à jour l'historique
        history_service = get_redis_import_history_service()
        history_service.update_import_status(
            uid=job.id,
            status="processing"
        )


def auto_deduplicate_entities(tenant_id: str = "default") -> None:
    """
    Dé-duplication automatique des entités après un import.

    Cette fonction est appelée automatiquement à la fin de chaque import
    pour nettoyer les entités en doublon dans Neo4j.

    Si la dé-duplication échoue, cela ne fait pas échouer le job d'import
    (c'est une opération de nettoyage optionnelle).
    """
    try:
        logger.info("🧹 Démarrage de la dé-duplication automatique des entités...")

        from knowbase.api.services.knowledge_graph_service import KnowledgeGraphService

        kg_service = KnowledgeGraphService(tenant_id=tenant_id)
        stats = kg_service.deduplicate_entities_by_name(
            tenant_id=tenant_id,
            dry_run=False  # Exécution réelle
        )

        if stats["duplicate_groups"] > 0:
            logger.info(
                f"✅ Dé-duplication automatique terminée: "
                f"{stats['duplicate_groups']} groupes traités, "
                f"{stats['entities_to_merge']} entités fusionnées, "
                f"{stats['relations_updated']} relations réassignées"
            )
        else:
            logger.info("✅ Aucun doublon détecté, base Neo4j déjà propre")

    except Exception as e:
        # Ne pas faire échouer le job si la dé-duplication échoue
        logger.warning(f"⚠️ Échec de la dé-duplication automatique (non bloquant): {e}")
        import traceback
        logger.debug(traceback.format_exc())


def ingest_pptx_job(
    *,
    pptx_path: str,
    document_type_id: Optional[str] = None,
    meta_path: Optional[str] = None,
    use_vision: bool = True,
) -> dict[str, Any]:
    try:
        # Marquer comme en cours de traitement
        mark_job_as_processing()
        update_job_progress("Initialisation", 0, 6, "Vérification du fichier PowerPoint")
        path = _ensure_exists(Path(pptx_path))

        update_job_progress("Préparation", 1, 6, "Préparation des métadonnées")
        if meta_path:
            meta_file = Path(meta_path)
            if meta_file.exists():
                target = path.with_suffix(".meta.json")
                if meta_file != target:
                    meta_file.replace(target)

        update_job_progress("Traitement", 2, 6, "Traitement du document PowerPoint")
        result = pptx_pipeline.process_pptx(path, document_type_id=document_type_id, use_vision=use_vision, progress_callback=update_job_progress)

        update_job_progress("Finalisation", 6, 6, "Import terminé avec succès")
        destination = pptx_pipeline.DOCS_DONE / f"{path.stem}.pptx"

        # Notifier l'historique Redis de la completion
        from knowbase.api.services.import_history_redis import get_redis_import_history_service
        from rq import get_current_job

        job = get_current_job()
        if job:
            history_service = get_redis_import_history_service()
            chunks_inserted = result.get("chunks_inserted", 0) if isinstance(result, dict) else 0
            history_service.update_import_status(
                uid=job.id,
                status="completed",
                chunks_inserted=chunks_inserted
            )

        # Dé-duplication automatique des entités après l'import
        auto_deduplicate_entities(tenant_id="default")

        return {
            "status": "completed",
            "output_path": str(destination),
            "chunks_inserted": result.get("chunks_inserted", 0) if isinstance(result, dict) else 0
        }
    except Exception as e:
        update_job_progress("Erreur", 0, 6, f"Erreur pendant le traitement: {str(e)}")

        # Rollback automatique : supprimer les chunks déjà insérés
        from knowbase.api.services.import_deletion import delete_import_completely
        from knowbase.api.services.import_history_redis import get_redis_import_history_service
        from rq import get_current_job

        job = get_current_job()
        if job:
            try:
                # Tentative de rollback des chunks Qdrant
                update_job_progress("Rollback", 0, 6, "Suppression des chunks partiels...")
                delete_import_completely(job.id)
                update_job_progress("Rollback", 0, 6, "Rollback terminé")
            except Exception as rollback_error:
                update_job_progress("Rollback échoué", 0, 6, f"Erreur rollback: {rollback_error}")

            # Notifier l'historique Redis de l'échec
            history_service = get_redis_import_history_service()
            history_service.update_import_status(
                uid=job.id,
                status="failed",
                error_message=str(e)
            )

        raise


def ingest_pdf_job(*, pdf_path: str, document_type_id: Optional[str] = None, use_vision: bool = True) -> dict[str, Any]:
    try:
        # Marquer comme en cours de traitement
        mark_job_as_processing()
        update_job_progress("Initialisation", 0, 3, "Vérification du fichier PDF")
        path = _ensure_exists(Path(pdf_path))

        update_job_progress("Traitement", 1, 3, "Traitement du document PDF")
        result = pdf_pipeline.process_pdf(path, document_type_id=document_type_id, use_vision=use_vision)
        destination = pdf_pipeline.DOCS_DONE / f"{path.stem}.pdf"

        update_job_progress("Terminé", 3, 3, "Import PDF terminé avec succès")

        # Notifier l'historique Redis de la completion
        from knowbase.api.services.import_history_redis import get_redis_import_history_service
        from rq import get_current_job

        job = get_current_job()
        if job:
            history_service = get_redis_import_history_service()
            chunks_inserted = result.get("chunks_inserted", 0) if isinstance(result, dict) else 0
            history_service.update_import_status(
                uid=job.id,
                status="completed",
                chunks_inserted=chunks_inserted
            )

        # Dé-duplication automatique des entités après l'import
        auto_deduplicate_entities(tenant_id="default")

        return {
            "status": "completed",
            "output_path": str(destination),
            "chunks_inserted": result.get("chunks_inserted", 0) if isinstance(result, dict) else 0
        }
    except Exception as e:
        update_job_progress("Erreur", 0, 3, f"Erreur pendant le traitement PDF: {str(e)}")

        # Notifier l'historique Redis de l'échec
        from knowbase.api.services.import_history_redis import get_redis_import_history_service
        from rq import get_current_job

        job = get_current_job()
        if job:
            history_service = get_redis_import_history_service()
            history_service.update_import_status(
                uid=job.id,
                status="failed",
                error_message=str(e)
            )

        raise


def ingest_excel_job(
    *,
    xlsx_path: str,
    meta: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    try:
        # Marquer comme en cours de traitement
        mark_job_as_processing()
        update_job_progress("Initialisation", 0, 4, "Vérification du fichier Excel")
        path = _ensure_exists(Path(xlsx_path))
        meta_dict = meta or {}

        update_job_progress("Traitement", 1, 4, "Traitement du fichier Excel")
        result = excel_pipeline.process_excel_rfp(path, meta_dict)

        update_job_progress("Finalisation", 3, 4, "Déplacement du fichier")
        destination = excel_pipeline.DOCS_DONE / path.name

        update_job_progress("Terminé", 4, 4, "Import Excel terminé avec succès")

        # Notifier l'historique Redis de la completion
        from knowbase.api.services.import_history_redis import get_redis_import_history_service
        from rq import get_current_job

        job = get_current_job()
        if job:
            history_service = get_redis_import_history_service()
            chunks_inserted = result.get("chunks_inserted", 0) if isinstance(result, dict) else 0
            history_service.update_import_status(
                uid=job.id,
                status="completed",
                chunks_inserted=chunks_inserted
            )

        # Dé-duplication automatique des entités après l'import
        auto_deduplicate_entities(tenant_id="default")

        return {
            "status": "completed",
            "output_path": str(destination),
            "chunks_inserted": result.get("chunks_inserted", 0) if isinstance(result, dict) else 0
        }
    except Exception as e:
        update_job_progress("Erreur", 0, 4, f"Erreur pendant le traitement Excel: {str(e)}")

        # Rollback automatique : supprimer les chunks déjà insérés
        from knowbase.api.services.import_deletion import delete_import_completely
        from knowbase.api.services.import_history_redis import get_redis_import_history_service
        from rq import get_current_job

        job = get_current_job()
        if job:
            try:
                # Tentative de rollback des chunks Qdrant
                update_job_progress("Rollback", 0, 4, "Suppression des chunks partiels...")
                delete_import_completely(job.id)
                update_job_progress("Rollback", 0, 4, "Rollback terminé")
            except Exception as rollback_error:
                update_job_progress("Rollback échoué", 0, 4, f"Erreur rollback: {rollback_error}")

            # Notifier l'historique Redis de l'échec
            history_service = get_redis_import_history_service()
            history_service.update_import_status(
                uid=job.id,
                status="failed",
                error_message=str(e)
            )

        raise


def fill_excel_job(*, xlsx_path: str, meta_path: str) -> dict[str, Any]:
    try:
        # Marquer comme en cours de traitement
        mark_job_as_processing()
        update_job_progress("Initialisation", 0, 5, "Vérification des fichiers")
        path = _ensure_exists(Path(xlsx_path))
        meta_file = Path(meta_path)

        # Créer une fonction de callback pour transmettre la progression du pipeline
        def pipeline_progress_callback(step: str, progress: int, total: int, message: str):
            # Convertir la progression du pipeline (0-100%) en progression globale (1-3 sur 5 étapes = 20%-60%)
            global_progress = 1 + int((progress / 100) * 2)  # 1 à 3
            update_job_progress(step, global_progress, 5, message)

        # Utiliser le nouveau pipeline intelligent
        from knowbase.ingestion.pipelines import smart_fill_excel_pipeline
        result = smart_fill_excel_pipeline.main(path, meta_file, progress_callback=pipeline_progress_callback)

        update_job_progress("Finalisation", 3, 5, "Création du fichier de sortie")
        output_dir = PRESENTATIONS_DIR
        output_dir.mkdir(parents=True, exist_ok=True)

        # Récupérer le nom original du fichier et construire un UID court
        from rq import get_current_job
        job = get_current_job()
        if job:
            # Extraire seulement la partie date/time de l'UID (après rfp_) au format YYYYMMJJHHMMSS
            uid_parts = job.id.split('_')
            if len(uid_parts) >= 3 and uid_parts[-3:-1] == ['rfp']:
                date_part = uid_parts[-2]  # YYYYMMJJ
                time_part = uid_parts[-1]  # HHMMSS
                short_uid = f"{date_part}{time_part}"  # YYYYMMJJHHMMSS
            else:
                short_uid = job.id

            # Extraire le nom original du fichier (avant le premier _)
            original_stem = path.stem.split('_')[0]  # "CriteoToFill" de "CriteoToFill_rfp_..."
        else:
            short_uid = "unknown"
            original_stem = path.stem

        destination = output_dir / f"{original_stem}_{short_uid}_filled.xlsx"
        path.replace(destination)

        update_job_progress("Nettoyage", 4, 5, "Suppression des fichiers temporaires")
        if meta_file.exists():
            meta_file.unlink()

        update_job_progress("Terminé", 5, 5, "Remplissage RFP terminé avec succès")

        # Notifier l'historique Redis de la completion
        from knowbase.api.services.import_history_redis import get_redis_import_history_service
        from rq import get_current_job

        job = get_current_job()
        if job:
            history_service = get_redis_import_history_service()
            chunks_filled = result.get("chunks_filled", 0) if isinstance(result, dict) else 0
            history_service.update_import_status(
                uid=job.id,
                status="completed",
                chunks_inserted=chunks_filled  # Pour RFP, on compte les questions remplies
            )

        return {
            "status": "completed",
            "output_path": str(destination),
            "chunks_filled": result.get("chunks_filled", 0) if isinstance(result, dict) else 0
        }
    except Exception as e:
        update_job_progress("Erreur", 0, 5, f"Erreur pendant le remplissage RFP: {str(e)}")

        # Rollback : pas de chunks insérés pour ce type de job (lecture seule)
        from knowbase.api.services.import_history_redis import get_redis_import_history_service
        from rq import get_current_job

        job = get_current_job()
        if job:
            # Notifier l'historique Redis de l'échec
            history_service = get_redis_import_history_service()
            history_service.update_import_status(
                uid=job.id,
                status="failed",
                error_message=str(e)
            )

        raise


__all__ = [
    "ingest_pptx_job",
    "ingest_pdf_job",
    "ingest_excel_job",
    "fill_excel_job",
]
