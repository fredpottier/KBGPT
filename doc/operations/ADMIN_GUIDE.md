# Guide Administrateur KnowWhere OSMOSE

**Version:** 1.0
**Date:** 2025-10-16
**Audience:** Administrateurs système et responsables plateforme

---

## Table des Matières

1. [Introduction](#1-introduction)
2. [Architecture Simplifiée](#2-architecture-simplifiée)
3. [Gestion des Tenants](#3-gestion-des-tenants)
4. [Configuration LLM](#4-configuration-llm)
5. [Gestion de l'Ontologie](#5-gestion-de-lontologie)
6. [Monitoring Grafana](#6-monitoring-grafana)
7. [Gestion Utilisateurs](#7-gestion-utilisateurs)
8. [Backup et Restauration](#8-backup-et-restauration)
9. [Troubleshooting](#9-troubleshooting)

---

## 1. Introduction

### 1.1 Qu'est-ce que KnowWhere OSMOSE ?

KnowWhere (nom commercial du projet OSMOSE - Organic Semantic Memory Organization & Smart Extraction) est une plateforme de **semantic intelligence** permettant d'extraire, canonicaliser et lier automatiquement des concepts à travers une base documentaire multilingue.

**Différenciation vs Copilot/Gemini** :
- ✅ Architecture agentique avec maîtrise des coûts LLM ($1-8/1000 pages)
- ✅ Dual-Graph Semantic Intelligence (Proto-KG → Published-KG)
- ✅ Filtrage contextuel hybride (Graph + Embeddings, $0 coût)
- ✅ Multi-tenant avec isolation stricte (Neo4j + Qdrant + Redis)
- ✅ Canonicalisation robuste avec sandbox auto-learning

**Tagline** : *"Le Cortex Documentaire des Organisations - Comprendre vos documents ET maîtriser vos coûts"*

### 1.2 Rôle de l'Administrateur

En tant qu'administrateur KnowWhere, vous êtes responsable de :

1. **Gestion des tenants** : Création, configuration, quotas, isolation
2. **Configuration LLM** : Modèles, prompts, coûts, rate limits
3. **Ontologie** : Validation concepts sandbox, rollback, catalogue SAP
4. **Monitoring** : Dashboards Grafana, alertes, métriques production
5. **Sécurité** : Permissions, audit trail, conformité GDPR/HIPAA
6. **Backup/Restore** : Sauvegarde données critiques (Neo4j, Qdrant)

---

## 2. Architecture Simplifiée

### 2.1 Composants Principaux

```
┌─────────────────────────────────────────────────────────────┐
│                    Frontend (Next.js)                       │
│           http://localhost:3000 - Interface Admin           │
└──────────────────────┬──────────────────────────────────────┘
                       │
┌──────────────────────▼──────────────────────────────────────┐
│              FastAPI Backend (8000)                         │
│  6 Agents: Supervisor, Extractor, Miner, Gatekeeper,       │
│            Budget Manager, LLM Dispatcher                   │
└──────────────────────┬──────────────────────────────────────┘
                       │
        ┌──────────────┼──────────────┐
        │              │              │
┌───────▼────────┐ ┌──▼────────┐ ┌──▼──────────┐
│   Neo4j        │ │  Qdrant   │ │   Redis     │
│  Proto-KG      │ │ Embeddings│ │   Queues    │
│  Published-KG  │ │  Vectors  │ │   Budgets   │
└────────────────┘ └───────────┘ └─────────────┘
```

### 2.2 Flux d'Ingestion Simplifié

```
1. Upload Document → 2. Topic Segmentation → 3. Concept Extraction
                                                      ↓
4. Proto-KG Storage ← ──────────────────────────────┘
                ↓
5. Gatekeeper Quality Check (Gate Profiles + Contextual Filtering)
                ↓
6. Published-KG Promotion ← Canonicalisation + Deduplication
```

**Dual-Graph Strategy** :
- **Proto-KG** : Candidats concepts extraits, non-validés (supprimés après 7 jours)
- **Published-KG** : Concepts validés haute qualité (persistés long-terme)

### 2.3 Architecture Agentique

**6 Agents Orchestrés par FSM (Finite State Machine)** :

| Agent | Rôle | Coût LLM |
|-------|------|----------|
| **Supervisor** | Orchestration FSM, timeout, retry logic | $0 |
| **ExtractorOrchestrator** | Routing NO_LLM/SMALL/BIG/VISION basé complexité | $0.001-0.03/doc |
| **PatternMiner** | Cross-segment reasoning, co-occurrence | $0 (Graph-based) |
| **GatekeeperDelegate** | Quality gates (STRICT/BALANCED/PERMISSIVE) | $0 |
| **BudgetManager** | Caps, quotas, refund logic | $0 |
| **LLMDispatcher** | Rate limiting 500/100/50 RPM, circuit breaker | $0 |

**Total Cost Target** : $0.25/doc (PDF textuels), $0.77/doc (complexes), $1.97/doc (PPT-heavy)

---

## 3. Gestion des Tenants

### 3.1 Concept de Multi-Tenant

**Isolation stricte** :
- Chaque tenant a un namespace isolé dans Neo4j, Qdrant, Redis
- Pas de fuite de données cross-tenant (validé par tests E2E Scénario B)
- Quotas budget et documents par tenant

### 3.2 Créer un Tenant

**Via API** :

```bash
curl -X POST http://localhost:8000/api/admin/tenants \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "tenant_id": "acme_corp",
    "tenant_name": "ACME Corporation",
    "quotas": {
      "max_docs_per_day": 500,
      "max_budget_per_day_usd": 100.0,
      "max_published_concepts": 10000
    },
    "settings": {
      "gate_profile": "BALANCED",
      "enable_contextual_filtering": true,
      "enable_auto_canonicalization": true,
      "canonicalization_threshold": 0.85
    }
  }'
```

**Réponse** :
```json
{
  "tenant_id": "acme_corp",
  "status": "active",
  "created_at": "2025-10-16T10:30:00Z",
  "namespace": {
    "neo4j_database": "acme_corp",
    "qdrant_collection_prefix": "acme_corp_",
    "redis_namespace": "tenant:acme_corp:"
  }
}
```

### 3.3 Configuration Quotas

**Quotas disponibles** :

| Quota | Défaut | Description |
|-------|--------|-------------|
| `max_docs_per_day` | 500 | Nombre max documents ingérés par jour |
| `max_budget_per_day_usd` | $100 | Budget LLM max par jour (resets à minuit UTC) |
| `max_published_concepts` | 10,000 | Nombre max concepts Published-KG |
| `max_proto_concepts` | 50,000 | Nombre max concepts Proto-KG (auto-nettoyé après 7j) |

**Ajuster quotas** :

```bash
curl -X PATCH http://localhost:8000/api/admin/tenants/acme_corp/quotas \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "max_docs_per_day": 1000,
    "max_budget_per_day_usd": 250.0
  }'
```

### 3.4 Surveiller Consommation

**Dashboard Admin** : http://localhost:3000/admin/tenants

**Métriques temps-réel** :
- Documents ingérés aujourd'hui
- Budget LLM consommé ($)
- Concepts Proto-KG / Published-KG
- Taux de promotion (%)
- Violations quotas (alertes rouges)

**Via API** :

```bash
curl http://localhost:8000/api/admin/tenants/acme_corp/metrics \
  -H "Authorization: Bearer $ADMIN_TOKEN"
```

**Réponse** :
```json
{
  "tenant_id": "acme_corp",
  "period": "today",
  "metrics": {
    "documents_ingested": 237,
    "budget_consumed_usd": 42.18,
    "llm_calls": {
      "SMALL": 1850,
      "BIG": 45,
      "VISION": 12
    },
    "concepts": {
      "proto_total": 15243,
      "published_total": 3872,
      "promotion_rate": 0.25
    },
    "quotas": {
      "docs_remaining": 263,
      "budget_remaining_usd": 57.82
    }
  }
}
```

---

## 4. Configuration LLM

### 4.1 Modèles Disponibles

**Configuration** : `config/llm_models.yaml`

**Tiers supportés** :

| Tier | Modèle | Coût | RPM Limit | Usage |
|------|--------|------|-----------|-------|
| **SMALL** | gpt-4o-mini | $0.15/1M tokens | 500 | Extraction simple, classification |
| **BIG** | gpt-4o | $2.50/1M tokens | 100 | Extraction complexe, reasoning |
| **VISION** | gpt-4o (vision) | $2.50/1M tokens | 50 | OCR images, slides PPTX |

**Routing automatique PrepassAnalyzer** :
- Détecte complexité document (PDF texte simple → SMALL, tables/images → BIG/VISION)
- Cache embeddings pour éviter re-processing
- Fallback gracieux si rate limit atteint

### 4.2 Modifier Configuration LLM

**Éditer** : `config/llm_models.yaml`

```yaml
models:
  gpt-4o-mini:
    provider: openai
    model_name: gpt-4o-mini
    tier: SMALL
    cost_per_1m_tokens:
      input: 0.15
      output: 0.60
    rate_limits:
      requests_per_minute: 500
      tokens_per_minute: 200000
    max_retries: 3
    timeout_seconds: 30

  gpt-4o:
    provider: openai
    model_name: gpt-4o
    tier: BIG
    cost_per_1m_tokens:
      input: 2.50
      output: 10.00
    rate_limits:
      requests_per_minute: 100
      tokens_per_minute: 100000
    max_retries: 3
    timeout_seconds: 60

  # Ajouter nouveau modèle (ex: Claude Sonnet)
  claude-sonnet-4:
    provider: anthropic
    model_name: claude-sonnet-4-20250514
    tier: BIG
    cost_per_1m_tokens:
      input: 3.00
      output: 15.00
    rate_limits:
      requests_per_minute: 50
      tokens_per_minute: 50000
    max_retries: 3
    timeout_seconds: 60
```

**Redémarrer service** : `docker-compose restart app`

### 4.3 Gérer les Prompts

**Configuration** : `config/prompts.yaml`

**Familles de prompts** :
- `concept_extraction` : Extraction concepts multilingues
- `canonicalization` : Normalisation noms canoniques
- `relation_extraction` : Détection relations sémantiques
- `quality_check` : Validation quality gates

**Éditer prompt** :

```yaml
prompts:
  concept_extraction:
    system: |
      Tu es un expert en extraction de concepts sémantiques.
      Extrait UNIQUEMENT les concepts techniques mentionnés dans le texte.
      Ne génère JAMAIS de concepts non présents.

    user_template: |
      Texte : {text}

      Extrait les concepts clés avec leurs définitions.
      Format JSON: [{{"name": "...", "type": "ENTITY|PRACTICE|STANDARD|TOOL|ROLE", "definition": "..."}}]
```

**Hot-reload** : Les prompts sont rechargés automatiquement (pas de restart nécessaire)

---

## 5. Gestion de l'Ontologie

### 5.1 Ontologie SAP Catalogue

**Source** : `config/sap_solutions.yaml`

**Structure** :

```yaml
sap_solutions:
  - canonical_name: "SAP S/4HANA Cloud"
    aliases:
      - "S4HANA Cloud"
      - "S/4HANA Cloud Edition"
      - "S4H Cloud"
    type: "PRODUCT"
    category: "ERP"
    definition: "Suite ERP cloud-native SAP"
    related_concepts:
      - "SAP RISE"
      - "SAP Clean Core"
```

**Ajout nouveau produit SAP** :

```yaml
  - canonical_name: "SAP Datasphere"
    aliases:
      - "SAP Data Warehouse Cloud"
      - "DWC"
      - "Datasphere"
    type: "PRODUCT"
    category: "DATA_PLATFORM"
    definition: "Plateforme data unifiée SAP"
    related_concepts:
      - "SAP Business Technology Platform"
      - "SAP HANA Cloud"
```

### 5.2 Sandbox Auto-Learning

**Concept** : Les concepts canoniques détectés automatiquement sont mis en sandbox avant validation admin.

**États** :
- `auto_learned_pending` : En attente validation admin (confidence < 0.95)
- `auto_learned_validated` : Auto-validé (confidence ≥ 0.95)
- `manual` : Créé manuellement par admin
- `deprecated` : Déprécié (erreur corrigée)

**Dashboard Sandbox** : http://localhost:3000/admin/ontology/sandbox

**Affichage** :

| Canonical Name | Confidence | Sources | Status | Actions |
|----------------|------------|---------|--------|---------|
| SAP Analytics Cloud | 0.92 | 15 docs | `pending` | ✅ Valider / ❌ Rejeter |
| S/4HANA Edge Edition | 0.78 | 3 docs | `pending` | ✅ Valider / ❌ Rejeter |

**Valider concept** :

```bash
curl -X POST http://localhost:8000/api/admin/ontology/validate \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "entity_id": "abcd-1234-5678",
    "action": "validate",
    "notes": "Produit SAP valide, confirmé par doc officielle"
  }'
```

### 5.3 Mécanisme Rollback

**Problème** : Un concept a été mal canonicalisé (fusion incorrecte)

**Solution** : Dépréciation avec migration automatique

**Exemple** : "SAP HANA" a été fusionné avec "SAP HANA Cloud" par erreur

**API Rollback** :

```bash
curl -X POST http://localhost:8000/api/admin/ontology/deprecate \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "old_entity_id": "entity-merged-incorrectly",
    "new_entity_id": "entity-correct-canonical",
    "reason": "incorrect_fusion",
    "deprecated_by": "admin@acme.com",
    "notes": "SAP HANA et SAP HANA Cloud sont 2 produits distincts"
  }'
```

**Effets** :
1. Ancien concept marqué `status="deprecated"`
2. Relation `DEPRECATED_BY` créée vers nouveau concept
3. Toutes relations migrées automatiquement
4. Audit trail complet conservé

**Historique** : http://localhost:3000/admin/ontology/deprecated

### 5.4 Decision Trace

**Audit trail complet** de chaque décision de canonicalisation

**Dashboard** : http://localhost:3000/admin/ontology/audit

**Filtres disponibles** :
- Par stratégie (ONTOLOGY_LOOKUP, FUZZY_MATCHING, LLM_CANONICALIZATION)
- Par date
- Par confidence (< 0.80, 0.80-0.95, ≥ 0.95)
- Par tenant

**Exemple trace JSON** :

```json
{
  "raw_name": "S4HANA Cloud",
  "entity_type_hint": "PRODUCT",
  "strategies": [
    {
      "strategy": "ONTOLOGY_LOOKUP",
      "score": 0.82,
      "success": true,
      "matched_canonical": "SAP S/4HANA Cloud"
    },
    {
      "strategy": "FUZZY_MATCHING",
      "score": 0.95,
      "success": true,
      "matched_canonical": "SAP S/4HANA Cloud"
    }
  ],
  "final_canonical_name": "SAP S/4HANA Cloud",
  "final_strategy": "FUZZY_MATCHING",
  "final_confidence": 0.95,
  "is_cataloged": true,
  "auto_validated": true,
  "timestamp": "2025-10-16T14:25:30Z"
}
```

---

## 6. Monitoring Grafana

### 6.1 Accès Dashboard

**URL** : http://localhost:3001 (Grafana)

**Credentials** :
- Username: `admin`
- Password: (voir `.env` → `GRAFANA_ADMIN_PASSWORD`)

**Dashboard OSMOSE** : "OSMOSE - Monitoring Dashboard"

### 6.2 Métriques Clés

**18 Panels Principaux** :

| Panel | Métrique | Alerte Si |
|-------|----------|-----------|
| **Ingestion Rate** | Documents/sec, Errors/sec | Errors > 5% |
| **FSM States** | Distribution états FSM | Stuck states > 10min |
| **LLM Calls by Tier** | SMALL/BIG/VISION distribution | BIG > 30% (coût élevé) |
| **LLM Cost** | Total $ accumulé, $/hour | $/hour > $10 |
| **Neo4j Proto-KG** | Concepts proto total, création rate | > 100k concepts |
| **Neo4j Published-KG** | Concepts published, relations | Stagnation promotion |
| **Deduplication Rate** | % concepts dédupliqués | > 60% (problème extraction) |
| **Promotion Rate** | % concepts promoted | < 20% (gates trop strictes) |
| **Filtrage Contextuel** | PRIMARY/COMPETITOR/SECONDARY | COMPETITOR promoted (bug) |
| **Redis Queues** | Pending, completed, failed | Pending > 1000 |
| **Multi-Tenant Isolation** | Violations cross-tenant | > 0 (CRITIQUE) |

### 6.3 Configurer Alertes

**Créer alerte Prometheus** :

```yaml
# prometheus/alerts.yml
groups:
  - name: osmose_alerts
    rules:
      - alert: HighLLMCostRate
        expr: rate(osmose_llm_cost_total[1h]) > 10
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "LLM cost rate > $10/hour"
          description: "Tenant {{ $labels.tenant }} has high LLM cost rate: {{ $value }}"

      - alert: TenantIsolationViolation
        expr: osmose_tenant_isolation_violations_total > 0
        for: 1m
        labels:
          severity: critical
        annotations:
          summary: "CRITICAL: Tenant isolation violation detected"
          description: "Immediate investigation required"
```

**Channels alertes** :
- Slack webhook : `#osmose-alerts`
- Email : `ops-team@acme.com`
- PagerDuty : Critical alerts only

---

## 7. Gestion Utilisateurs

### 7.1 Rôles Disponibles

| Rôle | Permissions | Accès |
|------|-------------|-------|
| **Admin** | Full access, gestion tenants, ontologie | Frontend + API admin |
| **Tenant Admin** | Gestion utilisateurs tenant, quotas lecture | Frontend tenant-specific |
| **User** | Upload docs, recherche, export | Frontend lecture/écriture |
| **Viewer** | Recherche uniquement | Frontend lecture seule |

### 7.2 Créer Utilisateur

**Via Interface** : http://localhost:3000/admin/users/create

**Via API** :

```bash
curl -X POST http://localhost:8000/api/admin/users \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "email": "john.doe@acme.com",
    "role": "user",
    "tenant_id": "acme_corp",
    "permissions": {
      "can_upload": true,
      "can_search": true,
      "can_export": true,
      "can_manage_ontology": false
    }
  }'
```

### 7.3 Audit Trail Utilisateurs

**Logs accès** :
- Toutes actions utilisateur loggées (upload, search, export)
- Retention 90 jours (conformité GDPR)
- Export CSV disponible

**Query logs** :

```bash
curl http://localhost:8000/api/admin/audit-logs \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  -G \
  -d "tenant_id=acme_corp" \
  -d "user_email=john.doe@acme.com" \
  -d "start_date=2025-10-01" \
  -d "end_date=2025-10-16"
```

---

## 8. Backup et Restauration

### 8.1 Données Critiques

**3 sources à sauvegarder** :

| Composant | Données | Fréquence | Taille Estimée |
|-----------|---------|-----------|----------------|
| **Neo4j** | Proto-KG + Published-KG | Quotidienne | 5-50 GB |
| **Qdrant** | Embeddings collections | Hebdomadaire | 10-100 GB |
| **Redis** | Queues + budgets | Temps-réel (réplication) | < 1 GB |

### 8.2 Backup Neo4j

**Script automatique** :

```bash
#!/bin/bash
# /scripts/backup_neo4j.sh

DATE=$(date +%Y-%m-%d)
BACKUP_DIR="/backups/neo4j"

# Dump Neo4j database
docker-compose exec neo4j neo4j-admin database dump \
  --database=neo4j \
  --to-path=/backups/neo4j-dump-${DATE}.dump

# Upload to S3
aws s3 cp ${BACKUP_DIR}/neo4j-dump-${DATE}.dump \
  s3://acme-backups/osmose/neo4j/neo4j-dump-${DATE}.dump

# Retention: supprimer backups > 30 jours
find ${BACKUP_DIR} -name "*.dump" -mtime +30 -delete
```

**Cron** : `0 2 * * * /scripts/backup_neo4j.sh` (tous les jours à 2h00 UTC)

### 8.3 Restore Neo4j

```bash
# Stop service
docker-compose stop neo4j

# Download backup from S3
aws s3 cp s3://acme-backups/osmose/neo4j/neo4j-dump-2025-10-15.dump \
  /backups/neo4j-restore.dump

# Restore database
docker-compose run --rm neo4j neo4j-admin database load \
  --from-path=/backups/neo4j-restore.dump \
  --database=neo4j \
  --overwrite-destination=true

# Restart service
docker-compose start neo4j
```

### 8.4 Backup Qdrant

**Snapshot Qdrant** :

```bash
curl -X POST http://localhost:6333/collections/concepts_published/snapshots \
  -H "Content-Type: application/json"

# Download snapshot
curl http://localhost:6333/collections/concepts_published/snapshots/snapshot-2025-10-16.snapshot \
  --output /backups/qdrant-snapshot-2025-10-16.snapshot

# Upload to S3
aws s3 cp /backups/qdrant-snapshot-2025-10-16.snapshot \
  s3://acme-backups/osmose/qdrant/
```

### 8.5 Restore Qdrant

```bash
# Download snapshot
aws s3 cp s3://acme-backups/osmose/qdrant/snapshot-2025-10-15.snapshot \
  /backups/qdrant-restore.snapshot

# Restore collection
curl -X POST http://localhost:6333/collections/concepts_published/snapshots/upload \
  -F "snapshot=@/backups/qdrant-restore.snapshot"
```

---

## 9. Troubleshooting

### 9.1 Problèmes Communs

#### Problème 1 : Documents bloqués en ingestion

**Symptômes** :
- Documents en status `PROCESSING` > 30 min
- Redis queue `pending` ne diminue pas

**Diagnostic** :

```bash
# Vérifier queue Redis
docker-compose exec redis redis-cli LLEN rq:queue:default

# Vérifier worker
docker-compose logs worker | grep ERROR
```

**Solutions** :
1. Redémarrer worker : `docker-compose restart worker`
2. Purger queue (si worker stuck) : `docker-compose exec redis redis-cli FLUSHDB` (⚠️ perte données queue)
3. Augmenter timeout worker : `.env` → `WORKER_TIMEOUT=600`

#### Problème 2 : Coûts LLM élevés

**Symptômes** :
- Budget tenant épuisé rapidement
- Dashboard Grafana : LLM cost > $10/hour

**Diagnostic** :

```bash
# Vérifier distribution tiers LLM
curl http://localhost:8000/api/admin/metrics/llm-calls | jq '.distribution'

# Expected: {"SMALL": 85%, "BIG": 12%, "VISION": 3%}
# Problème si: {"SMALL": 40%, "BIG": 50%, "VISION": 10%}
```

**Solutions** :
1. Tuning PrepassAnalyzer : Abaisser seuils BIG/VISION dans `config/agents/routing_policies.yaml`
2. Activer cache embeddings : `ENABLE_EMBEDDING_CACHE=true` dans `.env`
3. Ajuster gate profile : `BALANCED` → `PERMISSIVE` (moins de LLM calls validation)

#### Problème 3 : Concepts dupliqués

**Symptômes** :
- Dashboard Neo4j : Même concept × N occurrences
- Grafana : Deduplication rate < 20%

**Diagnostic** :

```cypher
// Trouver doublons
MATCH (c:CanonicalConcept {canonical_name: "SAP S/4HANA Cloud"})
RETURN count(c) as duplicate_count
```

**Solutions** :
1. Vérifier fonction `deduplicate=True` active dans `neo4j_client.promote_to_published()`
2. Ré-exécuter déduplication manuelle :

```bash
curl -X POST http://localhost:8000/api/admin/ontology/deduplicate \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"canonical_name": "SAP S/4HANA Cloud", "dry_run": false}'
```

#### Problème 4 : Filtrage contextuel inactif

**Symptômes** :
- Concurrents promus au même niveau que produits principaux
- Grafana : `COMPETITOR` adjustments = 0

**Diagnostic** :

```bash
# Vérifier config tenant
curl http://localhost:8000/api/admin/tenants/acme_corp/settings | jq '.enable_contextual_filtering'
# Expected: true

# Vérifier dépendances worker
docker-compose exec worker pip list | grep -E "(sentence-transformers|networkx)"
```

**Solutions** :
1. Activer filtrage : `enable_contextual_filtering: true` dans tenant settings
2. Installer dépendances :
   ```bash
   docker-compose exec worker pip install sentence-transformers networkx
   docker-compose restart worker
   ```

#### Problème 5 : Neo4j unavailable

**Symptômes** :
- Erreur `Neo4jConnectionError` dans logs
- Dashboard Grafana : Neo4j metrics = 0

**Diagnostic** :

```bash
# Vérifier Neo4j running
docker-compose ps neo4j

# Tester connexion
docker-compose exec neo4j cypher-shell -u neo4j -p $NEO4J_PASSWORD "RETURN 1"
```

**Solutions** :
1. Redémarrer Neo4j : `docker-compose restart neo4j`
2. Vérifier credentials : `.env` → `NEO4J_PASSWORD`
3. Vérifier réseau Docker : `docker network inspect sap_kb_default`

### 9.2 Logs Utiles

**Formats de logs** :

```bash
# Logs backend
docker-compose logs app | grep -E "\[OSMOSE:|ERROR|WARNING\]"

# Logs agents
docker-compose logs app | grep "\[AGENT:"

# Logs canonicalisation
docker-compose logs app | grep "\[ONTOLOGY:Sandbox\]"

# Logs filtrage contextuel
docker-compose logs app | grep "\[GATEKEEPER:ContextualFilter\]"
```

### 9.3 Support

**Niveaux de support** :

| Issue | Contact | SLA |
|-------|---------|-----|
| **Critical** (service down) | `ops-urgent@acme.com` | 1 hour |
| **High** (performance dégradée) | `support@acme.com` | 4 hours |
| **Medium** (bug non-bloquant) | `support@acme.com` | 1 business day |
| **Low** (question, feature request) | `support@acme.com` | 3 business days |

**Documentation complémentaire** :
- Architecture : `doc/OSMOSE_ARCHITECTURE_TECHNIQUE.md`
- Roadmap : `doc/OSMOSE_ROADMAP_INTEGREE.md`
- Phase 1.5 : `doc/phase1_osmose/PHASE1.5_TRACKING_V2.md`

---

**Version** : 1.0
**Dernière mise à jour** : 2025-10-16
**Auteur** : Équipe OSMOSE
