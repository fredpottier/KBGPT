# Guide Operationnel OSMOSIS

> **Niveau de fiabilite** : Operationnel verifie. Commandes, ports et services verifies contre docker-compose et kw.ps1. Les IPs EC2 et credentials peuvent changer — toujours verifier avec `./kw.ps1 info`.

*Document consolide — Mars 2026*

---

## 1. Architecture de deploiement

### Principe : 1 Instance = 1 Client

OSMOSIS utilise une architecture **d'instances dediees par client** plutot qu'un multi-tenancy logique. Chaque client dispose de sa propre stack complete (Neo4j, Qdrant, Redis, PostgreSQL, App, Worker, Frontend). Cette isolation physique simplifie l'audit de conformite, elimine les risques de fuite de donnees et constitue un argument commercial fort pour les secteurs reglementes (pharma, finance, sante).

### Architecture Multi-Compose

L'orchestration Docker est separee en trois fichiers compose :

| Fichier | Role | Services |
|---------|------|----------|
| `docker-compose.infra.yml` | Infrastructure stateful (rarement redemarree) | Qdrant v1.15.1, Redis 7.2-alpine, Neo4j 5.26.0, PostgreSQL 16 (pgvector) |
| `docker-compose.yml` | Application stateless (frequemment redemarree) | App (FastAPI), Worker (ingestion), Folder-Watcher, Frontend (Next.js) |
| `docker-compose.monitoring.yml` | Monitoring | Grafana, Loki 2.9.3, Promtail |

### Services detailles

| Service | Container | Port(s) | Description |
|---------|-----------|---------|-------------|
| **Qdrant** | knowbase-qdrant | 6333, 6334 (gRPC) | Base vectorielle — stockage embeddings et recherche semantique |
| **Redis** | knowbase-redis | 6379 | Queue RQ (ingestion) + cache + etat burst |
| **Neo4j** | knowbase-neo4j | 7474 (HTTP), 7687 (Bolt) | Knowledge Graph — claims, entities, relations |
| **PostgreSQL** | knowbase-postgres | 5432 | Metadata, sessions, audit trail, historique import |
| **App** | knowbase-app | 8000, 5678 (debug) | API FastAPI — backend principal |
| **Worker** | knowbase-worker | 5679 (debug) | Worker ingestion RQ — GPU NVIDIA (1 GPU reserve) |
| **Folder-Watcher** | knowbase-watcher | — | Surveillance `data/docs_in/` pour import automatique |
| **Frontend** | knowbase-frontend | 3000 | Interface Next.js |
| **Loki** | knowbase-loki | 3101 | Agregation de logs |
| **Promtail** | knowbase-promtail | — | Collecte des logs Docker |
| **Grafana** | knowbase-grafana | 3001 | Visualisation et dashboards |

### Modele de tenancy

**1 instance = 1 client** (isolation physique, pas multi-tenancy logique). Chaque deploiement a ses propres bases Neo4j, Qdrant, PostgreSQL et Redis. Le parametre `tenant_id` present dans le code (valeur par defaut `"default"`) est un **vestige technique** : il est passe en parametre a toutes les fonctions mais n'est jamais configure autrement que `"default"`. Il n'est pas un mode de partition commerciale ni un mecanisme de securite. La migration vers un multi-tenant logique (SaaS) est une option future — le code le supporte structurellement mais ce n'est pas active.

### Reseau et volumes

- **Reseau** : `knowbase_network` (bridge), partage entre tous les fichiers compose
- **Volumes nommes** : `knowbase_qdrant_data`, `knowbase_redis_data`, `knowbase_neo4j_data`, `knowbase_neo4j_logs`, `knowbase_neo4j_plugins`, `knowbase_postgres_data`, `knowbase_frontend_node_modules`, `knowbase_frontend_next_build`

---

## 2. Commandes kw.ps1

`kw.ps1` est le script PowerShell unifie pour gerer l'ensemble des services Docker.

### Demarrage

```powershell
./kw.ps1 start              # Demarre infra + app + monitoring (tout)
./kw.ps1 start infra        # Demarre uniquement infrastructure (Qdrant, Redis, Neo4j, Postgres)
./kw.ps1 start app          # Demarre uniquement application (App, Worker, Frontend)
./kw.ps1 start monitoring   # Demarre uniquement monitoring (Grafana, Loki, Promtail)
```

