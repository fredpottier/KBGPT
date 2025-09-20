from __future__ import annotations

import os
import shutil
from pathlib import Path
from typing import Dict, Any, List

from knowbase.api.services.import_history_redis import get_redis_import_history_service
from knowbase.common.clients import get_qdrant_client
from knowbase.config.settings import get_settings
import logging

settings = get_settings()

# Utiliser le logger standard Python
logger = logging.getLogger(__name__)

PRESENTATIONS_DIR = settings.presentations_dir
SLIDES_DIR = settings.slides_dir
THUMBNAILS_DIR = settings.thumbnails_dir
QDRANT_COLLECTION = settings.qdrant_collection


def delete_import_completely(uid: str) -> Dict[str, Any]:
    """
    Supprime complètement un import :
    - Chunks dans Qdrant
    - Fichiers PPTX, PDF, slides, thumbnails
    - Enregistrement historique Redis

    Args:
        uid: UID de l'import à supprimer

    Returns:
        Dictionnaire avec le détail des éléments supprimés

    Raises:
        FileNotFoundError: Si l'import n'existe pas
        Exception: En cas d'erreur de suppression
    """
    history_service = get_redis_import_history_service()
    qdrant_client = get_qdrant_client()

    # Récupérer les informations de l'import
    import_data = history_service.get_import_by_uid(uid)
    if not import_data:
        raise FileNotFoundError(f"Import avec UID {uid} non trouvé dans l'historique")

    filename = import_data.get('filename', '')
    logger.info(f"🗑️ Suppression complète de l'import {uid} ({filename})")

    deleted_items = {
        "chunks": 0,
        "files": [],
        "directories_cleaned": [],
        "redis_records": 0
    }

    # 1. Supprimer les chunks de Qdrant
    try:
        # Rechercher tous les chunks de cet import
        search_result = qdrant_client.scroll(
            collection_name=QDRANT_COLLECTION,
            scroll_filter={
                "must": [
                    {
                        "key": "document.source_name",
                        "match": {"value": f"{uid}.pptx"}
                    }
                ]
            },
            limit=10000  # Récupérer tous les chunks
        )

        chunk_ids = [point.id for point in search_result[0]]

        if chunk_ids:
            qdrant_client.delete(
                collection_name=QDRANT_COLLECTION,
                points_selector=chunk_ids
            )
            deleted_items["chunks"] = len(chunk_ids)
            logger.info(f"✅ Supprimé {len(chunk_ids)} chunks de Qdrant")
        else:
            logger.info("ℹ️ Aucun chunk trouvé dans Qdrant")

    except Exception as e:
        logger.error(f"❌ Erreur suppression chunks Qdrant: {e}")
        raise Exception(f"Erreur suppression chunks Qdrant: {e}")

    # 2. Supprimer les fichiers physiques
    file_patterns = [
        (PRESENTATIONS_DIR / f"{uid}.pptx", "PPTX traité"),
        (SLIDES_DIR / f"{uid}.pdf", "PDF généré"),
    ]

    # Ajouter les slides et thumbnails (pattern avec numéro de slide)
    slides_pattern = SLIDES_DIR.glob(f"{uid}_slide_*.jpg")
    thumbnails_pattern = THUMBNAILS_DIR.glob(f"{uid}_slide_*.jpg")

    for slide_file in slides_pattern:
        file_patterns.append((slide_file, f"Slide {slide_file.name}"))

    for thumb_file in thumbnails_pattern:
        file_patterns.append((thumb_file, f"Thumbnail {thumb_file.name}"))

    # Supprimer tous les fichiers
    for file_path, description in file_patterns:
        try:
            if file_path.exists():
                file_path.unlink()
                deleted_items["files"].append(str(file_path))
                logger.info(f"✅ Supprimé: {description}")
            else:
                logger.info(f"ℹ️ Fichier déjà absent: {description}")
        except Exception as e:
            logger.warning(f"⚠️ Erreur suppression {description}: {e}")

    # 3. Nettoyer les répertoires vides si nécessaire
    for directory in [PRESENTATIONS_DIR, SLIDES_DIR, THUMBNAILS_DIR]:
        try:
            if directory.exists() and not any(directory.iterdir()):
                logger.info(f"ℹ️ Répertoire {directory} vide (normal)")
                deleted_items["directories_cleaned"].append(str(directory))
        except Exception as e:
            logger.warning(f"⚠️ Erreur vérification répertoire {directory}: {e}")

    # 4. Supprimer l'enregistrement Redis
    try:
        # Supprimer de la liste d'historique
        history_key = history_service._get_history_key()
        import_key = history_service._get_import_key(uid)

        # Supprimer de la sorted set
        removed_from_history = history_service.redis_client.zrem(history_key, uid)
        # Supprimer les données de l'import
        removed_import_data = history_service.redis_client.delete(import_key)

        deleted_items["redis_records"] = removed_from_history + removed_import_data
        logger.info(f"✅ Supprimé enregistrement Redis ({removed_from_history + removed_import_data} clés)")

    except Exception as e:
        logger.error(f"❌ Erreur suppression Redis: {e}")
        raise Exception(f"Erreur suppression Redis: {e}")

    logger.info(f"🎉 Suppression complète de {uid} terminée avec succès")

    return deleted_items


__all__ = ["delete_import_completely"]