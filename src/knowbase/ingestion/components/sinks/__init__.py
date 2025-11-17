"""
Sinks pour écriture des données enrichies.

Modules extraits de pptx_pipeline.py pour réutilisabilité.
"""

from .qdrant_writer import ingest_chunks, embed_texts
from .neo4j_writer import write_document_metadata, write_slide_relations

__all__ = [
    # Qdrant
    "ingest_chunks",
    "embed_texts",
    # Neo4j
    "write_document_metadata",
    "write_slide_relations",
]
