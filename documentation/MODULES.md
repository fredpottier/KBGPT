# Référence des modules Python

Chaque tableau ci-dessous liste les fichiers Python du projet avec leur rôle, les fonctions/classes majeures, leurs dépendances clés et les effets de bord (I/O, réseau, stockage). Les modules de tests (`tests/`, `app/tests/`) sont regroupés en fin de document pour clarté.

## `src/knowbase/api`

### Racine & infrastructure

| Module | Rôle | Fonctions / classes clés | Dépendances | Entrées / effets de bord |
| --- | --- | --- | --- | --- |
| `src/knowbase/api/__init__.py` | Export des routers/services pour usage externe | définit `__all__` | — | — |
| `src/knowbase/api/main.py` | Création de l’app FastAPI, montage statique, inclusion routers | `create_app()` | FastAPI, `configure_logging`, `get_settings`, `warm_clients`, `StaticFiles`, routers | Lit fichiers `openapi.json`, monte dossiers `/static/*` |
| `src/knowbase/api/dependencies.py` | Fabrique les dépendances globales (settings, logging, warm clients) | `get_settings()`, `configure_logging()`, `warm_clients()` | `knowbase.config.settings`, `knowbase.common.clients` | Charge env vars, configure Loguru |

### Middleware & contexte

| Module | Rôle | Fonctions / classes clés | Dépendances | Effets |
| --- | --- | --- | --- | --- |
| `middleware/__init__.py` | Export du middleware | `__all__` | — | — |
| `middleware/user_context.py` | Injecte le contexte multi-tenant dans la requête | `UserContextMiddleware`, `get_user_context()` | FastAPI, `contextvars` | Lit headers HTTP, stocke dans `ContextVar` |

### Schémas Pydantic

| Module | Rôle | Objets principaux | Dépendances | Effets |
| --- | --- | --- | --- | --- |
| `schemas/search.py` | DTO recherche | `SearchRequest`, `SearchResult`, `SearchResponse` | Pydantic | — |
| `schemas/knowledge_graph.py` | DTO KG | `EntityCreate`, `EntityResponse`, `Relation*`, `SubgraphRequest`, `KnowledgeGraphStats`, `RelationType` | Enum, datetime | — |
| `schemas/tenant.py` | DTO Tenants | `Tenant`, `TenantCreate`, `TenantUpdate`, `TenantHierarchy`, `TenantStats` | Pydantic | — |
| `schemas/user.py` | DTO utilisateurs | `User`, `UserCreate`, `UserUpdate`, `UserListResponse` | datetime | — |
| `schemas/facts_governance.py` | DTO facts | `FactCreate`, `FactResponse`, `FactUpdate`, `FactFilters`, `FactStatus`, `ConflictsListResponse`, `FactStats` | Enum, datetime | — |
| `schemas/__init__.py` | regroupe exports | `__all__` | — | — |

### Routers HTTP

| Module | Rôle | Endpoints clés | Services utilisés | Effets |
| --- | --- | --- | --- | --- |
| `routers/search.py` | Recherche vectorielle | `POST /search`, `GET /solutions` | `search_documents`, `get_available_solutions`, clients Qdrant/embeddings | Appels Qdrant |
| `routers/ingest.py` | Ingestion & RFP | `/dispatch`, `/documents/upload-excel-qa`, `/documents/fill-excel-rfp`, `/documents/analyze-excel` | `handle_dispatch`, `handle_excel_qa_upload`, `handle_excel_rfp_fill`, `analyze_excel_file` | Enfile jobs RQ, lit fichiers upload |
| `routers/status.py` | Suivi de job | `GET /api/status/{uid}` | `job_status` | Lit Redis Queue + import history |
| `routers/imports.py` | Historique imports | `GET /history`, `GET /active`, `POST /sync`, `POST /cleanup`, `DELETE /{uid}/delete` | `RedisImportHistoryService`, `delete_import_completely` | Accès Redis DB1, Qdrant, filesystem |
| `routers/sap_solutions.py` | Dictionnaire SAP | `GET /`, `POST /resolve`, `GET /search/{query}`, `GET /with-chunks` | `SAPSolutionsManager`, Qdrant | Lecture YAML, appels LLM |
| `routers/downloads.py` | Téléchargements | `GET /filled-rfp/{uid}`, `GET /import-files/{uid}` | `RedisImportHistoryService` | Sert des fichiers depuis `presentations_dir`, `docs_*` |
| `routers/token_analysis.py` | Monitoring LLM | `/stats`, `/estimate-deck`, `/compare-providers`, `/cost-by-task`, `/pricing`, `/reset`, `/sagemaker-savings` | `TokenTracker` | Calculs internes |
| `routers/tenants.py` | Gestion Tenants | CRUD, stats, permissions | `TenantService` | Lecture/écriture JSON sur disque |
| `routers/users.py` | Gestion utilisateurs | CRUD, activité, set default | `UserService` | Lecture/écriture JSON |
| `routers/health.py` | Health global/Graphiti | `/`, `/tenants`, `/graphiti`, `/quick` | `TenantService`, HTTPX | Ping Qdrant, Graphiti, lit fichiers |
| `routers/graphiti.py` | API directe Graphiti | Episodes, facts, relations, subgraph, tenants | `GraphitiTenantManager`, `GraphitiStore` | Appels Neo4j/Postgres via Graphiti, isolation par tenant |
| `routers/knowledge_graph.py` | KG multi-tenant | Health, entités, relations, subgraphs, stats | `UserKnowledgeGraphService`, `UserContext` | Appels Graphiti |
| `routers/facts_governance.py` | Gouvernance facts | CRUD, conflicts, timeline, stats | `FactsGovernanceService`, `UserContext` | Graphiti, caches JSON |
| `routers/facts_intelligence.py` | Analytique facts | Confidence, patterns, metrics, alerts | `FactsIntelligenceService`, `FactsGovernanceService` | Appels LLM, analyses locales |
| `routers/knowledge_graph.py` | (voir ci-dessus) | — | — | — |
| `routers/__init__.py` | Exports routers | liste `__all__` | — | — |

