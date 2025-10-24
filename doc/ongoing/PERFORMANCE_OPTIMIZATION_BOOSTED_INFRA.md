# Optimisation Performance - Infrastructure Boostée

**Date:** 2025-10-24
**Objectif:** Maximiser les performances d'ingestion et de traitement sur infrastructure AWS boostée

---

## 🎯 Vue d'Ensemble

Ce document identifie **tous les paramètres de parallélisation** et d'optimisation pour améliorer significativement les temps de traitement sur une infrastructure EC2 plus puissante.

### Gains Attendus

| Configuration | Temps Ingestion (10 docs) | Amélioration |
|---------------|---------------------------|--------------|
| **Actuelle** (t3.2xlarge) | ~120-180s | Baseline |
| **Optimisée** (c5.4xlarge) | ~40-60s | **3x plus rapide** |
| **Maximale** (c5.9xlarge) | ~20-30s | **6x plus rapide** |

---

## 📊 Analyse Configuration Actuelle

### 1. Infrastructure EC2

**Actuel:**
```yaml
InstanceType: t3.2xlarge
- 8 vCPU
- 32 GB RAM
- Réseau: Up to 5 Gbps
```

**Goulots d'étranglement identifiés:**
- ❌ t3 = "burstable" (performance CPU non constante)
- ❌ Réseau limité à 5 Gbps
- ❌ Pas d'EBS optimisé par défaut

### 2. Conteneurs Docker

**Actuel:**

| Service | Workers/vCPU | RAM | Limites Actuelles |
|---------|--------------|-----|-------------------|
| **app** (FastAPI) | 4 workers Uvicorn | 2-4 GB | ❌ 4 workers pour 8 vCPU (50% utilisation) |
| **ingestion-worker** (RQ) | 4 concurrent jobs | 4-6 GB | ❌ Traitement séquentiel par worker |
| **neo4j** | Heap 4 GB | 1-4 GB heap | ⚠️ Pagecache 2 GB (peut être augmenté) |

**Problèmes:**
- Worker RQ = **1 seul processus Python** avec `WORKER_CONCURRENCY=4` (jobs RQ séquentiels !)
- Pas de parallélisation réelle au niveau ingestion
- Uvicorn workers = bon pour requêtes API, mais n'accélère pas l'ingestion

### 3. Architecture Agentique (OSMOSE)

**Actuel:**
- Traitement **séquentiel** des chunks
- Pas d'utilisation de `asyncio.gather()` ou `ThreadPoolExecutor`
- Appels LLM synchrones (un par un)

---

## 🚀 Optimisations Recommandées

### Niveau 1: Optimisations Sans Code (Facile) ⭐⭐⭐

#### A. Instance EC2 Plus Puissante

**Recommandé pour tests de charge:**
```yaml
InstanceType: c5.4xlarge  # Compute-optimized
- 16 vCPU (vs 8)
- 32 GB RAM
- Réseau: Up to 10 Gbps
- EBS optimisé inclus
- Coût: ~$0.68/heure (vs $0.33 pour t3.2xlarge)
```

**Pour charge maximale:**
```yaml
InstanceType: c5.9xlarge  # Heavy workload
- 36 vCPU
- 72 GB RAM
- Réseau: 10 Gbps
- Coût: ~$1.53/heure
```

**Action:** Modifier `cloudformation/knowbase-stack.yaml`
```yaml
AllowedValues:
  - t3.xlarge
  - t3.2xlarge
  - m5.2xlarge
  - c5.4xlarge  # ← RECOMMANDÉ
  - c5.9xlarge  # Pour charge maximale
  - c5.12xlarge # Pour tests extrêmes
```

#### B. Augmenter Workers FastAPI

**Actuel:** `--workers 4`
**Optimisé:** `--workers 12` (pour c5.4xlarge avec 16 vCPU)

**Fichier:** `docker-compose.ecr.yml`
```yaml
app:
  command: python -m uvicorn main:app --host 0.0.0.0 --port 8000 --workers 12
  deploy:
    resources:
      limits:
        cpus: '8.0'  # Augmenter de 2.0 → 8.0
        memory: 8G   # Augmenter de 4G → 8G
```

**Formule:** `workers = (2 x vCPU) + 1`
- c5.4xlarge (16 vCPU) → **12-16 workers**
- c5.9xlarge (36 vCPU) → **20-24 workers**

