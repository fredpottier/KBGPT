#!/bin/bash
# Start Application Services (App, Worker, Frontend)
# Usage: ./scripts/start-app.sh
# Prerequisite: Infrastructure services must be running

set -e

echo "🚀 Starting Application Services..."
echo "===================================="

# Check if infrastructure is running
if ! docker ps | grep -q "knowbase-qdrant"; then
    echo "❌ Error: Infrastructure services not running!"
    echo "Please start infrastructure first:"
    echo "  ./scripts/start-infra.sh"
    exit 1
fi

docker-compose -f docker-compose.app.yml up -d

echo ""
echo "⏳ Waiting for services to be healthy..."
sleep 5

echo ""
echo "📊 Application Status:"
docker-compose -f docker-compose.app.yml ps

echo ""
echo "✅ Application services started!"
echo ""
echo "Services available:"
echo "  - API:      http://localhost:8000"
echo "  - API Docs: http://localhost:8000/docs"
echo "  - Frontend: http://localhost:3000"
echo "  - Streamlit: http://localhost:8501"
echo ""
echo "To restart: docker-compose -f docker-compose.app.yml restart app"
echo "To stop: docker-compose -f docker-compose.app.yml down"
