# Chantier Benchmark OSMOSIS

**Statut** : Actif — RAGAS operationnel, 4 benchmarks realises, ContradictionEnvelope implemente
**Derniere mise a jour** : 31 mars 2026 (PM)

### Scores RAGAS — Evolution

| Run | Faithfulness | Ctx Relevance | Note |
|-----|-------------|---------------|------|
| Pre-hybrid (30 mars) | 0.743 | 0.580 | Baseline dense-only |
| Post-hybrid RRF (31 AM) | 0.793 | 0.730 | +15pp ctx (BM25 actif) |
| Post-Phase 2 C1+C3 (31 PM) | 0.806 | 0.718 | Canonicalisation stable |
| Post-KG-procedural (31 PM) | en cours | en cours | KG findings → instructions |

### Metriques manquantes — Qualite d'extraction (a implementer)

Le benchmark RAGAS mesure la qualite **en sortie** (reponses) mais pas la qualite **intermediaire** (extraction). Trois metriques cles manquent :

| Metrique | Ce qu'elle mesure | Comment |
|---|---|---|
| **Chunk Autonomy Score** | Le chunk est-il comprehensible seul ? | LLM evalue un echantillon (score 0-1). Detecte les chunks fragmentes. |
| **Claim Verification** | La claim est-elle reellement dans le texte source ? | Verifier verbatim/paraphrase sur echantillon. Detecte les hallucinations d'extraction. |
| **Coverage Score** | Quel % du contenu informatif est couvert par les claims ? | Comparer claims extraites vs full_text. Detecte le contenu rate (tableaux, diagrammes, notes). |

Ces metriques permettraient de mesurer l'impact des ameliorations d'extraction (Docling, rechunker, speaker notes) independamment de la synthese LLM.

### Contradictions — Etat des lieux et axes d'amelioration

**Ce qui fonctionne** :
- 20 CONTRADICTS + 287 QUALIFIES + 277 REFINES dans le KG
- Signal detector detecte les tensions
- ContradictionEnvelope force la surfaction (code ecrit, pas encore deploye)

**Problemes identifies** :
- **Recall tres faible** : seules les contradictions entre claims partageant les memes entites sont detectees. Si deux claims se contredisent sans entite commune, on rate la tension.
- **Proactive detection = 0%** : sur 5 questions T5 (question simple cachant une contradiction), 0% detecte. Le systeme ne surfasse une tension que sur question directe.
- **Dependance au post-import** : les CONTRADICTS sont crees pendant le clustering cross-doc, pas a l'extraction. Si le post-import n'a pas tourne, tensions absentes.

**Axes d'amelioration (par priorite)** :
1. **NLI classifier** (Natural Language Inference) : comparer les claims par entailment/contradiction semantique, pas par matching d'entites. DocNLI, SciFact comme references. Prerequis : Phase 3 C4 (relations evidence-first).
2. **Contradiction mining a l'ingestion** : detecter les tensions doc-par-doc au moment de l'extraction (pas seulement en post-import cross-doc). Permettrait de capter les contradictions intra-document.
3. **Claim comparison par QuestionDimension** : les QD sont des questions factuelles stables. Comparer les QS (valeurs extraites) entre documents pour la meme QD → contradiction structurelle automatique.
4. **Benchmark contradiction recall** : creer un gold standard de 20-30 contradictions connues dans le corpus, mesurer combien le systeme en detecte. Sans ca, on ne sait pas si on progresse.
**Sources archivees** : `doc/archive/pre-rationalization-2026-03/ongoing/SPRINT0_RAPPORT_EXHAUSTIF.md`, `SPRINT0_ZONES_OMBRE_ANALYSIS.md`, `PHASE_B_SPRINT_PLAN.md`, `BENCHMARK_V5_ANALYSE_CONTRADICTIONS.md`

---

## 1. Framework

### Composition du jeu de questions