#### C. Multiplier Workers RQ Ingestion

**CRITIQUE:** Actuellement il n'y a qu'**1 seul worker RQ** !

**Solution:** Utiliser Docker Compose `deploy.replicas`

**Fichier:** `docker-compose.ecr.yml`
```yaml
ingestion-worker:
  # ... config existante ...
  deploy:
    replicas: 8  # ← NOUVEAU: 8 workers RQ en parallèle
    resources:
      limits:
        cpus: '12.0'  # 16 vCPU total / 8 workers = ~1.5 vCPU par worker
        memory: 12G   # 96 GB total / 8 workers = 12 GB par worker
```

**Impact:** Passer de **1 document traité à la fois** à **8 documents en parallèle** !

**Configuration par Instance:**

| Instance | vCPU | Replicas Recommandé | Jobs Parallèles |
|----------|------|---------------------|-----------------|
| t3.2xlarge | 8 | 4 | 4 documents |
| c5.4xlarge | 16 | 8 | 8 documents |
| c5.9xlarge | 36 | 16 | 16 documents |

#### D. Optimiser Neo4j Memory

**Actuel:**
```yaml
neo4j:
  environment:
    - NEO4J_server_memory_heap_initial__size=1g
    - NEO4J_server_memory_heap_max__size=4g
    - NEO4J_server_memory_pagecache_size=2g
```

**Optimisé pour c5.4xlarge (32 GB RAM):**
```yaml
neo4j:
  environment:
    - NEO4J_server_memory_heap_initial__size=4g
    - NEO4J_server_memory_heap_max__size=8g
    - NEO4J_server_memory_pagecache_size=8g  # ← CRITIQUE pour perf
```

**Formule:** Pour RAM totale = X
- Heap: 25% de X
- Pagecache: 50% de X
- OS: 25% de X

#### E. Variables d'Environnement Ingestion

**Fichier:** `.env.production`

**Ajouter:**
```bash
# =====================================================
# PERFORMANCE OPTIMIZATION
# =====================================================

# RQ Worker
WORKER_CONCURRENCY=4          # Jobs par worker (garder 4)
RQ_WORKER_REPLICAS=8          # Nombre de workers RQ (NOUVEAU)

# Uvicorn FastAPI
UVICORN_WORKERS=12            # Workers FastAPI (2*vCPU + 1)

# LLM Rate Limits (augmenter pour infra boostée)
OPENAI_MAX_RPM=500            # Requêtes par minute OpenAI
ANTHROPIC_MAX_RPM=100         # Requêtes par minute Anthropic

# Neo4j Connection Pool
NEO4J_MAX_CONNECTION_POOL_SIZE=100  # Connexions simultanées (default: 50)

# Qdrant Batch Size
QDRANT_BATCH_SIZE=100         # Upsert batch (default: 50)
QDRANT_PARALLEL_UPLOADS=4     # Uploads parallèles (NOUVEAU)
```

---

### Niveau 2: Optimisations Code (Moyen) ⭐⭐

#### A. Paralléliser Appels LLM dans Agents

**Fichier:** `src/knowbase/agents/supervisor/supervisor.py`

**Actuel:** Appels séquentiels
```python
for chunk in chunks:
    result = await agent.process(chunk)  # Séquentiel !
```

**Optimisé:** Utiliser `asyncio.gather()`
```python
import asyncio

# Traiter tous les chunks en parallèle (limité par rate limits)
tasks = [agent.process(chunk) for chunk in chunks]
results = await asyncio.gather(*tasks)
```

**Impact:** Divise le temps d'extraction par le nombre de chunks (ex: 10 chunks = 10x plus rapide)

#### B. Ajouter ThreadPoolExecutor pour I/O

**Fichier:** `src/knowbase/ingestion/osmose_agentique.py`

**Pour les opérations I/O (Neo4j, Qdrant):**
```python
from concurrent.futures import ThreadPoolExecutor

class OsmoseAgentiqueService:
    def __init__(self):
        self.executor = ThreadPoolExecutor(max_workers=8)

    async def _parallel_upsert(self, chunks):
        loop = asyncio.get_event_loop()
        tasks = [
            loop.run_in_executor(
                self.executor,
                upsert_chunks,
                batch
            )
            for batch in batched(chunks, 100)
        ]
        await asyncio.gather(*tasks)
```

