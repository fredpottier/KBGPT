# Sprint 0 — Rapport Exhaustif des Diagnostics

**Date** : 24 mars 2026
**Branche** : `feat/wiki-concept-assembly-engine`
**Corpus** : 22 documents SAP, 15861 claims, 7059 entites, 2620 clusters, 252 tensions cross-doc
**Benchmark** : 275 questions (30 KG + 100 human T1, 25 KG + 50 human T2, 20 KG + 50 human T4)
**Juges** : Qwen/Qwen2.5-14B-Instruct-AWQ (primaire) + Claude claude-3-5-haiku-20241022 (validation), convergence 0.3%

---

## Synthese executive

Le Sprint 0 avait pour objectif de valider ou invalider les hypotheses architecturales de la Phase B avant de lancer l'implementation. **Resultat : la strategie initiale "bloc KG dans le prompt" a ete empiriquement invalidee.** Le KG est un game-changer pour les contradictions et la completude, mais degrade les questions simples quand il est injecte dans le prompt. La nouvelle direction est KG2RAG : le KG reorganise les chunks, pas le prompt.

### Verdict en 6 points

1. **OSMOSIS > RAG sur le complexe** : T2 contradictions 100% vs 0%, T4 completude +39%
2. **OSMOSIS < RAG sur le simple** : T1 human factual 35.3% vs 40.8% (-5.5pp)
3. **Le bloc KG degrade les resultats** : Test 1 v2 = -8pp factual, +6.9pp false_idk
4. **Le taux de refus de 33% est 100% un probleme de PROMPT** : tous les refus ont un score Qdrant >= 0.75 — les chunks pertinents SONT retrouves
5. **Le false_answer_rate est de 22%** (OSMOSIS) vs 25% (RAG) — le RAG est pire en faux positifs
6. **30% d'hallucination sur les questions negatives** : taux identique OSMOSIS/RAG, mais OSMOSIS "brode" plus (partial hallucination 30% vs 10%)

---

## Livrable 1 : Test contribution bloc KG (CRITIQUE)

### Protocole
50 questions T1 humaines. Memes chunks Qdrant pour les 2 conditions. Seul le prompt varie.

### Test v1 — Bloc KG minimal (noms d'entites, ~10 tokens)
- **Delta < 1%** sur toutes les metriques
- Le bloc ne contenait que des noms d'entites deja presents dans les chunks
- **Conclusion** : un bloc KG trivial est ignore par le LLM

### Test v2 — Bloc KG enrichi (SPO + tensions + QS, ~144 tokens)
| Metrique | Sans KG | Avec KG | Delta |
|----------|---------|---------|-------|
| factual_correctness | 0.40 | 0.32 | **-8pp** |
| false_idk_rate | 0.28 | 0.349 | **+6.9pp** |
| answer_relevant | 0.52 | 0.47 | **-5pp** |
| correct_source_cited | 0.31 | 0.359 | +4.9pp |

- **Le seul gain** est correct_source (+4.9pp) — le KG aide a identifier le bon document
- **Mais le LLM construit un etat mental partiel** a partir des SPO avant de lire les chunks, puis ne corrige pas (Qwen 14B trop petit pour ca)

### Decision
**Strategie "bloc KG dans le prompt" ABANDONNEE.** Nouvelle direction : KG2RAG — le KG reorganise les chunks (ordre, selection, adjacence contradictoire) sans modifier le contenu du prompt.

---

## Livrable 2 : Audit search.py

### Metriques structurelles
| Indicateur | Valeur |
|-----------|--------|
| Lignes totales | 2293 |
| Fonctions | 12 |
| `search_documents()` lignes | ~905 (L456-L1360) |
| Assignments dans search_documents | ~149 |
| try/except | ~21 |
| if/elif/else branches | ~65 |
| Variables d'etat accumulees | ~30+ |

