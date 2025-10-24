#!/bin/bash
#
# Script de déploiement KnowWhere sur EC2
# Exécuté directement sur l'instance EC2 pour éviter les problèmes SSH/SCP multiples
#
set -e  # Exit on error

LOGFILE="/tmp/knowbase-deploy.log"
WORKDIR="/home/ubuntu/knowbase"

log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1" | tee -a "$LOGFILE"
}

log "==================================="
log "Déploiement KnowWhere OSMOSE"
log "==================================="

# Étape 1: Création des répertoires
log "[1/7] Création structure répertoires..."
mkdir -p "$WORKDIR"/{config,monitoring/dashboards,data}
mkdir -p /data/{neo4j,qdrant,redis}
sudo chown -R ubuntu:ubuntu "$WORKDIR" /data
log "✓ Répertoires créés"

# Étape 2: Attendre que les fichiers soient uploadés
log "[2/7] Attente des fichiers de configuration..."
max_wait=60
waited=0
while [ ! -f "$WORKDIR/docker-compose.yml" ] && [ $waited -lt $max_wait ]; do
    sleep 2
    waited=$((waited + 2))
done

if [ ! -f "$WORKDIR/docker-compose.yml" ]; then
    log "✗ ERREUR: docker-compose.yml non trouvé après ${max_wait}s"
    exit 1
fi
log "✓ Fichiers de configuration reçus"

# Étape 3: Vérifier que .env existe et configure CORS si fourni
log "[3/7] Configuration environnement..."
if [ ! -f "$WORKDIR/.env" ]; then
    log "✗ ERREUR: Fichier .env manquant"
    exit 1
fi

# CORS_ORIGINS sera configuré par PowerShell avant ce script
log "✓ Fichier .env configuré"

# Étape 4: Ajouter ubuntu au groupe docker
log "[4/7] Configuration permissions Docker..."
sudo usermod -aG docker ubuntu
log "✓ Permissions Docker configurées"

# Étape 5: Login ECR
log "[5/7] Authentification ECR..."
AWS_REGION="${AWS_REGION:-eu-west-1}"
AWS_ACCOUNT_ID="${AWS_ACCOUNT_ID:-715927975014}"

# Get ECR password and login
aws ecr get-login-password --region "$AWS_REGION" | \
    sudo docker login --username AWS --password-stdin \
    "${AWS_ACCOUNT_ID}.dkr.ecr.${AWS_REGION}.amazonaws.com"

if [ $? -ne 0 ]; then
    log "✗ ERREUR: Échec authentification ECR"
    exit 1
fi
log "✓ ECR authentifié"

# Étape 6: Pull des images Docker
log "[6/7] Téléchargement images Docker (2-3 min)..."
cd "$WORKDIR"

# Check if monitoring stack should be deployed
if [ -f "docker-compose.monitoring.yml" ]; then
    log "  Pulling avec stack monitoring..."
    sudo docker-compose -f docker-compose.yml -f docker-compose.monitoring.yml pull
else
    log "  Pulling stack principal uniquement..."
    sudo docker-compose pull
fi

if [ $? -ne 0 ]; then
    log "✗ ERREUR: Échec pull images Docker"
    exit 1
fi
log "✓ Images Docker téléchargées"

# Étape 7: Démarrage des conteneurs
log "[7/7] Démarrage conteneurs Docker..."
if [ -f "docker-compose.monitoring.yml" ]; then
    sudo docker-compose -f docker-compose.yml -f docker-compose.monitoring.yml up -d
else
    sudo docker-compose up -d
fi

if [ $? -ne 0 ]; then
    log "✗ ERREUR: Échec démarrage conteneurs"
    sudo docker-compose logs --tail=50
    exit 1
fi
log "✓ Conteneurs démarrés"

# Attendre que les services soient ready
log "Attente démarrage services (60s)..."
sleep 60

# Vérifier statut des conteneurs
log "Statut final des conteneurs:"
sudo docker-compose ps | tee -a "$LOGFILE"

log "==================================="
log "✓ DÉPLOIEMENT TERMINÉ AVEC SUCCÈS"
log "==================================="
log "Logs complets: $LOGFILE"