### Arret

```powershell
./kw.ps1 stop               # Arrete tout
./kw.ps1 stop infra         # Arrete uniquement infrastructure
./kw.ps1 stop app           # Arrete uniquement application
```

### Redemarrage

```powershell
./kw.ps1 restart            # Redemarre tout
./kw.ps1 restart api        # Redemarre App + Frontend SANS toucher le worker (safe pendant import)
./kw.ps1 restart frontend   # Redemarre uniquement le frontend
./kw.ps1 restart app        # Redemarre App + Worker + Frontend (ATTENTION : tue le worker)
```

### Monitoring et informations

```powershell
./kw.ps1 status             # Statut de tous les services
./kw.ps1 ps                 # Alias de status
./kw.ps1 logs app           # Logs backend (Ctrl+C pour quitter)
./kw.ps1 logs worker        # Logs worker
./kw.ps1 logs neo4j         # Logs Neo4j
./kw.ps1 logs frontend      # Logs frontend
./kw.ps1 info               # Toutes les URLs + credentials
```

### Backup et restauration

```powershell
./kw.ps1 backup <name>                   # Creer un backup complet
./kw.ps1 backup <name> --no-cache        # Backup sans le cache d'extraction
./kw.ps1 restore <name>                  # Restaurer un backup
./kw.ps1 restore <name> --force          # Restaurer sans confirmation
./kw.ps1 restore <name> --auto-backup    # Backup automatique avant restauration
./kw.ps1 backup-list                     # Lister les backups disponibles
./kw.ps1 backup-delete <name>            # Supprimer un backup
```

### Nettoyage

```powershell
./kw.ps1 clean              # Purger volumes et containers (DANGER !)
```

---

## 3. URLs et Credentials

### Application

| Service | URL | Authentification |
|---------|-----|------------------|
| Frontend Next.js | http://localhost:3000 | — |
| API Backend | http://localhost:8000 | — |
| API Documentation (Swagger) | http://localhost:8000/docs | — |
| Streamlit UI (legacy) | http://localhost:8501 | — |

### Infrastructure

| Service | URL | Credentials |
|---------|-----|-------------|
| Neo4j Browser | http://localhost:7474 | `neo4j` / `graphiti_neo4j_pass` |
| Qdrant Dashboard | http://localhost:6333/dashboard | Pas d'authentification |
| Redis CLI | `docker exec knowbase-redis redis-cli` | — |
| PostgreSQL | `localhost:5432` | `knowbase` / `knowbase_secure_pass` |

### Monitoring

| Service | URL | Credentials |
|---------|-----|-------------|
| Grafana | http://localhost:3001 | `admin` / `Rn1lm@tr` |
| Loki API | http://localhost:3101 | — |

---

## 4. Burst Mode — EC2 Spot

### Principe

Le Mode Burst deporte **uniquement le compute LLM + Embeddings** sur une instance EC2 Spot GPU. Le pipeline d'ingestion, Qdrant et Neo4j restent locaux. L'EC2 Spot expose des endpoints API OpenAI-compatibles que le local consomme via le LLMRouter.

```
Mode Normal : Pipeline Local -> OpenAI API (LLM) + GPU Local (Embeddings)
Mode Burst  : Pipeline Local -> EC2 Spot vLLM (LLM) + EC2 Spot GPU (Embeddings)
                                   |
                            Meme destination locale (Qdrant/Neo4j)
```

### Configuration materielle

| Composant | Specification |
|-----------|---------------|
| **Instance** | g6.2xlarge (L4 GPU, 24 GB VRAM) |
| **Modele LLM** | Qwen/Qwen2.5-14B-Instruct-AWQ |
| **Quantization** | AWQ Marlin |
| **Serveur LLM** | vLLM (OpenAI-compatible) |
| **Embeddings** | intfloat/multilingual-e5-large via TEI v1.5 |
| **Performance** | 26.8 tokens/s (8.5x speedup vs non-quantise) |
| **Golden AMI** | v8 — `ami-05ec81177dc825d56` |
| **Region** | eu-central-1 |