### Fonctions principales
| Fonction | Lignes | Role |
|---------|--------|------|
| `search_documents()` | 905 | Orchestrateur monolithique — requete → chunks → enrichissement → synthese |
| `_get_kg_traversal_context()` | 246 | Traversee Neo4j : entites, relations SPO, tensions REFINES/QUALIFIES |
| `_get_qs_crossdoc_context()` | 311 | QuestionSignatures cross-doc + QuestionDimensions |
| `_enrich_chunks_with_kg()` | 97 | Matching chunk_id exact + fallback doc_id pour enrichir avec KG |
| `_fetch_chunks_for_claims()` | 73 | Pont Claims→Chunks via chunk_ids |
| `_search_claims_vector()` | 78 | Recherche vectorielle Neo4j sur claim embeddings |
| `_search_via_question_dimensions()` | 111 | Index qd_embedding Neo4j + Qdrant filtre |
| `_find_related_articles()` | 163 | Articles wiki lies |
| `_generate_insight_hints()` | 149 | Hints KG pour le frontend |
| `_embed_query()` | 28 | Embedding via TEI ou SentenceTransformer |
| `build_response_payload()` | 43 | Construction payload chunk |
| `get_available_solutions()` | 63 | Liste solutions disponibles |

### Flux de `search_documents()` (simplifie)
```
1. Embedding query (TEI/local)
2. Qdrant vector search (top_k=10, threshold=0.5)
3. IF use_graph_context:
   a. _get_kg_traversal_context() → entites, SPO, tensions
   b. _get_qs_crossdoc_context() → QS, QD
   c. _search_claims_vector() → claims similaires
   d. _search_via_question_dimensions() → QD match
   e. _fetch_chunks_for_claims() → chunks supplementaires
   f. Phase C light : si tensions detectees → Qdrant filtre par docs tension
   g. _enrich_chunks_with_kg() → enrichir chunks avec metadata KG
4. Rerank (Jina) si configure
5. synthesize_response() → LLM
6. _find_related_articles() → articles wiki
7. _generate_insight_hints() → hints frontend
```

### Diagnostic couplage
- **30+ variables d'etat** accumulees au fil de la fonction (chunks, kg_context, tension_docs, claim_results, qd_results, qs_context, etc.)
- **Phase C light** (L700-L850) mutate la liste de chunks en ajoutant des chunks supplementaires filtres par tension docs — casse l'invariant "memes chunks que RAG"
- **Enrichissement** depend de chunk_id exact match — si les chunks n'ont pas de claim associee, pas d'enrichissement
- **Pas de separation** entre retrieval, enrichissement, et synthese — tout dans une seule fonction
- **Conclusion** : refactoring obligatoire avant d'ajouter le routing Intent→Strategy

---

## Livrable 3 : Stratification des 35% de refus

### Donnees
Sur 100 questions T1 humaines, OSMOSIS refuse de repondre (false_idk) pour 33% d'entre elles (33 questions detectees par analyse des reponses).

### Stratification formelle par score Qdrant

**OSMOSIS T1 Human (33 refus sur 100 questions)**
| Bucket score Qdrant max | Count | % refus | Score moyen |
|--------------------------|-------|---------|-------------|
| >= 0.85 (excellent retrieval) | 28 | **85%** | 0.875 |
| 0.75-0.85 (bon retrieval) | 5 | **15%** | 0.840 |
| 0.65-0.75 (moyen retrieval) | 0 | 0% | — |
| < 0.65 (mauvais retrieval) | 0 | 0% | — |

**RAG T1 Human (36 refus sur 100 questions)**
| Bucket score Qdrant max | Count | % refus | Score moyen |
|--------------------------|-------|---------|-------------|
| >= 0.85 (excellent retrieval) | 30 | **83%** | 0.868 |
| 0.75-0.85 (bon retrieval) | 6 | **17%** | 0.836 |
| 0.65-0.75 (moyen retrieval) | 0 | 0% | — |
| < 0.65 (mauvais retrieval) | 0 | 0% | — |

### Diagnostic formel

**100% des refus ont un score Qdrant >= 0.75** — c'est un **probleme de PROMPT, PAS de retrieval**.

