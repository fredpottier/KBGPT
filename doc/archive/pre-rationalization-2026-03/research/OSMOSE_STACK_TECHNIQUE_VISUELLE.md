# 🏗️ Stack Technique OSMOSE - Architecture Visuelle

*Documentation de l'architecture complète du système KnowWhere/OSMOSE*

---

## 📊 Vue d'Ensemble - Architecture en Couches

```
┌─────────────────────────────────────────────────────────────────────┐
│                          COUCHE PRÉSENTATION                         │
│  ┌───────────────────────────────────────────────────────────────┐  │
│  │                    FRONTEND (Next.js 14)                       │  │
│  │                    Port: 3000                                  │  │
│  │  - Interface utilisateur moderne (React/TypeScript)            │  │
│  │  - Pages: Chat, Import, Search, RFP                            │  │
│  │  - Communication API REST avec Backend                         │  │
│  └───────────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────────┘
                                    │
                                    │ HTTP REST
                                    ▼
┌─────────────────────────────────────────────────────────────────────┐
│                          COUCHE APPLICATION                          │
│  ┌───────────────────────────────────────────────────────────────┐  │
│  │                   BACKEND (FastAPI)                            │  │
│  │                   Port: 8000                                   │  │
│  │  - API REST (routers: search, ingest, chat, purge)            │  │
│  │  - Orchestration des requêtes utilisateur                     │  │
│  │  - Gestion authentification/validation                        │  │
│  │  - Envoi tâches asynchrones à Redis                           │  │
│  └───────────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────────┘
                                    │
                                    │ Redis Queue (RQ)
                                    ▼
┌─────────────────────────────────────────────────────────────────────┐
│                        COUCHE TRAITEMENT                             │
│  ┌───────────────────────────────────────────────────────────────┐  │
│  │                    WORKER (RQ Worker)                          │  │
│  │                    Port: N/A (background)                      │  │
│  │  - Traitement asynchrone des tâches d'ingestion               │  │
│  │  - Exécution pipelines (PDF, PPTX, Excel)                     │  │
│  │  - Orchestration des Agents OSMOSE                            │  │
│  │  - Extraction, transformation, chargement (ETL)               │  │
│  └───────────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────────┘
                                    │
                    ┌───────────────┴───────────────┐
                    ▼                               ▼
┌─────────────────────────────────┐   ┌─────────────────────────────────┐
│      COUCHE INTELLIGENCE        │   │    COUCHE ORCHESTRATION         │
│  ┌───────────────────────────┐  │   │  ┌───────────────────────────┐  │
│  │   AGENTS OSMOSE           │  │   │  │    REDIS (Queue)          │  │
│  │                           │  │   │  │    Port: 6379             │  │
│  │  1. Gatekeeper            │  │   │  │  - Queue tâches RQ        │  │
│  │     - Routage requêtes    │  │   │  │  - Cache temporaire       │  │
│  │     - Filtrage pertinence │  │   │  │  - Pub/Sub events         │  │
│  │                           │  │   │  └───────────────────────────┘  │
│  │  2. Supervisor            │  │   └─────────────────────────────────┘
│  │     - Coordination agents │  │
│  │     - Stratégie réponse   │  │
│  │                           │  │
│  │  3. Extractor             │  │
│  │     - Extraction sémantiq.│  │
│  │     - Enrichissement LLM  │  │
│  └───────────────────────────┘  │
└─────────────────────────────────┘
                    │
        ┌───────────┴───────────┐
        ▼                       ▼
┌─────────────────────┐   ┌─────────────────────┐
│   COUCHE DONNÉES    │   │   COUCHE DONNÉES    │
│                     │   │                     │
│  ┌───────────────┐  │   │  ┌───────────────┐  │
│  │   QDRANT      │  │   │  │    NEO4J      │  │
│  │   Port: 6333  │  │   │  │  Port: 7474   │  │
│  │               │  │   │  │   7687 (bolt) │  │
│  │ - Stockage    │  │   │  │               │  │
│  │   vectoriel   │  │   │  │ - Graph DB    │  │
│  │ - Embeddings  │  │   │  │ - Ontologie   │  │
│  │ - Recherche   │  │   │  │ - Relations   │  │
│  │   sémantique  │  │   │  │ - Entités     │  │
│  │               │  │   │  │ - Proto-KG    │  │
│  │ Collections:  │  │   │  │               │  │
│  │ • knowbase    │  │   │  │ Tenants:      │  │
│  │ • rfp_qa      │  │   │  │ • default     │  │
│  │ • knowwhere_  │  │   │  │ • (multi)     │  │
│  │   proto       │  │   │  │               │  │
│  └───────────────┘  │   │  └───────────────┘  │
└─────────────────────┘   └─────────────────────┘
```

