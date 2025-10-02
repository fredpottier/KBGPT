"""
Module de déduplication content-based pour documents

Implémente signatures multi-niveaux (file_hash + content_hash) pour détecter
duplicates réels indépendamment du nom de fichier.

Phase 1 - Critère 1.5
"""

import hashlib
import re
import logging
from pathlib import Path
from typing import Optional, List, Dict, Any
from dataclasses import dataclass
from enum import Enum
from datetime import datetime

logger = logging.getLogger(__name__)


class DuplicateStatus(str, Enum):
    """Statut déduplication document"""
    EXACT_DUPLICATE = "exact_duplicate"
    CONTENT_MODIFIED = "content_modified"
    NEW_DOCUMENT = "new_document"


@dataclass
class DuplicateInfo:
    """Information déduplication avec metadata import existant"""
    status: DuplicateStatus
    existing_import_id: Optional[str] = None
    existing_filename: Optional[str] = None
    existing_chunk_count: Optional[int] = None
    existing_episode_uuid: Optional[str] = None
    imported_at: Optional[str] = None
    message: str = ""

    @property
    def is_duplicate(self) -> bool:
        """True si exact duplicate (rejet)"""
        return self.status == DuplicateStatus.EXACT_DUPLICATE

    @property
    def allow_upload(self) -> bool:
        """True si upload autorisé"""
        return self.status != DuplicateStatus.EXACT_DUPLICATE


def compute_file_hash(file_path: Path) -> str:
    """
    Calcul SHA256 fichier brut

    Détection copie exacte (même fichier binaire).

    Args:
        file_path: Chemin fichier à hasher

    Returns:
        Hash format "sha256:abc123..."

    Raises:
        FileNotFoundError: Si fichier introuvable
        IOError: Si erreur lecture
    """
    if not file_path.exists():
        raise FileNotFoundError(f"Fichier introuvable: {file_path}")

    sha256 = hashlib.sha256()

    try:
        with open(file_path, 'rb') as f:
            # Lecture par chunks 8KB pour performance
            for chunk in iter(lambda: f.read(8192), b''):
                sha256.update(chunk)

        file_hash = f"sha256:{sha256.hexdigest()}"
        logger.debug(f"File hash calculé: {file_hash[:16]}... pour {file_path.name}")
        return file_hash

    except Exception as e:
        logger.error(f"Erreur calcul file_hash pour {file_path}: {e}")
        raise


def compute_content_hash(extracted_content: str, source_type: str = "pptx") -> str:
    """
    Calcul SHA256 contenu normalisé

    Détection contenu identique malgré metadata fichier différente
    (ex: date création PPTX, auteur, propriétés document).

    Normalisation appliquée:
    - Lowercase
    - Trim whitespace excessif
    - Suppression caractères non-imprimables
    - Sort lignes (pour PPTX avec ordre slides modifié)

    Args:
        extracted_content: Contenu textuel extrait (tous slides concaténés)
        source_type: Type document ("pptx", "pdf", "excel")

    Returns:
        Hash format "sha256:def456..."
    """
    if not extracted_content:
        logger.warning("Contenu vide pour calcul content_hash")
        return "sha256:e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"  # SHA256 empty string

    # Normalisation aggressive
    normalized = extracted_content.lower().strip()

    # Normaliser whitespace (multiples espaces/tabs → simple espace)
    normalized = re.sub(r'\s+', ' ', normalized)

    # Retrait caractères non-imprimables
    normalized = re.sub(r'[^\x20-\x7E\n]', '', normalized)

    # Pour PPTX: sort lignes pour robustesse ordre slides modifié
    # (accepte réorganisation slides sans invalider hash)
    if source_type == "pptx":
        lines = normalized.split('\n')
        lines_sorted = sorted([line.strip() for line in lines if line.strip()])
        normalized = '\n'.join(lines_sorted)

    sha256 = hashlib.sha256(normalized.encode('utf-8'))
    content_hash = f"sha256:{sha256.hexdigest()}"

    logger.debug(f"Content hash calculé: {content_hash[:16]}... (length: {len(extracted_content)} chars)")
    return content_hash


async def check_duplicate(
    content_hash: str,
    tenant_id: str,
    qdrant_client: Any,
    collection_name: str = "knowbase"
) -> DuplicateInfo:
    """
    Vérification duplicate via index Qdrant

    Recherche chunks avec même content_hash dans même tenant.

    Args:
        content_hash: Hash contenu normalisé (format "sha256:...")
        tenant_id: ID tenant pour isolation
        qdrant_client: Client Qdrant initialisé
        collection_name: Collection Qdrant (défaut: "knowbase")

    Returns:
        DuplicateInfo avec statut et metadata import existant si duplicate
    """
    try:
        # Scroll Qdrant pour trouver chunks avec même content_hash
        results, _ = qdrant_client.scroll(
            collection_name=collection_name,
            scroll_filter={
                "must": [
                    {"key": "document.content_hash", "match": {"value": content_hash}},
                    {"key": "custom_metadata.tenant_id", "match": {"value": tenant_id}}
                ]
            },
            limit=1,
            with_payload=True
        )

        if not results:
            logger.info(f"✅ Nouveau document (content_hash: {content_hash[:16]}...)")
            return DuplicateInfo(
                status=DuplicateStatus.NEW_DOCUMENT,
                message="Nouveau document, import autorisé"
            )

        # Duplicate trouvé - récupérer metadata
        existing_chunk = results[0]
        payload = existing_chunk.payload

        document_meta = payload.get("document", {})
        import_id = document_meta.get("import_id")
        filename = document_meta.get("source_name", "unknown")
        imported_at = document_meta.get("imported_at", "unknown")
        episode_uuid = payload.get("episode_uuid")

        # Compter chunks de cet import (approximation via import_id)
        chunk_count = await _count_chunks_by_import(
            qdrant_client, collection_name, import_id, tenant_id
        ) if import_id else 1

        logger.warning(
            f"⚠️ Document duplicate détecté: {filename} "
            f"(importé le {imported_at}, {chunk_count} chunks)"
        )

        return DuplicateInfo(
            status=DuplicateStatus.EXACT_DUPLICATE,
            existing_import_id=import_id,
            existing_filename=filename,
            existing_chunk_count=chunk_count,
            existing_episode_uuid=episode_uuid,
            imported_at=imported_at,
            message=f"Document déjà importé le {imported_at} (fichier: {filename}, {chunk_count} chunks)"
        )

    except Exception as e:
        logger.error(f"Erreur check_duplicate: {e}", exc_info=True)
        # En cas d'erreur, autoriser import (fail-open pour éviter bloquer ingestion)
        return DuplicateInfo(
            status=DuplicateStatus.NEW_DOCUMENT,
            message=f"Erreur vérification duplicate (autorisé par défaut): {e}"
        )


