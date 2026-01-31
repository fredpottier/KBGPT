"""
OSMOSE Pipeline V2 - Cache Loader pour Pass 0

Ce module permet de charger un Pass0Result depuis le cache d'extraction V4,
évitant ainsi de re-parser le DoclingDocument.

Usage:
    from knowbase.stratified.pass0.cache_loader import load_pass0_from_cache

    result = load_pass0_from_cache(
        cache_path="/data/extraction_cache/abc123.v4cache.json",
        tenant_id="default"
    )
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from knowbase.stratified.pass0.adapter import (
    Pass0Result,
    ChunkToDocItemMapping,
)
from knowbase.structural.models import (
    DocItem,
    SectionInfo,
    TypeAwareChunk,
    ChunkKind,
    VisionObservation,
    TextOrigin,
)

logger = logging.getLogger(__name__)


@dataclass
class CacheLoadResult:
    """Résultat du chargement depuis le cache."""
    success: bool
    pass0_result: Optional[Pass0Result] = None
    cache_version: Optional[str] = None
    document_id: Optional[str] = None
    full_text: Optional[str] = None  # Contenu textuel complet (avec VISUAL_ENRICHMENT)
    doc_title: Optional[str] = None  # Titre du document
    vision_merged_count: int = 0     # DEPRECATED: Nombre de chunks FIGURE_TEXT enrichis
    # ADR-20260126: Vision Observations (séparées du graphe de connaissance)
    vision_observations: List[VisionObservation] = field(default_factory=list)
    # Layer R: sub-chunks meta (du JSON cache) et chemin vers le sidecar NPZ
    retrieval_embeddings: Optional[Dict] = None
    retrieval_embeddings_path: Optional[str] = None
    error: Optional[str] = None


def _load_legacy_v1_cache(
    cache_data: Dict,
    cache_path: str,
    tenant_id: str,
) -> CacheLoadResult:
    """
    Charge un cache legacy v1.0 en créant sections/chunks depuis les pages.

    Le format v1.0 a:
    - extracted_text.pages[]: liste de {slide_index, text}
    - extracted_text.full_text: texte complet
    - document_metadata.title: titre du document
    """
    try:
        # Extraire les métadonnées
        metadata = cache_data.get("metadata", {})
        doc_metadata = cache_data.get("document_metadata", {})
        extracted_text = cache_data.get("extracted_text", {})

        source_file = metadata.get("source_file", "unknown")
        # Générer un document_id depuis le nom du fichier
        document_id = Path(source_file).stem if source_file else Path(cache_path).stem

        doc_title = doc_metadata.get("title", document_id)
        full_text = extracted_text.get("full_text", "")
        pages = extracted_text.get("pages", [])

        if not pages:
            return CacheLoadResult(
                success=False,
                cache_version="v1_legacy",
                document_id=document_id,
                error="No pages found in legacy cache"
            )

        logger.info(f"[OSMOSE:CacheLoader:Legacy] Loading {len(pages)} pages from v1.0 cache")

        # Créer des chunks depuis les pages (1 chunk par page)
        chunks = []
        doc_items = []
        sections = []

        for page in pages:
            page_idx = page.get("slide_index", 0)
            page_text = page.get("text", "")

            if not page_text.strip():
                continue

            # Créer un chunk pour cette page
            chunk_id = f"chunk_p{page_idx:03d}"
            item_id = f"item_p{page_idx:03d}"

            chunk = TypeAwareChunk(
                chunk_id=chunk_id,
                tenant_id=tenant_id,
                doc_id=document_id,
                text=page_text,
                kind=ChunkKind.NARRATIVE_TEXT,
                page_no=page_idx,
                section_id=f"section_p{page_idx:03d}",
                item_ids=[item_id],
                is_relation_bearing=True,
                doc_version_id=f"{document_id}_v1",
            )
            chunks.append(chunk)

            # Créer un DocItem pour cette page
            doc_item = DocItem(
                tenant_id=tenant_id,
                doc_id=document_id,
                doc_version_id=f"{document_id}_v1",
                item_id=item_id,
                item_type="VISION_PAGE",  # Type pour slides/pages Vision
                text=page_text,
                page_no=page_idx,
                section_id=f"section_p{page_idx:03d}",
                charspan_start=0,
                charspan_end=len(page_text),
                reading_order_index=page_idx,
            )
            doc_items.append(doc_item)

            # Créer une section pour cette page
            section = SectionInfo(
                tenant_id=tenant_id,
                doc_id=document_id,
                doc_version_id=f"{document_id}_v1",
                section_id=f"section_p{page_idx:03d}",
                title=f"Page {page_idx}",
                section_path=f"/page_{page_idx}",
                section_level=1,
                parent_section_id=None,
            )
            sections.append(section)

        # Construire les mappings
        chunk_to_docitem_map: Dict[str, ChunkToDocItemMapping] = {}
        docitem_to_chunks_map: Dict[str, List[str]] = {}

        char_offset = 0
        for chunk in chunks:
            docitem_ids = [f"{tenant_id}:{document_id}:{item_id}" for item_id in chunk.item_ids]

            for docitem_id in docitem_ids:
                if docitem_id not in docitem_to_chunks_map:
                    docitem_to_chunks_map[docitem_id] = []
                docitem_to_chunks_map[docitem_id].append(chunk.chunk_id)

            mapping = ChunkToDocItemMapping(
                chunk_id=chunk.chunk_id,
                docitem_ids=docitem_ids,
                text=chunk.text,
                char_start=char_offset,
                char_end=char_offset + len(chunk.text),
            )
            chunk_to_docitem_map[chunk.chunk_id] = mapping
            char_offset += len(chunk.text) + 1

        # Construire Pass0Result
        pass0_result = Pass0Result(
            tenant_id=tenant_id,
            doc_id=document_id,
            doc_version_id=f"{document_id}_v1",
            doc_items=doc_items,
            sections=sections,
            chunks=chunks,
            chunk_to_docitem_map=chunk_to_docitem_map,
            docitem_to_chunks_map=docitem_to_chunks_map,
            doc_title=doc_title,
            page_count=len(pages),
        )

        logger.info(
            f"[OSMOSE:CacheLoader:Legacy] Created {len(chunks)} chunks, "
            f"{len(doc_items)} doc_items, {len(sections)} sections from {len(pages)} pages"
        )

        return CacheLoadResult(
            success=True,
            pass0_result=pass0_result,
            cache_version="v1_legacy",
            document_id=document_id,
            full_text=full_text,
            doc_title=doc_title,
            vision_merged_count=0,
        )

    except Exception as e:
        logger.error(f"[OSMOSE:CacheLoader:Legacy] Error loading legacy cache: {e}")
        return CacheLoadResult(
            success=False,
            cache_version="v1_legacy",
            error=str(e)
        )


def _build_vision_lookup(vision_results: List[Dict]) -> Dict[int, str]:
    """
    Construit un index page_no → texte Vision synthétisé.

    Transforme les résultats Vision (elements, relations) en texte lisible
    pour injection dans les chunks FIGURE_TEXT.
    """
    lookup = {}

    for vr in vision_results:
        page_no = vr.get("page_index", vr.get("page_no"))
        if page_no is None:
            continue

        # Synthétiser le contenu Vision en texte
        lines = []
        diagram_type = vr.get("diagram_type", "visual_content")
        lines.append(f"[Visual: {diagram_type}]")

        # Ajouter les éléments visibles
        elements = vr.get("elements", [])
        for elem in elements:
            elem_type = elem.get("type", "element")
            elem_text = elem.get("text", "")
            if elem_text:
                lines.append(f"- {elem_text}")

        # Ajouter les relations si présentes
        relations = vr.get("relations", [])
        for rel in relations:
            src = rel.get("source", "")
            tgt = rel.get("target", "")
            rel_type = rel.get("type", "related_to")
            if src and tgt:
                lines.append(f"- {src} → {rel_type} → {tgt}")

        if len(lines) > 1:  # Au moins diagram_type + du contenu
            lookup[page_no] = "\n".join(lines)

    return lookup


def _build_vision_observations(
    vision_results: List[Dict],
    tenant_id: str,
    doc_id: str,
) -> List[VisionObservation]:
    """
    Construit des VisionObservation depuis les résultats Vision.

    ADR-20260126: Vision est sorti du chemin de connaissance.
    Les observations sont stockées séparément pour navigation/UX.
    """
    import uuid
    observations = []

    for vr in vision_results:
        page_no = vr.get("page_index", vr.get("page_no"))
        if page_no is None:
            continue

        # Synthétiser la description
        lines = []
        diagram_type = vr.get("diagram_type", "visual_content")

        # Ajouter les éléments visibles
        elements = vr.get("elements", [])
        for elem in elements:
            elem_text = elem.get("text", "")
            if elem_text:
                lines.append(elem_text)

        # Ajouter les relations si présentes
        relations = vr.get("relations", [])
        for rel in relations:
            src = rel.get("source", "")
            tgt = rel.get("target", "")
            rel_type = rel.get("type", "related_to")
            if src and tgt:
                lines.append(f"{src} → {rel_type} → {tgt}")

        # Extraire les entités clés
        key_entities = []
        for elem in elements:
            elem_text = elem.get("text", "")
            if elem_text and len(elem_text) < 100:  # Probablement une entité
                key_entities.append(elem_text)

        description = "\n".join(lines) if lines else ""

        if description:  # Ne créer que si du contenu existe
            observation = VisionObservation(
                observation_id=f"vobs_{doc_id}_{page_no}_{uuid.uuid4().hex[:8]}",
                tenant_id=tenant_id,
                doc_id=doc_id,
                page_no=page_no,
                diagram_type=diagram_type,
                description=description,
                key_entities=key_entities[:10],  # Max 10 entités
                confidence=vr.get("confidence", 0.8),
                model=vr.get("model", "gpt-4o"),
                prompt_version=vr.get("prompt_version", ""),
                image_hash=vr.get("image_hash", ""),
                text_origin=TextOrigin.VISION_SEMANTIC,
            )
            observations.append(observation)

    return observations


def load_pass0_from_cache(
    cache_path: str,
    tenant_id: str = "default",
    merge_vision: bool = False,  # ADR-20260126: False par défaut (Vision hors Knowledge Path)
) -> CacheLoadResult:
    """
    Charge un Pass0Result depuis un fichier cache V2/V4/V5 ou legacy V1.

    Le cache contient:
    - extraction.stats.structural_graph.chunks[] (v2-v5)
    - extraction.vision_results[] (retournés comme VisionObservation, pas mergés)
    - extraction.full_text (avec [VISUAL_ENRICHMENT...])
    - extracted_text.pages[] (legacy v1.0)

    ADR-20260126: Vision est sorti du chemin de connaissance.
    Les vision_results sont retournés comme VisionObservation séparées,
    pas mergées dans les chunks FIGURE_TEXT.

    Args:
        cache_path: Chemin vers le fichier cache JSON
        tenant_id: ID du tenant
        merge_vision: DEPRECATED - Si True, merge le contenu Vision dans les chunks FIGURE_TEXT

    Returns:
        CacheLoadResult avec pass0_result et vision_observations si succès
    """
    try:
        cache_file = Path(cache_path)
        if not cache_file.exists():
            return CacheLoadResult(
                success=False,
                error=f"Cache file not found: {cache_path}"
            )

        with open(cache_file, "r", encoding="utf-8") as f:
            cache_data = json.load(f)

        # Vérifier la version
        cache_version = cache_data.get("cache_version", "unknown")

        # Détecter le format legacy v1.0 (metadata.version au lieu de cache_version)
        if cache_version == "unknown":
            metadata_version = cache_data.get("metadata", {}).get("version")
            if metadata_version == "1.0":
                cache_version = "v1_legacy"
                logger.info(f"[OSMOSE:CacheLoader] Detected legacy v1.0 format, using page-based extraction")
                return _load_legacy_v1_cache(cache_data, cache_path, tenant_id)

        if cache_version not in ["v2", "v3", "v4", "v5"]:
            return CacheLoadResult(
                success=False,
                cache_version=cache_version,
                error=f"Unsupported cache version: {cache_version}"
            )

        # Extraire les données
        extraction = cache_data.get("extraction", {})
        document_id = extraction.get("document_id", cache_data.get("document_id"))
        stats = extraction.get("stats", {})
        sg = stats.get("structural_graph", {})

        if not sg or "chunks" not in sg:
            return CacheLoadResult(
                success=False,
                cache_version=cache_version,
                document_id=document_id,
                error="Cache missing structural_graph.chunks"
            )

        # ADR-20260126: Charger les vision_results pour créer VisionObservation
        vision_results = extraction.get("vision_results", [])
        vision_observations = _build_vision_observations(
            vision_results, tenant_id, document_id or ""
        )
        if vision_observations:
            logger.info(
                f"[OSMOSE:CacheLoader] Created {len(vision_observations)} VisionObservations "
                f"(pages: {sorted(set(vo.page_no for vo in vision_observations))})"
            )

        # DEPRECATED: Construire le lookup Vision pour merge (si demandé)
        vision_lookup = {}
        if merge_vision:
            vision_lookup = _build_vision_lookup(vision_results)
            if vision_lookup:
                logger.warning(
                    f"[OSMOSE:CacheLoader] DEPRECATED: merge_vision=True, "
                    f"Vision content merged into chunks (pages: {sorted(vision_lookup.keys())})"
                )

        # Reconstruire les chunks avec merge Vision
        chunks = []
        vision_merged_count = 0
        for chunk_data in sg.get("chunks", []):
            kind_str = chunk_data.get("kind", "narrative")
            try:
                kind = ChunkKind(kind_str)
            except ValueError:
                kind = ChunkKind.NARRATIVE

            chunk_text = chunk_data["text"]

            # MERGE VISION: Si FIGURE_TEXT avec texte vide, utiliser Vision content
            if (
                merge_vision
                and kind == ChunkKind.FIGURE_TEXT
                and not chunk_text.strip()
            ):
                page_no = chunk_data.get("page_no")
                if page_no is not None and page_no in vision_lookup:
                    chunk_text = vision_lookup[page_no]
                    vision_merged_count += 1
                    logger.debug(
                        f"[OSMOSE:CacheLoader] Merged Vision into chunk "
                        f"{chunk_data['chunk_id']} (page {page_no})"
                    )

            chunk = TypeAwareChunk(
                chunk_id=chunk_data["chunk_id"],
                tenant_id=tenant_id,
                doc_id=document_id or "",
                text=chunk_text,
                kind=kind,
                page_no=chunk_data.get("page_no"),
                section_id=chunk_data.get("section_id"),
                item_ids=chunk_data.get("item_ids", []),
                is_relation_bearing=chunk_data.get("is_relation_bearing", False),
                doc_version_id=chunk_data.get("doc_version_id", ""),
            )
            chunks.append(chunk)

        if vision_merged_count > 0:
            logger.info(
                f"[OSMOSE:CacheLoader] Merged Vision content into "
                f"{vision_merged_count} FIGURE_TEXT chunks"
            )

        # Reconstruire les DocItems depuis le cache (ajouté en cache v5)
        doc_items = []
        # doc_version_id global (fallback si non présent dans chaque item)
        global_doc_version_id = sg.get("doc_version_id", f"{document_id}_v1")
        for item_data in sg.get("items", []):
            doc_item = DocItem(
                tenant_id=tenant_id,
                doc_id=document_id or "",
                doc_version_id=item_data.get("doc_version_id", global_doc_version_id),
                item_id=item_data.get("item_id", ""),
                item_type=item_data.get("item_type", "paragraph"),
                text=item_data.get("text", ""),
                page_no=item_data.get("page_no"),
                section_id=item_data.get("section_id", ""),
                charspan_start=item_data.get("charspan_start", 0),
                charspan_end=item_data.get("charspan_end", 0),
                reading_order_index=item_data.get("reading_order_index", 0),
            )
            doc_items.append(doc_item)

        if doc_items:
            logger.info(
                f"[OSMOSE:CacheLoader] Loaded {len(doc_items)} DocItems from cache"
            )

        # Construire les mappings
        chunk_to_docitem_map: Dict[str, ChunkToDocItemMapping] = {}
        docitem_to_chunks_map: Dict[str, List[str]] = {}

        char_offset = 0
        for chunk in chunks:
            # Convertir item_ids → docitem_ids V2
            docitem_ids = []
            for item_id in chunk.item_ids:
                docitem_id = f"{tenant_id}:{document_id}:{item_id}"
                docitem_ids.append(docitem_id)

                # Index inverse
                if docitem_id not in docitem_to_chunks_map:
                    docitem_to_chunks_map[docitem_id] = []
                docitem_to_chunks_map[docitem_id].append(chunk.chunk_id)

            mapping = ChunkToDocItemMapping(
                chunk_id=chunk.chunk_id,
                docitem_ids=docitem_ids,
                text=chunk.text,
                char_start=char_offset,
                char_end=char_offset + len(chunk.text),
            )
            chunk_to_docitem_map[chunk.chunk_id] = mapping
            char_offset += len(chunk.text) + 1

        # Extraire full_text et titre
        full_text = extraction.get("full_text", "")
        doc_title = extraction.get("title", "")

        # Construire Pass0Result
        pass0_result = Pass0Result(
            tenant_id=tenant_id,
            doc_id=document_id,
            doc_version_id=sg.get("doc_version_id", f"{document_id}_v1"),
            doc_items=doc_items,  # DocItems chargés depuis le cache (v5+)
            sections=[],   # Les Sections ne sont pas sérialisées dans le cache
            chunks=chunks,
            chunk_to_docitem_map=chunk_to_docitem_map,
            docitem_to_chunks_map=docitem_to_chunks_map,
            doc_title=doc_title or None,
            page_count=sg.get("item_count", 0) // 10,  # Estimation
        )

        # Layer R: Charger meta retrieval_embeddings du JSON + détecter sidecar NPZ
        retrieval_embeddings = stats.get("retrieval_embeddings")
        retrieval_embeddings_path = None
        if retrieval_embeddings and retrieval_embeddings.get("status") == "success":
            # Détecter le sidecar NPZ à côté du cache JSON
            for suffix in [".v5cache.json", ".v4cache.json", ".v3cache.json", ".v2cache.json"]:
                candidate = str(cache_path).replace(suffix, ".retrieval_embeddings.npz")
                if candidate != str(cache_path) and Path(candidate).exists():
                    retrieval_embeddings_path = candidate
                    break
            if retrieval_embeddings_path:
                logger.info(
                    f"[OSMOSE:CacheLoader] Found Layer R sidecar NPZ: "
                    f"{Path(retrieval_embeddings_path).name} "
                    f"({retrieval_embeddings.get('sub_chunk_count', '?')} sub-chunks)"
                )

        logger.info(
            f"[OSMOSE:CacheLoader] Loaded {len(chunks)} chunks, "
            f"{len(vision_observations)} VisionObservations from cache "
            f"for {document_id}"
        )

        return CacheLoadResult(
            success=True,
            pass0_result=pass0_result,
            cache_version=cache_version,
            document_id=document_id,
            full_text=full_text,
            doc_title=doc_title,
            vision_merged_count=vision_merged_count,
            vision_observations=vision_observations,
            retrieval_embeddings=retrieval_embeddings,
            retrieval_embeddings_path=retrieval_embeddings_path,
        )

    except Exception as e:
        logger.error(f"[OSMOSE:CacheLoader] Error loading cache: {e}")
        return CacheLoadResult(
            success=False,
            error=str(e)
        )


def list_cached_documents(
    cache_dir: str = "/data/extraction_cache",
) -> List[Dict[str, Any]]:
    """
    Liste tous les documents dans le cache d'extraction.

    Returns:
        Liste de dictionnaires avec info sur chaque cache
    """
    cache_path = Path(cache_dir)
    if not cache_path.exists():
        return []

    documents = []
    for cache_file in cache_path.glob("*.json"):
        try:
            with open(cache_file, "r", encoding="utf-8") as f:
                # Lire seulement les premiers éléments sans tout charger
                content = f.read(5000)  # Premiers 5KB suffisent pour metadata

            # Parser le début du JSON pour extraire les métadonnées
            import re
            doc_id_match = re.search(r'"document_id":\s*"([^"]+)"', content)
            version_match = re.search(r'"cache_version":\s*"([^"]+)"', content)
            created_match = re.search(r'"created_at":\s*"([^"]+)"', content)

            doc_info = {
                "cache_file": cache_file.name,
                "cache_path": str(cache_file),
                "document_id": doc_id_match.group(1) if doc_id_match else "unknown",
                "cache_version": version_match.group(1) if version_match else "unknown",
                "created_at": created_match.group(1) if created_match else None,
                "size_bytes": cache_file.stat().st_size,
            }
            documents.append(doc_info)

        except Exception as e:
            logger.warning(f"[OSMOSE:CacheLoader] Error reading {cache_file}: {e}")
            continue

    # Trier par date de création (plus récent en premier)
    documents.sort(key=lambda x: x.get("created_at", ""), reverse=True)

    return documents


def get_cache_path_for_file(
    file_path: str,
    cache_dir: str = "/data/extraction_cache",
) -> Optional[str]:
    """
    Trouve le fichier cache correspondant à un fichier source.

    Le cache utilise le hash SHA256 du fichier comme clé.
    """
    import hashlib

    source_path = Path(file_path)
    if not source_path.exists():
        return None

    # Calculer le hash du fichier
    sha256 = hashlib.sha256()
    with open(source_path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            sha256.update(chunk)
    file_hash = sha256.hexdigest()

    # Chercher le cache correspondant
    cache_path = Path(cache_dir)
    for version in ["v4", "v3", "v2"]:
        cache_file = cache_path / f"{file_hash}.{version}cache.json"
        if cache_file.exists():
            return str(cache_file)

    return None


__all__ = [
    "CacheLoadResult",
    "load_pass0_from_cache",
    "list_cached_documents",
    "get_cache_path_for_file",
]
