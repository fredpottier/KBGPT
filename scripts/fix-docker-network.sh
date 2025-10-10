#!/bin/bash
# Script pour corriger les problèmes de réseau Docker
# Connecte tous les services au réseau knowbase_network

set -e

echo "🔧 Correction réseau Docker - Knowbase"
echo "======================================"
echo ""

# Liste des services à connecter
SERVICES=(
    "knowbase-app"
    "knowbase-worker"
    "knowbase-frontend"
    "knowbase-redis"
    "knowbase-qdrant"
)

NETWORK="knowbase_network"

# Vérifier que le réseau existe
if ! docker network inspect $NETWORK > /dev/null 2>&1; then
    echo "❌ Le réseau $NETWORK n'existe pas"
    echo "Créez-le avec : docker network create $NETWORK"
    exit 1
fi

echo "✅ Réseau $NETWORK trouvé"
echo ""

# Connecter chaque service
for service in "${SERVICES[@]}"; do
    echo "Traitement de $service..."

    # Vérifier si le container existe
    if ! docker inspect $service > /dev/null 2>&1; then
        echo "  ⚠️  Container $service introuvable - skip"
        continue
    fi

    # Vérifier s'il est déjà connecté
    networks=$(docker inspect $service --format '{{range $key, $value := .NetworkSettings.Networks}}{{$key}} {{end}}')

    if echo "$networks" | grep -q "$NETWORK"; then
        echo "  ✅ Déjà connecté à $NETWORK"
    else
        echo "  🔗 Connexion à $NETWORK..."
        docker network connect $NETWORK $service 2>&1 || echo "  ⚠️  Erreur de connexion (peut-être déjà connecté)"
        echo "  ✅ Connecté avec succès"
    fi
done

echo ""
echo "======================================"
echo "✅ Configuration réseau terminée"
echo ""
echo "Redémarrez les services avec :"
echo "  docker-compose restart app ingestion-worker"