| Categorie | Nombre | Source | Objectif |
|-----------|--------|--------|----------|
| T1 Provenance (KG) | 30 | Generees depuis le KG (cross-doc) | Tester le retrieval enrichi KG |
| T1 Provenance (Human) | 100 | Redigees par Claude (simples) | Reflet de l'usage reel |
| T1 PPTX | 20 | Ciblent les 2 PPTX du corpus | Tester l'extraction slides |
| T1 Negatives | 10 | Reponse absente du corpus | Tester le refus d'hallucination |
| T1 Vagues | 10 | Code-switching FR/EN, formulations approximatives | Tester la robustesse |
| T2 Contradictions (KG) | 25 | Generees depuis les tensions KG | Detecter les divergences cross-doc |
| T2 Contradictions (Human) | 50 | Manuelles, evaluation experte | Gestion des contradictions reelles |
| T2 Proactive (T5) | 5 | Questions simples cachant une contradiction | Detection proactive |
| T4 Audit (KG) | 20 | Completude cross-doc | Exhaustivite des reponses |
| T4 Audit (Human) | 50 | Questions d'audit reelles | Completude sur cas d'usage |
| **Total** | **~320** | | |

### Juges

- **Juge primaire** : Qwen/Qwen2.5-14B-Instruct-AWQ via vLLM (EC2 Spot g6.2xlarge)
- **Juge validation** : Claude claude-3-5-haiku-20241022 (API Anthropic)
- **Convergence inter-juges** : 0.3% — les deux juges sont quasi-identiques

### Evolution prevue : RAGAS + RAGChecker diagnostic — PRIORITAIRE

**Statut : A INTEGRER (Phase 1 benchmark)**

Le framework actuel (LLM judge factual/relevant/false_answer) est bon pour le scoring global mais faible en **diagnostic**. Il ne distingue pas "le retrieval a echoue" de "le LLM a mal synthetise".

**RAGAS** (pip install ragas) decompose en metriques orthogonales :
- `faithfulness` : la reponse est-elle fidele au contexte fourni ? (detecte les hallucinations)
- `answer_relevance` : la reponse repond-elle a la question ?
- `context_precision` : les chunks retrieves contiennent-ils l'information necessaire ? (diagnostique le retrieval)
- `context_recall` : tous les faits necessaires sont-ils presents dans le contexte ?

**RAGChecker** cible le diagnostic modulaire retrieval vs generation et correle mieux avec le jugement humain que des metriques grossieres.

**Integration concrete** :
1. Apres chaque run benchmark, exporter les triplets (question, contexte_retrieved, reponse) au format RAGAS
2. Executer RAGAS sur le set T1 (questions simples) — objectif : identifier si l'echec est retrieval ou generation
3. Si context_precision < 0.7 → probleme retrieval (chunking ou embedding)
4. Si context_precision > 0.7 et faithfulness < 0.7 → probleme synthese (prompt ou LLM)

**Effort** : 2-3 jours. **References** : RAGAS (2023/2024), RAGChecker (NeurIPS D&B 2024).

**Regle** : benchmarker apres CHAQUE phase (pas seulement apres Phase 1). La boucle `implementation → benchmark → decision → suite` est le mecanisme de controle principal.
- **Calibration** : `factual_correctness >= 0.8` = reponse correcte (seuil derive empiriquement)
- **Juge rule-based** : T5 proactive detection (regles deterministes, pas de LLM)

### Architecture des fichiers

```
benchmark/
  config.yaml                    # Configuration (URLs, modeles, seuils)
  canary_test.py                 # 15 questions deterministes, run < 2min
  compare_runs.py                # Comparaison Sprint N vs Sprint N-1
  evaluators/
    llm_judge.py                 # Juge LLM multi-tache (T1/T2/T3/T4)
    claude_judge.py              # Juge Claude (validation)
    rule_based_judge.py          # Juge T5 proactive (deterministe)
  runners/
    run_osmosis.py               # Runner OSMOSIS (API + synthese equitable)
    run_osmosis_claude.py        # Runner avec synthese Claude
  baselines/
    rag_baseline.py              # RAG direct TEI+Qdrant (sans KG)
  questions/
    task1_provenance_kg.json     # 30 questions T1 KG
    task2_contradictions_kg.json # 25 questions T2 KG
    task4_audit_kg.json          # 20 questions T4 KG
```

