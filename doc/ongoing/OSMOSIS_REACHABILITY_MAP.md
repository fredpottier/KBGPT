# OSMOSIS — Carte de Reachability Autoritative

> **Statut** : document de référence. Corrige `doc/ongoing/OSMOSIS_NEW_REPO_GUIDE.md` (1er audit).
> **Date** : 2026-05-31
> **Branche** : feat/phase-b-augmentee
> **Principe** : un composant est **VIVANT** seulement s'il est *atteignable transitivement* depuis une racine vivante figée — PAS parce qu'« un import existe » ni parce qu'il est « récent ».

---

## 1. Méthode

### Racines vivantes figées (point de départ du BFS)

**A. FRONTEND — racine rendue**
`frontend/src/app/layout.tsx` → `MainLayout` → `TopNavigation` (**SEULE** nav réellement rendue).
Arbre de nav vivant (`TopNavigation.tsx:48-91`) : Chat `/chat`, Compare `/compare`, Vérifier `/verify`, Atlas ▾ (`/atlas`, `/wiki`, `/wiki/articles`), Documents ▾ (`/documents/import`, `/documents/status`), Administration `/admin` (cockpit, nav propre dans `admin/layout.tsx`).
⚠️ `ContextualSidebar.tsx` = composant **MORT** (jamais importé/rendu). Tout lien qui n'existe QUE là est mort.
Une page est **ALIVE** seulement si atteignable transitivement depuis cet arbre (lien nav → page → `<Link>`/`router.push`/`href` interne → page…). Page existante mais non atteignable = **ORPHELINE** (legacy).

**B. BACKEND — 3 racines indépendantes**
1. **Routeur monté dans `api/main.py` ET réellement appelé** par une page frontend vivante (via proxies `frontend/src/app/api/**` ou fetch direct).
2. **WORKER / ingestion** : `folder_watcher` (docker-compose) → `ingestion/folder_watcher.py` → `queue/dispatcher` → `queue/jobs_v2.ingest_document_v2_job` → `ExtractionPipelineV2` → ClaimFirst → relations cross-doc. **Vivant par le worker, indépendamment de toute UI.**
3. **APPELS INTERNES** : un module est ALIVE s'il est appelé depuis l'intérieur d'un module vivant, même sans aucun import de routeur.

