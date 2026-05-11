"""Inspect RQ queue state."""
import os
import redis
from rq import Queue
from rq.registry import FailedJobRegistry, StartedJobRegistry, FinishedJobRegistry

url = os.getenv("REDIS_URL")
r = redis.from_url(url)

for qname in ["ingestion", "reprocess", "benchmark"]:
    q = Queue(qname, connection=r)
    print(f"\n=== Queue: {qname} ===")
    print(f"  pending: {q.count}")
    print(f"  failed: {FailedJobRegistry(qname, connection=r).count}")
    print(f"  started: {StartedJobRegistry(qname, connection=r).count}")
    print(f"  finished: {FinishedJobRegistry(qname, connection=r).count}")
    # First few job ids
    job_ids = q.get_job_ids(0, 5)
    if job_ids:
        print(f"  next jobs: {job_ids}")
    failed_ids = FailedJobRegistry(qname, connection=r).get_job_ids()[:5]
    if failed_ids:
        print(f"  failed sample: {failed_ids}")
