# Phase B — Plan d'Execution par Sprint

**Date** : 24 mars 2026
**Base** : Sprint 0 rapport exhaustif + consensus 3 IA + vision produit fondateur
**Reference** : `OSMOSIS_VISION_PRODUIT_2026-03.md` pour les capacites cibles

---

## Sprint 0 — Diagnostic (TERMINE)

**Duree** : 6-7 jours (22-24 mars 2026)
**Statut** : 10/10 livrables complets

### Resultats cles
- Bloc KG dans prompt : **INVALIDE** (degrade -8pp)
- 35% refus : **100% probleme prompt** (pas retrieval)
- false_answer_rate : 22% OSMOSIS, 25% RAG
- Irrelevant : 26% OSMOSIS vs 17% RAG (+9pp, signal important)
- Partial hallucination (neg) : 30% OSMOSIS vs 10% RAG (+20pp, structurel au KG)
- T2 contradictions : 100% vs 0% — game-changer confirme
- T4 completude : +19pp — forte valeur

### Decisions prises
1. Strategie "KG dans le prompt" abandonnee → pivot KG2RAG
2. Hard constraint Type A = RAG (zero KG)
3. IntentResolver regex suffisant pour MVP
4. Refactoring search.py obligatoire avant routing

**Rapport** : `SPRINT0_RAPPORT_EXHAUSTIF.md`

---

## Sprint 1 — Securisation + Fondations (EN COURS)

**Duree estimee** : 10-12 jours
**Objectif** : Fiabiliser le systeme, implementer le routing, garantir non-regression

### Criteres Go/No-Go (avant de declarer Sprint 1 termine)

| Critere | Seuil | Metrique |
|---------|-------|----------|
| Non-regression Type A | OSMOSIS >= RAG factual sur questions simples | factual_correctness T1 human |
| Reduction false_idk | < 25% (actuellement 33%) | false_idk_rate T1 human |
| Controle false_answer | < 15% (actuellement 22%) | false_answer_rate T1 human |
| Controle irrelevant | <= RAG (actuellement +9pp) | irrelevant_rate T1 human |
| Controle partial hallucination | <= RAG (actuellement +20pp) | hallucination_rate T1 neg |
| T2 non-regression | >= 100% both_sides (KG) | both_sides_surfaced T2 KG |
| T4 non-regression | >= 68% completude (KG) | completeness_avg T4 KG |

### Livrable 1.1 — Tests canary (0.5j)
**Priorite** : P0 (prerequis pour tout le reste)

Creer un jeu de 15 questions deterministes, runable en <2 min :
- 5 questions simples (Type A) avec reponse exacte attendue
- 5 questions cross-doc (Type B/C) avec metriques KG
- 5 questions negatives (pas de reponse dans le corpus)

Script : `benchmark/canary_test.py` — lance OSMOSIS + RAG + juge, affiche pass/fail en <2 min.

### Livrable 1.2 — Fix prompt asymetrique (1j)
**Priorite** : P0

Objectif : reduire false_idk de 33% a <25% SANS augmenter false_answer au-dessus de 15%.

Approche :
- Modifier le SYSTEM_PROMPT pour etre plus permissif quand les chunks ont un score > 0.85
- Ajouter une instruction "Si les sources contiennent des informations partiellement pertinentes, reponds avec ce que tu as"
- Garder l'instruction stricte "ne reponds PAS si aucune source ne contient d'information"

Validation : canary test + benchmark T1 human (100 questions).

### Livrable 1.3 — Refactoring search.py (3-4j)
**Priorite** : P0

Decoupler la fonction monolithique `search_documents()` (905 lignes) en modules :
1. `retriever.py` — Qdrant vector search (pur RAG, invariant Type A)
2. `kg_enricher.py` — enrichissement KG (entites, tensions, clusters)
3. `chunk_organizer.py` — reorganisation des chunks (KG2RAG)
4. `intent_resolver.py` — classification Type A/B/C/D
5. `search_orchestrator.py` — routing et assemblage

