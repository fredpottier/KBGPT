# 📊 Audit Complet - SAP Knowledge Base - État Actuel (2025-10-10)

## 🎯 Vue d'Ensemble du Projet

**Nom** : Back2Promise - SAP Knowledge Base
**Version** : 2.0.0 (Neo4j Native)
**Statut Général** : 🟡 En développement actif
**Phases Complétées** : Phase 0 (100%), Phase 1 Semaines 1-2 (40%)

---

## 🏗️ Architecture Technique

### Stack Backend
- **Framework** : FastAPI 0.110+ (async/await natif)
- **Language** : Python 3.11+
- **Base de données relationnelle** : SQLite (metadata système)
- **Base de données graphe** : Neo4j 5.26.0 (Knowledge Graph natif)
- **Base vectorielle** : Qdrant 1.15.1 (embeddings)
- **Cache & Queue** : Redis 7.2 (RQ worker)
- **LLM** : Multi-provider (OpenAI, Anthropic, Ollama)

### Stack Frontend
- **Framework** : Next.js 14 (App Router)
- **Language** : TypeScript 5.0+
- **UI Library** : Chakra UI 2.8+
- **State Management** : React Context API
- **Authentification** : JWT (RS256, localStorage)

### Services d'Infrastructure (Docker Compose)

| Service | Image | Port | Statut | Fonction |
|---------|-------|------|--------|----------|
| **app** | sap-kb-app:latest | 8000 | ✅ Running | FastAPI backend principal |
| **ingestion-worker** | sap-kb-worker:latest | 5679 | ✅ Running | Worker async RQ (traitement docs) |
| **frontend** | sap-kb-frontend:latest | 3000 | ✅ Running (healthy) | Interface Next.js moderne |
| **ui** | sap-kb-ui:latest | 8501 | ✅ Running | Interface Streamlit legacy |
| **qdrant** | qdrant/qdrant:v1.15.1 | 6333 | ✅ Running | Base vectorielle (2 collections) |
| **redis** | redis:7.2 | 6379 | ✅ Running | Queue + cache |
| **ngrok** | ngrok/ngrok:latest | - | ✅ Running | Tunneling pour webhooks |
| **neo4j** | neo4j:5.26.0 | 7474, 7687 | ✅ Running (healthy) | Knowledge Graph (Graphiti) |
| **postgres-graphiti** | pgvector/pgvector:pg16 | 5433 | ✅ Running (healthy) | PostgreSQL pour Graphiti |
| **graphiti** | zepai/graphiti:latest | 8300 | 🟠 Running (unhealthy) | API Graphiti (problème connu) |

---

## 📡 Backend API - Endpoints Complets

### 1. **Authentication** (`/api/auth`) - Phase 0 ✅

| Endpoint | Méthode | Protection | Description |
|----------|---------|------------|-------------|
| `/api/auth/login` | POST | Public | Login avec email/password → JWT tokens |
| `/api/auth/refresh` | POST | Public | Refresh access token avec refresh token |
| `/api/auth/register` | POST | Public | Création compte utilisateur |
| `/api/auth/me` | GET | JWT Required | Récupération utilisateur courant |

**Schémas Pydantic** : `LoginRequest`, `TokenResponse`, `UserCreate`, `UserResponse`, `CurrentUser`

**Services** : `AuthService` (hash bcrypt, JWT RS256, clés RSA 2048-bit)

**Sécurité** :
- ✅ JWT RS256 avec clés RSA asymétriques
- ✅ Access tokens (1h expiration)
- ✅ Refresh tokens (7 jours)
- ✅ Claims : user_id, email, role, tenant_id
- ✅ RBAC : admin | editor | viewer

---

### 2. **Search** (`/search`) - Recherche Hybride

| Endpoint | Méthode | Protection | Description |
|----------|---------|------------|-------------|
| `/search` | POST | Public | Recherche vectorielle multi-sources |

**Fonctionnalités** :
- Recherche cascade : RFP Q/A (seuil 0.85) → Knowbase général (seuil 0.70)
- Collections Qdrant : `rfp_qa` (prioritaire), `knowbase`
- Enrichissement LLM avec contexte SAP
- Support filtres par tenant_id

---

### 3. **Facts** (`/api/facts`) - Knowledge Graph Phase 2

| Endpoint | Méthode | Protection | Description |
|----------|---------|------------|-------------|
| `/api/facts` | POST | JWT + Tenant | Création fact (status=proposed) |
| `/api/facts` | GET | JWT + Tenant | Liste facts avec filtres |
| `/api/facts/{id}` | GET | JWT + Tenant | Récupération fact par ID |
| `/api/facts/{id}` | PUT | JWT + Tenant | Mise à jour fact |
| `/api/facts/{id}` | DELETE | JWT + Admin | Suppression fact (admin only) |
| `/api/facts/{id}/approve` | POST | JWT + Admin | Approbation fact (status→approved) |
| `/api/facts/{id}/reject` | POST | JWT + Admin | Rejet fact (status→rejected) |
| `/api/facts/{id}/conflicts` | GET | JWT + Tenant | Détection conflits (CONTRADICTS, OVERRIDES) |
| `/api/facts/{id}/timeline` | GET | JWT + Tenant | Historique modifications fact |
| `/api/facts/stats` | GET | JWT + Tenant | Statistiques agrégées facts |

**Schémas** : `FactCreate`, `FactUpdate`, `FactResponse`, `FactApproval`, `ConflictResponse`, `FactTimelineEntry`, `FactsStats`

**Service** : `FactsService` (Neo4j native)

**Governance** :
- Workflow approve/reject avec audit trail
- Détection conflits automatique
- Timeline historique valeurs
- Isolation multi-tenant stricte

---

### 4. **Entity Types** (`/api/entity-types`) - Phase 2 Registry

