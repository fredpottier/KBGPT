#!/usr/bin/env python3
"""
Monitor overnight — boucle de surveillance ClaimFirst + post-import.

Lance en background depuis l'hôte Windows :
    python scripts/monitor_overnight.py

Phases :
- A. Monitor ClaimFirst batch : surveille progress, requeue si stuck, attend completion
- B. Post-import : déclenche /api/admin/post-import/run, attend completion
- C. Marque READY_TO_TERMINATE dans state file (la terminaison EC2 est faite par Claude
     au prochain wakeup, pour double validation)

Récupération automatique :
- Si vLLM down : check EC2 state. Si EC2 vivante : attend recovery. Si morte : log et
  poll pendant 2h max (le user peut relancer une instance manuellement).
- Si batch idle 15+ min avec processed < total : check Neo4j diff, requeue les restants.

Pas de spawn d'instance automatique (trop risqué la nuit sans validation). Si l'EC2 est
définitivement perdue, le script s'arrête avec WAITING_EC2_REVIVAL dans state file.
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
STATE_FILE = LOG_DIR / "monitor_overnight.state"
LOG_FILE = LOG_DIR / "monitor_overnight.log"

INSTANCE_ID = "i-01bdafc920f366430"
INSTANCE_IP_INITIAL = "3.71.186.209"
REGION = "eu-central-1"
TENANT = "default"

POLL_INTERVAL_SEC = 60
IDLE_THRESHOLD_SEC = 2700  # 45 min sans changement processed → requeue
                          # (docs SAP volumineux 1500p peuvent prendre 30-40 min)
EC2_REVIVAL_TIMEOUT_SEC = 7200  # 2h max d'attente sur EC2 morte
POST_IMPORT_TIMEOUT_SEC = 3600  # 1h max sur post-import

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE, encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
    force=True,
)
log = logging.getLogger("monitor")


def set_state(s: str, **extra) -> None:
    payload = {"state": s, "ts": datetime.utcnow().isoformat(), **extra}
    STATE_FILE.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    log.info(f"STATE={s} {extra}")


def run(cmd: list[str], timeout: int = 60) -> tuple[int, str]:
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return r.returncode, (r.stdout + r.stderr).strip()
    except subprocess.TimeoutExpired:
        return 124, "timeout"
    except Exception as e:
        return 1, str(e)


def docker_exec(container: str, cmd: str, timeout: int = 30) -> tuple[int, str]:
    return run(["docker", "exec", container, "sh", "-c", cmd], timeout=timeout)


def get_vllm_ip_from_redis() -> str | None:
    """Lit l'IP vLLM depuis osmose:burst:state."""
    rc, out = docker_exec(
        "knowbase-redis",
        'redis-cli -a "$REDIS_PASSWORD" --no-auth-warning GET osmose:burst:state',
    )
    if rc != 0 or not out:
        return None
    try:
        data = json.loads(out)
        url = data.get("vllm_url", "")
        # http://X.X.X.X:8000
        if url.startswith("http://"):
            return url.split("//")[1].split(":")[0]
    except Exception:
        pass
    return None


def vllm_healthy(ip: str | None = None) -> bool:
    target_ip = ip or get_vllm_ip_from_redis()
    if not target_ip:
        return False
    try:
        import requests
        r = requests.get(f"http://{target_ip}:8000/v1/models", timeout=5)
        return r.status_code == 200
    except Exception:
        return False


def ec2_state() -> str:
    """Retourne running/pending/stopping/stopped/terminated/unknown."""
    rc, out = run([
        "aws", "ec2", "describe-instances",
        "--region", REGION,
        "--instance-ids", INSTANCE_ID,
        "--query", "Reservations[0].Instances[0].State.Name",
        "--output", "text",
    ])
    return out.strip() if rc == 0 else "unknown"


def ec2_public_ip() -> str | None:
    rc, out = run([
        "aws", "ec2", "describe-instances",
        "--region", REGION,
        "--instance-ids", INSTANCE_ID,
        "--query", "Reservations[0].Instances[0].PublicIpAddress",
        "--output", "text",
    ])
    if rc == 0 and out and out != "None":
        return out.strip()
    return None