### Catégories de statut
- **ALIVE** : atteignable depuis une racine vivante (preuve = chemin fichier:ligne).
- **COCKPIT** : atteignable *uniquement* via l'espace `/admin` (racine vivante mais cantonnée au cockpit) — outillage admin/R&D, pas le chemin grand-public.
- **KEEP-DORMANT** : composant générique/cible intentionnel, non exercé aujourd'hui mais domain-agnostic et réactivable. **Jamais legacy.**
- **LEGACY** : inatteignable depuis toute racine vivante (preuve d'inatteignabilité, après vérif adversariale).

### Les 2 erreurs du 1er audit, corrigées ici

1. **`domain_packs._run_domain_pack_enrichment` classé mort à tort.**
   Réalité : appelé en interne par `claimfirst/orchestrator.py:667` (méthode `_run_domain_pack_enrichment` définie `:2935`). C'est un **appel interne d'un module vivant** (racine B.3) → **ALIVE**, alors qu'aucun routeur ne l'importe. Leçon : « aucun import de routeur » ≠ mort.

2. **RFP Excel + Documents UI classés vivants à tort (« un import/route existe »).**
   Réalité = **décision produit Fred** : RFP Excel **ABANDONNÉ** ; Documents UI **ABANDONNÉE** (le vrai import vivant = worker `folder_watcher`→`docs_in`, PAS le routeur HTTP `ingest`). Ces chaînes sont reclassées **LEGACY** même si des routes/pages restent techniquement câblées.

> Règle générale : on classe sur **« atteignable depuis une racine vivante »**, jamais sur « un import existe ». « Inchangé depuis longtemps » ≠ mort ; « inatteignable depuis l'entrée vivante » = mort. Un composant générique intentionnel non exercé = **KEEP-DORMANT**, jamais LEGACY (domain-agnostic).

---

## 2. Carte FRONTEND

### 2.1 Pages VIVANTES (atteignables)

| Route | Fichier | Atteinte depuis |
|---|---|---|
| `/` | `app/page.tsx` | Entrée appli → `router.push('/chat')` |
| `/chat` | `app/chat/page.tsx` | TopNav > Chat ; cible de la redirection de `/` |
| `/compare` | `app/compare/page.tsx` | TopNav > Compare (NavLink direct ; affiché si `hasCompare`, route reste atteignable) |
| `/verify` | `app/verify/page.tsx` | TopNav > Vérifier |
| `/atlas` | `app/atlas/page.tsx` | TopNav > Atlas ▾ > « Atlas narratif » |
| `/atlas/theme/[id]` | `app/atlas/theme/[id]/page.tsx` | `/atlas` → `NextLink` (atlas/page.tsx:349) |
| `/atlas/topic/[id]` | `app/atlas/topic/[id]/page.tsx` | `/atlas` → `NextLink` (atlas/page.tsx:382) |
| `/login` | `app/login/page.tsx` | `MainLayout` redirige non-authentifiés (MainLayout.tsx:24) ; bouton Connexion |
| `/register` | `app/register/page.tsx` | page auth (isAuthPage MainLayout.tsx:19), lien depuis `/login` |
| `/admin` (+ cockpit) | `app/admin/page.tsx` | Menu utilisateur > Paramètres → `/admin/settings` puis sidebar admin. Voir §3 COCKPIT. |

**Pages cockpit `/admin/**`** (vivantes via l'espace Administration, nav propre `admin/layout.tsx:59-114`) :
`/admin`, `/admin/gpu`, `/admin/backup`, `/admin/settings`, `/admin/theme`, `/admin/claimfirst`, `/admin/burst`, `/admin/domain-context`, `/admin/post-import`, `/admin/kg-hygiene`, `/admin/domain-packs`, `/admin/corpus-intelligence`, `/admin/contradictions`, `/admin/relations`, `/admin/relations/golden-set`, `/admin/corpus-audit`, `/admin/benchmarks`, `/admin/wiki-generator`, `/chat/runtime-v2` (lié depuis `admin/layout.tsx:100`).
⚠️ `/admin/markers` et `/admin/living-ontology` existent mais **hors sidebar courante** → cockpit-orphelines (à confirmer/retirer). `/admin/living-ontology` appelle un **routeur désactivé** (404 garanti, voir §3).
⚠️ **LIEN NAV CASSÉ** : `admin/layout.tsx:101` pointe vers `/admin/runtime-calibration` mais **aucune page** n'existe → lien mort dans la sidebar admin.

### 2.2 Pages VIVANTES mais FLAGGÉES par décision produit

| Route | Fichier | Flag |
|---|---|---|
| `/documents` | `app/documents/page.tsx` | Shell de redirection → `/documents/import`. **LEGACY** (Documents UI abandonnée). |
| `/documents/import` | `app/documents/import/page.tsx` | TopNav > Documents ▾ > « Import fichier ». **❌ LEGACY (décision produit).** Le backend d'ingestion (worker `folder_watcher`) reste **ALIVE** — ne pas confondre. |
| `/documents/status` | `app/documents/status/page.tsx` | TopNav > Documents ▾ > « Suivi imports ». **❌ LEGACY (décision produit)** — écran de suivi cockpit résiduel. |
| `/wiki` | `app/wiki/page.tsx` | TopNav > Atlas ▾ > « Wiki (legacy) ». **⚠️ FLAG legacy — décision Fred requise** (§4). |
| `/wiki/articles` | `app/wiki/articles/page.tsx` | TopNav > Atlas ▾ > « Articles wiki ». **⚠️ FLAG legacy.** |
| `/wiki/[slug]` | `app/wiki/[slug]/page.tsx` | Liens depuis `/wiki` et `/wiki/articles`. **⚠️ FLAG legacy.** |
| `/wiki/generate` | `app/wiki/generate/page.tsx` | Liens depuis `/wiki/articles` et `/wiki/[slug]`. **⚠️ FLAG legacy.** |
| `/wiki/domain/[facet_key]` | `app/wiki/domain/[facet_key]/page.tsx` | Lien depuis `/wiki`. **⚠️ FLAG legacy.** |

### 2.3 Pages ORPHELINES (LEGACY — inatteignables depuis la nav vivante)

| Route | Fichier | Raison |
|---|---|---|
| `/rfp-excel` | `app/rfp-excel/page.tsx` | Lié **uniquement** depuis `ContextualSidebar.tsx:95` (MORT). + **RFP Excel ABANDONNÉ**. |
| `/analytics` | `app/analytics/page.tsx` | Aucun `<Link>`/`router.push` depuis une page vivante (TopNav ni page reachable). |
| `/analytics/[hash]` | `app/analytics/[hash]/page.tsx` | Atteignable seulement depuis `/analytics` (lui-même orphelin). |
| `/documents/[id]` | `app/documents/[id]/page.tsx` | Aucune navigation interne ne pointe vers `/documents/<id>` (seuls appels API, pas de `<Link>`). |
| `/documents/rfp` | `app/documents/rfp/page.tsx` | Aucun lien nav vivant ; flux RFP (LEGACY). |
| `/documents/upload` | `app/documents/upload/page.tsx` | Aucun lien nav vivant (le flux d'import vivant = worker). |

> Fichier mort non-page repéré : `app/rfp-excel/page-original.tsx` (variante non routée).

### 2.4 Décisions produit appliquées (frontend)
- **RFP Excel** ❌ → `/rfp-excel` + `SAPSolutionSelector` + proxies excel = **LEGACY**.
- **Documents UI** ❌ → `/documents/import`, `/documents/status`, `/documents/upload`, `/documents/rfp`, `/documents/[id]` = **LEGACY** (mais backend ingestion worker reste ALIVE).
- **Wiki** ⚠️ → reachable mais étiqueté « legacy » dans la nav → **candidat retrait, décision Fred** (§4).

---

## 3. Carte BACKEND (par bloc)

### 3.1 Bloc `api-routers`

**ALIVE** (routeur monté + appelé par page vivante) :
| Routeur | Racine d'atteinte |
|---|---|
| `routers/search.py` | main.py:229 ; POST `/search` + GET `/corpus-features` appelés par `/chat` (lib/api.ts:197,221). **Vrai moteur d'answering en prod.** |
| `routers/sessions.py` | main.py:249 ; `/api/sessions` appelé par `/chat` (lib/api.ts:362-417). |
| `routers/markers.py` | main.py:255 ; GET `/markers` appelé par `/compare` (compare/page.tsx:141). |
| `routers/concepts.py` | main.py:245 ; POST `/concepts/diff` appelé par `/compare` (compare/page.tsx:188). |
| `routers/verify.py` | main.py:282 ; POST `/verify/upload-docx` appelé par `/verify` (proxy). |
| `routers/atlas.py` | main.py:291 ; `/atlas/homepage|topic|theme|perspective_topics` appelés par pages Atlas. |
| `routers/auth.py` | main.py:244 ; `/auth/*` alimente `/login`, `/register`, `fetchWithAuth`. **Infra transverse.** |

**KEEP-DORMANT** :
| Routeur | Raison |
|---|---|
| `routers/runtime_v6.py` | main.py:266. Routeur d'answering **CIBLE** (Parse→Plan→Execute→Evaluate→Synthesize, runtime_a3). Aucun appel HTTP frontend (grep `runtime_v6` = uniquement libellé d'onglet `RuntimeV6Tab.tsx`, jamais `fetch()`). Exercé par `scripts/bench_a38_runtime_v6.py`. Cible intentionnelle non câblée UI → **DORMANT, surtout pas LEGACY.** |
| `routers/wiki.py` | main.py:288. Techniquement ALIVE (pages `/wiki` reachable) mais entrée nav « legacy ». **Décision LEGACY/keep à TRANCHER PAR FRED** (§4). |
| `routers/document_types.py` | main.py:241. Proxies + `api.documentTypes` existent mais **aucune page** consommatrice. Gouvernance d'extraction générique domain-agnostic → DORMANT. |
| `routers/entity_types.py` | main.py:239. Référencé seulement par `admin/domain-context` (cockpit). Registry de gouvernance générique → DORMANT (rattaché cockpit). |
| `routers/entities.py` | main.py:238. Référencé seulement par `admin/domain-context` (cockpit). Gestion entités dynamiques générique → DORMANT. |
| `routers/entity_resolution.py` | main.py:251. Aucun proxy/appel frontend, mais brique de dédup cross-doc générique → DORMANT (vérifier appels pipeline avant purge). |

**COCKPIT** (atteignable uniquement via `/admin`) :
`routers/admin.py` (main.py:243), `kg_hygiene.py` (294), `post_import.py` (300), `domain_packs.py` (297), `corpus_intelligence.py` (256), `kg_health.py` (257), `relations_explorer.py` (258), `gpu.py` (269), `burst.py` (252), `claimfirst.py` (272), `backup.py` (285), `benchmarks.py` (303), `domain_context.py` (246), `runtime_v2.py` (260, sert `/chat/runtime-v2` lié seulement depuis cockpit), `jobs.py` (240).
**Cockpit/frontière-legacy** : `documents.py` (242), `imports.py` (232), `status.py` (231) — consommés par la Documents UI (LEGACY) ; ne survivent que comme écrans de suivi cockpit. Décision Fred.

**LEGACY** (monté-mais-jamais-appelé ou flux abandonné — vérifié adversarialement) :
| Routeur | Preuve d'inatteignabilité |
|---|---|
| `routers/runtime_v3.py` | main.py:261 ; grep `runtime_v3` frontend = 0. Aucune page/proxy/appel interne vivant. |
| `routers/runtime_v4.py` | main.py:262 ; grep = 0. |
| `routers/runtime_v4_poc.py` | main.py:263 ; grep = 0. POC. |
| `routers/runtime_v4_2.py` | main.py:264 ; grep = 0. |
| `routers/runtime_v5.py` | main.py:265 ; grep `runtime_v5` frontend = 0. V5.1 Reading Agent non câblé UI. |
| `routers/challenge.py` | main.py:279 ; grep = 0. Fonction couverte par `/verify`. |
| `routers/ingest.py` | main.py:230. `fill_excel_rfp` (RFP ABANDONNÉ) + uploads consommés seulement par Documents UI (LEGACY). Vrai import = worker. |
| `routers/downloads.py` | main.py:234. `/filled-rfp/{uid}` = flux RFP Excel ABANDONNÉ. |
| `routers/solutions.py` | main.py:233. Consommé seulement par `SAPSolutionSelector` → `rfp-excel` (ABANDONNÉ). |
| `routers/analytics.py` | main.py:254. Consommé seulement par pages `/analytics*` ORPHELINES. |
| `routers/navigation.py` | main.py:253. Grep endpoint = 0 (exploration reprise par Atlas). |
| `routers/insights.py` | main.py:247. Aucun consommateur frontend. |
| `routers/facts.py` | main.py:236. Aucun appel (`/api/facts` grep = 0 ; hits « artefacts » = faux positifs). Service exclusif `facts_service.py` mort. |
| `routers/ontology.py` | main.py:237. Grep `/api/ontology` = 0. |
| `routers/claims.py` | main.py:250. `api.claims` défini mais 0 page consommatrice. Couche Canonical = cockpit/legacy. |
| `routers/token_analysis.py` | main.py:235. Grep endpoint = 0. |
| `routers/living_ontology.py` | **NON monté** : main.py:23 + 248 commentés (« living_ontology désactivé »). Injoignable par construction. La page `/admin/living-ontology` appelle ce routeur → **404 garanti**. |

### 3.2 Bloc `answering-runtime` (runtime_v2/v3/v4/v4_2/v4_poc/v5/v6 + runtime_a3)

**ALIVE** :
- `api/services/search.py` + `routers/search.py` — **VRAI moteur d'answering prod** (POST `/search`, `/chat`). Auto-suffisant : synthesis + retriever + query_decomposer + perspectives. N'utilise **AUCUN** runtime_v*/a3.
- `api/services/query_decomposer.py` — appel interne `search.py:887`.
- `runtime_v2/llm_client.py` — **ALIVE bien que le dossier runtime_v2 soit globalement legacy** : `query_decomposer.py:895` l'importe (toujours exécuté), aussi `atlas/generator.py:212`.
- `routers/runtime_v2.py` — sert `/chat/runtime-v2`, lié **uniquement** depuis le cockpit admin → **COCKPIT** (debug doc_detail/claim_detail/lifecycle), pas le chat de prod.

**COCKPIT / R&D** :
- `runtime_a3/**` — moteur KG-first cible (Parse→Plan→Execute→Evaluate→Synthesize). Atteint via `runtime_v6.py` (bench R&D) + scripts. **Aucune page nav publique.** À promouvoir ALIVE si Fred bascule `/search` sur a3.
- `routers/runtime_v6.py` — banc d'essai exposant runtime_a3.
- `app/scripts/bench_a38_runtime_v6.py` — harnais de benchmark.

**KEEP-DORMANT** :
- `runtime_a3/grounding_verifier.py` — vérificateur NLI (HHEM/nli) domain-agnostic générique. Atteint seulement via a3/v6 (non-live) + bench. Brique d'intégrité réutilisable → dormant jusqu'à décision moteur KG-first.
- `runtime_v3/nli_judge.py` — juge NLI partagé (`judge_faithfulness`). Appelants actuels (a3, facts_first) non-live, mais brique d'évaluation générique → dormant le temps de la migration osmosis.

**LEGACY** (cluster auto-référentiel, routeurs montés jamais appelés) :
`routers/runtime_v3.py` + `runtime_v3/` (sauf `nli_judge` dormant), `routers/runtime_v4.py` + `facts_first/`, `routers/runtime_v4_poc.py` + `runtime_v4_poc/`, `routers/runtime_v4_2.py` + `runtime_v4_2/`, `routers/runtime_v5.py` + `runtime_v5/` (modules `agent/*` portent des avertissements DEPRECATED auto-loggés).
> Piège écarté : `facts_first` et `runtime_v4` utilisent une classe `EvidenceBundle` venant de `facts_first.evidence_collector`, **distincte** de `relations.evidence_bundle_models`. ClaimFirst (worker vivant) n'importe **aucun** `facts_first` (grep = 0).

### 3.3 Bloc `ingestion` (`src/knowbase/ingestion/**`)

**ALIVE (worker B.2 + appels internes)** :
`folder_watcher.py` (run_watcher → enqueue_file), `queue/dispatcher.py`, `queue/jobs_v2.py` (`ingest_document_v2_job` → `_run_extraction_v2` → ClaimFirst), `queue/connection.py`, `queue/worker.py`, `queue/__main__.py`, `queue/__init__.py`, `pipelines/pass05_coref.py` (pipeline.py:343, `enable_linguistic_coref` défaut ON), **`osmose_enrichment.py`** (appel live `extraction_v2/pipeline.py:735` `generate_document_summary`, **indépendant** du chemin osmose_agentique dormant — voir Deltas §5), `document_valid_from_extractor.py` (orchestrator.py:199), `enrichment_tracker.py`, `resilience/recovery.py|job_manager.py|job_state.py|__init__.py` (worker boot), `burst/resync_subscriber.py|provider_switch.py|orchestrator.py|__init__.py|types.py|artifact_importer.py|artifact_exporter.py|resilient_client.py|aws_truth_service.py` (worker boot + routeur burst cockpit), `extraction_cache.py` (précieux par règle CLAUDE.md), `__init__.py`.

> **Note d'arbo** : `ExtractionPipelineV2` vit sous `src/knowbase/extraction_v2/pipeline.py` (PAS `ingestion/extraction_v2/`). Tout le sous-arbre `extraction_v2/**` (docling/pptx/markdown extractors, vision, gating, context, merge, tables…) est **ALIVE** via le worker (`jobs_v2._run_extraction_v2`).

**KEEP-DORMANT** :
- `osmose_agentique.py`, `osmose_integration.py`, `osmose_persistence.py`, `osmose_utils.py`, `text_chunker.py`, `hybrid_anchor_chunker.py` — chemin **Stratified V2** court-circuité par défaut (`INGESTION_SKIP_STRATIFIED_V2=true`, jobs_v2.py:386). Importés mais non exercés. Réactivables → dormant, pas legacy.
- CLI ops standalone (`cli/generate_thumbnails.py`, `cli/purge_collection.py`, `cli/purge_collection_entries.py`, `cli/test_search_qdrant.py`, `cli/update_main_solution.py`, `cli/update_supporting_solutions.py`, `cli/__init__.py`) — outils de maintenance manuels volontaires.
- `processors/__init__.py`, `pipelines/__init__.py` (contient pass05_coref ALIVE) — packages nécessaires.

**COCKPIT** :
`queue/pass2_jobs.py`, `queue/pass3_jobs.py`, `queue/pass4_jobs.py`, `pass2_orchestrator.py` — enfilés **uniquement** depuis `routers/admin.py:1598+` (espace `/admin`). Pipeline post-import piloté via le cockpit.

**LEGACY** :
| Module | Preuve |
|---|---|
| `pipelines/excel_pipeline.py` | folder_watcher→`ingest_excel_job`→`process_excel_rfp` = flux RFP Excel ABANDONNÉ. Ne feed PAS ClaimFirst. |
| `pipelines/fill_excel_pipeline.py` | Importé seulement par `smart_fill_excel_pipeline` (chaîne fill_excel RFP). |
| `pipelines/smart_fill_excel_pipeline.py` | `fill_excel_job` enfilé seulement par `ingest.fill_excel_rfp` (RFP ABANDONNÉ). |
| `queue/pass35_jobs.py` | grep `enqueue_pass35`/`pass35` hors fichier = 0. Jamais enfilé. |
| `queue/reprocess_job.py` | Unique appelant = `stratified/api/router.py:659`, routeur **commenté** dans main.py (l.20, 276) → non monté. ≠ `domain_packs/reprocess_job.py` (ALIVE). |
| `slide_reconstructor.py` | grep hors fichier = 0. Remplacé par extraction_v2 (Docling). |
| `validate_osmose_deps.py` | Script `python -m` validant un chemin dormant ; aucun import vivant. |
| `cli/migrate_collection.py` | Migration one-shot sap_kb→knowbase déjà effectuée. |

### 3.4 Bloc `extraction-kg` (`claimfirst/**` + `semantic/**` + `relations/**`)

**ALIVE (worker ClaimFirst, racine B.2 + appels internes)** :
`claimfirst/orchestrator.py` (← `worker_job.claimfirst_process_job` ← `jobs_v2.py:439`), `claimfirst/worker_job.py`, `claimfirst/models/**`, `extractors/claim_extractor.py` (+ entity/context/facet/noun_chunk/merge_arbiter/question_signature extractors), `resolution/subject_resolver.py` **et** `subject_resolver_v2.py` (les **deux** câblés, pas une variante morte), `axes/**`, `applicability/**`, `linkers/**`, `clustering/**`, `composition/**`, `comparisons/qs_comparator.py`, `persistence/claim_persister.py`, `quality/**` + `quality_filters.py`, `subject_indexer.py`, `constants.py`, `v6/procedure_extractor.py|procedure_linker.py|procedure_persister.py` (P1.3 câblé productif), `temporal/temporal_extractor.py`.
**Domain packs (correction n°1)** : `_run_domain_pack_enrichment` (orchestrator.py:667/2935) → la chaîne `domain_packs/**` est **ALIVE** par appel interne, sans aucun import de routeur.
`semantic/utils/language_detector.py` + `semantic/config.py` (via common), `semantic/inference/**` (graph_guided_search + insights).

**KEEP-DORMANT** :
- `claimfirst/canonicalization/**` (couche CanonicalClaim) — spec d'avenir (ARCH_CLAIMFIRST §Future Work), touchée seulement par le cockpit. Archi cible → dormant.
- `claimfirst/query/**` (temporal_query_engine, text_validator, scoped_query) — voie d'interrogation KG côté admin/diagnostic. Briques génériques réutilisables → dormant.
- `relations/types.py` — types partagés transversaux domain-agnostic.

**COCKPIT** :
- `routers/claimfirst.py`, `routers/claims.py` (couche Canonical), `routers/post_import.py` (c4/c6 cross-doc), `pass2_orchestrator.py` + `pass2_jobs.py`/`pass3_jobs.py` + `pass2_service.py`, `relations/candidate_miner_c4.py`, `relation_persister_c4.py`, `pivot_miner_c6.py`, `pivot_adjudicator_c6.py` — pilotés depuis `/admin`.
- **`relations/segment_relation_extractor.py` & co** (segment_window, structural_topic, scope_candidate_miner, scope_verifier, normative_*, discursive_pattern, semantic_consolidation_pass3, structure_parser, raw_assertion_writer) — **RECLASSÉ COCKPIT** (pas LEGACY) : importés par `pass2_orchestrator`/`pass2_service`, enfilés depuis `routers/admin.py` (cockpit). À conserver tant que les actions pass2/3/4 du cockpit existent.

**LEGACY** :
| Module | Preuve |
|---|---|
| `agents/supervisor/**` + `agents/gatekeeper` | Importés seulement par osmose_agentique/osmose_utils (Stratified V2 SKIPPED). |
| `relations/extraction_engine.py`, `neo4j_writer.py`, `llm_relation_extractor.py`, `doc_level_extractor.py`, `catalogue_builder.py` | Importés seulement par osmose_integration/persistence/supervisor (SKIPPED). **ClaimFirst n'importe aucun `knowbase.relations`** (grep orchestrator = 0). |
| `relations/candidate_miner_v33.py`, `gate_v33.py`, `v33_types.py` | Sous-graphe fermé interne à relations/, 0 importeur externe, absent de `relations/__init__.py`. |
| `relations/evidence_bundle_*` + `bundle_persistence.py` + `bundle_validator.py` | Importés seulement par `pass35_jobs.py` (jamais enfilé). Classe homonyme ≠ `facts_first.EvidenceBundle`. |
| `semantic/**` (profiler, segmentation, classification, extraction, indexing, linking, ontology, anchor_resolver, semantic_pipeline_v2, concept_embedding_service) | extraction_v2 + claimfirst n'importent **aucun** `knowbase.semantic` (grep = 0). Tirés seulement par osmose_* (SKIPPED) ou pass2 (cockpit). **CAVEAT** : `semantic/extraction/prompts.py` (`get_llm_judge_prompt`) importé lazy par `ontology/entity_normalizer_neo4j.py:428` (vivant) → **ne pas purger aveuglément tout `semantic/extraction/`**. `semantic/anchor_resolver` tiré par segment_relation_extractor (cockpit). `living_ontology`/`graph_guided_search` désactivés. |

### 3.5 Bloc `backend-services-common`

**ALIVE (infra transverse)** : `common/clients/neo4j_client.py` (71 importeurs), `qdrant_client.py` (19), `embeddings.py` (30), `redis_client.py` (9), `openai_client.py`, `anthropic_client.py`, `http.py`, `reranker.py` (runtime_v2 + runtime_a3), `shared_clients.py` ; `common/llm_router.py` (hub, 111 consommateurs), `llm_config.py`, `logging.py` (576 refs), `metrics.py`, `circuit_breaker.py`, `auth.py`, `context_id.py`, `corpus_stats.py`, `deprecation.py`, `dual_llm_logger.py`, `entity_normalizer.py`, `entity_types.py`, `language_detector.py`, `log_sanitizer.py`, `token_tracker.py`, `stopwords.py` ; `config/settings.py` (149), `feature_flags.py` (23), `paths.py` (7), `prompts_loader.py`, `response_modes_thresholds.py`.

**LEGACY (aucun consommateur de prod, seulement tests/docs)** :
| Module | Preuve |
|---|---|
| `common/tracing.py` | `trace_operation/span` référencés seulement dans le fichier + tests. Absent de `common/__init__.py`, aucun import prod. |
| `common/pagination.py` | `paginate()` seulement dans fichier + tests + doc planning. Aucun import prod. |
| `common/redis_client_resilient.py` | Référencé seulement fichier + tests + doc archive. Le worker utilise le client Redis standard. |
| `config/detection_keywords.py` | Référencé seulement par `benchmark/evaluators/*` + tests. benchmark/ n'est pas une racine vivante. |
| `api/services/graph_first_search.py` | Importé par personne en prod (absent main.py/routers/__init__). Seulement tests + docs. |
| `api/services/coverage_map_service.py` | Aucun import backend. Hits frontend = faux positifs (sous-chaîne). |
| `api/services/facts_service.py` | Importé seulement par `routers/facts.py` (jamais appelé). Hits frontend « artefacts » = faux positifs. |

---

## 4. Arbitrages produit pour Fred (features reachable mais candidates à retrait)

| # | Feature | État reachability | Pourquoi candidate retrait | Décision demandée |
|---|---|---|---|---|
| 1 | **Wiki** (`/wiki`, `/wiki/articles`, `/wiki/[slug]`, `/wiki/generate`, `/wiki/domain/[key]` + `routers/wiki.py`) | **ALIVE** mais entrée nav étiquetée « legacy » | Tu l'as toi-même marqué « legacy » dans TopNav ; doublonne avec Atlas (narratif). | **LEGACY (retrait) ou KEEP ?** Ne pas trancher seul. |
| 2 | **Documents UI** (`/documents/import`, `/documents/status`) | reachable nav, mais **flaggé LEGACY** (ta décision) | Le vrai import vivant = worker `folder_watcher` (dépôt `docs_in`). L'UI HTTP ne sert qu'à un suivi résiduel. | Confirmer retrait UI + conservation routeurs `imports/status/documents` comme cockpit-suivi, OU retrait complet. |
| 3 | **`/chat/runtime-v2`** (debug answering) | reachable seulement via cockpit `/admin` | Outil d'inspection R&D ; le chat de prod = `/search`. | Garder en cockpit ou retirer une fois runtime_a3 tranché. |
| 4 | **`/analytics` + `/analytics/[hash]`** | **ORPHELINES** (déjà non liées) | Aucun lien nav ; pages de qualité d'import isolées. | Confirmer suppression (purge sûre). |
| 5 | **RFP Excel** (`/rfp-excel` + `solutions`/`downloads`/`ingest.fill_excel` + 3 pipelines excel) | **ORPHELIN/LEGACY** (ta décision) | Abandonné. | Confirmer purge du bloc complet. |
| 6 | **`/admin/markers`, `/admin/living-ontology`** | hors sidebar admin courante | `living-ontology` appelle un routeur **désactivé** (404 garanti). `markers` non lié dans la sidebar. | Retirer pages mortes + lien cassé `/admin/runtime-calibration` (admin/layout.tsx:101). |

---

## 5. Deltas vs le guide initial (`OSMOSIS_NEW_REPO_GUIDE.md`)

| Élément | Statut guide initial | Statut corrigé (reachability) | Raison |
|---|---|---|---|
| `domain_packs/**` (`_run_domain_pack_enrichment`) | mort / sans consommateur | **ALIVE** | Appel interne `orchestrator.py:667` (B.3). « Aucun import de routeur » ≠ mort. |
| `ingestion/osmose_enrichment.py` | mort par transitivité d'osmose_agentique (SKIPPED) | **ALIVE** | Appelant **indépendant** vivant : `extraction_v2/pipeline.py:735` `generate_document_summary` (étape 6a live). La transitivité « tout ce qu'osmose_agentique tire est mort » était **fausse** pour ce module. |
| `relations/segment_relation_extractor.py` & co (normative, scope, structural_topic, semantic_consolidation_pass3…) | LEGACY | **COCKPIT** | Importés par pass2_orchestrator/pass2_service, enfilés depuis `routers/admin.py` (espace `/admin` = racine vivante). Pas legacy tant que les actions pass2/3/4 cockpit existent. |
| `semantic/extraction/prompts.py` | LEGACY (avec tout `semantic/**`) | **CAVEAT — ne pas purger** | `get_llm_judge_prompt` importé lazy par `ontology/entity_normalizer_neo4j.py:428` (vivant). Tendrille vivante dans un bloc majoritairement legacy. |
| `resolution/subject_resolver_v2.py` | variante possiblement morte | **ALIVE** | Les **deux** resolvers câblés (orchestrator.py:49-50), pas une variante abandonnée. |
| RFP Excel (`/rfp-excel`, solutions, downloads, ingest.fill_excel, pipelines excel) | reachable / vivant (routes existent) | **LEGACY** | Décision produit Fred : abandonné. Atteignabilité technique ≠ vivant produit. |
| Documents UI (`/documents/import`, `/documents/status`, upload, rfp, [id]) | vivant (dans TopNav) | **LEGACY (produit)** | Décision produit ; vrai import = worker. Routeurs `imports/status/documents` rétrogradés cockpit-suivi. |
| `runtime_v6.py` / `runtime_a3/**` | (ambigu) potentiellement vivant | **KEEP-DORMANT / COCKPIT R&D** | Aucun appel HTTP frontend (grep = onglet bench seulement). Cible intentionnelle non câblée. Jamais LEGACY. |
| `runtime_v2/llm_client.py` | mort (dossier runtime_v2 legacy) | **ALIVE** | `query_decomposer.py:895` l'importe dans le chemin `/search` vivant. Fichier vivant dans un dossier globalement legacy. |
| `living_ontology.py` (routeur) | (monté ?) | **LEGACY confirmé** | main.py:23+248 **commentés** → non monté. Page `/admin/living-ontology` → 404. |
| `facts_service.py` / `routers/facts.py` | (présumé utile) | **LEGACY** | Monté-mais-jamais-appelé ; hits « artefacts » = faux positifs. |
| `common/tracing.py`, `pagination.py`, `redis_client_resilient.py`, `graph_first_search.py`, `coverage_map_service.py`, `detection_keywords.py` | (présumés infra) | **LEGACY** | Aucun consommateur de prod (seulement tests/docs/benchmark). |
| Cluster `runtime_v3/v4/v4_poc/v4_2/v5` + `facts_first` | (versions historiques) | **LEGACY** (sauf `nli_judge`, `grounding_verifier` = dormant) | Routeurs montés jamais appelés ; cluster auto-référentiel ; `/search` est le moteur vivant. |

---

## 6. Résumé chiffré

- **Frontend** : 10 pages publiques ALIVE + ~21 pages cockpit `/admin` ; **8 pages flaggées** (Documents UI ×2 + Wiki ×5 + `/documents` shell) ; **6 pages ORPHELINES/LEGACY** ; 2 pages cockpit mortes (markers, living-ontology) + 1 lien nav cassé.
- **Backend `api-routers`** : 7 ALIVE, 6 KEEP-DORMANT, ~18 COCKPIT, 17 LEGACY.
- **Answering-runtime** : 3 ALIVE (search/query_decomposer/runtime_v2.llm_client) + runtime_v2 router COCKPIT ; 3 COCKPIT R&D (a3/v6/bench) ; 2 KEEP-DORMANT ; ~5 clusters LEGACY (v3/v4/v4_poc/v4_2/v5 + facts_first).
- **Ingestion** : ~26 ALIVE, ~13 KEEP-DORMANT, 4 COCKPIT, 8 LEGACY.
- **Extraction-KG** : grand bloc ClaimFirst ALIVE + domain_packs ALIVE ; 3 KEEP-DORMANT ; ~6 COCKPIT (dont segment_relation reclassé) ; ~6 familles LEGACY (semantic/**, agents/**, relations historiques).
- **Common/services** : ~30 ALIVE (infra), 7 LEGACY.

**Corrections majeures vs guide initial : 13** (voir §5) — dont **6 changements de statut « durcissants »** vers vivant/cockpit qui auraient causé une suppression à tort : domain_packs, osmose_enrichment, segment_relation/pass2, semantic/extraction/prompts, subject_resolver_v2, runtime_v2/llm_client.

**Top 3 arbitrages produit à trancher** : (1) **Wiki** retrait ou keep ; (2) **Documents UI** retrait UI + sort des routeurs imports/status/documents ; (3) purge des **orphelines** (`/analytics*`, RFP Excel complet, pages admin mortes + lien `/admin/runtime-calibration`).
