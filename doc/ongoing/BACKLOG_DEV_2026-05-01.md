# Backlog développement OSMOSIS — État au 2026-05-01

> **Source** : audit complet des mémoires Claude (`~/.claude/projects/.../memory/`), `doc/ongoing/`, plan V3.3 contradiction detection, TODOs du code, branche `feat/contradiction-detection`.
> **Périmètre** : uniquement développement. Les chantiers test/validation/bench/audit qualité sont gérés séparément.
> **Total** : ~55 chantiers de développement identifiés.

---

## 🔥 Priorité haute

- ✅ **Sécurisation Redis post-incident** — Livré 2026-05-01 (commit 863c988) : binding 127.0.0.1 partout, requirepass + 8 rename-command, REDIS_PASSWORD propagé aux 12 fichiers Python, validé end-to-end (NOAUTH sans password, FLUSHALL renamed, app HTTP 200).
- **Recovery script worker** — Au boot : `mgr.list_active_jobs()` → relance depuis dernier checkpoint. Source : `project_v2_finalisation_phasing.md`. **Non démarré**.

---

## 🚧 Chantiers techniques engagés mais non finalisés

- **Sprint V3.3 contradiction detection (S1a/S1b/S2/S3/S4 + R1-R7)** — Plan 9 sprints, seul S0 amorcé. Le runtime 7 modes déprisé par V2 anchor-driven, mais le **modèle de données V3.3** (12 LogicalRelations, 3 axes, LifecycleStatus) reste valide pour l'ingestion. Source : `zazzy-beaming-crane.md`. **S0 amorcé, reste reporté/repensé**.
- **LIFECYCLE_RELATION strict (V2-S1)** — Persistence sur déclaration textuelle explicite uniquement, validator evidence-locked, backfill 17 docs aerospace. Source : `VISION_RECENTREE_OSMOSIS_2026-04-30.md` §9. **Amorcé**.
- **Refactor profond post-V2** — Mentionné mais sans spec. Source : `project_v2_finalisation_phasing.md`. **Non démarré, scope non documenté**.
- **Calibration auto-adaptative response modes** — Étendre au-delà de SAP : 20-30q calibration au post-import. Mode AUGMENTED désactivé en attente. Source : `project_v3_response_modes.md`. **Non démarré**.
- ✅ **Mode AUGMENTED reactivation** — Livré 2026-05-01 (commit 8632371) : 14 exemples LLM ajoutés au yaml, trigger candidate Etage A (question_mode==AUGMENTED + ≥3 nouveaux docs), gate Etage B renforcé (new_docs ≥ 3 + kg_trust ≥ 0.5). Rollback rapide via env MODE_AUGMENTED_ENABLED=false.
- **Refonte chat (Phase 1 + 2)** — Phase 1 nettoyer (score, bloc verite, sources lisibles) ; Phase 2 Split Truth View + Insight Cards + switch automatique. Source : `CHANTIER_REFONTE_CHAT.md`. **Non démarré** (runtime-v2 a peut-être résolu une partie).
- **Verify V1 — refacto via pipeline search** — `evidence_matcher` cassé. Refactorer `verification_service` pour utiliser le pipeline search. Source : `CHANTIER_VERIFY_V1_ETAT.md`. **Non démarré**.
- **Verify V2 — Document Review Word** — Upload .docx → analyse → .docx annoté avec commentaires natifs. 3 niveaux. Source : `SPEC_VERIFY_V2_DOCUMENT_REVIEW.md`. **Non démarré**.
- **RAGAS faithfulness — double scoring** — `faith_chunks` vs `faith_total` (avec graph context). Source : `project_ragas_faithfulness_investigation.md`. **Non démarré** (~6-9h).

---

## 📋 Chantiers définis mais non commencés

