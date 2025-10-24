#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Create knowwhere_proto collection in Qdrant."""

import sys
from qdrant_client import QdrantClient
from qdrant_client.models import Distance, VectorParams, HnswConfigDiff, OptimizersConfigDiff

# Fix Windows UTF-8 output
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding='utf-8')

client = QdrantClient(host="localhost", port=6333)

# Check if collection exists
collections = client.get_collections().collections
existing = [c.name for c in collections]

if "knowwhere_proto" in existing:
    print("⚠️  Collection 'knowwhere_proto' already exists")
else:
    # Create collection with same config as concepts_proto
    client.create_collection(
        collection_name="knowwhere_proto",
        vectors_config=VectorParams(
            size=1024,  # multilingual-e5-large
            distance=Distance.COSINE,
        ),
        hnsw_config=HnswConfigDiff(
            m=16,
            ef_construct=100,
            full_scan_threshold=10000
        ),
        optimizers_config=OptimizersConfigDiff(
            deleted_threshold=0.2,
            vacuum_min_vector_number=1000,
            default_segment_number=2,
            indexing_threshold=10000
        )
    )
    print("✅ Collection 'knowwhere_proto' created successfully")

# Verify
info = client.get_collection("knowwhere_proto")
print(f"📊 Collection info:")
print(f"   - Vectors: {info.vectors_count}")
print(f"   - Points: {info.points_count}")
print(f"   - Vector size: {info.config.params.vectors.size}")
print(f"   - Distance: {info.config.params.vectors.distance}")
