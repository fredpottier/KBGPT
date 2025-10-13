#!/bin/bash
# Entrypoint pour le worker d'ingestion
# Purge automatiquement le cache Python au démarrage

echo "🧹 Purge du cache Python..."
find /app -type f -name "*.pyc" -delete 2>/dev/null || true
find /app -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true

echo "✅ Cache Python purgé"
echo "🚀 Démarrage du worker RQ..."

# Exécuter la commande passée en argument (CMD du Dockerfile ou docker-compose)
exec "$@"
