# Catalogue des APIs FastAPI

Ce document référence l’ensemble des endpoints exposés par `create_app()` (`src/knowbase/api/main.py`). Chaque section correspond à un router et détaille : méthode, chemin final (avec préfixe), schémas de requête/réponse, services internes appelés, dépendances externes (Qdrant, Redis, LLM, Graphiti…). Les schémas mentionnés sont ceux définis dans `src/knowbase/api/schemas`.

> ℹ️ Tous les endpoints héritent du middleware `UserContextMiddleware` qui extrait les en-têtes (`X-User-ID`, `X-Group-ID`, etc.) pour contextualiser les appels multi-tenant.

## Recherche (`src/knowbase/api/routers/search.py`)

| Méthode & chemin | Requête | Réponse | Services internes | Dépendances externes |
| --- | --- | --- | --- | --- |
| `POST /search` | `SearchRequest` (question, option solution) | objet `{"status", "results", "synthesis"}` | `search_documents()` | Qdrant (`get_qdrant_client`), SentenceTransformer (`get_sentence_transformer`), reranker + LLM (`synthesize_response`) |
| `GET /solutions` | Query vide | `List[str]` | `get_available_solutions()` | Qdrant scroll collection principale |

## Ingestion (`src/knowbase/api/routers/ingest.py`)

| Méthode & chemin | Requête | Réponse | Services internes | Dépendances externes |
| --- | --- | --- | --- | --- |
| `POST /dispatch` | Form-data (`action_type`, `document_type`, `question`, `file`, `meta`) | Status JSON (search, ingest, fill) | `handle_dispatch()` | Qdrant, SentenceTransformer, OpenAI (canonicalisation), Redis Queue (`enqueue_*`), Redis import history |
| `POST /documents/upload-excel-qa` | `UploadFile` Excel + option meta | Status JSON | `handle_excel_qa_upload()` | Redis import history, Redis Queue (Excel ingestion) |
| `POST /documents/fill-excel-rfp` | `UploadFile` Excel + option meta | Status JSON | `handle_excel_rfp_fill()` | Redis import history, Redis Queue (smart fill), OpenAI canonicalisation |
| `POST /documents/analyze-excel` | `UploadFile` Excel | Analyse des onglets (liste colonnes, échantillons) | `analyze_excel_file()` | pandas, openpyxl |

## Statut ingestion (`src/knowbase/api/routers/status.py`, préfixe `/api`)

| Méthode & chemin | Requête | Réponse | Services internes | Dépendances externes |
| --- | --- | --- | --- | --- |
| `GET /api/status/{uid}` | UID job | `{"action", "status", ...}` | `job_status()` | Redis Queue (`fetch_job`), Redis import history |

## Historique d’import (`src/knowbase/api/routers/imports.py`, préfixe `/api`)

| Méthode & chemin | Requête | Réponse | Services internes | Dépendances externes |
| --- | --- | --- | --- | --- |
| `GET /api/imports/history` | `limit` (int) | Liste des enregistrements | `RedisImportHistoryService.get_history()` | Redis DB1 |
| `GET /api/imports/active` | — | Liste imports actifs | `RedisImportHistoryService.get_active_imports()` | Redis DB1 + Queue RQ |
| `POST /api/imports/sync` | — | `{message, synced_count}` | `RedisImportHistoryService.sync_orphaned_jobs()` | Redis DB1 + Queue RQ |
| `POST /api/imports/cleanup` | `days` | `{message, deleted_count}` | `RedisImportHistoryService.cleanup_old_records()` | Redis DB1 |
| `DELETE /api/imports/{uid}/delete` | UID | `{message, deleted_items}` | `import_deletion.delete_import_completely()` | Redis DB1, Qdrant, stockage disque |

## Solutions SAP (`src/knowbase/api/routers/sap_solutions.py`, préfixe `/api/sap-solutions`)

| Méthode & chemin | Requête | Réponse | Services internes | Dépendances externes |
| --- | --- | --- | --- | --- |
| `GET /api/sap-solutions/` | — | `SolutionsListResponse` | `SAPSolutionsManager.get_solutions_list()` | Lecture YAML `config/sap_solutions.yaml` |
| `POST /api/sap-solutions/resolve` | `SolutionResolveRequest` | `SolutionResolveResponse` | `SAPSolutionsManager.resolve_solution()` | LLMRouter (OpenAI/Anthropic), YAML |
| `GET /api/sap-solutions/search/{query}` | Path `query` | `SolutionsListResponse` | `SAPSolutionsManager.get_solutions_list()` (filtrage) | YAML |
| `GET /api/sap-solutions/with-chunks` | `extend_search` bool | `SolutionsListResponse` | `get_sap_solutions_manager().get_solutions_list()` + Qdrant scroll | Qdrant (collections principale & `rfp_qa`) |

