"""Analyse du cache d'extraction."""
import json

cache_path = "/data/extraction_cache/363f5357dfe38242a968415f643eff1edca39866d7e714bcb9ea5606cece5359.v5cache.json"

with open(cache_path) as f:
    d = json.load(f)

print("=== TOP LEVEL KEYS ===")
print(list(d.keys()))

ext = d.get("extraction", {})
print("\n=== EXTRACTION KEYS ===")
print(list(ext.keys()))

print(f"\n=== COUNTS ===")
print(f"Vision results: {len(ext.get('vision_results', []))}")
print(f"Chunks (top level): {len(d.get('chunks', []))}")
print(f"Doc items (top level): {len(d.get('doc_items', []))}")

# Structural data
structural = d.get("structural", {})
print(f"\n=== STRUCTURAL ===")
print(f"Keys: {list(structural.keys())}")
print(f"Chunks: {len(structural.get('chunks', []))}")
print(f"Doc items: {len(structural.get('doc_items', []))}")
print(f"Sections: {len(structural.get('sections', []))}")

# Sample chunk
chunks = structural.get("chunks", [])
if chunks:
    print(f"\n=== SAMPLE CHUNK ===")
    print(f"Keys: {list(chunks[0].keys())}")
    print(f"Kind: {chunks[0].get('kind')}")
