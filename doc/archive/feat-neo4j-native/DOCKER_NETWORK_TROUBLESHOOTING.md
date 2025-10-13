# Résolution Problèmes Réseau Docker - SAP KB

**Date** : 10 octobre 2025
**Problème** : Erreur DNS "Failed to DNS resolve address neo4j:7687"
**Statut** : ✅ RÉSOLU

---

## 🐛 Symptômes

### Erreurs observées

```
ERROR: Failed to DNS resolve address neo4j:7687: [Errno -2] Name or service not known
ECONNREFUSED 172.18.0.4:8000
```

### Services affectés

- ❌ Backend API (`app`) → Ne peut pas accéder à Neo4j
- ❌ Worker d'ingestion (`ingestion-worker`) → Crash lors de l'import PPTX
- ❌ Frontend Next.js (SSR) → Erreur 500 sur pages admin

---

## 🔍 Cause Racine

**Problème** : Services sur des réseaux Docker différents

Les fichiers `docker-compose.yml` et `docker-compose.infra.yml` définissaient le réseau différemment :

```yaml
# docker-compose.infra.yml ✅
networks:
  knowbase_net:
    name: knowbase_network  # Nom explicite

# docker-compose.yml ❌ (AVANT)
networks:
  knowbase_net:
    driver: bridge  # Pas de nom → Docker crée "sap_kb_knowbase_net"
```

**Résultat** :
- Neo4j → `knowbase_network`
- App, Worker, Redis, Qdrant → `sap_kb_knowbase_net` ❌

Les services ne pouvaient pas communiquer entre eux.

---

## ✅ Solution Appliquée

### 1. Unifier le nom de réseau

**Fichier** : `docker-compose.yml`

```yaml
networks:
  knowbase_net:
    name: knowbase_network  # ← AJOUTÉ
    driver: bridge
```

### 2. Connecter manuellement les services existants

Pour les containers déjà créés, il faut les reconnecter :

```bash
# Connecter tous les services au bon réseau
docker network connect knowbase_network knowbase-app
docker network connect knowbase_network knowbase-worker
docker network connect knowbase_network knowbase-frontend
docker network connect knowbase_network knowbase-redis
docker network connect knowbase_network knowbase-qdrant

# Redémarrer les services
docker-compose restart app ingestion-worker
```

### 3. Ou utiliser le script automatique

```bash
# Exécuter le script de correction
bash scripts/fix-docker-network.sh
```

---

## 🧪 Vérification

### Vérifier que tous les services sont sur le même réseau

```bash
# Vérifier chaque service
for service in app worker frontend neo4j redis qdrant; do
  echo "=== knowbase-$service ==="
  docker inspect knowbase-$service --format '{{range $key, $value := .NetworkSettings.Networks}}{{$key}} {{end}}'
done
```

**Résultat attendu** : Tous doivent afficher `knowbase_network`

### Tester la connectivité Neo4j

```bash
# Depuis le container app
docker exec knowbase-app nc -zv neo4j 7687
# Doit afficher : neo4j (7687) open

# Vérifier les logs (pas d'erreurs DNS)
docker-compose logs app --tail=50 | grep -E "ERROR|DNS"
# Ne doit PAS contenir "Failed to DNS resolve"
```

### Tester l'import PPTX

```bash
# Via l'interface web
http://localhost:3000/documents/import

# Vérifier les logs worker (pas d'erreurs)
docker-compose logs ingestion-worker -f
```

---

## 📊 Services et Leurs Réseaux

| Service | Container | Réseau Requis | Communique Avec |
|---------|-----------|---------------|-----------------|
| **App** | knowbase-app | knowbase_network | Neo4j, Redis, Qdrant |
| **Worker** | knowbase-worker | knowbase_network | Neo4j, Redis, Qdrant |
| **Frontend** | knowbase-frontend | knowbase_network | App (SSR calls) |
| **Neo4j** | knowbase-neo4j | knowbase_network | App, Worker |
| **Redis** | knowbase-redis | knowbase_network | App, Worker |
| **Qdrant** | knowbase-qdrant | knowbase_network | App, Worker |

---

## 🚨 Prévention

### Recréer tous les services (méthode propre)

Si vous voulez nettoyer complètement et recréer :

```bash
# ATTENTION : Cela supprime tous les containers

# 1. Arrêter tous les services
docker-compose down
docker-compose -f docker-compose.infra.yml down

# 2. Supprimer l'ancien réseau
docker network rm sap_kb_knowbase_net 2>/dev/null || true

# 3. Recréer avec la bonne config
docker-compose -f docker-compose.infra.yml up -d
docker-compose up -d
```

### Vérifier lors du démarrage

Ajoutez cette vérification dans vos scripts de déploiement :

```bash
# Vérifier que tous les services sont sur le bon réseau
EXPECTED_NETWORK="knowbase_network"

for service in knowbase-app knowbase-worker knowbase-neo4j; do
  network=$(docker inspect $service --format '{{range $key, $value := .NetworkSettings.Networks}}{{$key}}{{end}}')
  if ! echo "$network" | grep -q "$EXPECTED_NETWORK"; then
    echo "❌ $service n'est PAS sur $EXPECTED_NETWORK"
    exit 1
  fi
done

echo "✅ Tous les services sont sur le bon réseau"
```

---

## 📝 Problèmes Connexes Résolus

### 1. Frontend SSR → Backend (ECONNREFUSED)

**Problème** : Le frontend appelait `localhost:8000` depuis le container Docker.

**Solution** : URLs différentes pour client vs serveur

```typescript
// frontend/src/lib/api.ts
const isServer = typeof window === 'undefined'
const API_BASE_URL = isServer
  ? 'http://app:8000'        // SSR (container Docker)
  : 'http://localhost:8000'  // Client (navigateur)
```

### 2. Pages Admin Vides (500 Error)

**Problème** : Backend ne pouvait pas accéder à Neo4j → erreur 500 sur `/api/entity-types`

**Solution** : Après connexion au bon réseau, toutes les pages admin fonctionnent.

---

## 🔗 Commits Associés

```
10895dd fix(docker): Unifier réseau Docker pour communication inter-services
8ed909c fix(frontend): Corriger appels API SSR avec URLs Docker internes
```

---

## 📞 Support

Si le problème persiste après avoir suivi ce guide :

1. Vérifier les logs de chaque service
2. Vérifier la connectivité réseau : `docker network inspect knowbase_network`
3. Vérifier les variables d'environnement : `docker exec knowbase-app env | grep NEO4J`

---

**Dernière mise à jour** : 2025-10-10
**Testé avec** : Docker Compose v2.x, Neo4j 5.26.0