---

## 🔍 Détail des Composants

### 1. FRONTEND (Next.js 14) - Couche Présentation

**Rôle:** Interface utilisateur moderne

**Technologies:**
- Next.js 14 (App Router)
- React 18
- TypeScript
- Tailwind CSS

**Responsabilités:**
- Affichage interface utilisateur
- Gestion état application (Context API)
- Communication avec Backend via fetch API
- Routing pages (/chat, /documents/import, /search, /rfp-excel)

**Interactions:**
- **→ Backend (FastAPI):** Requêtes HTTP REST (GET, POST)
- **← Backend:** Réponses JSON (données, status, erreurs)

**URLs:**
- Interface principale: http://localhost:3000
- Chat: http://localhost:3000/chat
- Import documents: http://localhost:3000/documents/import

---

### 2. BACKEND (FastAPI) - Couche Application

**Rôle:** API REST et orchestration

**Technologies:**
- FastAPI (Python 3.11)
- Pydantic (validation)
- Uvicorn (ASGI server)

**Responsabilités:**
- Exposition API REST (/search, /ingest, /chat, /purge)
- Validation requêtes (Pydantic schemas)
- Authentification/Autorisation
- Routage vers services appropriés
- **Envoi tâches asynchrones à Worker via Redis**

**Structure:**
```
src/knowbase/api/
├── main.py              # Point d'entrée FastAPI
├── dependencies.py      # Injection dépendances
├── routers/            # Endpoints REST
│   ├── search.py
│   ├── ingest.py
│   ├── chat.py
│   └── purge.py
├── services/           # Logique métier
│   ├── search_service.py
│   ├── purge_service.py
│   └── solutions.py
└── schemas/            # Modèles Pydantic
```

**Interactions:**
- **← Frontend:** Requêtes HTTP REST
- **→ Redis:** Enqueue tâches (via RQ - Redis Queue)
- **→ Qdrant:** Recherche vectorielle directe (requêtes search)
- **→ Neo4j:** Requêtes graph (via neo4j_client)
- **→ LLM Providers:** OpenAI, Anthropic (via llm_router)

**URLs:**
- API: http://localhost:8000
- Documentation Swagger: http://localhost:8000/docs
- Status: http://localhost:8000/status

---

### 3. WORKER (RQ Worker) - Couche Traitement

**Rôle:** Traitement asynchrone et orchestration agents

**Technologies:**
- Python RQ (Redis Queue)
- Pipelines ingestion personnalisés

**Responsabilités:**
- **Consommation tâches depuis Redis**
- Exécution pipelines ingestion (PDF, PPTX, Excel)
- Orchestration Agents OSMOSE (Gatekeeper, Supervisor, Extractor)
- Extraction contenu (texte, images, métadonnées)
- Transformation données (chunking, embeddings)
- Chargement dans Qdrant + Neo4j

**Pipelines:**
```
src/knowbase/ingestion/pipelines/
├── pdf_pipeline.py      # Traitement PDF (OCR, extraction)
├── pptx_pipeline.py     # Traitement PowerPoint (slides, images)
└── excel_pipeline.py    # Traitement Excel (Q/A RFP)
```

