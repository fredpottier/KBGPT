# Guide Developpeur OSMOSIS

> **Niveau de fiabilite** : Code-verified (Mars 2026). Structure, routers et pages verifies contre le filesystem. Les feature flags et configs peuvent evoluer — toujours verifier les fichiers YAML.

*Document consolide — Mars 2026*

---

## 1. Structure du code

### Backend Python

```
src/knowbase/
├── api/                  # FastAPI — routers, services, schemas
│   ├── routers/          # 38 routers (voir section 2)
│   ├── services/         # Logique metier (search, synthesis, backup, etc.)
│   └── schemas/          # Modeles Pydantic (requetes/reponses)
├── claimfirst/           # Pipeline ClaimFirst — orchestration + worker
├── stratified/           # Pipeline Stratifie V2 — passes 0-3
├── extraction_v2/        # Extraction Docling + Vision (GPT-4o)
│   ├── extractors/       # Extracteurs par format (docling, pptx)
│   ├── vision/           # Analyseur vision slides
│   └── pipeline.py       # Pipeline d'extraction V2
├── retrieval/            # Qdrant Layer R, rechunker, recherche vectorielle
├── facets/               # Facet Engine V2
├── ingestion/            # Import, burst, queue RQ, folder watcher
├── common/               # Clients externes (Qdrant, Neo4j, OpenAI, embeddings)
├── config/               # Settings Pydantic, feature flags
├── db/                   # Modeles SQLAlchemy (PostgreSQL)
├── agents/               # Agents IA specialises
├── audit/                # Audit trail
├── consolidation/        # Consolidation cross-document
├── domain_packs/         # Packs de domaine (ontologies exportables)
├── entity_resolution/    # Resolution d'entites
├── hygiene/              # Nettoyage KG
├── linguistic/           # Analyse linguistique
├── logging/              # Configuration logging structuree
├── memory/               # Memoire conversationnelle
├── navigation/           # Navigation dans le corpus
├── neo4j_custom/         # Requetes Neo4j specifiques
├── ontology/             # Ontologie apprise + domain context injector
├── relations/            # Detection de relations
├── rules/                # Business rules
├── semantic/             # Couche semantique OSMOSE
├── structural/           # Graphe structurel (Docling)
├── ui/                   # Interface Streamlit (legacy)
├── utils/                # Utilitaires generaux
└── verification/         # Verification de claims
```

### Frontend Next.js

```
frontend/src/
├── app/                  # App Router Next.js 14
│   ├── page.tsx          # Page d'accueil
│   ├── layout.tsx        # Layout principal
│   ├── chat/             # Interface de recherche conversationnelle
│   ├── documents/        # Gestion documents
│   │   ├── import/       # Import de documents
│   │   ├── upload/       # Upload direct
│   │   ├── status/       # Suivi statut import
│   │   ├── rfp/          # RFP Excel
│   │   └── [id]/         # Detail document
│   ├── wiki/             # Wiki genere
│   ├── compare/          # Comparaison documents
│   ├── verify/           # Verification de claims
│   ├── analytics/        # Tableaux de bord
│   ├── rfp-excel/        # Import Q/A RFP
│   ├── admin/            # Pages administration
│   │   ├── backup/       # Backup & restore
│   │   ├── benchmarks/   # Benchmark runner + radars D3
│   │   ├── burst/        # Controle du mode Burst
│   │   ├── claimfirst/   # Pilotage ClaimFirst
│   │   ├── contradictions/  # Detection contradictions
│   │   ├── corpus-audit/    # Audit du corpus
│   │   ├── corpus-intelligence/ # Intelligence corpus
│   │   ├── domain-context/  # Contexte de domaine
│   │   ├── domain-packs/    # Packs de domaine
│   │   ├── gpu/          # Statut GPU
│   │   ├── kg-hygiene/   # Hygiene Knowledge Graph
│   │   ├── living-ontology/ # Ontologie vivante
│   │   ├── markers/      # Markers de qualite
│   │   ├── post-import/  # Actions post-import
│   │   ├── settings/     # Parametres
│   │   └── wiki-generator/ # Generateur Wiki
│   └── api/              # Routes API Next.js
├── components/           # Composants React reutilisables
└── lib/                  # Utilitaires et helpers
```

### Configuration