### Services métier

| Module | Rôle | Fonctions/classes | Dépendances | Effets |
| --- | --- | --- | --- | --- |
| `services/ingestion.py` | Orchestration ingestion & RFP | `handle_dispatch`, `handle_excel_qa_upload`, `handle_excel_rfp_fill`, `analyze_excel_file`, helpers | Redis history, Qdrant, OpenAI, pandas, openpyxl, filesystem | Sauvegarde fichiers, enfile jobs RQ, canonicalisation LLM |
| `services/search.py` | Recherche + synthèse | `search_documents`, `get_available_solutions`, `build_response_payload` | Qdrant, SentenceTransformer, reranker, `synthesize_response` | Appels Qdrant, LLM |
| `services/status.py` | Suivi job | `job_status` | RQ jobs, Redis history | Lit / met à jour Redis |
| `services/import_history_redis.py` | Historique Redis | `RedisImportHistoryService` (CRUD) | redis-py, `get_settings` | Lecture/écriture Redis DB1 |
| `services/import_deletion.py` | Suppression complète d’un import | `delete_import_completely` | Qdrant client, filesystem, Redis history | Supprime fichiers, Qdrant points, clés Redis |
| `services/import_history.py` | (legacy file wrapper) | utilitaires d’import | Settings | — |
| `services/synthesis.py` | Synthèse LLM pour recherche | `synthesize_response` | `LLMRouter`, OpenAI/Anthropic | Appels LLM |
| `services/sap_solutions.py` | Dictionnaire solutions | `SAPSolutionsManager` (load/save, canonicalisation) | `LLMRouter`, YAML | Lecture/écriture YAML |
| `services/tenant.py` | Persistence tenants | `TenantService` (CRUD, stats, permissions) | Pydantic, JSON fichiers | I/O disque (`data/tenants/*.json`) |
| `services/user.py` | Persistence utilisateurs | `UserService` (CRUD, default user, activité) | JSON fichiers | I/O disque (`data/users.json`) |
| `services/knowledge_graph.py` | KG corporate | `KnowledgeGraphService` | `GraphitiStore`, caches en mémoire | Appels Graphiti, maintient caches |
| `services/user_knowledge_graph.py` | KG multi-tenant | `UserKnowledgeGraphService` | `KnowledgeGraphService`, `UserService`, `UserContext` | Crée groupes Graphiti, maj JSON utilisateurs |
| `services/facts_governance_service.py` | Gouvernance facts | `FactsGovernanceService` | Graphiti store, caches internes, LLMRouter (pour conflits) | Appels Graphiti, persistance JSON/Graphiti |
| `services/facts_intelligence.py` | IA gouvernance | `FactsIntelligenceService` | `LLMRouter`, `FactsGovernanceService`, analytics pandas-like | Appels LLM, calculs statistiques |
| `services/import_history.py` | utilitaires (si présents) | Fonctions d’agrégat | Settings | — |
| `services/__init__.py` | exports | `__all__` | — | — |

