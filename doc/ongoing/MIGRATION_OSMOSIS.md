# Migration vers OSMOSIS — Plan de reconstruction propre

> **Statut :** Proposition de travail (à valider) — document de migration.
> **Objet :** Spécifier précisément quel code reprendre, comment le renommer et l'organiser,
> pour créer un nouveau dépôt `osmosis` débarrassé du legacy accumulé par 9 mois de pivots.
> **Source :** audit complet de l'existant KBGPT (mai 2026) — graphe d'imports depuis les
> points d'entrée réels (worker d'ingestion + API `/search`).

---

## 0. Pourquoi ce document

Le projet actuel n'a pas un problème d'architecture : la vision (`VISION.md`) et la doc
d'architecture sont saines et récentes (refonte 18/05/2026). Le problème est l'**accumulation
de code mort qui cohabite avec le code vivant sans séparation** — d'où les « mauvais
branchements » qui ramènent vers du legacy (`stratified`, `runtime_v2`, `agents`…).

Plutôt que forker + élaguer (qui traîne l'historique et les couplages cachés), on **repart d'un
dépôt neuf `osmosis`** où l'on importe sélectivement le **cœur actif uniquement**, avec un
**nommage propre** et une **séparation des outils annexes**.

Ordre de grandeur de la cure : `src/knowbase` passe de **869 → ~470 fichiers `.py` (-45 %)**,
suppression de ~440 markdown d'archive et ~160 scripts jetables.

---

## 1. Principes directeurs

1. **Plus aucun nom de version ni de pivot dans le code.** `extraction_v2`, `runtime_v3`,
   `claimfirst`, `stratified`, `facts_first`, `runtime_a3` → noms porteurs et stables.
2. **`knowbase` n'existe plus.** Le package racine devient `osmosis`. Ancien naming
   (`KnowBase`, `KnowWhere`, `SAP KB`) banni du code, des logs et de la doc.
3. **Un seul chemin par responsabilité.** Une seule lignée d'extraction, un seul runtime Q/A.
   Le code mort n'est pas importé : il n'existe pas dans le dépôt.
4. **Les outils annexes sont des dépôts indépendants** (cockpit, bench) — pas livrés en prod
   sur chaque déploiement.
5. **Domain-agnostic par construction** (axiome AX-11 de VISION.md) : aucun couplage SAP en dur.
6. **La doc de référence est reprise telle quelle** (VISION, ROADMAP, ARCH_*, ADR) — c'est la
   boussole, elle est déjà propre.

---

## 2. Stratégie multi-dépôts

| Dépôt | Contenu | Justification |
|---|---|---|
| **`osmosis`** | Produit : backend (FastAPI + worker), frontend, infra de déploiement, doc, config, tests | Le livrable |
| **`osmosis-cockpit`** | Service de supervision autonome (actuel `cockpit/`) | **Demande explicite** : système indépendant qui se *branche* sur une instance pour remonter métriques/feedback ; ne doit pas être déployé en prod sur chaque système. WebSocket + UI statique + collectors (docker, burst, llm_budget, ragas, pipeline). |
| **`osmosis-bench`** *(proposé)* | Harnais d'évaluation (`benchmark/` code + gold sets) | 29 Mo dont l'essentiel = datasets et résultats. C'est un outil de R&D, pas du runtime produit. Le **code d'éval + gold sets** y vivent ; les **runs datés** (`runs/`, 5.4 Mo) sont jetés. |

> **Couplage cockpit ↔ osmosis :** le cockpit consomme l'API/les logs/Redis/Neo4j d'une instance
> osmosis. Définir un **contrat d'interface stable** (endpoints de métriques + format logs) plutôt
> qu'un import de code. Si du code est partagé (ex. modèles de métriques), en faire un petit
> package publié, pas une dépendance de chemin.

---

## 3. Convention de nommage

### 3.1 Package racine
`src/knowbase/` → **`src/osmosis/`** (et tous les `from knowbase.…` → `from osmosis.…`).

### 3.2 Table de renommage des modules

| Ancien | Nouveau | Rôle | Note |
|---|---|---|---|
| `extraction_v2/` | **`extraction/`** | Parsing documents (Docling + Vision) + cache versionné | Absorbe `stratified/pass0` (cache_loader) + `structural/models` |
| `claimfirst/` | **`claims/`** | Pipeline d'extraction de claims atomiques (cœur épistémique) | Renommer aussi `ARCH_CLAIMFIRST.md` → `ARCH_CLAIMS.md` |
| `claimfirst/v6/` + module `runtime_v6/` | **`claims/procedures/`** | Extraction procédures/références (feature gardée derrière flag) | Voir décision §8 |
| `runtime_a3/` + router `runtime_v6.py` + infra de `runtime_v5/` + `runtime_v3/nli_judge` | **`runtime/`** | Q/A KG-first : Parse → Plan → Execute → Evaluate → Synthesize | Terme aligné sur VISION §4.4 |
| `semantic/inference/` | **`inference/`** | InferenceEngine (alimente le router `insights`) | Le reste de `semantic/` est dissous |
| `semantic/utils/` (langue, embeddings) | **`common/nlp/`** | Détection de langue + embeddings utilitaires | Fusion dans le socle commun |
| `neo4j_custom/` | **`kg/neo4j/`** | Utilitaires Neo4j | Regroupement KG (§4, optionnel) |
| `relations/` | **`kg/relations/`** | Relations claim-vs-claim, enrichissement KG | Regroupement KG (optionnel) |
| `ontology/` | **`kg/ontology/`** | Catalogues d'entités/types | Regroupement KG (optionnel) |
| `hygiene/` | **`kg/hygiene/`** | Règles de qualité KG | Regroupement KG (optionnel) |
| `entity_resolution/` | **`kg/entity_resolution/`** | Résolution/fusion d'entités | Regroupement KG (optionnel) |

### 3.3 Noms conservés (déjà porteurs)
`api/`, `ingestion/`, `common/`, `config/`, `retrieval/`, `memory/`, `navigation/`, `wiki/`,
`atlas/`, `verification/`, `logging/`, **`domain_packs/`** (nom déjà porteur : packs domain-centric
pluggables — concept central, à conserver tel quel).

---

## 4. Architecture cible du dépôt `osmosis`

```
osmosis/
├── src/osmosis/
│   ├── api/                  # FastAPI : create_app, routers (élagués), services, schemas
│   ├── ingestion/            # worker RQ, dispatcher, jobs, folder_watcher, burst, resilience
│   │   └── extraction/       # ex-extraction_v2 : Docling + Vision + cache versionné
│   ├── claims/               # ex-claimfirst : pipeline claims atomiques (cœur)
│   │   └── procedures/       # ex-claimfirst/v6 + ex-module runtime_v6 (gated)  [cf §8]
│   ├── runtime/              # Q/A KG-first consolidé (ex-a3 + infra v5 + nli_judge v3)
│   │   ├── verifier/  api/  tools/  observability/
│   ├── retrieval/            # Layer R, rechunker, services de recherche
│   ├── inference/            # ex-semantic/inference (InferenceEngine → insights)
│   ├── kg/                   # [regroupement proposé]
│   │   ├── relations/  ontology/  hygiene/  entity_resolution/  neo4j/
│   ├── domain_packs/         # Domain Packs pluggables (ajout de packs domain-centric)
│   ├── memory/               # sessions
│   ├── navigation/  wiki/  atlas/  verification/
│   ├── common/               # clients (Qdrant/Neo4j/Redis/PG), llm_router, nlp/, utils
│   ├── config/               # settings + chargement YAML
│   └── logging/
├── frontend/                 # repris ~tel quel (nettoyage mineur, cf §5.9)
├── config/                   # YAML métier (llm_models, prompts, domains…)
├── doc/                      # VISION + ROADMAP + ARCH_* + OPS + DEV_GUIDE + ongoing/adr
├── tests/                    # tests alignés au code repris
├── migrations/               # *.cypher versionnés
├── schemas/
├── scripts/                  # ~40 outils durables (setup/reset/migrate/import-export)
├── docker-compose.infra.yml
├── docker-compose.yml
├── docker-compose.monitoring.yml
├── app/Dockerfile  frontend/Dockerfile
└── README.md  CLAUDE.md (réécrits)
```

> Le regroupement `kg/` est **optionnel** : il clarifie mais représente un déplacement de plus.
> Si on veut minimiser les déplacements au premier jet, garder `relations/`, `ontology/`,
> `hygiene/`, `entity_resolution/`, `neo4j_custom/` à plat et regrouper plus tard.

---

## 5. Inventaire détaillé : GARDER / RENOMMER / JETER

### 5.1 Ingestion (cœur, GARDER)
Flux réel confirmé :
```
folder_watcher / dispatcher → RQ jobs_v2.ingest_document_v2_job
  → extraction (Docling + Vision) ──> cache data/extraction_cache (versioned_cache.py, v5)
  → [Stratified V2 / osmose_agentique : SKIPPÉ par défaut — à supprimer]
  → enqueue ClaimFirst → claims.orchestrator  (cœur productif)
```
- **GARDER** : `ingestion/queue/` (`worker.py`, `dispatcher.py`, `jobs_v2.py`, `connection.py`,
  `__main__.py`), `ingestion/folder_watcher.py`, `ingestion/resilience/`, `ingestion/burst/`.
- **GARDER → `extraction/`** : tout `extraction_v2/**` (52 fichiers), dont
  `extraction_v2/cache/versioned_cache.py` = **le vrai gestionnaire du cache précieux** (format v5).
- **GARDER (utilitaires relus par claims)** puis fondre dans `extraction/` :
  `stratified/pass0/cache_loader.py`, `stratified/pass0/adapter.py`,
  `stratified/pass1/assertion_unit_indexer.py`, `stratified/models/`, `structural/models.py`.
- **JETER** : `ingestion/osmose_agentique.py`, `ingestion/osmose_*`, `pass2_orchestrator.py`,
  `ingestion/processors/` (vide), `ingestion/extraction_cache.py` (ancien `.knowcache.json`,
  remplacé par `versioned_cache.py` ; vérifier d'abord les call-sites admin/backup/purge).
- **À vérifier** : jobs auxiliaires `pass2_jobs.py / pass3 / pass35 / pass4 / reprocess_job.py`
  (sont-ils enqueués en prod ? sinon jeter).

### 5.2 Claims (cœur, GARDER → `claims/`)
`claimfirst/` (105 fichiers, 40k LOC) repris intégralement et renommé `claims/`. Sous-modules
réellement utilisés par l'orchestrator/worker : `models/`, `extractors/`, `linkers/`,
`clustering/`, `composition/`, `axes/`, `applicability/`, `resolution/`,
`persistence/claim_persister.py`, `quality/` + `quality_filters.py`,
`comparisons/qs_comparator.py`, `subject_indexer.py`, `constants.py`.
- `claimfirst/v6/` → `claims/procedures/` (gardé derrière flag `V6_PROCEDURE_EXTRACTION`, **off**
  par défaut). Décision §8.

### 5.3 Runtime Q/A (consolider → `runtime/`)
`runtime_a3` est quasi autonome (ne dépend que de `common/`). Plan de consolidation :
- **GARDER (cœur)** : tout `runtime_a3/` → `runtime/` (`orchestrator, parse, plan, execute,
  evaluate, synthesize, schemas, predicate_resolver, subject_resolver, claim_filter, reranker,
  sufficiency_checker, grounding_verifier`).
- **GARDER (façade)** : `api/routers/runtime_v6.py` → `api/routers/runtime.py`.
- **PORTER depuis `runtime_v3/`** : `nli_judge.py` (seul fichier requis — par a3 + verifier).
- **PORTER depuis `runtime_v5/` (infra réutilisable, sinon perte sèche)** :
  - `api/` : `models, admission, idempotency, job_store, sse, router`
  - `tools/` : `registry, sanitizer`
  - `verifier/` : `claim_segmenter, backends, grounding_verifier, thresholds, failure, answer_checks`
  - `observability/` : `metrics, tracer, pii`
  - `agent/` : `budgets, cancellation, redlock, tenant_guard, two_phase_publish`
- **JETER** : `runtime_v2/` (après découplage, cf note), `runtime_v3/` (sauf `nli_judge`),
  router `runtime_v4.py`, `runtime_v4_poc/`, `runtime_v4_2/`, `facts_first/` (20 fichiers ;
  consommé uniquement par v4* + verifier v5), et l'**orchestration agentique de v5**
  (`reasoning_agent*.py`, `agent/execution_plan.py`, `loop_signature.py`, `query_reformulator.py`,
  `doc_topics_loader.py`, `*_llm_caller.py`, `reading_tools*.py`).
- **Découplage requis avant suppression de `runtime_v2`** : encore importé par
  `anchor/anchor_extractor.py`, `atlas/generator.py`, `api/services/query_decomposer.py`.

### 5.4 Recherche & retrieval (GARDER)
`/search` est **totalement indépendant** des `runtime_v*` (confirmé).
- **GARDER** : `api/routers/search.py`, `api/services/search.py`, `synthesis.py`, `retriever.py`,
  `signal_policy.py`, `query_decomposer.py` (après découplage runtime_v2), `perspectives/`.
- **GARDER** : `retrieval/` (`qdrant_layer_r.py`, `rechunker.py`).
- **Mort/désactivé** : `graph_first_search.py`, `graph_guided_search.py` (présents mais OFF) —
  jeter sauf si réactivation prévue ; dans ce cas ils retiennent `semantic/inference`.

### 5.5 Knowledge Graph (GARDER → `kg/`)
`relations/` (56 fichiers, très référencé), `ontology/` (16), `hygiene/` (14, router monté),
`entity_resolution/` (13, router monté), `neo4j_custom/` (5). Regrouper sous `kg/` (optionnel).

### 5.6 Features secondaires actives (GARDER)
`memory/` (sessions), `navigation/`, `wiki/` (router monté), `atlas/` (router monté),
`verification/` (router `/verify` monté), `inference/` (ex-semantic/inference → router `insights`),
`domain_packs/` (router + reprocess) — mécanisme d'ajout de packs domain-centric, **conservé tel
quel** (nom porteur, concept central de l'agnosticité multi-domaines AX-11).

### 5.7 Socle transverse (GARDER)
`common/**` (+ absorbe `semantic/utils` → `common/nlp/`), `config/**`, `logging/`.

### 5.8 À SUPPRIMER (mort confirmé)
- **Zéro référence entrante, non montés** : `facets/`, `audit/`, `lifecycle/`, `rules/`, `ui/`,
  `current/` (~27 fichiers).
- **Pivot d'extraction abandonné** : `stratified/` (57, sauf utilitaires §5.1), `structural/`
  (sauf `models.py`), `agents/` (20, `__init__` DEPRECATED, appelé seulement par chemin skippé),
  `semantic/` (sauf `inference/` et `utils/` → relocalisés ; `__init__` du package DEPRECATED).
- **Lignée runtime abandonnée** : cf §5.3 (`runtime_v2`, v3 sauf nli, v4*, v5 orchestration,
  `facts_first`).
- **Incertains à trancher** (refs faibles/indirectes) : `consolidation/`, `linguistic/`
  (`coref_engine` DEPRECATED, garder FastCoref si utilisé), `anchor/`, `perspectives/`
  (vérifier usage par synthèse).

### 5.9 Frontend (GARDER, nettoyage mineur)
Qualité ~7/10, socle propre (`lib/` axios typé). Nettoyage :
- Supprimer : `app/rfp-excel/page-original.tsx` (doublon), `components/common/LanguageSelector.tsx`
  et `components/layout/ContextualSidebar.tsx` (orphelins).
- Pages hors-nav à décider : `/documents/upload`, `/documents/rfp` (doublons import/rfp-excel),
  `/wiki` (legacy → garder `/wiki/articles` + `/atlas`).
- Réactiver dans `next.config.js` : retirer `ignoreBuildErrors:true` + `ignoreDuringBuilds:true`
  (dette TS/ESLint cachée). Repasser `tsconfig` target `es5` → `es2020+`.
- API helper `documentTypes` marqué DEPRECATED dans `lib/api.ts` → retirer.

#### 5.9.1 Ménage de la navigation admin (`app/admin/layout.tsx`)
La nav admin (sections Infrastructure / Import / Knowledge Graph / Analyse / Atlas) mélange du
produit et des dashboards R&D, et contient des entrées mortes.

**Supprimer (mort / 404) :**
- `Runtime V2 (chat)` → `/chat/runtime-v2` : suit le runtime_v2 backend jeté (cf §5.3). Retirer
  l'item nav + `app/chat/runtime-v2/` + `app/api/runtime_v2/*` + `components/runtime/`.
- `Runtime Calibration` → `/admin/runtime-calibration` (`layout.tsx:101`) : **lien mort, la page
  n'existe pas (404)**. Retirer l'item.
- `/admin/living-ontology` (page hors-nav, liée depuis le dashboard) : backend `living_ontology`
  **désactivé** dans `api/main.py`. Retirer la page + la carte du dashboard.
- `/admin/markers` (page hors-nav orpheline) : à retirer sauf usage réel de la feature markers.

**Renommer (suffixe de version) :**
- `Relations V3.3` → **`Relations`** (route `/admin/relations` inchangée).

**Déporter hors de l'admin produit (vers `osmosis-cockpit` / `osmosis-bench`, cf §2) :**
La sous-section *Analyse* empile des surfaces d'**observabilité/R&D** qui correspondent à la mission
du cockpit (« métriques et feedback sur l'état du système ») et du harnais bench :
- `Benchmarks` (`/admin/benchmarks`, 1335 l.) → `osmosis-bench`.
- `Golden Set (annotation)` (`/admin/relations/golden-set`) → outil d'annotation/éval → `osmosis-bench`.
- `Audit Corpus` (`/admin/corpus-audit`) → diagnostic → `osmosis-cockpit`.
- `Corpus Intelligence` (`/admin/corpus-intelligence`) → dashboard → cockpit (ou garder si jugé produit).

**Garder dans l'admin produit osmosis :** GPU & Compute, Backup & Restore, Configuration
(découper, 1315 l.), Apparence ; Claim-First Pipeline, Mode Burst ; Domain Context (découper,
2309 l.), Post-Import, KG Hygiene, Domain Packs ; Contradictions, Relations ; Générateur Atlas.

**Cible :** une nav admin resserrée sur l'exploitation quotidienne ; l'observabilité et la R&D
vivent dans des surfaces indépendantes.

### 5.10 Infra & config (GARDER l'actif, élaguer les doublons)
- **GARDER** : `docker-compose.infra.yml` (Qdrant v1.15.1, Redis 7.2, Neo4j 5.26, Postgres/pgvector)
  + `docker-compose.yml` + `docker-compose.monitoring.yml` ; `frontend/Dockerfile` (multi-stage,
  modèle à suivre) ; `config/**` (YAML métier, conserver tel quel) ; `migrations/*.cypher` ;
  `schemas/` ; module `burst/` + `cloudformation/burst-spot*.yaml` (GPU Spot à la demande).
- **JETER/ÉLAGUER** : `docker-compose.app.yml` (doublon désynchronisé), `.build.yml`,
  `.ecr.yml` (sauf déploiement ECR), `cloudformation/knowbase-stack.yaml` (EC2 monolithe
  redondant avec le burst — garder un seul chemin).
- **À refondre** : `app/Dockerfile` en **multi-stage**, sortir torch/spacy/docling/fasttext de la
  base, retirer `pytest`/`respx` du runtime, LibreOffice/Java seulement si conversion Office utile.

### 5.11 Doc, scripts, tests
- **Doc — GARDER** : `doc/README.md`, `VISION.md`, `EXECUTION_ROADMAP.md`, `ARCH_PIPELINE.md`,
  `ARCH_CLAIMFIRST.md`(→`ARCH_CLAIMS.md`), `ARCH_RETRIEVAL.md`, `ARCH_STOCKAGE.md`, `OPS.md`,
  `DEV_GUIDE.md`, `ongoing/adr/` (ADR structurants), `ongoing/etudes/`. Mettre à jour les
  références de nommage (knowbase→osmosis, claimfirst→claims, extraction_v2→extraction).
- **Doc — NE PAS reprendre** : `doc/archive/` (443), `ongoing/chantiers/` + `ongoing/sessions/`
  (journaux datés → archive hors dépôt).
- **Scripts — GARDER (~40)** : `setup_*`, `migrate_*`/`migration_*`, `reset_*`,
  `import_document.py`/`export_document.py`, `clean_all_databases.*`,
  `full_reset_preserve_cache.*`, `backfill_*`, `check_qdrant.py`, `aws/`, `golden-ami/`, `router/`.
- **Scripts — JETER (~160)** : `audit_*`, `diag_*`/`diagnostic_*`, `analyze_*`, `bench_*`,
  doublons `test-burst-v2..v4.ps1`, `dump_*`, `inspect_*`, `night_orchestrator`, etc.
- **Tests — GARDER, élaguer** : alignés ~90 % avec le code actif (claims 53, runtime 27,
  common 21, api 17, relations 17). Retirer les tests de code jeté : `runtime_v2/`, `runtime_v6/`
  (1), `mvp_v1/`, `phase_1_8/`, `eval_deepseek/`, `stratified/` (sauf utilitaires gardés).
- **Fichiers racine — JETER** : `AUDIT_README_RAPPORT.md`, `TASK_COMPLETE.md`,
  `routing_fails_audit.txt`, `analyze_cache.py`. **GARDER** : `enterprise_sap.osmpack` (artefact
  domain pack), `dc.ps1`, `kw.ps1` (adapter), `migrations/`, `schemas/`.

---

## 6. Procédure de migration suggérée

1. **Geler** une révision de référence de KBGPT (tag), pour traçabilité.
2. **Créer** les dépôts `osmosis`, `osmosis-cockpit`, `osmosis-bench` (vides).
3. **Script d'import sélectif** (rsync/copie) matérialisant l'arbo §4 : ne copier QUE les chemins
   GARDER. Le mort n'est jamais copié.
4. **Renommer** le package : `git mv`/déplacement + remplacement global `knowbase→osmosis` et la
   table §3.2. Outil : recherche-remplacement contrôlée sur les imports.
5. **Consolider `runtime/`** : fusionner a3 + infra v5 portée + `nli_judge` ; recâbler le router.
6. **Dissoudre `semantic/`** : relocaliser `inference/` et `utils`→`common/nlp/`, supprimer le reste.
7. **Découpler `runtime_v2`** de `anchor`/`atlas`/`query_decomposer` avant de ne pas l'importer.
8. **Recâbler `api/main.py`** : ne monter que les routers vivants (retirer `runtime_v2..v5`,
   `stratified` déjà commenté, `living_ontology`).
9. **Réécrire** `README.md` + `CLAUDE.md` (naming osmosis, structure réelle, règles à jour).
10. **Vérifier** : `mypy`/`ruff`/`pytest` verts ; build images ; `docker compose up` ; un import
    document de bout en bout (ingestion → claims → KG) ; une requête `/search` ; une requête
    `runtime`.
11. **Initialiser** l'historique git sur un commit propre (« import osmosis depuis cœur actif KBGPT »).

---

## 7. Points de vigilance / sécurité

- 🔴 **`ngrok.yml` contient un authtoken en clair** — révoquer et exclure du nouveau dépôt.
- 🟠 `buildspec.yml` expose l'AWS Account ID — paramétrer via variable.
- 🟠 `next.config.js` : TS/ESLint désactivés au build → réactiver (cf §5.9).
- 🟠 `app/Dockerfile` mono-stage avec ML lourd + outils de test en prod → refondre (cf §5.10).
- 🟠 `CLAUDE.md` actuel **obsolète** (structure doc à 4 fichiers, naming « KnowWhere ») alors que
  la doc réelle est refondée → réécrire pour osmosis.
- ⚠️ **Cache précieux** : la règle « ne jamais supprimer `data/extraction_cache/` » reste valable ;
  le gestionnaire est `extraction/cache/versioned_cache.py` (format v5), pas l'ancien
  `.knowcache.json`.

---

## 8. Décisions ouvertes à trancher

| # | Décision | Recommandation |
|---|---|---|
| D1 | Renommer `claimfirst` → `claims` (et `ARCH_CLAIMFIRST.md`) ? | Oui (cohérent avec « Claim » de VISION) — mais vérifier l'impact sur les ADR qui citent ClaimFirst |
| D2 | Regroupement `kg/` (relations+ontology+hygiene+entity_resolution+neo4j) ? | Optionnel ; faisable en 2e passe pour limiter les déplacements initiaux |
| D3 | Sort de `claims/procedures/` (ex-claimfirst/v6 + module runtime_v6), feature gated OFF | Garder le code (renommé) mais hors chemin par défaut ; ou différer l'import tant que non activé |
| D4 | `benchmark/` : dépôt séparé `osmosis-bench` ou sous-dossier `tests/eval/` d'osmosis ? | Dépôt séparé (29 Mo, R&D) |
| D5 | Zones incertaines `consolidation/`, `linguistic/`, `anchor/`, `perspectives/` | Trancher par un dernier audit d'usage UI/synthèse avant import |
| D6 | Sort de `graph_first_search`/`graph_guided_search` (OFF) et `living_ontology` | Si abandon définitif, jeter — et `inference/` ne reste justifié que par `insights` |

---

*Document de travail — à confronter à `VISION.md` et `EXECUTION_ROADMAP.md` avant exécution.*