**Impact:** Upload vers Qdrant 4-8x plus rapide

#### C. Batch Processing Neo4j

**Fichier:** `src/knowbase/ontology/neo4j_schema.py`

**Actuel:** Requêtes une par une
**Optimisé:** Utiliser `UNWIND` pour batch inserts

```cypher
UNWIND $entities AS entity
MERGE (e:Entity {canonical_name: entity.name, tenant_id: $tenant_id})
SET e += entity.properties
```

**Impact:** 10-20x plus rapide pour création de concepts

---

### Niveau 3: Optimisations Architecture (Avancé) ⭐

#### A. Utiliser RQ Burst Workers

**Fichier:** `src/knowbase/ingestion/queue/worker.py`

**Ajouter support multi-worker:**
```python
import os

def run_worker(*, queue_name: str | None = None) -> None:
    # Lire nombre de workers depuis env
    num_workers = int(os.getenv("RQ_WORKER_REPLICAS", "1"))

    # Démarrer plusieurs workers dans des processus séparés
    if num_workers > 1:
        from multiprocessing import Process
        processes = []
        for i in range(num_workers):
            p = Process(target=_run_single_worker, args=(queue_name, i))
            p.start()
            processes.append(p)

        for p in processes:
            p.join()
    else:
        _run_single_worker(queue_name, 0)
```

#### B. Implémenter Queue Priority

**Pour traiter les petits documents en priorité:**

```python
from rq import Queue

# Créer queues avec priorités
high_priority = Queue("high", connection=redis)
low_priority = Queue("low", connection=redis)

# Router selon taille document
if doc_size < 1_000_000:  # < 1 MB
    high_priority.enqueue(process_document, doc)
else:
    low_priority.enqueue(process_document, doc)
```

#### C. Ajouter Caching Redis Intelligent

**Mettre en cache les résultats d'extraction:**

```python
import hashlib
import redis

def get_cached_extraction(text: str, redis_client: redis.Redis):
    cache_key = f"extraction:{hashlib.sha256(text.encode()).hexdigest()}"
    cached = redis_client.get(cache_key)
    if cached:
        return json.loads(cached)
    return None

def cache_extraction(text: str, result: dict, redis_client: redis.Redis):
    cache_key = f"extraction:{hashlib.sha256(text.encode()).hexdigest()}"
    redis_client.setex(cache_key, 86400, json.dumps(result))  # 24h TTL
```

---

## 📋 Configuration Recommandée par Scénario

### Scénario 1: Tests Performance Standard

**Instance:** `c5.4xlarge` (16 vCPU, 32 GB RAM)
**Coût:** ~$0.68/heure

**docker-compose.ecr.yml:**
```yaml
app:
  command: python -m uvicorn main:app --host 0.0.0.0 --port 8000 --workers 12
  deploy:
    resources:
      limits:
        cpus: '8.0'
        memory: 8G

ingestion-worker:
  deploy:
    replicas: 8
    resources:
      limits:
        cpus: '1.5'  # 12 vCPU / 8 workers
        memory: 3G

neo4j:
  environment:
    - NEO4J_server_memory_heap_max__size=8g
    - NEO4J_server_memory_pagecache_size=8g
```

**.env.production:**
```bash
UVICORN_WORKERS=12
RQ_WORKER_REPLICAS=8
OPENAI_MAX_RPM=500
NEO4J_MAX_CONNECTION_POOL_SIZE=100
QDRANT_BATCH_SIZE=100
```

**Gains attendus:** 3-4x plus rapide

---

### Scénario 2: Charge Maximale

**Instance:** `c5.9xlarge` (36 vCPU, 72 GB RAM)
**Coût:** ~$1.53/heure

**docker-compose.ecr.yml:**
```yaml
app:
  command: python -m uvicorn main:app --host 0.0.0.0 --port 8000 --workers 24
  deploy:
    resources:
      limits:
        cpus: '16.0'
        memory: 16G

ingestion-worker:
  deploy:
    replicas: 16
    resources:
      limits:
        cpus: '2.0'  # 32 vCPU / 16 workers
        memory: 4G

neo4j:
  environment:
    - NEO4J_server_memory_heap_max__size=16g
    - NEO4J_server_memory_pagecache_size=24g
```