- **Cockpit widget burst local vLLM** — Throughput tok/s temps réel, KV cache, prefix cache. Source : `project_cockpit_widget_local_burst.md`. **Non démarré**.
- ✅ **Atlas — restructuration Domain → Document → Topic** — Livré 2026-05-01 (commit 927bc53) : nouvelle fonction `enrich_atlas_domains()` qui clusterise les AtlasRoots via DeepSeek-V4-Pro. Schéma `(:AtlasDomain)-[:CONTAINS_ROOT]->(:AtlasRoot)`. API expose hiérarchie Domain → Root → Topic. Frontend rendu hiérarchique conditionnel + fallback vue plate. Sur aerospace : 2 domains générés (navigabilité 6765 faits / dual-use 5407 faits).
- **Atlas — global_reading_order cross-dossiers** — Tour guidé corpus complet. Source : `project_atlas_pipeline_production.md`. **Non démarré**.
- **Frontend admin ClaimFirst Settings** — Page sliders pour les paramètres ClaimFirst + table `tenant_settings` Postgres. Source : `TODO_ADMIN_UI_CLAIMFIRST_PARAMS.md`. **Non démarré**.
- **Plugin Word Office Add-in** — React+Office.js, panneau latéral. Source : `SPEC_VERIFY_V2_DOCUMENT_REVIEW.md`. **Non démarré** (~2-3j MVP).
- **Externaliser listes hardcodées non-critiques** — 55 listes / 20 fichiers. Critiques fait, reste benchmark detection (`TENSION_KEYWORDS`, etc.) → `config/detection_keywords.yaml`. Source : `AUDIT_HARDCODED_WORD_LISTS.md`. **Partiellement fait**.
- **Answer Gap Detector** — TF-IDF inverse + gap_score déterministe ANSWERABLE/UNCERTAIN/UNANSWERABLE. Source : `PROPOSITION_ANSWER_GAP_DETECTOR.md`. **Non démarré**.
- **HALT/EPR Logprob Entropy Detection** — `logprobs=true` dans synthèse, entropie moyenne, flag si > seuil. Source : `RECHERCHE_UNANSWERABLE_DETECTION.md`. **Non démarré** (~1-2h).
- **Phase 2 OSMOSE** — NarrativeThreadDetector + IntelligentSegmentationEngine + DualStorageExtractor. TODOs Phase 1 dans `src/knowbase/semantic/__init__.py`. **Non démarré**.
- **Reflexion Leiden / GraphRAG hiérarchique** — Source : `[futur]_REFLEXION_LEIDEN_GRAPHRAG.md`. **Réflexion uniquement**.
- **Health Toolbox scripts** — Tri 4 catégories (Diagnostic, Correctif, Rebuild, Infra) + déplacements vers `archive/`, `tests/`, `poc/`. Source : `HEALTH_TOOLBOX_SCRIPTS.md`. **Non démarré**.
- **Benchmark Dashboard UI (5 onglets)** — Drill-down score → questions → détail. Source : `SPEC_BENCHMARK_DASHBOARD_UI.md`. **Non démarré**.
- **Exact Answer Gate V1** — Rejet pre-LLM pour questions à réponse structurée absente. Source : `SPEC_EXACT_ANSWER_GATE_V1.md`. **Non démarré**.

---

## 🐛 Bugs identifiés à corriger

- [x] **Bug Qwen2.5-14B dégénérescence ClaimFirst** — WEF Presidio : 148 batches, 433 erreurs, 0 claims. ✅ **Fix défensif appliqué 2026-05-01** (commit 8e67caf) : `_is_degenerative_response()` détecte 3 patterns avant `json.loads`. Reste dormant tant que rien ne dégénère. La cause racine prompt domain-agnostic n'a pas été touchée (besoin du PDF pour repro).
- [x] **Bug cache markdown full_text vide** — ✅ **Déjà corrigé** (vérifié 2026-05-01) : `MarkdownExtractor` existe (`extraction_v2/extractors/markdown_extractor.py`) et est branché dans `jobs_v2.py:191`.
- [x] **Bug dispatcher /docs_in route Stratified V2 obsolète** — ✅ **Fix appliqué 2026-05-01** (commit 8e67caf) : `INGESTION_SKIP_STRATIFIED_V2=true` par défaut, ClaimFirst (étape 5) reste l'extracteur productif.
- [ ] **Facet linkage 27% sur biomédical** — 3 tentatives ont empiré. Piste : embedding similarity sur `facet.canonical_question`. Source : `project_facet_linkage_chantier.md`. **⏸️ Pending** (~1j dev + corpus biomédical pour valider, pas un quick fix).
- [x] **frontend/package.json gitignored** — ✅ **Fix appliqué 2026-05-01** (commit b50d3e6) : exception `!frontend/package.json`/`!frontend/package-lock.json`/`!frontend/tsconfig*.json` dans .gitignore + 3 fichiers maintenant trackés.
- ~~**Bug 029/030 crash post-Docling silencieux**~~ — **Retiré du backlog 2026-05-01** : pas reproductible sans contexte de logs (perdu depuis 30/03). À ré-ouvrir uniquement si le bug récidive lors d'un nouvel import (logger alors stdout/stderr Docling + fichier source).
- [x] **Frontend bouton "Lancer" RAGAS cassé** — ✅ **Fix appliqué 2026-05-01** (commit 8e67caf) : mismatch profile `default` → `standard` dans PROFILES + 2× `useState`. Backend valide `['quick','standard','full']`.
- [x] **`ragas` perdu à chaque restart worker** — ✅ **Déjà corrigé** (vérifié 2026-05-01) : `ragas>=0.4.0` est dans `app/requirements.txt`, version 0.4.3 installée dans app + worker containers.
- [x] **Burst state perdu au restart app** — ✅ **Fix appliqué 2026-05-01** (commit 8e67caf) : `_try_rehydrate_from_persistent_state()` au boot du `BurstOrchestrator` lit Redis+fichier (avec health check) et reconstitue `self.state` si l'instance est saine.