```
config/
├── feature_flags.yaml              # Feature flags (voir section 4.1)
├── llm_models.yaml                 # Mapping taches -> modeles LLM
├── prompts.yaml                    # Prompts configurables par famille
├── semantic_intelligence_v2.yaml   # Config intelligence semantique
├── visibility_policies.yaml        # Politiques de visibilite
├── canonicalization_thresholds.yaml # Seuils de canonicalisation
├── agents/                         # Config agents IA
├── meta_patterns/                  # Patterns meta
├── neo4j/                          # Scripts Neo4j
├── normalization/                  # Regles de normalisation
├── ontologies/                     # Ontologies de domaine
└── rules/                          # Business rules YAML
```

---

## 2. API Endpoints

L'API FastAPI expose 38 routers. Point d'entree : `src/knowbase/api/main.py`.

### Routers principaux

| Router | Fichier | Description |
|--------|---------|-------------|
| `search` | `search.py` | Recherche semantique — intent resolver, retriever, chunk organizer |
| `documents` | `documents.py` | CRUD documents |
| `imports` | `imports.py` | Declenchement et suivi d'imports |
| `ingest` | `ingest.py` | Ingestion directe de documents |
| `claims` | `claims.py` | Acces aux claims extraites |
| `entities` | `entities.py` | Acces aux entites |
| `concepts` | `concepts.py` | Gestion des concepts canoniques |
| `wiki` | `wiki.py` | Generation de wiki |
| `backup` | `backup.py` | Backup et restauration |
| `benchmarks` | `benchmarks.py` | Runner de benchmark |
| `burst` | `burst.py` | Controle du mode Burst EC2 |
| `claimfirst` | `claimfirst.py` | Pipeline ClaimFirst |
| `post_import` | `post_import.py` | Actions post-import (bridge, embeddings) |
| `token_analysis` | `token_analysis.py` | Analyse de tokens |

### Routers secondaires

| Router | Description |
|--------|-------------|
| `admin` | Administration generale |
| `analytics` | Metriques et statistiques |
| `auth` | Authentification |
| `challenge` | Challenge de claims |
| `corpus_intelligence` | Intelligence sur le corpus |
| `document_types` | Types de documents |
| `domain_context` | Contexte de domaine client |
| `domain_packs` | Packs de domaine exportables |
| `downloads` | Telechargement de fichiers |
| `entity_resolution` | Resolution d'entites |
| `entity_types` | Types d'entites |
| `facts` | Faits extraits |
| `gpu` | Statut GPU |
| `insights` | Insights corpus |
| `jobs` | Gestion des jobs RQ |
| `kg_hygiene` | Hygiene du Knowledge Graph |
| `living_ontology` | Ontologie apprise |
| `markers` | Markers de qualite |
| `navigation` | Navigation corpus |
| `ontology` | Ontologie statique |
| `sessions` | Sessions utilisateur |
| `solutions` | Catalogue solutions |
| `status` | Statut systeme |
| `verify` | Verification de claims |

---

## 3. Frontend Pages

### Pages publiques

| Route | Description |
|-------|-------------|
| `/` | Page d'accueil |
| `/chat` | Interface de recherche conversationnelle OSMOSIS |
| `/documents/import` | Import de documents |
| `/documents/upload` | Upload direct |
| `/documents/status` | Suivi des imports en cours |
| `/documents/[id]` | Detail d'un document |
| `/documents/rfp` | RFP par document |
| `/rfp-excel` | Import Q/A RFP Excel |
| `/wiki` | Wiki genere |
| `/compare` | Comparaison de documents |
| `/verify` | Verification de claims |
| `/analytics` | Tableaux de bord analytiques |

### Pages administration (`/admin`)

| Route | Description |
|-------|-------------|
| `/admin` | Dashboard admin |
| `/admin/backup` | Backup et restauration |
| `/admin/benchmarks` | Benchmark runner avec radars D3 |
| `/admin/burst` | Controle du mode Burst EC2 Spot |
| `/admin/claimfirst` | Pilotage du pipeline ClaimFirst |
| `/admin/contradictions` | Detection de contradictions |
| `/admin/corpus-audit` | Audit du corpus |
| `/admin/corpus-intelligence` | Intelligence sur le corpus |
| `/admin/domain-context` | Configuration du contexte de domaine |
| `/admin/domain-packs` | Gestion des packs de domaine |
| `/admin/gpu` | Statut GPU et ressources |
| `/admin/kg-hygiene` | Hygiene du Knowledge Graph |
| `/admin/living-ontology` | Ontologie apprise et vivante |
| `/admin/markers` | Markers de qualite |
| `/admin/post-import` | Actions post-import |
| `/admin/settings` | Parametres generaux |
| `/admin/wiki-generator` | Generateur de Wiki |

