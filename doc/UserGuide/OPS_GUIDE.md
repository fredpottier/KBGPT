# Guide Opérations KnowWhere OSMOSE

**Version:** 1.0
**Date:** 2025-10-16
**Audience:** Équipes DevOps et SRE

---

## Table des Matières

1. [Déploiement](#1-déploiement)
2. [Configuration Services](#2-configuration-services)
3. [Scaling](#3-scaling)
4. [Monitoring et Alerting](#4-monitoring-et-alerting)
5. [Logs et Debugging](#5-logs-et-debugging)
6. [Performance Tuning](#6-performance-tuning)
7. [Security Best Practices](#7-security-best-practices)
8. [Disaster Recovery](#8-disaster-recovery)
9. [Maintenance](#9-maintenance)
10. [SLI/SLO/SLA](#10-slislosla)

---

## 1. Déploiement

### 1.1 Pré-requis Production

**Infrastructure minimale** :

| Composant | CPU | RAM | Disk | Notes |
|-----------|-----|-----|------|-------|
| **App (FastAPI)** | 4 cores | 8 GB | 50 GB | Python 3.11+ |
| **Worker (RQ)** | 4 cores | 8 GB | 50 GB | Python 3.11+ |
| **Frontend (Next.js)** | 2 cores | 4 GB | 20 GB | Node.js 20+ |
| **Neo4j** | 8 cores | 16 GB | 200 GB SSD | Enterprise Edition recommandée |
| **Qdrant** | 4 cores | 16 GB | 500 GB SSD | GPU optionnel pour performance |
| **Redis** | 2 cores | 4 GB | 20 GB | Persistence AOF activée |
| **Prometheus** | 2 cores | 4 GB | 100 GB | Retention 30 jours |
| **Grafana** | 1 core | 2 GB | 10 GB | - |

**Total recommandé** : 27 cores, 62 GB RAM, 950 GB disque

### 1.2 Déploiement Docker Compose (Production)

**Clone repository** :

```bash
git clone https://github.com/acme/knowwhere-osmose.git
cd knowwhere-osmose
git checkout v1.0-production
```

**Configuration .env** :

```bash
# Copier template
cp .env.example .env

# Éditer variables production
nano .env
```

**Variables critiques** :

```bash
# Environment
ENVIRONMENT=production
DEBUG_APP=false
DEBUG_WORKER=false

# API Keys (REQUIS)
OPENAI_API_KEY=sk-proj-xxxxxxxxxxxxxxxxxxxxx
ANTHROPIC_API_KEY=sk-ant-xxxxxxxxxxxxxxxxxxxxx

# Database URLs
NEO4J_URI=bolt://neo4j:7687
NEO4J_PASSWORD=<strong-password-here>
QDRANT_URL=http://qdrant:6333
REDIS_URL=redis://redis:6379/0

# Security
JWT_SECRET_KEY=<generate-with-openssl-rand-hex-32>
FRONTEND_URL=https://knowwhere.acme.com
ALLOWED_ORIGINS=https://knowwhere.acme.com

# Monitoring
PROMETHEUS_ENABLED=true
GRAFANA_ADMIN_PASSWORD=<strong-password-here>

# Backups
S3_BACKUP_BUCKET=acme-osmose-backups
AWS_ACCESS_KEY_ID=AKIA...
AWS_SECRET_ACCESS_KEY=...
```

**Lancer services** :

```bash
# Build images
docker-compose -f docker-compose.prod.yml build

# Start services
docker-compose -f docker-compose.prod.yml up -d

# Vérifier santé
docker-compose ps
curl http://localhost:8000/health
```

**Initialiser database** :

```bash
# Neo4j: Créer contraintes et indexes
docker-compose exec app python scripts/init_neo4j_schema.py

# Qdrant: Créer collections
docker-compose exec app python scripts/init_qdrant_collections.py
```

### 1.3 Déploiement Kubernetes (Scalable)

**Fichiers manifests** : `k8s/`

**Namespace** :

```bash
kubectl create namespace osmose-production
kubectl config set-context --current --namespace=osmose-production
```

**Secrets** :

```bash
kubectl create secret generic osmose-secrets \
  --from-literal=openai-api-key=$OPENAI_API_KEY \
  --from-literal=neo4j-password=$NEO4J_PASSWORD \
  --from-literal=jwt-secret=$JWT_SECRET
```

**Déploiement** :

```bash
# Stateful services (Neo4j, Qdrant, Redis)
kubectl apply -f k8s/statefulsets/

# Application services
kubectl apply -f k8s/deployments/

# Ingress (HTTPS)
kubectl apply -f k8s/ingress.yml
```

**Vérifier rollout** :

```bash
kubectl rollout status deployment/osmose-app
kubectl get pods -l app=osmose
```

---

## 2. Configuration Services

### 2.1 Neo4j Production

**docker-compose.prod.yml** :

```yaml
neo4j:
  image: neo4j:5.14-enterprise
  environment:
    - NEO4J_AUTH=neo4j/${NEO4J_PASSWORD}
    - NEO4J_server_memory_heap_initial__size=4G
    - NEO4J_server_memory_heap_max__size=4G
    - NEO4J_server_memory_pagecache_size=8G
    - NEO4J_server_jvm_additional=-XX:+UseG1GC
    - NEO4J_dbms_security_auth__enabled=true
    - NEO4J_dbms_connector_bolt_listen__address=0.0.0.0:7687
    - NEO4J_dbms_connector_http_listen__address=0.0.0.0:7474
  volumes:
    - neo4j_data:/data
    - neo4j_logs:/logs
    - /backups/neo4j:/backups
  ulimits:
    nofile:
      soft: 40000
      hard: 40000
```

**Tuning performance** :

```
# neo4j.conf
dbms.transaction.timeout=300s
dbms.lock.acquisition.timeout=60s
dbms.checkpoint.interval.time=15m
dbms.checkpoint.interval.tx=100000
```

### 2.2 Qdrant Production

**docker-compose.prod.yml** :

```yaml
qdrant:
  image: qdrant/qdrant:v1.7
  environment:
    - QDRANT__SERVICE__GRPC_PORT=6334
    - QDRANT__STORAGE__STORAGE_PATH=/qdrant/storage
    - QDRANT__STORAGE__SNAPSHOTS_PATH=/qdrant/snapshots
    - QDRANT__STORAGE__PERFORMANCE__MAX_SEARCH_THREADS=4
  volumes:
    - qdrant_storage:/qdrant/storage
    - qdrant_snapshots:/qdrant/snapshots
    - /backups/qdrant:/backups
```

**Optimisations** :

```yaml
# Activer HNSW indexing
hnsw_config:
  m: 16
  ef_construct: 100
  full_scan_threshold: 10000

# Quantization (réduction mémoire 75%)
quantization_config:
  scalar:
    type: int8
    quantile: 0.99
    always_ram: true
```

### 2.3 Redis Production

**docker-compose.prod.yml** :

```yaml
redis:
  image: redis:7-alpine
  command: >
    redis-server
    --appendonly yes
    --appendfsync everysec
    --maxmemory 4gb
    --maxmemory-policy allkeys-lru
  volumes:
    - redis_data:/data
```

**Monitoring** :

```bash
# Redis CLI
docker-compose exec redis redis-cli

# Check memory
INFO memory

# Check keys
DBSIZE

# Slow log
SLOWLOG GET 10
```

---

## 3. Scaling

### 3.1 Scaling Horizontal

**Worker Replicas** :

```yaml
# docker-compose.prod.yml
worker:
  deploy:
    replicas: 5  # 5 workers concurrents
    resources:
      limits:
        cpus: '4'
        memory: 8G
```

**Auto-scaling K8s** :

```yaml
# k8s/hpa.yml
apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
metadata:
  name: osmose-worker-hpa
spec:
  scaleTargetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: osmose-worker
  minReplicas: 3
  maxReplicas: 20
  metrics:
    - type: Resource
      resource:
        name: cpu
        target:
          type: Utilization
          averageUtilization: 70
    - type: Pods
      pods:
        metric:
          name: queue_length
        target:
          type: AverageValue
          averageValue: "100"
```

### 3.2 Scaling Vertical

**Augmenter ressources Neo4j** :

```bash
# Arrêter service
docker-compose stop neo4j

# Éditer limits
nano docker-compose.prod.yml
# → heap: 4G → 8G, pagecache: 8G → 16G

# Redémarrer
docker-compose up -d neo4j
```

**Augmenter ressources Qdrant** :

```yaml
qdrant:
  deploy:
    resources:
      limits:
        cpus: '8'      # 4 → 8
        memory: 32G    # 16G → 32G
```

### 3.3 Scaling Multi-Région

**Architecture** :

```
Région US-EAST-1 (Primary)
├── App + Worker + Frontend
├── Neo4j (Primary)
├── Qdrant (Primary)
└── Redis (Primary)

Région EU-WEST-1 (Replica)
├── App + Worker + Frontend (read-only)
├── Neo4j (Replica - Read Replica)
├── Qdrant (Replica)
└── Redis (Replica)
```

**Neo4j Replication** :

```
# Primary
NEO4J_dbms_mode=CORE

# Replica
NEO4J_dbms_mode=READ_REPLICA
NEO4J_causal__clustering_initial__discovery__members=neo4j-primary:5000
```

---

## 4. Monitoring et Alerting

### 4.1 Prometheus Configuration

**prometheus.yml** :

```yaml
global:
  scrape_interval: 15s
  evaluation_interval: 15s

scrape_configs:
  - job_name: 'osmose-app'
    static_configs:
      - targets: ['app:8000']
    metrics_path: '/metrics'

  - job_name: 'neo4j'
    static_configs:
      - targets: ['neo4j:2004']

  - job_name: 'qdrant'
    static_configs:
      - targets: ['qdrant:6333']

  - job_name: 'redis'
    static_configs:
      - targets: ['redis-exporter:9121']
```

### 4.2 Alertes Critiques

**alerts.yml** :

```yaml
groups:
  - name: osmose_critical
    rules:
      - alert: ServiceDown
        expr: up{job="osmose-app"} == 0
        for: 2m
        labels:
          severity: critical
        annotations:
          summary: "OSMOSE service down"

      - alert: HighErrorRate
        expr: rate(osmose_ingestion_errors_total[5m]) > 0.1
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "Error rate > 10%"

      - alert: Neo4jDiskFull
        expr: neo4j_store_size_bytes / neo4j_store_size_limit_bytes > 0.90
        for: 10m
        labels:
          severity: critical

      - alert: QueueBacklog
        expr: osmose_redis_queue_pending_total > 1000
        for: 15m
        labels:
          severity: warning
```

### 4.3 Health Checks

**Endpoints** :

```bash
# App health
curl http://localhost:8000/health
# → {"status": "healthy", "services": {"neo4j": "up", "qdrant": "up", "redis": "up"}}

# Neo4j health
curl http://localhost:7474/db/data/
# → HTTP 200

# Qdrant health
curl http://localhost:6333/health
# → {"title": "qdrant - vector search engine", "version": "1.7.0"}

# Redis health
docker-compose exec redis redis-cli PING
# → PONG
```

**Kubernetes Probes** :

```yaml
livenessProbe:
  httpGet:
    path: /health
    port: 8000
  initialDelaySeconds: 30
  periodSeconds: 10
  timeoutSeconds: 5
  failureThreshold: 3

readinessProbe:
  httpGet:
    path: /ready
    port: 8000
  initialDelaySeconds: 10
  periodSeconds: 5
  timeoutSeconds: 3
  failureThreshold: 2
```

---

## 5. Logs et Debugging

### 5.1 Centralisation Logs (ELK Stack)

**Filebeat configuration** :

```yaml
filebeat.inputs:
  - type: docker
    containers.ids:
      - '*'
    processors:
      - add_docker_metadata: ~
      - decode_json_fields:
          fields: ["message"]
          target: "json"

output.elasticsearch:
  hosts: ["elasticsearch:9200"]
  index: "osmose-logs-%{+yyyy.MM.dd}"
```

### 5.2 Log Levels

**Configuration** : `.env`

```bash
# Production
LOG_LEVEL=INFO

# Debug (temporaire)
LOG_LEVEL=DEBUG

# Structured logs
LOG_FORMAT=json
```

**Formats logs** :

```json
{
  "timestamp": "2025-10-16T15:30:45.123Z",
  "level": "INFO",
  "logger": "osmose.agents.supervisor",
  "message": "[OSMOSE:FSM] Transition START → SEGMENTATION",
  "context": {
    "document_id": "doc-12345",
    "tenant_id": "acme_corp",
    "state": "SEGMENTATION"
  }
}
```

### 5.3 Debugging Production

**Activer debug temporaire** (1 container spécifique) :

```bash
# Set env var
docker-compose exec app bash -c "export LOG_LEVEL=DEBUG && supervisorctl restart app"

# Tail logs
docker-compose logs -f app | grep DEBUG
```

**Activer profiling** :

```python
# app/main.py
from pyinstrument import Profiler

@app.middleware("http")
async def profile_request(request: Request, call_next):
    profiler = Profiler()
    profiler.start()
    response = await call_next(request)
    profiler.stop()
    print(profiler.output_text())
    return response
```

---

## 6. Performance Tuning

### 6.1 Optimisations Backend

**Uvicorn workers** :

```yaml
# docker-compose.prod.yml
app:
  command: uvicorn src.knowbase.api.main:app --host 0.0.0.0 --port 8000 --workers 4
```

**Cache Redis** :

```python
# Activer cache LLM responses
ENABLE_LLM_CACHE=true
LLM_CACHE_TTL_SECONDS=604800  # 7 jours
```

**Connection pooling** :

```python
# Neo4j
NEO4J_MAX_CONNECTION_POOL_SIZE=50
NEO4J_CONNECTION_ACQUISITION_TIMEOUT=60

# Qdrant
QDRANT_GRPC_PORT=6334  # Plus rapide que HTTP
QDRANT_TIMEOUT=30
```

### 6.2 Optimisations Qdrant

**Indexing HNSW** :

```python
from qdrant_client.models import VectorParams, HnswConfigDiff

client.recreate_collection(
    collection_name="concepts_published",
    vectors_config=VectorParams(size=1024, distance="Cosine"),
    hnsw_config=HnswConfigDiff(
        m=16,                    # Links per node (default: 16)
        ef_construct=100,        # Construction effort (default: 100)
        full_scan_threshold=10000  # Switch to HNSW above this size
    )
)
```

**Quantization** (réduction RAM 75%) :

```python
from qdrant_client.models import ScalarQuantization

client.update_collection(
    collection_name="concepts_published",
    quantization_config=ScalarQuantization(
        type="int8",
        quantile=0.99,
        always_ram=True
    )
)
```

### 6.3 Optimisations Neo4j

**Indexes essentiels** :

```cypher
// Documents
CREATE INDEX document_tenant_id IF NOT EXISTS
FOR (d:Document) ON (d.tenant_id);

CREATE INDEX document_created_at IF NOT EXISTS
FOR (d:Document) ON (d.created_at);

// Concepts
CREATE INDEX concept_canonical_name IF NOT EXISTS
FOR (c:CanonicalConcept) ON (c.canonical_name);

CREATE INDEX concept_tenant_status IF NOT EXISTS
FOR (c:CanonicalConcept) ON (c.tenant_id, c.status);

// Relations
CREATE INDEX relation_type IF NOT EXISTS
FOR ()-[r:RELATED_TO]-() ON (r.type);
```

**Query optimization** :

```cypher
// MAUVAIS (scan complet)
MATCH (c:CanonicalConcept)
WHERE c.canonical_name CONTAINS "SAP"
RETURN c

// BON (index lookup)
MATCH (c:CanonicalConcept {tenant_id: $tenant_id})
WHERE c.canonical_name STARTS WITH "SAP"
RETURN c
```

---

## 7. Security Best Practices

### 7.1 Network Security

**Firewall rules** :

```bash
# Autoriser uniquement ports nécessaires
ufw allow 22/tcp      # SSH
ufw allow 443/tcp     # HTTPS
ufw deny 8000/tcp     # Backend (internal only)
ufw deny 7687/tcp     # Neo4j (internal only)
ufw deny 6333/tcp     # Qdrant (internal only)
```

**Docker network isolation** :

```yaml
networks:
  frontend:
    driver: bridge
  backend:
    driver: bridge
    internal: true  # Pas d'accès externe

services:
  app:
    networks:
      - frontend
      - backend
  neo4j:
    networks:
      - backend  # Isolé
```

### 7.2 Secrets Management

**Utiliser secrets externes** (pas .env) :

```yaml
# docker-compose.prod.yml avec Docker Swarm secrets
services:
  app:
    secrets:
      - openai_api_key
      - neo4j_password

secrets:
  openai_api_key:
    external: true
  neo4j_password:
    external: true
```

**Kubernetes secrets** :

```bash
kubectl create secret generic osmose-secrets \
  --from-file=openai-key=./secrets/openai.key \
  --from-file=neo4j-password=./secrets/neo4j.password
```

### 7.3 HTTPS/TLS

**Nginx reverse proxy** :

```nginx
server {
    listen 443 ssl http2;
    server_name knowwhere.acme.com;

    ssl_certificate /etc/nginx/ssl/cert.pem;
    ssl_certificate_key /etc/nginx/ssl/key.pem;
    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_ciphers HIGH:!aNULL:!MD5;

    location / {
        proxy_pass http://frontend:3000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-Proto $scheme;
    }

    location /api/ {
        proxy_pass http://app:8000;
        proxy_set_header Host $host;
    }
}
```

---

## 8. Disaster Recovery

### 8.1 RPO/RTO Targets

| Composant | RPO | RTO | Stratégie |
|-----------|-----|-----|-----------|
| **Neo4j** | 24h | 2h | Backup quotidien + WAL |
| **Qdrant** | 1 week | 4h | Snapshot hebdomadaire |
| **Redis** | 1h | 30min | AOF persistence + Replication |
| **Application** | 0 (stateless) | 15min | Redeploy Docker images |

### 8.2 Backup Strategy

**Automated backups** : `scripts/backup-all.sh`

```bash
#!/bin/bash
set -e

DATE=$(date +%Y-%m-%d-%H%M)
BACKUP_ROOT=/backups/${DATE}

# Neo4j
docker-compose exec neo4j neo4j-admin database dump \
  --to-path=/backups/neo4j-${DATE}.dump

# Qdrant
curl -X POST http://localhost:6333/collections/concepts_published/snapshots
curl -O http://localhost:6333/collections/concepts_published/snapshots/latest

# Upload to S3
aws s3 sync ${BACKUP_ROOT} s3://acme-osmose-backups/${DATE}/

# Cleanup old backups (> 30 days)
find /backups -mtime +30 -delete
```

**Cron** : `0 3 * * * /scripts/backup-all.sh`

### 8.3 Restore Procedure

**Ordre de restore** :

1. Restore Neo4j (graphe concepts)
2. Restore Qdrant (embeddings)
3. Redeploy application (stateless)
4. Vérifier intégrité données

**Temps estimé** : 2-4 heures selon taille données

---

## 9. Maintenance

### 9.1 Maintenance Planifiée

**Fenêtre maintenance** : Dimanche 02:00-06:00 UTC

**Checklist** :

1. **Pré-maintenance** (30min avant)
   - [ ] Notification utilisateurs
   - [ ] Backup complet
   - [ ] Vérifier rollback plan

2. **Maintenance** (2-4h)
   - [ ] Mettre service en mode lecture seule
   - [ ] Upgrade Docker images
   - [ ] Appliquer migrations database
   - [ ] Tests smoke

3. **Post-maintenance** (30min)
   - [ ] Remettre en mode lecture/écriture
   - [ ] Vérifier métriques Grafana
   - [ ] Notification fin maintenance

### 9.2 Upgrades Zero-Downtime

**Blue-Green deployment** :

```bash
# Deploy version v2.0 (green)
docker-compose -f docker-compose.green.yml up -d

# Test green
curl http://localhost:8001/health

# Switch traffic (Nginx)
nginx -s reload  # Route → green

# Remove blue
docker-compose -f docker-compose.blue.yml down
```

### 9.3 Nettoyage Régulier

**Proto-KG cleanup** (automatique) :

```cypher
// Supprimer Proto-KG > 7 jours
MATCH (p:ProtoConcept)
WHERE p.created_at < datetime() - duration('P7D')
  AND p.status = 'pending'
DELETE p
```

**Qdrant vacuum** :

```bash
# Optimize collection (defragmentation)
curl -X POST http://localhost:6333/collections/concepts_published/optimize
```

---

## 10. SLI/SLO/SLA

### 10.1 Service Level Indicators (SLI)

| SLI | Mesure | Target |
|-----|--------|--------|
| **Availability** | Uptime % | > 99.9% (43 min downtime/mois) |
| **Latency** | P95 ingestion time | < 30s/doc |
| **Error Rate** | Errors / Total requests | < 1% |
| **Throughput** | Documents/jour | > 1000 |

### 10.2 Service Level Objectives (SLO)

**SLO 1 - Availability** :
- **Target** : 99.9% uptime mensuel
- **Error Budget** : 43 minutes/mois
- **Mesure** : `avg_over_time(up{job="osmose-app"}[30d]) > 0.999`

**SLO 2 - Performance** :
- **Target** : P95 latency < 30s
- **Error Budget** : 5% requests > 30s
- **Mesure** : `histogram_quantile(0.95, rate(osmose_ingestion_duration_seconds_bucket[30d])) < 30`

**SLO 3 - Qualité** :
- **Target** : Precision@Promote > 90%
- **Error Budget** : 10% faux positifs
- **Mesure** : `osmose_concepts_promoted_valid_total / osmose_concepts_promoted_total > 0.90`

### 10.3 Service Level Agreements (SLA)

**Tier Premium** :
- Availability : 99.95%
- Support : 1h response time critical issues
- Backups : Quotidiens avec retention 30 jours
- Crédits : 10% MRR si SLA breached

**Tier Standard** :
- Availability : 99.5%
- Support : 4h response time critical issues
- Backups : Hebdomadaires avec retention 7 jours
- Crédits : 5% MRR si SLA breached

---

**Version** : 1.0
**Dernière mise à jour** : 2025-10-16
**Auteur** : Équipe DevOps OSMOSE
