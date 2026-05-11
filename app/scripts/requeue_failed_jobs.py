"""Re-enqueue les jobs failed après fix Redis auth."""
import os
import redis
from rq.registry import FailedJobRegistry
from rq import Queue

url = os.getenv("REDIS_URL")
r = redis.from_url(url)

for qname in ["ingestion"]:
    registry = FailedJobRegistry(qname, connection=r)
    failed_ids = registry.get_job_ids()
    print(f"Queue {qname}: {len(failed_ids)} failed jobs")
    for jid in failed_ids:
        try:
            registry.requeue(jid)
            print(f"  ✓ requeued: {jid}")
        except Exception as e:
            print(f"  ✗ {jid}: {type(e).__name__}: {e}")

# Confirm
q = Queue("ingestion", connection=r)
print(f"\nQueue ingestion now: {q.count} pending, {FailedJobRegistry('ingestion', connection=r).count} failed")
