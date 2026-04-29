#!/bin/bash
# Night orchestrator — autonomous batch + post-import + AMI + AWS cleanup
#
# Phase A: wait for ClaimFirst batch (queue=0 + all docs persisted)
# Phase B: run all 13 post-import steps
# Phase C: create AMI v10 from i-0a9629cd55ec141ea
# Phase D: wait for AMI available
# Phase E: terminate EC2 + deregister old AMIs (v7/v8/v9)

set -u  # err on undefined var ; do NOT set -e (we handle errors per phase)
LOG=/c/Projects/SAP_KB/logs/orchestrator_night.log
STATE=/c/Projects/SAP_KB/logs/orchestrator_night.state
mkdir -p /c/Projects/SAP_KB/logs

INSTANCE_ID="i-0a9629cd55ec141ea"
REGION="eu-central-1"
NEW_AMI_NAME="osmose-burst-v10-qwen25-14b-awq"
OLD_AMIS_EUC="ami-099cbd44d5be7612b ami-0a52b60280f390e94 ami-05ec81177dc825d56"
OLD_AMIS_EUW3="ami-0e1d45537a965962a"

EXPECTED_DOC_COUNT=17  # Total docs in cache (was 10 orphans + 7 historical)

log() {
  local msg="$(date -u +'%Y-%m-%d %H:%M:%S') [$1] ${@:2}"
  echo "$msg" | tee -a "$LOG"
}

set_state() {
  echo "$1" > "$STATE"
}

# ============================================================================
# Phase A: ClaimFirst batch completion
# ============================================================================
phase_a_wait_batch() {
  log INFO "PHASE A: Waiting for ClaimFirst batch completion"
  set_state "phase_a_running"

  local max_wait=$((14 * 3600))  # 14h max
  local start_ts=$(date +%s)
  local stuck_iterations=0
  local prev_queue=-1
  local prev_active=""

  while true; do
    local elapsed=$(( $(date +%s) - start_ts ))
    if [ "$elapsed" -gt "$max_wait" ]; then
      log ERROR "PHASE A: timeout after ${max_wait}s (still queue>0)"
      set_state "phase_a_timeout"
      return 1
    fi

    local queue=$(docker exec knowbase-redis redis-cli LLEN rq:queue:reprocess 2>/dev/null | tr -d '\r')
    local started=$(docker exec knowbase-worker python3 -c "
from rq.registry import StartedJobRegistry
from redis import Redis
r = Redis(host='knowbase-redis', port=6379)
print(len(StartedJobRegistry('reprocess', connection=r).get_job_ids()))
" 2>/dev/null | tail -1)
    local docs_with_claims=$(docker exec knowbase-neo4j cypher-shell -u neo4j -p graphiti_neo4j_pass --format plain "MATCH (c:Claim) WITH DISTINCT c.doc_id AS d RETURN count(d) AS n" 2>/dev/null | grep -E '^[0-9]+$' | tail -1)

    log INFO "queue=$queue started=$started docs_with_claims=${docs_with_claims:-?}/$EXPECTED_DOC_COUNT"

    # Idle check: queue=0 + started=0 + reasonable doc count
    if [ "$queue" = "0" ] && [ "$started" = "0" ]; then
      if [ "${docs_with_claims:-0}" -ge "$EXPECTED_DOC_COUNT" ]; then
        log INFO "PHASE A: BATCH COMPLETE — all $EXPECTED_DOC_COUNT docs have claims"
        set_state "phase_a_done"
        return 0
      fi

      # Idle but not all docs have claims → check if real or just transient
      stuck_iterations=$((stuck_iterations + 1))
      log WARN "Idle but only ${docs_with_claims:-0}/$EXPECTED_DOC_COUNT docs have claims (stuck_iter=$stuck_iterations)"
      if [ "$stuck_iterations" -ge 3 ]; then
        # 3 consecutive idle checks (15 min) and not all done = likely failed jobs
        log WARN "PHASE A: idle 15+ min with ${docs_with_claims:-0}/$EXPECTED_DOC_COUNT — proceeding anyway"
        set_state "phase_a_done_partial"
        return 0
      fi
    else
      stuck_iterations=0
    fi

    sleep 300  # 5 min
  done
}

# ============================================================================
# Phase B: Post-import pipeline
# ============================================================================
phase_b_post_import() {
  log INFO "PHASE B: Enqueueing post-import (13 steps)"
  set_state "phase_b_running"

  # Direct enqueue via RQ (skip HTTP auth)
  local job_id=$(docker exec knowbase-worker python3 -c "
from redis import Redis
from rq import Queue
import os
r = Redis(host='knowbase-redis', port=6379)
q = Queue('reprocess', connection=r)
steps = [
    'canonicalize','facets','facet_consolidate','purge_orphan_facets',
    'cluster_cross_doc','chains_cross_doc','detect_contradictions',
    'domain_pack_reprocess','claim_embeddings','claim_chunk_bridge',
    'archive_isolated','garbage_collection','c4_relations','c6_pivots',
    'build_perspectives'
]
from knowbase.api.routers.post_import import run_pipeline_job, STEPS_BY_ID
ordered = sorted(steps, key=lambda s: STEPS_BY_ID[s].order)
job = q.enqueue(run_pipeline_job, ordered, 'default', job_timeout='8h')
print(job.id)
" 2>/dev/null | tail -1)

  if [ -z "$job_id" ]; then
    log ERROR "PHASE B: failed to enqueue post-import"
    set_state "phase_b_failed_enqueue"
    return 1
  fi

  log INFO "PHASE B: enqueued job_id=$job_id, waiting for completion"

  local max_wait=$((9 * 3600))  # 9h
  local start_ts=$(date +%s)

  while true; do
    local elapsed=$(( $(date +%s) - start_ts ))
    if [ "$elapsed" -gt "$max_wait" ]; then
      log ERROR "PHASE B: timeout after ${max_wait}s"
      set_state "phase_b_timeout"
      return 1
    fi

    local status=$(docker exec knowbase-worker python3 -c "
from rq.job import Job
from redis import Redis
r = Redis(host='knowbase-redis', port=6379)
try:
    j = Job.fetch('$job_id', connection=r)
    print(j.get_status())
except Exception as e:
    print(f'ERR:{e}')
" 2>/dev/null | tail -1)

    log INFO "PHASE B: job_id=$job_id status=$status (elapsed=${elapsed}s)"

    case "$status" in
      JobStatus.FINISHED)
        log INFO "PHASE B: COMPLETE"
        set_state "phase_b_done"
        return 0
        ;;
      JobStatus.FAILED)
        log WARN "PHASE B: job FAILED (will continue to AMI anyway)"
        set_state "phase_b_failed_job"
        return 0  # Continue to AMI even if post-import failed
        ;;
      JobStatus.STARTED|JobStatus.QUEUED|JobStatus.SCHEDULED)
        sleep 300
        ;;
      *)
        log WARN "PHASE B: unknown status $status, sleeping"
        sleep 300
        ;;
    esac
  done
}