### Modes d'execution

- **Standard** : re-synthese avec le meme LLM (comparaison equitable OSMOSIS vs RAG)
- **Full-pipeline** (`--full-pipeline`) : utilise la synthese native OSMOSIS (mesure le vrai comportement production)
- **Decouverte Sprint 2** : le runner standard mesurait un systeme different de la production. Les scores full-pipeline sont radicalement differents. Utiliser `--full-pipeline` pour tous les benchmarks futurs.

---

## 2. Scores actuels — Baseline V5 (29 mars 2026)

**Juges** : T1/T4/T5 = rule-based deterministe, T2 Expert = evaluation manuelle, T2 KG = LLM.
**Run** : `20260329_v5_baseline` (12 fichiers judge dans `data/benchmark/results/`).

### T1 Provenance — 100 questions humaines + 100 KG (rule-based)

| Metrique | OSMOSIS Human | RAG Human | OSMOSIS KG | RAG KG |
|----------|:-:|:-:|:-:|:-:|
| factual_correctness | **0.689** | 0.666 | **0.396** | 0.375 |
| answers_correctly | **47%** | 42% | 6% | 5% |
| false_idk | 9% | 10% | 47% | 50% |
| correct_source | **68%** | 64% | **31%** | 28% |

**Invariant respecte** : OSMOSIS >= RAG sur toutes les metriques.
**Gain KG principal** : +5pp answers_correctly sur Human, +3pp correct_source.

### T2 Expert — 25 questions manuelles (evaluation manuelle)

| Metrique | OSMOSIS | RAG | Delta |
|----------|---------|-----|-------|
| Factual correctness | **0.62** | 0.56 | **+6pp** |
| Answers correctly | **44%** | 36% | **+8pp** |
| Both sides surfaced | **36%** | 28% | **+8pp** |
| Tension mentioned | 16% | 16% | = |

**Constat** : OSMOSIS surfasse mieux les deux cotes (+8pp) mais ne mentionne pas plus souvent la tension.

### T5 KG Differentiators — 30 questions (rule-based)

| Categorie | Metrique | OSMOSIS | RAG | Delta |
|-----------|----------|---------|-----|-------|
| Cross-doc (10q) | chain_score | **1.000** | 0.967 | +3.3pp |
| Cross-doc (10q) | avg_docs_cited | 4.4 | 4.4 | = |
| Proactive (5q) | detection_rate | **0%** | 0% | = |
| Proactive (5q) | contradictions en metadata | **3-8** | 0 | KG detecte |
| Multi-source (10q) | aspect_coverage | **0.458** | 0.342 | **+11.6pp** |
| Multi-source (10q) | correct | 30% | 30% | = |

**Constat critique** : Le KG detecte les contradictions (metadata) mais **0% de proactive detection**.
C'est le verrou principal — voir P1 ContradictionEnvelope.

### T4 Completude — 50 questions humaines + 100 KG (rule-based)

| Metrique | OSMOSIS Human | RAG Human | OSMOSIS KG | RAG KG |
|----------|:-:|:-:|:-:|:-:|
| factual_correctness | **0.896** | 0.889 | **0.582** | 0.577 |
| answers_correctly | **82%** | 80% | 0% | 0% |
| completeness | 0.815 | 0.807 | **0.449** | 0.436 |
| topic_coverage | **98%** | 98% | **81%** | 79% |

**Invariant respecte** : OSMOSIS >= RAG. Gain faible sur T4 (attendu : le KG n'ajoute pas grand-chose a l'exhaustivite).

### T2 Contradictions — 100 questions KG (LLM judge)

| Metrique | OSMOSIS | RAG |
|----------|---------|-----|
| factual_correctness | **0.316** | 0.286 |
| both_sides_surfaced | **20%** | 7% |
| tension_mentioned | **19%** | 7% |

**Note** : questions auto-generees, qualite variable. Les questions T2 Expert manuelles sont plus fiables.

### T4 Completude — 20 questions KG (historique)

