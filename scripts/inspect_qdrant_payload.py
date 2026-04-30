#!/usr/bin/env python3
"""Diag : inspecter le payload Qdrant complet pour comprendre la structure."""
import sys
sys.path.insert(0, "/app/src")

from qdrant_client.models import FieldCondition, Filter, MatchValue
from knowbase.common.clients.shared_clients import get_qdrant_client, get_sentence_transformer
from knowbase.config.settings import get_settings

settings = get_settings()
qdrant = get_qdrant_client()
embedder = get_sentence_transformer(settings.embeddings_model, cache_folder=str(settings.hf_home))

# Cherche un claim quelconque de 2021/821
vec = embedder.encode("passage: This Regulation establishes a Union regime").tolist()
results = qdrant.search(
    collection_name="knowbase_chunks_v2",
    query_vector=vec,
    limit=3,
    query_filter=Filter(must=[FieldCondition(key="doc_id", match=MatchValue(value="dualuse_reg_2021_821_original_65eef5dc"))]),
    with_payload=True,
)

for r in results:
    print(f"\n=== Score {r.score:.3f} | id={r.id} ===")
    print(f"  Payload keys: {list((r.payload or {}).keys())}")
    for k, v in (r.payload or {}).items():
        s = str(v)[:200]
        print(f"  - {k}: {s}")