# ============================================================================
# Phase C: Create AMI v10
# ============================================================================
phase_c_create_ami() {
  log INFO "PHASE C: Creating AMI $NEW_AMI_NAME from $INSTANCE_ID"
  set_state "phase_c_running"

  local timestamp=$(date -u +%Y%m%d-%H%M)
  local ami_name="${NEW_AMI_NAME}-${timestamp}"
  local ami_id=$(aws ec2 create-image \
    --region "$REGION" \
    --instance-id "$INSTANCE_ID" \
    --name "$ami_name" \
    --description "OSMOSIS burst v10 — Qwen2.5-14B-Instruct-AWQ on vLLM 0.9.2 (created $(date -u))" \
    --no-reboot \
    --query 'ImageId' \
    --output text 2>&1 | tail -1)

  if [[ "$ami_id" != ami-* ]]; then
    log ERROR "PHASE C: AMI creation failed: $ami_id"
    set_state "phase_c_failed"
    return 1
  fi

  log INFO "PHASE C: AMI created: $ami_id name=$ami_name"
  echo "$ami_id" > /c/Projects/SAP_KB/logs/orchestrator_ami_id.txt
  set_state "phase_c_done:$ami_id"
  return 0
}

# ============================================================================
# Phase D: Wait for AMI available
# ============================================================================
phase_d_wait_ami() {
  log INFO "PHASE D: Waiting for AMI available"
  local ami_id=$(cat /c/Projects/SAP_KB/logs/orchestrator_ami_id.txt 2>/dev/null)
  if [[ "$ami_id" != ami-* ]]; then
    log ERROR "PHASE D: no AMI ID found"
    set_state "phase_d_failed_noami"
    return 1
  fi

  set_state "phase_d_running:$ami_id"
  local max_wait=$((45 * 60))  # 45 min
  local start_ts=$(date +%s)

  while true; do
    local elapsed=$(( $(date +%s) - start_ts ))
    if [ "$elapsed" -gt "$max_wait" ]; then
      log ERROR "PHASE D: timeout after ${max_wait}s"
      set_state "phase_d_timeout"
      return 1
    fi

    local state=$(aws ec2 describe-images --region "$REGION" --image-ids "$ami_id" --query 'Images[].State' --output text 2>&1 | tr -d '\r')
    log INFO "PHASE D: AMI $ami_id state=$state (elapsed=${elapsed}s)"

    case "$state" in
      available)
        log INFO "PHASE D: AMI READY"
        set_state "phase_d_done:$ami_id"
        return 0
        ;;
      pending)
        sleep 60
        ;;
      *)
        log ERROR "PHASE D: bad AMI state: $state"
        set_state "phase_d_bad_state:$state"
        return 1
        ;;
    esac
  done
}