**Flux de Traitement:**
```
1. Réception tâche depuis Redis
2. Lecture document (data/docs_in/)
3. Extraction contenu (BinaryParser, SlideProcessor)
4. Transformation (LLMAnalyzer, TextUtils)
5. Génération embeddings (OpenAI/Anthropic)
6. Stockage Qdrant (vecteurs)
7. Stockage Neo4j (entités/relations)
8. Déplacement document (data/docs_done/)
9. Mise à jour status (.status files)
```

**Interactions:**
- **← Redis:** Récupération tâches (dequeue)
- **→ Agents OSMOSE:** Appel orchestration
- **→ Qdrant:** Insertion vecteurs (upsert)
- **→ Neo4j:** Insertion entités/relations (Cypher)
- **→ LLM Providers:** Analyse contenu, génération embeddings

---

### 4. AGENTS OSMOSE - Couche Intelligence

**Rôle:** Intelligence sémantique et orchestration

#### 4.1 Gatekeeper (Agent de Routage)

**Fichier:** `src/knowbase/agents/gatekeeper/gatekeeper.py`

**Responsabilités:**
- Analyse requête utilisateur
- Détermination type requête (search, chat, explain)
- Filtrage pertinence
- Routage vers Supervisor

**Interactions:**
- **← Worker/Backend:** Requête utilisateur brute
- **→ Supervisor:** Requête enrichie + contexte

#### 4.2 Supervisor (Agent de Coordination)

**Fichier:** `src/knowbase/agents/supervisor/supervisor.py`

**Responsabilités:**
- Coordination stratégie réponse
- Planification étapes traitement
- Orchestration Extractor
- Synthèse finale

**Interactions:**
- **← Gatekeeper:** Requête enrichie
- **→ Extractor:** Demandes extraction
- **→ Backend:** Réponse finale

#### 4.3 Extractor (Agent d'Extraction)

**Fichier:** `src/knowbase/agents/extractor/orchestrator.py`

**Responsabilités:**
- Extraction sémantique ciblée
- Enrichissement LLM
- Recherche vectorielle (Qdrant)
- Requêtes graph (Neo4j)

**Interactions:**
- **← Supervisor:** Requêtes extraction
- **→ Qdrant:** Recherche similarité
- **→ Neo4j:** Requêtes Cypher
- **→ LLM:** Enrichissement/Analyse

---

### 5. REDIS - Couche Orchestration

**Rôle:** Queue de tâches et cache

**Technologies:**
- Redis 7.x
- RQ (Redis Queue)

**Responsabilités:**
- **Gestion queue tâches asynchrones** (Backend → Worker)
- Cache temporaire (sessions, résultats intermédiaires)
- Pub/Sub pour événements temps réel
- Monitoring état tâches

**Collections Redis:**
- `rq:queue:default`: Queue tâches ingestion
- `rq:job:*`: Métadonnées jobs
- Cache: Résultats recherche, sessions

**Interactions:**
- **← Backend:** Enqueue tâches (LPUSH)
- **→ Worker:** Dequeue tâches (BRPOP)
- **↔ Backend/Worker:** Cache (GET/SET)