**Filet de securite** : canary test avant/apres chaque etape de refactoring.

### Livrable 1.4 — IntentResolver 2-passes + routing (3-4j)
**Priorite** : P1

Architecture 2-passes domain-agnostic (consensus Claude Code + Claude Web) :

**Passe 1 — Classification linguistique (< 5ms, pre-retrieval)**
- Cosine similarity entre l'embedding de la question et ~20 prototypes generiques par type
- Prototypes Type A : "What is X?", "Comment fonctionne Y?", "Explain Z"
- Prototypes Type B : "Compare X and Y", "Difference entre X et Y", "X vs Y"
- Prototypes Type C : "Resume complet de X", "Que disent tous les documents sur X", "Audit de X"
- Prototypes Type D : "Quel est le seuil exact de X?", "Quelle est la valeur de X?"
- Zero training, zero ML, domain-agnostic natif
- En cas de doute → Type A par defaut (optimiste, degrade gracieusement)

**Retrieval Qdrant** : identique pour tous les types (top_k=10), memes chunks que le RAG

**Passe 2 — Reclassification post-retrieval (signal KG)**
Regles deterministes sur les resultats du retrieval, pas sur la question :
- Les chunks recuperes touchent des claims avec tensions REFINES/QUALIFIES ? → upgrade Type B
- Les claims matchees couvrent 4+ documents distincts ? → upgrade Type C
- Un QuestionDimension match exact avec extracted_value ? → upgrade Type D
- Les chunks impliquent 2+ versions du meme sujet (ApplicabilityFrame) ? → upgrade Type B/C

**Pourquoi 2-passes** (Claude Web) :
- "Quelles sont les nouvelles fonctionnalites de la version 2023 ?" ressemble linguistiquement a Type A
- Seul le KG sait que ca necessite un raisonnement differentiel (Capacite 3)
- La Passe 1 ne peut pas detecter ca — la Passe 2 upgrade apres retrieval
- KG vide → Passe 2 n'upgrade jamais → tout reste Type A → degradation gracieuse

**Execution du type final** :
- **Type A** (defaut) : chunks Qdrant bruts, zero enrichissement KG → invariant non-regression
- **Type B** : chunks reorganises en adjacence contradictoire (tensions), prompts structures
- **Type C** : top_k elargi a 20, clusters cross-doc pour completude, entites pour couverture
- **Type D** : QD match → reponse structuree avec valeur exacte

### Livrable 1.5 — KG2RAG chunk reorganization (3j)
**Priorite** : P1

Le KG reorganise l'ORDRE et la SELECTION des chunks, pas le prompt.
Active uniquement pour les types B/C/D (jamais pour Type A) :
- CHAINS_TO pour l'ordre narratif
- ClaimClusters pour la representativite cross-doc
- REFINES/QUALIFIES pour placer les chunks contradictoires en adjacence
- Top_k elargi a 20 pour Type C (audit/completude)

**Garde-fou critique** (Claude Web) : verifier que KG2RAG ne degrade PAS le taux irrelevant ni le partial hallucination. Test systematique sur questions negatives apres chaque iteration.
**Hard constraint** : Type A ne passe JAMAIS par KG2RAG — chunks identiques au RAG pur.

### Livrable 1.6 — Benchmark enrichi (1j)
**Priorite** : P1 (en parallele)

Ajouter dans le juge LLM :
- `false_answer_rate` : metrique formelle (pas approximation)
- `irrelevant_rate` : reponse hors-sujet
- `partial_hallucination_rate` : reconnait l'absence mais repond quand meme (questions negatives)

Creer le script de non-regression automatise : compare Sprint N vs Sprint N-1 sur toutes les metriques.

---

## Sprint 2 — Architecture Signal-Driven (REVISE 25/03 soir — consensus ChatGPT + Claude Web + Claude Code)

