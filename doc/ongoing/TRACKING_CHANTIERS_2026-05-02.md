# Tracking chantiers OSMOSIS — actif au 2026-05-02 (rafraîchi 2026-05-10)

> **But** : fichier de pilotage unique pour adresser les chantiers restants un à un.
> **Source** : audit `BACKLOG_DEV_2026-05-01.md` + descriptions détaillées rédigées 02/05 + ajouts incrémentaux.
> **Statut** : `TODO` / `IN_PROGRESS` / `DONE` / `BLOCKED` / `DEFERRED` / `SUPERSEDED`.
> **Convention** : à chaque démarrage, mettre `IN_PROGRESS` + date. À chaque clôture, `DONE` + commit hash.
> **Rafraîchissement 2026-05-06** : ajout des sections CH-30.9-18, CH-31, CH-32, CH-33, CH-34, CH-35, CH-36/37/38 (SUPERSEDED), CH-39 (Refonte V3 livrée), CH-40 (Sprint S0 V4 Calibration & Gold-set complet), CH-41 (V4 Facts-First Tranche 1 list — en cours, **CH-41.M BLOCKING avant tout code**). Pivot architectural V4 facts-first acté à 3 voix (Fred + Claude + ChatGPT) — ADR `chantiers/2026-05-06_CH-41_ADR_FACTS_FIRST.md` ratifié.
>
> **Rafraîchissement 2026-05-10** : ajout section **CH-49 OSMOSIS V4.2 Tiered Pipeline** — runtime_v4_2/ livré complet (Phase 1+2+3+4). Architecture cible Layer 0+1+2 avec 5 operators Cap2.A/B/C/D/E + UnifiedIntentRouter + verifier veto critique. ADR v1.1 LOCKED post 2 rounds critique LLMs externes. 4 commits poussés `c96fe01..c0b4863`. **Charte respectée** : 0 référence corpus dans runtime, modèles open-source uniquement (Sonnet/GPT-4o exclus). Endpoint `/api/runtime_v4_2/answer` live en parallèle de V4.1 (pas de promotion principal).

---

## 🚨 Direction architecturale courante (06/05/2026)

**Pivot V4 facts-first** post-Sprint S0 :
- V3 LLM-centric (chunks → LLM résume → réponse) abandonné comme cible — diagnostiqué « compression sémantique destructive » (factual_correctness 0.368, item_recall 0.07, 31.7% judge_overscored)
- Cible V4 : Retrieval → Question Type Detection → Type-Adaptive Fact Extraction → Composition (LLM = formatage uniquement) → Verifier final
- Déploiement par **tranches verticales** (pas MVP) : list → factual → temporal/comparison → causal → unanswerable/false_premise → verifier cascade
- ADR maître : `doc/ongoing/chantiers/2026-05-06_CH-41_ADR_FACTS_FIRST.md` (intègre design ChatGPT 06/05 + 8 ajustements C1-C8 + réserve forte verrouillage contrats avant code)
- Doc état des lieux S0 : `doc/ongoing/chantiers/2026-05-05_CH-40_S0_BASELINE.md` (504 lignes, self-contained, partage externe)
- Design réf. : `doc/ongoing/chantiers/2026-05-06_CH-41_STRUCTURER_V1_DESIGN_REFERENCE.md`
- **CH-41.M = bloquant pour tout le reste** : verrouiller contrats Structured Evidence Package commun + Domain Pack extension AVANT de coder.

---

## 🔥 Priorité haute

### CH-01 — Recovery script worker
- **Statut** : DONE (2026-05-02, commit 3a35e64)
- **Effort** : ~0.5j
- **Fichiers** : `BurstOrchestrator.__init__`, `JobsV2Manager.boot()`
- **Quoi** : Au boot de l'app/worker, balayer `mgr.list_active_jobs()` et relancer chaque job depuis son dernier checkpoint Redis (`osmose:job:<id>:state`).
- **Pourquoi** : Aujourd'hui un restart app perd le store en mémoire ; tout import en cours doit être relancé manuellement (cf. mésaventure burst state du 09/04). Un crash sur 4j d'ingestion = redémarrer 4j.
- **Acceptation** : `docker restart knowbase-worker` pendant un import → reprise automatique depuis le dernier checkpoint, aucun document re-traité depuis le début.
- **Note** : la rehydratation burst state (commit 8e67caf) est un sous-ensemble du même pattern à généraliser.

---

## 🚧 Engagés mais non finalisés

