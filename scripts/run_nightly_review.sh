#!/bin/bash
# Script Linux/macOS pour lancer la revue nocturne
# Usage: ./scripts/run_nightly_review.sh [OPTIONS]

echo ""
echo "========================================"
echo "  REVUE NOCTURNE SAP KB"
echo "========================================"
echo ""

# Vérifier que Python est installé
if ! command -v python3 &> /dev/null; then
    echo "ERREUR: Python 3 n'est pas installé"
    exit 1
fi

# Aller à la racine du projet
cd "$(dirname "$0")/.."

# Lancer la revue avec les arguments passés
python3 scripts/nightly_review.py "$@"

echo ""
echo "========================================"
echo "  REVUE TERMINEE"
echo "========================================"
echo ""
