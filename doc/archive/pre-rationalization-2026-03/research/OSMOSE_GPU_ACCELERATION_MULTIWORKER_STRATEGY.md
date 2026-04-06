# OSMOSE - Stratégie GPU Acceleration & Multi-Worker

**Date:** 2025-11-15
**Version:** 1.0
**Status:** ✅ Solution Implémentée
**Phase:** Phase 1 - Optimisation Performance

---

## 📋 Table des Matières

1. [Contexte & Problème](#contexte--problème)
2. [Analyse Technique](#analyse-technique)
3. [Solution Implémentée](#solution-implémentée)
4. [Stratégies Multi-Worker Production](#stratégies-multi-worker-production)
5. [Recommandations](#recommandations)
6. [Plan d'Action](#plan-daction)

---

## 🎯 Contexte & Problème

### Objectif Performance

**Cible:** Réduire le temps d'ingestion d'un document de **85 minutes → 15-20 minutes**

**Équipement:**
- GPU: NVIDIA RTX 5070 Ti
- Environnement: Docker Desktop Windows + WSL2
- Configuration: 1 worker RQ pour traitement documents

### Problème Rencontré

**Erreur CUDA Multiprocessing:**
```
RuntimeError: Cannot re-initialize CUDA in forked subprocess.
To use CUDA with multiprocessing, you must use the 'spawn' start method
```

**Manifestation:**
- Le worker RQ démarre correctement
- Les modèles d'embeddings tentent de s'initialiser sur GPU
- ❌ **ERREUR** lors de l'exécution du job (subprocess forké)
- Fallback sur CPU → performance dégradée (85 min au lieu de 15-20 min)

---

## 🔬 Analyse Technique

### Cause Racine

Le problème est une **incompatibilité architecturale** entre RQ Worker et CUDA :

#### 1. Architecture RQ Worker

```python
# RQ Worker utilise os.fork() pour exécuter les jobs
class Worker:
    def execute_job(self, job):
        pid = os.fork()  # ← Fork le processus
        if pid == 0:
            # Processus fils exécute le job
            job.perform()
```

#### 2. Limitation CUDA

**CUDA ne supporte PAS fork()** :
- Lors d'un `fork()`, le processus fils hérite de l'état mémoire du parent
- Si le parent a initialisé CUDA, le fils essaie de réutiliser cet état
- ❌ **CUDA refuse** : les contextes GPU ne peuvent pas être partagés via fork

#### 3. Pourquoi set_start_method('spawn') ne fonctionnait pas

**Tentative initiale** (lignes 3-9 de worker.py) :
```python
import multiprocessing
try:
    multiprocessing.set_start_method('spawn', force=True)
except RuntimeError:
    pass
```

**Pourquoi ça échouait** :
- `set_start_method()` configure le module `multiprocessing` Python
- RQ n'utilise PAS `multiprocessing`, mais `os.fork()` directement
- Le paramétrage n'avait donc aucun effet sur RQ

### Séquence d'Erreur

```
1. Worker RQ démarre (processus principal)
   └─> warm_clients() charge les modèles
       └─> get_sentence_transformer() initialise SentenceTransformer
           └─> Auto-détecte CUDA et l'initialise ✅

2. Job arrive dans la queue Redis

3. RQ Worker fork() un subprocess
   └─> Le subprocess hérite de l'état CUDA du parent

4. Job tente d'utiliser les embeddings
   └─> MultilingualEmbedder.__init__() détecte CUDA
       └─> Essaie d'initialiser SentenceTransformer sur CUDA
           └─> ❌ RuntimeError: Cannot re-initialize CUDA in forked subprocess
```

---

## ✅ Solution Implémentée

### SimpleWorker : La Solution RQ Native

RQ fournit une classe `SimpleWorker` qui **n'utilise PAS fork()** :

**Différence clé** :
- `Worker` : Fork un subprocess pour chaque job (incompatible CUDA)
- `SimpleWorker` : Exécute les jobs **dans le même processus** (compatible CUDA)

### Modifications Apportées

**Fichier:** `src/knowbase/ingestion/queue/worker.py`

**Avant** :
```python
from __future__ import annotations

# CRITICAL: Force 'spawn' method BEFORE any torch/CUDA imports
import multiprocessing
try:
    multiprocessing.set_start_method('spawn', force=True)
except RuntimeError:
    pass

import logging
import os
import debugpy
from rq import Worker  # ← Worker standard (utilise fork)

def warm_clients() -> None:
    """Preload shared heavy clients so all jobs reuse the same instances."""
    get_openai_client()
    get_qdrant_client()
    get_sentence_transformer()

def run_worker(*, queue_name: str | None = None, with_scheduler: bool = True) -> None:
    warm_clients()
    queue = get_queue(queue_name)

    worker = Worker(  # ← Utilise fork()
        [queue.name],
        connection=get_redis_connection(),
        job_monitoring_interval=30,
    )

    worker.work(
        with_scheduler=with_scheduler,
        logging_level=logging.INFO,
        max_jobs=max_jobs,
    )
```

**Après** :
```python
from __future__ import annotations

import logging
import os
import debugpy
from rq import SimpleWorker  # ← SimpleWorker (pas de fork)

def warm_clients() -> None:
    """Preload shared heavy clients so all jobs reuse the same instances.

    Using SimpleWorker (no fork), we can safely warm all clients including GPU models.
    """
    get_openai_client()
    get_qdrant_client()
    get_sentence_transformer()  # ✅ Safe avec SimpleWorker

def run_worker(*, queue_name: str | None = None, with_scheduler: bool = True) -> None:
    warm_clients()
    queue = get_queue(queue_name)

    # IMPORTANT: Use SimpleWorker instead of Worker to avoid fork() with CUDA
    # SimpleWorker runs jobs in the same process (no fork), making it safe for GPU
    worker = SimpleWorker(  # ← Pas de fork
        [queue.name],
        connection=get_redis_connection(),
        job_monitoring_interval=30,
    )

    worker.work(
        with_scheduler=with_scheduler,
        logging_level=logging.INFO,
        max_jobs=max_jobs,
    )
```

**Changements** :
1. ✅ `Worker` → `SimpleWorker` (ligne 7)
2. ✅ Suppression du code `multiprocessing.set_start_method()` (plus nécessaire)
3. ✅ Commentaires explicatifs ajoutés

### Avantages de SimpleWorker

| Critère | Worker (fork) | SimpleWorker (same process) |
|---------|--------------|----------------------------|
| **Compatible CUDA** | ❌ Non | ✅ Oui |
| **Isolation jobs** | ✅ Forte (subprocess) | ⚠️ Moyenne (même processus) |
| **Overhead startup** | ⚠️ Fork à chaque job | ✅ Aucun overhead |
| **Mémoire** | ⚠️ Dupliquée | ✅ Partagée |
| **Performance GPU** | ❌ Impossible | ✅ Optimale |

### Comportement avec DEV_MODE

**Configuration actuelle** (`docker-compose.yml`) :
```yaml
environment:
  DEV_MODE: "true"  # Auto-reload après chaque job
```

**Impact** (`worker.py` lignes 41-42) :
```python
is_dev_mode = os.getenv("DEV_MODE", "true").lower() == "true"
max_jobs = 1 if is_dev_mode else 10  # Recharge après 1 job en dev
```

**Résultat** :
- En DEV : Worker traite 1 job → se termine → redémarre proprement
- En PROD : Worker traite 10 jobs → se termine → redémarre (évite fuites mémoire)

✅ **Parfait pour SimpleWorker** : Le worker se recharge régulièrement donc pas d'accumulation d'état

---

## 🏗️ Stratégies Multi-Worker Production

### Contexte

SimpleWorker exécute les jobs **séquentiellement** (1 job à la fois par worker).

**Question** : Comment scaler pour traiter plusieurs documents en parallèle ?

### Option 1 : Multi-Containers SimpleWorker (⭐ RECOMMANDÉ)

**Architecture** : 1 container = 1 SimpleWorker = 1 GPU dédié

#### Configuration Docker Compose

```yaml
# docker-compose.prod.yml
version: '3.8'

x-worker-common: &worker-common
  build:
    context: .
    dockerfile: ./app/Dockerfile
  image: sap-kb-worker:latest
  env_file: .env
  environment:
    REDIS_URL: redis://redis:6379/0
    DEV_MODE: "false"  # Production mode
    HF_HOME: /data/models
    KNOWBASE_DATA_DIR: /data
  volumes:
    - ./data:/data
    - ./src:/app/src
    - ./config:/app/config
  networks:
    - knowbase_net
  working_dir: /app
  command: python -m knowbase.ingestion.queue

services:
  # ========================================
  # Worker 1 - GPU 0
  # ========================================
  ingestion-worker-1:
    <<: *worker-common
    container_name: osmose-worker-gpu-1
    stop_grace_period: 30s
    deploy:
      resources:
        reservations:
          devices:
            - driver: nvidia
              device_ids: ['0']  # GPU physique 0
              capabilities: [gpu]
    environment:
      CUDA_VISIBLE_DEVICES: "0"
      WORKER_NAME: "gpu-worker-1"

  # ========================================
  # Worker 2 - GPU 1
  # ========================================
  ingestion-worker-2:
    <<: *worker-common
    container_name: osmose-worker-gpu-2
    stop_grace_period: 30s
    deploy:
      resources:
        reservations:
          devices:
            - driver: nvidia
              device_ids: ['1']  # GPU physique 1
              capabilities: [gpu]
    environment:
      CUDA_VISIBLE_DEVICES: "0"  # Mappé comme device 0 dans le container
      WORKER_NAME: "gpu-worker-2"

  # ========================================
  # Worker 3 - CPU Fallback (optionnel)
  # ========================================
  ingestion-worker-cpu:
    <<: *worker-common
    container_name: osmose-worker-cpu
    stop_grace_period: 30s
    # Pas de configuration GPU → utilisera CPU automatiquement
    environment:
      CUDA_VISIBLE_DEVICES: ""  # Force CPU
      WORKER_NAME: "cpu-worker"

networks:
  knowbase_net:
    name: knowbase_network
    driver: bridge
```

#### Déploiement

```bash
# Production avec 2 GPUs + 1 CPU fallback
docker-compose -f docker-compose.prod.yml up -d

# Vérifier les workers actifs
docker-compose -f docker-compose.prod.yml ps

# Logs d'un worker spécifique
docker logs osmose-worker-gpu-1 -f

# Scaling dynamique (workers CPU uniquement)
docker-compose -f docker-compose.prod.yml up -d --scale ingestion-worker-cpu=3
```

#### Avantages ✅

1. **Simplicité** : Aucun changement de code nécessaire
2. **Isolation GPU** : Chaque worker a son propre GPU dédié
3. **Scalabilité linéaire** :
   - 1 GPU → 1 worker → 1 job concurrent
   - 2 GPUs → 2 workers → 2 jobs concurrents
   - N GPUs → N workers → N jobs concurrents
4. **Failover** : Si un worker crash, les autres continuent
5. **Monitoring** : Logs séparés par container
6. **Hybrid** : Mélange GPU + CPU workers possible

#### Inconvénients ⚠️

1. **Mémoire** : Chaque worker charge ses propres modèles
   - `multilingual-e5-large` : ~2.5 GB par worker
   - Solution : Acceptable si GPU a ≥8GB VRAM
2. **Overhead** : N containers au lieu de 1
   - Impact : Négligeable avec Docker (containers légers)

#### Estimation Ressources

**Par Worker GPU** :
- VRAM : ~3-4 GB (modèle embeddings + contexte CUDA)
- RAM : ~4-6 GB (modèles Python + cache)
- CPU : 2-4 cores (extraction texte, Vision API)

**Exemple Configuration** :
- **Machine 1** : 1× RTX 5070 Ti (16GB) → 2 workers GPU + 1 worker CPU
- **Machine 2** : 2× RTX 4090 (48GB) → 4 workers GPU + 2 workers CPU

---

### Option 2 : Celery avec Pool=Solo (Alternative)

**Principe** : Remplacer RQ par Celery qui supporte nativement les workers sans fork

#### Migration vers Celery

**1. Installation**
```bash
pip install celery[redis]
```

**2. Configuration Celery**
```python
# config/celery_config.py
from celery import Celery

app = Celery(
    'osmose',
    broker='redis://redis:6379/0',
    backend='redis://redis:6379/1'
)

app.conf.update(
    task_serializer='pickle',
    accept_content=['pickle', 'json'],
    result_serializer='pickle',
    timezone='Europe/Paris',
    enable_utc=True,

    # IMPORTANT: Pool solo (pas de fork)
    worker_pool='solo',  # ← Équivalent SimpleWorker
    worker_concurrency=1,
)
```

**3. Définition Tasks**
```python
# src/knowbase/ingestion/celery_tasks.py
from config.celery_config import app
from knowbase.ingestion.pipelines.pptx_pipeline import PPTXPipeline

@app.task(bind=True)
def ingest_pptx_task(self, file_path: str, **kwargs):
    """Task Celery pour ingestion PPTX (équivalent ingest_pptx_job RQ)."""

    # Progress callback avec Celery
    def update_progress(progress: int, message: str):
        self.update_state(
            state='PROGRESS',
            meta={'current': progress, 'message': message}
        )

    pipeline = PPTXPipeline()
    result = pipeline.process_pptx(
        file_path,
        progress_callback=update_progress,
        **kwargs
    )

    return result
```

**4. Lancement Worker**
```bash
# Development
celery -A config.celery_config worker --pool=solo --loglevel=info

# Production avec 3 workers
celery -A config.celery_config worker --pool=solo --concurrency=1 --hostname=worker1@%h
celery -A config.celery_config worker --pool=solo --concurrency=1 --hostname=worker2@%h
celery -A config.celery_config worker --pool=solo --concurrency=1 --hostname=worker3@%h
```

**5. Enqueue Tasks**
```python
# Remplacer les appels RQ
# AVANT (RQ)
from knowbase.ingestion.queue.jobs import ingest_pptx_job
job = queue.enqueue(ingest_pptx_job, file_path, ...)

# APRÈS (Celery)
from knowbase.ingestion.celery_tasks import ingest_pptx_task
task = ingest_pptx_task.delay(file_path, ...)
```

#### Avantages ✅

1. **Production-grade** : Utilisé par millions d'applications
2. **Monitoring avancé** : Flower UI (dashboard web)
3. **Task chaining** : Workflows complexes (ingestion → OCR → embedding → indexing)
4. **Retry logic** : Gestion sophistiquée des erreurs
5. **Distributed** : Workers sur plusieurs machines facilement
6. **Pool options** : `solo`, `threads`, `gevent` selon besoins

#### Inconvénients ⚠️

1. **Migration complète** : Remplacer tout le code RQ (2-3 jours)
2. **Complexité** : Courbe d'apprentissage Celery
3. **Overhead** : Plus lourd que RQ (mais features++)

#### Quand Migrer vers Celery ?

**Signaux pour migrer** :
- ✅ Besoin de workers distribués (plusieurs machines)
- ✅ Workflows complexes avec dépendances entre tasks
- ✅ Monitoring avancé requis (dashboard, métriques)
- ✅ Plus de 5-10 workers concurrents
- ✅ Gestion fine des priorités et retry

**Pas nécessaire si** :
- ✅ ≤ 5 workers sur même machine
- ✅ Jobs simples et indépendants
- ✅ RQ + SimpleWorker fonctionne bien

---

### Option 3 : Custom Worker avec subprocess.spawn (❌ Non Recommandé)

**Principe** : Créer une classe Worker personnalisée qui override le mécanisme de fork

**Pourquoi ne pas faire ça** :
- ❌ Complexité élevée (maintenance long terme)
- ❌ Risque de bugs subtils (sérialisation, IPC)
- ❌ Doit suivre les mises à jour RQ
- ✅ **SimpleWorker fait déjà le job**

---

## 🎯 Recommandations

### Phase 1-2 : Développement & MVP (Actuel)

**✅ Solution Actuelle : SimpleWorker (1 worker)**

**Configuration** : `docker-compose.yml`
```yaml
ingestion-worker:
  image: sap-kb-worker:latest
  container_name: knowbase-worker
  environment:
    DEV_MODE: "true"  # Auto-reload après chaque job
  deploy:
    resources:
      reservations:
        devices:
          - driver: nvidia
            count: 1
            capabilities: [gpu]
```

**Avantages** :
- ✅ Fonctionne MAINTENANT (pas de refactoring)
- ✅ Compatible GPU (RTX 5070 Ti utilisé)
- ✅ Simple à débugger

**Limitations acceptables** :
- ⚠️ 1 document à la fois (séquentiel)
- ⚠️ OK pour développement et démonstrations

---

### Phase 3 : Pré-Production (Semaines 20-24)

**✅ Solution : Multi-Containers SimpleWorker**

**Configuration** : Créer `docker-compose.prod.yml`

**Scalabilité cible** :
- **2 workers GPU** : Traitement de 2 documents simultanés
- **1 worker CPU** : Fallback si GPUs occupés

**Déploiement** :
```bash
# Lancement production
docker-compose -f docker-compose.infra.yml \
               -f docker-compose.yml \
               -f docker-compose.prod.yml \
               -f docker-compose.monitoring.yml \
               up -d
```

**Monitoring** :
- Grafana : Dashboards per-worker
- Prometheus : Métriques GPU (nvidia-smi)
- Loki : Logs agrégés

---

### Phase 4 : Production & Scale (Semaines 25+)

**Évaluation Migration Celery**

**Critères de décision** :

| Critère | Rester RQ+SimpleWorker | Migrer Celery |
|---------|----------------------|---------------|
| **Nb workers** | ≤ 5 workers | > 5 workers |
| **Distribution** | Même machine | Plusieurs machines |
| **Workflows** | Jobs indépendants | Tasks avec dépendances |
| **Monitoring** | Grafana suffit | Besoin Flower UI |
| **Effort migration** | 0 jours | 2-3 jours |

**Recommandation** :
- ✅ **Si ≤ 5 workers** : Garder SimpleWorker (KISS principle)
- ⚠️ **Si > 5 workers** : Évaluer Celery vs scale horizontal (+ machines)

---

## 📝 Plan d'Action

### ✅ Fait (2025-11-15)

1. ✅ Analyse du problème CUDA multiprocessing
2. ✅ Identification solution : SimpleWorker
3. ✅ Implémentation dans `worker.py`
4. ✅ Redémarrage worker sans erreurs
5. ✅ Documentation technique créée

### 🔄 En Cours

1. ⏳ **Test GPU avec import réel**
   - Action : Lancer import d'un document
   - Validation : Observer logs CUDA initialization
   - Cible : Confirmer temps < 20 min (vs 85 min CPU)

### 📅 Court Terme (Phase 1 - Semaines 11-14)

1. **Valider performance GPU** (Semaine 11)
   - Import de 5 documents test
   - Mesurer temps réels
   - Comparer CPU vs GPU

2. **Optimiser configuration GPU** (Semaine 12)
   - Ajuster `batch_size` pour VRAM disponible
   - Tester différentes configurations `max_jobs`
   - Documenter settings optimaux

3. **Monitoring GPU** (Semaine 13)
   - Ajouter métriques GPU à Prometheus
   - Dashboard Grafana : VRAM, utilisation, température
   - Alertes si GPU non utilisé

### 📅 Moyen Terme (Phase 2-3 - Semaines 15-24)

1. **Créer docker-compose.prod.yml** (Semaine 20)
   - Configuration 2-3 workers
   - Tests de charge
   - Documentation déploiement

2. **Tests scalabilité** (Semaine 21)
   - Import concurrent de 10 documents
   - Mesurer throughput réel
   - Identifier bottlenecks

3. **Optimisation mémoire** (Semaine 22)
   - Profiling VRAM par worker
   - Ajuster `max_jobs` si nécessaire
   - Tests stabilité 24h

### 📅 Long Terme (Phase 4 - Semaines 25+)

1. **Évaluation Celery** (Semaine 25)
   - POC Celery sur branche `feat/celery-migration`
   - Comparaison RQ vs Celery
   - Décision GO/NO-GO

2. **Production readiness** (Semaine 26+)
   - CI/CD pour déploiement workers
   - Runbooks opérationnels
   - Formation équipe ops

---

## 🔧 Maintenance & Troubleshooting

### Vérifier que GPU est utilisé

```bash
# Dans le container worker
docker exec knowbase-worker python -c "
import torch
print(f'CUDA available: {torch.cuda.is_available()}')
print(f'Device: {torch.cuda.get_device_name(0)}')
"
```

**Output attendu** :
```
CUDA available: True
Device: NVIDIA GeForce RTX 5070 Ti
```

### Vérifier initialisation SentenceTransformer

```bash
# Logs worker au démarrage
docker logs knowbase-worker | grep OSMOSE

# Devrait afficher
[OSMOSE] Loading embeddings model: intfloat/multilingual-e5-large...
[OSMOSE] ✅ Embeddings model loaded: intfloat/multilingual-e5-large (1024D, device: cuda (GPU: NVIDIA GeForce RTX 5070 Ti))
```

### Monitoring VRAM en temps réel

```bash
# Sur l'hôte Windows avec GPU
nvidia-smi -l 1

# Observer "GPU-Util" et "Memory-Usage" pendant ingestion
```

### Si GPU non utilisé (fallback CPU)

**Symptômes** :
- Logs montrent `device: cpu`
- Temps d'ingestion > 60 min

**Diagnostic** :
```bash
# 1. Vérifier GPU visible par Docker
docker run --rm --gpus all nvidia/cuda:12.0.0-base-ubuntu22.04 nvidia-smi

# 2. Vérifier configuration docker-compose
docker-compose config | grep -A 5 "ingestion-worker"

# 3. Vérifier CUDA_VISIBLE_DEVICES
docker exec knowbase-worker env | grep CUDA
```

**Solutions** :
1. Redémarrer Docker Desktop (bug Windows)
2. Vérifier `docker-compose.yml` lignes 79-85 (deploy.resources.reservations)
3. Mettre à jour NVIDIA Container Toolkit

---

## 📊 Métriques Cibles

### Performance GPU vs CPU

| Métrique | CPU (baseline) | GPU (cible) | Amélioration |
|----------|----------------|-------------|--------------|
| **Temps ingestion** (230 slides) | 85 min | 15-20 min | **~4.5x** |
| **Embeddings batch** (128 texts) | ~5 sec | ~0.5 sec | **10x** |
| **Topic segmentation** | ~45 min | ~5 min | **9x** |
| **Throughput** | 0.7 docs/h | 3-4 docs/h | **5x** |

### Scalabilité Multi-Worker

| Configuration | Throughput Théorique | Utilisation VRAM |
|---------------|---------------------|------------------|
| 1 worker GPU | 3-4 docs/h | 3-4 GB |
| 2 workers GPU | 6-8 docs/h | 6-8 GB |
| 3 workers GPU | 9-12 docs/h | 9-12 GB |

**Note** : RTX 5070 Ti (16 GB VRAM) → Max 3-4 workers GPU recommandés

---

## 🔗 Références

### Documentation Projet

- **Architecture OSMOSE** : `doc/OSMOSE_ARCHITECTURE_TECHNIQUE.md`
- **Phase 1 Semantic Core** : `doc/phases/PHASE1_SEMANTIC_CORE.md`
- **Roadmap** : `doc/OSMOSE_ROADMAP_INTEGREE.md`

### Documentation Externe

- **RQ SimpleWorker** : https://python-rq.org/docs/workers/#simpleworker
- **CUDA Multiprocessing** : https://pytorch.org/docs/stable/notes/multiprocessing.html
- **Celery** : https://docs.celeryproject.org/en/stable/
- **Docker GPU** : https://docs.docker.com/config/containers/resource_constraints/#gpu

### Issues & Discussions

- **RQ + CUDA Fork Issue** : https://github.com/rq/rq/issues/1220
- **PyTorch Multiprocessing** : https://github.com/pytorch/pytorch/issues/3492

---

## ✍️ Changelog

| Date | Version | Changements |
|------|---------|-------------|
| 2025-11-15 | 1.0 | Document initial - Solution SimpleWorker implémentée |

---

**Maintenu par** : Équipe OSMOSE
**Dernière révision** : 2025-11-15