## Téléchargements (`src/knowbase/api/routers/downloads.py`, préfixe `/api/downloads`)

| Méthode & chemin | Requête | Réponse | Services internes | Dépendances externes |
| --- | --- | --- | --- | --- |
| `GET /api/downloads/filled-rfp/{uid}` | UID | `FileResponse` Excel | `RedisImportHistoryService.get_import_by_uid()` | Système de fichiers (`presentations_dir`), historique Redis |
| `GET /api/downloads/import-files/{uid}` | UID | `FileResponse` | `RedisImportHistoryService.get_import_by_uid()` | Système de fichiers (`docs_done`, `docs_in`) |

## Analyse des tokens (`src/knowbase/api/routers/token_analysis.py`, préfixe `/api/tokens`)

| Méthode & chemin | Requête | Réponse | Services internes | Dépendances externes |
| --- | --- | --- | --- | --- |
| `GET /api/tokens/stats` | — | `{stats_by_model, total_cost, total_usage_count}` | `get_token_tracker().get_stats_by_model()` | Historique en mémoire |
| `GET /api/tokens/estimate-deck` | `num_slides`, `model`, `avg_input_tokens`, `avg_output_tokens` | `DeckCostEstimate` | `TokenTracker.estimate_deck_cost()` | Barème de coûts intégré |
| `GET /api/tokens/compare-providers` | `input_tokens`, `output_tokens`, `base_model` | Comparaison coûts | `TokenTracker.compare_providers()` | Tarifs intégrés |
| `GET /api/tokens/cost-by-task` | — | Stats par type de tâche | Agrégation `TokenTracker` | — |
| `GET /api/tokens/pricing` | — | Détail tarifs | `TokenTracker.MODEL_PRICING` | — |
| `POST /api/tokens/reset` | — | `{message}` | `TokenTracker.usage_history.clear()` | — |
| `GET /api/tokens/sagemaker-savings` | `num_slides`, `current_model`, `avg_input_tokens`, `avg_output_tokens` | Analyse d’économies | `TokenTracker.estimate_deck_cost()` | Tarifs intégrés |

## Tenants (`src/knowbase/api/routers/tenants.py`, préfixe `/api/tenants`)

| Méthode & chemin | Requête | Réponse | Services internes | Dépendances externes |
| --- | --- | --- | --- | --- |
| `POST /api/tenants/` | `TenantCreateRequest` | `Tenant` | `TenantService.create_tenant()` | Fichiers JSON sous `/data/tenants` |
| `GET /api/tenants/` | `page`, `page_size`, filtres | `TenantListResponse` | `TenantService.list_tenants()` | Fichiers JSON |
| `GET /api/tenants/{tenant_id}` | Path | `Tenant` | `TenantService.get_tenant()` | Fichiers JSON |
| `PUT /api/tenants/{tenant_id}` | `TenantUpdate` | `Tenant` | `TenantService.update_tenant()` | Fichiers JSON |
| `DELETE /api/tenants/{tenant_id}` | Path | 204 | `TenantService.delete_tenant()` | Fichiers JSON |
| `POST /api/tenants/{tenant_id}/users` | `AddUserToTenantRequest` | `UserTenantMembership` | `TenantService.add_user_to_tenant()` | Fichiers JSON |
| `GET /api/tenants/{tenant_id}/users` | Path | Liste memberships | `TenantService.get_tenant_users()` | Fichiers JSON |
| `GET /api/tenants/{tenant_id}/hierarchy` | Path | `TenantHierarchy` | `TenantService.get_tenant_hierarchy()` | Fichiers JSON |
| `PUT /api/tenants/{tenant_id}/stats` | `TenantStatsUpdate` | 204 | `TenantService.update_tenant_stats()` | Fichiers JSON |
| `GET /api/tenants/user/{user_id}/tenants` | Path | Liste memberships | `TenantService.get_user_tenants()` | Fichiers JSON |
| `GET /api/tenants/user/{user_id}/default-tenant` | Path | `{default_tenant_id, tenant}` | `TenantService.get_default_tenant_for_user()` | Fichiers JSON |
| `POST /api/tenants/user/{user_id}/check-permission` | Query `tenant_id`, `permission` | `{has_permission}` | `TenantService.user_has_permission()` | Fichiers JSON |
| `POST /api/tenants/initialize-defaults` | Query `created_by` | `{message, created_tenant_ids}` | `TenantService.create_tenant()` | Fichiers JSON |

## Utilisateurs (`src/knowbase/api/routers/users.py`, préfixe `/api`)

