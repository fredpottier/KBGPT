#!/usr/bin/env bash
# Monitor auto-réparant du lot d'ingestion alcohol_health.
#  - Détecte chaque doc terminé (claims persistés) -> sort pour rapport.
#  - Self-healing : si l'IP burst dans Redis ne répond plus, découvre l'instance
#    AWS running et resync Redis (set_burst_state_in_redis) -> le batch survit aux
#    reprises spot sans intervention. Le resync est loggé (pas de sortie).
#  - Sort aussi quand les 24 docs sont faits.
set -uo pipefail
NEO='docker exec knowbase-neo4j cypher-shell -u neo4j -p graphiti_neo4j_pass --format plain'
REGION=eu-central-1
TARGET=24

done_list() { $NEO "MATCH (c:Claim {tenant_id:'alcohol_health'}) RETURN DISTINCT c.doc_id AS d ORDER BY d" 2>/dev/null \
  | grep -v '^d$' | tr -d '"\r' | grep . | sed -E 's/_[0-9a-f]{8}$//' | sort -u; }

burst_ip() { docker exec knowbase-app python -c "from knowbase.ingestion.burst.provider_switch import get_burst_state_from_redis as g; s=g() or {}; u=s.get('vllm_url','') if s.get('active') else ''; print(u.replace('http://','').split(':')[0])" 2>/dev/null | tr -d '\r'; }

healthy() { curl -s -m 6 "http://$1:8080/" 2>/dev/null | grep -q '"healthy": true'; }

aws_running_ip() { aws ec2 describe-instances --region $REGION \
  --filters "Name=instance-type,Values=g6.xlarge,g6.2xlarge,g5.xlarge,g5.2xlarge" "Name=instance-state-name,Values=running" \
  --query "Reservations[].Instances[?PublicIpAddress!=null].PublicIpAddress | [0]" --output text 2>/dev/null | tr -d '\r'; }

resync_to() { docker exec knowbase-app python -c "
from knowbase.ingestion.burst.provider_switch import set_burst_state_in_redis
print(set_burst_state_in_redis(vllm_url='http://$1:8000', vllm_model='Qwen/Qwen2.5-14B-Instruct-AWQ', embeddings_url='http://$1:8001'))" 2>/dev/null | tr -d '\r'; }

BASE="$(done_list)"
BASE_N=$(printf '%s\n' "$BASE" | grep -c .)
echo "START baseline=$BASE_N docs @ $(date +%H:%M:%S)"

for i in $(seq 1 120); do
  # --- self-healing burst ---
  IP="$(burst_ip)"
  if [ -z "$IP" ] || ! healthy "$IP"; then
    NEWIP="$(aws_running_ip)"
    if [ -n "$NEWIP" ] && [ "$NEWIP" != "None" ] && healthy "$NEWIP"; then
      resync_to "$NEWIP" >/dev/null
      echo "RESYNC $(date +%H:%M:%S): burst '$IP' KO -> resync vers $NEWIP (sain)"
    else
      echo "WARN $(date +%H:%M:%S): burst '$IP' KO et aucune instance saine trouvée (NEWIP=$NEWIP)"
    fi
  fi
  # --- doc completion ---
  NOW="$(done_list)"; TOT=$(printf '%s\n' "$NOW" | grep -c .)
  NEW="$(comm -13 <(printf '%s\n' "$BASE" | sort) <(printf '%s\n' "$NOW" | sort) | grep .)"
  if [ -n "$NEW" ]; then
    echo "NEW_DONE @ $(date +%H:%M:%S) (total=$TOT/$TARGET)"; printf '%s\n' "$NEW"
    exit 0
  fi
  if [ "$TOT" -ge "$TARGET" ]; then echo "ALL_DONE total=$TOT @ $(date +%H:%M:%S)"; exit 0; fi
  sleep 40
done
echo "TIMEOUT après 120 cycles (total=$TOT/$TARGET) @ $(date +%H:%M:%S)"