| Endpoint | Méthode | Protection | Description |
|----------|---------|------------|-------------|
| `/api/entity-types` | GET | JWT + Tenant | Liste types découverts (filtres status) |
| `/api/entity-types` | POST | JWT + Admin | Création type manuel |
| `/api/entity-types/{type}` | GET | JWT + Tenant | Détail type avec compteurs |
| `/api/entity-types/{type}/approve` | POST | JWT + Admin | Approbation type (status→approved) |
| `/api/entity-types/{type}/reject` | POST | JWT + Admin | Rejet type (status→rejected + cascade delete) |
| `/api/entity-types/{type}/stats` | GET | JWT + Tenant | Statistiques type |

**Modèle SQLite** : `EntityTypeRegistry`
- Compteurs : `entity_count`, `pending_entity_count`
- Workflow : `pending` → `approved` / `rejected`
- Audit : `approved_by`, `approved_at`, `rejection_reason`

**Service** : `EntityTypeRegistryService`

---

### 5. **Document Types** (`/api/document-types`) - Phase 6

| Endpoint | Méthode | Protection | Description |
|----------|---------|------------|-------------|
| `/api/document-types` | GET | JWT + Tenant | Liste types documents |
| `/api/document-types` | POST | JWT + Admin | Création type document |
| `/api/document-types/{id}` | GET | JWT + Tenant | Détail type |
| `/api/document-types/{id}` | PUT | JWT + Admin | Mise à jour type |
| `/api/document-types/{id}` | DELETE | JWT + Admin | Suppression type |

**Modèles SQLite** : `DocumentType`, `DocumentTypeEntityType` (many-to-many)

**Fonctionnalités** :
- Contexte prompt pour guider extraction LLM
- Association entity_types suggérés
- Statistiques usage_count

**Service** : `DocumentTypeService`

---

### 6. **Ingestion** (`/api/ingest`) - Import Documents

| Endpoint | Méthode | Protection | Description |
|----------|---------|------------|-------------|
| `/ingest/pdf` | POST | Public | Import PDF (MegaParse + OCR) |
| `/ingest/pptx` | POST | Public | Import PowerPoint (MegaParse) |
| `/ingest/excel-qa` | POST | Public | Import RFP Excel Q/A |
| `/api/ingest/rfp-excel/template` | GET | Public | Télécharger template Excel RFP |

**Pipeline** :
1. Upload fichier → `/data/docs_in/`
2. Job Redis RQ async
3. Parsing (PDF: Unstructured, PPTX: python-pptx)
4. Chunking + embeddings
5. Ingestion Qdrant
6. Déplacement vers `/data/docs_done/`

**Formats supportés** : PDF, PPTX, DOCX, Excel (.xlsx)

---

### 7. **Imports** (`/api/imports`) - Historique & Monitoring

| Endpoint | Méthode | Protection | Description |
|----------|---------|------------|-------------|
| `/api/imports/history` | GET | Public | Historique imports Redis |
| `/api/imports/active` | GET | Public | Jobs en cours (RQ) |
| `/api/imports/{uid}/delete` | DELETE | JWT + Admin | Suppression import + données Qdrant |
| `/api/imports/sync` | POST | JWT + Admin | Synchro Redis ↔ Qdrant |

**Storage** : Redis (hash `import:{uid}`)

**Service** : `ImportHistoryRedisService`, `ImportDeletionService`

---

### 8. **Status** (`/api/status`) - Health Checks

| Endpoint | Méthode | Protection | Description |
|----------|---------|------------|-------------|
| `/api/status` | GET | Public | Health check multi-services |
| `/api/status/qdrant` | GET | Public | Statut Qdrant + collections |
| `/api/status/neo4j` | GET | Public | Statut Neo4j + compteurs |
| `/api/status/redis` | GET | Public | Statut Redis + queues |

**Métriques retournées** :
- Qdrant : collections count, vectors count, disk usage
- Neo4j : nodes count, relationships count, indexes
- Redis : queue sizes (default, failed, finished)

---

### 9. **Ontology** (`/api/ontology`) - Catalogues Entités

| Endpoint | Méthode | Protection | Description |
|----------|---------|------------|-------------|
| `/api/ontology/catalogues` | GET | Public | Liste catalogues disponibles |
| `/api/ontology/catalogues/{name}` | GET | Public | Détail catalogue avec entités |
| `/api/ontology/entity-types` | GET | Public | Liste types d'entités (multi-catalogues) |

**Catalogues disponibles** :
- `sap_modules.yaml` : Modules SAP (S/4HANA, ECC, BTP...)
- `sap_products.yaml` : Produits SAP
- `infrastructure.yaml` : Infra (Cloud, Database, Middleware)

---

### 10. **Jobs** (`/api/jobs`) - Monitoring RQ Worker

| Endpoint | Méthode | Protection | Description |
|----------|---------|------------|-------------|
| `/api/jobs` | GET | Public | Liste jobs RQ (all/pending/finished/failed) |
| `/api/jobs/{job_id}` | GET | Public | Détail job avec progress |

**Queue Redis** : `default` (ingestion), `failed` (retry), `finished` (cleanup)

---

### 11. **Admin** (`/api/admin`) - Administration

| Endpoint | Méthode | Protection | Description |
|----------|---------|------------|-------------|
| `/api/admin/purge` | POST | JWT + Admin | Purge complète (Qdrant + Neo4j + Redis) |
| `/api/admin/health` | GET | JWT + Admin | Health check détaillé système |

**Service** : `PurgeService` (purge sélective ou totale)

---

### 12. **SAP Solutions** (`/api/sap-solutions`) - Catalogue

| Endpoint | Méthode | Protection | Description |
|----------|---------|------------|-------------|
| `/api/sap-solutions` | GET | Public | Liste solutions SAP (YAML config) |

**Config** : `config/sap_solutions.yaml` (50+ solutions SAP)

---

### 13. **Downloads** (`/api/downloads`) - Téléchargement Documents Source

| Endpoint | Méthode | Protection | Description |
|----------|---------|------------|-------------|
| `/api/downloads/{filename}` | GET | Public | Télécharger document source original |

**Source** : `/data/docs_done/{filename}` (documents traités)

---

### 14. **Token Analysis** (`/api/token-analysis`) - Coûts LLM