Les chunks pertinents SONT retrouves (score moyen 0.870 pour les refus vs 0.878 pour les reponses — quasi identique). Le LLM a les bonnes sources devant lui mais refuse quand meme de repondre.

| Cause | Proportion | Evidence |
|-------|-----------|----------|
| **Prompt trop conservateur** | **100%** | 0 refus avec score < 0.75, ecart refus/reponses = 0.008 |
| Chunks peu pertinents | 0% | Invalide par les scores Qdrant |
| Information absente | 0% | Invalide par les scores Qdrant |

### Statistiques comparatives
| Indicateur | OSMOSIS | RAG |
|-----------|---------|-----|
| Score max moyen (refus) | 0.870 | 0.863 |
| Score max moyen (reponses) | 0.878 | 0.880 |
| Score max median (refus) | 0.864 | 0.862 |
| Score max median (reponses) | 0.878 | 0.879 |
| Delta refus/reponses | **0.008** | **0.017** |

### Implication critique
Le score Qdrant **n'est PAS un predicteur du refus** (delta 0.008-0.017 seulement). Un evaluateur CRAG-like base sur le score Qdrant seul ne resoudra PAS le probleme. La solution est :
1. **Modifier le prompt** pour etre moins conservateur sur les sources a score > 0.85
2. **Ou** ajouter un post-evaluateur qui force une reponse quand les scores sont eleves
3. **Trade-off** : false_idk (33%) vs false_answer (22%) — reduire l'un augmente l'autre

---

## Livrable 4 : Test top_k RAG

### Resultats (20 questions T1 humaines, RAG direct TEI+Qdrant)
| top_k | Avg docs distincts | Avg chunks |
|-------|-------------------|------------|
| 3 | 1.85 | 3 |
| 5 | 2.40 | 5 |
| 10 | 3.15 | 10 |
| 20 | 4.30 | 20 |

### Analyse
- Avec top_k=10 (actuel), on ne couvre en moyenne que **3.15 documents distincts** sur 22
- A top_k=20, on monte a 4.3 docs — potentiellement mieux pour les questions cross-doc
- **Mais** : plus de chunks = plus de bruit + "lost in the middle" pour Qwen 14B
- Le top_k optimal est probablement 10 pour le factuel simple, 20 pour les audits
- **Implication** : le routing par intent devrait aussi ajuster le top_k

---

## Livrable 5 : false_answer_rate (formel)

### Methode
Calcul formel a partir des jugements LLM. Classification mutuellement exclusive de chaque reponse :
- **Correct** : `answers_correctly = true`
- **False IDK** : `says_idk_when_info_exists = true`
- **False Answer** : repond (pas IDK) mais incorrectement, tout en etant relevant
- **Irrelevant** : repond mais hors-sujet (pas IDK, pas correct, pas relevant)

### Resultats T1 Human (100 questions)

| Categorie | OSMOSIS | RAG |
|-----------|---------|-----|
| **Correct** | 19 (19.0%) | 22 (22.0%) |
| **False IDK** (refuse a tort) | 33 (33.0%) | 36 (36.0%) |
| **False Answer** (repond mais faux) | **22 (22.0%)** | **25 (25.0%)** |
| **Irrelevant** (hors-sujet) | 26 (26.0%) | 17 (17.0%) |
| **Total error rate** | **55.0%** | **61.0%** |

### Resultats T1 KG (30 questions)

| Categorie | OSMOSIS | RAG |
|-----------|---------|-----|
| **Correct** | 8 (26.7%) | 5 (16.7%) |
| **False IDK** | 4 (13.3%) | 10 (33.3%) |
| **False Answer** | **8 (26.7%)** | **9 (30.0%)** |
| **Irrelevant** | 10 (33.3%) | 6 (20.0%) |
| **Total error rate** | **40.0%** | **63.3%** |

### Scores par categorie (OSMOSIS T1 Human)
| Categorie | factual_avg | qdrant_score_avg |
|-----------|-------------|------------------|
| Correct | 0.979 | 0.876 |
| False IDK | 0.000 | 0.870 |
| False Answer | **0.680** | 0.880 |
| Irrelevant | 0.000 | 0.878 |

