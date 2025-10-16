#!/bin/bash
# Stop all services (app + infrastructure)
# Usage: ./scripts/stop-all.sh

set -e

echo "🛑 Stopping all services..."
echo "============================"

echo ""
echo "1️⃣  Stopping application services..."
docker-compose -f docker-compose.app.yml down

echo ""
echo "2️⃣  Stopping infrastructure services..."
docker-compose -f docker-compose.infra.yml down

echo ""
echo "✅ All services stopped!"
echo ""
echo "To start again:"
echo "  ./scripts/start-infra.sh"
echo "  ./scripts/start-app.sh"