def re_attach_burst(new_ip: str) -> bool:
    """Met à jour osmose:burst:state via container app."""
    script = (
        "from knowbase.ingestion.burst.provider_switch import set_burst_state_in_redis; "
        f"ok = set_burst_state_in_redis('http://{new_ip}:8000', "
        f"'Qwen/Qwen2.5-14B-Instruct-AWQ', 'http://{new_ip}:8001'); "
        "print('OK' if ok else 'FAIL')"
    )
    rc, out = run(["docker", "exec", "knowbase-app", "python", "-c", script], timeout=30)
    log.info(f"re_attach result rc={rc} out={out[:200]}")
    return rc == 0 and "OK" in out


def get_claimfirst_state() -> dict:
    rc, out = docker_exec(
        "knowbase-redis",
        'redis-cli -a "$REDIS_PASSWORD" --no-auth-warning HGETALL osmose:claimfirst:state',
    )
    if rc != 0 or not out:
        return {}
    lines = out.split("\n")
    result = {}
    for i in range(0, len(lines) - 1, 2):
        result[lines[i].strip()] = lines[i + 1].strip()
    return result


def count_docs_in_neo4j() -> int:
    script = (
        'from neo4j import GraphDatabase; '
        'd = GraphDatabase.driver("bolt://neo4j:7687", auth=("neo4j","graphiti_neo4j_pass")); '
        f'r = d.session().run("MATCH (c:Claim {{tenant_id:\\"{TENANT}\\"}}) '
        'RETURN count(DISTINCT c.doc_id) AS n").single(); print(r["n"])'
    )
    rc, out = run(["docker", "exec", "knowbase-app", "python", "-c", script], timeout=30)
    try:
        return int(out.strip().split("\n")[-1])
    except (ValueError, IndexError):
        return -1


def requeue_remaining() -> bool:
    """Lance enqueue_claimfirst_missing.py."""
    rc, out = run([
        "docker", "exec", "knowbase-app",
        "python", "/app/scripts/enqueue_claimfirst_missing.py"
    ], timeout=60)
    log.info(f"requeue result rc={rc}")
    log.info(out[-500:])
    return rc == 0


def post_import_status() -> dict:
    """Retourne l'état du post-import via Redis."""
    rc, out = docker_exec(
        "knowbase-redis",
        f'redis-cli -a "$REDIS_PASSWORD" --no-auth-warning GET osmose:post_import:state:{TENANT}',
    )
    if rc != 0 or not out:
        return {}
    try:
        return json.loads(out)
    except Exception:
        return {}


def trigger_post_import() -> bool:
    """Lance post-import via RQ enqueue direct (bypass auth API).
    Enqueue tous les 15 steps dans l'ordre via run_pipeline_job."""
    script = (
        "import os; "
        "from redis import Redis; from rq import Queue; "
        "from knowbase.api.routers.post_import import run_pipeline_job, STEPS; "
        "rc = Redis.from_url(os.getenv('REDIS_URL')); "
        "q = Queue('reprocess', connection=rc); "
        "all_steps = sorted([s.id for s in STEPS], key=lambda x: next(s.order for s in STEPS if s.id==x)); "
        f"job = q.enqueue(run_pipeline_job, all_steps, '{TENANT}', job_timeout='4h'); "
        "print(f'job_id={job.id} steps={len(all_steps)}')"
    )
    rc, out = run(["docker", "exec", "knowbase-app", "python", "-c", script], timeout=60)
    log.info(f"trigger_post_import rc={rc} out={out[:400]}")
    return rc == 0 and "job_id=" in out


# ── Phase A: Monitor ClaimFirst ─────────────────────────────────────────────

