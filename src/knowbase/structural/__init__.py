"""
OSMOSE Structural Graph - Option C

Module pour l'extraction et gestion du Structural Graph depuis DoclingDocument.

Ce module remplace les heuristiques basées sur les markers linéarisés par une
consommation directe de la structure native de Docling.

Spec: doc/ongoing/ADR_STRUCTURAL_GRAPH_FROM_DOCLING.md

Composants:
- models.py: Modèles Pydantic (DocItem, DocumentVersion, StructuralProfile, etc.)
- docitem_builder.py: Extraction DoclingDocument → DocItem
- section_profiler.py: Assignment DocItem → Section et calcul profils
- type_aware_chunker.py: Chunking NARRATIVE/TABLE/FIGURE
- neo4j_schema.py: Schéma Neo4j (constraints, indexes)
"""

from knowbase.structural.models import (
    # Enums
    BboxUnit,
    ChunkKind,
    DocItemType,
    # Constantes
    DOCLING_LABEL_MAPPING,
    RELATION_BEARING_TYPES,
    STRUCTURE_BEARING_TYPES,
    # Modèles
    DocItem,
    DocumentVersion,
    PageContext,
    SectionInfo,
    StructuralProfile,
    TypeAwareChunk,
    # Fonctions
    compute_doc_hash,
    map_docling_label,
)

from knowbase.structural.docitem_builder import (
    DocItemBuilder,
    DocItemBuildResult,
    table_to_text,
    table_to_json,
    figure_to_text,
    select_primary_prov,
    compute_reading_order,
)

from knowbase.structural.section_profiler import (
    SectionProfiler,
    is_item_relation_bearing,
    filter_relation_bearing_items,
    analyze_document_structure,
)

from knowbase.structural.type_aware_chunker import (
    TypeAwareChunker,
    get_narrative_chunks,
    get_table_chunks,
    get_figure_chunks,
    get_code_chunks,
    analyze_chunks,
)

from knowbase.structural.graph_builder import (
    StructuralGraphBuilder,
    StructuralGraphBuildResult,
    build_structural_graph_from_docling,
    is_structural_graph_enabled,
    USE_STRUCTURAL_GRAPH,
)

__all__ = [
    # Enums
    "BboxUnit",
    "ChunkKind",
    "DocItemType",
    # Constantes
    "DOCLING_LABEL_MAPPING",
    "RELATION_BEARING_TYPES",
    "STRUCTURE_BEARING_TYPES",
    # Modèles
    "DocItem",
    "DocumentVersion",
    "PageContext",
    "SectionInfo",
    "StructuralProfile",
    "TypeAwareChunk",
    # Fonctions modèles
    "compute_doc_hash",
    "map_docling_label",
    # Builder
    "DocItemBuilder",
    "DocItemBuildResult",
    "table_to_text",
    "table_to_json",
    "figure_to_text",
    "select_primary_prov",
    "compute_reading_order",
    # Profiler
    "SectionProfiler",
    "is_item_relation_bearing",
    "filter_relation_bearing_items",
    "analyze_document_structure",
    # Chunker
    "TypeAwareChunker",
    "get_narrative_chunks",
    "get_table_chunks",
    "get_figure_chunks",
    "get_code_chunks",
    "analyze_chunks",
    # Graph Builder
    "StructuralGraphBuilder",
    "StructuralGraphBuildResult",
    "build_structural_graph_from_docling",
    "is_structural_graph_enabled",
    "USE_STRUCTURAL_GRAPH",
]
