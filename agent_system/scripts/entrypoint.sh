#!/bin/bash
# Entrypoint pour le container agent
# Corrige les permissions et configure l'environnement

# Fixer les permissions du dossier .claude si nécessaire
if [ -d "/home/agent/.claude" ]; then
    sudo chown -R agent:agent /home/agent/.claude 2>/dev/null || true
    sudo chmod -R 755 /home/agent/.claude 2>/dev/null || true
fi

# Créer et fixer permissions du dossier projects pour les outputs
sudo mkdir -p /app/agent_system/data/projects 2>/dev/null || true
sudo chown -R agent:agent /app/agent_system/data/projects 2>/dev/null || true

# Fixer permissions du dossier .git pour permettre les opérations git
if [ -d "/app/.git" ]; then
    sudo chown -R agent:agent /app/.git 2>/dev/null || true
fi

# Fixer les permissions Docker socket pour que l'agent puisse l'utiliser
if [ -S "/var/run/docker.sock" ]; then
    sudo chmod 666 /var/run/docker.sock 2>/dev/null || true
fi

# Configurer Git pour accepter le répertoire /app (ownership différente)
git config --global --add safe.directory /app 2>/dev/null || true
git config --global --add safe.directory '*' 2>/dev/null || true

# Configurer identité Git par défaut pour les commits
git config --global user.email "agent@knowwhere.local" 2>/dev/null || true
git config --global user.name "KnowWhere Agent" 2>/dev/null || true

# Exécuter la commande passée en argument (ou tail par défaut)
exec "$@"