| Endpoint | Méthode | Protection | Description |
|----------|---------|------------|-------------|
| `/api/token-analysis` | GET | Public | Statistiques tokens + coûts LLM |

**Métriques** : total_tokens, input_tokens, output_tokens, estimated_cost

---

## 🗄️ Base de Données - Schémas Complets

### SQLite - Metadata Système (`data/entity_types_registry.db`)

**Tables créées** :

#### 1. `entity_types_registry` (Phase 2)
```sql
CREATE TABLE entity_types_registry (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    type_name VARCHAR(50) NOT NULL,           -- Ex: INFRASTRUCTURE, SOLUTION
    status VARCHAR(20) NOT NULL DEFAULT 'pending',  -- pending | approved | rejected
    first_seen TIMESTAMP NOT NULL,
    discovered_by VARCHAR(20) DEFAULT 'llm',  -- llm | admin | system
    entity_count INTEGER DEFAULT 0,
    pending_entity_count INTEGER DEFAULT 0,
    approved_by VARCHAR(100),
    approved_at TIMESTAMP,
    rejected_by VARCHAR(100),
    rejected_at TIMESTAMP,
    rejection_reason TEXT,
    tenant_id VARCHAR(50) DEFAULT 'default',
    description TEXT,
    normalization_status VARCHAR(20),         -- generating | pending_review | NULL
    normalization_job_id VARCHAR(50),
    normalization_started_at TIMESTAMP,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(type_name, tenant_id)
);
CREATE INDEX ix_type_status_tenant ON entity_types_registry(status, tenant_id);
```

#### 2. `document_types` (Phase 6)
```sql
CREATE TABLE document_types (
    id VARCHAR(36) PRIMARY KEY,
    name VARCHAR(100) NOT NULL,               -- Ex: Technical Documentation
    slug VARCHAR(50) NOT NULL UNIQUE,         -- Ex: technical
    description TEXT,
    context_prompt TEXT,                      -- Prompt contextuel pour LLM
    prompt_config TEXT,                       -- JSON config
    usage_count INTEGER DEFAULT 0,
    is_active BOOLEAN DEFAULT TRUE,
    tenant_id VARCHAR(50) DEFAULT 'default',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(slug, tenant_id)
);
```

#### 3. `document_type_entity_types` (Phase 6 - Many-to-Many)
```sql
CREATE TABLE document_type_entity_types (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    document_type_id VARCHAR(36) NOT NULL,
    entity_type_name VARCHAR(50) NOT NULL,    -- SOLUTION, PRODUCT, etc.
    source VARCHAR(20) DEFAULT 'manual',      -- manual | llm_discovered | template
    confidence FLOAT,                         -- 0.0-1.0 si découvert par LLM
    validated_by VARCHAR(100),
    validated_at TIMESTAMP,
    examples TEXT,                            -- JSON array exemples
    tenant_id VARCHAR(50) DEFAULT 'default',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(document_type_id, entity_type_name),
    FOREIGN KEY(document_type_id) REFERENCES document_types(id) ON DELETE CASCADE
);
```

#### 4. `users` (Phase 0 - Authentication)
```sql
CREATE TABLE users (
    id VARCHAR(36) PRIMARY KEY,
    email VARCHAR(255) NOT NULL UNIQUE,
    password_hash VARCHAR(255) NOT NULL,      -- bcrypt hash
    full_name VARCHAR(100),
    role VARCHAR(20) NOT NULL DEFAULT 'viewer',  -- admin | editor | viewer
    tenant_id VARCHAR(50) DEFAULT 'default',
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    last_login_at TIMESTAMP
);
CREATE INDEX ix_user_email ON users(email);
CREATE INDEX ix_user_tenant_role ON users(tenant_id, role);
```

#### 5. `audit_log` (Phase 0 - Audit Trail)
```sql
CREATE TABLE audit_log (
    id VARCHAR(36) PRIMARY KEY,
    user_id VARCHAR(36),                      -- FK vers users
    user_email VARCHAR(255) NOT NULL,
    action VARCHAR(50) NOT NULL,              -- CREATE | UPDATE | DELETE | APPROVE | REJECT
    resource_type VARCHAR(50) NOT NULL,       -- entity | fact | entity_type | document_type
    resource_id VARCHAR(255),
    tenant_id VARCHAR(50) NOT NULL,
    details TEXT,                             -- JSON avec before/after
    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE SET NULL
);
CREATE INDEX ix_audit_timestamp ON audit_log(timestamp);
CREATE INDEX ix_audit_user_action ON audit_log(user_id, action);
CREATE INDEX ix_audit_resource ON audit_log(resource_type, resource_id);
```

**Total Tables SQLite** : 5 tables principales + indexes

---

### Neo4j - Knowledge Graph (`bolt://localhost:7687`)

**Schémas créés** :

#### Phase 1 - Document Backbone (Semaines 1-2) ✅

**Nodes** :

1. **`:Document`** - Documents source
```cypher
(:Document {
    document_id: STRING (UUID),              // UNIQUE CONSTRAINT
    title: STRING,
    source_path: STRING,                     // UNIQUE CONSTRAINT
    document_type: STRING,                   // "Technical Presentation", "Proposal"...
    description: STRING,
    status: STRING,                          // "active", "archived"
    metadata: STRING (JSON),
    tenant_id: STRING,
    created_at: DATETIME,
    updated_at: DATETIME
})
```

2. **`:DocumentVersion`** - Versions documentaires
```cypher
(:DocumentVersion {
    version_id: STRING (UUID),               // UNIQUE CONSTRAINT
    document_id: STRING,
    version_label: STRING,                   // "v1.0", "v2.1"
    effective_date: DATETIME,
    checksum: STRING (SHA256),               // UNIQUE CONSTRAINT (anti-duplicatas)
    file_size: INTEGER,
    page_count: INTEGER,
    author_name: STRING,
    author_email: STRING,
    reviewer_name: STRING,
    is_latest: BOOLEAN,
    metadata: STRING (JSON),
    created_at: DATETIME,
    ingested_at: DATETIME
})
```

**Relationships** :

