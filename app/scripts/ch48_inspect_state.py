import json, os, redis
r = redis.Redis.from_url(os.getenv("REDIS_URL"), decode_responses=True)
for key in ["osmose:benchmark:robustness:state", "osmose:benchmark:t2t5:state", "osmose:benchmark:ragas:state"]:
    v = r.get(key)
    if v:
        try:
            d = json.loads(v)
            print(f"--- {key} ---")
            print(json.dumps(d, indent=2, default=str)[:1500])
        except Exception as exc:
            print(f"{key}: {exc}")
            print(f"raw: {v[:300]}")
