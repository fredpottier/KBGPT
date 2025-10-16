#!/bin/bash
# Script de nettoyage complet de toutes les bases de données
# Usage: ./scripts/clean_all_databases.sh [--confirm]

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

# Couleurs pour les logs
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

log_info() {
    echo -e "${BLUE}ℹ️  $1${NC}"
}

log_success() {
    echo -e "${GREEN}✅ $1${NC}"
}

log_warning() {
    echo -e "${YELLOW}⚠️  $1${NC}"
}

log_error() {
    echo -e "${RED}❌ $1${NC}"
}

# Vérifier si le flag --confirm est passé
CONFIRM_FLAG=""
if [ "$1" = "--confirm" ]; then
    CONFIRM_FLAG="yes"
fi

echo ""
echo "════════════════════════════════════════════════════════════════"
echo "  🧹 NETTOYAGE COMPLET DES BASES DE DONNÉES SAP KB"
echo "════════════════════════════════════════════════════════════════"
echo ""
log_warning "Ce script va supprimer TOUTES les données de :"
echo "  • Qdrant (collections knowbase et rfp_qa)"
echo "  • Redis (DB 0 et DB 1)"
echo "  • Neo4j (tous les nodes et relations)"
echo "  • Postgres/Graphiti (cache episodes)"
echo "  • Historique imports (data/status/)"
echo ""

if [ "$CONFIRM_FLAG" != "yes" ]; then
    read -p "Êtes-vous sûr de vouloir continuer ? (tapez 'oui' pour confirmer) : " confirmation
    if [ "$confirmation" != "oui" ]; then
        log_error "Annulation du nettoyage."
        exit 1
    fi
fi

echo ""
log_info "Démarrage du nettoyage..."
echo ""

# ═══════════════════════════════════════════════════════════════════
# 1. QDRANT - Supprimer toutes les collections
# ═══════════════════════════════════════════════════════════════════
log_info "[1/5] Nettoyage Qdrant..."

COLLECTIONS=$(curl -s http://localhost:6333/collections | python -m json.tool 2>/dev/null | grep '"name"' | awk -F'"' '{print $4}')

if [ -z "$COLLECTIONS" ]; then
    log_warning "Aucune collection Qdrant trouvée"
else
    for collection in $COLLECTIONS; do
        log_info "  Suppression collection: $collection"
        curl -s -X DELETE "http://localhost:6333/collections/$collection" > /dev/null 2>&1
        log_success "  Collection $collection supprimée"
    done
fi

# ═══════════════════════════════════════════════════════════════════
# 2. REDIS - Purger toutes les bases
# ═══════════════════════════════════════════════════════════════════
log_info "[2/5] Nettoyage Redis..."

# DB 0 (imports metadata)
DB0_SIZE=$(docker exec knowbase-redis redis-cli -n 0 DBSIZE 2>/dev/null | grep -o '[0-9]*')
if [ "$DB0_SIZE" -gt 0 ]; then
    log_info "  Purge Redis DB 0 ($DB0_SIZE clés)"
    docker exec knowbase-redis redis-cli -n 0 FLUSHDB > /dev/null 2>&1
    log_success "  Redis DB 0 purgée"
else
    log_warning "  Redis DB 0 déjà vide"
fi

# DB 1 (jobs queue)
DB1_SIZE=$(docker exec knowbase-redis redis-cli -n 1 DBSIZE 2>/dev/null | grep -o '[0-9]*')
if [ "$DB1_SIZE" -gt 0 ]; then
    log_info "  Purge Redis DB 1 ($DB1_SIZE clés)"
    docker exec knowbase-redis redis-cli -n 1 FLUSHDB > /dev/null 2>&1
    log_success "  Redis DB 1 purgée"
else
    log_warning "  Redis DB 1 déjà vide"
fi

# ═══════════════════════════════════════════════════════════════════
# 3. NEO4J - Supprimer tous les nodes et relations
# ═══════════════════════════════════════════════════════════════════
log_info "[3/5] Nettoyage Neo4j..."

if docker ps --format '{{.Names}}' | grep -q "graphiti-neo4j"; then
    # Credentials Neo4j (depuis .env)
    NEO4J_USER=${NEO4J_USER:-neo4j}
    NEO4J_PASSWORD=${NEO4J_PASSWORD:-graphiti_neo4j_pass}

    # Compter les nodes avant suppression
    NODE_COUNT=$(docker exec graphiti-neo4j cypher-shell -u "$NEO4J_USER" -p "$NEO4J_PASSWORD" \
        "MATCH (n) RETURN count(n) as count" 2>/dev/null | tail -1 | tr -d ' ' || echo "0")

    if [ "$NODE_COUNT" -gt 0 ]; then
        log_info "  Suppression de $NODE_COUNT nodes Neo4j"
        docker exec graphiti-neo4j cypher-shell -u "$NEO4J_USER" -p "$NEO4J_PASSWORD" \
            "MATCH (n) DETACH DELETE n" > /dev/null 2>&1
        log_success "  Neo4j purgé ($NODE_COUNT nodes supprimés)"
    else
        log_warning "  Neo4j déjà vide"
    fi
else
    log_warning "  Conteneur Neo4j non trouvé (OK si non utilisé)"
fi

# ═══════════════════════════════════════════════════════════════════
# 4. POSTGRES/GRAPHITI - Skip (non utilisé, Graphiti deprecated)
# ═══════════════════════════════════════════════════════════════════
log_info "[4/5] Postgres/Graphiti (skip - non utilisé)..."
log_warning "  Graphiti n'est plus utilisé, conteneurs ignorés"

# ═══════════════════════════════════════════════════════════════════
# 5. HISTORIQUE IMPORTS - Supprimer fichiers status
# ═══════════════════════════════════════════════════════════════════
log_info "[5/5] Nettoyage historique imports..."

STATUS_DIR="$PROJECT_ROOT/data/status"
if [ -d "$STATUS_DIR" ]; then
    STATUS_COUNT=$(find "$STATUS_DIR" -type f -name "*.json" 2>/dev/null | wc -l)
    if [ "$STATUS_COUNT" -gt 0 ]; then
        log_info "  Suppression de $STATUS_COUNT fichiers status"
        find "$STATUS_DIR" -type f -name "*.json" -delete 2>/dev/null
        log_success "  Historique imports nettoyé"
    else
        log_warning "  Aucun fichier status trouvé"
    fi
else
    log_warning "  Répertoire status non trouvé"
fi

# ═══════════════════════════════════════════════════════════════════
# RÉSUMÉ FINAL
# ═══════════════════════════════════════════════════════════════════
echo ""
echo "════════════════════════════════════════════════════════════════"
log_success "NETTOYAGE TERMINÉ AVEC SUCCÈS"
echo "════════════════════════════════════════════════════════════════"
echo ""
log_info "Résumé des opérations :"
echo "  ✓ Qdrant : toutes les collections supprimées"
echo "  ✓ Redis : DB 0 et DB 1 purgées"
echo "  ✓ Neo4j : tous les nodes supprimés"
echo "  ○ Postgres/Graphiti : ignoré (non utilisé)"
echo "  ✓ Historique : fichiers status supprimés"
echo ""
log_info "Vous pouvez maintenant importer un nouveau PPTX avec une base propre."
echo ""