| Méthode & chemin | Requête | Réponse | Services internes | Dépendances externes |
| --- | --- | --- | --- | --- |
| `GET /api/users` | — | `UserListResponse` | `UserService.list_users()` | Fichier JSON `data/users` |
| `GET /api/users/default` | — | `User` | `UserService.get_default_user()` | Fichier JSON |
| `GET /api/users/{user_id}` | Path | `User` | `UserService.get_user()` | Fichier JSON |
| `POST /api/users` | `UserCreate` | `User` | `UserService.create_user()` | Fichier JSON |
| `PUT /api/users/{user_id}` | `UserUpdate` | `User` | `UserService.update_user()` | Fichier JSON |
| `DELETE /api/users/{user_id}` | — | `{message}` | `UserService.delete_user()` | Fichier JSON |
| `POST /api/users/{user_id}/activity` | — | `{message}` | `UserService.update_last_active()` | Fichier JSON |
| `POST /api/users/{user_id}/set-default` | — | `User` | `UserService.set_default_user()` | Fichier JSON |

## Healthchecks (`src/knowbase/api/routers/health.py`, préfixe `/api/health`)

| Méthode & chemin | Requête | Réponse | Services internes | Dépendances externes |
| --- | --- | --- | --- | --- |
| `GET /api/health/` | — | Statut global (API, Qdrant, Redis, Postgres, Graphiti) | HTTPX ping interne | Qdrant (`http://qdrant:6333/health`), Graphiti services locaux |
| `GET /api/health/tenants` | — | Stats Tenants | `TenantService.list_tenants()` | Fichiers JSON |
| `GET /api/health/graphiti` | — | Statut Graphiti (Neo4j, Postgres, service) | HTTPX | Services Graphiti locaux |
| `GET /api/health/quick` | — | Ping rapide | — | — |

## Graphiti (integration directe, `src/knowbase/api/routers/graphiti.py`, préfixe `/api/graphiti`)

Tous ces endpoints sont `async` et passent par `GraphitiTenantManager` (singleton initialisé à la demande).

| Méthode & chemin | Requête | Réponse | Services internes | Dépendances externes |
| --- | --- | --- | --- | --- |
| `GET /api/graphiti/health` | — | Statut minimal | Lecture config Graphiti | Variables d’environnement Graphiti |
| `GET /api/graphiti/health-full` | — | Statut complet (store) | `GraphitiTenantManager.store.health_check()` | Graphiti store (Neo4j, Postgres) |
| `POST /api/graphiti/episodes` | `EpisodeCreate` | `{episode_uuid, ...}` | `GraphitiTenantManager.isolate_tenant_data(action="create_episode")` | Graphiti store, isolation multi-tenant |
| `POST /api/graphiti/facts` | `FactCreate` | `{fact_uuid, ...}` | `GraphitiTenantManager.isolate_tenant_data(action="create_fact")` | Graphiti store |
| `GET /api/graphiti/facts` | Query `query`, `group_id`, `status_filter`, `limit` | `{facts}` | `GraphitiTenantManager.isolate_tenant_data` ou `store.search_facts()` | Graphiti store |
| `POST /api/graphiti/relations` | `RelationCreate` | `{relation_id, ...}` | `GraphitiTenantManager.store.create_relation()` | Graphiti store |
| `POST /api/graphiti/subgraph` | `SubgraphRequest` | `{subgraph}` | `GraphitiTenantManager.isolate_tenant_data()` | Graphiti store |
| `GET /api/graphiti/memory/{group_id}` | Path + `limit` | `{memory}` | `GraphitiTenantManager.isolate_tenant_data(action="get_memory")` | Graphiti store |
| `POST /api/graphiti/tenants` | `TenantCreate` | `{message, tenant}` | `GraphitiTenantManager.create_tenant()` | Graphiti store |
| `GET /api/graphiti/tenants` | — | `{tenants}` | `GraphitiTenantManager.list_tenants()` | Graphiti store |
| `GET /api/graphiti/tenants/{group_id}` | Path | `{tenant}` | `GraphitiTenantManager.get_tenant_info()` | Graphiti store |
| `DELETE /api/graphiti/tenants/{group_id}` | Path + `confirm` | `{message}` | `GraphitiTenantManager.delete_tenant()` | Graphiti store |

## Knowledge Graph utilisateur/corporate (`src/knowbase/api/routers/knowledge_graph.py`, préfixe `/api`)

Ces endpoints se basent sur `UserKnowledgeGraphService` qui choisit dynamiquement le groupe (corporate ou personnel) via `UserContext`.

