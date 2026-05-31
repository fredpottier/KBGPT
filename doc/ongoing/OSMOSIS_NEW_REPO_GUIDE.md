# Guide de création du nouveau repo « Osmosis »

> **Statut** : document de travail (doc/ongoing). Source de vérité pour la migration `SAP_KB` → `osmosis`.
> **Date** : 2026-05-31. **Branche d'audit** : `feat/phase-b-augmentee`.
> **Périmètre** : ce guide synthétise la cartographie + la classification par bloc (api-routers, runtime, ingestion, extraction-kg/relations, common) et les vérifications grep associées. Il est **actionnable** : suivez-le étape par étape.

---

## 1. Objectif & principes

**But** : reconstruire un dépôt **neuf** nommé `osmosis` — propre, déployable en production, **sans legacy**, avec un nommage métier clair (zéro numéro de version, zéro jargon interne dans les noms).

### Principes directeurs (non négociables)

1. **Repo neuf, PAS un fork.** On crée `osmosis` à blanc puis on **importe sélectivement le vivant**. On ne migre jamais « tout le repo puis on nettoie » : le legacy ne doit jamais entrer.
2. **Trois projets indépendants** (dépôts ou packages séparés) :
   - **`osmosis`** = application cœur (ingestion + KG + answering + UI end-user).
   - **`osmosis-cockpit`** = ops/admin/qualité (benchmarks, GPU/burst, KG hygiene, re-passes KG, domain-context, monitoring, backup).
   - **`osmosis-bench`** (ou sous-projet du cockpit) = harnais de bench/diagnostic et scripts one-off.
3. **Nommage propre** : pas de `v2/v3/v4/v5/v6/a3/a38`, pas de `knowbase`, pas de `kg_*`/`claimfirst` exposés tels quels, pas de `SAP_KB`. Noms métier (`answering`, `ingestion`, `knowledge_graph`, `extraction`...).
4. **Domain-agnostic strict** : un composant générique/intentionnel (médical, légal, aéro) reste **KEEP-DORMANT** même s'il n'est pas exercé par le corpus SAP de test. « Inutile sur le corpus actuel » n'est **jamais** un motif de suppression.
5. **Preuve avant verdict** : un module n'est `legacy` que si un **grep exhaustif** (src/ + frontend/src/ + app/scripts + config + routers) prouve l'absence de tout consommateur de production vivant **ET** qu'il est superseded. On cite toujours les consommateurs (ou leur absence).
6. **Pas de scope minimal** : on vise la cible complète. Si un effort grossit, on reporte l'estimation, on ne dégrade pas le périmètre.

---

## 2. Méthode de classification

Quatre statuts, appliqués fichier par fichier (jamais « par dossier en bloc » sans vérifier).

| Statut | Définition | Critère de preuve |
|--------|------------|-------------------|
| **ALIVE** | Sur un chemin de production vivant (ingestion par défaut, runtime answering, UI end-user, infra partagée consommée par du vivant). | ≥1 consommateur prod cité (fichier:ligne). |
| **KEEP-DORMANT** | Générique/intentionnel (domain-agnostic, garde-fou togglable, capacité multi-domaine), non exercé par le corpus actuel mais conçu pour l'être. | Intention de design documentée + réactivable ; **interdit** de classer legacy. |
| **LEGACY** | Mort **et** superseded. Aucun chemin prod vivant ne l'appelle ; un remplaçant existe. | grep exhaustif → 0 consommateur vivant + remplaçant cité. |
| **COCKPIT** | Vivant mais relève de l'ops/admin/qualité (dashboards, re-passes KG, burst GPU, bench, backup). HTTP-reachable via `/admin/*` ou scripts ops. | Consommateur = router admin monté ou frontend `app/admin/**` ou script ops. → va dans `osmosis-cockpit`. |

**Règle d'or (Fred)** : *jamais legacy parce qu'inutile sur le corpus de test actuel*. Un module non exercé par SAP mais générique = KEEP-DORMANT, pas LEGACY.