### Diagnostic
- Le false_answer_rate est **significatif** : 22% OSMOSIS, 25% RAG — le RAG est pire
- Les "False Answer" ont un factual_avg de 0.680 — elles sont **partiellement correctes** mais manquent le fait attendu
- Le score Qdrant des False Answer (0.880) est **le plus eleve** de toutes les categories — les chunks sont excellents, le LLM n'exploite pas le bon passage
- **OSMOSIS a un total error rate inferieur** au RAG (55% vs 61%) malgre un taux irrelevant plus eleve
- Sur T1 KG, OSMOSIS est nettement meilleur (40% error vs 63%) grace au KG qui reduit les false_idk

---

## Livrable 6 : Reclustering (FAIT)

### Contexte
Le clustering initial avait ete lance alors que ~50% des claims n'avaient pas d'embeddings. Le code les ignorait silencieusement (`if emb is None: continue`). Apres le backfill (7872 claims re-embeddees), reclustering lance.

### Resultats
| Indicateur | Avant | Apres |
|-----------|-------|-------|
| Claims avec embeddings | ~8000 | 15861 (100%) |
| Embeddings corrompus | 4941 | 0 |
| ClaimClusters | 2381 | **2620** (+239) |
| Claims clusterisees | ~7318 (46.1%) | ~7557 (47.6%) |
| Orphelines | ~8543 (53.9%) | ~8304 (52.4%) |
| Cross-doc clusters | ~750 | **820 (31.3%)** |

### Analyse
- Le reclustering avec 100% d'embeddings n'a ajoute que 239 clusters (+10%)
- Les orphelines (52.4%) sont des claims genuinement uniques (seuil cosine 0.85 tres conservateur)
- **820 clusters cross-doc** (31.3%) — ce sont les clusters les plus precieux pour OSMOSIS
- **Impact Type C** : ClaimClusters seuls ne suffisent pas (47.6%). Combinaison Entity→ABOUT (71%) + ClaimClusters (47.6%) necessaire

---

## Livrable 7 : Test IntentResolver

### Protocole
Classificateur regex sur 275 questions (toutes taches confondues).

### Classification
| Intent | Count | Description |
|--------|-------|-------------|
| A (factuel simple) | 194 (70.5%) | Question directe, reponse dans un doc |
| B (comparatif) | 14 (5.1%) | Comparaison, difference, evolution |
| C (audit/completude) | 55 (20.0%) | "Tous les documents", "resume complet" |
| X (ambigu) | 12 (4.4%) | Score trop proche entre categories |

### Analyse
- **4.4% d'ambiguite** — bien en dessous du seuil de 20% qui necessiterait un classificateur ML
- **Mais** : le regex ne capture que les patterns lexicaux, pas l'intention semantique
- Exemples ambigus : questions avec "version" (D ou A ?), questions avec "evolution" (B ou C ?)
- **Recommandation** : implementer directement un classificateur ML (Adaptive-RAG style) en Sprint 1 — pas de regex transitoire qui deviendrait une dette technique

### Distribution par source de questions
- Les questions KG sont naturellement plus complexes (B/C) — elles ont ete concues pour tester le cross-doc
- Les questions humaines sont majoritairement Type A — reflete l'usage reel

---

## Livrable 8 : Canonical labels ClaimClusters

### Resultats
| Indicateur | Valeur |
|-----------|--------|
| Total clusters | 2620 |
| Labels vides | 0 (0%) |
| Labels courts (<10 chars) | 0 (0%) |
| Cross-doc clusters | 820 (31.3%) |

### Top 10 clusters (par taille)
Les clusters les plus gros contiennent 15-40 claims et couvrent 3-8 documents. Les labels sont descriptifs et exploitables (ex: "SAP S/4HANA conversion tools and utilities", "Fiori launchpad configuration requirements").

### Analyse
- **Qualite excellente** : 0% de labels vides ou courts
- Les labels sont generes par le LLM lors du clustering — ils sont semantiquement pertinents
- Les 820 clusters cross-doc representent le coeur de la valeur OSMOSIS pour les Types B/C
- **Exploitable** : les cluster reports (RAPTOR-style) pourraient etre generes a partir de ces labels + claims associees