### Golden AMI

L'AMI pre-configuree contient tous les composants necessaires (modeles pre-telecharges, images Docker pre-pullees, services systemd). Demarrage en 1-2 minutes au lieu de 10-15 minutes.

| Composant | Taille |
|-----------|--------|
| Systeme Ubuntu + drivers NVIDIA | ~40 GB |
| Qwen 2.5 14B AWQ | ~8 GB |
| E5-Large Embeddings | ~1.3 GB |
| Images Docker (vLLM + TEI) | ~10 GB |
| **Total AMI** | **~65 GB (volume 80 GB)** |

### Economies

| Poste | Mode Normal (OpenAI) | Mode Burst (Spot) | Economie |
|-------|---------------------|--------------------|----------|
| LLM (100 docs) | ~$15 | ~$1.00 (1.5h Spot) | **93%** |
| Vision GPT-4o | ~$3/doc (40 calls) | ~$1.20 (gating 60%) | **60%** |
| Cout Spot | — | ~$0.70-0.90/h | — |

### Workflow

1. Admin active Burst (via UI ou API)
2. Instance Spot lancee depuis la Golden AMI
3. Healthcheck sur port 8080 (vLLM + Embeddings ready)
4. LLMRouter bascule automatiquement vers EC2
5. Import batch lance — pipeline local, providers distants
6. Fin du batch — instance Spot terminee, retour mode normal

### Etat Redis

Le burst stocke son etat dans Redis : cle `osmose:burst:state` avec TTL 86400s.

---

## 5. Deploiement AWS

### Architecture

Build local (Windows) -> Push images vers AWS ECR -> Pull sur EC2 -> Docker Compose

### Workflow de deploiement

```powershell
# 1. Build et push vers ECR
.\scripts\build-and-push-ecr.ps1

# 2. Deployer sur EC2
.\scripts\deploy-ec2.ps1 -InstanceIP "18.203.45.67" -KeyPath "C:\path\to\key.pem"

# 3. Update sans re-setup
.\scripts\deploy-ec2.ps1 -InstanceIP "18.203.45.67" -KeyPath "C:\path\to\key.pem" -SkipSetup
```

### Instances recommandees

| Type | vCPU | RAM | Prix/mois | Usage |
|------|------|-----|-----------|-------|
| t3.xlarge | 4 | 16 GB | ~$60 | Tests, 10-50 docs/jour |
| t3.2xlarge | 8 | 32 GB | ~$120 | Production legere |
| m5.2xlarge | 8 | 32 GB | ~$140 | Production intensive |

### Security Groups (ports a ouvrir)

| Port | Service | Source |
|------|---------|--------|
| 22 | SSH | Votre IP uniquement |
| 8000 | API Backend | Votre IP |
| 3000 | Frontend | 0.0.0.0/0 ou votre IP |
| 7474 | Neo4j Browser | Votre IP uniquement |
| 6333 | Qdrant UI | Votre IP uniquement |

**SECURITE** : Ne jamais ouvrir les ports 7474 et 6333 en 0.0.0.0/0.

### Elastic IP

Recommande pour eviter le changement d'IP a chaque stop/start. Gratuit tant qu'associee a une instance active.

---

## 6. Backup et Restore

### Strategie par service

| Service | RPO | RTO | Methode |
|---------|-----|-----|---------|
| **Neo4j** | 24h | 2h | Export Cypher (APOC) ou dump binaire |
| **Qdrant** | 1 semaine | 4h | Snapshot API par collection |
| **Redis** | 1h | 30 min | AOF persistence + BGSAVE |
| **PostgreSQL** | 24h | 1h | pg_dump |
| **Application** | 0 (stateless) | 15 min | Redeploy images |

### Backup via kw.ps1

```powershell
# Backup complet (Neo4j + Qdrant + metadata)
./kw.ps1 backup SAP_20260329

# Restauration
./kw.ps1 restore SAP_20260329
```

Les backups sont stockes dans `data/backups/snapshots/`. Collections Qdrant sauvegardees : `knowbase_chunks_v2`, `rfp_qa`.

### Backup manuel Neo4j

