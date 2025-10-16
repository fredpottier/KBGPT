#!/bin/bash
# Restart Application Services (without touching infrastructure)
# Usage: ./scripts/restart-app.sh [service]
#   Examples:
#     ./scripts/restart-app.sh        # Restart all app services
#     ./scripts/restart-app.sh app    # Restart only backend API
#     ./scripts/restart-app.sh worker # Restart only ingestion worker

set -e

SERVICE=${1:-}

if [ -z "$SERVICE" ]; then
    echo "🔄 Restarting all application services..."
    docker-compose -f docker-compose.app.yml restart
else
    echo "🔄 Restarting $SERVICE..."
    docker-compose -f docker-compose.app.yml restart "$SERVICE"
fi

echo ""
echo "✅ Restart completed!"
echo ""
echo "📊 Status:"
docker-compose -f docker-compose.app.yml ps

echo ""
echo "📝 View logs:"
if [ -z "$SERVICE" ]; then
    echo "  docker-compose -f docker-compose.app.yml logs -f"
else
    echo "  docker-compose -f docker-compose.app.yml logs -f $SERVICE"
fi
