"""
OSMOSE Structural Graph - Graph Builder (Option C)

Module bridge qui intègre le Structural Graph dans le pipeline d'extraction.

Ce module:
1. Extrait les DocItems depuis DoclingDocument
2. Assigne les sections et calcule les profils
3. Crée les chunks type-aware
4. Persiste le tout dans Neo4j

Usage dans le pipeline:
    from knowbase.structural import StructuralGraphBuilder

    builder = StructuralGraphBuilder(neo4j_driver)
    result = await builder.build_from_docling_result(
        docling_result=docling_result,
        tenant_id="default",
        doc_id="mydoc",
    )

Spec: doc/ongoing/ADR_STRUCTURAL_GRAPH_FROM_DOCLING.md
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, TYPE_CHECKING

from knowbase.structural.docitem_builder import DocItemBuilder, DocItemBuildResult
from knowbase.structural.section_profiler import SectionProfiler, analyze_document_structure
from knowbase.structural.type_aware_chunker import TypeAwareChunker, analyze_chunks
from knowbase.structural.models import (
    DocItem,
    DocumentVersion,
    PageContext,
    SectionInfo,
    TypeAwareChunk,
    ChunkKind,
)

if TYPE_CHECKING:
    from neo4j import AsyncDriver, Driver

logger = logging.getLogger(__name__)


# ===================================
# CONFIGURATION
# ===================================

# Feature flag pour activer/désactiver Option C
USE_STRUCTURAL_GRAPH = os.getenv("USE_STRUCTURAL_GRAPH", "false").lower() == "true"

# Chemin pour persister les artefacts DoclingDocument (D7)
DOCLING_ARTIFACTS_PATH = os.getenv(
    "DOCLING_ARTIFACTS_PATH",
    "data/docling_artifacts"
)


# ===================================
# GRAPH BUILD RESULT
# ===================================

class StructuralGraphBuildResult:
    """Résultat de la construction du Structural Graph."""

    def __init__(
        self,
        doc_items: List[DocItem],
        sections: List[SectionInfo],
        chunks: List[TypeAwareChunk],
        doc_version: DocumentVersion,
        page_contexts: List[PageContext],
        doc_dict: Dict[str, Any],
    ):
        self.doc_items = doc_items
        self.sections = sections
        self.chunks = chunks
        self.doc_version = doc_version
        self.page_contexts = page_contexts
        self.doc_dict = doc_dict

        # Analyse
        self._structure_analysis = None
        self._chunk_analysis = None

    @property
    def item_count(self) -> int:
        return len(self.doc_items)

    @property
    def section_count(self) -> int:
        return len(self.sections)

    @property
    def chunk_count(self) -> int:
        return len(self.chunks)

    @property
    def narrative_chunk_count(self) -> int:
        return sum(1 for c in self.chunks if c.kind == ChunkKind.NARRATIVE_TEXT)

    @property
    def structure_analysis(self) -> Dict[str, Any]:
        if self._structure_analysis is None:
            self._structure_analysis = analyze_document_structure(
                self.doc_items, self.sections
            )
        return self._structure_analysis

    @property
    def chunk_analysis(self) -> Dict[str, Any]:
        if self._chunk_analysis is None:
            self._chunk_analysis = analyze_chunks(self.chunks)
        return self._chunk_analysis

    def summary(self) -> str:
        """Résumé du build."""
        return (
            f"StructuralGraphBuildResult: "
            f"{self.item_count} items, "
            f"{self.section_count} sections, "
            f"{self.chunk_count} chunks "
            f"({self.narrative_chunk_count} narrative), "
            f"hash={self.doc_version.doc_version_id[:20]}..."
        )


# ===================================
# STRUCTURAL GRAPH BUILDER
# ===================================

class StructuralGraphBuilder:
    """
    Constructeur du Structural Graph depuis DoclingDocument.

    Orchestre:
    1. DocItemBuilder: extraction items
    2. SectionProfiler: assignment sections
    3. TypeAwareChunker: création chunks
    4. Persistance Neo4j (optionnel)
    5. Persistance artefact JSON (optionnel)

    Usage:
        builder = StructuralGraphBuilder()

        # Build sans persistance (pour tests/analyse)
        result = builder.build_from_docling(
            docling_document=doc,
            tenant_id="default",
            doc_id="mydoc",
        )

        # Build avec persistance Neo4j
        result = await builder.build_and_persist(
            docling_document=doc,
            tenant_id="default",
            doc_id="mydoc",
            neo4j_driver=driver,
        )
    """

    def __init__(
        self,
        max_chunk_size: int = 3000,
        persist_artifacts: bool = True,
        artifacts_path: Optional[str] = None,
    ):
        """
        Initialise le builder.

        Args:
            max_chunk_size: Taille max des chunks narratifs
            persist_artifacts: Persister les artefacts DoclingDocument (D7)
            artifacts_path: Chemin des artefacts (default: DOCLING_ARTIFACTS_PATH)
        """
        self.max_chunk_size = max_chunk_size
        self.persist_artifacts = persist_artifacts
        self.artifacts_path = artifacts_path or DOCLING_ARTIFACTS_PATH

    def build_from_docling(
        self,
        docling_document: Any,
        tenant_id: str,
        doc_id: str,
        source_uri: Optional[str] = None,
        pipeline_version: Optional[str] = None,
    ) -> StructuralGraphBuildResult:
        """
        Construit le Structural Graph depuis un DoclingDocument.

        Cette méthode est synchrone et ne persiste rien dans Neo4j.
        Utilisez build_and_persist() pour la version avec persistance.

        Args:
            docling_document: DoclingDocument de Docling
            tenant_id: ID du tenant
            doc_id: ID du document
            source_uri: URI source (optionnel)
            pipeline_version: Version du pipeline (optionnel)

        Returns:
            StructuralGraphBuildResult
        """
        logger.info(f"[StructuralGraphBuilder] Building graph for doc={doc_id}...")

        # 1. Extraire les DocItems
        item_builder = DocItemBuilder(
            tenant_id=tenant_id,
            doc_id=doc_id,
            source_uri=source_uri,
            pipeline_version=pipeline_version,
        )
        item_result = item_builder.build_from_docling(docling_document)

        logger.info(f"[StructuralGraphBuilder] Extracted {item_result.item_count} items")

        # 2. Assigner les sections et calculer les profils
        section_profiler = SectionProfiler(
            tenant_id=tenant_id,
            doc_id=doc_id,
            doc_version_id=item_result.doc_version.doc_version_id,
        )
        sections = section_profiler.assign_sections(item_result.doc_items)

        logger.info(f"[StructuralGraphBuilder] Assigned {len(sections)} sections")

        # 3. Créer les chunks type-aware
        chunker = TypeAwareChunker(
            tenant_id=tenant_id,
            doc_id=doc_id,
            doc_version_id=item_result.doc_version.doc_version_id,
            max_chunk_size=self.max_chunk_size,
        )
        chunks = chunker.create_chunks(item_result.doc_items, sections)

        logger.info(f"[StructuralGraphBuilder] Created {len(chunks)} chunks")

        result = StructuralGraphBuildResult(
            doc_items=item_result.doc_items,
            sections=sections,
            chunks=chunks,
            doc_version=item_result.doc_version,
            page_contexts=item_result.page_contexts,
            doc_dict=item_result.doc_dict,
        )

        logger.info(f"[StructuralGraphBuilder] {result.summary()}")

        return result

    async def build_and_persist(
        self,
        docling_document: Any,
        tenant_id: str,
        doc_id: str,
        neo4j_driver: "AsyncDriver",
        source_uri: Optional[str] = None,
        pipeline_version: Optional[str] = None,
        database: str = "neo4j",
    ) -> StructuralGraphBuildResult:
        """
        Construit et persiste le Structural Graph.

        Args:
            docling_document: DoclingDocument de Docling
            tenant_id: ID du tenant
            doc_id: ID du document
            neo4j_driver: Driver Neo4j async
            source_uri: URI source (optionnel)
            pipeline_version: Version du pipeline (optionnel)
            database: Nom de la base Neo4j

        Returns:
            StructuralGraphBuildResult
        """
        # 1. Build le graph
        result = self.build_from_docling(
            docling_document=docling_document,
            tenant_id=tenant_id,
            doc_id=doc_id,
            source_uri=source_uri,
            pipeline_version=pipeline_version,
        )

        # 2. Persister l'artefact JSON (D7)
        if self.persist_artifacts:
            await self._persist_artifact(
                tenant_id=tenant_id,
                doc_id=doc_id,
                doc_hash=result.doc_version.doc_version_id,
                doc_dict=result.doc_dict,
            )

        # 3. Persister dans Neo4j
        await self._persist_to_neo4j(
            result=result,
            driver=neo4j_driver,
            database=database,
        )

        return result

    async def _persist_artifact(
        self,
        tenant_id: str,
        doc_id: str,
        doc_hash: str,
        doc_dict: Dict[str, Any],
    ) -> None:
        """
        Persiste l'artefact DoclingDocument en JSON.

        Spec: ADR D7
        """
        try:
            # Créer le chemin: data/docling_artifacts/{tenant_id}/{doc_id}/{doc_hash}.json
            artifact_dir = Path(self.artifacts_path) / tenant_id / doc_id
            artifact_dir.mkdir(parents=True, exist_ok=True)

            # Nom de fichier basé sur le hash (sans le préfixe v1:)
            hash_short = doc_hash.replace("v1:", "")[:32]
            artifact_path = artifact_dir / f"{hash_short}.json"

            # Sauvegarder (compression possible en futur - D7.3)
            with open(artifact_path, "w", encoding="utf-8") as f:
                json.dump(doc_dict, f, ensure_ascii=False, indent=2)

            logger.info(f"[StructuralGraphBuilder] Artifact saved: {artifact_path}")

        except Exception as e:
            logger.warning(f"[StructuralGraphBuilder] Failed to save artifact: {e}")

    async def _persist_to_neo4j(
        self,
        result: StructuralGraphBuildResult,
        driver: "AsyncDriver",
        database: str,
    ) -> None:
        """
        Persiste le Structural Graph dans Neo4j.

        Crée les nœuds:
        - DocumentVersion
        - PageContext
        - SectionContext (enrichi)
        - DocItem
        - TypeAwareChunk

        Et les relations:
        - (DocumentContext)-[:HAS_VERSION]->(DocumentVersion)
        - (DocumentVersion)-[:HAS_PAGE]->(PageContext)
        - (DocumentVersion)-[:HAS_SECTION]->(SectionContext)
        - (SectionContext)-[:CONTAINS]->(DocItem)
        - (DocItem)-[:ON_PAGE]->(PageContext)
        - (TypeAwareChunk)-[:DERIVED_FROM]->(DocItem)
        """
        logger.info(f"[StructuralGraphBuilder] Persisting to Neo4j...")

        async with driver.session(database=database) as session:
            # Batch les opérations pour performance
            await session.execute_write(
                self._create_version_and_pages_tx,
                result.doc_version,
                result.page_contexts,
            )

            await session.execute_write(
                self._create_sections_tx,
                result.sections,
            )

            # Batch les DocItems (peuvent être nombreux)
            batch_size = 500
            for i in range(0, len(result.doc_items), batch_size):
                batch = result.doc_items[i:i + batch_size]
                await session.execute_write(
                    self._create_docitems_tx,
                    batch,
                )

            # Batch les chunks
            for i in range(0, len(result.chunks), batch_size):
                batch = result.chunks[i:i + batch_size]
                await session.execute_write(
                    self._create_chunks_tx,
                    batch,
                )

        logger.info(
            f"[StructuralGraphBuilder] Persisted: "
            f"{len(result.doc_items)} items, "
            f"{len(result.sections)} sections, "
            f"{len(result.chunks)} chunks"
        )

    def persist_to_neo4j_sync(
        self,
        result: StructuralGraphBuildResult,
        neo4j_client: Any = None,
    ) -> None:
        """
        Persiste le Structural Graph dans Neo4j (version synchrone).

        Compatible avec le Neo4jClient existant du projet.

        Args:
            result: Résultat de build_from_docling()
            neo4j_client: Instance de Neo4jClient (ou None pour auto-detect)
        """
        # Auto-detect Neo4j client si non fourni
        if neo4j_client is None:
            try:
                from knowbase.common.clients.neo4j_client import get_neo4j_client
                from knowbase.config.settings import get_settings

                settings = get_settings()
                neo4j_client = get_neo4j_client(
                    uri=settings.neo4j_uri,
                    user=settings.neo4j_user,
                    password=settings.neo4j_password,
                    database="neo4j"
                )
            except Exception as e:
                logger.warning(f"[StructuralGraphBuilder] Could not get Neo4j client: {e}")
                return

        if not neo4j_client.is_connected():
            logger.warning("[StructuralGraphBuilder] Neo4j not connected, skipping persistence")
            return

        logger.info(f"[StructuralGraphBuilder] Persisting to Neo4j (sync)...")

        try:
            with neo4j_client.driver.session(database="neo4j") as session:
                # Créer DocumentVersion et Pages
                session.execute_write(
                    self._create_version_and_pages_tx,
                    result.doc_version,
                    result.page_contexts,
                )

                # Créer Sections
                session.execute_write(
                    self._create_sections_tx,
                    result.sections,
                )

                # Batch les DocItems (peuvent être nombreux)
                batch_size = 500
                for i in range(0, len(result.doc_items), batch_size):
                    batch = result.doc_items[i:i + batch_size]
                    session.execute_write(
                        self._create_docitems_tx,
                        batch,
                    )

                # Batch les chunks
                for i in range(0, len(result.chunks), batch_size):
                    batch = result.chunks[i:i + batch_size]
                    session.execute_write(
                        self._create_chunks_tx,
                        batch,
                    )

            logger.info(
                f"[StructuralGraphBuilder] Persisted (sync): "
                f"{len(result.doc_items)} items, "
                f"{len(result.sections)} sections, "
                f"{len(result.chunks)} chunks"
            )

        except Exception as e:
            logger.error(f"[StructuralGraphBuilder] Neo4j persistence failed: {e}")
            raise

    @staticmethod
    def _create_version_and_pages_tx(tx, doc_version: DocumentVersion, pages: List[PageContext]):
        """Transaction pour créer DocumentVersion et PageContext."""
        # Créer/mettre à jour DocumentVersion
        tx.run("""
            MERGE (v:DocumentVersion {
                tenant_id: $tenant_id,
                doc_id: $doc_id,
                doc_version_id: $doc_version_id
            })
            SET v += $props
            WITH v
            MATCH (d:DocumentContext {tenant_id: $tenant_id, doc_id: $doc_id})
            MERGE (d)-[:HAS_VERSION]->(v)
        """, {
            "tenant_id": doc_version.tenant_id,
            "doc_id": doc_version.doc_id,
            "doc_version_id": doc_version.doc_version_id,
            "props": doc_version.to_neo4j_properties(),
        })

        # Créer les PageContext
        for page in pages:
            tx.run("""
                MERGE (p:PageContext {
                    tenant_id: $tenant_id,
                    doc_version_id: $doc_version_id,
                    page_no: $page_no
                })
                SET p += $props
                WITH p
                MATCH (v:DocumentVersion {
                    tenant_id: $tenant_id,
                    doc_version_id: $doc_version_id
                })
                MERGE (v)-[:HAS_PAGE]->(p)
            """, {
                "tenant_id": page.tenant_id,
                "doc_version_id": page.doc_version_id,
                "page_no": page.page_no,
                "props": page.to_neo4j_properties(),
            })

    @staticmethod
    def _create_sections_tx(tx, sections: List[SectionInfo]):
        """Transaction pour créer les SectionContext."""
        for section in sections:
            tx.run("""
                MERGE (s:SectionContext {
                    tenant_id: $tenant_id,
                    doc_version_id: $doc_version_id,
                    section_id: $section_id
                })
                SET s += $props
                WITH s
                MATCH (v:DocumentVersion {
                    tenant_id: $tenant_id,
                    doc_version_id: $doc_version_id
                })
                MERGE (v)-[:HAS_SECTION]->(s)
            """, {
                "tenant_id": section.tenant_id,
                "doc_version_id": section.doc_version_id,
                "section_id": section.section_id,
                "props": section.to_neo4j_properties(),
            })

            # Créer relation parent si applicable
            if section.parent_section_id:
                tx.run("""
                    MATCH (child:SectionContext {
                        tenant_id: $tenant_id,
                        doc_version_id: $doc_version_id,
                        section_id: $child_id
                    })
                    MATCH (parent:SectionContext {
                        tenant_id: $tenant_id,
                        doc_version_id: $doc_version_id,
                        section_id: $parent_id
                    })
                    MERGE (child)-[:SUBSECTION_OF]->(parent)
                """, {
                    "tenant_id": section.tenant_id,
                    "doc_version_id": section.doc_version_id,
                    "child_id": section.section_id,
                    "parent_id": section.parent_section_id,
                })

    @staticmethod
    def _create_docitems_tx(tx, items: List[DocItem]):
        """Transaction pour créer les DocItem (batch)."""
        for item in items:
            tx.run("""
                MERGE (i:DocItem {
                    tenant_id: $tenant_id,
                    doc_id: $doc_id,
                    doc_version_id: $doc_version_id,
                    item_id: $item_id
                })
                SET i += $props
                WITH i
                OPTIONAL MATCH (s:SectionContext {
                    tenant_id: $tenant_id,
                    doc_version_id: $doc_version_id,
                    section_id: $section_id
                })
                FOREACH (_ IN CASE WHEN s IS NOT NULL THEN [1] ELSE [] END |
                    MERGE (s)-[:CONTAINS]->(i)
                )
                WITH i
                OPTIONAL MATCH (p:PageContext {
                    tenant_id: $tenant_id,
                    doc_version_id: $doc_version_id,
                    page_no: $page_no
                })
                FOREACH (_ IN CASE WHEN p IS NOT NULL THEN [1] ELSE [] END |
                    MERGE (i)-[:ON_PAGE]->(p)
                )
            """, {
                "tenant_id": item.tenant_id,
                "doc_id": item.doc_id,
                "doc_version_id": item.doc_version_id,
                "item_id": item.item_id,
                "section_id": item.section_id,
                "page_no": item.page_no,
                "props": item.to_neo4j_properties(),
            })

    @staticmethod
    def _create_chunks_tx(tx, chunks: List[TypeAwareChunk]):
        """Transaction pour créer les TypeAwareChunk (batch)."""
        for chunk in chunks:
            tx.run("""
                MERGE (c:TypeAwareChunk {
                    tenant_id: $tenant_id,
                    chunk_id: $chunk_id
                })
                SET c += $props
            """, {
                "tenant_id": chunk.tenant_id,
                "chunk_id": chunk.chunk_id,
                "props": chunk.to_neo4j_properties(),
            })

            # Créer relations DERIVED_FROM vers les DocItems
            for item_id in chunk.item_ids:
                tx.run("""
                    MATCH (c:TypeAwareChunk {tenant_id: $tenant_id, chunk_id: $chunk_id})
                    MATCH (i:DocItem {
                        tenant_id: $tenant_id,
                        doc_version_id: $doc_version_id,
                        item_id: $item_id
                    })
                    MERGE (c)-[:DERIVED_FROM]->(i)
                """, {
                    "tenant_id": chunk.tenant_id,
                    "chunk_id": chunk.chunk_id,
                    "doc_version_id": chunk.doc_version_id,
                    "item_id": item_id,
                })


# ===================================
# CONVENIENCE FUNCTIONS
# ===================================

def is_structural_graph_enabled() -> bool:
    """Vérifie si le Structural Graph est activé."""
    return USE_STRUCTURAL_GRAPH


def convert_chunks_for_relation_extraction(
    chunks: List[TypeAwareChunk],
    proto_concepts: List[Any],
    relation_bearing_only: bool = True,
) -> List[Dict[str, Any]]:
    """
    Convertit les TypeAwareChunks au format attendu par LLMRelationExtractor.

    Cette fonction:
    1. Filtre les chunks relation-bearing si demandé (NARRATIVE_TEXT uniquement)
    2. Annote chaque chunk avec `anchored_concepts` basé sur les ProtoConcepts
    3. Retourne le format Dict attendu par extract_relations_chunk_aware()

    Args:
        chunks: Liste des TypeAwareChunks du Structural Graph
        proto_concepts: Liste des ProtoConcepts extraits (avec anchors)
        relation_bearing_only: Si True, ne retourne que les chunks NARRATIVE_TEXT

    Returns:
        Liste de dicts au format attendu par LLMRelationExtractor:
        {
            "chunk_id": str,
            "text": str,
            "char_start": int,
            "char_end": int,
            "page_no": int,
            "anchored_concepts": [{"concept_id": str, ...}, ...]
        }
    """
    import re

    # 1. Filtrer si demandé
    if relation_bearing_only:
        filtered_chunks = [c for c in chunks if c.is_relation_bearing]
        logger.info(
            f"[StructuralGraph] Filtered {len(chunks)} chunks to "
            f"{len(filtered_chunks)} relation-bearing chunks"
        )
    else:
        filtered_chunks = chunks

    if not filtered_chunks:
        return []

    # 2. Construire index texte → chunk pour lookup rapide
    # On recherche les mentions de concepts dans le texte de chaque chunk

    # 3. Construire liste de surface_forms pour chaque proto
    proto_surface_forms: Dict[str, List[str]] = {}
    proto_by_surface: Dict[str, List[str]] = {}  # surface_form → proto_ids

    for proto in proto_concepts:
        proto_id = getattr(proto, 'concept_id', None)
        if not proto_id:
            continue

        # Collecter toutes les surface forms
        forms = set()
        label = getattr(proto, 'concept_name', '')
        if label:
            forms.add(label.lower())

        # Ajouter les surface_forms si disponibles
        if hasattr(proto, 'surface_forms') and proto.surface_forms:
            for sf in proto.surface_forms:
                forms.add(sf.lower())

        # Ajouter depuis les anchors si disponibles
        if hasattr(proto, 'anchors') and proto.anchors:
            for anchor in proto.anchors:
                surface_form = getattr(anchor, 'surface_form', '')
                if surface_form and len(surface_form) < 100:  # Éviter les quotes trop longues
                    forms.add(surface_form.lower())

        proto_surface_forms[proto_id] = list(forms)

        # Index inverse
        for form in forms:
            if form not in proto_by_surface:
                proto_by_surface[form] = []
            proto_by_surface[form].append(proto_id)

    # 4. Pour chaque chunk, trouver les concepts mentionnés
    result_chunks = []
    char_offset = 0

    for chunk in filtered_chunks:
        chunk_text_lower = chunk.text.lower()

        # Trouver les concepts ancrés dans ce chunk
        anchored_concepts = []
        seen_protos = set()

        for form, proto_ids in proto_by_surface.items():
            if form in chunk_text_lower:
                for proto_id in proto_ids:
                    if proto_id not in seen_protos:
                        seen_protos.add(proto_id)
                        anchored_concepts.append({
                            "concept_id": proto_id,
                            "surface_form": form,
                        })

        # Construire le dict au format attendu
        chunk_dict = {
            "chunk_id": chunk.chunk_id,
            "text": chunk.text,
            "char_start": char_offset,
            "char_end": char_offset + len(chunk.text),
            "page_no": chunk.page_no,
            "section_id": chunk.section_id,
            "kind": chunk.kind.value if hasattr(chunk.kind, 'value') else str(chunk.kind),
            "is_relation_bearing": chunk.is_relation_bearing,
            "anchored_concepts": anchored_concepts,
            # Métadonnées additionnelles
            "item_ids": chunk.item_ids,
            "doc_version_id": chunk.doc_version_id,
        }

        result_chunks.append(chunk_dict)
        char_offset += len(chunk.text) + 1  # +1 pour séparateur virtuel

    logger.info(
        f"[StructuralGraph] Converted {len(result_chunks)} chunks for relation extraction, "
        f"avg {sum(len(c['anchored_concepts']) for c in result_chunks) / max(len(result_chunks), 1):.1f} "
        f"concepts/chunk"
    )

    return result_chunks


def get_narrative_chunks_for_relations(
    structural_graph_result: "StructuralGraphBuildResult",
    proto_concepts: List[Any],
) -> List[Dict[str, Any]]:
    """
    Raccourci pour obtenir les chunks narratifs prêts pour l'extraction de relations.

    Args:
        structural_graph_result: Résultat de StructuralGraphBuilder.build_from_docling()
        proto_concepts: Liste des ProtoConcepts extraits

    Returns:
        Liste de dicts au format LLMRelationExtractor
    """
    return convert_chunks_for_relation_extraction(
        chunks=structural_graph_result.chunks,
        proto_concepts=proto_concepts,
        relation_bearing_only=True,
    )


async def build_structural_graph_from_docling(
    docling_document: Any,
    tenant_id: str,
    doc_id: str,
    neo4j_driver: Optional["AsyncDriver"] = None,
    source_uri: Optional[str] = None,
) -> Optional[StructuralGraphBuildResult]:
    """
    Fonction helper pour construire le Structural Graph.

    Si neo4j_driver est fourni, persiste dans Neo4j.
    Sinon, retourne juste le résultat.

    Args:
        docling_document: DoclingDocument de Docling
        tenant_id: ID du tenant
        doc_id: ID du document
        neo4j_driver: Driver Neo4j (optionnel)
        source_uri: URI source (optionnel)

    Returns:
        StructuralGraphBuildResult ou None si désactivé
    """
    if not is_structural_graph_enabled():
        logger.debug("[StructuralGraph] Feature disabled, skipping build")
        return None

    builder = StructuralGraphBuilder()

    if neo4j_driver:
        return await builder.build_and_persist(
            docling_document=docling_document,
            tenant_id=tenant_id,
            doc_id=doc_id,
            neo4j_driver=neo4j_driver,
            source_uri=source_uri,
        )
    else:
        return builder.build_from_docling(
            docling_document=docling_document,
            tenant_id=tenant_id,
            doc_id=doc_id,
            source_uri=source_uri,
        )
