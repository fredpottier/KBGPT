#!/bin/bash
# Entrypoint pour le container agent
# Corrige les permissions du dossier .claude monté depuis Windows

# Fixer les permissions du dossier .claude si nécessaire
if [ -d "/home/agent/.claude" ]; then
    # Utiliser sudo pour changer les permissions (l'agent a les droits sudo)
    sudo chown -R agent:agent /home/agent/.claude 2>/dev/null || true
    sudo chmod -R 755 /home/agent/.claude 2>/dev/null || true
fi

# Exécuter la commande passée en argument (ou tail par défaut)
exec "$@"
