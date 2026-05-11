"""Nettoie les jobs failed historiques (FileNotFound après déplacement par user)."""
import os
import redis
from rq.registry import FailedJobRegistry

url = os.getenv("REDIS_URL")
r = redis.from_url(url)

for qname in ["ingestion", "reprocess", "benchmark"]:
    registry = FailedJobRegistry(qname, connection=r)
    failed_ids = registry.get_job_ids()
    if not failed_ids:
        continue
    print(f"Queue {qname}: {len(failed_ids)} failed jobs to remove")
    for jid in failed_ids:
        try:
            registry.remove(jid, delete_job=True)
            print(f"  ✓ removed: {jid}")
        except Exception as e:
            print(f"  ✗ {jid}: {type(e).__name__}: {e}")
    print(f"  After: {FailedJobRegistry(qname, connection=r).count} failed")
