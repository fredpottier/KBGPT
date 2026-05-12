"""Enqueue ClaimFirst sur les docs présents en cache mais absents de Neo4j."""
import os
import sys

sys.path.insert(0, "/app/src")

from neo4j import GraphDatabase

TENANT = "default"

# 1. Liste des doc_ids disponibles dans les caches
from knowbase.stratified.pass0.cache_loader import list_cached_documents
available = list_cached_documents("/data/extraction_cache")
print(f"=== Caches disponibles ===")
print(f"  Total: {len(available)}")
available_ids = [d["document_id"] for d in available]

# 2. Liste des doc_ids déjà persistés dans Neo4j (au moins 1 claim)
driver = GraphDatabase.driver(
    "bolt://neo4j:7687",
    auth=("neo4j", "graphiti_neo4j_pass"),
)
with driver.session() as s:
    result = s.run(
        "MATCH (c:Claim {tenant_id:$tid}) RETURN DISTINCT c.doc_id AS doc_id",
        tid=TENANT,
    )
    done_ids = {row["doc_id"] for row in result if row["doc_id"]}

print(f"\n=== Neo4j ===")
print(f"  Docs avec claims persistés: {len(done_ids)}")

# 3. Diff : caches dispo mais pas dans Neo4j
remaining = [d for d in available_ids if d not in done_ids]
print(f"\n=== Diff ===")
print(f"  Caches dispo: {len(available_ids)}")
print(f"  Déjà persistés: {len(available_ids) - len(remaining)}")
print(f"  Restants à traiter: {len(remaining)}")

if not remaining:
    print("\n[INFO] Tous les caches sont déjà persistés.")
    sys.exit(0)

print(f"\nÉchantillon docs restants (5 premiers):")
for d in remaining[:5]:
    print(f"  - {d}")
if len(remaining) > 5:
    print(f"  ... +{len(remaining)-5} autres")

# 4. Cleanup state stale du job zombie
import redis
r = redis.from_url(os.getenv("REDIS_URL"))
deleted = r.delete("osmose:claimfirst:state")
print(f"\n=== Cleanup ===")
print(f"  osmose:claimfirst:state DEL: {deleted}")

# 5. Cleanup started registry pour le job zombie (si présent)
from rq.registry import StartedJobRegistry, FailedJobRegistry
for qname in ["reprocess", "ingestion"]:
    reg = StartedJobRegistry(qname, connection=r)
    for jid in reg.get_job_ids():
        if jid.startswith("claimfirst_"):
            try:
                reg.remove(jid, delete_job=True)
                print(f"  Started job {jid} removed from registry ({qname})")
            except Exception as e:
                print(f"  Failed to remove {jid}: {e}")

# 6. Enqueue
print("\n=== Enqueue ===")
from knowbase.ingestion.queue.dispatcher import enqueue_claimfirst_process

new_job = enqueue_claimfirst_process(doc_ids=remaining, tenant_id=TENANT)
print(f"  ✓ New job enqueued: {new_job.id}")
print(f"  Queue: {new_job.origin}")
print(f"  Docs: {len(remaining)}")

print(f"\n[OK] Pipeline reparti avec {len(remaining)} docs (async fix appliqué).")
