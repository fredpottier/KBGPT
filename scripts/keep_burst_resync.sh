#!/usr/bin/env bash
# Gardien resync-only pour travail nocturne : maintient Redis pointé sur une
# instance burst saine (reprise spot). Ne s'arrête pas (tourne en boucle longue).
set -uo pipefail
REGION=eu-central-1
burst_ip(){ docker exec knowbase-app python -c "from knowbase.ingestion.burst.provider_switch import get_burst_state_from_redis as g;s=g() or {};u=s.get('vllm_url','') if s.get('active') else '';print(u.replace('http://','').split(':')[0])" 2>/dev/null|tr -d '\r'; }
healthy(){ curl -s -m6 "http://$1:8080/" 2>/dev/null|grep -q '"healthy": true'; }
aws_ip(){ aws ec2 describe-instances --region $REGION --filters "Name=instance-type,Values=g6.xlarge,g6.2xlarge,g5.xlarge,g5.2xlarge" "Name=instance-state-name,Values=running" --query "Reservations[].Instances[?PublicIpAddress!=null].PublicIpAddress | [0]" --output text 2>/dev/null|tr -d '\r'; }
resync(){ docker exec knowbase-app python -c "from knowbase.ingestion.burst.provider_switch import set_burst_state_in_redis as s;print(s(vllm_url='http://$1:8000',vllm_model='Qwen/Qwen2.5-14B-Instruct-AWQ',embeddings_url='http://$1:8001'))" 2>/dev/null|tr -d '\r'; }
for i in $(seq 1 480); do
  IP="$(burst_ip)"
  if [ -z "$IP" ] || ! healthy "$IP"; then
    N="$(aws_ip)"
    if [ -n "$N" ] && [ "$N" != "None" ] && healthy "$N"; then resync "$N">/dev/null; echo "RESYNC $(date +%H:%M:%S): $IP -> $N"; else echo "WARN $(date +%H:%M:%S): burst KO N=$N"; fi
  fi
  sleep 45
done