**.env.production:**
```bash
UVICORN_WORKERS=24
RQ_WORKER_REPLICAS=16
OPENAI_MAX_RPM=1000
NEO4J_MAX_CONNECTION_POOL_SIZE=200
QDRANT_BATCH_SIZE=200
```

**Gains attendus:** 6-8x plus rapide

---

### Scénario 3: Tests Extrêmes (Budget Illimité)

**Instance:** `c5.12xlarge` (48 vCPU, 96 GB RAM)
**Coût:** ~$2.04/heure

**+ Ajouter instances séparées:**
- Neo4j sur instance dédiée (r5.2xlarge - RAM optimized)
- Qdrant sur instance dédiée (c5.2xlarge)
- Redis sur instance dédiée (r5.large)

**Gains attendus:** 10-12x plus rapide

---

## 🔧 Guide d'Implémentation

### Étape 1: Modifications CloudFormation

**Fichier:** `cloudformation/knowbase-stack.yaml`

```yaml
Parameters:
  InstanceType:
    Default: c5.4xlarge  # Changer de t3.2xlarge
    AllowedValues:
      - t3.xlarge
      - t3.2xlarge
      - m5.2xlarge
      - c5.4xlarge  # ← AJOUTER
      - c5.9xlarge  # ← AJOUTER
```

### Étape 2: Modifications docker-compose.ecr.yml

**Ajouter replicas pour ingestion-worker:**

```yaml
ingestion-worker:
  # ... configuration existante ...
  environment:
    # ... variables existantes ...
    WORKER_CONCURRENCY: "4"  # Garder 4 jobs par worker
  deploy:
    replicas: 8  # ← AJOUTER: 8 workers en parallèle
    resources:
      limits:
        cpus: '1.5'  # Ajuster selon instance
        memory: 3G
      reservations:
        cpus: '1.0'
        memory: 2G
```

**Augmenter workers Uvicorn:**

```yaml
app:
  command: python -m uvicorn main:app --host 0.0.0.0 --port 8000 --workers 12  # 4 → 12
  deploy:
    resources:
      limits:
        cpus: '8.0'  # 2.0 → 8.0
        memory: 8G   # 4G → 8G
```

**Optimiser Neo4j:**

```yaml
neo4j:
  environment:
    # ... autres variables ...
    - NEO4J_server_memory_heap_initial__size=4g  # 1g → 4g
    - NEO4J_server_memory_heap_max__size=8g      # 4g → 8g
    - NEO4J_server_memory_pagecache_size=8g      # 2g → 8g
```

### Étape 3: Modifications .env.production

**Ajouter au fichier `.env.production`:**

```bash
# =====================================================
# PERFORMANCE OPTIMIZATION (Infrastructure Boostée)
# =====================================================

# Uvicorn Workers (FastAPI)
UVICORN_WORKERS=12

# RQ Workers (Ingestion)
RQ_WORKER_REPLICAS=8
WORKER_CONCURRENCY=4

# LLM Rate Limits
OPENAI_MAX_RPM=500
ANTHROPIC_MAX_RPM=100

# Neo4j Connection Pool
NEO4J_MAX_CONNECTION_POOL_SIZE=100

# Qdrant Optimization
QDRANT_BATCH_SIZE=100
QDRANT_PARALLEL_UPLOADS=4
```

### Étape 4: Déploiement

```powershell
# 1. Build et push images (si pas déjà fait)
.\scripts\aws\build-and-push-ecr.ps1

# 2. Détruire stack existant
.\scripts\aws\destroy-cloudformation.ps1 -StackName "knowbase-test"

# 3. Déployer avec nouvelle config
.\scripts\aws\deploy-cloudformation.ps1 `
    -StackName "knowbase-perf-test" `
    -InstanceType "c5.4xlarge" `
    -KeyPairName "my-key" `
    -KeyPath ".\my-key.pem"
```

### Étape 5: Tests de Performance

**Test baseline (1 document):**
```bash
time curl -X POST http://<IP_EC2>:8000/ingest/pptx \
  -F "file=@test-doc.pptx"
```

**Test charge (10 documents en parallèle):**
```bash
for i in {1..10}; do
  curl -X POST http://<IP_EC2>:8000/ingest/pptx \
    -F "file=@test-doc-$i.pptx" &
done
wait
```