```bash
# Export Cypher (recommande pour portabilite)
docker exec knowbase-neo4j cypher-shell -u neo4j -p graphiti_neo4j_pass \
  --format plain "CALL apoc.export.cypher.all('/backup/neo4j-backup.cypher', {})"

# Dump binaire (recommande si > 10 GB)
docker exec knowbase-neo4j neo4j-admin dump \
  --database=neo4j --to=/backup/neo4j-dump.dump
```

### Backup manuel Qdrant

```bash
# Creer snapshot par collection
curl -X POST "http://localhost:6333/collections/knowbase_chunks_v2/snapshots"
curl -X POST "http://localhost:6333/collections/rfp_qa/snapshots"
```

### REGLE VITALE : Protection du cache d'extraction

**NE JAMAIS SUPPRIMER `data/extraction_cache/`**

Les fichiers `.knowcache.json` sont precieux :
- Evitent de re-extraire les documents (economise temps et couts LLM)
- Permettent de rejouer les imports apres une purge systeme
- Ne doivent jamais etre supprimes lors d'une purge

---

## 7. Couts AWS

### Scenarios de couts mensuels

#### Scenario A : Tests occasionnels (~$27/mois)

```
Usage : 3h/jour, 5 jours/semaine = 60h/mois

EC2 Compute (t3.xlarge)     : $4.93
EBS Storage (130 GB)        : $10.40
ECR Storage (15 GB)         : $1.50
Data Transfer               : $2.00
API LLM (10 docs/jour)      : $7.50
                              ------
TOTAL                       : ~$27/mois
```

#### Scenario B : Dev/Test quotidien (~$119/mois)

```
Usage : 24/7

EC2 Compute (t3.xlarge)     : $60
EBS Storage (130 GB)        : $10.40
ECR + Transfer              : $10.50
API LLM (50 docs/jour)      : $38
                              ------
TOTAL                       : ~$119/mois
```

#### Scenario C : Production (~$309/mois)

```
EC2 Compute (t3.2xlarge RI) : $80
EBS Storage (300 GB)        : $24
ECR + Transfer + CloudWatch : $51.50
API LLM (200 docs/jour)     : $154
                              ------
TOTAL                       : ~$309/mois
```

### Point cle

**Les couts LLM representent 80-90% des couts operationnels totaux.** La strategie Burst sur EC2 Spot avec Qwen 14B AWQ reduit ces couts de 93% par rapport a OpenAI.

### Optimisation des couts

- **Stop/Start** : Arreter l'instance quand non utilisee (economie 87%)
- **Reserved Instances** : -33% sur engagement 1 an
- **Spot Instances** : -50 a 70% pour le compute LLM (Burst Mode)
- **Budget Alerts** : Configurer dans AWS Billing (seuil recommande : $100/mois)

---

## 8. Monitoring

### Stack Grafana + Loki + Promtail

| Composant | Role | Port |
|-----------|------|------|
| **Grafana** | Dashboards et visualisation | 3001 |
| **Loki** | Stockage et indexation des logs | 3101 |
| **Promtail** | Collecte des logs Docker en temps reel | — |

### Configuration

Les fichiers de configuration sont dans `monitoring/` :
- `monitoring/loki-config.yml` — Configuration Loki
- `monitoring/promtail-config.yml` — Configuration Promtail
- `config/grafana_dashboard.json` — Dashboard pre-configure

### Health checks

```bash
# App health
curl http://localhost:8000/status

# Neo4j
curl http://localhost:7474

# Qdrant
curl http://localhost:6333/health

# Redis
docker exec knowbase-redis redis-cli ping
# -> PONG

# Loki
curl http://localhost:3101/ready
```

### Logs par service

```bash
docker-compose logs -f app           # Backend FastAPI
docker-compose logs -f ingestion-worker  # Worker ingestion
docker-compose logs -f frontend      # Next.js
docker-compose logs -f neo4j         # Neo4j
docker-compose logs -f qdrant        # Qdrant
```

---

## 9. Multi-sources (futur — Phase 3)

### Architecture Source Enrollment

OSMOSIS adopte une architecture **"Source Enrollment & Push-to-Osmosis"** pour ingerer des documents depuis des sources heterogenes sans devenir le systeme de stockage.

### Modele de donnees

