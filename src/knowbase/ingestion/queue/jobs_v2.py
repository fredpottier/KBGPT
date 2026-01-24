"""
Jobs V2 - Pipeline d'ingestion unifie avec Extraction V2.

Utilise ExtractionPipelineV2 (Docling + Vision Gating V4) pour tous les formats.
Active via feature flag: extraction_v2.enabled = true

Architecture:
    docs_in/
        |
    folder_watcher
        |
    dispatcher (check feature flag)
        |
    +-------------------+
    | jobs_v2.py        |  <-- CE FICHIER
    | (unifie)          |
    +-------------------+
        |
    ExtractionPipelineV2
    (Docling + Gating + Vision + Merge + Linearize)
        |
    osmose_agentique
    (Semantic Processing)
        |
    Qdrant + Neo4j
"""

from __future__ import annotations

import asyncio
import os
import socket
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

from rq import get_current_job

from knowbase.config.settings import get_settings
from knowbase.config.feature_flags import get_feature_flags
from knowbase.common.logging import setup_logging


SETTINGS = get_settings()
DOCS_IN = SETTINGS.docs_in_dir
DOCS_DONE = SETTINGS.docs_done_dir
logger = setup_logging(SETTINGS.logs_dir, "jobs_v2.log")


def _ensure_exists(path: Path) -> Path:
    """Verifie que le fichier existe."""
    if not path.exists():
        raise FileNotFoundError(f"File not found: {path}")
    return path


def send_worker_heartbeat():
    """Envoie un heartbeat pour signaler que le worker est actif."""
    job = get_current_job()
    if job:
        worker_id = f"{socket.gethostname()}:{os.getpid()}"
        job.meta.update({
            "last_heartbeat": datetime.now().timestamp(),
            "worker_id": worker_id
        })
        job.save()


def update_job_progress(step: str, progress: int = 0, total_steps: int = 0, message: str = ""):
    """Met a jour la progression du job."""
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
            "worker_id": worker_id,
            "pipeline_version": "v2"
        })
        job.save()


def mark_job_as_processing():
    """Marque le job comme en cours."""
    from knowbase.api.services.import_history_redis import get_redis_import_history_service

    job = get_current_job()
    if job:
        send_worker_heartbeat()
        history_service = get_redis_import_history_service()
        history_service.update_import_status(uid=job.id, status="processing")


def auto_deduplicate_entities(tenant_id: str = "default") -> None:
    """Deduplication automatique apres import."""
    try:
        logger.info("[V2] Demarrage deduplication automatique...")
        from knowbase.api.services.knowledge_graph_service import KnowledgeGraphService

        kg_service = KnowledgeGraphService(tenant_id=tenant_id)
        stats = kg_service.deduplicate_entities_by_name(
            tenant_id=tenant_id,
            dry_run=False
        )

        if stats["duplicate_groups"] > 0:
            logger.info(
                f"[V2] Deduplication: {stats['duplicate_groups']} groupes, "
                f"{stats['entities_to_merge']} fusions"
            )
    except Exception as e:
        logger.warning(f"[V2] Deduplication echouee (non bloquant): {e}")


async def _run_extraction_v2(
    file_path: Path,
    document_type_id: Optional[str] = None,
    tenant_id: str = "default",
) -> Dict[str, Any]:
    """
    Execute le pipeline Extraction V2.

    Args:
        file_path: Chemin du document
        document_type_id: Type de document (optionnel)
        tenant_id: Tenant ID

    Returns:
        Resultat d'extraction avec full_text et structure
    """
    from knowbase.extraction_v2 import (
        ExtractionPipelineV2,
        PipelineConfig,
    )

    # Charger config depuis feature flags
    flags = get_feature_flags()
    v2_config = flags.get("extraction_v2", {})
    vision_config = v2_config.get("vision_config", {})
    gating_thresholds = v2_config.get("gating_thresholds", {})

    # Creer configuration pipeline
    config = PipelineConfig(
        enable_vision=True,
        enable_gating=True,
        vision_required_threshold=gating_thresholds.get("vision_required", 0.60),
        vision_recommended_threshold=gating_thresholds.get("vision_recommended", 0.40),
        vision_budget=vision_config.get("budget"),
        tenant_id=tenant_id,
        use_cache=v2_config.get("cache", {}).get("enabled", True),
        cache_version=v2_config.get("cache", {}).get("version", "v4"),
        vision_model=vision_config.get("model", "gpt-4o"),
        vision_temperature=vision_config.get("temperature", 0.0),
        include_recommended_in_vision=vision_config.get("include_recommended", True),
    )

    logger.info(
        f"[ExtractionV2] Processing {file_path.name} with config: "
        f"vision={config.enable_vision}, gating={config.enable_gating}"
    )

    # Executer pipeline
    pipeline = ExtractionPipelineV2(config)
    result = await pipeline.process_document(
        file_path=str(file_path),
        tenant_id=tenant_id,
    )

    # Extraire metriques (depuis stats, pas metadata)
    metrics = result.stats.get("metrics", {})

    logger.info(
        f"[ExtractionV2] Complete: {result.document_id}, "
        f"{len(result.full_text)} chars, "
        f"{metrics.get('vision_processed_pages', 0)} pages Vision"
    )

    return {
        "document_id": result.document_id,
        "full_text": result.full_text,
        "structure": result.structure,
        "page_index": result.page_index,
        "file_type": result.file_type,
        "metrics": metrics,
        "doc_context": result.doc_context,  # PR4: DocContextFrame pour assertions
    }