# ============================================================================
# Phase E: Terminate EC2 + deregister ALL old AMIs across ALL regions
# ============================================================================
phase_e_cleanup() {
  log INFO "PHASE E: AWS cleanup (ALL regions)"
  set_state "phase_e_running"

  local new_ami_id=$(cat /c/Projects/SAP_KB/logs/orchestrator_ami_id.txt 2>/dev/null)

  # 1. Terminate EC2 instance
  log INFO "PHASE E1: terminating $INSTANCE_ID"
  aws ec2 terminate-instances --region "$REGION" --instance-ids "$INSTANCE_ID" \
    --query 'TerminatingInstances[].[InstanceId,CurrentState.Name,PreviousState.Name]' \
    --output text 2>&1 | tee -a "$LOG"

  # 2. Scan ALL active regions for owned AMIs and deregister all EXCEPT the new v10
  local regions=$(aws ec2 describe-regions --query 'Regions[].RegionName' --output text 2>/dev/null | tr '\t' '\n')

  for region in $regions; do
    log INFO "PHASE E2: scanning $region for owned AMIs"
    local amis_json=$(aws ec2 describe-images --owners self --region "$region" \
      --query 'Images[].[ImageId,Name,BlockDeviceMappings[].Ebs.SnapshotId]' \
      --output text 2>/dev/null)
    if [ -z "$amis_json" ]; then
      continue
    fi

    # Lines come as: ami-XXX\tname\nsnap-XXX\nsnap-YYY (multi-line per AMI)
    # Parse: each AMI starts with ami- prefix
    while IFS=$'\t' read -r col1 col2 col3; do
      if [[ "$col1" == ami-* ]]; then
        local ami_id="$col1"
        local ami_name="$col2"
        # Skip the new v10 we just created
        if [ "$ami_id" = "$new_ami_id" ]; then
          log INFO "PHASE E2: SKIP new v10 AMI $ami_id in $region"
          continue
        fi
        log INFO "PHASE E2: deregister $ami_id ($ami_name) in $region"
        # Snapshot from BlockDeviceMappings
        local snaps=$(aws ec2 describe-images --region "$region" --image-ids "$ami_id" \
          --query 'Images[].BlockDeviceMappings[].Ebs.SnapshotId' \
          --output text 2>/dev/null | tr '\t\r\n' ' ')
        aws ec2 deregister-image --region "$region" --image-id "$ami_id" 2>&1 | tee -a "$LOG"
        for snap in $snaps; do
          if [[ "$snap" == snap-* ]]; then
            log INFO "PHASE E2: delete snapshot $snap in $region"
            aws ec2 delete-snapshot --region "$region" --snapshot-id "$snap" 2>&1 | tee -a "$LOG"
          fi
        done
      fi
    done <<< "$amis_json"
  done

  # 3. Also scan for orphan snapshots (not associated with any AMI)
  log INFO "PHASE E3: scanning for orphan snapshots in source region $REGION"
  local owned_snaps=$(aws ec2 describe-snapshots --region "$REGION" --owner-ids self \
    --query 'Snapshots[?!contains(Description,`v10`) && contains(Description,`OSMOSE`)].[SnapshotId,Description]' \
    --output text 2>/dev/null)
  if [ -n "$owned_snaps" ]; then
    while IFS=$'\t' read -r snap_id desc; do
      if [[ "$snap_id" == snap-* ]]; then
        log INFO "PHASE E3: delete orphan snap $snap_id ($desc)"
        aws ec2 delete-snapshot --region "$REGION" --snapshot-id "$snap_id" 2>&1 | tee -a "$LOG"
      fi
    done <<< "$owned_snaps"
  fi

  log INFO "PHASE E: cleanup done"
  set_state "phase_e_done"
  return 0
}

# ============================================================================
# Main
# ============================================================================
main() {
  log INFO "=== ORCHESTRATOR START ==="
  set_state "starting"

  phase_a_wait_batch || { log ERROR "PHASE A failed — STOP"; set_state "stopped_at_a"; exit 1; }
  phase_b_post_import || { log ERROR "PHASE B failed — STOP (no AMI/cleanup)"; set_state "stopped_at_b"; exit 1; }
  phase_c_create_ami || { log ERROR "PHASE C failed — STOP (no cleanup)"; set_state "stopped_at_c"; exit 1; }
  phase_d_wait_ami || { log ERROR "PHASE D failed — STOP (no cleanup, AMI not available)"; set_state "stopped_at_d"; exit 1; }
  phase_e_cleanup || { log ERROR "PHASE E failed but AMI created"; set_state "stopped_at_e"; exit 1; }

  log INFO "=== ORCHESTRATOR ALL DONE ==="
  set_state "all_done"
}

main "$@"