| Méthode & chemin | Requête | Réponse | Services internes | Dépendances externes |
| --- | --- | --- | --- | --- |
| `GET /api/knowledge-graph/health` | — | `{status, mode, group_id, stats}` | `UserKnowledgeGraphService.get_user_stats()` | Graphiti store |
| `POST /api/knowledge-graph/entities` | `EntityCreate` | `EntityResponse` | `UserKnowledgeGraphService.create_entity_for_user()` | Graphiti store, cache en mémoire |
| `GET /api/knowledge-graph/entities/{entity_id}` | Path | `EntityResponse` | `UserKnowledgeGraphService.get_entity_for_user()` | Graphiti store |
| `POST /api/knowledge-graph/relations` | `RelationCreate` | `RelationResponse` | `UserKnowledgeGraphService.create_relation_for_user()` | Graphiti store |
| `GET /api/knowledge-graph/relations` | Query `entity_id`, `relation_type`, `limit` | `List[RelationResponse]` | `UserKnowledgeGraphService.list_relations_for_user()` | Graphiti store |
| `DELETE /api/knowledge-graph/relations/{relation_id}` | Path | `{status, message}` | `UserKnowledgeGraphService.delete_relation_for_user()` | Graphiti store |
| `POST /api/knowledge-graph/subgraph` | `SubgraphRequest` | `SubgraphResponse` | `UserKnowledgeGraphService.get_subgraph_for_user()` | Graphiti store |
| `GET /api/knowledge-graph/stats` | — | `KnowledgeGraphStats` | `UserKnowledgeGraphService.get_user_stats()` | Graphiti store |

## Facts Governance (`src/knowbase/api/routers/facts_governance.py`, préfixe `/api/facts`)

| Méthode & chemin | Requête | Réponse | Services internes | Dépendances externes |
| --- | --- | --- | --- | --- |
| `POST /api/facts` | `FactCreate` | `FactResponse` | `FactsGovernanceService.create_fact()` (avec `detect_conflicts`) | Graphiti store (via service), stockage JSON | 
| `GET /api/facts` | Query filtres | `FactsListResponse` | `FactsGovernanceService.list_facts()` | Graphiti store |
| `GET /api/facts/{fact_id}` | Path | `FactResponse` | `FactsGovernanceService.get_fact()` | Graphiti store |
| `PUT /api/facts/{fact_id}/approve` | `FactApprovalRequest` | `FactResponse` | `FactsGovernanceService.approve_fact()` | Graphiti store |
| `PUT /api/facts/{fact_id}/reject` | `FactRejectionRequest` | `FactResponse` | `FactsGovernanceService.reject_fact()` | Graphiti store |
| `GET /api/facts/conflicts/list` | — | `ConflictsListResponse` | `FactsGovernanceService.get_conflicts()` | Graphiti store + règles métiers |
| `GET /api/facts/timeline/{entity_id}` | Path | `FactTimelineResponse` | `FactsGovernanceService.get_timeline()` | Graphiti store |
| `DELETE /api/facts/{fact_id}` | Path | 204 | `FactsGovernanceService.reject_fact()` (soft delete) | Graphiti store |
| `GET /api/facts/stats/overview` | — | `FactStats` | `FactsGovernanceService.get_stats()` | Graphiti store |

## Facts Intelligence (`src/knowbase/api/routers/facts_intelligence.py`, préfixe `/api/facts/intelligence`)

| Méthode & chemin | Requête | Réponse | Services internes | Dépendances externes |
| --- | --- | --- | --- | --- |
| `POST /api/facts/intelligence/confidence-score` | `ConfidenceScoreRequest` | `ConfidenceScoreResponse` | `FactsIntelligenceService.calculate_confidence_score()` + `FactsGovernanceService.list_facts()` | LLMRouter (OpenAI/Anthropic) |
| `POST /api/facts/intelligence/suggest-resolution/{fact_uuid}` | Path + body `FactCreate` reconstruit | `{suggestions}` | `FactsIntelligenceService.suggest_conflict_resolutions()` | LLMRouter |
| `POST /api/facts/intelligence/detect-patterns` | `PatternsRequest` | `PatternsResponse` | `FactsIntelligenceService.detect_patterns_and_anomalies()` | LLMRouter (pour analyses), données Graphiti |
| `GET /api/facts/intelligence/metrics` | Query `time_window_days` | `MetricsResponse` | `FactsIntelligenceService.calculate_governance_metrics()` | Données Facts |
| `GET /api/facts/intelligence/alerts` | Query `severity` | `{alerts, total, by_severity}` | `FactsIntelligenceService` + `FactsGovernanceService.get_conflicts()` | LLMRouter pour recommandations |

Ce catalogue couvre l’intégralité des routes montées par l’application FastAPI. Pour les détails de logique métier, reportez-vous à `MODULES.md` et au registre machine `registry.json`.