async def _run_osmose_processing(
    document_id: str,
    document_title: str,
    document_path: Path,
    full_text: str,
    tenant_id: str = "default",
    doc_context: Optional[Any] = None,  # PR4: DocContextFrame
) -> Dict[str, Any]:
    """
    Execute le traitement OSMOSE apres extraction.

    Args:
        document_id: ID du document
        document_title: Titre du document
        document_path: Chemin du document
        full_text: Texte extrait (avec marqueurs V2)
        tenant_id: Tenant ID
        doc_context: DocContextFrame pour assertions (PR4)

    Returns:
        Resultat OSMOSE
    """
    from knowbase.ingestion.osmose_agentique import OsmoseAgentiqueService

    integrator = OsmoseAgentiqueService()

    result = await integrator.process_document_agentique(
        document_id=document_id,
        document_title=document_title,
        document_path=document_path,
        text_content=full_text,
        tenant_id=tenant_id,
        doc_context_frame=doc_context,  # PR4: Passer DocContextFrame
    )

    return {
        "osmose_success": result.osmose_success,
        "concepts_extracted": result.concepts_extracted,
        "canonical_concepts": result.canonical_concepts,
        "relations_stored": result.proto_kg_relations_stored,
        "phase2_relations": result.phase2_relations_extracted,
        "embeddings_stored": result.proto_kg_embeddings_stored,
        "duration_seconds": result.total_duration_seconds,
    }


