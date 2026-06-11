#!/usr/bin/env bash
# Gardien auto-réparant pendant le post-import.
#  - Resync Redis vers une instance burst saine si l'actuelle tombe (reprise spot).
#  - Surveille le job RQ du post-import : sort quand finished/failed.
#  - Logge l'étape courante (depuis les logs worker) pour rapport.
set -uo pipefail
JOB="${1:?job_id requis}"
REGION=eu-central-1

burst_ip() { docker exec knowbase-app python -c "from knowbase.ingestion.burst.provider_switch import get_burst_state_from_redis as g; s=g() or {}; u=s.get('vllm_url','') if s.get('active') else ''; print(u.replace('http://','').split(':')[0])" 2>/dev/null | tr -d '\r'; }
healthy() { curl -s -m 6 "http://$1:8080/" 2>/dev/null | grep -q '"healthy": true'; }
aws_ip() { aws ec2 describe-instances --region $REGION --filters "Name=instance-type,Values=g6.xlarge,g6.2xlarge,g5.xlarge,g5.2xlarge" "Name=instance-state-name,Values=running" --query "Reservations[].Instances[?PublicIpAddress!=null].PublicIpAddress | [0]" --output text 2>/dev/null | tr -d '\r'; }
resync_to() { docker exec knowbase-app python -c "from knowbase.ingestion.burst.provider_switch import set_burst_state_in_redis as s; print(s(vllm_url='http://$1:8000', vllm_model='Qwen/Qwen2.5-14B-Instruct-AWQ', embeddings_url='http://$1:8001'))" 2>/dev/null | tr -d '\r'; }
job_status() { docker exec knowbase-app python -c "
import os; from redis import Redis; from rq.job import Job
try:
    j=Job.fetch('$JOB', connection=Redis.from_url(os.environ['REDIS_URL']))
    print(j.get_status(refresh=True))
except Exception as e:
    print('unknown')
" 2>/dev/null | tr -d '\r' | tail -1; }

echo "KEEP-START job=$JOB @ $(date +%H:%M:%S)"
LAST_STEP=""
for i in $(seq 1 240); do
  IP="$(burst_ip)"
  if [ -z "$IP" ] || ! healthy "$IP"; then
    N="$(aws_ip)"
    if [ -n "$N" ] && [ "$N" != "None" ] && healthy "$N"; then
      resync_to "$N" >/dev/null; echo "RESYNC $(date +%H:%M:%S): '$IP' KO -> $N"
    else
      echo "WARN $(date +%H:%M:%S): burst KO, aucune instance saine (N=$N)"
    fi
  fi
  STEP=$(docker logs --since 80s knowbase-worker-2 2>&1 | grep -oE "\[PostImport\][^|]*|étape [a-z_]+|step=[a-z_]+|Étape [a-z_]+" | tail -1)
  [ -n "$STEP" ] && [ "$STEP" != "$LAST_STEP" ] && { echo "STEP $(date +%H:%M:%S): $STEP"; LAST_STEP="$STEP"; }
  ST="$(job_status)"
  if [ "$ST" = "finished" ] || [ "$ST" = "failed" ]; then
    echo "POSTIMPORT_$ST @ $(date +%H:%M:%S)"; exit 0
  fi
  sleep 45
done
echo "KEEP-TIMEOUT @ $(date +%H:%M:%S)"