### CH-02 — Modèle V3.3 résiduel post-V2 anchor-driven
- **Statut** : IN_PROGRESS — Phase 1 cadrage livrée 2026-05-02 (`chantiers/2026-05-02_CH-02_CADRAGE_V33_VS_V2.md`), périmètre réduit à 4 sous-chantiers
- **Effort total** : ~4j (au lieu des 2-3 sprints initiaux — V2 a absorbé l'essentiel de V3.3)
- **Ordre validé** : CH-02.1 → CH-02.4 → CH-02.3 → CH-02.2

#### CH-02.1 — Backfill lifecycle_status DocumentContext
- **Statut** : DONE (2026-05-02, commit a5b8288)
- **Effort** : 0.5j
- **Quoi** : 0/17 docs ont `lifecycle_status`. Inférer de manière déterministe : ACTIVE par défaut, DEPRECATED si un successor EVOLVES_FROM/SUPERSEDES sortant existe.
- **Pourquoi** : Bloque l'étape Current Resolver V2 (filtrage `WHERE dc.lifecycle_status = 'ACTIVE'`).
- **Acceptation** : 17/17 DC ont une valeur, distribution audit log.

#### CH-02.4 — Finaliser validity_start claim-level (résidu S1b)
- **Statut** : DONE (2026-05-02, plafond technique atteint)
- **Effort réel** : ~30 min (batch 19.7 min + audit 10 min) sur burst EC2 g6.2xlarge
- **Résultat** : 333 claims avec validity_start (idem pré-batch — pipeline idempotent)
- **Acceptation revisée** : la cible "≥3 000 claims" du plan S1b était une **estimation erronée** (basée sur Phase B Test 2 sur autre échantillon). Le plafond du pipeline evidence-locked sur le corpus aerospace est 333/40 196 = 0.83%.
- **Audit qualité Claude (15 claims rejetés)** : 14/15 corrects + 1 borderline. Les 1 102 candidates rejetées sont presque toutes des cas où la date numérique du passage est :
  - un identifiant de loi (`Act 111/1994`, `Regulation 522/1973`, `ISO 230-2:1988`, `NPA 2015-19`)
  - une date d'émission de document référencé (`AC dated 18.5.2009`, `EUROCAE amendment dated 06/09/99`)
  - une date d'adoption parlementaire (`of 15 July 2020` ≠ applicable_from selon V3.3)
  - un numéro de section (`4.1.11 Supercooled...`)
- **Conclusion** : LLM bien calibré (0 hallucination, 0 faux négatif évident). Pour le pipeline V2 anchor-driven, le fallback runtime via `doc.publication_date` (cf VISION §4.2) couvre les 39 863 claims sans override. Augmenter au-delà de 333 nécessiterait soit relâcher le validator (= hallucinations), soit confondre identifiant/adoption avec applicable_from (= faux).

#### CH-02.3 — REAFFIRMS Doc→Doc (extension V2-S1)
- **Statut** : DONE (2026-05-02, commit 3682bd1)
- **Effort réel** : 13 min batch sur burst EC2 (script `backfill_lifecycle_relations_strict.py --all` 17 docs)
- **Résultat** : **0 REAFFIRMS détecté** dans le corpus aerospace
- **Acceptation revisée** : le code REAFFIRMS était déjà en place (model + prompt + persister depuis V2-S1). Le batch a confirmé que **le corpus aerospace ne contient PAS de déclaration textuelle explicite de réaffirmation** (ex: "This document reaffirms..."). C'est un résultat factuel — le LLM a scanné et n'a rien hallucné.
- **Bonus livré** :
  - **+1 EVOLVES_FROM** détecté + supprimé (faux positif cs25_amdt_26→25, conf=0.5, quote="CS-25") — cleanup P1.1 du PHASING V2 appliqué
  - **Durcissement persister** : ajout seuils `min_confidence ≥ 0.70` et `min_quote_len ≥ 30` dans `lifecycle_persister.py` pour empêcher la récurrence de ce type de faux positif
- **État final KG** : 4 LIFECYCLE_RELATION (3 EVOLVES_FROM dualuse + 1 SUPERSEDES), tous conf ≥ 0.98 et quote ≥ 30 chars
- **CH-03 implication** : CH-03 LIFECYCLE_RELATION strict V2-S1 est **absorbé par CH-02.3** — le scan multi-fenêtre a tourné sur les 17 docs avec le pattern V2-S1 complet. Pas besoin de relancer CH-03 séparément.

#### CH-02.2 — Audit qualité 4 862 LOGICAL_RELATION existantes
- **Statut** : DONE (2026-05-02, audit livré, en attente validation user pour exécution purge)
- **Effort réel** : ~1h (47 paires auditées par Claude expert)
- **Livrable** : `doc/ongoing/chantiers/2026-05-02_CH-02.2_AUDIT_LOGICAL_RELATION.md`
- **Résultats** :
  - **EQUIVALENT** 12/12 = 100% factuel (mais ~90% verbatim copies — utilité faible)
  - **OVERLAP** 0/6 = 0% — fallback générique cassé (en réalité = SUPERSET/SUBSET/DISJOINT)
  - **EXCEPTION** 0/6 = 0% — confusion avec EQUIVALENT/LIFECYCLE
  - **CONFLICT** 2-4/16 = 12-25% — confusion énumération OR avec opposition
  - **DISJOINT** 3/3 = 100% ✅
  - **SUPERSET** 0/2 = 0% — direction d'inclusion incorrecte
  - **SUBSET** 1/1 = 100% ✅
  - **DEFINITION_OF** 1/1 = 100% ✅
- **Recommandations user — VALIDÉES "a" (option safe partout) 2026-05-02** :
  - Q1 ✅ Purgé OVERLAP (436) + EXCEPTION (84) + SUPERSET (2) = **522 edges**
  - Q2 ✅ Option A — purgé 12 faux positifs CONFLICT (frequency changers, Appendix O facets, DS/SC alloys, Output energy J, ETOPS thresholds), gardé **4 vrais/borderline** : hazardous/catastrophic ×2, service history, impact energy
  - Q3 ✅ Option (a) — EQUIVALENT (4 319) gardés tels quels (no-op)
- **État final KG** : 4 328 LOGICAL_RELATION (vs 4 862 avant, -534 edges = -11%)
  - EQUIVALENT 4 319 (gardés, ~90% verbatim cross-doc)
  - CONFLICT 4 (vrais/borderline, conf ≥ 0.9)
  - DISJOINT 3, SUBSET 1, DEFINITION_OF 1 (gardés, 100% précision)
- **Patterns d'erreur identifiés** :
  - CONFLICT : décomposition d'énumération "X may be A or B" en 2 claims contradictoires
  - OVERLAP : utilisé comme fallback quand classifier ne sait pas trancher SUPERSET/SUBSET/DISJOINT
  - EXCEPTION : utilisé pour toute différence textuelle (paraphrases, évolutions de version)
- **Implication V2** : refactor du classifier 12-types pour résoudre ces patterns = sprint dédié hors scope CH-02 (déféré V2-S2/S3 ou plus tard)

### CH-03 — LIFECYCLE_RELATION strict (V2-S1)
- **Statut** : DONE — absorbé par CH-02.3 (2026-05-02)
- **Note** : le backfill `backfill_lifecycle_relations_strict.py --all` exécuté en CH-02.3 a couvert le scope V2-S1 complet (3 types LIFECYCLE × 17 docs). Plus de delta à livrer côté code. Si nouveaux docs ingérés → relancer le script.
- **Effort restant** : 0
- **Fichiers** : `lifecycle_relation_extractor.py` (à créer), validator commun avec apply_frame_v2
- **Quoi** : Persister `(:Claim)-[:LIFECYCLE_RELATION {kind, evidence_quote, doc_id}]→(:Claim)` UNIQUEMENT si une déclaration textuelle explicite l'établit ("This regulation supersedes Reg 2021/821..."). Validator evidence-locked obligatoire.
- **Pourquoi** : Le compliance officer doit tracer la chaîne légale d'évolution. Aujourd'hui les liens versionnels sont implicites (release_id), pas exploitables en query "qu'est-ce qui remplace cet article ?".
- **Acceptation** : backfill 17 docs aerospace → ≥1 LIFECYCLE_RELATION détectée par doc avec evidence_quote présente verbatim.

### CH-04 — Calibration auto-adaptative response modes
- **Statut** : IN_PROGRESS — CH-04.1 livré 2026-05-02, CH-04.2/3/4 différés
- **Effort total** : ~2-3j (CH-04.1 = 0.5j fait, CH-04.2 = 1.5j déféré, CH-04.3 = 0.3j déféré, CH-04.4 = 0.5j-1j déféré)

#### CH-04.1 — Externalisation seuils dans YAML
- **Statut** : DONE (2026-05-02, commit e019fd7)
- **Effort** : 0.5j (réel ~30 min)
- **Livré** :
  - `config/response_modes_thresholds.yaml` — 12 seuils + generic_entities + tenant_overrides
  - `src/knowbase/config/response_modes_thresholds.py` — loader Pydantic-style avec singleton + reload
  - `signal_policy.py` refactoré : `MAX_KG_INJECTION_TOKENS`, `TENSION_MIN_STRENGTH`, `TENSION_MIN_TEXTS`, `EXACTNESS_MIN_STRENGTH`, `AUGMENTED_MIN_NEW_DOCS`, `AUGMENTED_GATE_MIN_NEW_DOCS`, `AUGMENTED_GATE_MIN_TRUST`, fallback TENSION (2/0.4), fallback STRUCTURED_FACT (2/0.5), `KG_OVERRIDE_MIN_CONFIDENCE`, `GENERIC_ENTITIES` — tous lus depuis YAML.
- **Acceptation** : smoke test passé — toutes les valeurs match les hardcodes pré-refacto, comportement identique.

#### CH-04.2 — Calibration auto via questions étalon (DIFFÉRÉ)
- **Statut** : DEFERRED — à activer just-in-time quand on ingère un nouveau corpus (test Armand)
- **Effort estimé** : 1.5j
- **Quoi** : Service `corpus_calibration_runner.py` qui génère 20-30 questions étalon (LLM sur claims), run le pipeline, mesure les distributions (n_tensions, distinct_docs, kg_trust), calcule des seuils calibrés (ex: 25e percentile pour MIN_NEW_DOCS, 50e pour MIN_TRUST), persiste dans `tenant_settings` Postgres.

#### CH-04.3 — Hook post-import (DIFFÉRÉ avec CH-04.2)
- **Statut** : DEFERRED
- **Effort estimé** : 0.3j
- **Quoi** : Trigger CH-04.2 automatiquement après import batch.

#### CH-04.4 — Dashboard observabilité response modes (NOUVEAU, DIFFÉRÉ)
- **Statut** : DEFERRED
- **Effort estimé** : 0.5-1j
- **Quoi** : Dashboard frontend qui montre la distribution des modes décidés (DIRECT vs AUGMENTED vs TENSION...), le taux de fallback Étage B (cands AUGMENTED → DIRECT), les corrélations RAGAS×mode. Permet de DÉTECTER si les seuils sont mal adaptés (ex: 100% DIRECT = AUGMENTED jamais déclenché, ou 80% fallback = mismatch A/B).
- **Pourquoi** : Sans cet outil d'observabilité, on ne sait pas SI les seuils nécessitent recalibration. C'est la condition préalable pour CH-04.2 (calibration auto).

### CH-05 — Refonte chat Phase 1 (nettoyer)
- **Statut** : DONE (2026-05-02) — CH-05.1, CH-05.2, CH-05.3, CH-05.4, CH-05.5 livrés
- **Effort total révisé** : ~2j (vs 2-3j initial — CH-05.4/5 ajoutés en cours de route en réaction au feedback UX "indigeste")

#### CH-05.1 — Cleanup composants obsolètes
- **Statut** : DONE (2026-05-02, commit à venir)
- **Effort** : 0.5j (réel ~30 min)
- **Livré** :
  - **Supprimés** : 11 composants chat obsolètes (~2 300 lignes) — `KnowledgeProofPanel`, `ReasoningTracePanel`, `CoverageMapPanel`, `InstrumentedToggle`, `TruthContractBadge`, `AssertionRenderer`, `AssertionPopover`, `ProofTicketCard`, `InstrumentedAnswerDisplay`, `SplitTruthView`, `SourceCard` (chat/)
  - **Supprimé** : `frontend/src/types/instrumented.ts` (347 lignes)
  - **Cleanup** : `chat/index.ts` (5 exports actifs), `lib/api.ts` (param `useInstrumented` retiré + body `use_instrumented`), `types/api.ts` (prop `instrumented_answer` retirée), `types/index.ts` (export instrumented retiré)
  - **Bonus** : retiré dead code `getConfidenceConfig` dans `SynthesizedAnswer.tsx` + 3 imports orphelins + duplicate `position="relative"`
- **Total cleanup** : ~2 650 lignes mortes
- **Validation** : `tsc --noEmit` aucune nouvelle erreur (les erreurs préexistantes hors scope CH-05.1 conservées)

#### CH-05.2 — Helper formatDocumentName centralisé
- **Statut** : DONE (2026-05-02, commit à venir)
- **Effort** : 0.3j (réel ~20 min)
- **Livré** :
  - **Nouveau** : `frontend/src/lib/formatDocumentName.ts` — 2 helpers exportés (`formatDocumentName`, `getFileExtension`)
  - Logique : retire path → hash final (`_[a-f0-9]{6,}`) → préfixe numérique (`^\d{3}(_\d+)?_`) → extension → underscores/tirets en espaces → title case basique avec préservation des acronymes/numéros → tronque à 55 chars
  - **Refactoré** : `SearchResultDisplay.tsx`, `SourcesSection.tsx`, `ThumbnailCarousel.tsx` — utilisent maintenant le helper unifié
  - **Bug fix** dans `SourcesSection.tsx` : `getFileExtension` recevait `filename` (déjà nettoyé sans extension) au lieu de `source` brute → tous les badges file type tombaient sur `DEFAULT`. Maintenant l'extension est extraite avant cleanup.
- **Validation** : `tsc --noEmit` aucune erreur sur fichiers refactorés.

#### CH-05.3 — Sources cliquables vers fichier source
- **Statut** : DONE (2026-05-02, commit fdf72ea)
- **Effort** : 0.5j (réel ~45 min)
- **Livré** :
  - **Backend** : nouveau endpoint `GET /api/documents/source-file?doc_id=...` qui :
    - Retire le suffix hash hex du doc_id (`cs25_amdt_22_8e69026c` → `cs25_amdt_22`)
    - Cherche dans `data/docs_in/` puis `data/docs_done/` un fichier dont le stem match
    - Retourne `FileResponse` avec auto-detect media_type
    - Sécurité : path traversal bloqué (`/`, `\`, `..` rejetés sur le doc_id) + `resolve()` validé contre les whitelists
  - **Frontend** : `SourcesSection.tsx` :
    - Au clic sur une source, fetch authentifié (Bearer JWT) → blob → `URL.createObjectURL` → `window.open` nouveau tab
    - Si `source_file` est déjà une URL absolue (`http://`/`https://`), ouvre directement
    - Toast d'erreur si le fichier est introuvable / fetch échoue
    - Cleanup `URL.revokeObjectURL` après 60s
- **Limitation actuelle** : scan O(n) du filesystem à chaque clic (pas de cache/index doc_id → path). Acceptable pour les 17 docs aerospace, à optimiser si volume augmente.
- **Tech debt** : créer une table de mapping doc_id → file_path en Postgres pour éliminer le scan FS (CH-05.3b futur).

#### CH-05.4 — Footnotes Wikipedia-style (refonte UX inline pills)
- **Statut** : DONE (2026-05-02, commits `37397f0`, `5b171a5`)
- **Effort** : 0.4j (réel ~30 min)
- **Contexte** : feedback user "c'est indigeste et les liens ne semblent pas fonctionner" (6-8 pills `cs25_amdt_27_..., p.433` denses dans chaque paragraphe). Choix Option 3 footnotes-style.
- **Livré** :
  - **Nouveau** : `frontend/src/lib/sourceRefs.ts` — `indexAndReplaceSources(text)` parse `[[SOURCE:doc_id|page]]` → remplace par `[[REF:N]]` + retourne liste ordonnée `SourceRef[]`. Dédup par `(docId, page)` (initialement par docId seul, modifié en CH-05.5).
  - **Nouveau** : `frontend/src/components/ui/SourcesFootnotes.tsx` — composant liste numérotée en bas de réponse. Chaque entrée `[N] DocName · p.XXX` cliquable, ouvre le fichier source.
  - **Nouveau** : `RefPill` dans `SourcePill.tsx` — pill compacte `[N]` inline (~20px) cliquable, tooltip = `[N] DocName p.XXX`. Prop renommée `sourceRef` (collision React reserved `ref`).
  - **Nouveau** : `renderWithRefs(text, refs)` dans `SourcePill.tsx` — parse `[[REF:N]]` → React nodes `<RefPill>`.
  - **Modifié** : `SynthesizedAnswer.tsx` — pré-process `synthesis.synthesized_answer` via `indexAndReplaceSources` (useMemo), passe `sourceRefs` à `createMarkdownComponents`, rend `<SourcesFootnotes refs={sourceRefs} />` à la fin.
- **Bug fix** : prop `ref` renommée `sourceRef` après runtime error "Cannot read properties of undefined (reading 'docId')" — `ref` est interceptée par React (forwardRef).
- **Acceptation** : pills `[1]`, `[2]`, ... compactes inline ; liste détaillée en bas avec nom + page ; clic ouvre le fichier source.

#### CH-05.5 — Deep-link PDF #page=N (RFC 3778)
- **Statut** : DONE (2026-05-02, commits `fdc0646`, `59a527d`, `6208150`)
- **Effort** : 0.3j (réel ~20 min)
- **Contexte** : user demande "n'utiliser qu'un numéro pour chaque occurrence du doc dans le texte", puis confirme "il n'est pas possible d'ouvrir le pdf directement à la bonne page, hein ?" → vérifie faisabilité, implémente.
- **Livré** :
  - **Backend** : `documents.py` `/source-file` — ajoute `Content-Disposition: inline` (vs `attachment`) pour permettre rendu inline dans le viewer PDF du navigateur (au lieu de download).
  - **Frontend** : `openSourceFile.ts` :
    - Helper `parsePageNumber(page)` accepte `number | string` (parse `"p.433"` ou `42`).
    - Append fragment `#page=N` à l'URL ouverte (RFC 3778).
    - Pour blob URLs (doc_id → fetch authentifié) : fragment ajouté **uniquement si** `blob.type === 'application/pdf'` (ignoré sinon).
    - `URL.revokeObjectURL` strip le fragment avant cleanup.
  - **Frontend** : `sourceRefs.ts` — dédup par `(docId, page)` (au lieu de docId seul) → permet plusieurs entrées pour le même PDF cité à différentes pages, chaque clic ouvre la bonne page.
  - **Frontend** : `RefPill` + `SourcesFootnotes` — passent `ref.page` à `openSourceFile`, tooltip et liste affichent la page.
- **Comportement final** :
  - PDFs → vrai deep-link à la page (`[1] Cs25 Amdt 27 · p.433` ouvre p.433, `[2] Cs25 Amdt 27 · p.585` ouvre p.585).
  - PPTX/DOCX → fragment ignoré par le navigateur, ouvre page 1 (limitation RFC 3778, formats non concernés).
- **Acceptation** : multi-pages PDF testé OK ; ouvre directement à la bonne page dans le viewer Chrome/Edge intégré.

### CH-06 — Refonte chat Phase 2 (Insight Cards + Audit auto)
- **Statut** : IN_PROGRESS (CH-06.1, CH-06.2, CH-06.3 livrés 2026-05-03 — reste validation runtime CH-06.4)
- **Effort réel** : ~1.5h (vs 4-5j initial — squelette V1 réutilisable, refonte ciblée)
- **Diagnostic état avant** : 60% du squelette existait (types `InsightHint`, fonction `_generate_insight_hints` legacy V1.1, `InsightHintsBlock` UI legacy) MAIS la fonction backend interrogeait `:CONTRADICTS|REFINES|QUALIFIES` (relations purgées en V2 le 30/04) et n'était pas branchée à `/api/runtime_v2/answer`.

#### CH-06.1 — Backend insight_hints V2 (LOGICAL + LIFECYCLE)
- **Statut** : DONE (2026-05-03)
- **Livré** :
  - `src/knowbase/runtime_v2/insight_hints.py` (nouveau) — `build_insight_hints(response, driver, tenant_id)` qui génère 3 types de cards depuis `PipelineResponse` :
    - `attention` — `ConflictReport.is_resolved_by_lifecycle=False` (vraie contradiction)
    - `evolution` — conflict résolu par lifecycle + `LIFECYCLE_RELATION` (SUPERSEDES/EVOLVES_FROM/REAFFIRMS) sortantes des docs cités + anchor RANGE avec evolution_points
    - `cross_doc` — ≥2 `authoritative_doc_ids`
  - `src/knowbase/runtime_v2/models.py` — `PipelineResponse.insight_hints: list[dict]` ajouté
  - `src/knowbase/api/routers/runtime_v2.py` — appel `build_insight_hints()` post-pipeline (non-bloquant) + log `n_insight_hints` ajouté
- **Validation** : Python compile OK. Activation runtime nécessite restart app (à faire après bench actuel).

#### CH-06.2 — Frontend cards visuelles
- **Statut** : DONE (2026-05-03)
- **Livré** :
  - `frontend/src/components/runtime/InsightCards.tsx` (nouveau, ~140 lignes) — composant React avec 3 styles distincts (rouge/violet/teal), icônes (alert/calendar/link), priorités, tri auto attention > evolution > cross_doc
  - Type `InsightHint` exporté pour réutilisation
  - `frontend/src/app/chat/runtime-v2/page.tsx` — type `PipelineResponse.insight_hints` ajouté + `<InsightCards />` rendu juste sous la synthèse
- **Validation** : tsc sans nouvelle erreur (les erreurs TS visibles sur `LifecycleGraphMini` sont préexistantes — `reactflow/dagre` pas indexés).

#### CH-06.3 — Mode Audit auto
- **Statut** : DONE (2026-05-03, intégré dans CH-06.2)
- **Livré** : badge "🔍 Mode Audit · Contradiction(s) détectée(s)" en rouge auto-affiché si ≥1 card `attention` présente, en tête du bloc cards.

#### CH-06.4 — Test sur 10 questions T2
- **Statut** : EN ATTENTE — nécessite restart app + bench T2 réel sur le KG actuel.
- **Sera fait après le restart à la fin du bench actuel (CH-30.7)**.

### CH-07 — Verify V1 — refacto via pipeline search
- **Statut** : TODO
- **Effort** : 1.5j
- **Fichiers** : `verification_service.py` uniquement
- **Quoi** : Le moteur `evidence_matcher` est cassé (recherche dans Neo4j claims au lieu de Qdrant, prompt générique, fallback Ollama). Refacto = remplacer `assertion_splitter → evidence_matcher → comparison_engine` par : pour chaque assertion, `search(assertion_text) → synthèse → comparer assertion vs synthèse`.
- **Pourquoi** : 13/15 assertions classées "confirmed" alors que 6 contiennent des erreurs volontaires. Le pipeline `search.py` actuel est optimisé (faithfulness 79%, tension 100%) — autant le réutiliser.
- **Acceptation** : sur le doc de test Verify, 6/6 erreurs volontaires détectées comme "contredit" ou "nuancé".

### CH-08 — Verify V2 — Document Review Word
- **Statut** : TODO (dépend de CH-07)
- **Effort** : 3j (backend ~2j, frontend ~1j)
- **Quoi** : Upload `.docx` → analyse paragraphe par paragraphe → `.docx` annoté avec commentaires natifs Word, 3 niveaux (assertion confirmée/nuancée/contredite). `python-docx` déjà installé, structures V3 (AssertionVerdict, DocumentReviewResult) déjà définies.
- **Pourquoi** : Use case Armand direct — un compliance officer relit un règlement annoté. Différenciateur fort vs ChatGPT.
- **Acceptation** : upload d'un règlement test → `.docx` retourné avec ≥1 commentaire par paragraphe, ouvrable dans Word natif.

### CH-09 — RAGAS faithfulness — double scoring
- **Statut** : DONE (code, 2026-05-03 — validation au prochain run RAGAS)
- **Effort réel** : ~45 min (vs 6-9h estimé — la piste 2 `faithfulness_total` existait déjà à 80%, restait à brancher DeepInfra + runtime V2)
- **Diagnostic état avant** : la piste 2 (chunks + graph_context_text) était déjà implémentée dans `ragas_diagnostic.py:381-431`, mais 3 bloquants :
  - Juge RAGAS = OpenAI gpt-4o-mini par défaut (viole politique "pas OpenAI/Anthropic")
  - Embeddings RAGAS = OpenAI text-embedding-3-small (idem)
  - API utilisée = `/api/search` V1.1 (pas runtime V2 anchor-driven)
- **Livré** :
  - `_get_ragas_providers()` refondu — **provider défaut = `deepinfra`** (Qwen2.5-72B-Instruct via API OpenAI-compat), fail-fast si `DEEPINFRA_API_KEY` manque. Mode `openai` reste disponible mais explicite (legacy).
  - **Embeddings défaut = e5-large local** (multilingual-e5-large via langchain HF) — fallback OpenAI uniquement si `RAGAS_JUDGE_PROVIDER=openai`. Le mode deepinfra REFUSE le fallback OpenAI.
  - `_build_v2_graph_context_text(response)` (nouveau) — synthétise le `graph_context_text` à partir de la réponse runtime V2 (claims + conflicts + lifecycle resolution + insight_hints) pour que `faithfulness_total` reflète bien la qualité KG V2.
  - `_call_runtime_v2_api()` (nouveau) — appelle `/api/runtime_v2/answer`, retourne format compatible RAGAS pipeline (contexts = claims top-K, answer = synthesized_answer, graph_context_text synthétique).
  - `_collect_one()` étendu — toggle env `RAGAS_USE_RUNTIME_V2=true` pour basculer V1.1 → V2.
  - La piste 2 `faithfulness_total` (chunks + KG) était déjà là — maintenant activable depuis runtime V2.
- **Validation** : `python -m py_compile` OK. À tester au prochain run RAGAS via :
  ```
  RAGAS_USE_RUNTIME_V2=true RAGAS_JUDGE_PROVIDER=deepinfra docker-compose exec app python -m benchmark.evaluators.ragas_diagnostic --profile quick
  ```
- **Acceptation à valider** : `faith_total` ≥ baseline RAG pur sur 100q ; `faith_chunks` documenté séparément (déjà visible dans frontend `/admin/benchmarks` onglet RAGAS — page.tsx:437-439).

---

## 📋 Définis mais non commencés

### CH-10 — Atlas global_reading_order cross-dossiers
- **Statut** : TODO
- **Effort** : 1-2j
- **Quoi** : Tour guidé "lecture continue" du corpus complet, qui chaîne les NarrativeTopics dans un ordre pédagogique (vs aujourd'hui : navigation Domain → Root → Topic isolés).
- **Pourquoi** : Atlas narratif livré 01/05 répond à "je veux explorer un dossier". Manque "je veux comprendre l'ensemble du corpus en 2h". Surface différenciante face à Copilot.
- **Acceptation** : sur le corpus aerospace, `global_reading_order` retourne 60 NarrativeTopics chaînés cohérents validés à la lecture par Fred.

### CH-11 — Frontend admin ClaimFirst Settings
- **Statut** : TODO
- **Effort** : 1.5j
- **Quoi** : Page `/admin/claimfirst-settings` avec sliders pour les 8-12 paramètres ClaimFirst (seuils contrôle, batch size, max parallel, seuils résolveur). Persistance dans `tenant_settings` Postgres.
- **Pourquoi** : Aujourd'hui tout est codé en dur ou dans `.env`. Pour onboarder un nouveau tenant (Armand) il faut éditer le code. Multi-tenant = bloqué sans cette UI.
- **Acceptation** : ajustement d'un seuil via UI → import suivant utilise la nouvelle valeur sans restart.

### CH-12 — Externaliser listes hardcodées non-critiques
- **Statut** : DONE (2026-05-03)
- **Effort réel** : ~25 min (vs 0.5j estimé)
- **Périmètre** : 6 listes "détection linguistique" (priorité HAUTE de l'audit) externalisées
- **Livré** :
  - `config/detection_keywords.yaml` (nouveau) — 6 listes avec section `tenant_overrides` :
    - `tension_keywords` (23) — divergen, contradict, however, en revanche, …
    - `ignorance_keywords` (21) — pas d'information, je ne sais pas, not found, …
    - `correction_keywords` (21) — en realite, contrairement, actually, …
    - `temporal_keywords` (19) — années 2021-2025, evolution, version, mise a jour, …
    - `contradiction_keywords` (8) — sous-ensemble de tension, focus pour T2 scoring
    - `idk_phrases` (13) — fusion des `idk_phrases` (primary_metrics) + `idk_patterns` (rule_based_judge)
  - `src/knowbase/config/detection_keywords.py` (nouveau) — loader Pydantic-style, dataclass `DetectionKeywords` immuable, singleton process-level avec cache par tenant + `reload_detection_keywords()` pour les tests
  - **4 fichiers refactorés** :
    - `benchmark/evaluators/t2t5_diagnostic.py` — `TENSION_KEYWORDS` désormais alias depuis le loader
    - `benchmark/evaluators/robustness_diagnostic.py` — `IGNORANCE_KEYWORDS`, `CORRECTION_KEYWORDS`, `TEMPORAL_KEYWORDS` aliases
    - `benchmark/evaluators/primary_metrics.py` — `contradiction_keywords` + `idk_phrases` lazy-load
    - `benchmark/evaluators/rule_based_judge.py` — `idk_patterns` lazy-load (alias sur `idk_phrases`)
- **Validation** :
  - Tous les modules compilent
  - Smoke test loader : 23/21/21/19/8/13 items chargés correctement (rétrocompat 100%)
  - Acceptance criteria respectée : `grep "^TENSION_KEYWORDS\s*=" benchmark src` retourne uniquement `TENSION_KEYWORDS = list(_get_dk()...)` (alias, pas hardcode)
- **Reste hors scope** (audit complet 55 listes) : 49 listes restantes, dont :
  - **Critiques** (4) — stopwords/BM25/ENTITY_STOPLIST déjà migrés vers IDF dynamique (CH antérieur)
  - **Moyennes** (7) — relations KG `SEMANTIC_RELATION_TYPES`, `EXCLUDED_RELATION_TYPES`, `CANONICAL_PREDICATES` (avec **3 doublons** à dédup) — chantier dédié si refonte schéma
  - **Basses** (~38) — patterns spécifiques entity_extractor, discursive, etc. — laissés hardcodés (faible impact multilingue, plus stables).

### CH-13 — Answer Gap Detector
- **Statut** : DONE (code, 2026-05-03 — validation acceptance après restart + analyse run T6)
- **Effort réel** : ~30 min (vs 1j estimé — réutilise corpus_stats IDF déjà en prod)
- **Livré** :
  - `src/knowbase/runtime_v2/answer_gap_detector.py` (nouveau) :
    - `extract_specific_terms(question)` → tokens IDF ≥ 2.5 OU hors-corpus ≥ 4 chars
    - `compute_gap_score(specific_terms, retrieved_text)` → (gap, found, missing)
    - `classify(gap_score)` → ANSWERABLE (<0.25) / UNCERTAIN (0.25-0.50) / UNANSWERABLE (≥0.50)
    - `detect_answer_gap(question, retrieved_text)` API publique
  - `src/knowbase/runtime_v2/models.py` — `PipelineResponse.answer_gap_score`, `answer_gap_classification`, `answer_gap_missing_terms`
  - `src/knowbase/runtime_v2/pipeline.py` — branchement post-retrieval, avant synthèse
  - `src/knowbase/runtime_v2/insight_hints.py` — bonus card "Information potentiellement absente" / "Couverture incertaine" (priority=1)
  - `src/knowbase/api/routers/runtime_v2.py` — log structuré `answer_gap_score` + `answer_gap_classification`
- **Réutilise** : `knowbase/common/corpus_stats.py` (IDF dynamique mutualisé existant)
- **Validation** : tous les modules compilent. Activation runtime nécessite restart app.
- **Acceptation à valider après restart** : sur 25 questions unanswerable T6 (catégorie `unanswerable` du benchmark `aero_t6_robustness.json`), mesurer le recall UNANSWERABLE classification ≥ 72% sans dégrader les ANSWERABLE des autres tasks.

### CH-14 — HALT/EPR Logprob Entropy Detection
- **Statut** : DONE (code, 2026-05-03 — calibration empirique du seuil différée à un run dédié)
- **Effort réel** : ~30 min (vs 1-2h estimé)
- **Livré** :
  - `src/knowbase/runtime_v2/entropy.py` (nouveau) — `compute_avg_entropy(logprobs_content)` (Shannon sur top_logprobs re-normalisés) + `is_low_confidence(entropy, threshold=1.5)` + constante `LOW_CONFIDENCE_ENTROPY_THRESHOLD=1.5` (à calibrer)
  - `src/knowbase/runtime_v2/llm_client.py` — méthode `chat_completion_with_meta(logprobs=True, top_logprobs=5)` ; `chat_completion()` reste rétrocompatible (délègue à _with_meta)
  - `src/knowbase/runtime_v2/synthesis.py` — `ResponseSynthesizer.capture_logprobs=True` par défaut, stocke `last_metrics = {entropy, n_tokens_with_logprobs, provider, model}` après chaque synthèse
  - `src/knowbase/runtime_v2/models.py` — `PipelineResponse.synthesis_entropy: Optional[float]` + `synthesis_low_confidence: bool`
  - `src/knowbase/runtime_v2/pipeline.py` — propage `synthesizer.last_metrics["entropy"]` dans la réponse
  - `src/knowbase/runtime_v2/insight_hints.py` — bonus card "🔍 Confiance faible" auto si `synthesis_low_confidence=True` (priority=1)
  - `src/knowbase/api/routers/runtime_v2.py` — log structuré ajoute `synthesis_entropy` + `synthesis_low_confidence`
- **Validation** : tous les modules compilent. Activation runtime nécessite restart app.
- **Calibration** : le seuil 1.5 est une estimation. Calibration empirique = run sur 25 questions unanswerable (T6), mesure entropy + comparaison avec verdict juge → ajuster seuil pour Pearson ≥ 0.5. À faire en CH-14b séparé après le run benchmark complet.

### CH-15 — Health Toolbox scripts
- **Statut** : DONE (README catégoriel livré, 2026-05-03 — déplacement physique différé pour validation user)
- **Effort réel** : ~25 min (vs 0.5j estimé — approche conservatrice : visibilité sans déplacement)
- **Livré** :
  - `app/scripts/README.md` étendu (~250 lignes, vs 177 avant) — couvre les **117 scripts** Python avec catégorisation systématique :
    - 🩺 **Diagnostic** (13 scripts) — audit lecture seule
    - 📊 **Benchmark** (5)
    - 🔧 **Correctif** (12) — fix/cleanup/archive (modifient KG)
    - ♻️ **Backfill / Rebuild** (22) — recalcul propriété sans réingestion
    - 🔄 **Migration** (8) — one-shot post-refonte
    - 🛠️ **Setup / Infra** (9)
    - 🧱 **Build / Compute** (30) — pipelines enrichissement
    - 🧪 **Tests dev** (15) — smokes ad-hoc
    - 🚀 **POC / Demo** (3)
  - **Section "Candidats archive"** explicite : 12 scripts identifiés comme legacy/redondant (ex: `generate_atlas.py` POC, `extract_question_signatures.py` v1, `backfill_relations_c4/c6.py` legacy V1.1, migrations one-shot exécutées)
  - Workflows typiques documentés : reset Proto-KG / backup / audit quotidien / backfill post-CH-02 / build atlas
- **Approche conservatrice** : pas de déplacement physique pour ne pas casser de références (Docker, kw.ps1, doc, post_import worker). Le déplacement vers `_archive_done/`, `_dev_tests/`, `poc/` se fera après validation user de la liste candidate.
- **Reste optionnel** (CH-15b, ~30 min) : déplacer physiquement les 12 candidats archive après validation user.

### CH-16 — Exact Answer Gate V1
- **Statut** : TODO
- **Effort** : 2j
- **Quoi** : Gate déterministe pré-LLM pour 3 familles de questions à réponse structurée : EXACT_NUMERIC (prix, %, durée), EXACT_IDENTIFIER (code transaction, SAP Note), VERSION_DATE. Si NER + heuristiques ne trouvent pas la forme attendue dans les chunks → réponse "information non disponible" sans appel LLM.
- **Pourquoi** : Complémentaire à CH-13 Answer Gap Detector. Gap couvre questions ouvertes ; Gate couvre questions fermées. Hallucination 7/8 sur EXACT_NUMERIC → bloquant pour Armand.
- **Acceptation** : sur 8 questions unanswerable EXACT_NUMERIC du benchmark, 7+ rejetées proprement.

---

## 🐛 Bugs

### CH-17 — Facet linkage 27% biomédical (#70)
- **Statut** : BLOCKED — nécessite corpus biomédical actif
- **Effort** : 1j dev + 0.5j calibration
- **Quoi** : Sur le corpus biomédical, seuls 27% des facets sont liés à un claim. 3 tentatives ont empiré (15.4%, 21.2%). Piste recommandée : embedding similarity sur `facet.canonical_question` (déjà persisté).
- **Pourquoi** : Sans facets liés, le retrieval N3 (par question canonique) est aveugle sur ce corpus. Bloque toute démo médicale.
- **Acceptation** : ≥60% facets liés sur corpus biomédical, sans régresser le corpus SAP/aerospace.

---

## 🔍 Investigations actives

### CH-18 — Instabilité juge LLM benchmarks T2/T5
- **Statut** : IN_PROGRESS
- **Effort** : 0.5-1j selon option
- **Quoi** : `gpt-4o-mini` non-déterministe même `temperature=0` : 37%-84% sur le même corpus. Options : (a) changer pour Claude Haiku, (b) hybridation Qwen+Claude (étendre le pattern du benchmark global à T2/T5), (c) auto-cohérence (3 runs + vote).
- **Pourquoi** : Sans juge stable, on ne peut pas mesurer une régression. Critique pour valider toute évolution V2.
- **Acceptation** : 3 runs consécutifs sur le même corpus → écart < 5pp.

### CH-19 — KG Quality régulatoire P5 (entités génériques)
- **Statut** : TODO
- **Effort** : 1j
- **Quoi** : Sur le corpus régulatoire (71 docs GDPR/AI Act/CCPA), P5 = entités trop génériques ("data", "user", "system") créent du bruit. P1-P4, P6 résolus. Solution : seuil IDF pour rejeter les sub-génériques + listes domain pack.
- **Pourquoi** : Atlas regulatory n'est pas exploitable car les Roots sont des entités génériques sans pouvoir de structuration.
- **Acceptation** : Atlas regulatory affiche des Roots métier (RGPD, Privacy, AI Act) au lieu de "data", "user".

### CH-20 — Negative Rejection — implémentation
- **Statut** : TODO (analyse rédigée)
- **Effort** : 1j
- **Quoi** : Coverage Score pré-synthèse — calculer un score de couverture des chunks/claims pour la question, et si < seuil, retourner directement "information insuffisante" sans appeler le LLM.
- **Pourquoi** : Complémentaire au gate exact (CH-16). Couvre les cas où l'info est "à moitié là".
- **Acceptation** : sur questions UNCERTAIN, taux d'abstention correct ≥ 60%.

### CH-21 — Étape qualité OSMOSIS — chunks fragiles
- **Statut** : TODO
- **Effort** : 1-1.5j
- **Quoi** : `chain_coverage` 52.3% (-18pp) = 48% des claims ne sont pas reliés à leur chunk source. Cause probable : merge de chunks brise les liens claim ↔ source dans le rechunker.
- **Pourquoi** : Faithfulness dépend directement du chain_coverage. Sans fix, le retrieval cite des chunks reconstitués qui ne contiennent plus le verbatim original.
- **Acceptation** : `chain_coverage` ≥ 75% post-fix, faithfulness améliorée.

### CH-22 — Pollution KG mode DIRECT — gap enrichissement
- **Statut** : IN_PROGRESS (amorcé, B' Override partiel)
- **Effort** : 1-1.5j à finaliser
- **Quoi** : En mode DIRECT, le KG est sous-exploité. On injecte certains signaux (tensions) mais pas tout (perspectives, narratives). À étendre.
- **Pourquoi** : DIRECT = mode par défaut. Si le KG n'apporte rien en DIRECT, OSMOSIS est dégradé en RAG pur sur le golden path.
- **Acceptation** : sur 50 questions DIRECT, ≥30% reçoivent un signal KG (perspective ou tension) injecté.

### CH-23 — 199 mots tronqués (8%) — hard cut sans sentence/line break
- **Statut** : TODO
- **Effort** : 0.5j
- **Fichiers** : `rechunker.py` boundary detection
- **Quoi** : 199 chunks ont un hard-cut au milieu d'un mot après le rechunker. Audit avait pointé un sentence/line break à respecter avant de couper.
- **Pourquoi** : Faithfulness pénalisée par les mots tronqués (LLM ne peut pas citer un mot incomplet). 8% = significatif.
- **Acceptation** : 0 chunk avec hard-cut middle-of-word post-fix sur le corpus actuel.

---

## 🎨 UX/UI

### CH-24 — UI Raisonnement étendu
- **Statut** : TODO
- **Effort** : 2j frontend
- **Quoi** : Couvrir DIRECT/AUGMENTED, silences (le système n'a rien dit), tensions cross-doc dans la trace de raisonnement. ADR existe (`chantiers/2026-04-29_CH-24_ADR_RAISONNEMENT_UI.md`).
- **Pourquoi** : Aujourd'hui la trace ne montre que CROSS_DOC. Le compliance officer doit voir POURQUOI le système n'a rien dit sur un aspect.
- **Acceptation** : sur 10 questions variées, la trace explique le mode choisi + les signaux écartés.

### CH-25 — Multi-preset themes — finalisation
- **Statut** : IN_PROGRESS (foundation amorcée)
- **Effort** : 0.5j
- **Quoi** : Switcher header pour basculer Dark Elegance ↔ Fusion. Foundation Chakra déjà en place (`PresetThemeProvider`). Reste : persistance préférence utilisateur + animation de transition.
- **Pourquoi** : Demandé par user. Présentation Armand = Dark Elegance ; démo grand public = Fusion.
- **Acceptation** : switch header → thème change instantanément, persiste après reload.

### CH-26 — N5 side-by-side claims en tension
- **Statut** : TODO
- **Effort** : 1j frontend
- **Quoi** : Vue dédiée pour comparer 2 claims contradictoires côte à côte (texte source verbatim, doc, date, role). Déclenchée depuis Insight Card "⚠️ Tension détectée".
- **Pourquoi** : Use case Armand direct — voir les divergences réglementaires côte à côte. Audit-friendly.
- **Acceptation** : page `/tensions/[id]` affiche les 2 claims + métadonnées + doc source cliquable.

### CH-27 — N1 export PDF de la trace
- **Statut** : TODO
- **Effort** : 1.5j
- **Quoi** : Export PDF de la conversation chat + trace de raisonnement + sources. Reproduction fidèle du rendu écran.
- **Pourquoi** : Compliance-ready. Un audit doit pouvoir conserver la preuve de la réponse + ses sources.
- **Acceptation** : bouton "Exporter PDF" → fichier PDF lisible avec sources cliquables.

### CH-28 — Sources cliquables avec nom lisible
- **Statut** : TODO (sous-ensemble de CH-05)
- **Effort** : 0.5j (peut être traité dans CH-05)
- **Quoi** : Aujourd'hui les sources s'affichent en hash brut (`027_SAP_S4HANA_2023_Security_Guide_c160af0e`). Mapper vers nom lisible (`Security Guide 2023, p.42`) + lien vers viewer doc.
- **Pourquoi** : Problème 6 du diagnostic chat. UX inacceptable en l'état.
- **Acceptation** : 0 hash visible dans le rendu chat sur 20 questions.

---

## 🧪 Benchmarks

### CH-30 — Refonte benchmarks V2 (RAGAS, T1/T2/T5/T6/T7, Robustesse)
- **Statut** : IN_PROGRESS (démarré 2026-05-03)
- **Effort total** : ~5-6j (généralisation phase par phase, validation user à chaque livraison)
- **Contexte** : architecture anchor-driven V2 + lifecycle relations + classifier 12-types + response modes externalisés ont profondément modifié le pipeline de réponse. Les questions historiques (SAP, regulatory) ne reflètent plus le périmètre/comportement actuel.
- **Corpus** : aerospace seul (corpus actuellement ingéré, 17 docs : 11 CS-25 + 6 dual-use EU). Le regulatory (71 docs) n'est plus ingéré — le bench se fait sur ce qui est en prod.
- **Méthode** : Claude lit les docs (PDF + KG claims pré-extraits) et rédige les questions. Pas de génération LLM aveugle.
- **Volumétrie cible** : 250-300 questions au total
- **Tasks** :
  - **T1** Provenance (~50q) — citation directe, 1 doc
  - **T2** Contradictions (~40q) — vrais conflits + tensions cross-doc
  - **T5** Cross-doc (~30q) — chains nécessitant ≥2 docs
  - **T6** Robustness (~120q) — 10 catégories
  - **T7** V2 anchor-driven (~50q) — **NOUVEAU** : lifecycle queries, anchor applicability, distinction LIFECYCLE vs CONFLICT

#### CH-30.0 — Inventaire KG + cadrage format
- **Statut** : IN_PROGRESS (2026-05-03)
- **Effort** : 0.5j
- **Quoi** : extraire les claims clés par doc, lifecycle relations, top entities, anchors. Vérifier format JSON attendu par les runners (`run_osmosis_v2.py`). Output : doc inventaire = source de vérité pour la génération.

#### CH-30.1 — Génération T1 Provenance (~50q)
- **Statut** : TODO
- **Effort** : 1j

#### CH-30.2 — Génération T2 Contradictions (~40q)
- **Statut** : TODO
- **Effort** : 0.75j

#### CH-30.3 — Génération T5 Cross-doc (~30q)
- **Statut** : TODO
- **Effort** : 0.75j

#### CH-30.4 — Génération T6 Robustness (~120q)
- **Statut** : TODO
- **Effort** : 1.5j

#### CH-30.5 — Génération T7 V2 anchor-driven (~50q) **NOUVEAU**
- **Statut** : TODO
- **Effort** : 1j
- **Quoi** : task spécifique post-V2 — lifecycle queries (SUPERSEDES/EVOLVES_FROM/REAFFIRMS), anchor-based applicability ("règles applicables à un avion certifié en 2024"), distinction LIFECYCLE vs CONFLICT, validity dates héritées.

#### CH-30.6 — Validation runs + intégration runners
- **Statut** : TODO
- **Effort** : 0.5j

#### CH-30.7 — Re-run benchmarks complets
- **Statut** : IN_PROGRESS (lancé 2026-05-03 10:44 — 290q sans burst, ETA ~4-5h)
- **Effort** : 0.5j (compute) + analyse résultats

#### CH-30.8 — Intégration frontend admin/benchmarks pour T1 + T7 (NOUVEAU)
- **Statut** : DONE (code, 2026-05-03 — en attente restart app pour activation runtime)
- **Effort réel** : ~1.5h (vs 1.5-2j estimé — choix simplificateur d'un tab unique "Aerospace V2" au lieu de 2 tabs T1/T7 séparés)
- **Approche pragmatique** : un seul tab "Aerospace V2" qui couvre les 5 tasks (T1/T2/T5/T6/T7) avec sélecteur de task au lancement, plutôt que 2 tabs T1/T7 dédiés. Les onglets RAGAS/Contradictions/Robustesse historiques sont conservés inchangés.
- **Livré** :
  - **Backend** : `benchmark/evaluators/aero_v2_diagnostic.py` (job RQ qui orchestre `run_osmosis_v2.py` + `judge_v2.py` en sub-process, suit la progression via Redis `osmose:benchmark:aero_v2:state`).
  - **Backend** : `src/knowbase/api/routers/benchmarks_aero_v2.py` (4 endpoints : POST `/run`, GET `/progress`, GET `` (liste), GET `/{filename}`, DELETE `/{filename}`). Préfixe `/api/benchmarks/aero_v2`.
  - **Backend** : `src/knowbase/api/main.py` modifié — `include_router(benchmarks_aero_v2.router)`.
  - **Frontend** : `page.tsx` étendu avec 1 tab "Aerospace V2" (icône FiCompass, accent teal `#14b8a6`), composant `AeroV2Tab`, type `AeroV2Report`, intégration polling/launch via le `LaunchPanel` partagé. Le `selectedProfile` est mappé en `task` pour l'API aero_v2.
  - **Frontend** : `LaunchPanel.tsx` corrigé (couleurs hardcodées au lieu de `var(--xxx)` qui était overridé par le thème actif → titre "Lancer un benchmark" + bouton "Lancer tout" redeviennent lisibles).
- **Validation** : Python compile OK ; TS sans nouvelle erreur (les erreurs TS pré-existantes lignes 324-326 et 899 sont conservées hors scope).
- **Activation runtime** : nécessite `docker restart knowbase-app` une fois le bench actuel terminé (CH-30.7), puis tester un run via le tab.
- **Reste** (déféré, hors scope CH-30.8) : adapter `OverviewTab` pour afficher 5 cards (ajout d'une card Aerospace V2 récap) — utile mais non bloquant.

#### CH-30.9 — Brancher bench V2 sur les 3 onglets existants
- **Statut** : DONE (2026-05-03)
- **Quoi** : RAGAS / Contradictions / Robustesse interrogent désormais directement `runtime_v2/answer` au lieu de l'ancien `/api/search` V1.1.

#### CH-30.10 — Robustness fallback LLM-juge pour catégories T7
- **Statut** : DONE (2026-05-03)
- **Quoi** : Mapping T7 → T6 keyword fallback ajouté pour les catégories anchor lifecycle.

#### CH-30.11 — Diagnostics t2t5 + robustness → runtime_v2/answer
- **Statut** : DONE (2026-05-03)

#### CH-30.12 — RAGAS_USE_RUNTIME_V2 par défaut
- **Statut** : DONE (2026-05-03) — env activé en prod.

#### CH-30.13 — Frontend score N/A si proactive_count=0
- **Statut** : DONE (2026-05-03)

#### CH-30.14 — Supprimer fallback V1.1 dans diagnostics
- **Statut** : DONE (2026-05-03)

#### CH-30.15 — T2/T5 scorer V2 via LLM-juge Prometheus
- **Statut** : DONE (2026-05-04)
- **Note** : remplacé par Llama-3.3-70B en CH-34 suite audit underjudging Prometheus.

#### CH-30.16 — Robustness scorers V2 (Prometheus puis Llama-3.3-70B)
- **Statut** : DONE (2026-05-04)

#### CH-30.17 — Adoucir prompt synthèse V2 (prompt-induced hallucination)
- **Statut** : DONE (2026-05-04)

#### CH-30.18 — Fix RAGAS NaN propagation moyennes
- **Statut** : DONE (2026-05-04)
- **Quoi** : `math.isnan` filter sur les scores RAGAS pour éviter pollution moyennes par valeurs manquantes.

### CH-31 — Retrieval V2 enrichi (decomposer + HyDE + LLM-filter)
- **Statut** : DONE (2026-05-04)
- **Sous-chantiers** : CH-31.A query_decomposer branché, CH-31.B enrichi (answer_shape + HyDE + KG subject + term_lookup), CH-31.C LLM-filter post-retrieval, CH-31.D validation cross-domain.

### CH-32 — Verification post-synth (premise + NLI judge)
- **Statut** : DONE (2026-05-04)
- **Sous-chantiers** : CH-32.A premise validator (logical-form + KG check), CH-32.B faithfulness NLI judge post-synthesis (mDeBERTa-v3-xnli-multilingual).

### CH-33 — Optimisation latence pipeline V2 (model routing + max_tokens)
- **Statut** : DONE (2026-05-04)

### CH-34 — Audit retrieval failures + judge calibration (post-bench 04/05)
- **Statut** : DONE (2026-05-04)
- **Quoi** : Identifié Prometheus underjudging 70% des cas. Migré juge bench → Llama-3.3-70B-Instruct via DeepInfra.

### CH-35 — Sprint A : Retrieval overhaul (Hybrid + filter + re-rank)
- **Statut** : DONE (2026-05-04/05)
- **Sous-chantiers** : CH-35.A1 hybrid BM25+vector RRF, CH-35.A2 LLM-filter min_keep adaptatif + bypass factuel, CH-35.A3 Subject Resolver tie-breaker par anchor, CH-35.A4 cross-encoder re-rank top-K (BGE-reranker-v2-m3).
- **CH-35.A5** Query decomposer aggressive mode (multi_hop / conditional) : SUPERSEDED par V4 facts-first.

### CH-36 — Sprint B : Synthèse anti-hallucination
- **Statut** : SUPERSEDED par CH-39 puis CH-41 (V4 facts-first)

### CH-37 — Sprint C : Régulatoire guardrails
- **Statut** : SUPERSEDED par CH-41 (verifier cascade reporté en tranche 6 V4)

### CH-38 — Sprint D : Calibration finale + Domain Pack
- **Statut** : SUPERSEDED par CH-40 (Sprint S0 V4 calibration) + CH-41.M (contrat Domain Pack extension)

### CH-39 — Refonte runtime_v3 minimaliste (5 stages)
- **Statut** : DONE (2026-05-05)
- **Effort réel** : ~1 jour
- **Quoi** : Pipeline V3 minimaliste 5 stages, 250 lignes vs 951 V2. Hybrid retrieve + cross-encoder rerank GPU + agentic synthesis 1-LLM-call + NLI mDeBERTa multilingue + regen conditionnel. 0 listing métier hardcodé.
- **Sous-chantiers** :
  - CH-39.1 Setup mDeBERTa-v3-xnli multilingue (HHEM-2.1 incompatible transformers 5.x)
  - CH-39.2 Agentic synthesis prompt v4 + output JSON
  - CH-39.3 runtime_v3/pipeline.py
  - CH-39.4 API endpoint `/api/runtime_v3/answer`
  - CH-39.5 Validation bench v2 vs v3 (Robust V3_FINAL3 0.545 vs V2 ABC1 0.495 = +5pp)
- **Pipeline V3 livré 2026-05-05 matin**, sert de baseline V3 pour Sprint S0 V4.

### CH-40 — Sprint S0 V4 : Calibration & Gold-set
- **Statut** : DONE (2026-05-05/06)
- **Effort réel** : 1 jour (vs 1 semaine estimé — gold-set bootstrap auto + structured metrics + scripts d'analyse)
- **Source** : `doc/ongoing/chantiers/2026-05-05_CH-40_S0_BASELINE.md` (504 lignes, self-contained), `doc/ongoing/chantiers/2026-05-05_CH-40_S0_DISAGREEMENT_ANALYSIS.md`, `doc/ongoing/chantiers/2026-05-05_CH-40_S0_SANITY_CHECK.md`
- **Sous-chantiers** :
  - CH-40.0 Construction gold-set v4 (97q brownfield stratifiées + criterion-level annotations bootstrap Qwen-72B + review Claude)
  - CH-40.1 Activation RAGAS FactualCorrectness (extract_reference étendu pour gold-set v4 + signature `ascore` corrigée + profile `gold_v4` + 3e MetricBar UI)
  - CH-40.2 Métriques structurées par type (item_level_recall, exact_match_identifiers, citation_presence_rate, coverage_state_accuracy) — CRITIQUE garde-fou anti-overfit
  - CH-40.3 Dépose keyword scorer fallback + retry juge LLM exponential backoff
  - CH-40.4 Calibration Pearson juge (verdict FAIL : global 0.46, false_premise -0.94, unanswerable -0.79 = bug schéma gold-set, pas du juge)
  - CH-40.5 Bench baseline V3 (V3_S0_BASELINE Robust 0.531 / V3_S0_GOLD4 RAGAS faith 0.536 / ctx 0.688 / factual 0.368) + doc `chantiers/2026-05-05_CH-40_S0_BASELINE.md`
  - CH-40.6 Logging désaccords judge vs structured (31.7% judge_overscored documentés top-20)
  - CH-40.7 Sanity check externe Fred (9q FR pour verdict ternaire OK/KO/bizarre)
- **Bilan** : H1 réfutée (factual_correctness < faithfulness), gate Pearson en attente de correction schéma gold-set false_premise/unanswerable. Pivot architectural V4 facts-first décidé post-S0.

---

## 🚀 V4 Facts-First (NEW post-pivot 06/05/2026)

### CH-41 — V4 Facts-First : Tranches 1-5 + couches transverses + leviers latence
- **Statut** : DONE (2026-05-07, pipeline V4 stabilisé pour 5 types structurels + leviers 1+2+3 retenus)
- **Effort réel** : 1 jour livraison Tranches + 1 jour leviers latence (vs estimation initiale 4-5 sem)
- **ADR** : `doc/ongoing/chantiers/2026-05-06_CH-41_ADR_FACTS_FIRST.md` (validé 3 voix Fred + Claude + ChatGPT)
- **Cible atteinte** : pipeline facts-first complet sur les 5 types structurels (list / factual / temporal / comparison / causal) + 2 spéciaux (unanswerable / false_premise via routing)
- **Bilan** : routing 82% sur 5 types (LLM zero-shot Qwen-72B), verifier déterministe 100%, 0 hallucination rejetée. p50 list 44s, factual 26.5s. Leviers latence livrés (workers=4 default, timeouts 120s, mode=single list). Llama-Turbo Structurer et HHEM-2.1 Channel 2 abandonnés après tests live (résultats catastrophiques abstention systématique / régression latence-qualité).
- **Doc bilan** : `doc/ongoing/chantiers/2026-05-07_BENCH_GLOBAL_V4_FINAL_ANALYSIS.md` + `2026-05-07_BENCH_POST_LEVIERS_LATENCE.md`

#### CH-41.M — Verrouillage contrats Facts-First (BLOQUANT, NEW review ChatGPT)
- **Statut** : IN_PROGRESS (2026-05-06)
- **Effort** : 2-3 jours
- **Pourquoi BLOQUANT** : réserve forte ChatGPT — « verrouiller contrats Structured Evidence Package commun + Domain Pack extension AVANT de coder, sinon refaire les fondations à tranche 3 (temporal/comparison) ».
- **Livrables** :
  1. `schemas/facts_first_v1_common.json` — socle commun figé (champs partagés tous types : `schema_version`, `primary_type`, `answerability`, `coverage_state`, `source`, `confidence`, `language`, `extracted_at`, `extraction_model`)
  2. `domain_packs/_template/facts_first_extensions.yaml` — format YAML extension Domain Pack avec règle invariante `maps_to` core minimal universel
  3. Doc mode EAV abstention structurée (D-FF11) avec disclaimer explicite, **pas chemin généraliste** (alerte si > 10% trafic EAV)
  4. Cadrage panel stress-test 100q (D-FF12) = couverture typologique seulement, pas qualité
- **Validation** : Fred + relecture LLM tiers (Claude web, ChatGPT) avant unlock CH-41.0

#### CH-41.0 — Pré-requis Tranche 1 (gold-sets + panel stress-test)
- **Statut** : DONE (2026-05-06, tous livrables A+B+C+D+E livrés en 1 jour)
- **Effort** : 1 jour réel (vs 1 semaine estimée)
- **Livrables** :
  - **A+B** ✅ DONE (2026-05-06) : `gold_set_v4.json` enrichi de 20 → **55 list questions** / **251 items annotés** (cibles 50/250 atteintes). Méthode : formulation manuelle Claude depuis claims Neo4j (Cypher direct), PAS de LLM bootstrap (rejet feedback Fred « usine à gaz »). IDs `GOLD_v4_LIST_NEW_098` à `132`. Couverture : EU 2021/821 (autorisations, scope, exemptions, annexes, transit, obligations EM, definitions Article 2), CS-25 amdt 28 (take-off, landing, ice protection, AMC, icing exclusions, weight/balance), Annex I dual-use 2024/2547 (categories, machine tools 2B001, entry codes, exclusion notes).
  - **C** ✅ DONE (2026-05-06) : `scripts/build_panel_stress_test_100q.py` exécuté + hotfix `_fix_panel_hr_and_lang.py`. **124 questions** (médical 20, legal 22, software 20, hr 20, product 22, edge 20). Distribution : factual 25, list 21, temporal 17, comparison 16, causal 15, unanswerable 11, false_premise 4, edge non-typés 15. Langs : 73 fr / 51 en. Cible HFF5 ≥ 95% : à mesurer en CH-41.1.
  - **D** ✅ DONE (2026-05-06) : `scripts/fix_gold_set_v4_false_premise_unanswerable.py` exécuté. 10/10 questions (5 false_premise + 5 unanswerable) annotées avec signaux sémantiques multilingues domain-agnostic. Champs ajoutés : `correct_premise_rejection_signals[]` / `unanswerable_explicit_signals[]` + `expected_response_summary` + `_phase_d_metadata`.
  - **E** ✅ DONE (2026-05-06) : baseline factual mesuré sur 25q factual du gold-set v4. **factual_correctness mean = 0.361** (min 0.0, max 1.0, n=25/25 valides). Cohérent V3_S0_GOLD2 (0.368, delta -0.007 = variance). Gate D-FF13 = ≥ 0.361 (variance ±0.05 → plancher 0.311). Persisté `data/benchmark/calibration/rag_baseline_factual.json`. Doc : `doc/ongoing/chantiers/2026-05-06_CH-41_RAG_BASELINE_FACTUAL.md`.

#### CH-41.1 — QuestionAnalyzer (composant [A])
- **Statut** : DONE (2026-05-06, scope ré-cadré 5 types structurels — voir doc résultats)
- **Module** : `src/knowbase/facts_first/question_analyzer.py`
- **Eval** : `scripts/eval_question_analyzer.py` + `data/benchmark/calibration/question_analyzer_eval.json`
- **Doc résultats** : `doc/ongoing/chantiers/2026-05-06_CH-41.1_QUESTION_ANALYZER_RESULTS.md`
- **Résultats** : top-1 = 0.735 (7 types) / 0.795 (5 types structurels) ; HFF5 coverage = **1.000** (gate ≥ 0.95 ✓)
- **Décision scope** : `unanswerable` et `false_premise` retirés du périmètre QuestionAnalyzer (verdicts d'answerabilité non détectables sans corpus). Promotion vers ces 2 types se fait en aval :
  - EvidenceCollector (CH-41.2) → promotion `unanswerable` si 0 evidence
  - Structurer/Verifier (CH-41.3) → promotion `false_premise` si contradiction prémisse vs evidence
- **Charte anti-V2 respectée** : prompt sémantique pur (pas de regex, pas de listing métier), multilingue par construction, < 50 lignes
- **Quoi** : Multi-label top-2 avec confidence threshold (≥0.7 single / 0.5-0.7 combined / <0.5 EAV fallback). Démarrer list detection, étendre aux autres types au fur et à mesure des tranches.
- **Gate** : accuracy ≥ 90% top-1 ET ≥ 95% top-2 sur 100q humainement annotées par type. **Reste à atteindre 0.90 top-1 sur 5 types après cleanup ground truth temporal/comparison ambiguous (différé post-CH-41.4).**

#### CH-41.2 — EvidenceCollector (composant [B])
- **Statut** : DONE (2026-05-06)
- **Module** : `src/knowbase/facts_first/evidence_collector.py`
- **Tests** : 9 tests pytest avec mocks (Neo4j + ClaimRetriever) — all PASS
- **Wraps** : `ClaimRetriever` runtime_v3 existant (CH-35 hybrid + rerank GPU multilingue) ; enrichit chaque hit via Neo4j Cypher pour `verbatim_quote`, `publication_date`, `chunk_id` — fallback chunk-only si pas de claim_id ou Neo4j down (résilience prouvée)
- **Quoi** : Source primaire = Claims atomiques Neo4j (40 196 claims médiane 113 chars). Source secondaire = chunks Qdrant. Flux : Qdrant top chunks → claim_ids via chunk_ids → enrichir Neo4j → DocumentContext + LOGICAL_RELATION → fallback chunks-only si claims insuffisantes.
- **Documenter** : fallback tenant sans Claims indexés (Domain Pack neuf, dégradation contrôlée).

#### CH-41.3 — ListStructurer + ListComposer + Channel 1 Verifier (composants [C][D][E1])
- **Statut** : DONE (2026-05-06)
- **Modules** : `src/knowbase/facts_first/list_structurer.py`, `list_composer.py`, `list_verifier.py`, `pipeline.py` (orchestrator)
- **Tests** : 6+5+13 = 24 tests pytest (mocks LLM + déterministe) — all PASS
- **ListStructurer** : prompt extractive D-FF1 (every item cites verbatim quote) + validation déterministe (quote substring/overlap match in pool + dedup normalized_label + max_items cap). Sur bench live : 1/180 items rejetés en hallucination = 0.5% taux propre.
- **ListComposer** : LLM cantonné formatage (D-FF4) — labels verbatim + sentence_support[support_ids]. Fallback déterministe si LLM échoue (intro + bullet list).
- **Channel1Verifier** : 5 checks déterministes (schema common+list, item integrity quote≥10 chars + doc_id, composer mapping support_ids existants, coverage coherence, identifier exact-match heuristique). Sur bench live : verifier_passed_rate = **100%**.
- **Quoi** : Schéma JSON list (items[] + enumeration_quality), Composer borné JSON → prose avec sentence_support[support_ids[]], Verifier Channel 1 déterministe avec repair policy (identifier mismatch → retry, missing item → retry, 2 fails → deterministic fallback). Stockage Neo4j : `(:StructuredList)-[:HAS_ITEM]->(:StructuredListItem)-[:DERIVED_FROM]->(:Claim)` runtime-only par défaut.

#### CH-41.4 — Bench dédié list + ablation tranche 1
- **Statut** : DONE (2026-05-06, verdict partiel)
- **Bench** : `scripts/bench_list_tranche1.py` — 35 questions handcrafted GOLD_v4_LIST_NEW_*
- **Doc résultats** : `doc/ongoing/chantiers/2026-05-06_CH-41.4_BENCH_LIST_TRANCHE1_RESULTS.md`
- **Résultats finaux post-optimisations (matcher sémantique e5 cosine ≥ 0.85)** : item_f1 = **0.827** ✓ | item_recall = **0.679** ✓ (vs V3 0.07 = **+61pp** ≈ gate ADR +58pp) | item_precision = 0.683 | verifier_passed_rate = **1.000** ✓ | **source_acc = 0.427** ✓→amélioré +10pp (gate 0.80 encore non atteint) | p95 = 86s mesuré / **~66s estimé avec Composer Gemma-3-12b-it** ✗
- **Résultats (matcher strict)** : item_f1 = 0.627 | item_recall = 0.203 (×3 sous-estimation — paraphrases LLM + cross-lingual FR↔EN)
- **Optimisations appliquées (2026-05-06 PM)** :
  1. ✅ Cleanup gold-set : 169/169 items annotés `normalized_label_en` (49 via LLM, 120 direct EN) via `scripts/cleanup_gold_set_v4_normalized_labels.py`
  2. ✅ Source accuracy fix : doc_id matcher tolérant (préfixe ≥ 12 chars) → +10pp (0.33 → 0.43)
  3. ✅ Latency Composer : routage Gemma-3-12b-it (8.9s mean vs 18.9s Qwen72B = **2.8× plus rapide**, verifier 100%). Bench micro `scripts/bench_composer_models.py` × 4 modèles. Gain estimé p50 49s→39s, p95 86s→66s. Tests pytest 41/41 OK.
- **Rescoring sémantique** : `scripts/rescore_bench_list_semantic.py` + `data/benchmark/calibration/{bench_list_tranche1, bench_list_tranche1_semantic, bench_composer_models}.json`
- **Latence** : Structurer + Composer = 2 appels séquentiels Qwen2.5-72B DeepInfra (~30-40s chacun). Optimisable via vLLM EC2 (Qwen2.5-14B AWQ 5-10× plus rapide) ou Composer modèle plus petit.
- **Quoi** : Bench item_f1 / item_recall / item_precision / source_accuracy / coverage_state_accuracy / latence p50-p95 sur les 50q list du gold-set v4 enrichi. Comparaison V3 LLM-libre vs V4 facts-first list. Ablation par composant (sans QuestionAnalyzer / sans EvidenceCollector Claims / sans Channel 1 verifier).
- **Gate** : item_f1 ≥ 0.70 ✓, item_recall ≥ 0.65 ✗ (mais 2.5× V3), source_accuracy ≥ 0.80 ✗, p95 ≤ 35s ✗.

#### CH-41.5 — Chunk-extractive fallback factual simple (D-FF13)
- **Statut** : DONE (2026-05-06, intégré dans FactualStructurer Tranche 2)
- **Module** : `src/knowbase/facts_first/factual_structurer.py` (méthodes `_should_trigger_d_ff13`, `_chunk_extractive_fallback`, `_detect_conflict`)
- **Modèle fallback** : `google/gemma-3-12b-it` (extract-only, prompt court ≤30 lignes)
- **Tests** : 4 tests dédiés (D-FF13 trigger, désactivation analyzer/chunk score bas, kind=text rejected, conflict detection)
- **Bench live (n=21 valid)** : activation rate **19%** (4/21), tous en mode `factual_simple_chunk_extractive` (0 conflit détecté)
- **Gate vs V3 RAG baseline** : factual_correctness 0.312 vs 0.361 = delta -0.049 → DANS variance LLM-judge ±0.05 (gate tangent)
- **Doc résultats** : `doc/ongoing/chantiers/2026-05-06_CH-41_TRANCHE2_FACTUAL_RESULTS.md`
- **Pourquoi** : préserver le bénéfice du mécanisme V1.1 historique « si KG silencieux → RAG pur » (mode `DIRECT` du `signal_policy.py`) dans l'architecture facts-first. Décision validée 3 voix (Fred + Claude + ChatGPT, 2026-05-06) après constat de la perte de ce mécanisme dans le pipeline V3 actuel et risque de régression sur questions factuelles simples.
- **Quoi** : fallback déterministe activé quand `primary_type=factual` ET `FactualStructurer` faible confiance ET top chunk Qdrant fiable ET `object.kind` court (date/number/identifier/name/currency/duration/boolean) ET aucune `LOGICAL_RELATION` critique ET pas de désaccord chunk vs fact. Sortie au format `facts_first_v1` valide avec `diagnostic.fallback_mode = "factual_simple_chunk_extractive"`. Reste un Structured Evidence Package, pas un retour V3 caché.
- **Cas désaccord** : si fact faible diverge du chunk → `coverage_state=unknown` + `fallback_mode="factual_simple_conflict_suspected"` + `answerability=partial`. Pas de tranchage arbitraire.
- **Seuil** : `initial_threshold = 0.7`, recalibration obligatoire post-tranche 2 sur gold-set factual simple.
- **Gate ship tranche 2 (factual)** : `factual_correctness(facts-first avec D-FF13) ≥ factual_correctness(RAG baseline pur)` sur ≥30q factual simples. Sinon factual ne ship pas, V3 reste actif sur ce type.
- **Implication CH-41.0** : ajouter mesure RAG baseline pur (retrieval + LLM extract sans Structurer) dans le bench préparation, en parallèle de Facts-First.

### Tranches futures V4 (non démarrées)

- **Tranche 6 — verifier cascade complet** : Channel 2 NLI ciblé multilingue + bake-off A/B/C juges si Pearson encore < 0.7 après correction schéma. Gate faithfulness +5pp + regen rate -50% + delta FR-EN ≤ 5pp. Effort 2 sem. **NOTE 2026-05-07** : Channel 2 mDeBERTa-v3-base maintenu en prod (HHEM-2.1 testé et abandonné). Cascade C2+C3 différée tant que Pearson juge non recalibré (cf CH-40).

**Tranches 1-5 livrées en CH-41 (2026-05-07)** : list / factual / temporal / comparison / causal opérationnels.

---

### CH-42 — Sprint S2 V4 : Question Router fine-tuné + Adaptive Retrieval
- **Statut** : IN_PROGRESS (2026-05-07, en pause user-decision après Phase 4 cascade)
- **ADR** : `doc/ongoing/chantiers/2026-05-05_CH-40_ADR_V4_ARCHITECTURE.md` §9 (addendum 2026-05-07 — pivot routing distribué, gate amendé)
- **Doc challenge externe** : `doc/ongoing/chantiers/2026-05-07_S2_ROUTER_CHALLENGE_EXTERNE.md` (290 lignes self-contained)
- **Doc Phase 0 audit** : `doc/ongoing/chantiers/2026-05-07_PHASE0_AUDIT_TAXONOMY.md`
- **Cible amendée §9.4** : `answer_shape` top-1 ≥ 90% pré-retrieval + routing final effective ≥ 90% (post-retrieval inclus)
- **Plafond mécanique mesuré** : 86% (17/132 fails corpus_dependent → non décidables pré-retrieval). Gate 90% top-1 strict pré-retrieval **mathématiquement non atteignable** sur taxonomie originale → pivot architecture en 2 axes.

#### CH-42.1 — Phase 0 Audit taxonomique (54 fails)
- **Statut** : DONE (2026-05-07)
- **Résultats** : 33% linguistic_pattern, 35% intrinsically_ambiguous, **31% corpus_dependent**
- **Implication** : confirmation empirique du pivot taxonomie distribuée

#### CH-42.2 — Phase 1 Re-tag gold_set_v4 (3 nouveaux champs)
- **Statut** : DONE (2026-05-07, `gold_set_v4_retagged.json`)
- **Champs ajoutés** : `gold_answer_shape` (5 classes), `gold_epistemic_status` (3 classes), `gold_corpus_signal_required` (6 classes)
- **47/132 questions (36%)** nécessitent un signal corpus (contradiction 14, supersession 13, kg_meta 10, missing_info 6, premise_check 4)

#### CH-42.3 — Phase 2 Re-train sur answer_shape (5 classes)
- **Statut** : DONE (2026-05-07, `data/router/v3/model/`)
- **Dataset** : 14767q multi-source (Mintaka 3990 + SQuAD2 unans 1500 + SQuAD2 causal 1297 + HotpotQA 884 + FalseQA 1867 + 490 manuel + 3900 traductions FR Qwen-72B), re-taggué via patterns
- **Modèle** : XLM-RoBERTa-base (278M, 5 epochs bf16 GPU L4, train_loss 0.22)
- **Résultats** :
  - Val (notre split) : top-1 **97.6%**, top-2 **99.7%**, F1 0.97
  - gold_set_v4 retagged : top-1 **73.5%**, top-2 **86.4%** (vs 58% sur ancienne taxonomie, +15.5pp)
  - panel_stress (multi-domain) : top-1 **79.8%**, top-2 **91.5%** (vs 55% avant, +24.8pp)
  - Per-shape gold : causal 100% ✅, list 94% ✅, comparison_explicit 25% (n=4 faible), scalar_factual 58%, temporal 50%
- **Validation empirique du pivot** : +24.8pp panel multi-domaines confirme que le pivot taxonomie EST la bonne direction.

#### CH-42.4 — Phase 4 Cascade calibrée DeBERTa + LLM fallback
- **Statut** : DONE (2026-05-07, `data/router/v3/cascade_calibration.json`)
- **Calibration** : Temperature scaling sur val (T=1.666)
- **Résultats** :
  - gold_set_v4 effective @ thr=0.9 : **80.3%** (DeBERTa pour 79.5% des cas, LLM fallback 20.5%)
  - panel effective @ thr=0.95 : **84.7%** (DeBERTa pour 83%, LLM 17%)
- **Diagnostic** : la cascade plafonne à 80-85% car même les cas confident (proba >0.9) ne dépassent pas 79% accuracy. Gate strict 90% non atteint.
- **Décision user 2026-05-07** : **arrêt momentané du chantier S2** — plafond gain marginal vs effort restant. Reprendre après priorités produit prioritaires (cf "À faire" ci-dessous).

#### CH-42.5 — Phase 3 Active learning ciblé + Phase 5 EvidenceRerouter étendu (NON DÉMARRÉS)
- **Statut** : DEFERRED (2026-05-07, suspendu sur décision Fred)
- **Pourquoi DEFERRED** : audit Phase 0 + run cascade montrent qu'on plafonne à ~85% effective. Pour atteindre gate 90%, options Phase 3 (active learning sur 35 fails) + Phase 5 (rerouter étendu) — gain estimé +5-10pp mais effort 3-5 sessions. Fred priorise d'autres chantiers business critiques.
- **Reprise possible** : 2-3 sessions effort si gate strict redevient critique
- **Livrables si repris** :
  - Phase 3 : génération 300 questions régulatoires ciblées sur fail patterns scalar_factual/temporal + re-train v4
  - Phase 5 : EvidenceRerouter étendu avec promotions corpus-aware déclaratives (`scalar_factual → comparison` si CONTRADICTS ≥ 2, `* → temporal` si SUPERSEDES chain ≥ 2 hops, `* → unanswerable` si answerability_hint, `* → false_premise` si premise_validator)
  - Bench séparé du rerouter sur les 47 cas corpus_dependent

#### CH-42.B — Adaptive Retrieval modes (NON DÉMARRÉ, hors scope priorités actuelles)
- **Statut** : DEFERRED (2026-05-07)
- **Effort estimé** : 2-3 sessions
- **Livrables prévus** :
  - Mode `list` doc-scoped scroll Qdrant K=30-50 (cible exact_id list 0.199 → ≥0.50)
  - Mode `versioning` Neo4j 2-hop sur LIFECYCLE_RELATION + LOGICAL_RELATION pour temporal/comparison/causal (cible T7 lifecycle +8pp)
- **Note** : moins prioritaire que les chantiers business car les modes actuels (single retrieval + EvidenceRerouter post-retrieval CH-42.3) atteignent déjà des résultats acceptables.

---

### CH-49 — OSMOSIS V4.2 Tiered Pipeline (runtime_v4_2)
- **Statut** : DONE Phase 1+2+3+4 (2026-05-10, 4 commits poussés `c96fe01..c0b4863`)
- **ADR maître** : `doc/ongoing/chantiers/2026-05-10_CH-49_ADR_PIPELINE_V4_2_ARCHITECTURE_CIBLE_v1.md` (v1.1 LOCKED, 2 rounds critique LLMs externes)
- **Doc livraison** : `doc/ongoing/chantiers/2026-05-10_CH-49_PHASE1_LIVRAISON.md` + `_PHASE2_LIVRAISON.md` + `_P1_BENCH_RESULTS.md` + `_P1_MULTI_VIEW_SCORER_CALIBRATION.md`
- **Décision archi** : Nouveau module `runtime_v4_2/` parallèle à V4.1. Endpoint `POST /api/runtime_v4_2/answer`. Pas de promotion endpoint principal.
- **Architecture livrée** : Tiered Pipeline Layer 0+1+2 avec verifier veto critique anti-Goodhart
  - Layer 0 : Cheap Certainty + Q↔A Verifier DeepSeek-V3.1 (anti-biais vs Composer Llama-Turbo) + abstain reward
  - Layer 1 : 5 operators Cap2.A/B/C/D/E (temporal_active, lifecycle_resolution, kg_query, set_reasoning, comparison_contradiction)
  - Layer 2 : Adaptive Orchestrator agentic DeepSeek-V3.1 tool use (5 iters max, timeout 45s)
  - UnifiedIntentRouter : 1 LLM call dispatche vers operators applicables (gain p50 -18%)
  - Multi-view scorer (exact + fuzzy + semantic + abstain reward) + telemetry QuestionTrace JSONL
- **Charte respectée** (audit grep confirmé) :
  - Domain-agnostic strict : 0 référence corpus dans `runtime_v4_2/`. Prompts INTENT avec placeholders abstraits `<DOC_X>`, `<STATUS>`, `<X>`, `<Y>`
  - Pas de modèles propriétaires (Sonnet/GPT-4o exclus pour coût) — open-source only via Together AI
  - Anti-biais auto-juge : Verifier DeepSeek ≠ Composer Llama-Turbo
  - LLM ≠ operator : raisonnement structurel (Cypher, set ops, clustering) en Python déterministe
  - Lifecycle evidence-locked (vision recentrée 30/04) : LIFECYCLE_RELATION uniquement sur déclaration textuelle explicite
- **Découvertes critiques** :
  - **Verifier veto manquant** initialement : Cap2.X consultaient le verifier mais retournaient ANSWER toujours → 5 misroutes. Refactor `if MISALIGNED → fallback` élimine 100% des misroutes.
  - **Faute charte Cap2.B** corrigée immédiatement post-audit Fred (4 exemples corpus-spécifiques 428/2009, 2021/821, etc. → placeholders abstraits)
  - **KG sous-équipé en LIFECYCLE_RELATION** (4 seulement) : conforme à charte stricte (déclarations explicites uniquement). Limite Cap2.B/C bench mais comportement attendu.
- **Métriques Robust 120q** : V4.1 baseline 0.403 → P1 0.867 → P2 full+veto 0.859 → P4 router smoke 30q 0.905. Latence p95 hausse cumulative (cascades verifier veto + Layer 2). Bench complet 120q final en cours.
- **Limites reconnues** : (a) latence p95 ~50s avec Layer 2 actif sur abstains, optim future via couplage router-operator params ; (b) KG diversité claims limite Cap2.E.

---

## ⚙️ Dette technique

### CH-29 — TODOs critiques code (consolidés)
- **Statut** : TODO (lot)
- **Effort** : ~3-4j si traité en bloc
- **Liste** :
  - `auth_service.py:23` — JWT secret en hard-coded ; doit venir de `os.getenv("JWT_SECRET")`
  - `llm_router.py:1345/1353` — Anthropic + SageMaker en synchrone ; doivent passer async (perf burst)
  - `dispatcher.py:245/254` — pas de retry sur échec queue + appel LLM direct au lieu de LLMRouter
  - `signal_policy.py:235/254` — gap signal monolingue ; doit être cross-lingue + cross-encoder NLI
  - `assertion_classifier.py:126` — cross-encoder en POC ; à promouvoir en prod
  - `agents/budget.py:231` — quotas tenant en mémoire ; doivent persister Redis
  - `relations/llm_relation_extractor.py:332` — chunking naïf ; chunking intelligent par phrase
  - `instrumented_answer_builder.py:131` — `evidence_url` sans highlight ; ajouter `#:~:text=...`
  - + ~15 TODOs mineurs dispersés
- **Pourquoi** : Aucun n'est urgent isolément. Certains bloquent multi-tenant (auth, quotas). À planifier en sprint dédié dette.
- **Acceptation** : `grep -rn "TODO\|FIXME" src/ | wc -l` réduit ≥ 50%.

---

## Suivi des modifications

| Date | Auteur | Modification |
|---|---|---|
| 2026-05-02 | Création | Tracking initial 29 chantiers, descriptions étoffées issues du backlog 2026-05-01 |
| 2026-05-02 | CH-01 livré | Recovery au boot worker : `_recover_interrupted_jobs()` dans `worker.py:warm_clients()`, validé end-to-end (8/8 tests + dry-run injection + restart prod log "No interrupted jobs to recover") |
| 2026-05-03 | CH-05.4/5 ajoutés | Traçabilité footnotes Wikipedia-style + deep-link PDF `#page=N` (livrés post-compaction 2026-05-02 en réaction au feedback UX "indigeste") |
| 2026-05-03 | CH-30.9-14 livrés | Diagnostics V2 branchés sur `runtime_v2/answer`, RAGAS_USE_RUNTIME_V2 par défaut, fallback V1.1 supprimé, frontend score N/A |
| 2026-05-04 | CH-30.15-18 + CH-31/32/33/34/35 livrés | Sprint A retrieval overhaul (hybrid+filter+rerank), retrieval enrichi (decomposer+HyDE+LLM-filter), verification post-synth (premise+NLI), audit juge migré Prometheus → Llama-3.3-70B |
| 2026-05-05 | CH-39 livré (Refonte V3) | Pipeline V3 minimaliste 5 stages 250 lignes, 0 hardcoded list, livré matin. Bench Robust V3_FINAL3 0.545 vs V2 ABC1 0.495 = +5pp |
| 2026-05-05/06 | CH-40 livré (Sprint S0 V4) | Calibration & gold-set : 97q stratifié + structured metrics anti-overfit + Pearson juge (FAIL global 0.46) + disagreement summary (31.7% overscored) + `chantiers/2026-05-05_CH-40_S0_BASELINE.md` 504 lignes self-contained |
| 2026-05-06 | Pivot V4 facts-first | Décision architecturale 3 voix (Fred + Claude + ChatGPT) — abandon V3 LLM-centric, cible facts-first par tranches verticales. ADR `chantiers/2026-05-06_CH-41_ADR_FACTS_FIRST.md` ratifié. CH-36/37/38 SUPERSEDED |
| 2026-05-06 | CH-41 créé | V4 Facts-First Tranche 1 list. **CH-41.M BLOQUANT** (verrouillage contrats) avant CH-41.0 pré-requis. Réserve forte ChatGPT review intégrée |
| 2026-05-06 | Tracking rafraîchi | Mise à jour exhaustive : ajout CH-30.9-18, CH-31/32/33/34/35, CH-36/37/38 (SUPERSEDED), CH-39 (DONE), CH-40 (DONE), CH-41 (IN_PROGRESS) |
| 2026-05-06 | CH-41.M livré | Verrouillage contrats Facts-First : 8 schémas JSON figés + 2 YAML Domain Pack (template + aerospace) + doc EAV abstention + cadrage stress-test 100q |
| 2026-05-06 | Réorg `chantiers/` | 25 docs liés au tracking centralisés dans `doc/ongoing/chantiers/` avec préfixe date `YYYY-MM-DD_CH-XX_*.md`. 6 douteux laissés à racine pour validation |
| 2026-05-06 | D-FF13 + CH-41.5 ajoutés | Garde-fou chunk-extractive fallback pour factual simple (préserve mécanisme V1.1 « KG silencieux → RAG pur »). Validé 3 voix Fred + Claude + ChatGPT |
| 2026-05-07 | CH-41 livré + bench global V4 | Tranches 1-5 V4 livrées (5 types structurels + 2 spéciaux). Bench global 132q : routing 82%, verifier 100%, 0 hallucination. p50 list 44s, factual 26.5s. |
| 2026-05-07 | Leviers latence 1-5 testés | Levier 1 (mode=single list), 2 (workers=4), 3 (timeouts 120s) RETENUS. Levier 4 (Llama-Turbo) ABANDONNÉ (129/132 abstentions piège). Levier 5 (HHEM-2.1) ABANDONNÉ (latence +25%, verifier régresse). Worst-case factual 794s éliminé. Mistral-Small-22B candidat optionnel via env (-25% p50). |
| 2026-05-07 | Audit triangulé S2 | Trois LLM externes (ChatGPT, Claude Web) + audit Phase 0 (54 fails) convergent : 31% corpus_dependent → gate 90% strict pré-retrieval mathématiquement non atteignable. Pivot architecture en 2 axes (answer_shape pré-retrieval + epistemic_status partiellement post-retrieval). |
| 2026-05-07 | ADR §9 amendement | Addendum §9 ADR V4 : taxonomie distribuée acté. Gate révisé : 90% answer_shape + 90%+ effective. Garde-fous (rerouter explicable + re-tag gold). |
| 2026-05-07 | CH-42 partiel + DEFERRED | Phase 0/1/2/4 livrées (audit, re-tag gold, re-train, cascade). Gain mesuré +24.8pp panel top-1 vs run précédent. Phase 3 (active learning) + Phase 5 (rerouter étendu) + S2.B (adaptive retrieval) DEFERRED sur décision Fred — plafond gain marginal vs priorités business. |
| 2026-05-09 | CH-49 ADR v0.7 | 32 décisions atomiques par type (audit corrections pipeline V4.1) — déprécié au profit ADR v1.0/v1.1 |
| 2026-05-10 | CH-49 ADR v1.1 LOCKED | Refonte 5 capabilities + 9 amendments post 2 rounds critique LLMs externes (ChatGPT-5 ×3 + Claude Web Opus ×2). Reasoning is an escalation, not a default. |
| 2026-05-10 | CH-49 Phase 1 livré | runtime_v4_2/ Layer 0 production-grade : Q↔A Verifier DeepSeek + multi-view scorer + abstain reward + telemetry QuestionTrace. Endpoint /api/runtime_v4_2/answer live. Score Robust 0.867 (+47% vs V4.1). |
| 2026-05-10 | CH-49 Phase 2 livré + verifier veto | 3 operators Cap2.B/C/D + correction critique : verifier veto (refactor `MISALIGNED → fallback`) élimine 100% des misroutes. Faute charte Cap2.B (4 exemples corpus-spécifiques) corrigée immédiatement post-audit Fred. |
| 2026-05-10 | CH-49 Phase 3 livré | Layer 2 Adaptive Orchestrator agentic DeepSeek-V3.1 tool use (5 iters max, timeout 45s). Tool registry (vector_search + 4 operators Cap2 + extract_answer). Trigger sur Layer 0 ABSTAIN/MISALIGNED. |
| 2026-05-10 | CH-49 Phase 4 Optim | UnifiedIntentRouter — 1 LLM call dispatche vers operators applicables au lieu de cascade séquentielle. Gain p50 -18% sur smoke 30q. |
| 2026-05-10 | CH-49 Phase 4 Cap2.E | comparison_contradiction_op evidence-first cluster + LLM qualifier (Amendment 9 ADR). 5/5 operators Cap2 livrés. 1er Layer 2 ANSWER réussi observé (causal_why). |
| 2026-05-10 | CH-49 commits poussés | 4 commits poussés sur feat/contradiction-detection : c96fe01 (Phase 1+2+3), fb72858 (snapshot historique), f278577 (router unifié), c0b4863 (Cap2.E). Audit charte grep : 0 référence corpus dans runtime_v4_2/. |

---

## Légende statuts

- **TODO** : pas démarré, prêt à être pris
- **IN_PROGRESS** : en cours, indiquer la date de démarrage
- **DONE** : terminé, indiquer le commit hash
- **BLOCKED** : bloqué par une dépendance externe (corpus, etc.)
- **DEFERRED** : repoussé sciemment (ex: attendre refactor profond)
- **SUPERSEDED** : remplacé par un chantier plus récent qui en absorbe le scope (ex: CH-36/37/38 par CH-39 puis CH-41 V4 facts-first)