async def _count_chunks_by_import(
    qdrant_client: Any,
    collection_name: str,
    import_id: str,
    tenant_id: str
) -> int:
    """
    Compte chunks d'un import_id donné

    Args:
        qdrant_client: Client Qdrant
        collection_name: Collection
        import_id: UUID import
        tenant_id: ID tenant

    Returns:
        Nombre de chunks
    """
    try:
        results, _ = qdrant_client.scroll(
            collection_name=collection_name,
            scroll_filter={
                "must": [
                    {"key": "document.import_id", "match": {"value": import_id}},
                    {"key": "custom_metadata.tenant_id", "match": {"value": tenant_id}}
                ]
            },
            limit=10000,  # Max count
            with_payload=False  # Performance: pas besoin payload
        )

        count = len(results)
        logger.debug(f"Import {import_id[:8]}... contient {count} chunks")
        return count

    except Exception as e:
        logger.warning(f"Erreur count chunks import {import_id}: {e}")
        return 0


async def get_import_metadata(
    import_id: str,
    tenant_id: str,
    qdrant_client: Any,
    collection_name: str = "knowbase"
) -> Optional[Dict[str, Any]]:
    """
    Récupère metadata complète d'un import

    Args:
        import_id: UUID import
        tenant_id: ID tenant
        qdrant_client: Client Qdrant
        collection_name: Collection

    Returns:
        Dict avec metadata ou None si introuvable
    """
    try:
        results, _ = qdrant_client.scroll(
            collection_name=collection_name,
            scroll_filter={
                "must": [
                    {"key": "document.import_id", "match": {"value": import_id}},
                    {"key": "custom_metadata.tenant_id", "match": {"value": tenant_id}}
                ]
            },
            limit=1,
            with_payload=True
        )

        if not results:
            return None

        chunk = results[0]
        payload = chunk.payload
        document_meta = payload.get("document", {})

        # Compter tous les chunks de cet import
        chunk_count = await _count_chunks_by_import(
            qdrant_client, collection_name, import_id, tenant_id
        )

        return {
            "import_id": import_id,
            "tenant_id": tenant_id,
            "filename": document_meta.get("source_name", "unknown"),
            "file_hash": document_meta.get("source_file_hash"),
            "content_hash": document_meta.get("content_hash"),
            "episode_uuid": payload.get("episode_uuid"),
            "chunk_count": chunk_count,
            "imported_at": document_meta.get("imported_at"),
            "import_status": "completed"
        }

    except Exception as e:
        logger.error(f"Erreur get_import_metadata pour {import_id}: {e}")
        return None


async def get_imports_history(
    tenant_id: str,
    qdrant_client: Any,
    collection_name: str = "knowbase",
    limit: int = 50,
    offset: int = 0
) -> List[Dict[str, Any]]:
    """
    Récupère historique imports par tenant

    Agrégation par import_id avec metadata.

    Args:
        tenant_id: ID tenant
        qdrant_client: Client Qdrant
        collection_name: Collection
        limit: Nombre max imports à retourner
        offset: Offset pagination

    Returns:
        Liste metadata imports triés par date DESC
    """
    try:
        # Scroll tous les chunks du tenant
        results, _ = qdrant_client.scroll(
            collection_name=collection_name,
            scroll_filter={
                "must": [
                    {"key": "custom_metadata.tenant_id", "match": {"value": tenant_id}}
                ]
            },
            limit=10000,  # Max pour agrégation
            with_payload=True
        )

        # Agréger par import_id
        imports_map = {}
        for chunk in results:
            payload = chunk.payload
            document_meta = payload.get("document", {})
            import_id = document_meta.get("import_id")

            if not import_id:
                continue

            if import_id not in imports_map:
                imports_map[import_id] = {
                    "import_id": import_id,
                    "tenant_id": tenant_id,
                    "filename": document_meta.get("source_name", "unknown"),
                    "file_hash": document_meta.get("source_file_hash"),
                    "content_hash": document_meta.get("content_hash"),
                    "episode_uuid": payload.get("episode_uuid"),
                    "chunk_count": 0,
                    "imported_at": document_meta.get("imported_at", "unknown"),
                    "import_status": "completed"
                }

            imports_map[import_id]["chunk_count"] += 1

        # Convertir en liste et trier par date DESC
        imports_list = list(imports_map.values())
        imports_list.sort(key=lambda x: x["imported_at"], reverse=True)

        # Pagination
        paginated = imports_list[offset:offset + limit]

        logger.info(f"Historique imports tenant {tenant_id}: {len(imports_list)} total, retourné {len(paginated)}")
        return paginated

    except Exception as e:
        logger.error(f"Erreur get_imports_history: {e}", exc_info=True)
        return []