---

## 🔍 Investigations à reprendre (orientées dev)

- **Instabilité juge LLM benchmarks T2/T5** — gpt-4o-mini non-déterministe même temp=0. 37%-84% sur même corpus → impose fix dev (changer juge ou hybridation). Source : `INVESTIGATION_BENCHMARK_JUDGE_STABILITY.md`. **En cours**.
- **KG Quality régulatoire P5 (entités génériques)** — P1-P4, P6 résolus, P5 reste. Source : `INVESTIGATION_KG_QUALITY_REGULATORY.md`. **Non démarré**.
- **Negative Rejection — implémentation** — Coverage Score pre-synthèse. Source : `ANALYSE_NEGATIVE_REJECTION_STRATEGY.md`. **Analyse rédigée, non implémenté**.
- **Étape qualité OSMOSIS — chunks fragiles** — chain_coverage 52.3% (-18pp). Source : `ANALYSE_ETAPE_QUALITE_OSMOSIS.md`. **Fixes non démarrés**.
- **Pollution KG mode DIRECT — gap enrichissement** — B' Override partiel. Source : `ANALYSE_KG_ENRICHMENT_GAP.md`. **Amorcé**.
- **Doublon SubjectAnchors "Rise with SAP" / "S/4HANA Private Cloud"** — Source : `project_sprint2_chunking_vision.md`. **Non démarré**.
- **199 mots tronqués (8%) — hard cut sans sentence/line break** — Rechunker V3 résiduel. **Non démarré**.

---

## 🎨 Améliorations UX/UI

- **UI Raisonnement étendu** — Couverture mode DIRECT/AUGMENTED, silences, tensions. Source : `ADR_RAISONNEMENT_UI.md`. **À faire selon priorité**.
- **Multi-preset themes (Dark Elegance + Fusion)** — Switcher header. Source : tâche #17. **Foundation amorcée, finalisation à faire**.
- **Frontend N2 visualisation grappes de tensions** — KG Health cockpit existe, exposition tensions à vérifier. **À explorer**.
- **N5 side-by-side claims en tension** — Source : `ARMAND_TEST_READINESS_AUDIT.md`. **Non démarré**.
- **N1 export PDF de la trace** — **Non démarré**.
- **Persona profiles V1** — Réduit à 1 toggle Audit en V2. À intégrer en sprint V2-S5. **Non démarré**.
- **Sources cliquables avec nom lisible** — Au lieu de hash. Source : `CHANTIER_REFONTE_CHAT.md` problème 6. **Non démarré**.

---

## ⚙️ Dette technique / refactor

- ✅ **Suppression physique runtime V1.1** — Vérifié 2026-05-01 : `src/knowbase/runtime/` n'existe plus, aucune référence orpheline, frontend `/chat/runtime` retiré. Cleanup déjà complet.
- ✅ **Stratified V2 router déprecate** — Livré 2026-05-01 (commit 8632371) : `/api/v2/*` retiré du main.py (HTTP 404). Code `knowbase/stratified/` conservé car pass0/pass1/claimkey activement utilisés par ClaimFirst.
- **TODOs critiques code** :
  - `auth_service.py:23` — JWT secret depuis env vars
  - `llm_router.py:1345/1353` — async pour Anthropic + SageMaker
  - `dispatcher.py:245/254` — queue retry + LLM via LLMRouter
  - `signal_policy.py:235/254` — gap signal cross-lingue + cross-encoder NLI
  - `assertion_classifier.py:126` — cross-encoder en production
  - `agents/budget.py:231` — quotas tenant via Redis
  - `relations/llm_relation_extractor.py:332` — chunking intelligent
  - `instrumented_answer_builder.py:131` — evidence_url avec highlight
  - + ~15 autres TODOs mineurs dispersés
- **Dette ComparableSubject — fix structurel** — Hiérarchie produit (parent/enfant) dans pack + propagation release_id. Source : `project_dette_comparable_subject.md`. **Fix minimal fait, structurel non démarré**.

---

## Suivi des modifications

| Date | Auteur | Modification |
|---|---|---|
| 2026-05-01 | Audit initial | Création du backlog suite à audit complet |
| 2026-05-01 | Bug fixing session | 7/9 bugs traités (6 fixes + 3 vérifications "déjà corrigé"), 2 pending documentés (facet linkage biomédical = ~1j dev dédié, crash 029/030 = repro perdue) |
| 2026-05-01 | Sprint A→E | 5 chantiers livrés : Sécurisation Redis (commit 863c988), runtime V1.1 cleanup vérifié, Stratified V2 router déprecate (8632371), Mode AUGMENTED réactivation (8632371), Atlas Domain→Root→Topic (927bc53) |