---

## 4. Configuration

### 4.1 Feature Flags (`config/feature_flags.yaml`)

Les feature flags controlent l'activation des fonctionnalites sans modification de code.

**Usage dans le code :**

```python
from knowbase.config.feature_flags import is_feature_enabled, get_feature_config

if is_feature_enabled("stratified_pipeline_v2"):
    # Utiliser le pipeline stratifie V2
    ...

config = get_feature_config("llm_calibration")
```

**Flags principaux :**

| Bloc | Flag | Role |
|------|------|------|
| `stratified_pipeline_v2` | `enabled` | Pipeline principal d'ingestion |
| | `pass1_v22` | Extract-then-Structure V2.2 |
| | `enable_pointer_mode` | Mode pointeur (anti-reformulation) |
| | `strict_promotion` | Promotion stricte des concepts |
| `hybrid_intelligence` | `enable_hybrid_extraction` | Route segments LOW_QUALITY_NER vers LLM |
| | `enable_document_context` | Resume document pour desambiguisation |

**Architecture** : 1 instance = 1 client, donc chaque client a son propre `feature_flags.yaml`. Le `tenant_id` reste "default".

### 4.2 Modeles LLM (`config/llm_models.yaml`)

Mapping declaratif tache -> modele. Modifier ce fichier pour changer les modeles sans toucher au code.

| Tache | Modele par defaut | Usage |
|-------|-------------------|-------|
| `vision` | gpt-4o | Analyse multimodale (slides, images) |
| `metadata` | gpt-4o | Extraction metadonnees JSON |
| `long_summary` | qwen3.5:9b-q8_0 | Resumes de textes longs |
| `enrichment` | qwen3.5:9b-q8_0 | Enrichissement de contenu |
| `classification` | qwen3.5:9b-q8_0 | Classification binaire rapide |
| `canonicalization` | gpt-4o | Canonicalisation de noms |
| `knowledge_extraction` | qwen3.5:9b-q8_0 | Extraction structuree (concepts, facts) |
| `translation` | qwen3.5:9b-q8_0 | Traduction |
| `rfp_question_analysis` | gpt-4o | Analyse questions RFP |

**Strategie tiered** : Qwen local (ingestion batch) + Haiku 3.5 (synthese production) + Claude Sonnet (raisonnement complexe/juge).

### 4.3 Prompts (`config/prompts.yaml`)

Les prompts sont generiques par defaut. Le contexte metier specifique est injecte dynamiquement via le Domain Context (`src/knowbase/ontology/domain_context_injector.py`).

Familles de prompts :
- `assertion_synthesis` — Synthese en assertions verifiables
- Prompts d'extraction, classification, enrichissement (configures par tache)

---

## 5. Flux d'import document

### Etape 0 : Verification du cache

Le systeme calcule le hash MD5 du fichier et cherche dans `data/extraction_cache/`. Si un fichier `.knowcache.json` existe et correspond, l'extraction est instantanee (< 1s au lieu de 15-20 min).

### Etape 1 : Extraction (Pipeline V2)

Selon le format :
- **PDF** : Extraction via Docling (structural graph) -> TypeAwareChunks
- **PPTX** : Extraction native python-pptx + reconstruction de slides (speaker notes incluses)
- **Vision optionnelle** : GPT-4o pour slides/pages avec schemas, diagrammes, tableaux

### Etape 2 : Rechunking

Les TypeAwareChunks sont passes dans le rechunker (`src/knowbase/retrieval/rechunker.py`) :
- Target : 1500 caracteres, overlap 200
- Prefixe contextuel ajoute a chaque chunk

### Etape 3 : Ingestion dans les stores

- **Qdrant** : Chunks vectorises (embeddings multilingual-e5-large) dans la collection `knowbase_chunks_v2`
- **Neo4j** : Claims, entities, relations dans le Knowledge Graph
- **Bridge claim-chunk** : Table de correspondance claim <-> chunk pour tracabilite

### Etape 4 : Post-import

Scripts de post-traitement (`/admin/post-import`) :
- Backfill bridge claim-chunk
- Backfill embeddings de claims
- Detection de contradictions

### Pipeline ClaimFirst

