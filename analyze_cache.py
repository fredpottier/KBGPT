"""Analyse du cache d'extraction."""
import json
import sys

cache_path = "/data/extraction_cache/363f5357dfe38242a968415f643eff1edca39866d7e714bcb9ea5606cece5359.v5cache.json"

with open(cache_path) as f:
    d = json.load(f)

ext = d.get("extraction", {})
print(f"Cache version: {d.get('cache_version', 'unknown')}")
print(f"Document ID: {d.get('document_id', 'unknown')}")
print(f"Vision results: {len(ext.get('vision_results', []))}")
print(f"Text pages: {len(ext.get('pages_text', {}))}")

chunks = d.get("chunks", [])
print(f"Chunks in cache: {len(chunks)}")

# Compter les types de chunks
kinds = {}
for c in chunks:
    k = c.get("kind", "unknown")
    kinds[k] = kinds.get(k, 0) + 1
print(f"Chunk kinds: {kinds}")

# Vérifier si des chunks FIGURE_TEXT existent
figure_text_count = sum(1 for c in chunks if c.get("kind") == "FIGURE_TEXT")
print(f"FIGURE_TEXT chunks: {figure_text_count}")