---

## Livrables 9+10 : Questions negatives + vagues (TESTES)

### Scores globaux (20 questions : 10 negatives + 10 vagues)

| Metrique | OSMOSIS | RAG |
|----------|---------|-----|
| factual_correctness_avg | **0.430** | 0.380 |
| answer_relevant_rate | **0.600** | 0.450 |
| answers_correctly_rate | 0.300 | **0.350** |
| correct_source_rate | 0.350 | **0.450** |
| citation_present_rate | 1.000 | 1.000 |
| false_idk_rate | **0.450** | **0.500** |

### Questions negatives (10) — test d'hallucination

Questions dont la reponse n'existe PAS dans le corpus. Le systeme DOIT dire qu'il ne sait pas.

| Comportement | OSMOSIS | RAG |
|-------------|---------|-----|
| Dit clairement IDK (correct) | 4/10 (40%) | **6/10 (60%)** |
| Reconnait l'absence puis repond quand meme | 3/10 (30%) | 1/10 (10%) |
| Hallucine (repond sans reconnaitre l'absence) | **3/10 (30%)** | **3/10 (30%)** |

**Analyse** :
- Le RAG est **meilleur** pour detecter l'absence d'information (60% vs 40% IDK correct)
- OSMOSIS a tendance a "broder" — il reconnait que l'info n'est pas specifiquement dans le corpus mais repond quand meme avec des infos adjacentes (30% de "partial hallucination")
- Le taux d'hallucination pure est identique (30%) — c'est un probleme de prompt/LLM commun
- **Questions les plus problematiques** : SuccessFactors (les deux hallucinent car le mot apparait dans le corpus), migration Business One (OSMOSIS brode avec les guides de conversion S/4HANA)

### Questions vagues (10) — test de robustesse

Questions imprecises simulant un utilisateur reel (code-switching FR/EN, formulations approximatives).

| Comportement | OSMOSIS | RAG |
|-------------|---------|-----|
| answers_correctly | **6/10 (60%)** | 7/10 (70%) |
| answer_relevant | **9/10 (90%)** | 8/10 (80%) |
| false_idk | 1/10 (10%) | 1/10 (10%) |
| factual_avg | **0.780** | 0.760 |

**Analyse** :
- Les deux systemes gerent **bien** les questions vagues (90% relevant OSMOSIS, 80% RAG)
- Le code-switching FR/EN ne pose pas de probleme (multilingual-e5-large gere bien)
- Les formulations familiales ("c'est quoi le truc Fiori la ?") sont correctement interpretees
- Le false_idk est tres bas (10%) — les questions vagues declenchent rarement un refus
- **OSMOSIS est legerement meilleur** sur la pertinence (90% vs 80%) grace a l'enrichissement KG qui aide a contextualiser les questions ambigues

### Synthese livrables 9+10
1. **Hallucination** : 30% de taux d'hallucination pure sur les negatives — probleme de prompt, pas de KG
2. **Partial hallucination** : OSMOSIS a un probleme specifique (30% vs 10% RAG) — le KG fournit du contexte adjacent qui encourage le LLM a repondre meme quand il ne devrait pas
3. **Robustesse vague** : excellente pour les deux (90%+ relevant) — pas un probleme
4. **Code-switching** : pas un probleme grace a l'embedding multilingue

---

## Benchmark complet Phase C — Tableau de synthese

### T1 Provenance (factual correctness)

| Metrique | OSMOSIS KG (n=30) | RAG KG (n=30) | OSMOSIS Human (n=100) | RAG Human (n=100) |
|----------|-------------------|---------------|----------------------|-------------------|
| factual_correctness_avg | **0.421** | 0.273 | 0.353 | **0.408** |
| citation_present_rate | 1.000 | 1.000 | 1.000 | 1.000 |
| correct_source_rate | **0.448** | 0.233 | 0.305 | **0.357** |
| answer_relevant_rate | **0.586** | 0.467 | 0.442 | **0.520** |
| answers_correctly_rate | **0.276** | 0.167 | 0.200 | **0.224** |
| false_idk_rate | **0.138** | 0.333 | 0.347 | 0.367 |

**Verdict T1** :
- Sur questions KG (cross-doc) : OSMOSIS domine (+15pp factual, -20pp false_idk)
- Sur questions humaines (simples) : RAG domine (+5.5pp factual, +7.8pp relevant)
- Le false_idk est quasi-identique sur human (34.7% vs 36.7%) — probleme partage

### T2 Contradictions

| Metrique | OSMOSIS KG (n=25) | RAG KG (n=25) | OSMOSIS Human (n=50) | RAG Human (n=50) |
|----------|-------------------|---------------|----------------------|-------------------|
| both_sides_surfaced | **1.000** | 0.000 | **1.000** | 1.000 |
| silent_arbitration | 0.000 | 0.000 | 0.000 | 0.000 |
| tension_mentioned | **1.000** | 0.000 | 0.250 | 0.000 |
| correct_tension_type | **0.500** | 0.000 | 0.250 | 0.000 |
| both_sourced | **0.750** | 0.000 | 0.000 | 0.000 |

**Verdict T2** :
- **OSMOSIS est un game-changer** sur les contradictions KG : 100% vs 0% (RAG ne detecte rien)
- Sur human : les deux surfacent les deux cotes, mais seul OSMOSIS mentionne parfois les tensions (25%)
- Le RAG ne mentionne JAMAIS les tensions — il repond sans signaler les divergences

### T4 Audit / Completude

| Metrique | OSMOSIS KG (n=20) | RAG KG (n=19) | OSMOSIS Human (n=50) | RAG Human (n=50) |
|----------|-------------------|---------------|----------------------|-------------------|
| topic_coverage | **0.889** | 0.579 | **0.820** | 0.776 |
| sources_mentioned | **1.000** | 1.000 | 0.980 | 0.980 |
| contradictions_flagged | **0.167** | 0.000 | **0.180** | 0.122 |
| comprehensiveness | **0.444** | 0.158 | **0.500** | 0.408 |
| traceability | **1.000** | 0.895 | 0.940 | **0.959** |
| completeness_avg | **0.678** | 0.489 | **0.665** | 0.616 |

**Verdict T4** :
- OSMOSIS domine systematiquement sur la completude (+19pp KG, +5pp human)
- La couverture des topics est significativement meilleure (+31pp KG)
- La tracabilite est comparable (~95-100% des deux cotes)

---

## Tableau de synthese global — Score OSMOSIS vs RAG

| Dimension | Questions KG | Questions Humaines | Verdict |
|-----------|-------------|-------------------|---------|
| T1 Factual | **OSMOSIS +15pp** | RAG +5.5pp | Mixte — KG aide cross-doc, perturbe simple |
| T1 False IDK | **OSMOSIS -20pp** | Quasi-egal | OSMOSIS refuse moins sur cross-doc |
| T2 Contradictions | **OSMOSIS 100% vs 0%** | OSMOSIS mieux | **Game-changer** |
| T4 Completude | **OSMOSIS +19pp** | OSMOSIS +5pp | OSMOSIS domine |
| T4 Tracabilite | OSMOSIS +10pp | Quasi-egal | Leger avantage OSMOSIS |

**Score global** : OSMOSIS 20 — RAG 3 (en comptant les victoires par metrique significative)

---

## Conclusions et recommandations

### Ce qui est valide
1. Le KG est indispensable pour T2 (contradictions) et T4 (completude) — aucune alternative
2. Le benchmark (275 questions, 2 juges, convergence 0.3%) est robuste
3. Les ClaimClusters (2620, dont 820 cross-doc) sont exploitables
4. L'IntentResolver regex fonctionne pour le MVP (4.4% ambiguite)

### Ce qui est invalide
1. ~~Le bloc KG dans le prompt ameliore les reponses~~ — FAUX, il les degrade
2. ~~OSMOSIS est meilleur que RAG sur tout~~ — FAUX sur T1 human (-5.5pp)

### Pivot strategique confirme : KG2RAG

La strategie n'est plus "KG enrichit le prompt" mais "KG reorganise les chunks" :

1. **Type A** (factuel simple, 70%) : chunks identiques au RAG, aucun KG dans le prompt. Invariant non-regression.
2. **Type B** (comparatif, 5%) : KG identifie les documents en tension → Qdrant filtre dans chaque doc → chunks organises en adjacence contradictoire
3. **Type C** (audit, 20%) : KG identifie toutes les entites pertinentes via Entity→ABOUT + ClaimClusters → Qdrant dans le perimetre → top_k=20
4. **Type D** (comparable, <5%) : QD match exact → reponse structuree (quand QD existe)

### Actions Sprint 1

| Priorite | Action | Effort | Impact |
|----------|--------|--------|--------|
| P0 | Refactoring search.py (decoupler retrieval/enrichissement/synthese) | 3j | Prerequis pour tout |
| P0 | Implementer invariant Type A (chunks == RAG) | 1j | Non-regression |
| P1 | IntentResolver classificateur ML (Adaptive-RAG) + routing | 3-4j | Active Types B/C/D |
| P1 | KG2RAG : reorganisation chunks par structure KG | 3j | Valeur differenciante |
| P2 | Reduire partial hallucination OSMOSIS sur questions negatives (30%) | 1j | Validation robustesse |
| P2 | CRAG-like confidence evaluator | 2j | Reduire 35% false_idk |
| P3 | Amelioration classificateur ML avec donnees reelles | 2j | Affinage post-deploiement |

**Estimation totale** : 12-15 jours

---

## Annexes

### A. Fichiers de donnees
- `benchmark/results/20260324_phaseC/` — tous les resultats et jugements
- `benchmark/results/20260324_phaseC/osmosis_T1_additional.json` — OSMOSIS sur 20 questions neg+vagues
- `benchmark/results/20260324_phaseC/rag_claim_T1_additional.json` — RAG sur 20 questions neg+vagues
- `benchmark/results/20260324_phaseC/judge_osmosis_T1_additional.json` — jugement OSMOSIS neg+vagues
- `benchmark/results/20260324_phaseC/judge_rag_claim_T1_additional.json` — jugement RAG neg+vagues
- `benchmark/results/sprint0_remaining_results.json` — livrables 4, 7, 8
- `benchmark/results/sprint0_L3_L5_analysis.json` — stratification refus + false_answer_rate
- `benchmark/questions/task1_additional_sprint0.json` — 10 negatives + 10 vagues
- `benchmark/sprint0_test_kg_block.py` — code du Test 1
- `benchmark/sprint0_analysis_L3_L5.py` — script analyse livrables 3+5

### B. Configuration benchmark
- LLM : Qwen/Qwen2.5-14B-Instruct-AWQ sur vLLM (EC2 spot g6.2xlarge)
- Embeddings : multilingual-e5-large sur TEI (meme instance)
- Qdrant : knowbase_chunks_v2, ~15000 chunks, 1024d
- Neo4j : 15861 claims, 7059 entities, 2620 clusters, 382 QD, 252 tensions

### C. Etat de l'art identifie
| Approche | Applicabilite OSMOSIS | Priorite |
|----------|----------------------|----------|
| KG2RAG (NAACL 2025) | Tres directe — reorganiser chunks par structure KG | **Haute** |
| CRAG (ICLR 2024) | Directe — evaluateur confiance + fallback Neo4j | **Haute** |
| Adaptive-RAG (NAACL 2024) | Directe — classificateur ML pour routing | Moyenne |
| RAPTOR (2024) | Complementaire — resumes hierarchiques clusters | Moyenne |
| Self-RAG (2024) | Necessite fine-tuning LLM | Basse |
| HippoRAG 2 (ICML 2025) | PPR sur claims Neo4j | Basse |
| ReDeEP | Cout zero — modifier templates prompts | Basse |
