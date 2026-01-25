"""
OSMOSE Pipeline V2 - Pass 0 Adapter

Adapter qui réutilise le code structural existant (src/knowbase/structural/)
et l'adapte au schéma V2.

Ce module:
1. Wrap StructuralGraphBuilder existant
2. Génère des docitem_id composites pour V2
3. Fournit le mapping chunk→DocItem pour Anchor Resolution (Pass 1.3b)
4. Peut persister vers le schéma Neo4j V2 (labels Document, Section)

Usage:
    from knowbase.stratified.pass0 import Pass0Adapter, build_structural_graph_v2

    # Via adapter
    adapter = Pass0Adapter()
    result = adapter.process_document(docling_document, tenant_id, doc_id)

    # Via fonction helper
    result = build_structural_graph_v2(docling_document, tenant_id, doc_id)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional, TYPE_CHECKING

from knowbase.structural.graph_builder import (
    StructuralGraphBuilder,
    StructuralGraphBuildResult,
)
from knowbase.structural.models import (
    DocItem,
    SectionInfo,
    TypeAwareChunk,
    DocumentVersion,
)

if TYPE_CHECKING:
    from neo4j import AsyncDriver

logger = logging.getLogger(__name__)


# ===================================
# RESULT V2
# ===================================

@dataclass
class ChunkToDocItemMapping:
    """Mapping d'un chunk vers ses DocItems source."""
    chunk_id: str
    docitem_ids: List[str]
    text: str
    char_start: int
    char_end: int

    def get_primary_docitem(self) -> Optional[str]:
        """Retourne le DocItem principal (premier de la liste)."""
        return self.docitem_ids[0] if self.docitem_ids else None


@dataclass
class Pass0Result:
    """
    Résultat de Pass 0 (Structural Graph) pour V2.

    Contient:
    - Les DocItems avec docitem_id V2 (composite)
    - Les Sections
    - Les Chunks (pour retrieval)
    - Le mapping chunk→DocItem (pour Anchor Resolution)
    """
    tenant_id: str
    doc_id: str
    doc_version_id: str

    # Structures
    doc_items: List[DocItem] = field(default_factory=list)
    sections: List[SectionInfo] = field(default_factory=list)
    chunks: List[TypeAwareChunk] = field(default_factory=list)

    # Mapping pour Anchor Resolution (Pass 1.3b)
    chunk_to_docitem_map: Dict[str, ChunkToDocItemMapping] = field(default_factory=dict)

    # Index inversé: docitem_id → liste de chunks qui le contiennent
    docitem_to_chunks_map: Dict[str, List[str]] = field(default_factory=dict)

    # Metadata
    doc_title: Optional[str] = None
    page_count: int = 0
    created_at: datetime = field(default_factory=datetime.utcnow)

    @property
    def item_count(self) -> int:
        return len(self.doc_items)

    @property
    def section_count(self) -> int:
        return len(self.sections)

    @property
    def chunk_count(self) -> int:
        return len(self.chunks)

    def get_docitem_for_chunk(self, chunk_id: str) -> Optional[str]:
        """
        Retourne le docitem_id principal pour un chunk donné.
        Utilisé par Anchor Resolution (Pass 1.3b).
        """
        mapping = self.chunk_to_docitem_map.get(chunk_id)
        return mapping.get_primary_docitem() if mapping else None

    def get_docitem_ids_for_chunk(self, chunk_id: str) -> List[str]:
        """
        Retourne tous les docitem_ids pour un chunk donné.
        Un chunk peut couvrir plusieurs DocItems (cas CROSS_DOCITEM).
        """
        mapping = self.chunk_to_docitem_map.get(chunk_id)
        return mapping.docitem_ids if mapping else []

    def get_docitem_by_id(self, docitem_id: str) -> Optional[DocItem]:
        """Retourne un DocItem par son ID composite V2."""
        for item in self.doc_items:
            if self._make_docitem_id(item) == docitem_id:
                return item
        return None

    def _make_docitem_id(self, item: DocItem) -> str:
        """Génère le docitem_id composite V2."""
        return f"{item.tenant_id}:{item.doc_id}:{item.item_id}"

    def summary(self) -> str:
        return (
            f"Pass0Result: {self.item_count} items, "
            f"{self.section_count} sections, "
            f"{self.chunk_count} chunks, "
            f"{len(self.chunk_to_docitem_map)} mappings"
        )