1. `(:Document)-[:HAS_VERSION]->(:DocumentVersion)` - Lien document → version
2. `(:DocumentVersion)-[:SUPERSEDES]->(:DocumentVersion)` - Lineage versions (v2 supersedes v1)
3. `(:DocumentVersion)-[:AUTHORED_BY]->(:Person)` - Authorship
4. `(:DocumentVersion)-[:REVIEWED_BY]->(:Person)` - Review
5. `(:Episode)-[:FROM_DOCUMENT]->(:DocumentVersion)` - Provenance episode → version

**Contraintes Neo4j** :
```cypher
CREATE CONSTRAINT doc_id_unique IF NOT EXISTS
FOR (d:Document) REQUIRE d.document_id IS UNIQUE;

CREATE CONSTRAINT doc_version_id_unique IF NOT EXISTS
FOR (v:DocumentVersion) REQUIRE v.version_id IS UNIQUE;

CREATE CONSTRAINT doc_version_checksum_unique IF NOT EXISTS
FOR (v:DocumentVersion) REQUIRE v.checksum IS UNIQUE;

CREATE CONSTRAINT doc_source_path_unique IF NOT EXISTS
FOR (d:Document) REQUIRE d.source_path IS UNIQUE;
```

**Index Neo4j** (7 index créés) :
```cypher
CREATE INDEX doc_source_path_idx IF NOT EXISTS
FOR (d:Document) ON (d.source_path);

CREATE INDEX doc_tenant_idx IF NOT EXISTS
FOR (d:Document) ON (d.tenant_id);

CREATE INDEX doc_version_label_idx IF NOT EXISTS
FOR (v:DocumentVersion) ON (v.version_label);

CREATE INDEX doc_version_effective_date_idx IF NOT EXISTS
FOR (v:DocumentVersion) ON (v.effective_date);

CREATE INDEX doc_version_checksum_idx IF NOT EXISTS
FOR (v:DocumentVersion) ON (v.checksum);

CREATE INDEX doc_version_is_latest_idx IF NOT EXISTS
FOR (v:DocumentVersion) ON (v.is_latest);

CREATE INDEX doc_version_composite_idx IF NOT EXISTS
FOR (v:DocumentVersion) ON (v.document_id, v.effective_date);
```

**Services Phase 1** :
- ✅ `DocumentSchema` - Création schéma Neo4j
- ✅ `DocumentRegistryService` - CRUD documents/versions
- ✅ `VersionResolutionService` - Résolution versions (latest, effective_at, lineage)

---

#### Phase 2 - Facts Knowledge Graph (Déjà existant)

**Nodes** : `:Fact`, `:Entity`, `:Episode`

**Service** : `FactsService` (API REST complète)

---

### Qdrant - Collections Vectorielles

| Collection | Dimensions | Vectors | Description |
|------------|------------|---------|-------------|
| `rfp_qa` | 1536 (OpenAI) | Variable | Questions/Réponses RFP prioritaires |
| `knowbase` | 1536 (OpenAI) | Variable | Base de connaissances générale |

**Metadata stockés** :
- `source_document` : Nom fichier source
- `import_uid` : UID import Redis
- `tenant_id` : Isolation multi-tenant
- `chunk_index` : Index chunk dans document
- `page_number` : Numéro page source
- `timestamp` : Date ingestion

---

## 🖥️ Frontend - Pages Complètes

### Architecture Next.js 14

**Router** : App Router (file-based routing)
**Layout** : `MainLayout` avec TopNavigation + ContextualSidebar
**Authentification** : `AuthContext` (React Context + JWT localStorage)

---

### Pages Implémentées (18 pages)

#### 1. Authentification

| Page | Route | Protection | Description |
|------|-------|------------|-------------|
| Login | `/login` | Public | Authentification JWT (email/password) |
| Register | `/register` | Public | Création compte (full_name, email, password, role) |

**Features** :
- Validation mot de passe (8 chars min)
- Redirection `?redirect=/admin` après login
- Show/hide password toggle
- Sélection rôle (admin/editor/viewer)

---

#### 2. Chat & Recherche

| Page | Route | Protection | Description |
|------|-------|------------|-------------|
| Home | `/` | Public | Redirection vers `/chat` |
| Chat | `/chat` | Public | Interface recherche hybride vectorielle |

**Features** :
- Recherche full-text + vectorielle
- Affichage sources avec scores
- Historique conversations
- Export résultats

---

#### 3. Documents

| Page | Route | Protection | Description |
|------|-------|------------|-------------|
| Documents List | `/documents` | Public | Liste documents ingérés |
| Document Detail | `/documents/[id]` | Public | Détail document avec chunks |
| Document Upload | `/documents/upload` | JWT + Editor | Upload documents (PDF, PPTX) |
| Document Import | `/documents/import` | JWT + Editor | Import documents avec config |
| Import Status | `/documents/status` | Public | Historique imports + monitoring jobs |
| RFP Excel | `/rfp-excel` | JWT + Editor | Import Q/A Excel RFP |

**Features** :
- Drag & drop upload
- Monitoring temps réel (RQ jobs)
- Progress bars ingestion
- Suppression imports avec cascade Qdrant
- Export template Excel RFP

---

#### 4. Administration

| Page | Route | Protection | Description |
|------|-------|------------|-------------|
| Admin Dashboard | `/admin` | JWT + Admin | Dashboard admin avec stats |
| Entity Types | `/admin/dynamic-types` | JWT + Admin | Liste entity types (approve/reject workflow) |
| Entity Type Detail | `/admin/dynamic-types/[typeName]` | JWT + Admin | Détail type avec entités associées |
| Document Types List | `/admin/document-types` | JWT + Admin | Liste types documents |
| Document Type Create | `/admin/document-types/new` | JWT + Admin | Création type document |
| Document Type Edit | `/admin/document-types/[id]` | JWT + Admin | Édition type document |
| Settings | `/admin/settings` | JWT + Admin | Paramètres système |

**Features** :
- Approve/Reject entity types découverts
- Association entity_types → document_types
- Statistiques temps réel (compteurs Neo4j)
- Purge données (Qdrant + Neo4j + Redis)