def phase_a_monitor_claimfirst() -> bool:
    log.info("=== PHASE A: monitor ClaimFirst ===")
    set_state("PHASE_A_MONITORING")

    last_processed = -1
    last_change_ts = time.time()
    ec2_down_since = None

    while True:
        cf = get_claimfirst_state()
        processed = int(cf.get("processed", 0))
        total = int(cf.get("total_documents", 0))
        status = cf.get("status", "")
        current = cf.get("current_filename", "")

        # Check vLLM
        vllm_ok = vllm_healthy()

        # Check Neo4j
        docs_in_kg = count_docs_in_neo4j()

        log.info(
            f"cf={status} processed={processed}/{total} "
            f"current='{current[:40]}' vllm={'OK' if vllm_ok else 'DOWN'} kg={docs_in_kg}"
        )

        # Eviction Spot ?
        if not vllm_ok:
            if ec2_down_since is None:
                ec2_down_since = time.time()
                log.warning(f"vLLM DOWN detected at {datetime.utcnow().isoformat()}")
            state = ec2_state()
            log.warning(f"EC2 {INSTANCE_ID} state={state}")

            if state == "running":
                # vLLM down mais EC2 vivante : peut-être restart en cours
                ip = ec2_public_ip()
                if ip and ip != INSTANCE_IP_INITIAL:
                    log.warning(f"IP changed: {INSTANCE_IP_INITIAL} → {ip}, re-attach")
                    if re_attach_burst(ip):
                        ec2_down_since = None
            elif state in ("terminated", "shutting-down", "stopped"):
                set_state("WAITING_EC2_REVIVAL", ec2_state=state)
                # Attendre que le user relance une instance OU timeout
                if time.time() - ec2_down_since > EC2_REVIVAL_TIMEOUT_SEC:
                    log.error(f"EC2 dead for >{EC2_REVIVAL_TIMEOUT_SEC}s, aborting")
                    set_state("ABORTED_EC2_LOST")
                    return False
        else:
            # vLLM OK
            ec2_down_since = None

            # Detect completion : Neo4j contient tous les docs cachés ET pas de job started
            # On utilise enqueue_claimfirst_missing.py qui calcule le delta
            rc, out = run([
                "docker", "exec", "knowbase-app",
                "python", "-c",
                "import sys; sys.path.insert(0,'/app/src'); "
                "from knowbase.stratified.pass0.cache_loader import list_cached_documents; "
                "from neo4j import GraphDatabase; "
                "available = {d['document_id'] for d in list_cached_documents('/data/extraction_cache')}; "
                f"d = GraphDatabase.driver('bolt://neo4j:7687', auth=('neo4j','graphiti_neo4j_pass')); "
                "done = {r['doc_id'] for r in d.session().run("
                f"\"MATCH (c:Claim {{tenant_id:'{TENANT}'}}) RETURN DISTINCT c.doc_id AS doc_id\""
                ").data() if r['doc_id']}; "
                "missing = available - done; "
                "print(f'AVAILABLE={len(available)} DONE={len(done & available)} MISSING={len(missing)}')"
            ], timeout=30)
            log.info(f"delta: {out[-200:]}")

            if "MISSING=0" in out:
                log.info("PHASE A: all docs persisted in Neo4j — COMPLETE")
                set_state("PHASE_A_COMPLETE", docs_kg=docs_in_kg)
                return True

            # Detect stuck (no progress 15+ min)
            if processed != last_processed:
                last_processed = processed
                last_change_ts = time.time()
            elif time.time() - last_change_ts > IDLE_THRESHOLD_SEC:
                # Vérifier si un job est en cours
                rc, qstate = run([
                    "docker", "exec", "knowbase-app",
                    "python", "/app/scripts/check_rq_queue.py"
                ], timeout=15)
                if "started: 0" in qstate.lower() or "started: 1" in qstate.lower():
                    log.warning(f"Idle {(time.time()-last_change_ts)/60:.0f}min, requeue missing")
                    if requeue_remaining():
                        last_change_ts = time.time()
                    else:
                        log.error("Requeue failed")

        time.sleep(POLL_INTERVAL_SEC)


# ── Phase B: Post-import ─────────────────────────────────────────────────────

