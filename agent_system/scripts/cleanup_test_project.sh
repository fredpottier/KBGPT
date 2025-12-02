#!/bin/bash
# Script de nettoyage après test du projet

PROJECT_ID=${1:-"todo_api_test"}

echo "🧹 Nettoyage du projet de test: $PROJECT_ID"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

# Retourner sur la branche d'origine
ORIGINAL_BRANCH=$(git rev-parse --abbrev-ref HEAD)
if [ "$ORIGINAL_BRANCH" = "project/$PROJECT_ID" ]; then
    echo "⚠️  Vous êtes sur la branche du projet, checkout main..."
    git checkout main
fi

# Supprimer la branche projet
if git rev-parse --verify "project/$PROJECT_ID" >/dev/null 2>&1; then
    echo "🗑️  Suppression de la branche: project/$PROJECT_ID"
    git branch -D "project/$PROJECT_ID"
    echo "✅ Branche supprimée"
else
    echo "ℹ️  Branche project/$PROJECT_ID n'existe pas"
fi

# Supprimer les fichiers générés
if [ -d "agent_system/data/projects/$PROJECT_ID" ]; then
    echo "🗑️  Suppression des fichiers: agent_system/data/projects/$PROJECT_ID"
    rm -rf "agent_system/data/projects/$PROJECT_ID"
    echo "✅ Fichiers supprimés"
else
    echo "ℹ️  Répertoire data/projects/$PROJECT_ID n'existe pas"
fi

# Retourner sur la branche d'origine (si différente de la branche projet)
if [ "$ORIGINAL_BRANCH" != "project/$PROJECT_ID" ]; then
    echo "🔙 Retour sur: $ORIGINAL_BRANCH"
    git checkout "$ORIGINAL_BRANCH"
fi

echo ""
echo "✅ Nettoyage terminé!"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