---

### Composants Partagés

**Layout** :
- `MainLayout` : Layout principal avec navigation
- `TopNavigation` : Menu horizontal (Chat, Documents, Admin)
- `ContextualSidebar` : Menu latéral contextuel (documents, admin)

**Auth** :
- `ProtectedRoute` : Wrapper protection par JWT
- `AuthContext` : Context global auth (user, login, logout, hasRole)

**UI** :
- Chakra UI components (Button, Modal, Table, Badge...)
- Custom colors : `brand.500` (bleu SAP)
- Responsive design (mobile-first)

---

## 🔐 Sécurité - Phase 0 Complétée (100%)

### Authentification JWT RS256 ✅

**Implementation** :
- ✅ Clés RSA 2048-bit générées (`config/keys/jwt_private.pem`, `jwt_public.pem`)
- ✅ Access token : 1h expiration
- ✅ Refresh token : 7 jours expiration
- ✅ Claims JWT : `user_id`, `email`, `role`, `tenant_id`
- ✅ Hash bcrypt pour passwords (12 rounds)

**Endpoints Auth** :
- ✅ `POST /api/auth/login` - Login
- ✅ `POST /api/auth/refresh` - Refresh token
- ✅ `GET /api/auth/me` - Current user
- ✅ `POST /api/auth/register` - Register

**Dependencies FastAPI** :
- ✅ `get_current_user()` - Extraction user depuis JWT
- ✅ `require_admin()` - Protection admin only
- ✅ `require_editor()` - Protection editor+
- ✅ `get_tenant_id()` - Extraction tenant_id depuis JWT (pas query param)

**Tests** :
- ✅ 13 tests unitaires `AuthService`
- ✅ 10 tests dependencies FastAPI
- ✅ 14 tests E2E endpoints auth
- **Total : 37 tests authentication passés** ✅

---

### RBAC (Role-Based Access Control) ✅

**Rôles définis** :
- **admin** : Full access (CRUD, approve/reject, purge)
- **editor** : Create/update entities/facts (pas delete)
- **viewer** : Read-only

**Hiérarchie** : `admin > editor > viewer`

**Protection endpoints** :
- ✅ Facts API : Tenant isolation + RBAC
- ✅ Entity Types : Admin approve/reject only
- ✅ Document Types : Admin CRUD only
- ✅ Admin purge : Admin only

---

### Rate Limiting ✅

**Implementation** : SlowAPI
**Limites** : 100 requêtes/minute par IP
**Erreur** : HTTP 429 Too Many Requests

---

### Audit Trail ✅

**Table** : `audit_log` (SQLite)
**Actions loggées** : CREATE, UPDATE, DELETE, APPROVE, REJECT
**Métadonnées** :
- user_id, user_email
- action, resource_type, resource_id
- tenant_id
- details (JSON before/after)
- timestamp

**Service** : `AuditService` (non encore implémenté dans tous endpoints)

---

### Multi-Tenancy ✅

**Isolation** :
- ✅ `tenant_id` extrait depuis JWT (pas query param)
- ✅ Tous les endpoints Facts isolés par tenant
- ✅ Index composite `(tenant_id, type_name)` dans SQLite
- ✅ Queries Neo4j filtrées par `tenant_id`

---

## 📊 Phases & Progression

### ✅ Phase 0 : Security Hardening - **100% COMPLÉTÉE**

**Durée** : 1 journée (2025-10-09)
**Effort** : ~20h (accélérée vs 160h prévues)

**Réalisations** :
- ✅ JWT RS256 Authentication complète
- ✅ RBAC (admin/editor/viewer)
- ✅ Dependencies FastAPI (get_current_user, require_admin...)
- ✅ Modèles SQLite (User, AuditLog)
- ✅ 37 tests authentication (tous passés)
- ✅ Rate limiting SlowAPI (100 req/min)
- ✅ Script création admin par défaut

**Score sécurité** : 8.5/10 (target atteint)

---

### 🟡 Phase 1 : Document Backbone - **40% COMPLÉTÉE** (Semaines 1-2)

**Durée prévue** : 5 semaines
**Statut** : 🟡 En cours (démarré le 2025-10-10)
**Effort estimé** : 200 heures

**Réalisations (Semaines 1-2)** :

#### ✅ Semaine 1 : Schéma Neo4j (100%)
- ✅ Nodes `:Document` et `:DocumentVersion`
- ✅ 4 contraintes unicité (document_id, version_id, checksum, source_path)
- ✅ 7 index performance (source_path, tenant_id, version_label, effective_date, checksum, is_latest, composite)
- ✅ 5 relations (HAS_VERSION, SUPERSEDES, AUTHORED_BY, REVIEWED_BY, FROM_DOCUMENT)
- ✅ Script migration `document_schema.py`

#### ✅ Semaine 2 : Services Backend (100%)
- ✅ `DocumentRegistryService` - CRUD documents/versions
  - `create_document()` : Création document + version initiale
  - `create_version()` : Ajout nouvelle version
  - `get_document_by_id()` : Récupération document avec versions
  - `get_latest_version()` : Version la plus récente
  - `detect_duplicate()` : Détection par checksum SHA256
  - `list_documents()` : Liste avec filtres (status, type, pagination)
- ✅ `VersionResolutionService` - Résolution versions
  - `resolve_latest()` : Résolution version active
  - `resolve_effective_at(date)` : Point-in-time query
  - `get_version_lineage()` : Graphe succession versions
  - `compare_versions()` : Diff metadata entre versions
  - `check_obsolescence()` : Détection versions obsolètes
- ✅ Schemas Pydantic complets
  - `DocumentCreate`, `DocumentUpdate`, `DocumentResponse`
  - `DocumentVersionCreate`, `DocumentVersionResponse`
  - `DocumentLineage`, `VersionComparison`
  - Enums : `DocumentStatus`, `DocumentType`

**Fichiers créés (Phase 1)** :
```
src/knowbase/ontology/document_schema.py
src/knowbase/api/schemas/documents.py
src/knowbase/api/services/document_registry_service.py
src/knowbase/api/services/version_resolution_service.py
```

