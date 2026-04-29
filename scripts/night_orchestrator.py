#!/usr/bin/env python3
"""
Night orchestrator — Python version that survives shell teardowns.

Runs INSIDE the knowbase-app container via `docker exec -d`.
- Phase A: wait for ClaimFirst batch to finish
- Phase B: enqueue + wait post-import (15 steps)
- Phase C: create AMI v10 (via aws cli on host through... wait this is in container)

Actually since AWS CLI lives on the host but Redis/Neo4j live in containers,
this script lives ON THE HOST and is launched via Python's Popen with
DETACHED_PROCESS flag (Windows) so it survives the launcher shell.

Run:
    python scripts/night_orchestrator.py
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

LOG_DIR = Path(r"C:\Projects\SAP_KB\logs")
LOG_DIR.mkdir(parents=True, exist_ok=True)
STATE_FILE = LOG_DIR / "orchestrator_night.state"
LOG_FILE = LOG_DIR / "orchestrator_night.log"
AMI_FILE = LOG_DIR / "orchestrator_ami_id.txt"

INSTANCE_ID = "i-0a9629cd55ec141ea"
REGION = "eu-central-1"
NEW_AMI_NAME = "osmose-burst-v10-qwen25-14b-awq"
EXPECTED_DOC_COUNT = 17

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE, encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
    force=True,
)
log = logging.getLogger("orchestrator")


def set_state(s: str) -> None:
    STATE_FILE.write_text(s, encoding="utf-8")


def run(cmd: list[str], timeout: int = 60, capture: bool = True) -> tuple[int, str]:
    """Run subprocess, return (rc, stdout_or_combined)."""
    try:
        r = subprocess.run(
            cmd,
            capture_output=capture,
            text=True,
            timeout=timeout,
            shell=False,
        )
        out = (r.stdout or "") + (r.stderr or "")
        return r.returncode, out.strip()
    except subprocess.TimeoutExpired:
        return -1, f"TIMEOUT after {timeout}s"
    except Exception as e:
        return -2, f"EXCEPTION: {e}"


# ============================================================================
# Phase A
# ============================================================================
def phase_a_wait_batch() -> bool:
    log.info("PHASE A: Waiting for ClaimFirst batch completion")
    set_state("phase_a_running")

    max_wait = 14 * 3600
    start = time.time()
    stuck = 0

    while True:
        if time.time() - start > max_wait:
            log.error("PHASE A: timeout")
            set_state("phase_a_timeout")
            return False

        rc, q = run(["docker", "exec", "knowbase-redis", "redis-cli", "LLEN", "rq:queue:reprocess"], 30)
        queue = q.strip() if rc == 0 else "?"

        rc, started_out = run([
            "docker", "exec", "knowbase-worker", "python3", "-c",
            "from rq.registry import StartedJobRegistry; from redis import Redis; "
            "r = Redis(host='knowbase-redis', port=6379); "
            "print(len(StartedJobRegistry('reprocess', connection=r).get_job_ids()))"
        ], 30)
        started = started_out.split("\n")[-1].strip() if rc == 0 else "?"

        rc, n_out = run([
            "docker", "exec", "knowbase-neo4j", "cypher-shell",
            "-u", "neo4j", "-p", "graphiti_neo4j_pass", "--format", "plain",
            "MATCH (c:Claim) WITH DISTINCT c.doc_id AS d RETURN count(d) AS n",
        ], 30)
        docs_with_claims = 0
        if rc == 0:
            for line in n_out.split("\n"):
                line = line.strip()
                if line.isdigit():
                    docs_with_claims = int(line)
                    break

        log.info(f"queue={queue} started={started} docs_with_claims={docs_with_claims}/{EXPECTED_DOC_COUNT}")

        # Idle check
        try:
            queue_int = int(queue)
            started_int = int(started)
        except ValueError:
            queue_int = -1
            started_int = -1

        # Stale registry was cleared. Real idle = queue=0 AND started=0.
        if queue_int == 0 and started_int == 0:
            if docs_with_claims >= EXPECTED_DOC_COUNT:
                log.info("PHASE A: BATCH COMPLETE")
                set_state("phase_a_done")
                return True
            stuck += 1
            log.warning(f"Idle but only {docs_with_claims}/{EXPECTED_DOC_COUNT} docs — stuck_iter={stuck}")
            if stuck >= 6:
                log.warning(f"PHASE A: idle 30min with partial — proceeding ({docs_with_claims}/{EXPECTED_DOC_COUNT})")
                set_state(f"phase_a_done_partial:{docs_with_claims}")
                return True
        else:
            stuck = 0

        time.sleep(300)


# ============================================================================
# Phase B
# ============================================================================
def phase_b_post_import() -> bool:
    log.info("PHASE B: Enqueueing post-import (15 steps)")
    set_state("phase_b_running")

    rc, out = run([
        "docker", "exec", "knowbase-worker", "python3", "-c", """
