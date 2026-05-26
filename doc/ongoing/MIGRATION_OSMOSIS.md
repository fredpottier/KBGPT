# Migration vers OSMOSIS — Plan de reconstruction propre

> **Statut :** Proposition de travail (à valider) — document de migration.
> **Objet :** Spécifier quel code reprendre, renommer ou abandonner pour créer un dépôt `osmosis`
> sain, débarrassé du legacy, avec une **arborescence repensée** lisible.
> **Méthode :** audit du graphe d'imports depuis les points d'entrée réels (worker d'ingestion,
> API `/search`, routers montés), réalisé sur l'état courant du code (869 fichiers `.py` dans
> `src/knowbase`).
> **Cadre :** analyse organisée autour des **6 blocs fonctionnels** du système.

---

## 0. Constat

Le système se décompose en 6 blocs : **(1) ingestion de documents**, **(2) post-processing
KG**, **(3) runtime de questionnement**, **(4) frontend + admin**, **(5) cockpit déporté**,
**(6) orchestration AWS**. La vision et la doc d'architecture sont saines et récentes ; le
**code** porte 9 mois de pivots non nettoyés (7 lignées de runtime, 5 approches d'extraction,
pipelines pass2/3/4 manuels, modules orphelins).

Le problème n'est pas l'architecture mais la **cohabitation code mort / code vivant sans
séparation**, d'où les « mauvais branchements » vers du legacy. On repart d'un dépôt neuf
`osmosis` (pas un fork git), avec import sélectif du cœur vivant, nommage propre et arborescence
réorganisée par bloc.

Ordre de grandeur : `src/knowbase` **869 → ~430 fichiers `.py`** ; suppression de ~440 markdown
d'archive et ~160 scripts jetables ; sortie de 2 sous-projets en dépôts indépendants.

---

## 1. BLOC 1 — Pipeline d'ingestion de documents

### Flux réel (confirmé)
```
folder_watcher / dispatcher
  → RQ jobs_v2.ingest_document_v2_job
      ├─ extraction_v2 (Docling + Vision) ──> cache data/extraction_cache (versioned_cache.py, v5)
      ├─ [Stratified V2 / osmose_agentique : SKIPPÉ par défaut — INGESTION_SKIP_STRATIFIED_V2=true]
      ├─ auto_deduplicate_entities (dédup Cypher par nom)
      ├─ move docs_in → docs_done
      └─ enqueue ClaimFirst (queue "reprocess")
          → claimfirst.orchestrator.process_and_persist  (extraction claims + qualité)
```

### GARDER
| Module actuel | Rôle |
|---|---|
| `ingestion/queue/` (`worker.py`, `dispatcher.py`, `jobs_v2.py`, `connection.py`, `__main__.py`) | Worker RQ (écoute `default`+`reprocess`+`benchmark`) + enqueue |
| `ingestion/folder_watcher.py` | Surveillance dossier d'entrée |
| `ingestion/resilience/` | Recovery / checkpoints |
| `extraction_v2/` (52 fichiers) | Parsing documents : Docling + Vision + gating + merge |
| `extraction_v2/cache/versioned_cache.py` | **Gestionnaire du cache précieux** (format v5) |
| `claimfirst/` (105 fichiers) | Extraction de claims atomiques + pipelines qualité (cœur) |
| `stratified/pass0/{cache_loader,adapter}.py`, `pass1/assertion_unit_indexer.py`, `stratified/models/`, `structural/models.py` | Utilitaires relus par ClaimFirst (cache → DocItems) |

