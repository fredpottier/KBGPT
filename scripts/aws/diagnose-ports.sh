#!/bin/bash
#
# Script de diagnostic pour identifier les conflits de ports Docker
# Usage: ./diagnose-ports.sh
#

LOGFILE="/tmp/port-diagnostic.log"

log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1" | tee -a "$LOGFILE"
}

log "========================================="
log "DIAGNOSTIC PORTS DOCKER"
log "========================================="

# Étape 1: Processus utilisant les ports
log ""
log "[1] Processus écoutant sur les ports critiques:"
log "Port 3000 (Frontend):"
sudo lsof -i :3000 2>&1 | tee -a "$LOGFILE" || echo "  Aucun processus" | tee -a "$LOGFILE"

log "Port 3001 (Grafana):"
sudo lsof -i :3001 2>&1 | tee -a "$LOGFILE" || echo "  Aucun processus" | tee -a "$LOGFILE"

log "Port 3100 (Loki):"
sudo lsof -i :3100 2>&1 | tee -a "$LOGFILE" || echo "  Aucun processus" | tee -a "$LOGFILE"

log "Port 3101 (Loki externe):"
sudo lsof -i :3101 2>&1 | tee -a "$LOGFILE" || echo "  Aucun processus" | tee -a "$LOGFILE"

log "Port 8501 (UI):"
sudo lsof -i :8501 2>&1 | tee -a "$LOGFILE" || echo "  Aucun processus" | tee -a "$LOGFILE"

# Étape 2: Conteneurs Docker
log ""
log "[2] État conteneurs Docker:"
sudo docker ps -a --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}" | tee -a "$LOGFILE"

# Étape 3: Conteneurs en statut Created (fantômes)
log ""
log "[3] Conteneurs fantômes (Created mais pas Started):"
sudo docker ps -a --filter "status=created" --format "table {{.Names}}\t{{.Image}}\t{{.Ports}}" | tee -a "$LOGFILE"

# Étape 4: Réseaux Docker
log ""
log "[4] Réseaux Docker:"
sudo docker network ls | tee -a "$LOGFILE"

log ""
log "[5] Configuration réseau knowbase_network:"
sudo docker network inspect knowbase_network 2>&1 | tee -a "$LOGFILE" || echo "  Réseau n'existe pas" | tee -a "$LOGFILE"

# Étape 6: iptables rules pour Docker
log ""
log "[6] Règles iptables Docker (ports 3000-3101):"
sudo iptables -t nat -L DOCKER -n --line-numbers | grep -E "3000|3001|3100|3101|8501" | tee -a "$LOGFILE" || echo "  Aucune règle trouvée" | tee -a "$LOGFILE"

# Étape 7: Bindings de ports Docker (docker-proxy)
log ""
log "[7] Processus docker-proxy actifs:"
ps aux | grep docker-proxy | grep -v grep | tee -a "$LOGFILE"

# Étape 8: Tentative de bind test
log ""
log "[8] Test de bind direct sur les ports:"
for port in 3000 3001 3100 3101 8501; do
    log "  Test port $port:"
    timeout 1 nc -l -p $port 2>&1 | tee -a "$LOGFILE" &
    sleep 0.5
    kill %1 2>/dev/null
done

log ""
log "========================================="
log "FIN DIAGNOSTIC"
log "========================================="
log "Logs complets: $LOGFILE"