**URL:**
- Port: 6379 (pas d'interface web par défaut)

---

### 6. QDRANT - Couche Données Vectorielles

**Rôle:** Base de données vectorielle (embeddings)

**Technologies:**
- Qdrant 1.x
- HNSW index (Hierarchical Navigable Small World)

**Responsabilités:**
- Stockage embeddings (vecteurs 1536 dimensions pour OpenAI)
- Recherche par similarité sémantique (cosine similarity)
- Filtrage par métadonnées (tenant_id, document_type)
- Gestion collections multiples

**Collections:**
- `knowbase`: Base de connaissances générale (seuil 0.70)
- `rfp_qa`: Questions/Réponses RFP prioritaires (seuil 0.85)
- `knowwhere_proto`: Proto-KG OSMOSE (Phase 1)

**Structure Payload:**
```json
{
  "text": "Contenu textuel chunk",
  "document_name": "presentation.pptx",
  "tenant_id": "default",
  "slide_number": 5,
  "metadata": {...}
}
```

**Interactions:**
- **← Worker:** Insertion vecteurs (upsert)
- **← Backend/Extractor:** Recherche (search)
- **→ Backend:** Résultats + scores similarité

**URLs:**
- Dashboard: http://localhost:6333/dashboard
- API: http://localhost:6333

---

### 7. NEO4J - Couche Données Graphe

**Rôle:** Base de données graphe (ontologie, relations)

**Technologies:**
- Neo4j 5.x
- Cypher Query Language
- APOC plugins

**Responsabilités:**
- Stockage ontologie sémantique (entités, concepts)
- Gestion relations entre entités (RELATES_TO, IS_PART_OF)
- Multi-tenancy (propriété tenant_id sur tous les nœuds)
- Proto-KG OSMOSE (Phase 1: Semantic Core)

**Modèle de Données:**
```cypher
// Exemple de structure
(Document {tenant_id, name, type})
  -[:CONTAINS]->
(Entity {tenant_id, name, type, canonical_name})
  -[:RELATES_TO {type, confidence}]->
(Entity)

(Concept {tenant_id, name, domain})
  -[:IS_INSTANCE_OF]->
(Category)
```

**Constraints:**
```cypher
CREATE CONSTRAINT entity_unique
  FOR (e:Entity)
  REQUIRE (e.tenant_id, e.canonical_name) IS UNIQUE;

CREATE CONSTRAINT document_unique
  FOR (d:Document)
  REQUIRE (d.tenant_id, d.name) IS UNIQUE;
```

**Interactions:**
- **← Worker:** Insertion entités/relations (CREATE/MERGE Cypher)
- **← Extractor:** Requêtes graph (MATCH Cypher)
- **→ Backend:** Résultats requêtes (relations, chemins)

**URLs:**
- Neo4j Browser: http://localhost:7474
- Bolt: bolt://localhost:7687
- Credentials: neo4j / graphiti_neo4j_pass

---

## 🔄 Flux de Données Principaux

### Flux 1: Import Document (Ingestion Asynchrone)

```
1. [Frontend] Upload fichier → POST /ingest
2. [Backend] Validation + sauvegarde data/docs_in/
3. [Backend] Enqueue tâche → Redis (RQ)
4. [Worker] Dequeue tâche ← Redis
5. [Worker] Exécution pipeline (pdf/pptx/excel)
   5.1 Extraction contenu (BinaryParser)
   5.2 Chunking + Analyse (LLMAnalyzer)
   5.3 Génération embeddings (OpenAI API)
6. [Worker] Stockage Qdrant (vecteurs)
7. [Worker] Stockage Neo4j (entités/relations)
8. [Worker] Déplacement data/docs_done/
9. [Frontend] Polling status → GET /status/{job_id}
```

### Flux 2: Recherche Sémantique (Synchrone)

```
1. [Frontend] Requête search → POST /search
2. [Backend] Validation query
3. [Backend] Recherche Qdrant (similarity search)
   3.1 Collection rfp_qa (seuil 0.85)
   3.2 Collection knowbase (seuil 0.70) si pas de résultats
4. [Qdrant] Retour top-k résultats + scores
5. [Backend] Enrichissement Neo4j (relations entités)
6. [Backend] Réponse JSON → Frontend
7. [Frontend] Affichage résultats
```

### Flux 3: Chat Intelligent (OSMOSE Agents)

```
1. [Frontend] Question chat → POST /chat
2. [Backend] Enqueue tâche → Redis
3. [Worker] Dequeue tâche
4. [Gatekeeper] Analyse requête
   4.1 Classification type (search/explain/chat)
   4.2 Extraction intent
5. [Supervisor] Coordination
   5.1 Planification stratégie
   5.2 Orchestration Extractor
6. [Extractor] Extraction sémantique
   6.1 Recherche Qdrant (embeddings)
   6.2 Requêtes Neo4j (graph)
   6.3 Enrichissement LLM
7. [Supervisor] Synthèse finale
8. [Backend] Réponse → Frontend
9. [Frontend] Affichage conversation
```

### Flux 4: Purge Système (Multi-sources)

```
1. [Frontend] Demande purge → POST /purge
2. [Backend] Orchestration purge
3. [Backend] → Redis FLUSHDB (queue)
4. [Backend] → Qdrant DELETE collections
5. [Backend] → Neo4j DETACH DELETE (tenant_id)
6. [Backend] → Filesystem cleanup (docs_in, docs_done, status)
7. [Backend] ⚠️ Préservation data/extraction_cache/ (CRITIQUE)
8. [Backend] Réponse succès → Frontend
```

---

## 📊 Matrice des Responsabilités

| Composant | Stockage | Traitement | Orchestration | Interface |
|-----------|----------|------------|---------------|-----------|
| **Frontend** | - | - | - | ✅ UI/UX |
| **Backend** | - | Validation | ✅ API REST | ✅ HTTP |
| **Worker** | - | ✅ ETL | ✅ Pipelines | - |
| **Redis** | ✅ Queue | - | ✅ Tasks | - |
| **Qdrant** | ✅ Vecteurs | ✅ Similarité | - | - |
| **Neo4j** | ✅ Graphe | ✅ Requêtes | - | - |
| **Agents** | - | ✅ IA | ✅ Logique | - |

---

## 🔐 Sécurité et Bonnes Pratiques

### Multi-Tenancy
- **Qdrant:** Filtrage par `tenant_id` dans payload
- **Neo4j:** Propriété `tenant_id` sur tous les nœuds
- **Backend:** Injection `tenant_id` automatique (dependencies.py)

### Gestion Secrets
- Variables `.env` pour API Keys
- Jamais de credentials en dur dans code
- Docker secrets pour production

### Cache et Performance
- ⚠️ **CRITIQUE:** `data/extraction_cache/` JAMAIS supprimé lors purge
- Cache Redis pour résultats fréquents
- Indexes Neo4j sur `tenant_id` + `canonical_name`
- HNSW Qdrant pour recherche rapide

---

## 📈 Monitoring et Observabilité

### Logs
```bash
# Logs par service
docker-compose logs -f app       # Backend
docker-compose logs -f worker    # Worker
docker-compose logs -f frontend  # Frontend
docker-compose logs -f neo4j     # Neo4j
```

### Métriques
- **Qdrant:** Dashboard collections (http://localhost:6333/dashboard)
- **Neo4j:** Browser stats (http://localhost:7474)
- **Backend:** `/status` endpoint (http://localhost:8000/status)
- **Grafana:** Monitoring (http://localhost:3001) - admin/Rn1lm@tr

### Performance Attendue
- Recherche vectorielle: **< 100ms**
- Ingestion PPTX: **2-5s/doc**
- Ingestion PDF (OCR): **5-15s/doc**
- Synthèse LLM: **1-3s**

---

## 🚀 Commandes Utiles

### Démarrage
```powershell
./kw.ps1 start              # Tout démarrer
./kw.ps1 start infra        # Infrastructure seule
./kw.ps1 start app          # Application seule
```

### Status et Logs
```powershell
./kw.ps1 status             # Status tous services
./kw.ps1 logs app           # Logs backend
./kw.ps1 logs worker        # Logs worker
./kw.ps1 info               # Toutes URLs + credentials
```

### Maintenance
```bash
# Reset Proto-KG (préserve schéma)
docker-compose exec app python scripts/reset_proto_kg.py

# Reset complet (supprime schéma)
docker-compose exec app python scripts/reset_proto_kg.py --full

# Tests infrastructure
docker-compose exec app pytest tests/semantic/test_infrastructure.py -v
```

---

## 📚 Références

- **Architecture complète:** `doc/OSMOSE_ARCHITECTURE_TECHNIQUE.md`
- **Phase 1 (en cours):** `doc/phases/PHASE1_SEMANTIC_CORE.md`
- **Roadmap produit:** `doc/OSMOSE_AMBITION_PRODUIT_ROADMAP.md`
- **Configuration LLM:** `config/llm_models.yaml`
- **Scripts maintenance:** `app/scripts/README.md`

---

*Dernière mise à jour: 2025-11-19*
*Version: OSMOSE Phase 1 - Semantic Core*
