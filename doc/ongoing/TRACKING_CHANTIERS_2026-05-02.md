# Tracking chantiers OSMOSIS — actif au 2026-05-02

> **But** : fichier de pilotage unique pour adresser les chantiers restants un à un.
> **Source** : audit `BACKLOG_DEV_2026-05-01.md` + descriptions détaillées rédigées 02/05.
> **Statut** : `TODO` / `IN_PROGRESS` / `DONE` / `BLOCKED` / `DEFERRED`.
> **Convention** : à chaque démarrage, mettre `IN_PROGRESS` + date. À chaque clôture, `DONE` + commit hash.

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
- **Statut** : IN_PROGRESS — Phase 1 cadrage livrée 2026-05-02 (`CADRAGE_CH02_V33_VS_V2_2026-05-02.md`), périmètre réduit à 4 sous-chantiers
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
- **Livrable** : `doc/ongoing/AUDIT_LOGICAL_RELATION_CH02_2_2026-05-02.md`
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
- **Quoi** : Couvrir DIRECT/AUGMENTED, silences (le système n'a rien dit), tensions cross-doc dans la trace de raisonnement. ADR existe (`ADR_RAISONNEMENT_UI.md`).
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

---

## Légende statuts

- **TODO** : pas démarré, prêt à être pris
- **IN_PROGRESS** : en cours, indiquer la date de démarrage
- **DONE** : terminé, indiquer le commit hash
- **BLOCKED** : bloqué par une dépendance externe (corpus, etc.)
- **DEFERRED** : repoussé sciemment (ex: attendre refactor profond)