from redis import Redis
from rq import Queue
from knowbase.api.routers.post_import import run_pipeline_job, STEPS_BY_ID
r = Redis(host='knowbase-redis', port=6379)
q = Queue('reprocess', connection=r)
steps = ['canonicalize','facets','facet_consolidate','purge_orphan_facets','cluster_cross_doc','chains_cross_doc','detect_contradictions','domain_pack_reprocess','claim_embeddings','claim_chunk_bridge','archive_isolated','garbage_collection','c4_relations','c6_pivots','build_perspectives']
ordered = sorted(steps, key=lambda s: STEPS_BY_ID[s].order)
job = q.enqueue(run_pipeline_job, ordered, 'default', job_timeout='8h')
print(job.id)
"""
    ], 60)

    job_id = ""
    if rc == 0:
        for line in out.split("\n"):
            if line.startswith("claimfirst_") or line.startswith("rq:") or len(line) > 8 and "-" not in line:
                # Just take the last non-empty line
                pass
        job_id = out.split("\n")[-1].strip()

    if not job_id or " " in job_id:
        log.error(f"PHASE B: failed to enqueue: {out}")
        set_state("phase_b_failed_enqueue")
        return False

    log.info(f"PHASE B: enqueued job_id={job_id}")
    max_wait = 9 * 3600
    start = time.time()

    while True:
        if time.time() - start > max_wait:
            log.error("PHASE B: timeout")
            set_state("phase_b_timeout")
            return False

        rc, out = run([
            "docker", "exec", "knowbase-worker", "python3", "-c",
            f"from rq.job import Job; from redis import Redis; "
            f"r = Redis(host='knowbase-redis', port=6379); "
            f"j = Job.fetch('{job_id}', connection=r); "
            f"print(j.get_status())"
        ], 30)
        status = out.split("\n")[-1].strip() if rc == 0 else "?"
        log.info(f"PHASE B: job_id={job_id} status={status}")

        if "FINISHED" in status:
            set_state("phase_b_done")
            return True
        if "FAILED" in status:
            log.warning("PHASE B: job FAILED, continuing to AMI anyway")
            set_state("phase_b_failed_job")
            return True
        time.sleep(300)


# ============================================================================
# Phase C: AMI
# ============================================================================
def phase_c_create_ami() -> bool:
    log.info(f"PHASE C: Creating AMI from {INSTANCE_ID}")
    set_state("phase_c_running")

    timestamp = datetime.utcnow().strftime("%Y%m%d-%H%M")
    ami_name = f"{NEW_AMI_NAME}-{timestamp}"

    rc, out = run([
        "aws", "ec2", "create-image",
        "--region", REGION,
        "--instance-id", INSTANCE_ID,
        "--name", ami_name,
        "--description", f"OSMOSIS burst v10 — Qwen2.5-14B-Instruct-AWQ on vLLM 0.9.2 (created {datetime.utcnow().isoformat()})",
        "--no-reboot",
        "--query", "ImageId",
        "--output", "text",
    ], 120)

    ami_id = out.strip().split("\n")[-1].strip()
    if not ami_id.startswith("ami-"):
        log.error(f"PHASE C: bad output: {out}")
        set_state("phase_c_failed")
        return False

    log.info(f"PHASE C: AMI created: {ami_id} name={ami_name}")
    AMI_FILE.write_text(ami_id, encoding="utf-8")
    set_state(f"phase_c_done:{ami_id}")
    return True


# ============================================================================
# Phase D: Wait AMI available
# ============================================================================
def phase_d_wait_ami() -> bool:
    log.info("PHASE D: Waiting for AMI available")
    ami_id = AMI_FILE.read_text(encoding="utf-8").strip() if AMI_FILE.exists() else ""
    if not ami_id.startswith("ami-"):
        log.error(f"PHASE D: no AMI ID")
        set_state("phase_d_failed_noami")
        return False

    set_state(f"phase_d_running:{ami_id}")
    max_wait = 45 * 60
    start = time.time()

    while True:
        if time.time() - start > max_wait:
            log.error("PHASE D: timeout")
            set_state("phase_d_timeout")
            return False

        rc, out = run([
            "aws", "ec2", "describe-images",
            "--region", REGION, "--image-ids", ami_id,
            "--query", "Images[].State", "--output", "text",
        ], 60)
        state = out.strip().split("\n")[-1].strip() if rc == 0 else "?"
        log.info(f"PHASE D: AMI {ami_id} state={state}")

        if state == "available":
            set_state(f"phase_d_done:{ami_id}")
            return True
        if state in ("failed", "invalid", "deregistered", "error"):
            log.error(f"PHASE D: bad state={state}")
            set_state(f"phase_d_bad_state:{state}")
            return False
        time.sleep(60)


# ============================================================================
# Phase E: Cleanup
# ============================================================================
def phase_e_cleanup() -> bool:
    log.info("PHASE E: AWS cleanup (ALL regions)")
    set_state("phase_e_running")

    new_ami = AMI_FILE.read_text(encoding="utf-8").strip() if AMI_FILE.exists() else ""

    # 1. Terminate EC2
    log.info(f"PHASE E1: terminating {INSTANCE_ID}")
    rc, out = run([
        "aws", "ec2", "terminate-instances",
        "--region", REGION, "--instance-ids", INSTANCE_ID,
        "--query", "TerminatingInstances[].[InstanceId,CurrentState.Name]",
        "--output", "text",
    ], 60)
    log.info(f"  → {out}")

    # 2. Get all regions
    rc, regions_out = run([
        "aws", "ec2", "describe-regions",
        "--query", "Regions[].RegionName", "--output", "text",
    ], 30)
    regions = regions_out.replace("\t", " ").split() if rc == 0 else []

    # 3. Scan all regions for owned AMIs
    for region in regions:
        log.info(f"PHASE E2: scanning {region}")
        rc, out = run([
            "aws", "ec2", "describe-images",
            "--owners", "self", "--region", region,
            "--query", "Images[].[ImageId,Name]",
            "--output", "json",
        ], 60)
        if rc != 0 or not out.strip():
            continue
        try:
            amis = json.loads(out)
        except Exception as e:
            log.warning(f"  parse fail in {region}: {e}")
            continue

        for ami in amis:
            ami_id, ami_name = ami[0], ami[1]
            if ami_id == new_ami:
                log.info(f"  SKIP new v10 {ami_id} in {region}")
                continue
            log.info(f"  deregister {ami_id} ({ami_name}) in {region}")

            # Get snapshots
            rc2, snaps_out = run([
                "aws", "ec2", "describe-images",
                "--region", region, "--image-ids", ami_id,
                "--query", "Images[].BlockDeviceMappings[].Ebs.SnapshotId",
                "--output", "text",
            ], 30)
            snaps = snaps_out.replace("\t", " ").split() if rc2 == 0 else []

            run([
                "aws", "ec2", "deregister-image",
                "--region", region, "--image-id", ami_id,
            ], 30)

            for snap in snaps:
                if snap.startswith("snap-"):
                    log.info(f"    delete snap {snap} in {region}")
                    run([
                        "aws", "ec2", "delete-snapshot",
                        "--region", region, "--snapshot-id", snap,
                    ], 30)

    log.info("PHASE E: cleanup done")
    set_state("phase_e_done")
    return True


def main():
    log.info("=== ORCHESTRATOR START (Python) ===")
    set_state("starting")
    if not phase_a_wait_batch():
        log.error("PHASE A failed — STOP"); set_state("stopped_at_a"); sys.exit(1)
    if not phase_b_post_import():
        log.error("PHASE B failed — STOP"); set_state("stopped_at_b"); sys.exit(1)
    if not phase_c_create_ami():
        log.error("PHASE C failed — STOP"); set_state("stopped_at_c"); sys.exit(1)
    if not phase_d_wait_ami():
        log.error("PHASE D failed — STOP"); set_state("stopped_at_d"); sys.exit(1)
    if not phase_e_cleanup():
        log.error("PHASE E failed"); set_state("stopped_at_e"); sys.exit(1)

    log.info("=== ORCHESTRATOR ALL DONE ===")
    set_state("all_done")


if __name__ == "__main__":
    main()
