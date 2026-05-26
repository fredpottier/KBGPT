# ADR P1.4-bis — Refonte de l'extraction de Claims (qualité-first, multi-étapes)

> Date : 2026-05-26
> Statut : DRAFT — en attente validation Fred
> Branche : `feat/phase-b-augmentee`
> Références : `doc/ongoing/CLAIM_ANALYSIS_P1_4.md` (Volets 3-4, mesures sur-extraction/dédup/utilité), `doc/ongoing/SOTA_CLAIM_EXTRACTION_2026.md` (Volets 1-3, dont Volet 3 = fiabilité Qwen), `ADR_PHASE_B_HYPER_RELATIONAL_CLAIMS.md` (qualifiers/procédures), mémoires [[project-overextraction-dedup-next-step]], [[project-subject-canonical-must-be-quasi-mandatory]], [[project-judge-abstention-overfit]].

---

## 1. Motivation

### 1.1 Le déclencheur immédiat (sur-extraction ×23)
Le prompt P1.3.5 (décontextualisation + question-guided + open-predicate + qualifiers + « extract EVERY genuine claim » dans **un seul méga-appel**) a produit une **sur-extraction ×23** (8530 claims / 4 docs ≈ 73% de l'ancien corpus ; Feature Scope = 6934). Cause mécanique confirmée par la littérature (Volet 3) : **les LLM open-source (Qwen) suivent mal les consignes fines multi-contraintes simultanées**. Un méga-prompt qui doit « tout faire en une passe » est le profil d'échec type.

### 1.2 Le vrai objectif (au-delà du volume)
**La qualité des claims conditionne la capacité de la solution à répondre.** Un KG restreint à du contenu curé de haute qualité ramène les hallucinations proches de zéro ; sur des données non vérifiées, la même architecture fabrique des réponses pour 52% des questions (littérature RAG 2025). Cet ADR ne vise donc **pas seulement** à réduire le volume, mais à **refondre l'extraction pour maximiser, de façon vérifiable, toutes les dimensions de qualité d'un claim** — granularité, fidélité, indexabilité, exactitude des identifiants, modalité, structure relationnelle.

Les mesures déterministes du jour cadrent l'ampleur :
- **Dédup tiered (#2) = ~13%** de réduction sûre (post-traitement, commit 289aace).
- **Filtre utilité (#3) = ~17%** dont ~5% hard-junk sûr (commit e5c152b).
- → Post-traitement « sûr » ≈ 15-20% : **filet utile mais insuffisant** pour défaire le ×23. Le moteur structurel = catalogue Feature Scope (81% du corpus) sur-décomposé. **Seule la refonte de l'extraction (prompt + schéma + pipeline) traite la masse.**

---

## 2. État de l'existant (audit 26/05/2026)

| Composant | Fichier | État |
|---|---|---|
| Prompt extraction | `claimfirst/extractors/claim_extractor.py:266` `build_claim_extraction_prompt` | **Méga-prompt unique** (`CLAIM_EXTRACTION_PROMPT_TEMPLATE`) : 5 consignes en 1 appel. **À remplacer.** |
| Mode pointer | `claim_extractor.py` (Phase 1-3) | ✅ **Verbatim GARANTI** : le LLM pointe des unités, `verbatim_quote` reconstruit depuis l'index — **pas généré par le LLM**. **Propriété de grounding précieuse à préserver.** |
| Segmentation | `stratified/pass1/assertion_unit_indexer.py` | `item_type` Docling (LIST_ITEM/TABLE/HEADING/paragraph) → `list_item`/`bullet`/`table_cell` = **unités atomiques** (l.96/152). MAIS `split_on_colon=True`/`split_on_semicolon=True` → **clause-split déterministe des énumérations** dans les paragraphes (fuite de sur-décompo). |
| Signal structurel | `Passage.item_type` | ✅ Présent, déterministe, **domain-agnostic** (Docling parse la structure indépendamment du sujet). ❌ **JAMAIS injecté dans le prompt** → le LLM réinfère la structure → sur-décompose. |
| Subject canonical | `claimfirst/resolution/subject_resolver_v2.py` | Existe (LLM classifier). Couverture actuelle **80%** (6835/8530) — mieux que les 39% historiques, mais 20% manquants = inaccessibles au retrieval subject-based. |
| Modalité | `claimfirst/worker_job.py:838` `extract_modality` | Helper existant — **sous-exploité**. |
| Entités | `entity_canonicalizer.py` + `:CanonicalEntity` (482) | ✅ Résolution de coréférence pour le multi-hop. |
| Predicats | `claim_extractor.py` normalisation core + alias | ✅ structured_form (triplets) à **26%** seulement. |
| Qualifiers | Phase B (`ClaimQualifier`) | ✅ Livré, **2%** sur ce corpus (faible rendement factuel mais peu coûteux). |
| Bitemporel | Phase A1.3 (`valid_from`…) | ✅ Conserver. |
| Dédup ingestion | — | ❌ Inexistant → probe #2 prêt à industrialiser. |

---

## 3. Cadre COMPLET des dimensions de qualité d'un claim (la check-list)

> « Avons-nous envisagé toutes les améliorations ? » — voici les 16 dimensions qui déterminent si un claim **porte correctement l'information** et **permet de répondre**. Chacune mappée : pourquoi ça compte pour le QA → état → action P1.4-bis.

| # | Dimension | Pourquoi (impact QA) | État | Action P1.4-bis |
|---|---|---|---|---|
| Q1 | **Granularité / atomicité** (molecular) | Trop fin = bruit/dilution ; trop gros = non-retrouvable | sur-décomposé ×23 | **#1** minimalité + **#4** item_type + fix segmenter + schéma liste-comme-champ |
| Q2 | **Auto-portance / décontextualisation** | Claim isolé doit rester interprétable au retrieval | ✅ 96% | Conserver (Stage C dédiée) |
| Q3 | **Sujet nommé + canonique (indexabilité)** | Sans subject_canonical → invisible au retrieval subject-based | 80% | **Quasi-obligatoire** (≥92%, sinon `marginal=true`) ; subject_resolver_v2 |
| Q4 | **Fidélité / grounding (zéro hallucination)** | Un détail inventé à la décontextualisation = réponse fausse | verbatim_quote ✅ ; mais `text` synthétique peut dériver | **NOUVEAU : gate grounding** (claim ⊨ source ; ancrage identifiants) |
| Q5 | **Exactitude des identifiants/valeurs** | Code transac / n° réglement faux = régression factual | risque paraphrase | **Règle verbatim + check déterministe** (identifiant ∈ source) ; jamais normaliser |
| Q6 | **Modalité & polarité (négation, may/must/recommended)** | « recommandé » ≠ « est » ; « ne supporte PAS » inversé = faux | helper existe, sous-exploité | **Préserver explicitement** (champ + règle ; réutiliser `extract_modality`) |
| Q7 | **Check-worthiness / saillance** | Boilerplate/vacant dilue le KG (52% hallucination si non curé) | aucune à l'extraction | **#3 Stage A Sélection** + filtre hard-junk post |
| Q8 | **Structure relationnelle (triplet/structured_form)** | (subject,predicate,object) = base du multi-hop/relationnel | 26% | **Schéma natif** subject/predicate/objects[] → ↑ couverture |
| Q9 | **Qualifiers (temporel/spatial/version/condition)** | lifecycle/conditionnel | 2% | Conserver (cheap) |
| Q10 | **Liaison d'entités / coréférence** | Claims sur même entité doivent se relier (multi-hop) | ✅ entity_canonicalizer | Conserver |
| Q11 | **Validité bitemporelle** | « que savait-on à date T » vs « vrai aujourd'hui » | ✅ A1.3 | Conserver |
| Q12 | **Traçabilité / provenance** | Citation dans la réponse (doc, page, verbatim) | ✅ | Conserver |
| Q13 | **Déduplication** | Doublons polluent le ranking | ❌ | **#2 dédup tiered** en post-ingestion |
| Q14 | **Couverture / rappel** | Ne PAS perdre les faits importants (crainte Volet 1) | ✅ (sur-couvre) | Sélection ne coupe QUE le non-checkworthy ; **smoke vérifie le rappel** |
| Q15 | **Fluence du texte du claim** | Qualité d'embedding + de synthèse | ✅ médiane 99c | Conserver |
| Q16 | **Confiance calibrée (composite)** | Pondération runtime + abstention honnête ([[project-judge-abstention-overfit]]) | champ `confidence` brut (overconfident) | **Signal composite** mais **dé-pondérer les composants corrélés** (structured_completeness ~ subject_canonical_present) : ex. `0.4·raw + 0.35·grounding + 0.25·max(structured, subject_canonical)`. Calibration post-hoc (temp scaling/isotonic) **différée** (besoin gold-set annoté). |
| **Q17** | **Citation span-level (auditabilité)** | AI Act : « ce claim vient de cette phrase, page X, car 1234-1567 » | `unit_ids` ✅ + `char_start/end` sur `AssertionUnit` — MAIS Passages **non persistés en Neo4j** | **Stocker les `source_char_spans` SUR le Claim à l'extraction** (pas seulement les unit_ids, vu que les passages sont transients) + méthode **`Claim.get_source_citation()`** reconstruisant file/page/chars pour le Reading Agent. Données présentes → câblage. |
| **Q19** | **Normatif vs descriptif (poids déontique)** | Réglementaire/dual-use : « SHALL verify » (obligation) ≠ « typically verifies » (pratique) | `claim_type` **rempli 100%** (FACTUAL/DEFINITIONAL/PRESCRIPTIVE/PROCEDURAL/PERMISSIVE/CONDITIONAL) — mais **pas de DESCRIPTIVE explicite (=FACTUAL) ni PROHIBITIVE** | **Extraction DÉTERMINISTE des marqueurs déontiques en Stage B (pré-LLM)** : shall/must/should/may/required/prohibited/permitted (+FR) → compléter la taxonomie (ajouter PROHIBITIVE ; DESCRIPTIVE↔FACTUAL) et **rendre la classe normative fiable**. Domain-agnostic. Renforce Q6. |

**Apports NOUVEAUX de la refonte au-delà du volume** : **Q4 grounding gate**, **Q5 exactitude identifiants**, **Q6 modalité/négation**, **Q8 structured_form natif**, **Q3 subject_canonical quasi-obligatoire**, **Q16 confiance composite**, **Q17 citation span-level**, **Q19 normatif/descriptif**. Ce sont les dimensions QA-critiques (et compliance-critiques) qui n'étaient pas explicitement garanties.

> **Q20 (différé Phase C)** — *Claim interdependence* : détecter à l'extraction qu'un claim en implique un autre (« X is mandatory » ⊨ « X is required ») pour enrichir le KG. Relève des relations claim-claim (Phase B/C), pas de P1.4-bis.

> **Revue externe (Claude Web, 26/05/2026)** : architecture validée (multi-étapes, guided decoding, défaut sûr = SoTA). Gaps soulevés intégrés : Q17 (citation AI Act), Q19 (normatif), confiance composite (Q16 renforcé), grounding flag-not-reject, garde-fou longueur, robustesse détecteur énumération, smoke Qwen3-thinking. Décisions sur les 4 questions ouvertes → §11.

---

## 4. Décision — Architecture cible

### 4.1 Principe directeur
**Restructurer la TÂCHE (sous-tâches focalisées), pas empiler les consignes.** (Claimify, DeCRIM, DPPM, ACONIC : +10-40 pp de fiabilité sur LLM faibles.) Et : **défaut sûr déterministe** partout où c'est possible ; le LLM ne décide que ce qu'il décide bien.

### 4.2 Pipeline (couches déterministes encadrant des étapes LLM focalisées)

```
[DÉTERMINISTE PRE]  Segmentation + item_type (Docling)
   └─ FIX énumération : ne plus clause-splitter « X : A ; B ; C » en N unités
   └─ détecteur léger d'énumération intra-phrase (regex coordination) sur passages TEXT
   └─ transporte item_type + hint structurel jusqu'au prompt
        │
[LLM Stage A — SÉLECTION]  (check-worthiness, #3 à l'extraction)
   Garder le contenu vérifiable substantiel ; DROP opinion/boilerplate/vacant/méta.
   Prompt court mono-focus. Sortie guided-JSON {kept:[unit_ids], dropped:[{unit_id,reason}]}.
        │
[LLM Stage B — DÉCOMPOSITION-MINIMALITÉ + DÉCONTEXTUALISATION]  (#1 + Q2/Q5/Q6/Q8)
   Contenu retenu → claims autonomes. Règle : 1 assertion = 1 claim ;
   ÉNUMÉRATION = 1 claim dont l'objet est la LISTE (schéma liste-comme-champ).
   Préserver modalité/polarité + identifiants VERBATIM. Résoudre anaphores via
   passage_context ; nommer le sujet ; si irrésoluble → flag (NULL > faux).
   Mode pointer conservé (verbatim_quote garanti). Guided decoding XGrammar sur schéma :
     {subject, predicate, objects:[...], modality, polarity, qualifiers:[...],
      source_unit_ids:[...], self_contained_text}
        │
[DÉTERMINISTE GATES + POST]
   ├─ Grounding gate (Q4/Q5/Q17) : (a) identifiants du claim ∈ source (substring, déterministe,
   │   gratuit) ; (b) ancrage span CONTIGU dans la source (Q17 citation) ; (c) NLI :
   │   **`self_contained_text ⊨ verbatim_quote`** (pas juste « verbatim ∈ source » — la
   │   décontextualisation Stage C peut dériver, on vérifie le texte DÉCONTEXTUALISÉ).
   │   Modèle NLI = **`cross-encoder/nli-deberta-v3-base`** — DÉCIDÉ par spike empirique
   │   `p1_grounding_nli_spike.py` (séparation fidèle/hallu parfaite, marge +0.992, seuil ~0.5).
   │   **bge-reranker ÉCARTÉ** (reranker ≠ NLI : note 0.999 une hallucination « +X.509 » ;
   │   marge −0.041). mDeBERTa-xnli écarté (rate les paraphrases). HHEM cassé (remote code).
   │   Seuil ~0.5 → **flag `marginal=true`, PAS reject dur** (« NULL > faux » + rappel Q14).
   │   ⚠️ Modèle EN-fort : re-tester sur claims FR avant de s'y fier (corpus majoritairement EN).
   ├─ Garde-fou longueur (Q3 vacuous résiduel) : claim < ~5 mots → `marginal=true` (flag),
   │   SAUF s'il porte un identifiant protégé (ne jamais pénaliser un fait court mais précis).
   ├─ Marqueurs déontiques (Q19) : extraction déterministe shall/must/should/may/required/
   │   prohibited/permitted → affine claim_type {normative/descriptive/definitional}.
   ├─ subject_canonical (Q3) : subject_resolver_v2 → quasi-obligatoire, sinon marginal=true.
   ├─ entity linking (Q10), bitemporel (Q11), confidence (Q16) : inchangés.
   ├─ Dédup tiered (#2) : exact → cosine 0.93 → bge-reranker + garde-fou LARGE.
   └─ Filtre hard-junk (#3) : DROP seulement legal/marketing/méta haute-confiance,
        garde-fou SPÉCIFICITÉ-aware. (vacuous laissé au prompt Stage A, pas au post.)
```

**Coût LLM** : 2 appels focalisés/passage (A + B) au lieu d'1 méga-appel ; Stage A élague en amont (Stage B voit moins). Net comparable, fiabilité bien supérieure. Canonicalisation/entités/dédup réutilisent l'existant ou sont déterministes.

### 4.3 Le levier clé de granularité : le SCHÉMA, pas la consigne
Guided decoding **XGrammar (vLLM)** avec un schéma où **l'énumération est un CHAMP** :
```json
{"subject": "...", "predicate": "...", "objects": ["A", "B", "C"], ...}
```
→ « 1 claim avec liste » devient le **chemin de moindre résistance** pour le modèle. Le schéma **façonne** le comportement mieux qu'une consigne en prose (IFEval : les LLM ne tiennent pas un nombre cible → **JAMAIS** piloter par « ~300 claims/doc »).

### 4.4 #4 granularité adaptative = signal déterministe, PAS un classifieur (réponse au risque routeur)
- `item_type` (Docling) est déjà là, **déterministe + domain-agnostic** (un PDF médical, une norme, un manuel aerospace → mêmes types structurels). Aucun classifieur LLM de « type de document » → **aucun nouveau point de failure sémantique**.
- L'adaptation n'est qu'un **raffinement au-dessus du défaut sûr** (minimalité Q1). Si Docling se trompe sur un passage → dégradation gracieuse, **jamais** ×23.
- Politique par item_type (déterministe) :
  - `list_item`/`bullet` → 1 unité = candidat à ≤1 claim (déjà atomique) ; ne pas re-décomposer.
  - `table`/`table_cell` → ligne = fait ; éviter d'exploser les cellules.
  - `paragraph`/`TEXT` → minimalité + détecteur d'énumération intra-phrase.
  - `HEADING` → contexte, pas claim en soi.
- Limite honnête : Docling donne 1 `list_item` **par puce** (pas de conteneur « énumération ») et **les énumérations intra-paragraphe** (« supports X, Y, and Z ») ne sont PAS marquées `list_item` → relèvent du schéma liste-comme-champ + détecteur regex coordination (déterministe).
- **Robustesse du détecteur d'énumération (impératif)** : distinguer une énumération de valeurs partageant un prédicat (« supports X, Y **and** Z » → 1 claim-liste) d'une **coordination non-énumérative** : sujets coordonnés (« the pilot **and** the copilot must verify »), **alternative** (« procedure A **or** B may be used »), conjonction de propositions. **Défaut sûr = ne PAS décomposer si ambigu.** Tester explicitement ces faux positifs au smoke.

### 4.5 Fiabilité Qwen (Volet 3)
- Qwen2.5-14B (ré-ingestion) : `guided_json` vLLM propre → **utiliser XGrammar**.
- Qwen3-235B (extraction prod) : bug vLLM `guided_json`+`enable_thinking=False` (#18819) → **garder thinking on** ou valider/réparer. ⚠️ **Vérifier que `thinking=on` ne dégrade pas la sortie structurée** : smoke Qwen3+thinking vs Qwen2.5-14B sur 2-3 docs ; si Qwen3+thinking < Qwen2.5, garder Qwen2.5-14B pour l'extraction (Qwen3 reste au runtime).
- Température 0-0.2 ; prompts **courts mono-focus** ; **few-shot démonstratif cross-domain** (1 énumération gardée en liste, 1 opinion DROP, 1 modalité préservée).
- **Option (si coût A+B problématique)** : modèle léger pour Stage A (sélection, tâche simple) + modèle plus fort pour Stage B (décompo). Non retenu par défaut (2 endpoints = complexité burst) ; à activer seulement si le coût/latence le justifie.

---

## 5. Garanties domain-agnostic (charte)
- Aucune règle SAP en dur. Tests/exemples cross-domaines (médical/réglementaire/aerospace) ; vérifier systématiquement « cette règle tient-elle si SAP→médical ? ».
- item_type = structure, pas sémantique-domaine. Predicats core génériques. Sélection = critères universels (vérifiable/substantiel), pas une liste de boilerplates SAP.
- Garde-fous identifiants = heuristiques de forme (ALL_CAPS/snake/digit/chemin), pas un dictionnaire de codes SAP.

---

## 6. Changements concrets (file-level)

| Fichier | Changement |
|---|---|
| `assertion_unit_indexer.py` | Reconsidérer `split_on_colon`/`split_on_semicolon` : ne pas fragmenter une énumération ; option `keep_enumeration_as_unit`. Propager `unit_type` + détecteur d'énumération. |
| `claim_extractor.py` | Remplacer le méga-prompt par 2 étapes (Sélection, Décomposition-décontextualisation) ; injecter `item_type`/hint structurel ; brancher guided decoding (schéma liste-comme-champ) ; préserver modalité (`extract_modality`). |
| `models/claim.py` | Champs : `objects[]` (ou réutiliser structured_form), `modality`, `polarity`, `grounding_status`, `marginal`. (Réutiliser au max l'existant.) |
| NOUVEAU `extractors/selection_gate.py` | Stage A check-worthiness (LLM guided-JSON). |
| NOUVEAU `extractors/grounding_gate.py` | Q4/Q5 : ancrage identifiants (déterministe) + NLI/bge-reranker optionnel. |
| Pipeline ingestion | Insérer dédup tiered (#2) + filtre hard-junk (#3) avant persistance (industrialiser les 2 probes). |
| `config/llm_models.yaml` | Tâches `claim_selection`, `claim_decompose` (modèle/temp/guided). |

---

## 7. Conséquences

**Gains attendus (qualité → réponse)** : volume recalibré (cible indicative ~300-500/doc, **non imposée par un nombre** mais émergente des règles) ; fidélité garantie (gate grounding) ; identifiants exacts (anti-régression factual) ; modalité/négation préservées ; structured_form ↑ (multi-hop) ; subject_canonical ↑ (indexabilité) ; KG curé (boilerplate retiré). 

**Coûts/risques** : +1 appel LLM/passage (mitigé par élagage Stage A) ; refonte structurante du cœur extraction (tests de non-régression requis) ; dépendance guided decoding (gérer le bug Qwen3). 

**Alternative écartée** : garder le méga-prompt et seulement post-filtrer → insuffisant (post ≈ 15-20%, ne traite pas la masse catalogue) et ne corrige pas Q4/Q5/Q6.

---

## 8. Plan d'implémentation (incrémental, smoke-first)

0. **P1.4b-0 — Pré-flight modèle/guided decoding** : valider guided decoding (XGrammar) sur le modèle de ré-ingestion **Qwen2.5-14B** ; smoke **Qwen3+thinking vs Qwen2.5-14B** sur 2-3 docs (bug #18819 + dégradation thinking). Choisir le modèle d'extraction.
1. **P1.4b-1 — Segmenter** : option anti-fragmentation énumération + propagation item_type/unit_type. Tests unitaires **incluant les faux positifs** (sujets coordonnés « pilot AND copilot », alternative « A or B ») → ne pas décomposer.
2. **P1.4b-2 — Stage A Sélection** : `selection_gate.py` + guided-JSON. Smoke 2-3 docs, mesurer % drop (réutiliser méthode probe utilité).
3. **P1.4b-3 — Stage B Décompo+décontextualisation** : schéma liste-comme-champ + guided decoding + modalité/identifiants. Smoke.
4. **P1.4b-4 — Grounding gate** : ancrage identifiants déterministe + NLI `cross-encoder/nli-deberta-v3-base` (✅ **modèle décidé par spike `p1_grounding_nli_spike.py`**) vérifiant `self_contained_text ⊨ verbatim_quote`, en flag `marginal`. Smoke (claims flaggés) + re-test FR.
4b. **P1.4b-4b — Citation Q17** : stocker `source_char_spans` sur le Claim + `Claim.get_source_citation()` (file/page/chars). Test bout-en-bout `unit_ids → char spans → page`.
5. **P1.4b-5 — Industrialiser #2 dédup + #3 hard-junk** en post-ingestion.
6. **P1.4b-6 — Smoke intégré 2-3 docs** : re-mesurer **volume + dédup + utilité + grounding + recall** avec les probes. Cible : volume ÷ (3-5), décontextualisation maintenue (~96%), **rappel non dégradé** (vérifier qu'on ne perd pas de faits clés), subject_canonical ≥92%.
7. **P1.4b-7 — Ré-ingestion propre** (g6 PAS g6e, [[reference-ec2-burst-instance-g6-not-g6e]]) + **bench P1.5** (gate multi_hop ≥0.25 ET global ≥0.45, judge corrigé).

**Validation par étape (smoke-first, [[feedback-smoke-first-avoid-useless-full-bench]])** : si une étape ne réduit pas le volume / dégrade le rappel → stop + diagnostic avant la suivante.

---

## 9. Gates de validation (go/no-go avant ré-ingestion complète)
- ✅ Volume/doc ÷3 à ÷5 vs P1.3.5 (émergent, pas imposé).
- ✅ Décontextualisation ≥ 95% (ne pas régresser le gain Q2).
- ✅ **Rappel préservé** : sur un échantillon annoté, aucun fait clé perdu par la Sélection (Q14).
- ✅ subject_canonical ≥ 92% (Q3).
- ✅ Grounding : 0 identifiant inventé sur l'échantillon (Q4/Q5) ; NLI `marginal` cohérent.
- ✅ Dédup résiduelle < 5% (le schéma liste-comme-champ doit déjà réduire les doublons d'énumération).
- ✅ `claim_type` rempli ≥ 90% + classe normative/descriptive fiable (Q19).
- ✅ Détecteur énumération : **0 faux positif** (sujets coordonnés / alternative) sur smoke 15-20 phrases cross-domain avant P1.4b-2 (Q1).
- ✅ Citation Q17 : chaîne `claim → char spans → page` reconstructible bout-en-bout.

---

## 10. Risques

| Risque | Proba | Mitigation |
|---|---|---|
| Guided decoding casse sur Qwen3 (#18819) | Moy | enable_thinking=on / validation-réparation / fallback Qwen2.5-14B |
| Sélection coupe des faits utiles (rappel ↓) | Moy | Critère « when in doubt KEEP » + gate rappel + garde-fou identifiants |
| 2 appels LLM = coût/latence ↑ | Faible | Stage A élague ; batch ; concurrence calibrée burst |
| item_type Docling imparfait | Moy | Défaut sûr minimalité (dégradation gracieuse) + détecteur regex |
| Refonte casse la non-régression | Moy | Tests + smoke incrémental par étape, branche dédiée |

---

## 11. Décisions sur questions ouvertes (post-revue externe 26/05/2026)

1. **Coût 2 appels LLM (A+B) → GARDER SÉPARÉ.** Fusionner = recréer le méga-prompt défaillant. Coût mitigé par l'élagage Stage A (net ≈ 1.3-1.5× pas 2×). Calibrations incompatibles (A = haute précision/rappel, B = granularité). Option modèle léger/lourd en réserve (§4.5).
2. **Grounding → déterministe + NLI en FLAG (pas reject). MODÈLE DÉCIDÉ par spike empirique** (`p1_grounding_nli_spike.py`, 26/05) : **`cross-encoder/nli-deberta-v3-base`** (vrai NLI, déjà cache, chargement propre, séparation fidèle/hallu **marge +0.992**, seuil ~0.5). **bge-reranker ÉCARTÉ empiriquement** (reranker ≠ NLI, marge −0.041, note 0.999 une hallucination). mDeBERTa-xnli écarté (rate paraphrases). MiniCheck pas installé/inutile. NLI vérifie `self_contained_text ⊨ verbatim_quote`. Toujours `marginal=true`, jamais reject dur. Caveat : EN-fort, re-tester FR.
3. **Vacuous → prompt Stage A** (subjectif/domain-dépendant, pas de règle hard-codée) **+ garde-fou longueur en flag** (respecte le garde-fou identifiants).
4. **Dimensions ajoutées** : Q17 citation span-level (AI Act), Q19 normatif/descriptif (déontique), Q16 renforcé en confiance composite. Q20 (interdépendance) → Phase C.

*KG actuel (4 docs / 8530 claims) = bac à sable de mesure, re-purgé à la ré-ingestion propre. Probes `app/scripts/p1_dedup_tiered_probe.py` + `p1_utility_filter_smoke.py` réutilisables pour re-mesurer après chaque étape. Revue externe Claude Web intégrée le 26/05/2026.*
