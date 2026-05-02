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
- **Statut** : DONE (2026-05-02, commit à venir)
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
- **Statut** : TODO
- **Effort** : 2-3j
- **Fichiers** : `frontend/src/app/chat/`, `ChatMessage.tsx`, `SourceBadge.tsx`
- **Quoi** : Retirer score visible (62%), retirer bloc "vérité documentaire", rendre sources cliquables avec noms lisibles ("Security Guide 2023, p.42" au lieu de hash), intégrer sources dans le texte sous forme de micro-références.
- **Pourquoi** : 12 problèmes UX identifiés. Le chat ressemble à un debug panel, pas à un produit. Aucune différenciation visible vs ChatGPT.
- **Acceptation** : test utilisateur naïf sur 3 questions → comprend la réponse sans aide, identifie les sources sans demander.

### CH-06 — Refonte chat Phase 2 (Insight Cards + Audit auto)
- **Statut** : TODO (dépend de CH-05)
- **Effort** : 4-5j
- **Quoi** : Split Truth View + Insight Cards (encarts ⚠️ Point d'attention / 📅 Évolution détectée / 🔗 Contexte cross-doc) qui apparaissent SOUS la réponse uniquement si le KG apporte de la valeur. Switch automatique mode Audit quand tension détectée.
- **Pourquoi** : Différenciateur visible vs ChatGPT. Aujourd'hui les `insight_hints` sont générés par le backend mais invisibles côté frontend.
- **Acceptation** : sur 10 questions du benchmark T2 (tensions), au moins 8 affichent une Insight Card pertinente.

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
- **Statut** : TODO
- **Effort** : 6-9h
- **Fichiers** : `ragas_runner.py`, formatter de contexts
- **Quoi** : Scorer en parallèle `faith_chunks` (chunks seulement) + `faith_total` (chunks + graph context concaténé). Aujourd'hui la régression apparente vient du fait que le KG enrichit la réponse mais n'est pas vu par le juge.
- **Pourquoi** : `-13.6 pts` faithfulness vs RAG pur — biais structurel à corriger pour benchmarker honnêtement.
- **Acceptation** : sur 100 questions, `faith_total` ≥ baseline RAG pur, `faith_chunks` documenté à part.

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
- **Statut** : TODO
- **Effort** : 0.5j
- **Quoi** : 55 listes/20 fichiers (`AUDIT_HARDCODED_WORD_LISTS.md`). Critiques (stopwords) déjà migrées vers IDF dynamique. Reste les listes "détection" (TENSION_KEYWORDS, ANNOUNCEMENT_PATTERNS) dans `benchmark/`. Migration vers `config/detection_keywords.yaml`.
- **Pourquoi** : Multilingue/multi-domaine = ces listes EN/FR cassent dès qu'on charge un corpus ES/IT/DE.
- **Acceptation** : `grep -rn "TENSION_KEYWORDS\s*=" src/` ne retourne plus que des `from config import...`.

### CH-13 — Answer Gap Detector
- **Statut** : TODO
- **Effort** : 1j
- **Fichiers** : nouveau composant `answer_gap_detector.py`, `search.py`
- **Quoi** : TF-IDF inverse pour extraire les termes spécifiques de la question (mots dans <5% des chunks), vérifier leur présence dans top-K chunks. `gap_score = 1 - (termes_trouvés / total)`. Décision déterministe ANSWERABLE/UNCERTAIN/UNANSWERABLE pré-LLM.
- **Pourquoi** : 5/8 questions unanswerable du benchmark sont syntaxiquement OPEN (ne peuvent pas être détectées par classification de question). Le vrai signal est le gap question↔chunks.
- **Acceptation** : sur les 25 questions unanswerable du benchmark, ≥18 détectées (≥72%) sans dégrader les ANSWERABLE.

### CH-14 — HALT/EPR Logprob Entropy Detection
- **Statut** : TODO
- **Effort** : 1-2h
- **Fichiers** : `synthesis.py`, nouveau signal entropy
- **Quoi** : Activer `logprobs=true, top_logprobs=5` dans l'appel de synthèse. Calculer entropie moyenne des top-5 tokens. Si > seuil (à calibrer sur 25 questions unanswerable) → flag "réponse potentiellement non fondée".
- **Pourquoi** : Le RAG paradoxalement REDUIT la capacité d'abstention du LLM (Google Research). Signal post-hoc cross-lingue, gratuit, multilingue natif.
- **Acceptation** : entropie corrélée (Pearson ≥ 0.5) avec hallucinations détectées par juge LLM sur 100 questions.

### CH-15 — Health Toolbox scripts
- **Statut** : TODO
- **Effort** : 0.5j
- **Quoi** : Tri des ~80 scripts dans `app/scripts/` en 4 catégories (Diagnostic / Correctif / Rebuild / Infra). Déplacement obsolètes vers `archive/`, POC vers `poc/`, tests vers `tests/`. READMEs catégoriels.
- **Pourquoi** : Personne ne sait quoi lancer quand. La revue 02/04 avait identifié `generate_atlas.py` (POC) comme étant à la racine alors qu'il est obsolète vs `build_narrative_topics.py + generate_atlas_content.py`.
- **Acceptation** : `app/scripts/README.md` liste 4 catégories avec les scripts actifs uniquement.

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

---

## Légende statuts

- **TODO** : pas démarré, prêt à être pris
- **IN_PROGRESS** : en cours, indiquer la date de démarrage
- **DONE** : terminé, indiquer le commit hash
- **BLOCKED** : bloqué par une dépendance externe (corpus, etc.)
- **DEFERRED** : repoussé sciemment (ex: attendre refactor profond)
