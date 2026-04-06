# Docker Setup - Infrastructure Séparée

**Architecture** : Séparation Infrastructure (stateful) / Application (stateless)

---

## 🎯 Principe

L'architecture Docker a été restructurée pour séparer :

### Infrastructure (Stateful - Rarement redémarrée)
- **Qdrant** : Base vectorielle
- **Redis** : Cache & Queue
- **Neo4j** : Knowledge Graph
- **PostgreSQL** : Metadata (futur)

### Application (Stateless - Fréquemment redémarrée)
- **App** : Backend FastAPI
- **Worker** : Ingestion worker (RQ)
- **Frontend** : Interface Next.js
- **UI** : Interface Streamlit (legacy)

---

## 🚀 Démarrage Rapide

### 1. Démarrer Infrastructure (1 fois)

```bash
# Démarrer tous les services infrastructure
./scripts/start-infra.sh

# Ou manuellement
docker-compose -f docker-compose.infra.yml up -d
```

**Services disponibles** :
- Qdrant Dashboard : http://localhost:6333/dashboard
- Neo4j Browser : http://localhost:7474 (user: `neo4j`, pass: voir `.env`)
- Redis : `localhost:6379`

### 2. Démarrer Application

```bash
# Démarrer tous les services applicatifs
./scripts/start-app.sh

# Ou manuellement
docker-compose -f docker-compose.app.yml up -d
```

**Services disponibles** :
- API Backend : http://localhost:8000
- API Docs : http://localhost:8000/docs
- Frontend Next.js : http://localhost:3000
- Streamlit UI : http://localhost:8501

---

## 🔄 Redémarrages Fréquents (Développement)

### Redémarrer Backend uniquement

```bash
# Via script (recommandé)
./scripts/restart-app.sh app

# Ou manuellement
docker-compose -f docker-compose.app.yml restart app
```

### Redémarrer Worker uniquement

```bash
./scripts/restart-app.sh worker

# Ou
docker-compose -f docker-compose.app.yml restart ingestion-worker
```

### Redémarrer Frontend uniquement

```bash
./scripts/restart-app.sh frontend
```

### Redémarrer toute l'application (sans infrastructure)

```bash
./scripts/restart-app.sh

# Ou
docker-compose -f docker-compose.app.yml restart
```

**Avantage** : Infrastructure (Qdrant, Redis, Neo4j) **reste active** → pas de perte de données, pas de latence redémarrage.

---

## 🛑 Arrêter les Services

### Arrêter application uniquement

```bash
docker-compose -f docker-compose.app.yml down
```

### Arrêter tout (app + infrastructure)

```bash
./scripts/stop-all.sh

# Ou manuellement
docker-compose -f docker-compose.app.yml down
docker-compose -f docker-compose.infra.yml down
```

---

## 📊 Monitoring & Logs

### Voir statut services

```bash
# Infrastructure
docker-compose -f docker-compose.infra.yml ps

# Application
docker-compose -f docker-compose.app.yml ps

# Tous
docker ps
```

### Voir logs

```bash
# Logs backend en temps réel
docker-compose -f docker-compose.app.yml logs -f app

# Logs worker
docker-compose -f docker-compose.app.yml logs -f ingestion-worker

# Logs Neo4j
docker-compose -f docker-compose.infra.yml logs -f neo4j

# Tous les logs application
docker-compose -f docker-compose.app.yml logs -f
```

---

## 🔧 Configuration

### Variables d'environnement

Copier `.env.example` vers `.env` et configurer :

```bash
cp .env.example .env
```

**Variables clés** :
```env
# API Keys
OPENAI_API_KEY=your_key
ANTHROPIC_API_KEY=your_key

# Neo4j
NEO4J_PASSWORD=change_me_in_production

# Ports
APP_PORT=8000
FRONTEND_PORT=3000
APP_UI_PORT=8501
```

---

## 🧪 Tests Infrastructure

### Vérifier Qdrant

```bash
curl http://localhost:6333/collections
```

### Vérifier Redis