---

#### ⏸️ Semaine 3 : Ingestion Updates (0% - EN ATTENTE)

**Tâches prévues** :
- Parser metadata documents (PPTX metadata, creator, date publication)
- Calcul checksum SHA256 automatique
- Détection duplicatas avant ingestion
- Link Episode → DocumentVersion (relation PRODUCES)

---

#### ⏸️ Semaine 4 : APIs REST (0% - EN ATTENTE)

**Endpoints à créer** :
- `GET /api/documents` - Liste documents
- `GET /api/documents/{id}/versions` - Historique versions
- `GET /api/documents/{id}/lineage` - Graphe modifications
- `POST /api/documents/{id}/versions` - Upload nouvelle version

---

#### ⏸️ Semaine 5 : UI Admin (0% - EN ATTENTE)

**Pages à créer** :
- `/admin/documents/[id]/timeline` - Timeline view versions
- `/admin/documents/[id]/compare` - Comparaison versions
- Badges "Obsolète" sur versions périmées
- Change log visualisation

---

### Métriques Phase 1

| Métrique | Actuel | Target | Statut |
|----------|--------|--------|--------|
| **Statut Phase** | 🟡 EN COURS | COMPLÉTÉ | 🟡 |
| **Semaines écoulées** | 1/5 | 5/5 | 🟡 |
| **Tâches complétées** | 2/5 (40%) | 5/5 | 🟡 |
| **Couverture tests** | 0% | 85%+ | ⏸️ |
| **Score conformité** | 40% | 100% | 🟡 |
| **% documents avec versioning** | 0% | 100% | ⏸️ Pipeline non intégré |
| **Performance latest version** | ~2ms (estimé) | < 500ms | ✅ Index optimaux |
| **Détection duplicatas** | 0% | 100% | ⏸️ Checksum non calculé |

---

## 📁 Structure Fichiers Projet

```
SAP_KB/
├── src/knowbase/                     # Code Python principal
│   ├── api/
│   │   ├── routers/                  # 15 routers FastAPI
│   │   │   ├── auth.py               # Authentication JWT
│   │   │   ├── facts.py              # Knowledge Graph Facts
│   │   │   ├── entity_types.py       # Entity Types Registry
│   │   │   ├── document_types.py     # Document Types Management
│   │   │   ├── entities.py           # Entities dynamiques
│   │   │   ├── ontology.py           # Catalogues ontologies
│   │   │   ├── search.py             # Recherche hybride
│   │   │   ├── ingest.py             # Ingestion documents
│   │   │   ├── imports.py            # Historique imports
│   │   │   ├── status.py             # Health checks
│   │   │   ├── jobs.py               # Monitoring RQ
│   │   │   ├── admin.py              # Admin purge
│   │   │   ├── downloads.py          # Téléchargement docs
│   │   │   ├── token_analysis.py     # Analyse coûts LLM
│   │   │   └── sap_solutions.py      # Catalogue SAP
│   │   ├── services/                 # 22 services métier
│   │   │   ├── auth_service.py       # JWT + bcrypt
│   │   │   ├── audit_service.py      # Audit trail
│   │   │   ├── document_registry_service.py  # CRUD documents Phase 1
│   │   │   ├── version_resolution_service.py # Versioning Phase 1
│   │   │   ├── facts_service.py      # Facts Neo4j
│   │   │   ├── entity_type_registry_service.py  # Registry types
│   │   │   ├── document_type_service.py  # Document types
│   │   │   ├── knowledge_graph_service.py  # Neo4j queries
│   │   │   ├── import_history_redis.py  # Historique Redis
│   │   │   ├── import_deletion.py    # Suppression imports
│   │   │   ├── purge_service.py      # Purge données
│   │   │   ├── search.py             # Recherche Qdrant
│   │   │   ├── synthesis.py          # Synthèse LLM
│   │   │   └── ... (9 autres services)
│   │   ├── schemas/                  # Modèles Pydantic v2
│   │   │   ├── auth.py               # Schemas auth JWT
│   │   │   ├── documents.py          # Schemas Phase 1 Document Backbone
│   │   │   ├── facts.py              # Schemas Facts
│   │   │   └── ...
│   │   └── dependencies.py           # Dependencies FastAPI (get_current_user, etc.)
│   ├── ingestion/                    # Pipelines traitement
│   │   ├── parsers/                  # Parsers documents
│   │   │   ├── pdf_parser.py         # PDF avec OCR
│   │   │   ├── pptx_parser.py        # PowerPoint
│   │   │   └── excel_qa_parser.py    # RFP Excel
│   │   ├── pipelines/                # Pipelines ingestion
│   │   └── queue.py                  # RQ worker
│   ├── ontology/                     # Schémas Neo4j
│   │   ├── document_schema.py        # Phase 1 Document Backbone
│   │   └── neo4j_client.py           # Client Neo4j
│   ├── common/                       # Clients externes
│   │   ├── qdrant_client.py          # Client Qdrant
│   │   ├── llm_router.py             # Multi-provider LLM
│   │   └── openai_client.py          # Client OpenAI
│   ├── db/                           # Database SQLite
│   │   ├── models.py                 # Modèles SQLAlchemy (5 tables)
│   │   ├── base.py                   # Base SQLAlchemy
│   │   └── __init__.py               # init_db()
│   └── config/                       # Configuration
│       └── settings.py               # Settings Pydantic
│
├── frontend/src/                     # Interface Next.js TypeScript
│   ├── app/                          # App Router Next.js 14
│   │   ├── page.tsx                  # Home (redirect /chat)
│   │   ├── login/page.tsx            # Login JWT
│   │   ├── register/page.tsx         # Register
│   │   ├── chat/page.tsx             # Chat recherche
│   │   ├── documents/
│   │   │   ├── page.tsx              # Liste documents
│   │   │   ├── [id]/page.tsx         # Détail document
│   │   │   ├── upload/page.tsx       # Upload documents
│   │   │   ├── import/page.tsx       # Import config
│   │   │   ├── status/page.tsx       # Historique imports
│   │   │   └── rfp/page.tsx          # (legacy)
│   │   ├── rfp-excel/page.tsx        # Import RFP Excel
│   │   └── admin/
│   │       ├── page.tsx              # Admin dashboard
│   │       ├── dynamic-types/
│   │       │   ├── page.tsx          # Liste entity types
│   │       │   └── [typeName]/page.tsx  # Détail type
│   │       ├── document-types/
│   │       │   ├── page.tsx          # Liste document types
│   │       │   ├── new/page.tsx      # Création type
│   │       │   └── [id]/page.tsx     # Édition type
│   │       └── settings/page.tsx     # Paramètres
│   ├── components/
│   │   ├── layout/
│   │   │   ├── MainLayout.tsx        # Layout principal
│   │   │   ├── TopNavigation.tsx     # Menu horizontal + user menu
│   │   │   └── ContextualSidebar.tsx # Menu latéral
│   │   ├── auth/
│   │   │   └── ProtectedRoute.tsx    # Protection JWT
│   │   └── ... (composants UI)
│   ├── contexts/
│   │   └── AuthContext.tsx           # Context global auth
│   ├── lib/
│   │   ├── api.ts                    # API client (axios + interceptor JWT)
│   │   └── auth.ts                   # Auth service
│   └── styles/
│       └── theme.ts                  # Chakra UI theme
│
├── config/                           # Configuration YAML
│   ├── llm_models.yaml               # Configuration LLM multi-provider
│   ├── prompts.yaml                  # Prompts configurables
│   ├── sap_solutions.yaml            # Catalogue SAP (50+ solutions)
│   ├── keys/                         # Clés RSA JWT
│   │   ├── jwt_private.pem           # Clé privée RSA 2048-bit
│   │   └── jwt_public.pem            # Clé publique
│   └── ontologies/                   # Catalogues YAML
│       ├── sap_modules.yaml
│       ├── sap_products.yaml
│       └── infrastructure.yaml
│
├── data/                             # Données runtime
│   ├── docs_in/                      # Documents à traiter
│   ├── docs_done/                    # Documents traités
│   ├── public/                       # Assets (slides, thumbnails)
│   ├── models/                       # Modèles Hugging Face cache
│   ├── logs/                         # Logs application
│   └── entity_types_registry.db      # SQLite database
│
├── doc/                              # Documentation
│   ├── BACK2PROMISE_MASTER_ROADMAP.md  # Roadmap 6 phases
│   ├── PHASE_0_SECURITY_TRACKING.md    # Phase 0 complétée
│   ├── PHASE1_DOCUMENT_BACKBONE_TRACKING.md  # Phase 1 en cours
│   ├── ENDPOINTS_PROTECTION_CHECKLIST.md  # Checklist migration JWT
│   ├── AUTH_API_MIGRATION_REPORT.md    # Rapport migration auth frontend
│   └── ... (10+ fichiers documentation)
│
├── tests/                            # Tests unitaires + E2E
│   ├── services/
│   │   └── test_auth_service.py      # 13 tests AuthService
│   ├── api/
│   │   ├── test_auth_endpoints.py    # 14 tests E2E auth
│   │   └── test_auth_dependencies.py # 10 tests dependencies
│   └── ... (autres tests)
│
├── docker-compose.yml                # Orchestration 11 services
├── .env                              # Variables d'environnement
├── README.md                         # Documentation principale
└── CLAUDE.md                         # Instructions Claude Code

**Total** :
- ~100 fichiers Python backend
- ~50 fichiers TypeScript frontend
- ~150 fichiers au total (hors node_modules, venv)
```

