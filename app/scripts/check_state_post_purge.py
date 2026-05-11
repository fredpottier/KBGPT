"""État post-purge : Qdrant + Neo4j + caches."""
import sys, os
sys.path.insert(0, "/app/src")
from knowbase.common.clients import get_qdrant_client
from neo4j import GraphDatabase

q = get_qdrant_client()
print("=== Qdrant collections ===")
for c in q.get_collections().collections:
    info = q.get_collection(c.name)
    print(f"  {c.name}: {info.points_count} points")

print("\n=== Neo4j (tenant=default) ===")
d = GraphDatabase.driver("bolt://neo4j:7687", auth=("neo4j", "graphiti_neo4j_pass"))
with d.session() as s:
    for label in ["Claim", "Document", "DocumentContext", "DocumentVersion", "SectionContext", "DocItem", "Subject", "Anchor"]:
        try:
            r = s.run(f"MATCH (n:{label} {{tenant_id:'default'}}) RETURN count(n) AS n").single()
            print(f"  {label}: {r['n']}")
        except Exception as e:
            print(f"  {label}: error {e}")

print("\n=== Caches existants (data/extraction_cache/) ===")
import glob, json
caches = sorted(glob.glob("/app/data/extraction_cache/*.v5cache.json"))
print(f"Total: {len(caches)} caches")
for f in caches[:30]:
    try:
        with open(f, encoding="utf-8") as fh:
            d = json.load(fh)
        doc_id = d.get("document_id", "?")
        src = d.get("extraction", {}).get("source_path", "?")
        print(f"  {doc_id[:60]:<60} from {os.path.basename(src)}")
    except Exception as e:
        print(f"  {os.path.basename(f)[:50]} ERR: {type(e).__name__}")

print("\n=== Caches backup (burst/SAP/extraction_cache/) ===")
backups = sorted(glob.glob("/app/data/burst/SAP/extraction_cache/*.v5cache.json"))
print(f"Total: {len(backups)} backup caches")
for f in backups[:30]:
    try:
        with open(f, encoding="utf-8") as fh:
            d = json.load(fh)
        doc_id = d.get("document_id", "?")
        src = d.get("extraction", {}).get("source_path", "?")
        print(f"  {doc_id[:60]:<60} from {os.path.basename(src)}")
    except Exception as e:
        print(f"  {os.path.basename(f)[:50]} ERR: {type(e).__name__}")
