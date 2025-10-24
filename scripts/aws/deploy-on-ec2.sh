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

# Étape 1: Création des répertoires et vérification fichiers
log "[1/7] Préparation environnement..."
mkdir -p "$WORKDIR"/{config,monitoring/dashboards,data}
sudo mkdir -p /data/{neo4j,qdrant,redis}
sudo chown -R ubuntu:ubuntu "$WORKDIR" /data

# Vérifier que les fichiers essentiels sont présents
if [ ! -f "$WORKDIR/docker-compose.yml" ]; then
    log "✗ ERREUR: docker-compose.yml non trouvé dans $WORKDIR"
    log "Contenu du répertoire:"
    ls -la "$WORKDIR"
    exit 1
fi

if [ ! -f "$WORKDIR/.env" ]; then
    log "✗ ERREUR: .env non trouvé dans $WORKDIR"
    exit 1
fi

log "✓ Environnement prêt (répertoires + fichiers vérifiés)"

# Étape 2: Configuration environnement
log "[2/7] Configuration environnement..."
# CORS_ORIGINS + AWS variables déjà configurés par PowerShell dans .env
log "✓ Variables d'environnement configurées"

# Étape 3: Ajouter ubuntu au groupe docker
log "[3/7] Configuration permissions Docker..."
sudo usermod -aG docker ubuntu
log "✓ Permissions Docker configurées"

# Étape 4: Login ECR
log "[4/7] Authentification ECR..."
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

# Étape 5: Pull des images Docker
log "[5/7] Téléchargement images Docker (2-3 min)..."
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

# Étape 6: Créer réseau Docker + Démarrage des conteneurs
log "[6/7] Démarrage conteneurs Docker..."

# Créer le réseau s'il n'existe pas
if ! sudo docker network inspect knowbase_network >/dev/null 2>&1; then
    log "  Création réseau Docker knowbase_network..."
    sudo docker network create knowbase_network
fi

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

# Étape 7: Vérification finale
log "[7/7] Attente démarrage services (60s)..."
sleep 60

# Vérifier statut des conteneurs
log "Statut final des conteneurs:"
sudo docker-compose ps | tee -a "$LOGFILE"

log "==================================="
log "✓ DÉPLOIEMENT TERMINÉ AVEC SUCCÈS"
log "==================================="
log "Logs complets: $LOGFILE"
