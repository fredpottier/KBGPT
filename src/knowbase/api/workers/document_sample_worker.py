"""
Worker RQ pour analyse asynchrone de document samples.

Phase 6 - Document Types Management
"""
import json
from typing import Dict, Optional
from pathlib import Path

from knowbase.api.services.document_sample_analyzer_service import DocumentSampleAnalyzerService
from knowbase.common.logging import setup_logging
from knowbase.config.settings import get_settings

settings = get_settings()
logger = setup_logging(settings.logs_dir, "document_sample_worker.log")


async def analyze_document_sample_task(
    file_path: str,
    context_prompt: Optional[str] = None,
    model_preference: str = "claude-sonnet"
) -> Dict:
    """
    Tâche RQ pour analyser document sample.

    Args:
        file_path: Chemin vers fichier temporaire
        context_prompt: Contexte additionnel
        model_preference: Modèle LLM

    Returns:
        Résultat analyse avec suggested_types
    """
    logger.info(f"🚀 Début analyse document sample: {file_path}")

    try:
        # Vérifier que fichier existe
        path = Path(file_path)
        if not path.exists():
            raise FileNotFoundError(f"File not found: {file_path}")

        # Créer UploadFile-like object depuis fichier
        class FileWrapper:
            def __init__(self, file_path: str):
                self.filename = Path(file_path).name
                self._file_path = file_path

            async def read(self):
                with open(self._file_path, 'rb') as f:
                    return f.read()

        file_wrapper = FileWrapper(file_path)

        # Analyser
        service = DocumentSampleAnalyzerService()
        result = await service.analyze_document_sample(
            file=file_wrapper,
            context_prompt=context_prompt,
            model_preference=model_preference
        )

        logger.info(
            f"✅ Analyse terminée: {len(result['suggested_types'])} types suggérés"
        )

        # Nettoyer fichier temporaire
        try:
            path.unlink()
        except Exception as e:
            logger.warning(f"⚠️ Erreur suppression fichier temp: {e}")

        return result

    except Exception as e:
        logger.error(f"❌ Erreur analyse document sample: {e}")
        raise


__all__ = ["analyze_document_sample_task"]