## `src/knowbase/common`

| Module | Rôle | Fonctions / classes | Dépendances | Effets |
| --- | --- | --- | --- | --- |
| `common/__init__.py` | exports | — | — | — |
| `common/logging.py` | Setup Loguru | `setup_logging()` | Loguru, pathlib | Crée dossier logs |
| `common/llm_router.py` | Routage LLM multi-provider | `LLMRouter`, `TaskType`, `complete`, `complete_sagemaker`, helpers | OpenAI SDK, Anthropic SDK, boto3 (optionnel), YAML config, `TokenTracker` | Appels API LLM, SageMaker, lecture config |
| `common/token_tracker.py` | Suivi tokens & coûts | `TokenTracker`, `TokenUsage`, `ModelPricing`, helpers | dataclasses, logging | Sauvegarde optionnelle JSON log |
| `common/clients/__init__.py` | exports clients | `get_qdrant_client`, `get_sentence_transformer`, etc. | qdrant-client, sentence-transformers, openai, anthropic | Télécharge modèles HF, connecte Qdrant |
| `common/clients/qdrant_client.py` | Initialisation Qdrant | `get_qdrant_client`, `ensure_qdrant_collection` | qdrant-client, settings | Crée collections, connecte HTTP |
| `common/clients/embeddings.py` | Charge SentenceTransformer | `get_sentence_transformer` | sentence-transformers, settings | Télécharge modèle dans `models_dir` |
| `common/clients/openai_client.py` | Client OpenAI | `get_openai_client` | openai, settings | Instancie client, gère API key |
| `common/clients/anthropic_client.py` | Client Anthropic | `get_anthropic_client`, `is_anthropic_available` | anthropic | — |
| `common/clients/reranker.py` | Cross-encoder reranking | `get_cross_encoder`, `rerank_chunks` | sentence-transformers, numpy | Télécharge modèle reranker |
| `common/clients/http.py` | HTTP utilitaire (Graphiti) | `HttpClient` wrapper | httpx | — |
| `common/clients/shared_clients.py` | Cache de clients partagés | `SharedClients`, `warm_clients()` | dépendances clients | Précharge modèles/API |
| `common/interfaces/graph_store.py` | Interface Graph store | `GraphStoreProtocol`, dataclasses `FactStatus`, etc. | typing | — |
| `common/interfaces/__init__.py` | exports | — | — | — |
| `common/sap/normalizer.py` | Normalisation solutions SAP | `normalize_solution_name` | regex | — |
| `common/sap/solutions_dict.py` | Dictionnaire statique solutions | Constantes | — | — |
| `common/sap/claims.py` | Gestion des claims SAP | Fonctions utilitaires | JSON | — |
| `common/graphiti/config.py` | Config Graphiti | `GraphitiConfig.from_env()` | os, dataclasses | Lit env vars |
| `common/graphiti/graphiti_store.py` | Wrapper service Graphiti | `GraphitiStore` (CRUD entités, relations, facts, health) | httpx, async, Graphiti API | Requêtes HTTP Graphiti, conversions |
| `common/graphiti/tenant_manager.py` | Gestion multi-tenant Graphiti | `GraphitiTenantManager`, `create_tenant_manager` | `GraphitiStore`, asyncio locks | Maintient mapping groupe→store |
| `common/graphiti/__init__.py` | exports | — | — | — |

## `src/knowbase/config`

| Module | Rôle | Fonctions / classes | Dépendances | Effets |
| --- | --- | --- | --- | --- |
| `config/settings.py` | Configuration globale | `Settings` (Pydantic BaseSettings), `get_settings()` | os, pathlib, pydantic | Lit env vars, résout chemins `data/` |
| `config/paths.py` | Gestion chemins projet | `PROJECT_ROOT`, `DATA_DIR`, `ensure_directories()` | pathlib | Crée dossiers manquants |
| `config/prompts_loader.py` | Chargement prompts LLM | `load_prompts`, `select_prompt`, `render_prompt` | yaml, jinja2 | Lit fichiers `config/prompts/*.yaml` |
| `config/__init__.py` | exports | — | — | — |

## `src/knowbase/ingestion`

