"""
OSMOSE Retrieval Layer — Package principal.

Modules:
- rechunker: Re-chunking des TypeAwareChunks pour embeddings vectoriels
- qdrant_layer_r: Gestion collection Qdrant knowbase_chunks_v2 (Layer R)
"""

from knowbase.retrieval.rechunker import SubChunk, rechunk_for_retrieval
from knowbase.retrieval.qdrant_layer_r import (
    ensure_layer_r_collection,
    upsert_layer_r,
    delete_doc_from_layer_r,
    search_layer_r,
    COLLECTION_NAME,
)

__all__ = [
    "SubChunk",
    "rechunk_for_retrieval",
    "ensure_layer_r_collection",
    "upsert_layer_r",
    "delete_doc_from_layer_r",
    "search_layer_r",
    "COLLECTION_NAME",
]
