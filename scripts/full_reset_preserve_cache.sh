#!/bin/bash
# Script de purge complète Neo4j + Redis + Qdrant
# PRÉSERVE les caches d'extraction (data/extraction_cache/)

set -e

echo ""
echo "🗑️  PURGE COMPLÈTE SYSTÈME OSMOSE"
echo "=================================="
echo ""
echo "⚠️  ATTENTION : Cette opération va supprimer :"
echo "   - Tous les graphes Neo4j"
echo "   - Toutes les queues Redis"
echo "   - Toutes les collections Qdrant"
echo "   - Tous les fichiers de statut"
echo ""
echo "✅ PRÉSERVÉ :"
echo "   - Caches d'extraction (data/extraction_cache/)"
echo "   - Contexte métier Neo4j (DomainContextProfile)"
echo ""
read -p "Continuer ? (y/N) " -n 1 -r
echo
if [[ ! $REPLY =~ ^[Yy]$ ]]
then
    echo "❌ Opération annulée"
    exit 1
fi

echo ""
echo "1️⃣  Purge Redis..."
docker exec knowbase-redis redis-cli FLUSHDB
echo "   ✅ Redis purgé"

echo ""
echo "2️⃣  Purge Qdrant (collections)..."
curl -X DELETE "http://localhost:6333/collections/knowbase" 2>/dev/null || echo "   ⚠️  Collection knowbase n'existait pas"
curl -X DELETE "http://localhost:6333/collections/rfp_qa" 2>/dev/null || echo "   ⚠️  Collection rfp_qa n'existait pas"
curl -X DELETE "http://localhost:6333/collections/knowwhere_proto" 2>/dev/null || echo "   ⚠️  Collection knowwhere_proto n'existait pas"
echo "   ✅ Qdrant purgé"

echo ""
echo "3️⃣  Purge Neo4j (SAUF DomainContextProfile)..."
docker exec knowbase-neo4j cypher-shell -u neo4j -p graphiti_neo4j_pass --format plain "
MATCH (n)
WHERE NOT n:DomainContextProfile
DETACH DELETE n
" 2>/dev/null || echo "   ⚠️  Neo4j vide ou erreur connexion"
echo "   ✅ Neo4j purgé (contexte métier préservé)"

echo ""
echo "4️⃣  Purge fichiers traités..."
rm -rf data/docs_done/* 2>/dev/null || true
rm -rf data/status/*.status 2>/dev/null || true
echo "   ✅ Fichiers de statut purgés"

echo ""
echo "5️⃣  Vérification caches préservés..."
if [ -d "data/extraction_cache" ]; then
    CACHE_COUNT=$(find data/extraction_cache -name "*.knowcache.json" 2>/dev/null | wc -l)
    echo "   ✅ $CACHE_COUNT fichiers cache préservés"
else
    echo "   ⚠️  Dossier extraction_cache introuvable"
fi

echo ""
echo "6️⃣  Vérification contexte métier..."
CONTEXT_CHECK=$(docker exec knowbase-neo4j cypher-shell -u neo4j -p graphiti_neo4j_pass --format plain "
MATCH (dcp:DomainContextProfile {tenant_id: 'default'})
RETURN dcp.tenant_id AS tenant, dcp.industry AS industry
" 2>/dev/null || echo "")

if [[ $CONTEXT_CHECK == *"default"* ]]; then
    echo "   ✅ Contexte métier 'default' préservé"
else
    echo "   ⚠️  Contexte métier 'default' non trouvé (peut-être pas encore créé)"
fi

echo ""
echo "=================================="
echo "✅ PURGE TERMINÉE"
echo ""
echo "📊 État du système :"
echo "   - Neo4j : Vide (sauf DomainContextProfile)"
echo "   - Redis : Vide"
echo "   - Qdrant : Vide"
echo "   - Caches extraction : Préservés"
echo "   - Contexte métier : Préservé"
echo ""
echo "🚀 Prêt pour un nouvel import !"
echo ""
