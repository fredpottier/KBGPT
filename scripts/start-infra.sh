#!/bin/bash
# Start Infrastructure Services (Qdrant, Redis, Neo4j)
# Usage: ./scripts/start-infra.sh

set -e

echo "🚀 Starting Infrastructure Services..."
echo "======================================"

docker-compose -f docker-compose.infra.yml up -d

echo ""
echo "⏳ Waiting for services to be healthy..."
sleep 5

echo ""
echo "📊 Infrastructure Status:"
docker-compose -f docker-compose.infra.yml ps

echo ""
echo "✅ Infrastructure services started!"
echo ""
echo "Services available:"
echo "  - Qdrant:  http://localhost:6333/dashboard"
echo "  - Redis:   localhost:6379"
echo "  - Neo4j:   http://localhost:7474 (user: neo4j, pass: check .env)"
echo ""
echo "To stop: docker-compose -f docker-compose.infra.yml down"