**Bascule architecturale** : passage de "classifier les questions en types A/B/C/D" a "detecter les signaux KG sur le sujet puis composer la reponse".
**Motivation** : le diagnostic Sprint 2.0 a revele que 75% des questions sont mal classees par les prototypes embeddes. Le probleme est structurel (l'embedding capture la semantique du sujet, pas la structure interrogative). Au lieu de corriger les prototypes, on change le paradigme.
**Verification de coherence** : la bascule n'est PAS un pivot produit. Le frontend expose DEJA des signaux KG (KnowledgeProofPanel, ConfidenceBadge, CrossDocComparisons, InsightHints). Les 5 capacites de la vision produit sont toutes des cas ou le KG detecte un signal et l'expose. L'architecture signal-driven formalise ce que le produit fait deja.
**Duree estimee** : 8-10 jours
**Prerequis** : Sprint 1 go/no-go valide (FAIT — GO CONDITIONNEL)

### Principe : Signal-Driven KG Injection

```
Question → Retrieval Qdrant (toujours identique, RAG pur)
         → KG Signal Detection (interroge le KG sur les entites trouvees)
         → Signal Policy (si aucun signal → RAG pur, si signaux → enrichir)
         → Response Composition (prompt de base + injections conditionnelles par signal)
```

**Hard constraint** : si le KG ne detecte aucun signal, la reponse est RAG pur. Le silence du KG est un resultat normal, pas un echec.

### Signaux KG structurants (issus des 5 capacites)

| Signal | Source KG | Quand il s'active | Impact sur la reponse |
|--------|-----------|-------------------|----------------------|
| **Tension** | REFINES/QUALIFIES/CONTRADICTS cross-doc | 2+ documents en desaccord sur les entites du sujet | Presenter les deux positions avec sources |
| **Evolution temporelle** | Meme entite, valeurs differentes, doc_dates differentes | Le sujet a evolue dans le temps | Distinguer "vrai en 2022" vs "vrai en 2024" |
| **Couverture** | Nombre de docs avec claims sur le sujet vs chunks retournes | Le retrieval a manque des documents pertinents | Elargir le retrieval ou signaler la couverture partielle |
| **Exactitude** | QD match avec extracted_value + provenance | Une valeur exacte structuree existe | Reponse structuree avec valeur et source |
| **Silence** | Aucun signal detecte | Le KG n'a rien d'utile a apporter | RAG pur, zero injection |

### P0 — Fondations (4-5 jours)

#### Livrable 2.1 — Supprimer fallback doc_id dans enrichissement KG (0.5j)
Le fallback `doc_id` dans `_enrich_chunks_with_kg()` cause le +8pp irrelevant.
Fix independant de l'architecture — pertinent dans tous les cas.
Impact immediat attendu : -5pp irrelevant.

#### Livrable 2.2 — KG Signal Detector (2-3j)
Remplace l'IntentResolver par prototypes (`intent_resolver.py` → `kg_signal_detector.py`).

Pipeline :
1. Retrieval Qdrant (identique, deja fait par retriever.py)
2. Extraire les entites du sujet depuis les claims KG deja retrouvees par `_search_claims_vector()` (~0ms supplementaire, c'est deja dans le flux)
3. Pour chaque entite, interroger le KG :
   - Y a-t-il des tensions (REFINES/QUALIFIES/CONTRADICTS) cross-doc ? → **signal tension**
   - Y a-t-il des claims sur la meme entite avec des dates/versions differentes ? → **signal evolution**
   - Combien de documents couvrent ce sujet vs combien sont dans les chunks ? → **signal couverture**
   - Y a-t-il un QD match avec extracted_value ? → **signal exactitude**
4. Retourner un `SignalReport` (peut etre vide = silence)

**Domain-agnostic** : les signaux sont des proprietes structurelles du graphe, pas du contenu.
**Pas de classification de questions** : le systeme ne demande pas "quel type est cette question" mais "qu'est-ce que le KG sait sur ce sujet".

#### Livrable 2.3 — Signal Policy + Response Composition (1.5-2j)
Remplace le chunk_organizer par types et le prompt-per-type.

**Signal Policy** — decide quoi faire avec les signaux :
- Aucun signal → RAG pur, prompt de base (Sprint 1.2)
- Signal tension → ajouter un bloc "ATTENTION: divergence detectee entre docs X et Y" dans le prompt
- Signal evolution → ajouter "NOTE: ce sujet a evolue — version 2022 vs version 2024"
- Signal couverture → elargir le retrieval aux documents manquants (targeted, pas top_k=20 aveugle)
- Signal exactitude → ajouter "Valeur structuree disponible : X = Y (source: doc Z)"
- Plusieurs signaux → composer (pas tout injecter — prioriser par pertinence)

**Guard-rail** (lecon Sprint 0) : l'enrichissement total ne doit pas depasser ~150 tokens injectes. Au-dela, le LLM degrade (test v2 : -8pp avec 144 tokens de KG bloc).

#### Livrable 2.4 — Benchmark full-pipeline (0.5j)
Le benchmark runner actuel contourne l'IntentResolver/Signal Detector. Creer un mode "full pipeline" qui passe par l'API OSMOSIS pour mesurer le vrai comportement en production.

### P1 — Valeur visible (2-3 jours)

#### Livrable 2.5 — Evidence Layer signal-driven (1-1.5j)
Au lieu d'un Evidence Layer "par type", l'afficher quand un signal non-silence est detecte :
- Signal tension → bloc "Divergence detectee" (sources, positions)
- Signal evolution → bloc "Evolution temporelle" (timeline)
- Signal couverture → mention "X documents couvrent ce sujet, Y sont dans les sources ci-dessous"
- Pas de signal → pas de bloc evidence (RAG pur, pas de pseudo-confiance)

Le frontend a deja KnowledgeProofPanel et CrossDocComparisons — c'est un enrichissement de l'existant.

#### Livrable 2.6 — Benchmark /verify (1j)
Benchmarker la Capacite 5 (Validation) avec 50 assertions.
Le resultat determine le positionnement produit.

### P2 — Ameliorations (Sprint 3 si necessaire)

#### Livrable 2.7 — Cross-encoder NLI reranker (2j)
Reranking cross-encoder obligatoire pour ameliorer le classement des chunks.
Peut aussi servir de gate NLI pour filtrer les chunks non-pertinents avant injection de signaux.

#### Livrable 2.8 — Architecture tiered synthese (2j)
Qwen 14B quand aucun signal (RAG pur), Claude Haiku quand signaux complexes (tension + evolution).

### COUPE du Sprint 2

- **IntentResolver par prototypes** — supprime. Remplace par KG Signal Detector.
- **Types A/B/C/D** — supprimes comme concept architectural. Remplaces par signaux.
- **Prompt-per-type** — supprime. Remplace par injections conditionnelles par signal.
- **Modes UX** — reporte Sprint 3. Les signaux sont plus parlants que des "modes".
- **chunk_organizer par type** — simplifie. Plus de strategies A/B/C/D, juste "reorganiser si signal couverture".

### Criteres go/no-go Sprint 2

| Critere | Seuil | Actuel (Sprint 1) |
|---------|-------|-------------------|
| T1 factual (full pipeline) | >= 38% | **43.0% — ATTEINT** |
| false_idk (full pipeline) | < 30% | **16.5% — ATTEINT** |
| false_answer | < 15% | **31.0% — HORS SEUIL** (trade-off du prompt permissif) |
| irrelevant | < 20% | **27.0% — HORS SEUIL** |
| T2 both_sides | >= 100% | **100% — ATTEINT** |
| T2 tension_mentioned | >= 80% | **50% — REGRESSION** (prompt prod pas assez directif) |
| T4 completeness | >= 65% | **74.0% — ATTEINT** |
| Signal silence = RAG pur | 100% | Fonctionne (canary 15/15) |

### Resultats complets benchmark full-pipeline (25 mars 2026)

**Decouverte majeure** : le runner standard mesurait un systeme different de la production. Les scores full-pipeline sont radicalement differents.

#### T1 Factual — 100 questions humaines

| Metrique | Runner standard | **Full-pipeline (prod)** | Delta |
|----------|:-:|:-:|:-:|
| factual_correctness | 0.348 | **0.430** | **+8.2pp** |
| answer_relevant | 0.447 | **0.608** | **+16.1pp** |
| answers_correctly | 0.223 | **0.268** | **+4.5pp** |
| false_idk | 0.372 | **0.165** | **-20.7pp** |
| false_answer | 0.180 | **0.310** | **+13pp** |
| irrelevant | 0.260 | **0.270** | +1pp |
| total_error | 0.530 | **0.470** | **-6pp** |

#### T2 Contradictions — 25 questions KG

| Metrique | Runner standard | **Full-pipeline (prod)** |
|----------|:-:|:-:|
| both_sides_surfaced | 1.000 | **1.000** |
| tension_mentioned | 1.000 | **0.500** |
| correct_tension_type | 0.714 | **0.250** |
| both_sourced | 0.571 | **0.500** |

#### T4 Completude — 20 questions KG

| Metrique | Runner standard | **Full-pipeline (prod)** |
|----------|:-:|:-:|
| completeness_avg | 0.625 | **0.740** |
| comprehensiveness | 0.350 | **0.650** |
| topic_coverage | 0.800 | **0.850** |
| contradictions_flagged | 0.100 | **0.350** |
| traceability | 0.950 | **1.000** |

#### Analyse des resultats

**Gains** :
- T1 factual +8pp, relevant +16pp, false_idk -21pp — le prompt production fonctionne
- T4 completude +11.5pp, comprehensiveness +30pp — la synthese native est excellente pour l'audit
- T4 traceability 100% — parfait

**Regressions** :
- T1 false_answer +13pp (31%) — le prompt permissif genere plus de fausses reponses. Trade-off asymetrique visible.
- T2 tension_mentioned -50pp (50%) — le prompt production ne force pas assez la mention des tensions

**Problemes a adresser** :
1. **false_answer 31%** — P0 Sprint 2 suite. Recalibrer le prompt pour maintenir la permissivite (false_idk bas) tout en ajoutant un garde-fou contre les fausses reponses
2. **T2 tension_mentioned 50%** — le prompt production doit inclure une instruction plus directive sur les contradictions/tensions quand le KG les detecte (via synthesis_additions du signal-driven)
3. **Le runner standard ne mesure plus le bon systeme** — utiliser `--full-pipeline` pour tous les benchmarks futurs

### Fichiers resultats Sprint 2

```
benchmark/results/20260325_sprint2/
  osmosis_T1_human_fullpipe.json + judge_osmosis_T1_human_fullpipe.json
  osmosis_T2_kg_fullpipe.json + judge_osmosis_T2_kg_fullpipe.json
  osmosis_T4_kg_fullpipe.json + judge_osmosis_T4_kg_fullpipe.json
  osmosis_T1_human.json + judge_osmosis_T1_human.json  (standard, reference)
  osmosis_T2_kg.json + judge_osmosis_T2_kg.json  (standard, reference)
  osmosis_T4_kg.json  (standard, reference)
```

---

## Sprint 2 suite — Re-chunking + Architecture tiered LLM

**Statut** : Consensus obtenu (ChatGPT + Claude Web + Claude Code). ADR ecrit. Test borne superieure fait.

### Test borne superieure (25 mars 2026)

Chunks reconstruits (~1500 chars) depuis le full_text du cache, testes sans retrieval :

| LLM | Chunks atomiques (actuel) | Chunks reconstruits | Delta |
|-----|:---:|:---:|:---:|
| Claude Sonnet 4 | 2/13 (15%) | **7/13 (54%)** | **+39pp** |
| Claude Haiku 3.5 | non teste | **4/5 (80%)** | — |
| Qwen 14B | 2/13 (15%) | **2/13 (15%)** | **0pp** |

**Conclusions** :
- Des chunks plus riches ameliorent massivement la qualite pour Claude (+39pp)
- Qwen 14B est trop petit pour exploiter du contexte riche — zero amelioration
- Haiku 3.5 = 80% a $0.004/question — candidat synthese production
- 13/13 questions PPTX ont leur reponse dans les caches — 100% atteignables

### Architecture tiered LLM (decidee)

| Usage | LLM | Raison | Cout |
|-------|-----|--------|------|
| Ingestion/claims | Qwen 14B local (vLLM) | Verbatim, pas de raisonnement, volume | ~$0 |
| Synthese defaut | **Claude Haiku 3.5** (API) | 80% correct, $0.004/q | ~$120/mois (1000q/j) |
| Synthese complexe (signaux KG) | **Claude Sonnet 4** (API) | 100% correct, raisonnement superieur | ~$0.014/q |
| Juge benchmark | Claude Sonnet 4 | Precision maximale, volume faible | Negligeable |

### Phase 2 suite — Re-chunking (plan confirme)

**IMPORTANT** : Le corpus contient seulement 2 vrais PPTX (007 + 022) sur 22+ documents. 97/100 questions T1 ciblent des PDF. La strategie PDF (2B) est la priorite absolue.

**2A — Extracteur PPTX "slide reconstituee" (1-2j) — P1 (pas P0)**
- Concerne seulement 2 fichiers (007 + 022) = 3 questions du benchmark
- Section_title + slide_title + bullets hierarchiques + notes orateur + relations structurelles Docling
- Important pour le produit (futurs corpus clients) mais pas pour le benchmark actuel

**2B — Chunks PDF depuis TypeAwareChunks + rechunker + overlap (2-3j)**

Analyse du probleme PDF (25 mars) : les TypeAwareChunks du cache sont deja bien meilleurs que les DocItems (median 319 chars vs 68 chars Qdrant, 40% entre 300-1000 chars). Mais les faits specifiques restent fragmentes : "SPAM/SAINT patch 71 required" = 52 chars isole de sa procedure (393 chars dans le chunk suivant).

Strategie en 4 etapes :

1. **Utiliser les TypeAwareChunks du cache** comme base (pas les DocItems)
   - Deja structures par le pipeline d'extraction (sections, tables, figures)
   - Median 319 chars pour le Security Guide (vs 11 chars DocItems)

2. **Appliquer le rechunker existant** (`rechunker.py`) avec overlap
   - Target : 1000-1500 chars par chunk resultant
   - Overlap : 200 chars entre chunks consecutifs (recouvrement)
   - Le recouvrement resout le probleme du rattachement : un petit chunk apparait dans les deux chunks voisins, le retrieval trouvera le bon contexte
   - Regles de rattachement par structure :
     - Heading → se rattache TOUJOURS au contenu qui suit
     - Note/Warning → se rattache au paragraphe qui precede
     - Ligne de table → se rattache a sa table
     - Item de liste → se rattache a sa liste + heading de la liste
   - Filtrage post-fusion : supprimer les chunks restants < 80 chars

3. **Prefixe contextuel deterministe** (zero LLM)
   ```
   [Document: SAP S/4HANA 2023 Conversion Guide | Section: 3.4 Preparatory Steps]
   ```
   Le doc_title vient du DocumentContext, le section_title du structural graph

4. **Ajouter doc_title + section_title dans le payload Qdrant** pour le filtrage et l'affichage

Estimation impact : chunks PDF passent de median 68 chars (Qdrant actuel) a ~500-800 chars (TypeAwareChunks rechunkes). Les 60% de chunks < 100 chars disparaissent.

**2B.2 — Rechunker V2 : 3 ameliorations (1-2j)**

Resultats analyse Octopus (26 mars) : 61% de bons chunks narratifs mais 11% encore trop courts, prefixe section illisible (hash), pas de fusion cross-type.

Ameliorations du rechunker :
1. **Cross-type merge par section** : fusionner les chunks adjacents dans la meme section quel que soit leur type (NARRATIVE + TABLE) tant que < target_chars. Resout les "orphan facts" comme "SPAM/SAINT 71" (52 chars) isole a cote de sa procedure.
2. **Force-merge post-rechunking** : filet de securite — tout SubChunk < 100 chars est force-fusionne avec son voisin le plus proche. Elimine les 11% de chunks courts residuels.
3. **Section title lisible** : remplacer le hash section_id par le vrai titre de section (SectionInfo.title ou section_path) dans le prefixe contextuel.

**Couche 2 — Contextual Chunk Headers (Sprint 3, optionnel)**

Si la couche 1 ne suffit pas a atteindre les seuils de benchmark, ajouter un prefixe contextuel genere par LLM (Anthropic Contextual Retrieval style). Chaque chunk recoit 50-100 tokens de contexte generes par Haiku 3.5 (~1 USD pour le corpus complet avec prompt caching).
Resultats publies : -35% a -67% erreurs de retrieval.
**Tension invariant** : le prefixe LLM est une inference, pas du verbatim. Compromis : marquer `[CONTEXT INFERRED]`.
Refs : Anthropic blog sept. 2024, dsRAG AutoContext, Unstructured.io Contextual Chunking.

**Couche 3 — RSE (Relevant Segment Extraction) au retrieval (Sprint 3+)**

Au moment de la recherche, fusionner dynamiquement les chunks adjacents pertinents en segments optimaux avant de les envoyer au LLM. Idee de dsRAG (96.6% sur FinanceBench).
Partiellement couvert par le Phase C light existant.

**Ce qu'il ne faut PAS faire** (analyse Octopus) :
- Proposition chunking (Dense X Retrieval) : hallucination + perte tracabilite
- Late chunking (Jina) : necessite changement modele embedding
- Remplacer rechunker par Docling HybridChunker : input incompatible, pas d'overlap

**2C — Integration Haiku/Sonnet dans synthesis.py (1j)**
- Router vers Haiku par defaut pour la synthese
- Router vers Sonnet quand signal KG non-silencieux (tensions, evolution)
- Fallback Qwen local si API indisponible

**2D — Enrichissement benchmark PPTX (0.5j)**
- 20 questions PPTX supplementaires pour un signal robuste (33 questions total)

**2E — Re-ingestion from scratch (2-3j)**
- Purge Qdrant + Neo4j
- Re-ingestion avec nouvelle strategie
- Re-extraction claims ClaimFirst
- Benchmark differentie : PPTX >= 50%, PDF >= 60%

### ADR references
- `ADR_UNITE_PREUVE_VS_UNITE_LECTURE.md` — separation formelle unite de preuve / unite de lecture
- `ADR-20260126-vision-out-of-knowledge-path.md` — Vision hors du chemin critique KG (maintenu)

---

## Sprint 3+ — Extension (ESQUISSE)

### Always-on context layer (article Zep)
- Metadata de couverture systematique (combien de docs couvrent le sujet)
- Tensions proactives (injectees meme si question factuelle simple)
- DocumentContext always-on (version, scope, perimetre)

### Raisonnement differentiel (Capacite 3)
- Comparaison automatique entre versions (v2022 vs v2023)
- Deduction par absence : "present dans v2023 mais pas dans v2022 → nouveau"

### Evidence Layer systematique
- Afficher consensus/divergences pour toute reponse (pas conditionne par signaux)

### Benchmark /verify (Capacite 5)
- Tester la page /verify avec 50 assertions

### Corpus de demo non-SAP
- Ingestion du corpus RGPD (76 documents) pour demontrer domain-agnostic

---

## Suivi d'Avancement

| Sprint | Livrable | Statut | Date debut | Date fin | Notes |
|--------|----------|--------|------------|----------|-------|
| 0 | 10 livrables diagnostic | **TERMINE** | 22/03/2026 | 24/03/2026 | Rapport exhaustif |
| 1 | 1.1 Tests canary | **TERMINE** | 24/03/2026 | 24/03/2026 | `benchmark/canary_test.py` — 15 questions, 13/15 pass |
| 1 | 1.2 Fix prompt | **TERMINE** | 24/03/2026 | 25/03/2026 | synthesis.py: prompt EN domain-agnostic, regle "partial info". Canary 5/5 Type A (vs 0/5 avant). Benchmark T1 human: zero regression |
| 1 | 1.3 Refactoring search.py | **TERMINE** | 25/03/2026 | 25/03/2026 | Strangler Fig complet. Canary 12/15 (5/5 B/C, 4/5 A, 3/5 NEG) |
| 1 | 1.4 IntentResolver 2-passes | **TERMINE** | 25/03/2026 | 25/03/2026 | 27 prototypes, Passe 1+2 branches, classification 5/6 correcte |
| 1 | 1.5 KG2RAG | **TERMINE** | 25/03/2026 | 25/03/2026 | chunk_organizer branche, Type A = zero modification (hard constraint) |
| 1 | **VALIDATION GO/NO-GO** | **GO CONDITIONNEL** | 25/03/2026 | 25/03/2026 | T1: 0 regression (seuil 5pp), false_answer -4pp. T2: 100% both_sides. T4: completude 62.5% (-5pp, variabilite). false_idk et irrelevant restent hors-seuil (pre-existant Sprint 0) |
| 1 | 1.6 Benchmark enrichi | **TERMINE** | 24/03/2026 | 24/03/2026 | `llm_judge.py`: false_answer_rate, irrelevant_rate, total_error_rate + `compare_runs.py` |
| 2 | 2.0 Diagnostic false_idk par type | **FAIT** | 25/03/2026 | 25/03/2026 | 75% mal classes en Type C — prototypes invalides |
| 2 | 2.1 Supprimer fallback doc_id | **FAIT** | 25/03/2026 | 25/03/2026 | Matching exact chunk_id uniquement |
| 2 | 2.2 KG Signal Detector | **FAIT** | 25/03/2026 | 25/03/2026 | `kg_signal_detector.py` — 4 signaux + silence |
| 2 | 2.3 Signal Policy + Response Composition | **FAIT** | 25/03/2026 | 25/03/2026 | `signal_policy.py` — passthrough si silence |
| 2 | 2.4 Benchmark full-pipeline | **FAIT** | 25/03/2026 | 25/03/2026 | `--full-pipeline` flag. Premiere mesure reelle prod — resultats radicalement differents du runner standard |
| 2 | 2.5 Evidence Layer signal-driven | Planifie | | | P1 |
| 2 | 2.6 Benchmark /verify | Planifie | | | P1 |
| 2 | 2.7 Cross-encoder NLI reranker | Planifie | | | P2 |
| 2 | 2.8 Architecture tiered synthese | Planifie | | | P2 |
| 2 | **Nettoyage code mort** | **FAIT** | 25/03/2026 | 25/03/2026 | Supprime: intent_resolver.py, chunk_organizer.py, Graph-First, Hybrid Anchor. search.py -224 lignes |
| 2 | **BENCHMARK FULL-PIPE** | **FAIT** | 25/03/2026 | 25/03/2026 | Voir resultats ci-dessous |

---

## Risques Identifies

| Risque | Impact | Mitigation |
|--------|--------|-----------|
| KG2RAG aggrave irrelevant rate | Fort | Test systematique sur questions negatives a chaque iteration |
| Refactoring search.py casse des fonctionnalites | Fort | Canary tests avant/apres + benchmark complet post-refactoring |
| Fix prompt augmente false_answer | Fort | Trade-off asymetrique : garder false_answer < 15% meme si false_idk reste a 20-25% |
| IntentResolver mal classifie → mauvais mode | Moyen | Fallback Type A (RAG pur) si confiance basse |
| Performance degradee par le routing | Faible | Type A ne fait PAS d'appels KG supplementaires |