| Entite | Role |
|--------|------|
| **SourceConnection** | Tuyauterie technique vers un systeme source (OAuth2, API Key, etc.) |
| **SourceScope** | Perimetre administratif surveille (bibliotheque SharePoint, dossier Drive) |
| **DocumentSource** | Identite logique d'un document dans son systeme source |
| **DocumentSnapshot** | Etat exact du document au moment de l'ingestion — racine de provenance |
| **IngestionEvent** | Signal d'entree unifie (scan, webhook, push, upload — tous convergent) |

### Invariants

- **I-SRC-1** : Zero-retention du binaire source — OSMOSIS ne conserve jamais durablement le fichier original
- **I-SRC-2** : Attribution au snapshot, pas au document — chaque claim est liee a un snapshot precis
- **I-SRC-3** : Lien d'acces vers la source d'origine — "Ouvrir dans SharePoint" plutot que proxy
- **I-SRC-4** : Non-contamination du pipeline semantique — les connecteurs n'influencent pas le raisonnement
- **I-SRC-5** : Evenement d'ingestion comme interface unique — tous les modes produisent le meme `IngestionEvent`
- **I-SRC-6** : Tracabilite des disparitions — document supprime = marque, pas efface du KG

### Adapters prevus

| Adapter | Systemes | Priorite |
|---------|----------|----------|
| FilesystemAdapter | Local, reseau, NFS | Existe (burst/pending) |
| MicrosoftGraphAdapter | SharePoint, OneDrive, Teams | Phase 3.2 |
| GoogleWorkspaceAdapter | Google Drive | Phase 3.3 |
| S3Adapter | AWS S3, MinIO | Phase 3.4 |

---

## 10. Purge securisee

### Procedure correcte (preserver les caches)

```bash
# 1. Purger Redis
docker exec knowbase-redis redis-cli FLUSHDB

# 2. Purger les collections Qdrant
curl -X DELETE "http://localhost:6333/collections/knowbase_chunks_v2"
curl -X DELETE "http://localhost:6333/collections/rfp_qa"

# 3. Purger Neo4j
docker exec knowbase-neo4j cypher-shell -u neo4j -p graphiti_neo4j_pass \
  --format plain "MATCH (n) WHERE n.tenant_id = 'default' DETACH DELETE n"

# 4. Purger fichiers traites
rm -rf data/docs_in/* data/docs_done/* data/status/*.status
```

### CE QU'IL NE FAUT JAMAIS FAIRE

```bash
# NE JAMAIS supprimer le cache d'extraction
rm -rf data/extraction_cache/    # INTERDIT !

# NE JAMAIS purger une queue Redis entiere sans verification
# Verifier d'abord qu'aucun worker n'est actif

# NE JAMAIS rebuilder les containers sans autorisation explicite
docker-compose up --build        # INTERDIT sans accord
```

### Verifications prealables

Avant toute purge :
1. Verifier `docker-compose ps` — aucun worker actif
2. Verifier qu'aucun import n'est en cours
3. Le wiki job store est **en memoire** — tout restart app detruit les batch jobs en cours

---

## 11. References archive

Les documents source de ce guide consolide ont ete archives dans :

```
doc/archive/pre-rationalization-2026-03/
├── operations/
│   ├── OPS_GUIDE.md                    # Guide operations original
│   ├── AWS_DEPLOYMENT_GUIDE.md         # Deploiement AWS complet
│   ├── AWS_COST_MANAGEMENT.md          # Gestion couts AWS
│   ├── AWS_BACKUP_RESTORE_STRATEGY.md  # Strategie backup/restore
│   ├── BURST_SPOT_ARCHITECTURE.md      # Architecture Burst EC2 Spot
│   ├── GOLDEN_AMI_BURST_SPEC.md        # Specification Golden AMI
│   └── DOCKER_SETUP.md                 # Setup Docker multi-compose
├── architecture/
│   └── ARCHITECTURE_DEPLOIEMENT.md     # Architecture 1 instance = 1 client
└── ongoing/
    └── ADR_SOURCE_ENROLLMENT_SNAPSHOT_INGESTION.md  # ADR multi-sources
```

---

*Derniere mise a jour : 2026-03-29*