# ===================================
# ADAPTER V2
# ===================================

class Pass0Adapter:
    """
    Adapter V2 pour le Structural Graph.

    Réutilise StructuralGraphBuilder existant et adapte pour V2:
    - Génère docitem_id composites
    - Crée le mapping chunk→DocItem
    - (Optionnel) Persiste vers schéma Neo4j V2
    """

    def __init__(
        self,
        max_chunk_size: int = 3000,
        persist_artifacts: bool = False,
    ):
        """
        Initialise l'adapter.

        Args:
            max_chunk_size: Taille max des chunks (forwarded to StructuralGraphBuilder)
            persist_artifacts: Persister les artefacts JSON Docling
        """
        self.builder = StructuralGraphBuilder(
            max_chunk_size=max_chunk_size,
            persist_artifacts=persist_artifacts,
        )

    def process_document(
        self,
        docling_document: Any,
        tenant_id: str,
        doc_id: str,
        source_uri: Optional[str] = None,
    ) -> Pass0Result:
        """
        Traite un document Docling et retourne un Pass0Result V2.

        Cette méthode:
        1. Utilise StructuralGraphBuilder pour extraire items/sections/chunks
        2. Génère les docitem_id composites V2
        3. Crée le mapping chunk→DocItem pour Anchor Resolution

        Args:
            docling_document: DoclingDocument (depuis Docling)
            tenant_id: ID du tenant
            doc_id: ID du document
            source_uri: URI source (optionnel)

        Returns:
            Pass0Result avec structures et mappings V2
        """
        logger.info(f"[OSMOSE:Pass0:V2] Processing document {doc_id}...")

        # 1. Utiliser le builder existant
        build_result = self.builder.build_from_docling(
            docling_document=docling_document,
            tenant_id=tenant_id,
            doc_id=doc_id,
            source_uri=source_uri,
        )

        # 2. Créer le mapping chunk→DocItem
        chunk_to_docitem_map, docitem_to_chunks_map = self._build_mappings(
            chunks=build_result.chunks,
            doc_items=build_result.doc_items,
            tenant_id=tenant_id,
            doc_id=doc_id,
        )

        # 3. Construire le résultat V2
        result = Pass0Result(
            tenant_id=tenant_id,
            doc_id=doc_id,
            doc_version_id=build_result.doc_version.doc_version_id,
            doc_items=build_result.doc_items,
            sections=build_result.sections,
            chunks=build_result.chunks,
            chunk_to_docitem_map=chunk_to_docitem_map,
            docitem_to_chunks_map=docitem_to_chunks_map,
            doc_title=build_result.doc_version.title,
            page_count=build_result.doc_version.page_count,
        )

        logger.info(f"[OSMOSE:Pass0:V2] {result.summary()}")

        return result

    def _build_mappings(
        self,
        chunks: List[TypeAwareChunk],
        doc_items: List[DocItem],
        tenant_id: str,
        doc_id: str,
    ) -> tuple[Dict[str, ChunkToDocItemMapping], Dict[str, List[str]]]:
        """
        Construit les mappings chunk↔DocItem.

        Le TypeAwareChunk a déjà item_ids (liste des DocItem.item_id sources).
        On convertit en docitem_id composites V2.
        """
        chunk_to_docitem: Dict[str, ChunkToDocItemMapping] = {}
        docitem_to_chunks: Dict[str, List[str]] = {}

        # Index des DocItems par item_id pour lookup rapide
        items_by_id: Dict[str, DocItem] = {
            item.item_id: item for item in doc_items
        }

        char_offset = 0
        for chunk in chunks:
            # Convertir item_ids → docitem_ids V2
            docitem_ids = []
            for item_id in chunk.item_ids:
                item = items_by_id.get(item_id)
                if item:
                    docitem_id = f"{tenant_id}:{doc_id}:{item_id}"
                    docitem_ids.append(docitem_id)

                    # Index inverse
                    if docitem_id not in docitem_to_chunks:
                        docitem_to_chunks[docitem_id] = []
                    docitem_to_chunks[docitem_id].append(chunk.chunk_id)

            # Créer le mapping
            mapping = ChunkToDocItemMapping(
                chunk_id=chunk.chunk_id,
                docitem_ids=docitem_ids,
                text=chunk.text,
                char_start=char_offset,
                char_end=char_offset + len(chunk.text),
            )
            chunk_to_docitem[chunk.chunk_id] = mapping
            char_offset += len(chunk.text) + 1  # +1 pour séparateur

        logger.debug(
            f"[OSMOSE:Pass0:V2] Built {len(chunk_to_docitem)} chunk mappings, "
            f"{len(docitem_to_chunks)} docitem mappings"
        )

        return chunk_to_docitem, docitem_to_chunks

    async def process_and_persist_v2(
        self,
        docling_document: Any,
        tenant_id: str,
        doc_id: str,
        neo4j_driver: "AsyncDriver",
        source_uri: Optional[str] = None,
        database: str = "neo4j",
    ) -> Pass0Result:
        """
        Traite un document et persiste dans Neo4j avec le schéma V2.

        Crée les nodes:
        - Document (label V2)
        - Section (label V2)
        - DocItem

        Args:
            docling_document: DoclingDocument
            tenant_id: ID du tenant
            doc_id: ID du document
            neo4j_driver: Driver Neo4j async
            source_uri: URI source
            database: Base Neo4j

        Returns:
            Pass0Result
        """
        # 1. Process le document
        result = self.process_document(
            docling_document=docling_document,
            tenant_id=tenant_id,
            doc_id=doc_id,
            source_uri=source_uri,
        )

        # 2. Persister avec schéma V2
        await self._persist_to_neo4j_v2(result, neo4j_driver, database)

        return result

    async def _persist_to_neo4j_v2(
        self,
        result: Pass0Result,
        driver: "AsyncDriver",
        database: str,
    ) -> None:
        """
        Persiste dans Neo4j avec le schéma V2.

        Labels utilisés:
        - Document (pas DocumentContext)
        - Section (pas SectionContext)
        - DocItem
        """
        logger.info(f"[OSMOSE:Pass0:V2] Persisting to Neo4j (V2 schema)...")

        async with driver.session(database=database) as session:
            # Créer Document
            await session.execute_write(
                self._create_document_v2_tx,
                result,
            )

            # Créer Sections
            await session.execute_write(
                self._create_sections_v2_tx,
                result.sections,
                result.tenant_id,
                result.doc_id,
            )

            # Créer DocItems (batch)
            batch_size = 500
            for i in range(0, len(result.doc_items), batch_size):
                batch = result.doc_items[i:i + batch_size]
                await session.execute_write(
                    self._create_docitems_v2_tx,
                    batch,
                    result.tenant_id,
                    result.doc_id,
                )

        logger.info(
            f"[OSMOSE:Pass0:V2] Persisted: "
            f"{result.item_count} items, {result.section_count} sections"
        )

    @staticmethod
    def _create_document_v2_tx(tx, result: Pass0Result):
        """Transaction pour créer Document (V2)."""
        tx.run("""
            MERGE (d:Document {
                tenant_id: $tenant_id,
                doc_id: $doc_id
            })
            SET d.doc_version_id = $doc_version_id,
                d.title = $title,
                d.page_count = $page_count,
                d.item_count = $item_count,
                d.created_at = $created_at
        """, {
            "tenant_id": result.tenant_id,
            "doc_id": result.doc_id,
            "doc_version_id": result.doc_version_id,
            "title": result.doc_title,
            "page_count": result.page_count,
            "item_count": result.item_count,
            "created_at": result.created_at.isoformat(),
        })

    @staticmethod
    def _create_sections_v2_tx(tx, sections: List[SectionInfo], tenant_id: str, doc_id: str):
        """Transaction pour créer Sections (V2)."""
        for section in sections:
            # Générer section_id V2 (composite)
            section_id_v2 = f"{tenant_id}:{doc_id}:{section.section_id}"

            tx.run("""
                MERGE (s:Section {
                    tenant_id: $tenant_id,
                    section_id: $section_id
                })
                SET s.doc_id = $doc_id,
                    s.title = $title,
                    s.section_path = $section_path,
                    s.section_level = $section_level
                WITH s
                MATCH (d:Document {tenant_id: $tenant_id, doc_id: $doc_id})
                MERGE (d)-[:HAS_SECTION]->(s)
            """, {
                "tenant_id": tenant_id,
                "section_id": section_id_v2,
                "doc_id": doc_id,
                "title": section.title,
                "section_path": section.section_path,
                "section_level": section.section_level,
            })

            # Relation parent si applicable
            if section.parent_section_id:
                parent_id_v2 = f"{tenant_id}:{doc_id}:{section.parent_section_id}"
                tx.run("""
                    MATCH (child:Section {tenant_id: $tenant_id, section_id: $child_id})
                    MATCH (parent:Section {tenant_id: $tenant_id, section_id: $parent_id})
                    MERGE (child)-[:SUBSECTION_OF]->(parent)
                """, {
                    "tenant_id": tenant_id,
                    "child_id": section_id_v2,
                    "parent_id": parent_id_v2,
                })

    @staticmethod
    def _create_docitems_v2_tx(tx, items: List[DocItem], tenant_id: str, doc_id: str):
        """Transaction pour créer DocItems (V2, batch)."""
        for item in items:
            # Générer docitem_id V2 (composite)
            docitem_id = f"{tenant_id}:{doc_id}:{item.item_id}"
            section_id_v2 = f"{tenant_id}:{doc_id}:{item.section_id}" if item.section_id else None

            props = item.to_neo4j_properties()
            props["docitem_id"] = docitem_id  # Ajouter l'ID composite V2

            tx.run("""
                MERGE (i:DocItem {
                    tenant_id: $tenant_id,
                    docitem_id: $docitem_id
                })
                SET i += $props
                WITH i
                OPTIONAL MATCH (s:Section {
                    tenant_id: $tenant_id,
                    section_id: $section_id
                })
                FOREACH (_ IN CASE WHEN s IS NOT NULL THEN [1] ELSE [] END |
                    MERGE (s)-[:CONTAINS_ITEM]->(i)
                )
            """, {
                "tenant_id": tenant_id,
                "docitem_id": docitem_id,
                "section_id": section_id_v2,
                "props": props,
            })