```bash
docker exec knowbase-redis redis-cli ping
# Attendu: PONG
```

### Vérifier Neo4j

```bash
# Browser UI
open http://localhost:7474

# Ou via Cypher shell
docker exec -it knowbase-neo4j cypher-shell -u neo4j -p neo4j_password
```

### Vérifier Backend

```bash
curl http://localhost:8000/status
```

---

## 🐳 Commandes Utiles

### Rebuild image sans cache

```bash
# Backend
docker-compose -f docker-compose.app.yml build --no-cache app

# Frontend
docker-compose -f docker-compose.app.yml build --no-cache frontend
```

### Accéder à un container

```bash
# Backend
docker exec -it knowbase-app bash

# Worker
docker exec -it knowbase-worker bash

# Neo4j
docker exec -it knowbase-neo4j bash
```

### Nettoyer volumes (⚠️ SUPPRIME DONNÉES)

```bash
# Supprimer volumes infrastructure (Qdrant, Redis, Neo4j)
docker-compose -f docker-compose.infra.yml down -v

# Supprimer volumes application
docker-compose -f docker-compose.app.yml down -v
```

---

## 🔄 Workflow Développement Typique

```bash
# 1. Démarrer infra (1 fois le matin)
./scripts/start-infra.sh

# 2. Démarrer app
./scripts/start-app.sh

# 3. Développer code...

# 4. Redémarrer backend après modification
./scripts/restart-app.sh app

# 5. Voir logs
docker-compose -f docker-compose.app.yml logs -f app

# 6. Fin de journée
./scripts/stop-all.sh
```

---

## ⚙️ Ancien vs Nouveau

### Ancien (`docker-compose.yml` monolithique)

```bash
# Redémarrer backend
docker-compose restart app
# ❌ Redémarre AUSSI Qdrant, Redis → lent, inutile
```

### Nouveau (séparé)

```bash
# Redémarrer backend
docker-compose -f docker-compose.app.yml restart app
# ✅ Infrastructure reste active → rapide, propre
```

**Gain temps** : 3-5x plus rapide (5s vs 20-30s)

---

## 📚 Fichiers Docker

```
.
├── docker-compose.infra.yml   # Infrastructure (Qdrant, Redis, Neo4j, Postgres)
├── docker-compose.app.yml     # Application (App, Worker, Frontend, UI)
├── docker-compose.yml         # DEPRECATED (ancien monolithique)
├── .env.example               # Template variables
├── scripts/
│   ├── start-infra.sh         # Démarrer infrastructure
│   ├── start-app.sh           # Démarrer application
│   ├── restart-app.sh         # Redémarrer app (ou service spécifique)
│   └── stop-all.sh            # Arrêter tout
```

---

## ⚠️ Notes Importantes

1. **Infrastructure DOIT être démarrée AVANT application**
   ```bash
   # Ordre correct
   docker-compose -f docker-compose.infra.yml up -d  # 1️⃣
   docker-compose -f docker-compose.app.yml up -d    # 2️⃣
   ```

2. **Network partagé** : `knowbase_network` créé par `docker-compose.infra.yml`

3. **Volumes nommés** : Facilite identification (`knowbase_qdrant_data`, etc.)

4. **Healthchecks** : Tous services ont healthchecks pour vérifier statut

5. **Graceful shutdown** : `stop_grace_period` permet arrêt propre (worker finish jobs)

---

## 🆘 Troubleshooting

### "Network not found"

```bash
# Créer network manuellement
docker network create knowbase_network
```

### "Port already in use"

```bash
# Vérifier services actifs
docker ps

# Arrêter ancien docker-compose.yml si existant
docker-compose down
```

### "Cannot connect to Neo4j"

```bash
# Vérifier Neo4j démarré
docker-compose -f docker-compose.infra.yml ps

# Voir logs Neo4j
docker-compose -f docker-compose.infra.yml logs neo4j

# Attendre healthcheck (60s au démarrage)
docker inspect knowbase-neo4j | grep -A 10 Health
```

---

**Version** : 2.0 (Neo4j Native)
**Date** : 2025-10-03
