"""
Écriture de chunks enrichis dans Qdrant.

Module autonome extrait de pptx_pipeline.py avec toute sa logique métier.
Gère l'ingestion de chunks dans Qdrant avec métadonnées enrichies et schéma canonique.
"""

import uuid
from datetime import datetime, timezone
from typing import List, Dict, Any, Optional
import logging

from qdrant_client.models import PointStruct

from knowbase.common.clients import (
    get_qdrant_client,
    get_sentence_transformer,
)
from knowbase.config.settings import get_settings
from ..utils.text_utils import get_language_iso2


def embed_texts(
    texts: List[str],
    model_name: Optional[str] = None,
    logger: Optional[logging.Logger] = None
) -> List[List[float]]:
    """
    Génère des embeddings pour une liste de textes.

    Args:
        texts: Liste de textes à encoder
        model_name: Nom du modèle d'embedding (utilise settings par défaut si None)
        logger: Logger optionnel

    Returns:
        List[List[float]]: Liste des vecteurs d'embedding

    Example:
        >>> embeddings = embed_texts(["Hello world", "Bonjour monde"])
        >>> len(embeddings)
        2
        >>> len(embeddings[0])
        384  # Dimension du modèle
    """
    if logger is None:
        logger = logging.getLogger(__name__)

    settings = get_settings()
    model_name = model_name or settings.embeddings_model

    try:
        model = get_sentence_transformer(model_name)
        embeddings = model.encode(texts, show_progress_bar=False)
        return embeddings.tolist()
    except Exception as e:
        logger.error(f"❌ Erreur génération embeddings: {e}")
        raise


def ingest_chunks(
    chunks: List[Dict[str, Any]],
    doc_meta: Dict[str, Any],
    file_uid: str,
    slide_index: int,
    deck_summary: str,
    collection_name: Optional[str] = None,
    public_url: Optional[str] = None,
    qdrant_client=None,
    logger: Optional[logging.Logger] = None
) -> int:
    """
    Ingestion de chunks dans Qdrant avec schéma canonique enrichi.

    Filtre les chunks non informatifs (title, transition, agenda) et ingère
    les chunks valides dans Qdrant avec métadonnées enrichies pour la recherche.

    Args:
        chunks: Liste de chunks enrichis à ingérer
            [{"full_explanation": str, "meta": dict, "prompt_meta": dict, ...}, ...]
        doc_meta: Métadonnées globales du document
            {title, main_solution, supporting_solutions, audience, source_date, ...}
        file_uid: UID unique du fichier (sans extension)
        slide_index: Index de la slide
        deck_summary: Résumé global du deck (contexte)
        collection_name: Nom de la collection Qdrant (utilise settings par défaut si None)
        public_url: URL publique pour les assets (utilise settings par défaut si None)
        qdrant_client: Client Qdrant (créé si None)
        logger: Logger optionnel

    Returns:
        int: Nombre de points ingérés

    Example:
        >>> chunks = [
        ...     {
        ...         "full_explanation": "SAP S/4HANA Cloud provides...",
        ...         "meta": {"scope": "solution-specific", "type": "feature"},
        ...         "prompt_meta": {"document_type": "crr"}
        ...     }
        ... ]
        >>> doc_meta = {
        ...     "title": "SAP S/4HANA Overview",
        ...     "main_solution": "SAP S/4HANA",
        ...     "supporting_solutions": ["SAP RISE"],
        ...     "audience": ["Technical", "Business"],
        ...     "source_date": "2025-01-15"
        ... }
        >>> count = ingest_chunks(chunks, doc_meta, "abc123", 5, "Deck about S/4HANA")
        >>> count
        1
    """
    # Initialiser dépendances
    if logger is None:
        logger = logging.getLogger(__name__)

    settings = get_settings()
    collection_name = collection_name or settings.qdrant_collection
    public_url = public_url or settings.public_url

    if qdrant_client is None:
        qdrant_client = get_qdrant_client()

    # Filtrer les slides non informatifs
    excluded_roles = {"title", "transition", "agenda"}

    valid = []
    for ch in chunks:
        if not ch.get("full_explanation", "").strip():
            continue

        meta = ch.get("meta", {})
        slide_role = meta.get("slide_role", "")

        # Exclure les slides de type title, transition, agenda
        if slide_role in excluded_roles:
            logger.info(
                f"Slide {slide_index}: skipping chunk with slide_role '{slide_role}'"
            )
            continue

        valid.append(ch)

    if not valid:
        logger.info(f"Slide {slide_index}: no valid chunks after filtering")
        return 0

    # Générer embeddings
    texts = [ch["full_explanation"] for ch in valid]
    embs = embed_texts(texts, logger=logger)

    # Construire points Qdrant avec schéma canonique
    points = []
    for ch, emb in zip(valid, embs):
        meta = ch.get("meta", {})

        # Payload canonique enrichi
        payload = {
            "text": ch["full_explanation"].strip(),
            "language": get_language_iso2(ch["full_explanation"]),
            "ingested_at": datetime.now(timezone.utc).isoformat(),
            "document": {
                "source_name": f"{file_uid}.pptx",
                "source_type": "pptx",
                "source_file_url": f"{public_url}/static/presentations/{file_uid}.pptx",
                "slide_image_url": f"{public_url}/static/thumbnails/{file_uid}_slide_{slide_index}.jpg",
                "title": doc_meta.get("title", ""),
                "objective": doc_meta.get("objective", ""),
                "audience": doc_meta.get("audience", []),
                "source_date": doc_meta.get("source_date", ""),
                "all_mentioned_solutions": doc_meta.get(
                    "mentioned_solutions", []
                ),  # Solutions globales du deck entier
            },
            "solution": {
                "main": doc_meta.get("main_solution", ""),
                "family": doc_meta.get("family", ""),
                "supporting": doc_meta.get("supporting_solutions", []),
                "mentioned": meta.get(
                    "mentioned_solutions", []
                ),  # Utiliser les solutions spécifiques de ce chunk/slide
                "version": doc_meta.get("version", ""),
                "deployment_model": doc_meta.get("deployment_model", ""),
            },
            "chunk": {
                "scope": meta.get("scope", "solution-specific"),
                "slide_index": slide_index,
                "type": meta.get("type", ""),
                "level": meta.get("level", ""),
                "tags": meta.get("tags", []),
            },
            "deck_summary": deck_summary,
            "prompt_meta": ch.get("prompt_meta", {}),
        }

        points.append(PointStruct(id=str(uuid.uuid4()), vector=emb, payload=payload))

    # Ingestion dans Qdrant
    qdrant_client.upsert(collection_name=collection_name, points=points)

    logger.info(f"Slide {slide_index}: ingested {len(points)} chunks")
    return len(points)


__all__ = [
    "ingest_chunks",
    "embed_texts",
]