**Monitoring:**
```bash
# Voir utilisation CPU/RAM
ssh ubuntu@<IP_EC2> "docker stats"

# Voir logs workers
ssh ubuntu@<IP_EC2> "docker-compose logs -f ingestion-worker"

# Voir queue Redis
ssh ubuntu@<IP_EC2> "docker exec knowbase-redis redis-cli LLEN rq:queue:default"
```

---

## 📊 Métriques à Surveiller

### 1. Redis Queue

```bash
# Nombre de jobs en attente
LLEN rq:queue:default

# Nombre de jobs en cours
LLEN rq:queue:default:active

# Nombre de jobs échoués
LLEN rq:queue:failed
```

### 2. Neo4j Performance

```cypher
// Nombre de concepts créés
MATCH (c:CanonicalConcept) WHERE c.tenant_id = 'default' RETURN count(c)

// Temps moyen des requêtes
CALL dbms.listQueries() YIELD query, elapsedTimeMillis
RETURN query, elapsedTimeMillis ORDER BY elapsedTimeMillis DESC LIMIT 10
```

### 3. Utilisation Ressources

```bash
# CPU par conteneur
docker stats --format "table {{.Name}}\t{{.CPUPerc}}\t{{.MemUsage}}"

# Réseau
docker stats --format "table {{.Name}}\t{{.NetIO}}"
```

---

## 💰 Analyse Coûts

### Coûts Horaires EC2 (eu-west-1)

| Instance | vCPU | RAM | Coût/h | Coût/jour (8h) | Gain Perf |
|----------|------|-----|--------|----------------|-----------|
| t3.2xlarge | 8 | 32 GB | $0.33 | $2.64 | 1x (baseline) |
| c5.4xlarge | 16 | 32 GB | $0.68 | $5.44 | 3-4x |
| c5.9xlarge | 36 | 72 GB | $1.53 | $12.24 | 6-8x |
| c5.12xlarge | 48 | 96 GB | $2.04 | $16.32 | 10-12x |

**ROI:** Si vous traitez 100 documents/jour
- Baseline (t3.2xlarge): 300 minutes = $1.65
- Optimisé (c5.4xlarge): 75 minutes = $0.85 (**économie de 48%**)

---

## 🚨 Limites et Précautions

### 1. Rate Limits LLM

**OpenAI:**
- GPT-4: 500 RPM (tier 1), 10,000 RPM (tier 5)
- GPT-4o-mini: 30,000 RPM

**Solution:** Surveiller et ajuster `OPENAI_MAX_RPM` dans `.env`

### 2. Mémoire Neo4j

**Symptôme:** `OutOfMemoryError` dans logs Neo4j

**Solution:** Augmenter heap ou pagecache selon erreur:
- Heap errors → Augmenter `heap_max_size`
- Page cache errors → Augmenter `pagecache_size`

### 3. Saturation Redis

**Symptôme:** Jobs en queue augmentent sans être traités

**Solution:**
- Augmenter nombre de workers RQ (replicas)
- Vérifier que workers ne crashent pas (logs)

---

## ✅ Checklist de Validation

Avant de considérer l'optimisation réussie :

- [ ] CPU utilisation > 70% sur tous les cores (pas seulement 1-2)
- [ ] Workers RQ tous actifs (`docker ps` montre N replicas)
- [ ] Queue Redis se vide rapidement (< 30s par document)
- [ ] Aucun timeout LLM (vérifier logs)
- [ ] Neo4j query time < 100ms (vérifier `dbms.listQueries()`)
- [ ] Qdrant upsert time < 500ms par batch
- [ ] Temps ingestion total divisé par ≥3

---

## 📚 Ressources

- [AWS EC2 Instance Types](https://aws.amazon.com/ec2/instance-types/)
- [Neo4j Memory Configuration](https://neo4j.com/docs/operations-manual/current/performance/memory-configuration/)
- [RQ Worker Documentation](https://python-rq.org/docs/workers/)
- [Uvicorn Deployment](https://www.uvicorn.org/deployment/)
- [Docker Compose Deploy](https://docs.docker.com/compose/compose-file/deploy/)

---

**Auteur:** Claude Code
**Version:** 1.0
**Prochaine étape:** Implémenter les optimisations Niveau 1 et tester sur c5.4xlarge