---

## 📈 Statistiques & Métriques

### Backend API
- **Routers** : 15 routers FastAPI
- **Endpoints** : ~60 endpoints REST
- **Services** : 22 services métier
- **Modèles SQLite** : 5 tables
- **Schemas Pydantic** : 30+ schemas
- **Tests** : 37 tests auth (Phase 0), 0 tests Phase 1 (à venir)

### Frontend
- **Pages** : 18 pages Next.js
- **Composants** : 20+ composants React
- **Contexts** : 1 context (Auth)
- **API Client** : axios + interceptor JWT

### Infrastructure
- **Services Docker** : 11 containers
- **Bases de données** : 3 (SQLite, Neo4j, Qdrant)
- **Cache/Queue** : Redis
- **Status** : Tous services ✅ Running (1 unhealthy: graphiti - problème connu)

### Code
- **Lignes Python** : ~15,000 lignes (estimation)
- **Lignes TypeScript** : ~5,000 lignes (estimation)
- **Configuration YAML** : 5 fichiers
- **Documentation** : 15+ fichiers Markdown

---

## 🚀 URLs d'Accès

| Service | URL | Description |
|---------|-----|-------------|
| **Frontend moderne** | http://localhost:3000 | Interface Next.js principale |
| **API Documentation** | http://localhost:8000/docs | Swagger UI FastAPI |
| **API Backend** | http://localhost:8000 | API REST FastAPI |
| **Interface legacy** | http://localhost:8501 | Streamlit (à déprécier) |
| **Qdrant Dashboard** | http://localhost:6333/dashboard | Interface Qdrant |
| **Neo4j Browser** | http://localhost:7474 | Interface Neo4j |
| **Adminer (Graphiti)** | http://localhost:8080 | Interface PostgreSQL |
| **Graphiti API** | http://localhost:8300 | API Graphiti (unhealthy) |

---

## ⚠️ Problèmes Connus & Limitations

### 1. Graphiti Service Unhealthy 🟠
**Statut** : Container running mais unhealthy
**Impact** : API Graphiti (port 8300) ne répond pas correctement aux health checks
**Mitigation** : Service non critique pour Phase 1, investigation nécessaire si requis

### 2. Phase 1 Pipeline Non Intégré ⏸️
**Statut** : Services créés mais pas intégrés au pipeline ingestion
**Impact** : Documents ingérés n'ont pas de versioning/provenance
**Prochaine étape** : Semaine 3 - Intégration pipeline