**Pièges méthodologiques rencontrés (à rejouer pour tout nouveau composant)** :
- Une **string de logger** ou une **valeur d'enum** n'est PAS un import (`burst.py` liste des noms de loggers `osmose_*` / `text_chunker` ; `insights.py` contient la string d'enum `'transitive_inference'`). Vérifier `from … import …` réel.
- Un **re-export `__init__.py`** passif n'est pas un consommateur vivant.
- Un **endpoint HTTP atteignable** sans aucune UI ni script qui l'appelle = mort côté produit (mais le router reste monté → bien le décrocher de `main.py`).
- Distinguer **router** et **package** : un router peut être legacy alors que le package héberge un utilitaire partagé vivant (cf. `runtime_v3.nli_judge`, `runtime_v2.llm_client`).

---

## 3. Inventaire & classification par bloc

> Légende : ✅ ALIVE · 🟡 KEEP-DORMANT · 🔴 LEGACY · 🛠️ COCKPIT.
> Preuves grep complètes dans la cartographie/vérifications source ; ci-dessous la synthèse actionnable.

### 3.1 Bloc `runtime` (answering)

| Élément | Statut | Justification (consommateur / preuve) |
|---------|--------|----------------------------------------|
| `runtime_a3/**` (orchestrator, parse, plan, execute, evaluate, synthesize, schemas, subject_resolver, predicate_resolver, claim_filter, reranker, premise_verifier, grounding_verifier) | ✅ | **Seul runtime d'answering vivant.** Exposé par `api/routers/runtime_v6.py:26-36` ; `main.py:266`. `premise_verifier` + `grounding_verifier` ON par défaut. |
| `runtime_a3/sufficiency_checker.py` | 🟡 | Garde-fou OFF par défaut (`V6_SUFFICIENCY_CHECK_ENABLED=0`), câblé `synthesize.py:760` fail-open. Toggle intentionnel. |
| `runtime_v3/nli_judge.py` | 🟡→✅ | **Infra NLI partagée vivante** : importée par `runtime_a3/grounding_verifier.py:128` (ON par défaut). À EXTRAIRE avant tout retrait de `runtime_v3`. |
| `runtime_v2/llm_client.py` | 🟡→✅ | **Utilitaire LLM partagé vivant** : `atlas/generator.py:212,243`, `api/services/query_decomposer.py:895`, `anchor/anchor_extractor.py:133`. À extraire comme client commun. |
| `runtime_v3/**` (hors nli_judge) : pipeline, retriever, synthesis, llm_client, models | 🔴 | Superseded par `runtime_a3`. Consommé uniquement par routers v3/v4/v4_2/v4_poc + `facts_first/*` (tous legacy). Frontend grep = 0. |
| `runtime_v4/` (router seul ; **dossier package absent**) | 🔴 | `main.py:262`. Délègue à `facts_first` (non monté) + `runtime_v3.retriever`. 0 UI. |
| `runtime_v4_poc/**` + router | 🔴 | POC non promu. Référencé hors-router seulement par `runtime_v4_2` (legacy). 0 frontend. |
| `runtime_v4_2/**` + router | 🔴 | Tiered candidate abandonné. 0 import externe vivant hors son router. 0 frontend. |
| `runtime_v5/**` (Reading Agent) + router | 🔴 | Superseded — **auto-documenté** `runtime_v5/agent/loop_signature.py:14` (« NE PAS étendre, voir runtime_a3 »). 0 consommateur externe vivant. ⚠️ Auditer briques transverses (HHEM, tracer, redlock, tenant_guard) avant de jeter. |
| `runtime_v2/**` (pipeline answering, hors llm_client) + router | 🛠️ **UNSURE** | **Refuté legacy** : le router v2 a une UI câblée (`chat/runtime-v2/page.tsx`, 5 proxies `app/api/runtime_v2/*`, `LifecycleGraphMini.tsx`, lien `admin/layout.tsx:100`) + smoke quotidien `auto_validate_runtime_v2.py`. Seule UI d'answering/exploration réellement branchée. **Décision Fred requise** (cf. §8). |
| `runtime_v6/**` (= **module d'EXTRACTION**, PAS un runtime) | ✅ | ⚠️ **Nom trompeur.** Consommé par `claimfirst/v6/**`. À renommer `extraction_archetypes/`. |

> **Gros legacy à NE PAS embarquer** : `runtime_v3/pipeline`, `runtime_v4/`, `runtime_v4_poc/`, `runtime_v4_2/`, `runtime_v5/` (≈50 fichiers) + `facts_first/**` (non monté). Avant suppression : **extraire** `nli_judge` (v3) et `llm_client` (v2) en modules communs.

### 3.2 Bloc `api-routers` (50 routers, `main.py:229-303`)

**✅ ALIVE (≈30 routers end-user/core)** : `search` (⚠️ **vrai endpoint chat de prod**, `chat/page.tsx`→`/search`), `ingest`, `status`, `imports`, `solutions`, `downloads`, `token_analysis`, `facts`, `ontology`, `entities`, `entity_types`, `jobs`, `document_types`, `documents`, `auth`, `concepts`, `domain_context`, `insights`, `sessions`, `claims`*, `entity_resolution`, `navigation`, `analytics`, `markers`, `relations_explorer`, `challenge`, `verify`, `wiki`, `atlas`, `runtime_v6` (stratégique, exercé via cockpit bench), `claimfirst`* (pipeline = core ; UI monitoring = cockpit), `admin`* (frontière core/cockpit).

> *`claims`/`claimfirst`/`admin` = frontière à trancher (cf. §8).

**🟡 KEEP-DORMANT** : `domain_packs` (mécanisme multi-domaine, `main.py:297`), `living_ontology` (volontairement désactivé `main.py:248`, réactivable).

**🔴 LEGACY** : `runtime_v3`, `runtime_v4`, `runtime_v4_poc`, `runtime_v4_2` (routers — 0 frontend). `runtime_v2` = **COCKPIT/UNSURE** (UI debug branchée), `runtime_v5` = LEGACY (router mort, package à auditer).

**🛠️ COCKPIT** : `benchmarks`, `burst`, `gpu`, `kg_hygiene`, `kg_health`, `post_import`, `corpus_intelligence`, `backup`. Consommés exclusivement par `frontend/src/app/admin/**`.

### 3.3 Bloc `ingestion`

| Élément | Statut | Justification |
|---------|--------|---------------|
| `folder_watcher.py`, `queue/{dispatcher,jobs_v2,__init__,connection,worker}.py` | ✅ | Chemin prod : `docs_in` → folder_watcher (service Docker `docker-compose.yml:307`) → dispatcher → `jobs_v2.ingest_document_v2_job` → ExtractionPipelineV2 → **chaînage ClaimFirst** (`jobs_v2.py:439`). |
| `pipelines/excel_pipeline.py`, `pipelines/smart_fill_excel_pipeline.py`, `pipelines/fill_excel_pipeline.py` | ✅ | Flux RFP. ⚠️ `fill_excel_pipeline` est une **dépendance vivante** de `smart_fill` (`smart_fill_excel_pipeline.py:399`) — **réfuté legacy**, ne pas supprimer. |
| `pipelines/pass05_coref.py`, `document_valid_from_extractor.py`, `resilience/{job_manager,job_state,recovery}.py` | ✅ | Consommés par `extraction_v2/pipeline.py` et `claimfirst/orchestrator.py`. |
| `osmose_enrichment.py` | ✅ **partiel** | `generate_document_summary` consommé par `extraction_v2/pipeline.py:735`. **Découper** : garder cette fonction, retirer le reste. |
| `burst/**` | 🛠️ | EC2 Spot GPU. Consommé par `routers/burst.py` + `admin/burst`. → cockpit. |
| `queue/{pass2_jobs,pass3_jobs,pass4_jobs}.py`, `pass2_orchestrator.py`, `enrichment_tracker.py` | 🛠️ | **Réfutés legacy** : atteignables via endpoints `admin.py` LIVE (re-passes KG). → cockpit (ou supprimés si le cockpit retire ces endpoints). |
| `cli/{migrate,purge,purge_entries,generate_thumbnails}.py` | 🟡 | Outils ops de maintenance Qdrant/assets, génériques. |
| `osmose_agentique.py`, `osmose_utils.py`, `osmose_integration.py`, `osmose_persistence.py`, `text_chunker.py`, `hybrid_anchor_chunker.py`, `slide_reconstructor.py`, `validate_osmose_deps.py`, `queue/reprocess_job.py`, `queue/pass35_jobs.py` | 🔴 | **Ancien pipeline Stratified V2 / OSMOSE agentique**, court-circuité par défaut (`INGESTION_SKIP_STRATIFIED_V2=true`, `jobs_v2.py:386`). Superseded par ClaimFirst. `slide_reconstructor`/`validate_osmose_deps`/`pass35_jobs` = 0 consommateur (mort strict). |

### 3.4 Bloc `extraction-kg` (`claimfirst/**`, `semantic/**`, `relations/**`)

| Élément | Statut | Justification |
|---------|--------|---------------|
| `claimfirst/**` (orchestrator, extractors, persistence, resolution, applicability...) | ✅ | **Seul pipeline d'ingestion enqueué par défaut** (`enqueue_claimfirst_process`). Écrit `:Claim`/`:Procedure`/relations lus par `runtime_a3/execute.py`. |
| `claimfirst/resolution/subject_resolver.py` (v1) + `extractors/merge_arbiter.py` | ✅ | **Réfuté legacy** : v1 appelé `orchestrator.py:2155,2416` (`resolve_batch`), coexiste **par design** avec v2 (rôle différent). |
| `claimfirst/extractors/{scope_resolver,qs_llm_extractor,comparability_gate}.py` | 🟡 | Re-exportés par `__init__` + tests, non câblés dans orchestrator → dormants internes au package actif. |
| `claimfirst/applicability/frame_builder_v2.py`, `evidence_validator_v2.py` | 🔴 | Variante V2 jamais câblée (orchestrator utilise `FrameBuilder` V1 `orchestrator.py:1935`). Orphelins + backfill scripts. |
| `semantic/**` : `language_detector`, `embeddings`, `inference/inference_engine`, `insights`, `ontology` (partiel) | ✅ | Utils + inference vivante (autonome, `semantic/inference/inference_engine.py`). |
| `semantic/extraction` (ancres/concepts) | 🟡 | Générique domain-agnostic, non exercé. |
| `relations/` cross-doc c4/c6, `relations/types.py`, `relations_explorer` | ✅ | Cross-doc en post-import ClaimFirst + lecture LOGICAL_RELATION. |
| `relations/{raw_claim_writer,semantic_relation_writer,extraction_engine,neo4j_writer,llm_relation_extractor}.py` | 🔴 | Génération pass2 pré-ClaimFirst. Atteints uniquement via `supervisor`←`osmose_agentique` (skippé). Superseded par `claim_persister`. |
| `relations/{canonical_claim_writer,canonical_relation_writer,claim_consolidator,relation_consolidator,raw_assertion_writer}.py` | 🛠️ | Couche **Canonical** : NON lue par `runtime_a3` (0 réf), MAIS `routers/claims.py:34-37` + `lib/api.ts:323-358` câblent `/claims/consolidate,/concept,/conflicts,/stats`. → cockpit (consolidation manuelle). |
| Cluster V3.3 : `candidate_miner_v33`, `gate_v33`, `v33_types`, `logical_relation_classifier`, `relation_promoter`, `transitive_inference` | 🔴 | Piloté **uniquement par scripts d'expérimentation + tests**. ⚠️ Piège : `transitive_inference` (module) ≠ string d'enum `'transitive_inference'`. |
| Cluster EvidenceBundle : `evidence_bundle_*`, `bundle_*` | 🔴 | pass3.5 **enqueué par aucun router vivant** (seuls pass2/3/4 le sont). Mort. |
| 18 briques pass2 (`discursive_pattern_extractor`, `normative_*`, `structure_parser`, `segment_*_relation_extractor`, `predicate_extractor`, `tier_attribution`, `confidence_calculator`, `relation_extraction_{models,prompts}`, ...) | 🛠️ | Hors flux ClaimFirst, mais déclenchables via `admin.py` enqueue_pass2/3/4. → cockpit (ou legacy si endpoints retirés). |
| `relations/kpi_sentinel.py` | 🔴 | 0 consommateur total. |
| `semantic_consolidation_pass3.py` | 🛠️ | Via `governance_conflict_service`←`admin.py`. |

> **Méga-prompt legacy** : l'extraction de claims a un fallback **méga-prompt** dans `claimfirst/` (le pipeline staged P1.4b est OPT-IN, `CLAIMFIRST_STAGED_PIPELINE=0`). Décision migration : rendre le **staged pipeline** par défaut et **retirer le méga-prompt legacy** (cf. mémoire P1.4-bis).

### 3.5 Bloc `common` (infra partagée)

| Élément | Statut | Justification |
|---------|--------|---------------|
| `common/metrics.py` (Prometheus) + clients (Qdrant/Neo4j/OpenAI/Redis) | ✅ | Infra vivante (cités transversalement). |
| `common/tracing.py` | 🔴 | 0 consommateur prod (faux positif `runtime_v5/observability/metrics.py:308` = champ tenant, pas OTEL). Observabilité réelle = `metrics.py` + Grafana/Loki. |
| `common/pagination.py` | 🔴 | 0 appelant prod de `paginate()` (les hits « pagination » dans scripts = commentaires Cypher keyset). |
| `common/redis_client_resilient.py` | 🔴 | 0 import prod (tests + archive doc uniquement). |

---

## 4. Les 3 projets

### 4.1 `osmosis` (application cœur)

**Prend** :
- **Ingestion** : folder_watcher, queue (dispatcher/job d'ingestion/worker/connection), `extraction_v2` (Docling+Vision), `pass05_coref`, `document_valid_from_extractor`, resilience, `generate_document_summary` (extrait d'osmose_enrichment), pipelines Excel/RFP.
- **Extraction-KG** : `claimfirst/**` (avec staged pipeline par défaut), `semantic/{utils,inference,insights,ontology}`, relations cross-doc (c4/c6) + `types`.
- **Answering** : `runtime_a3/**` (renommé `answering/`), router answer.
- **API end-user** : les ~30 routers ALIVE (§3.2).
- **Frontend end-user** : `app/{chat,documents,rfp-excel,verify,atlas,wiki,solutions,...}`, `components/{chat,graph,ui,...}` (hors `app/admin/**`), `lib`, `stores`, `types`.
- **Infra commune** (cf. §4.4).

### 4.2 `osmosis-cockpit` (ops/admin/qualité)

**Prend** :
- **Routers** : `benchmarks`, `burst`, `gpu`, `kg_hygiene`, `kg_health`, `post_import`, `corpus_intelligence`, `backup`. (À trancher : `admin`, `claims`/consolidation, `claimfirst` monitoring.)
- **Backend ops** : `ingestion/burst/**`, re-passes KG (`pass2/3/4_jobs`, `pass2_orchestrator`, `pass2_service`, `enrichment_tracker`), couche Canonical + governance conflict (si conservée), 18 briques pass2 si les endpoints sont gardés.
- **Frontend** : tout `frontend/src/app/admin/**` (gpu, burst, benchmarks, kg-hygiene, domain-context, post-import, corpus-intelligence, backup, markers, relations, claimfirst) + `components/benchmarks/**` (`RuntimeV6Tab.tsx`).
- **Monitoring** : `docker-compose.monitoring.yml` (Grafana/Loki/Promtail), dossier `cockpit/` (collectors GPU/Docker/Knowledge/LLM-budget/pipeline/benchmark).

### 4.3 `osmosis-bench` (harnais bench/diagnostic — sous-projet du cockpit)

**Prend** : `app/scripts/bench_a38_runtime_v6.py`, `bench_a38_classic_rag.py`, `p3_compare_osmosis_vs_rag.py`, audits oracle (`audit_oracle_step*.py`), `p2_recall_audit.py`, `p1_probe_list_retrieval.py`, scripts `compare_*/analyze_*/audit_types_echecs_*`, gold-sets, evaluators (`primary_metrics.py`, `llm_judge.py`), `benchmark/**`.

### 4.4 Code COMMUN à extraire (lib partagée `osmosis-common` ou package interne)

À sortir des dossiers legacy/dispersés **avant** suppression, car consommé par du vivant :

| Source actuelle | Cible commune | Pourquoi |
|-----------------|---------------|----------|
| `runtime_v3/nli_judge.py` | `osmosis/verification/nli.py` | NLI faithfulness consommé par `grounding_verifier` (ON). |
| `runtime_v2/llm_client.py` | `osmosis/llm/runtime_client.py` | Routing vLLM-EC2→DeepInfra, 3 consommateurs vivants. |
| `common/{metrics, clients Qdrant/Neo4j/OpenAI/Redis}` | `osmosis/common/**` | Infra transverse. |
| Schémas Pydantic (`runtime_a3/schemas.py`, `claimfirst/schemas`) | `osmosis/schemas/**` | Contrats partagés ingestion↔answering↔API. |
| Config (`config/*.yaml`, settings centralisés) | `osmosis/config/**` + `config/` repo | LLM models, prompts, rules. |

---

## 5. Arborescence cible + conventions de nommage

### 5.1 Conventions

- **snake_case** pour les modules Python ; noms **métier**, jamais d'itération (`answering`, pas `runtime_a3/v6`).
- **Aucun** des tokens interdits dans un nom : `v2 v3 v4 v5 v6 a3 a38 a4* knowbase kg_ claimfirst SAP SAP_KB osmose_`.
- Préfixe d'API cohérent : `/api/...` pour le core, `/api/cockpit/...` pour l'ops.
- Package racine : `osmosis` (remplace `knowbase`).
- Frontend : pages end-user à la racine `app/`, ops sous le repo cockpit.

### 5.2 Arbo `osmosis` (app core)

```
osmosis/
├── osmosis/
│   ├── api/
│   │   ├── main.py                  # ~30 routers core uniquement
│   │   ├── routers/                 # answer.py, search.py, ingest.py, documents.py, ...
│   │   ├── services/
│   │   └── schemas/
│   ├── ingestion/
│   │   ├── watcher.py               # ex folder_watcher
│   │   ├── queue/                   # dispatcher.py, document_ingestion_job.py, worker.py, connection.py
│   │   ├── extraction/              # ex extraction_v2 (Docling+Vision)
│   │   ├── pipelines/               # excel_pipeline.py, rfp_autofill_pipeline.py
│   │   └── resilience/
│   ├── extraction/                  # ex claimfirst (claim-centric)
│   │   ├── orchestrator.py
│   │   ├── extractors/              # staged pipeline par défaut
│   │   ├── resolution/
│   │   ├── persistence/
│   │   └── archetypes/              # ex runtime_v6 (5 archétypes d'extraction)
│   ├── knowledge_graph/             # ex semantic+relations vivants
│   │   ├── inference/
│   │   ├── ontology/
│   │   ├── cross_document/          # c4/c6
│   │   └── types.py
│   ├── answering/                   # ex runtime_a3
│   │   ├── orchestrator.py
│   │   ├── parse.py / plan.py / execute.py / evaluate.py / synthesize.py
│   │   ├── resolvers/               # subject_resolver.py, predicate_resolver.py
│   │   ├── reranker.py / claim_filter.py
│   │   ├── premise_verifier.py / grounding_verifier.py / sufficiency_checker.py
│   │   └── schemas.py
│   ├── verification/                # nli.py (ex runtime_v3/nli_judge)
│   ├── llm/                         # runtime_client.py (ex runtime_v2/llm_client), router
│   ├── common/                      # clients, metrics, settings
│   ├── domain_packs/                # KEEP-DORMANT (biomedical, regulatory, aerospace...)
│   └── config/
├── frontend/                        # pages end-user (sans app/admin)
├── config/                          # *.yaml (llm_models, prompts, rules, sap_solutions→domain_catalog)
├── docker-compose.infra.yml
├── docker-compose.yml
├── migrations/                      # constraints Neo4j + collections Qdrant
└── tests/
```

### 5.3 Arbo `osmosis-cockpit`

```
osmosis-cockpit/
├── cockpit/                         # collectors GPU/Docker/Knowledge/LLM-budget/pipeline
├── api/routers/                     # benchmarks, compute_burst, gpu, kg_hygiene, kg_health,
│                                    #   post_import, corpus_intelligence, backup (prefix /api/cockpit)
├── services/
│   ├── compute_burst/               # ex ingestion/burst (EC2 Spot)
│   └── kg_reprocessing/             # ex pass2/3/4_jobs renommés (relation_enrichment_job, cross_doc_consolidation_job)
├── frontend/                        # ex frontend/src/app/admin/** + components/benchmarks
└── docker-compose.monitoring.yml    # Grafana/Loki/Promtail
```

### 5.4 Table de renommage

| Actuel | Cible | Note |
|--------|-------|------|
| repo `SAP_KB` / package `knowbase` | repo `osmosis` / package `osmosis` | + titre FastAPI « SAP Knowbase API » → « OSMOSIS API » (`main.py:53`). |
| `runtime_a3/` (+ router `runtime_v6.py`, route `/api/runtime_v6/answer`) | `answering/` (+ router `answer.py`, route `/api/answer`) | « v6 » trompeur (code répond `a3.0`). |
| `runtime_v6/` (module **extraction**) | `extraction/archetypes/` | Nom gravement trompeur (≠ runtime). |
| `runtime_v3/nli_judge.py` | `verification/nli.py` | Extraire avant suppression de v3. |
| `runtime_v2/llm_client.py` | `llm/runtime_client.py` | Extraire avant suppression de v2. |
| `runtime_v3,v4,v4_poc,v4_2,v5` (+ routers) | (suppression) | Après extraction des utils partagés. |
| `claimfirst/` | `extraction/` | Claim-centric reste l'abstraction ; nom interne « claimfirst » → métier. |
| `semantic/` + `relations/` (vivants) | `knowledge_graph/` | Regroupement métier. |
| `ingestion/queue/jobs_v2.py` | `ingestion/queue/document_ingestion_job.py` | Retirer `_v2`. |
| `enqueue_document_v2` / `pipeline_version='v2'` | `enqueue_document` / (sans version) | Retirer `v2`. |
| `osmose_agentique/utils/integration/persistence` | (suppression) | Legacy stratified. |
| `pass2/3/4_jobs.py`, `pass35_jobs.py` | `kg_reprocessing/*_job.py` (cockpit) ou suppression | Nom par fonction. |
| `ingestion/burst/` | `osmosis-cockpit/services/compute_burst/` | Ops compute. |
| `smart_fill_excel_pipeline.py` (+ `fill_excel_pipeline.py`) | `rfp_autofill_pipeline.py` (fonctions fusionnées) | Nom métier ; conserver les fonctions partagées. |
| `challenge.py` (route `/api/v2/challenge`) | `text_challenge.py` (route `/api/text-challenge`) | Retirer `v2`. |
| `config/sap_solutions.yaml` | `config/domain_catalog.yaml` | Domain-agnostic. |
| `bench_a38_runtime_v6.py` | `osmosis-bench/bench_answering.py` | Retirer `a38/v6`. |

---

## 6. Dépendances & pièges à ne pas oublier

À importer/recâbler **explicitement** (sources d'oubli classiques) :

- **Configs YAML** : `config/llm_models.yaml`, `config/prompts.yaml`, `config/rules*`, `config/neo4j*`, `config/sap_solutions.yaml`→`domain_catalog.yaml`. Vérifier les chemins relatifs après renommage du package.
- **Prompts** : prompts d'extraction (claimfirst staged), prompts answering (COMPARISON contrastif, premise verifier), prompts RFP. Retirer le **méga-prompt legacy**.
- **Schémas Pydantic** : `runtime_a3/schemas.py`, schémas claimfirst, schémas API. Centraliser dans `osmosis/schemas`. Attention aux `extra="ignore"` (ex `CitedClaim.source_doc_id`).
- **Migrations Neo4j / constraints** : `knowbase.semantic.setup_infrastructure`, `scripts/reset_proto_kg.py`. Recréer constraints + indexes (full-text claim.text). Collections Qdrant (`knowbase`→`osmosis`, `rfp_qa`, `knowwhere_proto`→`osmosis_proto`). **Renommer les collections** dans le code ET les scripts d'init.
- **Variables d'env** : tous les toggles runtime (`V6_PREMISE_VERIFIER_ENABLED`, `V6_GROUNDING_VERIFIER_ENABLED`, `V6_SUFFICIENCY_CHECK_ENABLED`, `V6_CROSS_ENCODER_RERANK`, `V6_HYBRID_RETRIEVAL`), ingestion (`INGESTION_SKIP_STRATIFIED_V2` → **supprimer** avec le legacy, `CLAIMFIRST_STAGED_PIPELINE` → **défaut 1**), `MAX_WALL_CLOCK_S`, `NOVITA_API_KEY` (⚠️ pas câblé dans compose actuel), clés API, ports. **Renommer les préfixes `V6_*`** en `ANSWERING_*`.
- **Dockerfiles & compose** : `app/Dockerfile`, `frontend/Dockerfile`, `docker-compose.infra.yml` (Qdrant/Redis/Neo4j/Postgres), `docker-compose.yml` (app/worker/frontend), service `folder_watcher` (`command: python -m ...watcher`), entrypoints worker. Le cockpit garde `docker-compose.monitoring.yml`.
- **Gold-sets & assets bench** : `benchmark/questions/**`, `gold_set_sap_v2`, runs historiques (→ osmosis-bench). Ne pas embarquer dans le core.
- **Assets publics** : slides/thumbnails (`data/public/**`), générateur de thumbnails.
- **Caches précieux** : `data/extraction_cache/*.knowcache.json` — **NE JAMAIS supprimer**. Prévoir leur portage/montage dans le nouveau repo.
- **`kw.ps1`** : script d'orchestration Docker → adapter au nouveau nommage.

---

## 7. Plan de migration pas-à-pas

> Pré-requis : stabilisation P1.4-bis terminée (staged pipeline validé). On migre **après** stabilisation.

1. **Créer le repo neuf `osmosis`** (à blanc, **PAS un fork**). Idem `osmosis-cockpit`, `osmosis-bench`.
2. **Extraire d'abord les utils partagés** du legacy (sinon on casse le vivant) :
   - `runtime_v3/nli_judge.py` → `osmosis/verification/nli.py`.
   - `runtime_v2/llm_client.py` → `osmosis/llm/runtime_client.py`.
   - `generate_document_summary` (osmose_enrichment) → module enrichment vivant.
   Mettre à jour les imports des consommateurs (`grounding_verifier`, `atlas/generator`, `query_decomposer`, `anchor_extractor`, `extraction_v2/pipeline`).
3. **Import sélectif du vivant** (ALIVE + KEEP-DORMANT) vers `osmosis` selon §3-4, **en renommant à la volée** (§5.4). Ne JAMAIS copier un dossier runtime legacy.
4. **Renommer le package** `knowbase`→`osmosis` (imports, `pyproject`, Dockerfiles, compose, scripts). Renommer collections Qdrant + préfixes env `V6_*`.
5. **Rendre le staged pipeline par défaut** (`CLAIMFIRST_STAGED_PIPELINE=1`), retirer le méga-prompt legacy, supprimer `INGESTION_SKIP_STRATIFIED_V2` et tout le bloc stratified/osmose_*.
6. **Câbler `main.py` core** : monter uniquement les ~30 routers ALIVE + KEEP-DORMANT. Décrocher les routers legacy/cockpit.
7. **Cockpit** : déplacer routers/services/frontend ops dans `osmosis-cockpit`, préfixe `/api/cockpit/*`, compose monitoring.
8. **Bench** : déplacer scripts + gold-sets + evaluators dans `osmosis-bench`.
9. **Smoke end-to-end** : ingérer 1-2 docs (cache préservé) → vérifier `:Claim` créés → poser une question via `/api/answer` → vérifier citations + abstention honnête. Smoke RFP Excel. Smoke search chat.
10. **CI** : pytest (cibler les tests des modules vivants seulement), ruff, mypy, `npm run build` frontend. Logger la config retrieval/LLM en début de tout bench (leçon A4.15).
11. **Secrets via vault** : clés API hors `.env` committé ; documenter les variables requises.
12. **Bench de non-régression** vs baseline OSMOSIS connue (exact_id_recall ≈ 0.788, abstention_correct ≈ 0.96, C1 ≈ 0.48-0.52).

### Checklist de non-régression

- [ ] `/api/answer` répond, premise+grounding verifiers ON, citations présentes.
- [ ] Ingestion par défaut = ClaimFirst **staged** ; 0 appel au pipeline stratified.
- [ ] `exact_id_recall` ≥ baseline (≈0.788) ; `abstention_correct` ≥ 0.95.
- [ ] Search chat end-user fonctionnel (`/search`).
- [ ] RFP autofill Excel fonctionnel.
- [ ] Aucun import résiduel vers `runtime_v3/v4/v4_poc/v4_2/v5`, `osmose_*`, `facts_first`.
- [ ] `nli_judge` et `llm_client` extraits ; `grounding_verifier`/`atlas`/`query_decomposer` OK.
- [ ] Collections Qdrant + constraints Neo4j recréées ; caches `.knowcache.json` préservés.
- [ ] Cockpit isolé (aucun router admin/bench monté dans le core).
- [ ] CI verte (pytest/ruff/mypy/frontend build).

---

## 8. Risques & questions ouvertes (décisions Fred)

**UNSURE / à trancher** :

1. **UI runtime_v2** : c'est la **seule UI d'answering/exploration câblée** (le runtime de prod `a3` n'est exposé qu'en cockpit/bench). Options : (a) **migrer cette UI vers `/api/answer`** puis retirer le pipeline v2 ; (b) garder v2 comme UI de prod transitoire. **Recommandation** : (a) — construire une UI chat sur `answering` avant de couper v2. Tant que non tranché, `/api/runtime_v2/answer` reste ALIVE.
2. **`admin.py`** : op core (purge/health data) ou cockpit ? Frontière. **Recommandation** : scinder — purge/health data dans le core (maintenance), dashboards dans le cockpit.
3. **`claimfirst.py` router** (monitoring jobs) : pipeline = core, mais son UI = `/admin/claimfirst`. **Recommandation** : router monitoring → cockpit ; pipeline `extraction/` → core.
4. **Couche Canonical** (`/claims/consolidate,/concept,/conflicts`) : non lue par le runtime mais câblée frontend. La garder (cockpit) ou la retirer ? **Recommandation** : cockpit tant que des écrans l'utilisent ; sinon legacy.
5. **`runtime_v5` (Reading Agent)** : LEGACY (auto-documenté superseded) MAIS la mémoire note une capacité unique (lecture texte source PDF que le KG-only n'a pas, alerte « runtime_v6 < V5.1 »). **Auditer** les briques transverses (HHEM verifier, observability/tracer, redlock, tenant_guard, two_phase_publish) AVANT de jeter — certaines peuvent devenir des modules communs.
6. **Re-passes KG pass2/3/4** : cockpit (les conserver comme outils ops) ou legacy (les supprimer avec le stratified) ? Dépend de leur valeur ops réelle.

**Pièges à NE PAS commettre** :
- Ne pas supprimer `nli_judge` (v3) / `llm_client` (v2) / `fill_excel_pipeline` / `subject_resolver` v1 / `merge_arbiter` / `generate_document_summary` : **tous ALIVE** malgré leur emplacement trompeur.
- Ne pas confondre `ingestion/queue/reprocess_job.py` (LEGACY) avec `domain_packs/reprocess_job.py` (**ALIVE**).
- Ne pas jeter `domain_packs/**` ni `semantic/extraction` (KEEP-DORMANT domain-agnostic).
- Ne pas embarquer `runtime_v6/` (extraction) en croyant que c'est un runtime.
- Ne pas se fier aux commentaires obsolètes (`relation_extraction_prompts.py:74` « Pipeline principal OSMOSE actuel » est **faux**).
- Mettre à jour le **logging de config** en tête de bench (V6_HYBRID_RETRIEVAL n'était positionné nulle part → benchs faussés A4.9-A4.14).