def ingest_document_v2_job(
    *,
    file_path: str,
    document_type_id: Optional[str] = None,
    tenant_id: str = "default",
) -> Dict[str, Any]:
    """
    Job d'ingestion unifie V2.

    Traite tous les formats (PDF, PPTX, DOCX, XLSX) via ExtractionPipelineV2,
    puis passe le resultat a OSMOSE pour traitement semantique.

    Args:
        file_path: Chemin du document
        document_type_id: Type de document (optionnel)
        tenant_id: Tenant ID

    Returns:
        Resultat de l'ingestion
    """
    try:
        # Initialisation
        mark_job_as_processing()
        update_job_progress("Initialisation", 0, 5, "Verification du fichier")

        path = _ensure_exists(Path(file_path))
        file_type = path.suffix.lower().lstrip(".")

        # Verification du mode Burst pour diagnostic
        try:
            from knowbase.common.llm_router import get_llm_router
            llm_router = get_llm_router()
            burst_status = llm_router.get_burst_status()
            if burst_status.get("burst_mode"):
                logger.info(
                    f"[V2] BURST MODE ACTIVE: endpoint={burst_status.get('burst_endpoint')}, "
                    f"model={burst_status.get('burst_model')}"
                )
            else:
                logger.info("[V2] BURST MODE INACTIVE: using configured providers (OpenAI/Anthropic)")
        except Exception as e:
            logger.warning(f"[V2] Could not check burst status: {e}")

        logger.info(f"[V2] Starting ingestion: {path.name} (type={file_type})")

        # Etape 1: Extraction V2
        update_job_progress("Extraction", 1, 5, "Extraction Docling + Vision Gating")

        extraction_result = asyncio.run(
            _run_extraction_v2(
                file_path=path,
                document_type_id=document_type_id,
                tenant_id=tenant_id,
            )
        )

        document_id = extraction_result["document_id"]
        full_text = extraction_result["full_text"]
        metrics = extraction_result["metrics"]
        doc_context = extraction_result.get("doc_context")  # PR4: DocContextFrame

        logger.info(
            f"[V2] Extraction complete: {document_id}, "
            f"{len(full_text)} chars, "
            f"{metrics.get('total_pages', 0)} pages, "
            f"doc_context={doc_context is not None}"
        )

        # Etape 2: Traitement OSMOSE
        update_job_progress("OSMOSE", 2, 5, "Traitement semantique OSMOSE")

        osmose_result = asyncio.run(
            _run_osmose_processing(
                document_id=document_id,
                document_title=path.stem,
                document_path=path,
                full_text=full_text,
                tenant_id=tenant_id,
                doc_context=doc_context,  # PR4: Passer DocContextFrame
            )
        )

        logger.info(
            f"[V2] OSMOSE complete: {document_id}, "
            f"concepts={osmose_result['concepts_extracted']}, "
            f"relations={osmose_result['relations_stored']}"
        )

        # Etape 3: Deduplication
        update_job_progress("Deduplication", 3, 5, "Deduplication des entites")
        auto_deduplicate_entities(tenant_id=tenant_id)

        # Etape 4: Deplacement fichier
        update_job_progress("Finalisation", 4, 5, "Deplacement vers docs_done")

        destination = DOCS_DONE / f"{path.stem}{path.suffix}"
        if path.exists():
            shutil.move(str(path), str(destination))
            logger.info(f"[V2] Moved to: {destination}")

        # Etape 5: Completion
        update_job_progress("Termine", 5, 5, "Import V2 termine avec succes")

        # Notifier historique
        from knowbase.api.services.import_history_redis import get_redis_import_history_service

        job = get_current_job()
        if job:
            history_service = get_redis_import_history_service()
            history_service.update_import_status(
                uid=job.id,
                status="completed",
                chunks_inserted=osmose_result.get("embeddings_stored", 0),
            )

        result = {
            "status": "completed",
            "pipeline_version": "v2",
            "output_path": str(destination),
            "document_id": document_id,
            "file_type": file_type,
            "extraction": {
                "chars": len(full_text),
                "pages": metrics.get("total_pages", 0),
                "vision_pages": metrics.get("vision_processed_pages", 0),
                "extraction_time_ms": metrics.get("extraction_time_ms", 0),
                "vision_time_ms": metrics.get("vision_time_ms", 0),
            },
            "osmose": {
                "concepts": osmose_result.get("concepts_extracted", 0),
                "canonical_concepts": osmose_result.get("canonical_concepts", 0),
                "relations_stored": osmose_result.get("relations_stored", 0),
                "phase2_relations": osmose_result.get("phase2_relations", 0),
                "embeddings_stored": osmose_result.get("embeddings_stored", 0),
                "duration_seconds": osmose_result.get("duration_seconds", 0),
            },
        }

        logger.info(f"[V2] Job completed: {document_id}")
        return result

    except Exception as e:
        logger.error(f"[V2] Job failed: {e}")
        update_job_progress("Erreur", 0, 5, f"Erreur: {str(e)}")

        # Rollback
        from knowbase.api.services.import_deletion import delete_import_completely
        from knowbase.api.services.import_history_redis import get_redis_import_history_service

        job = get_current_job()
        if job:
            try:
                update_job_progress("Rollback", 0, 5, "Suppression chunks partiels...")
                delete_import_completely(job.id)
            except Exception as rollback_error:
                logger.error(f"[V2] Rollback failed: {rollback_error}")

            history_service = get_redis_import_history_service()
            history_service.update_import_status(
                uid=job.id,
                status="failed",
                error_message=str(e),
            )

        raise


