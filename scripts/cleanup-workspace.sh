#!/bin/bash
# Script de nettoyage workspace - Supprime fichiers obsolètes Phase north-star-phase0

set -e

echo "🧹 Nettoyage workspace - Fichiers obsolètes"
echo "============================================"

# Fichiers à GARDER (nouveaux documents Phase 0)
KEEP_FILES=(
  "doc/SECURITY_AUDIT_PHASE0.md"
)

# Fichiers/répertoires à SUPPRIMER (obsolètes)
REMOVE_ITEMS=(
  "=0.20.0"
  "GRAPHITI_ALTERNATIVES_ANALYSIS_PROMPT.md"
  "SESSION_SUMMARY_2025-10-02.md"
  "app/scripts/"
  "app/test_embeddings.py"
  "app/test_pipeline_kg_functional.py"
  "app/test_pipeline_kg_sap_ilm.py"
  "config/document_types.yaml"
  "create_test_users.py"
  "doc/DOCUMENT_TYPE_STUDIO.md"
  "doc/GRAPHITI_CACHE_POSTGRESQL_MIGRATION.md"
  "doc/NORTH_STAR_IMPLEMENTATION_TRACKING_PHASE2.md"
  "doc/PHASE2_ANALYSE_FAIBLESSES.md"
  "doc/PHASE2_TESTS_VALIDATION_MANUELLE.md"
  "doc/architecture/"
  "fix_indentation_pptx_kg.py"
  "migrations/"
  "run_test_kg.py"
  "scripts/migrate_graphiti_cache_to_postgres.py"
  "scripts/migrate_to_neo4j_clean.sh"
  "scripts/test_migrate_sample.py"
  "src/knowbase/api/routers/query.py"
  "src/knowbase/api/schemas/query_understanding.py"
  "src/knowbase/config/document_type_registry.py"
  "src/knowbase/graphiti/"
  "src/knowbase/query/"
  "temp_line.txt"
  "test_embeddings_integration.py"
  "test_final_phase1.py"
  "test_kg_final.py"
  "test_llm_vision_real.py"
  "test_neo4j_direct.py"
  "test_openai_api.py"
  "test_phase2_demo.py"
  "test_pipeline_kg_functional.py"
  "test_pipeline_kg_quick.py"
  "test_pipeline_kg_sap_ilm.py"
  "tests/config/test_document_type_registry.py"
  "tests/query/"
)

echo ""
echo "📋 Fichiers à supprimer :"
for item in "${REMOVE_ITEMS[@]}"; do
  if [ -e "$item" ]; then
    echo "  - $item"
  fi
done

echo ""
read -p "Confirmer suppression ? (y/n) " -n 1 -r
echo

if [[ $REPLY =~ ^[Yy]$ ]]; then
  echo ""
  echo "🗑️  Suppression en cours..."

  for item in "${REMOVE_ITEMS[@]}"; do
    if [ -e "$item" ]; then
      rm -rf "$item"
      echo "  ✅ Supprimé: $item"
    fi
  done

  echo ""
  echo "✅ Nettoyage terminé !"
  echo ""
  echo "📊 Statut workspace :"
  git status --short
else
  echo ""
  echo "❌ Nettoyage annulé"
fi
