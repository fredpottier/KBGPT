"""Reprend le ClaimFirst sur les docs non encore persistés du batch failed."""
import os
import sys

sys.path.insert(0, "/app/src")

import redis
from rq import Queue
from rq.job import Job
from rq.registry import FailedJobRegistry
from neo4j import GraphDatabase

FAILED_JOB_ID = "claimfirst_009edb49"
TENANT = "default"

r = redis.from_url(os.getenv("REDIS_URL"))

# 1. Lire les doc_ids du job failed
registry = FailedJobRegistry("reprocess", connection=r)
failed_ids = registry.get_job_ids()
if FAILED_JOB_ID not in failed_ids:
    print(f"[ERR] Job {FAILED_JOB_ID} introuvable dans reprocess/failed")
    print(f"  Failed IDs disponibles: {failed_ids}")
    sys.exit(1)

job = Job.fetch(FAILED_JOB_ID, connection=r)

print(f"=== Job {FAILED_JOB_ID} ===")
print(f"  func: {job.func_name}")
print(f"  args: {len(job.args)} positional")
if job.args:
    initial_doc_ids = job.args[0]
    print(f"  doc_ids count: {len(initial_doc_ids)}")
else:
    initial_doc_ids = job.kwargs.get("doc_ids", [])
    print(f"  doc_ids count (kwargs): {len(initial_doc_ids)}")

print(f"  kwargs keys: {list(job.kwargs.keys())}")

# 2. Doc_ids déjà persistés dans Neo4j
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

# 3. Diff
remaining = [d for d in initial_doc_ids if d not in done_ids]
done_in_batch = [d for d in initial_doc_ids if d in done_ids]

print(f"\n=== Diff ===")
print(f"  Batch initial: {len(initial_doc_ids)}")
print(f"  Déjà traités (présents Neo4j): {len(done_in_batch)}")
print(f"  Restants à traiter: {len(remaining)}")

if not remaining:
    print("\n[INFO] Rien à faire, tous les docs du batch sont déjà persistés.")
    sys.exit(0)

print(f"\nÉchantillon docs restants (5 premiers):")
for d in remaining[:5]:
    print(f"  - {d}")
if len(remaining) > 5:
    print(f"  ... +{len(remaining)-5} autres")

# 4. Enqueue
print("\n=== Enqueue nouveau batch ===")
from knowbase.ingestion.queue.dispatcher import enqueue_claimfirst_process

new_job = enqueue_claimfirst_process(doc_ids=remaining, tenant_id=TENANT)
print(f"  ✓ New job enqueued: {new_job.id}")
print(f"  Queue: {new_job.origin}")
print(f"  Status: {new_job.get_status()}")

# 5. Cleanup state stale + failed registry
print("\n=== Cleanup ===")
deleted = r.delete("osmose:claimfirst:state")
print(f"  osmose:claimfirst:state DEL: {deleted}")

registry.remove(FAILED_JOB_ID, delete_job=True)
print(f"  Failed job {FAILED_JOB_ID} removed from registry")

print(f"\n[OK] Pipeline reparti avec {len(remaining)} docs.")