### JETER
`ingestion/osmose_agentique.py`, `ingestion/osmose_*`, `pass2_orchestrator.py`,
`ingestion/processors/` (vide), `ingestion/extraction_cache.py` (ancien `.knowcache.json`, remplacé
par `versioned_cache.py` ; vérifier d'abord les call-sites admin/backup/purge).

### Décision
`claimfirst/v6/` (extraction de procédures, derrière flag `V6_PROCEDURE_EXTRACTION` **off**) +
module `runtime_v6/` (schémas Procedure/Reference, **pas** un runtime Q/A) → à reclasser ensemble
en feature d'extraction optionnelle (cf §10 D3).

---

## 2. BLOC 2 — Post-processing après ingestion

**Découverte clé :** le vrai post-processing KG n'est **pas** dans les fichiers `pass*_jobs.py`
(qui sont **manuels** via l'admin, et legacy). Il est **inline dans `claimfirst/worker_job.py`** :
```
après extraction des claims (≥1-2 docs + Neo4j) :
  ├─ détection chaînes cross-doc   (claimfirst/composition/chain_detector)
  ├─ canonicalisation entités       (claimfirst/extractors/merge_arbiter)
  ├─ clustering cross-doc           (union-find inline)
  ├─ comparaison signatures Q       (claimfirst/comparisons/qs_comparator)
  └─ KG Hygiene L1                  (hygiene/engine.HygieneEngine, scope DOCUMENT_SET)
```
La déduplication d'entités est faite par `api/services/knowledge_graph_service.py`
(`deduplicate_entities_by_name`, Cypher), **pas** par le module `entity_resolution/`.

### GARDER
- `hygiene/` (14) — appelé par le worker ClaimFirst (Phase 13) → cœur du post-processing live.
- `ontology/` (16) — domain-context injector/store + extractors ClaimFirst.
- La logique de post-processing inline → **à extraire** du worker dans un module dédié
  `enrichment/` (cf arborescence §8).
- La dédup Cypher (`knowledge_graph_service`) → conserver (rattacher au domaine KG).

### JETER (pipeline pass2/3/4 manuel + modules legacy)
- `ingestion/queue/pass2_jobs.py`, `pass3_jobs.py`, `pass4_jobs.py` — déclenchés manuellement
  depuis `api/routers/admin.py`, non chaînés en prod.
- `ingestion/queue/pass35_jobs.py` — **aucun caller** (mort).
- `ingestion/queue/reprocess_job.py` — reprocess du pipeline Stratified V2 (désactivé).
- `consolidation/` (12) — lié au pass2 manuel.
- `entity_resolution/` (13) — atteint seulement via `consolidation` (pass4 manuel) + chemin osmose
  legacy ; la dédup live ne passe pas par lui.
- `facets/` (11), `lifecycle/` (5), `audit/` (3) — **0 importeur** (orphelins totaux).

### PARTIEL
- `relations/` (56) — **pas** dans la chaîne d'ingestion. Les *writers* sont le pass2 manuel
  (à jeter). Un sous-ensemble *lecture* sert la recherche graphe (`graph_first_search`,
  `tier_filter`, router `claims`). → Garder uniquement le sous-ensemble lecture, à préciser au
  moment du retrait (cf §10 D5). NB : `graph_first_search` est actuellement désactivé.

---

## 3. BLOC 3 — Runtime de questionnement

Il existe **8 variantes de runtime** + un endpoint `/search` indépendant. `runtime_a3` est la
lignée vivante (la plus récente) et est quasi autonome (ne dépend que de `common/`).

### Consolider en un seul `runtime/`
| Source | Action |
|---|---|
| `runtime_a3/` (14) | **Cœur** → `runtime/answering/` (orchestrator, parse, plan, execute, evaluate, synthesize, resolvers, reranker, grounding) |
| router `api/routers/runtime_v6.py` | **Façade** → `api/routers/runtime.py` (instancie a3) |
| `runtime_v3/nli_judge.py` | **Porter** (seul fichier requis par a3 + verifier) |
| Infra de `runtime_v5/` : `api/` (admission, idempotency, job_store, sse), `tools/` (registry, sanitizer), `verifier/` (claim_segmenter, backends, grounding_verifier, thresholds, failure, answer_checks), `observability/` (metrics, tracer, pii), `agent/{budgets,cancellation,redlock,tenant_guard,two_phase_publish}` | **Porter** (réutilisable, sinon perte sèche — personne d'autre ne l'importe) |
| `/search` : `api/routers/search.py`, `api/services/search.py`, `synthesis.py`, `retriever.py`, `signal_policy.py`, `query_decomposer.py` | **GARDER** → `runtime/search/` ; **indépendant** des runtime_v* |
| `retrieval/` (Layer R, rechunker) | **GARDER** → `runtime/retrieval/` |
| `anchor/` (4), `perspectives/` (9) | **GARDER** (utilisés côté search) |
| `semantic/inference/` | **GARDER** → `inference/` (router `insights`) |

### JETER
`runtime_v2/` (après découplage : encore importé par `anchor/anchor_extractor`, `atlas/generator`,
`api/services/query_decomposer`), `runtime_v3/` (sauf `nli_judge`), router `runtime_v4.py`,
`runtime_v4_poc/`, `runtime_v4_2/`, `facts_first/` (20, consommé uniquement par v4* + verifier v5),
et l'**orchestration agentique de v5** (`reasoning_agent*.py`, `agent/{execution_plan,loop_signature}`,
`query_reformulator.py`, `doc_topics_loader.py`, `*_llm_caller.py`, `reading_tools*.py`).

### Dissoudre `semantic/`
Le package `semantic/` (31) a son `__init__` **DEPRECATED**. Seuls deux îlots vivants :
`semantic/inference/` → `inference/` ; `semantic/utils/` (détection langue, embeddings) →
`platform/common/nlp/`. Tout le reste sert le chemin `osmose_agentique` mort → JETER.

---

## 4. BLOC 4 — Frontend + admin

Qualité ~7/10, socle propre (`lib/` axios typé). **GARDER** le frontend, nettoyage ciblé.

### Nettoyage général
- Supprimer : `app/rfp-excel/page-original.tsx` (doublon), `components/common/LanguageSelector.tsx`,
  `components/layout/ContextualSidebar.tsx` (orphelins).
- `next.config.js` : retirer `ignoreBuildErrors:true` + `ignoreDuringBuilds:true` (dette TS/ESLint
  cachée) ; `tsconfig` target `es5` → `es2020+`.
- API helper `documentTypes` (DEPRECATED dans `lib/api.ts`) → retirer.
- Pages hors-nav à décider : `/documents/upload`, `/documents/rfp` (doublons), `/wiki` (legacy →
  garder `/wiki/articles` + `/atlas`).

### Ménage de la nav admin (`app/admin/layout.tsx`)
**Supprimer (mort / 404) :**
- `Runtime V2 (chat)` → `/chat/runtime-v2` (+ `app/api/runtime_v2/*` + `components/runtime/`) :
  suit le runtime_v2 backend jeté.
- `Runtime Calibration` → `/admin/runtime-calibration` : **lien mort, page inexistante (404)**.
- `/admin/living-ontology` : backend `living_ontology` **désactivé** dans `api/main.py`.
- `/admin/markers` (hors-nav) : sauf usage réel de la feature.

**Renommer :** `Relations V3.3` → **`Relations`**.

**Déporter vers les dépôts indépendants (cf §6) :** la sous-section *Analyse* mélange produit et
observabilité/R&D :
- `Benchmarks` (`/admin/benchmarks`), `Golden Set` (`/admin/relations/golden-set`) → `osmosis-bench`.
- `Audit Corpus` (`/admin/corpus-audit`), `Corpus Intelligence` (`/admin/corpus-intelligence`) →
  `osmosis-cockpit` (ou garder Corpus Intelligence si jugé produit).

**Garder (admin produit) :** GPU & Compute, Backup & Restore, Configuration (découper, 1315 l.),
Apparence ; Claim-First Pipeline, Mode Burst ; Domain Context (découper, 2309 l.), Post-Import,
KG Hygiene, Domain Packs ; Contradictions, Relations ; Générateur Atlas.

---

## 5. BLOC 5 — Cockpit (déporté)

`cockpit/` (service FastAPI autonome : WebSocket + UI statique + collectors docker/burst/
llm_budget/ragas/pipeline) → **dépôt indépendant `osmosis-cockpit`**. C'est un système de
supervision qui se *branche* sur une instance osmosis pour remonter métriques/feedback ; il ne
doit pas être livré en prod sur chaque déploiement. Définir un **contrat d'interface stable**
(endpoints métriques + format logs) plutôt qu'un import de code partagé.

---

## 6. BLOC 6 — Orchestration AWS

Deux mécanismes distincts à ne pas confondre :

### (a) Burst GPU éphémère — VIVANT, cœur métier (GARDER)
Loue une instance **Spot GPU** à la demande pour absorber l'extraction LLM/embeddings lourde,
piloté depuis l'UI admin (`api/routers/burst.py` → `BurstOrchestrator`).
Flux : `create_stack(knowwhere-burst-{batch})` sur AMI Golden (vLLM + TEI via UserData) → bascule
des providers LLM/embeddings (`provider_switch`, état en Redis `osmose:burst:*` + fichier partagé) →
résilience Spot (`resilient_client`, `aws_truth_service` détecte le changement d'IP, `resync_subscriber`
réactive) → teardown (`TargetCapacity=0` par défaut, ou `delete_stack`).
Deux templates : `burst-spot.yaml` (Profil A : Qwen2.5-**14B**-AWQ + TEI sur L4/A10G 24 Go) ;
`burst-spot-72b.yaml` (Profil B : **72B**-AWQ seul sur L40S 48 Go, embeddings sur GPU worker).

**GARDER :** `ingestion/burst/` (orchestrator, provider_switch, resilient_client, aws_truth_service,
resync_subscriber, types), `ingestion/burst/cloudformation/burst-spot{,-72b}.yaml`,
`scripts/golden-ami/install-burst.sh`, `api/routers/burst.py`.
**INCERTAIN :** `ingestion/burst/artifact_{exporter,importer}.py` (mode hybride S3 — vérifier usage).

### (b) Déploiement EC2 monolithe — LEGACY/redondant (JETER ou isoler)
`cloudformation/knowbase-stack.yaml` (instance unique toute la stack Docker depuis ECR +
auto-destruction Lambda) + `scripts/aws/deploy-*`. Redondant avec le burst → garder un seul chemin.
- **JETER** : `scripts/aws/deploy-ec2.ps1` (SSH manuel, doublon), `repair-deployment.ps1`,
  `convert-utf8-bom.ps1` (hors sujet).
- **INCERTAIN** (si on garde un déploiement EC2) : `knowbase-stack.yaml`, `deploy-cloudformation.ps1`,
  `destroy-cloudformation.ps1`, `deploy-on-ec2.sh`, `aws-{start,stop,terminate}-instance.ps1`.

### CI/CD images (GARDER, renommer)
`buildspec.yml` (CodeBuild → ECR) + `docker-compose.ecr.yml` + `scripts/aws/build-and-push-ecr.ps1`
+ `setup-iam-permissions.ps1`. Incohérence à corriger : `build-and-push-ecr.ps1` gère loki/promtail/
grafana mais pas `buildspec.yml` (désync CI).

### Doublons à résoudre
- **Backup/restore** : deux paires (`backup-to-s3`/`restore-from-s3` vs `backup-knowbase`/
  `restore-knowbase`) → en garder **une**.
- README `scripts/aws/README.md` référence `delete-stack.ps1` (inexistant) → corriger.

### Renommage AWS (knowbase/SAP en dur)
ECR repos `sap-kb-{app,worker,frontend,ui,...}` → `osmosis-*` (buildspec, build-and-push-ecr,
docker-compose.ecr) ; IAM `sap-kb-codebuild-user` ; buckets `knowbase-backups-*`,
`knowbase-cloudformation-templates-temp` ; containers/volumes/réseau `knowbase-*` ; chemins
`/home/ubuntu/knowbase`, `C:\Project\SAP_KB`. **Externaliser** `AWS_ACCOUNT_ID=715927975014` et
`eu-west-1` (hardcodés partout). Le code burst utilise déjà des préfixes propres (`osmose:`,
`knowwhere-burst-`) — à aligner sur `osmosis`.

---

## 7. Socle transverse (toutes briques)

- `common/` (30) → éclater : `platform/storage/` (clients Qdrant/Neo4j/Redis/Postgres),
  `platform/llm/` (llm_router, embeddings, providers), `platform/common/` (utils, nlp ex-semantic/utils).
- `config/` (7) + `config/**.yaml` (métier) → `config/` (conserver tel quel).
- `db/` (5, SQLAlchemy app : users/auth) → `platform/db/`.
- `logging/` (2) → `platform/logging/`.

---

## 8. Arborescence repensée (proposition)

Réorganisation **par bloc fonctionnel** plutôt que par pile horizontale. L'`api/` redevient une
couche HTTP fine ; la logique métier vit dans les packages de bloc.

```
osmosis/
├── src/osmosis/
│   ├── kg/                       # Modèle Knowledge Graph (domaine partagé écrit par l'ingestion, lu par le runtime)
│   │   ├── schema/               # Document/Claim, bitemporel, persistence Neo4j
│   │   ├── ontology/             # ex-ontology (catalogues entités/types)
│   │   ├── hygiene/              # ex-hygiene (règles qualité KG)
│   │   ├── relations/            # ex-relations — SOUS-ENSEMBLE lecture (cf §10 D5)
│   │   └── dedup.py              # ex-knowledge_graph_service.deduplicate_*
│   │
│   ├── ingestion/                # BLOC 1+2 — faire entrer les docs dans le KG
│   │   ├── extraction/           # ex-extraction_v2 : parse (Docling+Vision) + cache versionné
│   │   ├── claims/               # ex-claimfirst : extraction de claims atomiques
│   │   │   └── procedures/       # ex-claimfirst/v6 + ex-module runtime_v6 (gated, cf D3)
│   │   ├── enrichment/           # BLOC 2 : post-processing extrait du worker (cross_doc, canonicalization, clustering, comparison, hygiene_l1)
│   │   ├── domain_packs/         # packs domain-centric (NER sidecar à l'ingestion)
│   │   ├── burst/                # BLOC 6 (applicatif) : burst GPU + cloudformation/burst-spot*.yaml
│   │   ├── queue/                # worker RQ, dispatcher, jobs
│   │   └── watcher.py            # ex-folder_watcher
│   │
│   ├── runtime/                  # BLOC 3 — questionner le système
│   │   ├── answering/            # ex-runtime_a3 (Parse→Plan→Execute→Evaluate→Synthesize)
│   │   ├── search/               # ex-/search (api/services/search, synthesis, retriever, signal_policy, query_decomposer, perspectives, anchor)
│   │   ├── retrieval/            # ex-retrieval (Layer R, rechunker)
│   │   ├── verifier/             # porté de runtime_v5
│   │   ├── tools/                # porté de runtime_v5 (ToolRegistry)
│   │   ├── observability/        # porté de runtime_v5 (OTel, metrics, pii)
│   │   └── jobs.py               # porté de runtime_v5 (admission, idempotency, job_store, sse)
│   │
│   ├── inference/                # ex-semantic/inference (router insights)
│   ├── features/                 # surfaces secondaires : wiki, atlas, navigation, memory, verification
│   │
│   ├── platform/                 # socle technique
│   │   ├── storage/              # clients Qdrant/Neo4j/Redis/Postgres (ex-common/clients)
│   │   ├── llm/                  # llm_router, embeddings, providers (ex-common)
│   │   ├── common/               # utils + nlp (ex-common/utils + ex-semantic/utils)
│   │   ├── db/                   # SQLAlchemy app (users/auth)
│   │   └── logging/
│   │
│   ├── api/                      # couche HTTP fine : routers regroupés par bloc (ingestion/, runtime/, kg/, admin/, features/)
│   └── config/
│
├── frontend/                     # repris ~tel quel (nettoyage §4)
├── config/                       # YAML métier (llm_models, prompts, domains…)
├── doc/                          # VISION + ROADMAP + ARCH_* + OPS + DEV_GUIDE + ongoing/adr
├── tests/                        # tests alignés au code repris
├── migrations/                   # *.cypher versionnés
├── schemas/
├── deploy/                       # BLOC 6 (infra) — IaC & scripts dédoublonnés
│   ├── ci/                       # buildspec.yml + docker-compose.ecr.yml (source unique repos ECR)
│   ├── golden-ami/               # install-burst.sh
│   ├── scripts/                  # backup-s3/restore-s3, setup-iam (1 seule paire backup)
│   ├── compose/                  # docker-compose.{infra,app,monitoring}.yml
│   └── ec2-monolith/             # OPTIONNEL (mécanisme b) : osmosis-stack.yaml + deploy/destroy — sinon supprimer
└── README.md  CLAUDE.md          # réécrits (naming osmosis, structure réelle)
```

Dépôts séparés : **`osmosis-cockpit`** (supervision), **`osmosis-bench`** (harnais d'éval +
`benchmark/` code + gold sets + `scripts/router/` entraînement DeBERTa).

> Le regroupement `kg/` et l'éclatement de `common/` en `platform/` sont les déplacements les
> plus structurants : ils peuvent être faits en 2e passe si l'on veut un premier import rapide.

---

## 9. Convention de nommage

1. Package racine `knowbase` → **`osmosis`** (tous les `from knowbase.…` → `from osmosis.…`).
2. **Aucun suffixe de version / nom de pivot** : `extraction_v2`→`extraction`,
   `claimfirst`→`claims`, `runtime_a3`/`runtime_v*`→`runtime`, `semantic`→dissous,
   `stratified`/`facts_first`→non migrés.
3. Naming AWS/CI : `sap-kb-*`, `knowbase-*` → `osmosis-*` (cf §6).
4. `domain_packs` **conservé tel quel** (nom porteur : packs domain-centric pluggables, concept
   central de l'agnosticité multi-domaines AX-11).
5. Bannir des logs/code/doc : « KnowBase », « KnowWhere », « SAP KB ». Doc : renommer
   `ARCH_CLAIMFIRST.md` → `ARCH_CLAIMS.md`.

---

## 10. Synthèse legacy à NE PAS migrer

- **Orphelins (0 référence)** : `facets/`, `audit/`, `lifecycle/`, `rules/`, `ui/`, `current/`.
- **Pivot extraction abandonné** : `stratified/` (sauf utilitaires §1), `structural/` (sauf
  `models.py`), `agents/` (`__init__` DEPRECATED), `semantic/` (sauf `inference/`+`utils/`),
  `osmose_agentique`/`osmose_*`.
- **Lignée runtime abandonnée** : `runtime_v2`, `runtime_v3` (sauf `nli_judge`), `runtime_v4*`,
  orchestration `runtime_v5`, `facts_first`.
- **Pipeline post-processing manuel** : `pass2/3/35/4_jobs.py`, `reprocess_job.py`,
  `consolidation/`, `entity_resolution/`.
- **AWS legacy** : EC2 monolithe (cf §6b), scripts dédoublonnés.
- **Doc/scripts** : `doc/archive/` (443), `ongoing/{chantiers,sessions}/`, ~160 scripts jetables
  (`audit_*`, `diag_*`, `analyze_*`, `bench_*`), fichiers racine `AUDIT_README_RAPPORT.md`,
  `TASK_COMPLETE.md`, `routing_fails_audit.txt`, `analyze_cache.py`.

### Décisions ouvertes
| # | Décision | Recommandation |
|---|---|---|
| D1 | `claimfirst` → `claims` (+ `ARCH_CLAIMS.md`) ? | Oui (aligné « Claim » de VISION) |
| D2 | Regroupement `kg/` + `platform/` dès le 1er import ? | Optionnel ; faisable en 2e passe |
| D3 | Sort de `claims/procedures/` (gated OFF) | Garder le code renommé, hors chemin par défaut |
| D4 | EC2 monolithe (mécanisme b) : garder ou supprimer ? | Supprimer si burst + futur déploiement managé suffisent |
| D5 | `relations/` : préciser le sous-ensemble lecture à garder | Auditer `graph_first_search`/`tier_filter`/router `claims` au retrait |
| D6 | `graph_first_search`/`graph_guided_search` (désactivés) + `living_ontology` | Si abandon, jeter ; sinon `inference/` justifié seulement par `insights` |

---

## 11. Procédure de migration

1. **Geler** un tag de référence sur KBGPT (traçabilité).
2. **Créer** les dépôts `osmosis`, `osmosis-cockpit`, `osmosis-bench`.
3. **Import sélectif** (script de copie) matérialisant l'arbo §8 : ne copier QUE le vivant.
4. **Renommer** package + modules (§9) par recherche-remplacement contrôlée des imports.
5. **Consolider `runtime/`** (a3 + infra v5 portée + nli_judge) ; recâbler le router.
6. **Extraire `enrichment/`** depuis `claimfirst/worker_job.py` (post-processing inline).
7. **Dissoudre `semantic/`** ; découpler `runtime_v2` d'`anchor`/`atlas`/`query_decomposer`.
8. **Recâbler `api/main.py`** : ne monter que les routers vivants.
9. **Réécrire** `README.md` + `CLAUDE.md` (naming + structure réelle).
10. **Vérifier** : `mypy`/`ruff`/`pytest` verts ; build images ; `docker compose up` ; import doc
    de bout en bout (extraction → claims → enrichment → KG) ; requête `/search` ; requête `runtime`.
11. **Initialiser** l'historique git sur un commit propre.

---

## 12. Points de vigilance / sécurité

- 🔴 `ngrok.yml` : **authtoken en clair** — révoquer, exclure du dépôt.
- 🟠 `buildspec.yml` : AWS Account ID en clair → variable.
- 🟠 `next.config.js` : TS/ESLint désactivés au build → réactiver.
- 🟠 `app/Dockerfile` mono-stage avec ML lourd (torch/spacy/docling/fasttext) + `pytest`/`respx`
  en prod → refondre en multi-stage.
- 🟠 `CLAUDE.md` actuel **obsolète** (structure doc, naming « KnowWhere ») → réécrire.
- ⚠️ **Cache précieux** : règle « ne jamais supprimer `data/extraction_cache/` » maintenue ;
  gestionnaire = `extraction/cache/versioned_cache.py` (v5).

---

*Document de travail — à confronter à `VISION.md` et `EXECUTION_ROADMAP.md` avant exécution.*
