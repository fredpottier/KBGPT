from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

from rq import get_current_job

from knowbase.config.settings import get_settings
from knowbase.ingestion.pipelines import (
    excel_pipeline,
    fill_excel_pipeline,
    pdf_pipeline,
    pptx_pipeline,
)


SETTINGS = get_settings()
PRESENTATIONS_DIR = SETTINGS.presentations_dir


def _ensure_exists(path: Path) -> Path:
    if not path.exists():
        raise FileNotFoundError(f"File not found: {path}")
    return path


def update_job_progress(step: str, progress: int = 0, total_steps: int = 0, message: str = ""):
    """Met à jour la progression du job actuel."""
    job = get_current_job()
    if job:
        job.meta.update({
            "current_step": step,
            "progress": progress,
            "total_steps": total_steps,
            "step_message": message,
            "detailed_status": "processing"
        })
        job.save()


def ingest_pptx_job(
    *,
    pptx_path: str,
    document_type: str = "default",
    meta_path: Optional[str] = None,
) -> dict[str, Any]:
    try:
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
        result = pptx_pipeline.process_pptx(path, document_type=document_type, progress_callback=update_job_progress)

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

        return {
            "status": "completed",
            "output_path": str(destination),
            "chunks_inserted": result.get("chunks_inserted", 0) if isinstance(result, dict) else 0
        }
    except Exception as e:
        update_job_progress("Erreur", 0, 6, f"Erreur pendant le traitement: {str(e)}")

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


def ingest_pdf_job(*, pdf_path: str) -> dict[str, Any]:
    path = _ensure_exists(Path(pdf_path))
    pdf_pipeline.process_pdf(path)
    destination = pdf_pipeline.DOCS_DONE / f"{path.stem}.pdf"
    return {"status": "completed", "output_path": str(destination)}


def ingest_excel_job(
    *,
    xlsx_path: str,
    meta: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    path = _ensure_exists(Path(xlsx_path))
    meta_dict = meta or {}
    excel_pipeline.process_excel_rfp(path, meta_dict)
    destination = excel_pipeline.DOCS_DONE / path.name
    return {"status": "completed", "output_path": str(destination)}


def fill_excel_job(*, xlsx_path: str, meta_path: str) -> dict[str, Any]:
    path = _ensure_exists(Path(xlsx_path))
    meta_file = Path(meta_path)
    fill_excel_pipeline.main(path, meta_file)
    output_dir = PRESENTATIONS_DIR
    output_dir.mkdir(parents=True, exist_ok=True)
    destination = output_dir / f"{path.stem}_filled.xlsx"
    path.replace(destination)
    if meta_file.exists():
        meta_file.unlink()
    return {"status": "completed", "output_path": str(destination)}


__all__ = [
    "ingest_pptx_job",
    "ingest_pdf_job",
    "ingest_excel_job",
    "fill_excel_job",
]