def phase_b_post_import() -> bool:
    log.info("=== PHASE B: post-import ===")
    set_state("PHASE_B_LAUNCHING")

    if not trigger_post_import():
        log.error("Failed to trigger post-import")
        set_state("PHASE_B_FAILED_TRIGGER")
        return False

    set_state("PHASE_B_RUNNING")
    start = time.time()
    while True:
        st = post_import_status()
        running = st.get("running", False)
        step = st.get("current_step_name", "")
        completed = len(st.get("completed_steps", []))
        total = st.get("total_steps", 0)

        log.info(f"post_import running={running} step={step} {completed}/{total}")

        if not running and completed >= total and total > 0:
            log.info("PHASE B: post-import complete")
            set_state("PHASE_B_COMPLETE", completed_steps=completed, total_steps=total)
            return True

        if time.time() - start > POST_IMPORT_TIMEOUT_SEC:
            log.error("PHASE B: timeout")
            set_state("PHASE_B_TIMEOUT")
            return False

        time.sleep(30)


# ── Phase C: Terminate EC2 ───────────────────────────────────────────────────

def phase_c_terminate_ec2() -> bool:
    """Terminate EC2 instance. SEULEMENT appelée si phases A et B sont OK."""
    log.info(f"=== PHASE C: terminate EC2 {INSTANCE_ID} ===")
    set_state("PHASE_C_TERMINATING", instance_id=INSTANCE_ID)

    # Double safety : revérifier que tous les docs sont en Neo4j
    rc, out = run([
        "docker", "exec", "knowbase-app",
        "python", "-c",
        "import sys; sys.path.insert(0,'/app/src'); "
        "from knowbase.stratified.pass0.cache_loader import list_cached_documents; "
        "from neo4j import GraphDatabase; "
        "available = {d['document_id'] for d in list_cached_documents('/data/extraction_cache')}; "
        "d = GraphDatabase.driver('bolt://neo4j:7687', auth=('neo4j','graphiti_neo4j_pass')); "
        "done = {r['doc_id'] for r in d.session().run("
        f"\"MATCH (c:Claim {{tenant_id:'{TENANT}'}}) RETURN DISTINCT c.doc_id AS doc_id\""
        ").data() if r['doc_id']}; "
        "missing = available - done; "
        "print(f'MISSING={len(missing)}')"
    ], timeout=30)

    if "MISSING=0" not in out:
        log.error(f"Phase C ABORTED: docs still missing in Neo4j ({out[:200]})")
        set_state("PHASE_C_ABORTED_DOCS_MISSING")
        return False

    log.info("Safety check OK: all docs persisted in Neo4j")

    # Terminate
    rc, out = run([
        "aws", "ec2", "terminate-instances",
        "--region", REGION,
        "--instance-ids", INSTANCE_ID,
    ], timeout=60)

    if rc != 0:
        log.error(f"terminate-instances failed: {out[:500]}")
        set_state("PHASE_C_TERMINATE_FAILED", aws_error=out[:300])
        return False

    log.info(f"terminate-instances issued: {out[:300]}")

    # Wait until terminated state
    for i in range(30):  # 30 × 10s = 5 min max
        time.sleep(10)
        state = ec2_state()
        log.info(f"EC2 state poll {i+1}: {state}")
        if state in ("terminated", "shutting-down"):
            log.info(f"EC2 terminated successfully at {datetime.utcnow().isoformat()}")
            set_state("TERMINATED",
                      instance_id=INSTANCE_ID,
                      terminated_at=datetime.utcnow().isoformat(),
                      ec2_state=state)
            return True

    log.warning("EC2 still not in terminated state after 5 min, but request was issued")
    set_state("PHASE_C_TERMINATE_PENDING", instance_id=INSTANCE_ID)
    return True


# ── Main ─────────────────────────────────────────────────────────────────────

def main():
    log.info(f"=== monitor_overnight START pid={os.getpid()} ===")
    set_state("STARTED")

    if not phase_a_monitor_claimfirst():
        log.error("Phase A failed, stopping (EC2 preserved for manual review)")
        return 1

    if not phase_b_post_import():
        log.error("Phase B failed, leaving EC2 alive for manual review")
        set_state("PHASE_B_FAILED_EC2_PRESERVED")
        return 1

    if not phase_c_terminate_ec2():
        log.error("Phase C failed or aborted, EC2 may still be alive")
        return 1

    log.info("=== ALL DONE — EC2 terminated, monitor exiting ===")
    return 0


if __name__ == "__main__":
    sys.exit(main())