| Metrique | Sprint 0 (RAG) | Sprint 0 (OSMOSIS) | Sprint 2 full-pipe |
|----------|:-:|:-:|:-:|
| completeness_avg | 0.489 | **0.678** | **0.740** |
| comprehensiveness | 0.158 | **0.444** | **0.650** |
| topic_coverage | 0.579 | **0.889** | **0.850** |
| traceability | 0.895 | **1.000** | **1.000** |

---

## 3. Constats cles

### 3.1 Le KG est un game-changer pour les contradictions (T2) et la completude (T4)

- T2 both_sides_surfaced : 100% OSMOSIS vs 0% RAG sur les questions KG
- T4 completude : +19pp par rapport au RAG sur les questions KG
- T4 traceability : 100% (parfait)
- Ces resultats sont **structurellement superieurs** — le RAG ne peut pas les atteindre sans graphe de connaissances

### 3.2 La qualite des chunks est le goulot d'etranglement principal

- 70% des chunks Qdrant font moins de 100 chars (mediane 68 chars)
- Cause racine : pipeline ClaimFirst envoie les DocItems atomiques 1:1 a Qdrant (MIN_CHARS=20)
- Correlation mesuree : questions reussies = 59% chunks courts, questions ratees = 75-78% chunks courts
- **Tous les benchmarks Sprint 0/1/2 refletent la qualite du chunking, pas celle de l'architecture**
- Test borne superieure avec chunks reconstruits (~1500 chars) : Claude Sonnet passe de 15% a **54%** (+39pp)

### 3.3 Le prompt etait la cause des 33% de refus

- Sprint 0 : 33% de false_idk, **100% avec score Qdrant >= 0.75**
- Le retrieval trouve les bons documents — le LLM refuse de repondre
- Sprint 1 fix prompt : false_idk passe de 33% a 16.5%
- Contrepartie : false_answer passe de 22% a 31% (trade-off asymetrique)

### 3.4 Le KG detecte les contradictions mais Haiku ne les surfasse pas

- Le KG detecte 3-8 contradictions par question dans les metadata
- Le signal tension est active, la policy ajoute "DIVERGENCES detected"
- Mais Claude Haiku **ignore l'instruction** — les tensions ne sont mentionnees que dans 16% des cas
- Causes identifiees : instructions noyees dans un prompt de 8000+ tokens, bloc KG limite a 600 chars, format pas assez explicite
- Piste : injection structuree avec template de reponse obligatoire (section "divergences")

### 3.5 Le runner standard ne mesure plus le bon systeme

Le runner standard (re-synthese equitable) et le full-pipeline (synthese native) donnent des resultats radicalement differents :
- false_idk : 37% (standard) vs 16.5% (full-pipe) — -21pp
- factual : 0.348 (standard) vs 0.430 (full-pipe) — +8pp
- **Utiliser systematiquement `--full-pipeline` pour tout benchmark futur**

---

## 4. Architecture tiered LLM

Test borne superieure (25 mars 2026) avec chunks reconstruits :

| LLM | Chunks atomiques | Chunks reconstruits | Delta |
|-----|:-:|:-:|:-:|
| Claude Sonnet 4 | 15% | **54%** | **+39pp** |
| Claude Haiku 3.5 | — | **80%** (5 questions) | — |
| Qwen 14B | 15% | **15%** | **0pp** |

### Architecture decidee

| Usage | LLM | Raison | Cout |
|-------|-----|--------|------|
| Ingestion/claims | Qwen 14B local (vLLM) | Verbatim, pas de raisonnement, volume | ~$0 |
| Synthese defaut | **Claude Haiku 3.5** (API) | 80% correct, $0.004/q | ~$120/mois |
| Synthese complexe (signaux KG) | **Claude Sonnet 4** (API) | 100% correct, raisonnement superieur | ~$0.014/q |
| Juge benchmark | Claude Sonnet 4 | Precision maximale, volume faible | Negligeable |

### Constats empiriques

