import json, os, redis
from pathlib import Path

r = redis.Redis.from_url(os.getenv("REDIS_URL"), decode_responses=True)
v = r.get("osmose:benchmark:t2t5:state")
print(f"t2t5 state: {v}")

base = Path("/app/data/benchmark/results")
t2t5_files = sorted([p for p in base.glob("t2t5_run_*.json")], key=lambda p: p.stat().st_mtime, reverse=True)
print(f"\nLatest t2t5 files:")
for p in t2t5_files[:5]:
    print(f"  {p.name}  ({p.stat().st_mtime})")
