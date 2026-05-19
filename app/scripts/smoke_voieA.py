"""Smoke test Voie A — vérifie multi-formulation + templates injectés."""
import json
import sys
import time
import uuid

import requests

URL = "http://localhost:8000"
tenant = "smoke-tenant-voieA"
question = "What is the recommended way to monitor WWI servers in SAP S/4HANA?"
shape = "factual"
idemp = f"smoke-voieA-{uuid.uuid4().hex[:8]}"

r = requests.post(
    f"{URL}/api/runtime_v5/answer",
    headers={
        "X-Tenant-ID": tenant,
        "X-Idempotency-Key": idemp,
        "Content-Type": "application/json",
    },
    json={"question": question, "answer_shape_hint": shape},
    timeout=60,
)
print(f"submit: {r.status_code}")
if r.status_code != 202:
    print(r.text[:500])
    sys.exit(1)
rid = r.json().get("request_id")
print(f"request_id: {rid}")

deadline = time.time() + 300
last_status = None
while time.time() < deadline:
    g = requests.get(
        f"{URL}/api/runtime_v5/answer/{rid}",
        headers={"X-Tenant-ID": tenant},
        timeout=30,
    )
    body = g.json()
    st = body.get("status")
    if st != last_status:
        print(f"  status={st}")
        last_status = st
    if st in ("completed", "failed", "cancelled"):
        break
    time.sleep(5)

print()
print("=" * 60)
print(f"status     : {body.get('status')}")
print(f"stop_reason: {body.get('stop_reason')}")
print(f"latency_ms : {body.get('latency_ms')}")
print(f"iterations : {body.get('iterations')}")
print()
ans = body.get("answer", "")
print(f"answer ({len(ans)} chars):")
print(ans[:2500])
