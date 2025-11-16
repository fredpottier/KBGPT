# Script kw.ps1 - Gestionnaire Docker KnowWhere/OSMOSE

Script PowerShell unifié pour gérer facilement tous les services Docker du projet.

## 🚀 Démarrage Rapide

```powershell
# Tout démarrer (infrastructure + application)
./kw.ps1 start

# Voir les URLs et credentials
./kw.ps1 info

# Voir le statut
./kw.ps1 status
```

## 📋 Commandes Disponibles

### Démarrage

```powershell
./kw.ps1 start              # Démarre infrastructure + application
./kw.ps1 start infra        # Démarre uniquement infrastructure (Qdrant, Redis, Neo4j)
./kw.ps1 start app          # Démarre uniquement application (App, Worker, Frontend, UI)
```

### Arrêt

```powershell
./kw.ps1 stop               # Arrête tout
./kw.ps1 stop infra         # Arrête uniquement infrastructure
./kw.ps1 stop app           # Arrête uniquement application
```

### Redémarrage

```powershell
./kw.ps1 restart            # Redémarre tout
./kw.ps1 restart infra      # Redémarre uniquement infrastructure
./kw.ps1 restart app        # Redémarre uniquement application
```

### Monitoring

```powershell
./kw.ps1 status             # Affiche statut de tous les services
./kw.ps1 ps                 # Alias de status

./kw.ps1 logs app           # Voir logs du backend (Ctrl+C pour quitter)
./kw.ps1 logs worker        # Voir logs du worker
./kw.ps1 logs neo4j         # Voir logs Neo4j
./kw.ps1 logs frontend      # Voir logs frontend Next.js
```

### Informations

```powershell
./kw.ps1 info               # Affiche toutes les URLs + credentials
```

**Sortie de `./kw.ps1 info` :**
```
URLs d'Acces
============

Application:
  Frontend Next.js  : http://localhost:3000
  API Backend       : http://localhost:8000
  API Documentation : http://localhost:8000/docs
  Streamlit UI      : http://localhost:8501

Infrastructure:
  Neo4j Browser     : http://localhost:7474
    Login           : neo4j
    Password        : graphiti_neo4j_pass

  Qdrant Dashboard  : http://localhost:6333/dashboard
    (pas d'auth)

  Redis             : localhost:6379
    (pas d'auth)

Configuration
=============
  MAX_WORKERS       : 30 (parallelisation vision GPT-4o)
```

### Nettoyage

```powershell
./kw.ps1 clean              # Purge TOUS les volumes et containers (DANGER!)
                            # Demande confirmation (tapez OUI)
                            # PRESERVE data/extraction_cache/
```

**⚠️ ATTENTION** : `clean` supprime toutes les données (Neo4j, Qdrant, Redis) mais **préserve** les caches d'extraction (`data/extraction_cache/`) qui sont précieux.

### Aide

```powershell
./kw.ps1 help               # Affiche l'aide complète
```

## 🏗️ Architecture Docker

Le projet utilise une architecture **multi-fichiers** depuis octobre 2025 :

### Fichiers Docker Compose

1. **`docker-compose.infra.yml`** : Infrastructure stateful (rarement redémarrée)
   - Qdrant (vector store)
   - Redis (cache + queue)
   - Neo4j (knowledge graph)

2. **`docker-compose.yml`** : Application stateless (fréquemment redémarrée en dev)
   - App (backend FastAPI)
   - Worker (ingestion RQ)
   - Frontend (Next.js)
   - UI (Streamlit legacy)

3. **`.env`** : Configuration unifiée
   ```bash
   COMPOSE_FILE=docker-compose.infra.yml:docker-compose.yml
   MAX_WORKERS=30
   ```

### Avantages de l'Architecture Séparée

✅ **Rapidité** : Redémarrage app uniquement (5s) vs infra+app (30s)
✅ **Sécurité** : Pas de perte de données lors des redémarrages dev
✅ **Flexibilité** : Gestion indépendante infra/app

## 🔧 Workflow Développement Typique

```powershell
# Démarrage journée (une fois)
./kw.ps1 start infra        # Démarre Qdrant, Redis, Neo4j

# Développement (plusieurs fois par jour)
./kw.ps1 start app          # Démarre/redémarre l'application
./kw.ps1 logs app           # Voir logs en temps réel
./kw.ps1 restart app        # Redémarre après changements code

# Fin de journée
./kw.ps1 stop               # Arrête tout
```

## 📊 Services et Ports

| Service | Port(s) | Description |
|---------|---------|-------------|
| **Frontend** | 3000 | Interface Next.js principale |
| **API** | 8000 | Backend FastAPI + Swagger docs |
| **Streamlit** | 8501 | Interface legacy |
| **Neo4j** | 7474, 7687 | Knowledge Graph (Browser + Bolt) |
| **Qdrant** | 6333, 6334 | Vector Store (HTTP + gRPC) |
| **Redis** | 6379 | Cache + Queue |
| **Worker** | 5679 | Ingestion worker (debug port) |

## 🔑 Credentials par Défaut (Dev)

**Neo4j** :
- URL : http://localhost:7474
- Login : `neo4j`
- Password : `graphiti_neo4j_pass`

**Qdrant** : Pas d'authentification (dashboard ouvert)

**Redis** : Pas d'authentification

**API** : Pas d'authentification en dev (admin créé automatiquement)

## 🐛 Troubleshooting

### Les services ne démarrent pas

```powershell
# Vérifier les logs
./kw.ps1 logs app

# Vérifier le statut
./kw.ps1 status

# En dernier recours : nettoyage complet
./kw.ps1 clean
./kw.ps1 start
```

### Neo4j n'apparaît pas

Vérifiez que le `.env` contient bien :
```bash
COMPOSE_FILE=docker-compose.infra.yml:docker-compose.yml
```

### Modèle d'embeddings corrompu

```powershell
# Arrêter tout
./kw.ps1 stop

# Supprimer le modèle corrompu
rm -r data/models/hub/models--intfloat--multilingual-e5-base

# Redémarrer (le modèle se retéléchargera)
./kw.ps1 start
```

## 🔗 Voir Aussi

- `CLAUDE.md` : Instructions complètes pour Claude Code
- `DOCKER_SETUP.md` : Documentation détaillée architecture Docker
- `README.md` : README principal du projet
- `doc/` : Documentation complète OSMOSE

---

*Script créé le 2025-11-15 pour simplifier la gestion Docker de KnowWhere/OSMOSE*