# ===================================
# CONVENIENCE FUNCTIONS
# ===================================

def build_structural_graph_v2(
    docling_document: Any,
    tenant_id: str,
    doc_id: str,
    source_uri: Optional[str] = None,
) -> Pass0Result:
    """
    Fonction helper pour construire le Structural Graph V2.

    Usage simple sans instancier l'adapter:
        result = build_structural_graph_v2(doc, "default", "mydoc")

    Args:
        docling_document: DoclingDocument de Docling
        tenant_id: ID du tenant
        doc_id: ID du document
        source_uri: URI source (optionnel)

    Returns:
        Pass0Result avec structures et mappings V2
    """
    adapter = Pass0Adapter()
    return adapter.process_document(
        docling_document=docling_document,
        tenant_id=tenant_id,
        doc_id=doc_id,
        source_uri=source_uri,
    )


def get_docitem_id_v2(tenant_id: str, doc_id: str, item_id: str) -> str:
    """
    Génère un docitem_id composite V2.

    Format: {tenant_id}:{doc_id}:{item_id}

    Ce format permet:
    - Unicité globale (multi-tenant)
    - Lookup rapide par tenant + doc_id
    - Correspondance avec item_id Docling original
    """
    return f"{tenant_id}:{doc_id}:{item_id}"


def parse_docitem_id_v2(docitem_id: str) -> tuple[str, str, str]:
    """
    Parse un docitem_id composite V2.

    Returns:
        Tuple (tenant_id, doc_id, item_id)

    Raises:
        ValueError si format invalide
    """
    parts = docitem_id.split(":", 2)
    if len(parts) != 3:
        raise ValueError(f"Invalid docitem_id format: {docitem_id}")
    return parts[0], parts[1], parts[2]