| Module | Rôle | Fonctions / classes | Dépendances | Effets |
| --- | --- | --- | --- | --- |
| `ingestion/__init__.py` | exports | — | — | — |
| `ingestion/queue/__init__.py` | exports | — | — | — |
| `ingestion/queue/connection.py` | Connexion Redis/RQ | `get_redis_connection`, `get_queue` | redis, rq | Ouvre connexion Redis |
| `ingestion/queue/dispatcher.py` | Enqueue jobs | `enqueue_pptx_ingestion`, `enqueue_pdf_ingestion`, `enqueue_excel_ingestion`, `enqueue_fill_excel`, `fetch_job` | RQ | Ajoute jobs, enrichit meta |
| `ingestion/queue/jobs.py` | Fonctions worker | `ingest_pptx_job`, `ingest_pdf_job`, `ingest_excel_job`, `fill_excel_job`, helpers `update_job_progress`, `mark_job_as_processing` | Pipelines, Redis history, filesystem | Lis/écrit fichiers, upsert Qdrant, update Redis |
| `ingestion/queue/worker.py` | Worker entrypoint | `run_worker`, `warm_clients`, `main` | RQ, debugpy | Lance worker, attache debugger |
| `ingestion/queue/__main__.py` | CLI worker | Permet `python -m knowbase.ingestion.queue` | `run_worker` | — |
| `ingestion/pipelines/pptx_pipeline.py` | Pipeline PPTX complet | `process_pptx`, extraction slides, conversion PDF→images, prompts LLM, embeddings, upsert Qdrant | MegaParse/python-pptx, PyMuPDF, PIL, Qdrant, LLMRouter | Gère fichiers (slides, thumbnails), appelle LLM, Qdrant |
| `ingestion/pipelines/pdf_pipeline.py` | Pipeline PDF | `process_pdf` | PyMuPDF, qdrant, SentenceTransformer | Convertit PDF, extrait texte, enregistre |
| `ingestion/pipelines/excel_pipeline.py` | Pipeline Excel ingestion | `process_excel_rfp` | pandas, openpyxl, Qdrant | Lit onglets, génère chunks |
| `ingestion/pipelines/fill_excel_pipeline.py` | Ancien pipeline RFP | Fonctions de remplissage | pandas, openpyxl | Manipule Excel |
| `ingestion/pipelines/smart_fill_excel_pipeline.py` | Pipeline intelligent RFP | `main`, helpers (analyse, recherche, écriture) | pandas, openpyxl, `search_documents`, LLMRouter | Lit/écrit Excel, interroge Qdrant/LLM |
| `ingestion/pipelines/__init__.py` | exports | — | — | — |
| `ingestion/processors/__init__.py` | placeholder | — | — | — |
| `ingestion/cli/*.py` | CLI maintenance | purge collections, generate thumbnails, migration, update solutions | Click/argparse, Qdrant, filesystem | Scripts standalone |

## `src/knowbase/ui`

| Module | Rôle | Fonctions / classes | Dépendances | Effets |
| --- | --- | --- | --- | --- |
| `ui/__init__.py` | exports | — | — | — |
| `ui/streamlit_app.py` | Interface Streamlit legacy | `main()` | streamlit, pandas, services backend | Lance UI Streamlit, appels API |

## Autres modules

| Module | Rôle | Fonctions / classes | Dépendances | Effets |
| --- | --- | --- | --- | --- |
| `src/knowbase/__init__.py` | Package marker | `__version__` éventuel | — | — |
| `app/main.py` | Entrée FastAPI conteneurisée | instancie `create_app()` | uvicorn, FastAPI | Sert l’API en mode conteneur |
| `app/claims_utils.py` | Utilitaires assertions (Streamlit) | Fonctions de formatage claims | pandas | — |
| `scripts/*.py` | Scripts opérationnels (import/export, validation Graphiti/Qdrant, analyse PPTX) | Fonctions `main()` spécifiques | click/argparse, services | Accèdent aux mêmes clients (Qdrant, Graphiti, filesystem) |
| `ui/app.py` | Lancement Streamlit packagé | `main()` | streamlit | Lance UI |
| `test_phase2_validation.py` | Script validation phases | Fonctions de test orchestré | pytest | — |

## Modules de tests

| Dossier | Contenu | Objectif |
| --- | --- | --- |
| `tests/` | Tests unitaires/integration pour le package `src/knowbase` (dependencies, settings, llm_router, ingestion, Graphiti, facts) | Valider la logique métier dans l’environnement source |
| `app/tests/` | Copies des tests pour l’application dockerisée (`app/`) | Garantir qu’`app/main.py` reste aligné avec `src/knowbase/api` |

Ce tableau constitue la carte des modules runtime. Les scripts/tests détaillés reprennent les mêmes services : reportez-vous à `registry.json` pour les signatures d’API précises.