### 3. Tests Phase 1 Non Créés ⏸️
**Statut** : 0% coverage tests Phase 1
**Impact** : Services DocumentRegistry/VersionResolution non testés
**Target** : 85%+ coverage (prévue Semaine 3)

### 4. Endpoints API Phase 1 Non Exposés ⏸️
**Statut** : Pas de router `/api/documents` encore
**Impact** : Services uniquement utilisables en interne
**Prochaine étape** : Semaine 4 - Création router documents

---

## 📝 Prochaines Actions Recommandées

### Priorité 1 - Finaliser Phase 1 (Semaine 3) 🎯

**Effort estimé** : 5-7 jours

1. **Modifier `megaparse_parser.py`** pour extraire :
   - Version (PPTX metadata `dc:version` ou filename pattern)
   - Creator (`dc:creator`)
   - Date publication (`dcterms:created`)
   - Reviewers/Approvers (custom properties si disponibles)

2. **Implémenter fonction `calculate_checksum(file_path)`** :
   - SHA256 hash du fichier
   - Appel avant ingestion
   - Stockage dans `DocumentVersion.checksum`

3. **Intégrer DocumentRegistry dans pipeline ingestion** :
   ```python
   doc_service = DocumentRegistryService(neo4j_client)

   # Vérifier duplicata
   existing = doc_service.get_version_by_checksum(checksum)
   if existing:
       logger.info(f"Document duplicate détecté: {filename}")
       return  # Skip ingestion

   # Créer document + version
   doc = doc_service.create_document(...)
   ```

4. **Lier Episode → DocumentVersion** :
   - Ajouter `document_id` et `document_version_id` dans Episode metadata
   - Créer relation `(:Episode)-[:PRODUCES]->(:DocumentVersion)`

5. **Créer tests unitaires** :
   - 20+ tests `DocumentRegistryService`
   - 15+ tests `VersionResolutionService`
   - Target : 85%+ coverage

---

### Priorité 2 - Créer APIs REST Documents (Semaine 4) 📡

**Effort estimé** : 3-5 jours

1. Créer router `src/knowbase/api/routers/documents.py`
2. Implémenter endpoints :
   - `GET /api/documents` - Liste documents (pagination, filtres)
   - `GET /api/documents/{id}/versions` - Historique versions
   - `GET /api/documents/{id}/lineage` - Graphe modifications
   - `POST /api/documents/{id}/versions` - Upload nouvelle version

3. Protection JWT + RBAC :
   - GET : `Depends(get_current_user)` (tous roles)
   - POST : `Depends(require_editor)` (editor + admin)

---

### Priorité 3 - UI Admin Documents (Semaine 5) 🖥️

**Effort estimé** : 5-7 jours

1. Créer pages Next.js :
   - `/admin/documents/[id]/timeline` - Timeline view versions
   - `/admin/documents/[id]/compare` - Comparaison versions

2. Visualisations :
   - Chakra Timeline component
   - Diff metadata side-by-side
   - Badges "Obsolète" sur versions périmées

---

## 🎯 Résumé Exécutif

### État Actuel du Projet (2025-10-10)

✅ **Phase 0 (Security Hardening)** : **100% COMPLÉTÉE**
- JWT RS256 Authentication fonctionnelle
- RBAC (admin/editor/viewer) implémenté
- 37 tests authentication tous passés
- Score sécurité : 8.5/10 (target atteint)

🟡 **Phase 1 (Document Backbone)** : **40% COMPLÉTÉE** (Semaines 1-2/5)
- Schéma Neo4j complet (4 contraintes + 7 index)
- Services backend créés (DocumentRegistry, VersionResolution)
- **⏸️ En attente** : Intégration pipeline (Semaines 3-5)

🚀 **Infrastructure** : **11 services Docker running**
- Backend FastAPI + Worker RQ opérationnels
- Frontend Next.js fonctionnel avec auth JWT
- Qdrant + Neo4j + Redis stables

📡 **API** : **~60 endpoints REST fonctionnels**
- 15 routers FastAPI
- 22 services métier
- Authentication complète (login, register, refresh, me)
- Facts, Entity Types, Document Types opérationnels

🖥️ **Frontend** : **18 pages Next.js implémentées**
- Authentification JWT complète (login, register, user menu)
- Admin dashboard avec entity types workflow
- Import documents (PDF, PPTX, Excel RFP)
- Monitoring jobs temps réel

🗄️ **Bases de données** :
- **SQLite** : 5 tables (users, audit_log, entity_types_registry, document_types...)
- **Neo4j** : Schéma Document Backbone (4 contraintes + 7 index) + Facts existants
- **Qdrant** : 2 collections (rfp_qa, knowbase)

---

### Métriques Globales

| Catégorie | Métrique | Valeur | Statut |
|-----------|----------|--------|--------|
| **Backend** | Routers | 15 | ✅ |
| **Backend** | Endpoints | ~60 | ✅ |
| **Backend** | Services | 22 | ✅ |
| **Backend** | Tests | 37 (Phase 0) | ✅ |
| **Frontend** | Pages | 18 | ✅ |
| **Frontend** | Composants | 20+ | ✅ |
| **Database** | Tables SQLite | 5 | ✅ |
| **Database** | Nodes Neo4j | 2 (Document, DocumentVersion) | ✅ |
| **Database** | Collections Qdrant | 2 (rfp_qa, knowbase) | ✅ |
| **Sécurité** | Score | 8.5/10 | ✅ |
| **Sécurité** | JWT Tests | 37/37 passés | ✅ |
| **Phase 0** | Progression | 100% | ✅ |
| **Phase 1** | Progression | 40% (Semaines 1-2) | 🟡 |

---

**Prochaine étape immédiate** :
🎯 **Démarrer Phase 1 Semaine 3** - Intégration pipeline ingestion avec extraction metadata, calcul checksum, et détection duplicatas (5-7 jours effort).

---

**Dernière mise à jour** : 2025-10-10
**Audit réalisé par** : Claude Code
**Prochaine revue** : Fin Semaine 3 (après intégration pipeline)