Le mode ClaimFirst (`src/knowbase/claimfirst/`) decompose les documents en claims atomiques avant vectorisation. Chaque claim est une assertion verifiable rattachee a un passage source.

---

## 6. Tests et Qualite

### Tests unitaires et integration

```bash
# Tests en local (PAS dans Docker)
python -m pytest

# Tests avec couverture
python -m pytest --cov=src/knowbase

# Tests specifiques
python -m pytest tests/semantic/test_infrastructure.py -v
```

**Note** : Le module `knowbase.common.llm_router` a des dependances lourdes — toujours le mocker dans les tests.

### Linting et formatage

```bash
# Via Docker
docker-compose exec app ruff check src/
docker-compose exec app ruff format src/
docker-compose exec app mypy src/

# Frontend
cd frontend && npm run lint
cd frontend && npm run build
```

### Benchmark

Le benchmark OSMOSIS teste 275+20 questions avec un systeme dual-juge (Qwen + Claude).

```bash
# Canary test rapide (15 questions)
python benchmark/canary_test.py

# Benchmark complet
python benchmark/runners/run_osmosis.py

# Comparaison de runs
python benchmark/compare_runs.py
```

Metriques clefs : `factual`, `relevant`, `false_idk`, `false_answer`.
Seuil de qualite : `factual >= 0.8` = reponse correcte, `false_answer < 15%`.

---

## 7. Conventions

### Messages de commit (francais)

```
feat: ajouter support format DOCX
fix: corriger recherche cascade RFP
refactor: optimiser pipeline PDF
docs: mettre a jour documentation API
```

### Branches

| Prefixe | Usage |
|---------|-------|
| `main` | Production stable |
| `feat/*` | Nouvelles fonctionnalites |
| `fix/*` | Corrections de bugs |
| `refactor/*` | Refactoring code |

### Nommage

- **Modules Python** : snake_case (`burst_orchestrator.py`)
- **Classes** : PascalCase (`BurstOrchestrator`)
- **Feature flags** : snake_case (`enable_hybrid_extraction`)
- **Collections Qdrant** : snake_case (`knowbase_chunks_v2`)
- **Logs** : Prefixe `[OSMOSE]` pour les logs projet

### Documentation

- Toute documentation en francais
- Structure stricte dans `doc/` (voir `CLAUDE.md` pour les regles)
- Docs temporaires dans `doc/ongoing/`

---

## 8. Variables d'environnement

### Fichier `.env` (variables principales)

```bash
# ===== API Keys (REQUIS) =====
OPENAI_API_KEY=sk-proj-...
ANTHROPIC_API_KEY=sk-ant-...

# ===== Debug =====
DEBUG_APP=false          # Debug FastAPI sur port 5678
DEBUG_WORKER=false       # Debug Worker sur port 5679

# ===== Ports =====
APP_PORT=8000            # FastAPI
FRONTEND_PORT=3000       # Next.js
APP_UI_PORT=8501         # Streamlit

# ===== Infrastructure =====
NEO4J_PASSWORD=graphiti_neo4j_pass
POSTGRES_PASSWORD=knowbase_secure_pass
REDIS_URL=redis://redis:6379/0

# ===== Worker =====
MAX_DOCUMENT_PROCESSING_TIME=3600   # 1h max par document
BURST_MAX_CONCURRENT_DOCS=2         # Parallelisme burst
CUDA_VISIBLE_DEVICES=0              # GPU device

# ===== Compose =====
COMPOSE_FILE=docker-compose.infra.yml:docker-compose.yml:docker-compose.monitoring.yml
```

### Variables d'environnement injectees par Docker

Ces variables sont definies dans `docker-compose.yml` et non dans `.env` :

- `PYTHONPATH=/app:/app/src`
- `HF_HOME=/data/models` — cache HuggingFace
- `ONNXTR_CACHE_DIR=/data/models/onnxtr` — cache OCR
- `KNOWBASE_DATA_DIR=/data`
- `TZ=Europe/Paris` — timezone pour tous les logs

---

## 9. References archive

Les documents source de ce guide consolide ont ete archives dans :

```
doc/archive/pre-rationalization-2026-03/
├── guides/
│   ├── FEATURE_FLAGS_GUIDE.md          # Guide complet feature flags
│   └── kw.README.md                    # Documentation script kw.ps1
└── specs/
    └── ingestion/
        └── SPEC-PROCESSUS_IMPORT_DOCUMENT.md  # Specification import detaillee
```

---

*Derniere mise a jour : 2026-03-29*