- Qwen 14B est trop petit pour exploiter du contexte riche — zero amelioration avec des chunks plus longs
- Haiku 3.5 atteint 80% a $0.004/question — candidat synthese production
- Sonnet 4 est 3.6x plus cher que Haiku mais 100% correct sur l'echantillon teste
- Le tiering Haiku/Sonnet est integre dans `synthesis.py` (ANTHROPIC_API_KEY requis)

---

## 5. Travaux non termines

### P0 — Re-benchmark apres re-chunking
Le chunking est en cours de refonte (voir CHANTIER_CHUNKING.md). Les 28 documents du corpus doivent etre re-ingeres avec les TypeAwareChunks + rechunker 1500 chars + prefixe contextuel. Le benchmark complet 320 questions doit etre relance en full-pipeline apres re-ingestion.
**Impact attendu** : factual > 60% (vs 43% actuel).

### P1 — ContradictionEnvelope : rendre les tensions non-ignorables

**Diagnostic V5** : Le KG detecte 3-8 contradictions par question (metadata), le signal tension s'active,
la policy ajoute "sources contain DIVERGENCES" — mais Haiku produit une reponse plate sans mentionner
la moindre divergence. **0% de proactive detection** sur T5 (5 questions simples cachant une contradiction).

**Cause racine** : La contradiction est traitee comme une annotation contexte secondaire (texte libre dans
un bloc KG de 600 chars). Le LLM peut la lire puis choisir de ne pas l'exprimer.

**Solution** : Introduire un `ContradictionEnvelope` — objet structure entre `build_policy()` et la synthese
qui transforme la tension d'une suggestion en **contrat de sortie executoire**.

#### Architecture cible

```
search.py:
  _search_claims_vector()  → claim_hits avec CONTRADICTS
  detect_signals()         → signal tension
  build_policy()           → force_tension_disclosure=True
  build_contradiction_envelope()  ← NOUVEAU
    ├─ collect_contradiction_pairs()     — extraire les paires CONTRADICTS
    ├─ rank_contradiction_pairs()        — scoring deterministe (overlap entites/query)
    ├─ select_contradiction_pairs()      — top 3, seuil 0.30
    ├─ fetch_contradiction_evidence()    — chunk_ids bridge exacts (pas vector search)
    └─ determine_required_disclosure()   — booleen contraignant
  build_synthesis_input()  → mode "tension_explicit" si required_disclosure

synthesis.py:
  generate_structured_response()  — template obligatoire avec section divergences
  validate_tension_disclosure()   — verifie que la reponse surfasse la tension
  si KO → fallback deterministe   — "Les sources ne sont pas homogenes sur ce point..."
```

#### Objets principaux

```python
ContradictionPair(claim_a_id, claim_b_id, claim_a_text, claim_b_text, entity_names, relevance_score)
ContradictionEvidence(pair, side_a_doc/quote/chunk_id, side_b_doc/quote/chunk_id, inferred_axis)
ContradictionEnvelope(has_tension, has_required_disclosure, disclosure_reason, evidences, synthesis_mode)
```

#### Principes cles

1. **Le choix de surfacer ne doit pas appartenir au LLM** — si `has_required_disclosure=True`, la reponse
   DOIT contenir la divergence. C'est un booleen contraignant, pas une suggestion.
2. **Evidence-first retrieval** — utiliser les chunk_ids du bridge (76.1% couverture) pour recuperer
   les deux cotes exacts, pas un vector search filtre par doc_id.
3. **Fallback deterministe** — si Haiku ignore la tension meme apres retry, generer une reponse template
   sobre mais correcte : "Source A dit X, Source B dit Y".
4. **Pas de retry LLM** — un seul appel Haiku avec template obligatoire + validation. Si KO → fallback direct.
5. **Guard-rail adaptatif** — 600 chars en mode standard, 1500 chars en mode tension_explicit.

#### Ordre d'implementation

1. Dataclasses (ContradictionPair, Evidence, Envelope)
2. `build_contradiction_envelope()` dans search.py (apres `build_policy()`)
3. Enrichir requete Neo4j pour retourner claim_b_id/text dans les CONTRADICTS
4. `fetch_contradiction_evidence()` via chunk_ids bridge
5. Modifier synthesis.py : template obligatoire quand tension_explicit
6. `validate_tension_disclosure()` + fallback deterministe
7. Benchmark T5 proactive detection