def ingest_excel_job(
    *,
    xlsx_path: str,
    meta: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Job d'ingestion Excel (RFP Q/A import).

    Migre depuis jobs.py - Excel pas encore dans ExtractionPipelineV2.

    Args:
        xlsx_path: Chemin du fichier Excel
        meta: Metadata optionnelle

    Returns:
        Resultat de l'ingestion
    """
    from knowbase.ingestion.pipelines import excel_pipeline

    try:
        mark_job_as_processing()
        update_job_progress("Initialisation", 0, 4, "Verification du fichier Excel")

        path = _ensure_exists(Path(xlsx_path))
        meta_dict = meta or {}

        update_job_progress("Traitement", 1, 4, "Traitement du fichier Excel")
        result = excel_pipeline.process_excel_rfp(path, meta_dict)

        update_job_progress("Finalisation", 3, 4, "Deplacement du fichier")
        destination = DOCS_DONE / path.name

        update_job_progress("Termine", 4, 4, "Import Excel termine avec succes")

        # Notifier historique Redis
        from knowbase.api.services.import_history_redis import get_redis_import_history_service

        job = get_current_job()
        if job:
            history_service = get_redis_import_history_service()
            chunks_inserted = result.get("chunks_inserted", 0) if isinstance(result, dict) else 0
            history_service.update_import_status(
                uid=job.id,
                status="completed",
                chunks_inserted=chunks_inserted
            )

        # Deduplication
        auto_deduplicate_entities(tenant_id="default")

        return {
            "status": "completed",
            "output_path": str(destination),
            "chunks_inserted": result.get("chunks_inserted", 0) if isinstance(result, dict) else 0
        }

    except Exception as e:
        update_job_progress("Erreur", 0, 4, f"Erreur traitement Excel: {str(e)}")

        from knowbase.api.services.import_deletion import delete_import_completely
        from knowbase.api.services.import_history_redis import get_redis_import_history_service

        job = get_current_job()
        if job:
            try:
                update_job_progress("Rollback", 0, 4, "Suppression chunks partiels...")
                delete_import_completely(job.id)
            except Exception as rollback_error:
                logger.error(f"[Excel] Rollback failed: {rollback_error}")

            history_service = get_redis_import_history_service()
            history_service.update_import_status(
                uid=job.id,
                status="failed",
                error_message=str(e)
            )

        raise


def fill_excel_job(*, xlsx_path: str, meta_path: str) -> Dict[str, Any]:
    """
    Job de remplissage RFP Excel.

    Migre depuis jobs.py.

    Args:
        xlsx_path: Chemin du fichier Excel a remplir
        meta_path: Chemin du fichier meta

    Returns:
        Resultat du remplissage
    """
    try:
        mark_job_as_processing()
        update_job_progress("Initialisation", 0, 5, "Verification des fichiers")

        path = _ensure_exists(Path(xlsx_path))
        meta_file = Path(meta_path)

        def pipeline_progress_callback(step: str, progress: int, total: int, message: str):
            global_progress = 1 + int((progress / 100) * 2)
            update_job_progress(step, global_progress, 5, message)

        from knowbase.ingestion.pipelines import smart_fill_excel_pipeline
        result = smart_fill_excel_pipeline.main(path, meta_file, progress_callback=pipeline_progress_callback)

        update_job_progress("Finalisation", 3, 5, "Creation du fichier de sortie")
        output_dir = SETTINGS.presentations_dir
        output_dir.mkdir(parents=True, exist_ok=True)

        job = get_current_job()
        if job:
            uid_parts = job.id.split('_')
            if len(uid_parts) >= 3 and uid_parts[-3:-1] == ['rfp']:
                date_part = uid_parts[-2]
                time_part = uid_parts[-1]
                short_uid = f"{date_part}{time_part}"
            else:
                short_uid = job.id

            original_stem = path.stem.split('_')[0]
        else:
            short_uid = "unknown"
            original_stem = path.stem

        destination = output_dir / f"{original_stem}_{short_uid}_filled.xlsx"
        path.replace(destination)

        update_job_progress("Nettoyage", 4, 5, "Suppression fichiers temporaires")
        if meta_file.exists():
            meta_file.unlink()

        update_job_progress("Termine", 5, 5, "Remplissage RFP termine avec succes")

        from knowbase.api.services.import_history_redis import get_redis_import_history_service

        job = get_current_job()
        if job:
            history_service = get_redis_import_history_service()
            chunks_filled = result.get("chunks_filled", 0) if isinstance(result, dict) else 0
            history_service.update_import_status(
                uid=job.id,
                status="completed",
                chunks_inserted=chunks_filled
            )

        return {
            "status": "completed",
            "output_path": str(destination),
            "chunks_filled": result.get("chunks_filled", 0) if isinstance(result, dict) else 0
        }

    except Exception as e:
        update_job_progress("Erreur", 0, 5, f"Erreur remplissage RFP: {str(e)}")

        from knowbase.api.services.import_history_redis import get_redis_import_history_service

        job = get_current_job()
        if job:
            history_service = get_redis_import_history_service()
            history_service.update_import_status(
                uid=job.id,
                status="failed",
                error_message=str(e)
            )

        raise


__all__ = [
    "ingest_document_v2_job",
    "ingest_excel_job",
    "fill_excel_job",
    "send_worker_heartbeat",
    "update_job_progress",
]
