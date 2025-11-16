#!/usr/bin/env python3
import sys
sys.path.insert(0, '/app')
from knowbase.common.clients.qdrant_client import get_qdrant_client

client = get_qdrant_client()
result = client.scroll(collection_name="knowbase", limit=3, with_payload=True, with_vectors=False)
if result[0]:
    for i, point in enumerate(result[0], 1):
        canon_ids = point.payload.get("canonical_concept_ids", [])
        proto_ids = point.payload.get("proto_concept_ids", [])
        print(f"Chunk {i}:")
        print(f"  proto_concept_ids: {len(proto_ids)} IDs")
        print(f"  canonical_concept_ids: {len(canon_ids)} IDs")
        if canon_ids:
            print(f"  ✅ HAS canonical IDs: {canon_ids[:2]}...")
else:
    print("No chunks found")