**Impact attendu** : proactive detection 0% → 60-80%, tension_mentioned 16% → 80%+, both_sides 36% → 80%+.
**Effort** : 2-3 jours.

### P2 — Cross-encoder NLI reranker
Reranking cross-encoder pour ameliorer le classement des chunks avant synthese. Peut aussi servir de gate NLI pour filtrer les chunks non-pertinents.
**Effort** : 2 jours.

### P3 — Benchmark /verify (Capacite 5)
50 assertions a valider par le systeme — determine le positionnement produit.
**Effort** : 1 jour.

### P4 — Metriques de differenciation
Le benchmark ne mesure pas encore :
- Proactive contradiction detection (signaler une tension non demandee)
- Cross-doc reasoning quality (utiliser 3+ documents de maniere coherente)
- Version-awareness (distinguer les versions quand pertinent)

---

## 6. Pistes ecartees

### Bloc KG dans le prompt (INVALIDE Sprint 0)
- Test v1 (noms d'entites, ~10 tokens) : delta < 1% — ignore par le LLM
- Test v2 (SPO + tensions + QS, ~144 tokens) : **degrade** les resultats (-8pp factual, +6.9pp false_idk)
- Le LLM construit un etat mental partiel a partir des SPO puis ne corrige pas (Qwen 14B trop petit)
- **Decision** : strategie abandonnee, remplacee par KG2RAG (reorganisation des chunks)

### IntentResolver par prototypes embeddes (INVALIDE Sprint 2)
- 27 prototypes par type (A/B/C/D), classification par cosine similarity
- 75% des questions mal classees — l'embedding capture la semantique du sujet, pas la structure interrogative
- **Decision** : remplace par le KG Signal Detector (signal-driven, pas classification)

### Types A/B/C/D comme concept architectural (SUPPRIME Sprint 2)
- Les types etaient une abstraction rigide qui ne s'adapte pas aux signaux reels du KG
- Remplaces par des signaux (tension, evolution, couverture, exactitude, silence)
- Le silence du KG = RAG pur (invariant respecte)

### IntentResolver regex (ECARTE Sprint 0)
- 4.4% d'ambiguite sur 275 questions — fonctionne en apparence
- Mais ne capture que les patterns lexicaux, pas l'intention semantique
- Recommandation : pas de regex transitoire qui deviendrait une dette technique

---

## 7. Etat de l'art identifie

| Approche | Applicabilite OSMOSIS | Priorite | Statut |
|----------|----------------------|----------|--------|
| **KG2RAG** (NAACL 2025) | Reorganiser chunks par structure KG | Haute | Partiellement implemente (signal-driven) |
| **CRAG** (ICLR 2024) | Evaluateur confiance + fallback | Haute | Non implemente |
| **Adaptive-RAG** (NAACL 2024) | Classificateur ML pour routing | Moyenne | Remplace par Signal Detector |
| **RAPTOR** (ICLR 2024) | Resumes hierarchiques clusters | Moyenne | Non implemente |
| **Self-RAG** (2024) | Fine-tuning LLM | Basse | Ecarte (necessite fine-tuning) |
| **HippoRAG 2** (ICML 2025) | PPR sur claims Neo4j | Basse | Non implemente |
| **ReDeEP** | Modifier templates prompts | Basse | Partiellement (prompt fix Sprint 1) |

---

## 8. Corpus et infrastructure

- **Corpus** : 28 documents SAP (22 ingeres + 6 en cours), PDF + PPTX
- **KG Neo4j** : 15 566 claims, 7 059 entites, 2 620 clusters, 20 relations CONTRADICTS, 252 tensions
- **Qdrant** : collection `knowbase_chunks_v2`, ~15 000 chunks, embedding multilingual-e5-large 1024d
- **vLLM** : Qwen/Qwen2.5-14B-Instruct-AWQ, EC2 Spot g6.2xlarge (L4 GPU), AWQ Marlin = 26.8 t/s
- **TEI** : multilingual-e5-large, version 1.5
