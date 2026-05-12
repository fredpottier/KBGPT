# Analyse — Pollution du contexte KG dans la synthese OSMOSIS

**Date** : 3 avril 2026
**Statut** : Point de blocage architectural identifie
**Priorite** : CRITIQUE — affecte 66% des reponses T2 du benchmark

---

## 1. Contexte produit

OSMOSIS est une plateforme de verification documentaire qui combine :
- **RAG classique** : retrieval vectoriel (Qdrant, e5-large multilingual) + BM25 hybrid + reranking
- **Knowledge Graph** (Neo4j) : claims extraites des documents, relations cross-doc (CONTRADICTS, REFINES, QUALIFIES, CHAINS_TO, COMPLEMENTS, EVOLVES_TO), entites canoniques
- **Synthese LLM** : Haiku 3.5 (defaut) ou GPT-4o-mini/GPT-4o

L'architecture est "signal-driven" : le KG detecte des signaux (tensions, evolutions, chaines cross-doc) et les injecte dans le prompt de synthese en complement des chunks RAG.

**La promesse produit** : OSMOSIS apporte une qualite qu'un simple RAG ne peut pas offrir — detection de contradictions cross-doc, raisonnement transitif multi-documents, alertes proactives.

---

## 2. Probleme identifie

### 2.1 Constat quantitatif

Sur 125 questions T2 (contradictions) evaluees avec un LLM-juge aligne (GPT-4o-mini) :

| Categorie | Nombre | % |
|---|---|---|
| Bonnes reponses (juge >= 0.5) | 37 | 30% |
| Partielles (0 < juge < 0.5) | 6 | 5% |
| "No information available" | 60 | 48% |
| Hors-sujet (juge = 0, pas "no info") | 22 | 18% |

**82/125 reponses problematiques (66%).**

### 2.2 Diagnostic des "no information"

Sur 31 reponses "no information" analysees en detail :
- **22/31 (71%)** : le RAG echoue aussi → probleme de retrieval/corpus (pas lie au KG)
- **9/31 (29%)** : le RAG repond correctement mais OSMOSIS dit "no information" → **le KG degrade la reponse**

### 2.3 Diagnostic des hors-sujet

22 reponses completement hors-sujet ou le LLM repond a une question differente de celle posee. Pattern typique : la question porte sur le sujet X, mais les chaines KG injectees parlent du sujet Y, et le LLM reformule les chaines Y au lieu de repondre sur X.

### 2.4 Tests de confirmation

#### Test A : Meme question, KG active vs desactive (Haiku)

Question : "Quel est le nom officiel du produit : SAP S/4HANA Cloud Private Edition ou SAP Cloud ERP ?"

| Mode | Resultat |
|---|---|
| **Sans KG** | Reponse parfaite en francais : "SAP S/4HANA Cloud Private Edition est la version de base, SAP Cloud ERP est le nom commercial" (2033 chars, concis, pertinent) |
| **Avec KG** | Hors-sujet : parle de "Central Procurement Integration" (5641 chars, verbeux, ne repond pas a la question) |

Les chunks retrieves sont **identiques** dans les deux cas (15 chunks pertinents du doc 023). C'est le bloc KG injecte (1740 chars, 4 chaines cross-doc) qui detourne le LLM.

#### Test B : Meme question avec KG, Haiku vs GPT-4o

| Modele | Resultat |
|---|---|
| **Haiku + KG** | Hors-sujet : "Central Procurement Integration" |
| **GPT-4o + KG** | Hors-sujet : "Central Procurement Integration" (meme erreur) |
| **Haiku sans KG** | Reponse parfaite |

**Conclusion : le probleme n'est pas le modele. Meme GPT-4o suit les chaines KG hors-sujet.** La presence du texte KG structure biaise la generation quelle que soit la capacite du LLM.

#### Test C : Question de retrieval vide

Question : "Dans quel cas les IDocs sont-ils envoyes au systeme Dispute Case Processing ?"

| Mode | Chunks | Resultat |
|---|---|---|
| RAG pur (benchmark) | 10 | Reponse correcte sur les IDocs, juge = 1.0 |
| OSMOSIS (benchmark) | 10 | "No information available", juge = 0.0 |
| OSMOSIS (live, post-fix) | 0 | Zero resultats |

Ce cas combine deux problemes : les chunks retrieves parlent bien du sujet mais le KG injecte un contexte qui fait dire au LLM "no information" malgre la presence des chunks pertinents.

---

## 3. Architecture actuelle du pipeline de synthese

### 3.1 Flux de donnees

```
Question utilisateur
    |
    v
[Embedding e5-large] → query_vector
    |
    +--→ [Qdrant hybrid search] → 10-15 chunks (dense + BM25 + RRF)
    |
    +--→ [Neo4j claims vector search] → kg_claim_results
    |         |
    |         +--→ [_build_kg_context_block] → "Reading instructions" (tensions, complements)
    |
    +--→ [Neo4j CHAINS_TO traversal 1-3 hops] → kg_chains_text (markdown, ~1500-2000 chars)
    |         |
    |         +--→ [Qdrant recherche ciblee sur chain_doc_ids] → 5 chunks supplementaires
    |
    +--→ [Neo4j QS cross-doc comparison] → qs_crossdoc_text (evolutions, contradictions)
    |
    v
[Prompt de synthese] = SYSTEM_MSG + chunks + kg_context_block + kg_chains_text + qs_crossdoc_text
    |
    v
[LLM (Haiku)] → reponse
```

### 3.2 Structure du prompt de synthese

Le prompt envoye au LLM contient dans cet ordre :
1. **System message** (regles generales)
2. **Question utilisateur**
3. **Chunks RAG** (textes bruts des documents)
4. **Bloc KG** concatene :
   - `kg_context_block` : "Reading instructions" (tensions detectees)
   - `kg_chains_text` : "Cross-document reasoning" (chaines CHAINS_TO)
   - `qs_crossdoc_text` : "Cross-document comparisons" (QuestionSignatures)

### 3.3 Regles du prompt (problematiques)

Avant correction (regles actives pendant les benchmarks) :

```
Rule 0: "Available sources are your PRIMARY evidence"
Rule 2: "Cross-document chains are THE MAIN answer — structure your answer around 
         these chains (not around individual chunks)"
Rule 9: "Cross-document comparisons are verified facts — do NOT ignore them"
```

**Les regles 2 et 9 contredisent la regle 0.** Le LLM recoit l'instruction de prioriser les chaines KG sur les chunks RAG.

Apres correction (appliquee mais insuffisante) :

```
Rule 2: "supplementary fact chains... Use ONLY if relevant... 
         IGNORE if off-topic"
Rule 9: "Include ONLY when relevant... IGNORE if not related"
```

**Le changement de formulation ne suffit pas** — meme avec "ignore if off-topic", la presence physique du bloc KG (1500+ chars structures) influence le LLM.

### 3.4 Contenu typique du bloc KG injecte

Pour la question "nom officiel du produit", le bloc KG contenait :

```
## Cross-document reasoning (supplementary notes)
The following fact chains were detected across multiple documents.
Use them ONLY if relevant to the user's question. Ignore if off-topic.

**Chaine cross-document (2 etapes)** — via SAP S/4HANA Cloud Private Edition
  • Central Procurement hub system integrates with... (source: Feature Scope Description)
  → Approval process triggers purchase order... (source: Business Scope 2025)

**Chaine cross-document (2 etapes)** — via SAP S/4HANA Cloud Private Edition
  • Connected systems share requisitions... (source: Installation Guide)
  → Freight order creation follows... (source: Admin Guide)

[... 2 autres chaines similaires]
```

Ces chaines sont factuellement correctes mais **non pertinentes** pour la question posee. L'entite "SAP S/4HANA Cloud Private Edition" matche la question (le terme apparait) mais les claims associees parlent de procurement, pas de nomenclature produit.

---

## 4. Cause racine

### 4.1 Matching trop large des entites

Le traversal KG extrait des entites candidates par regex :
- Acronymes : `[A-Z]{2,}` → attrape "SAP", "ERP", etc.
- Termes capitalises : `[A-Z][A-Za-z]+` → attrape "Cloud", "Private", "Edition"
- Combinaison : "SAP S/4HANA Cloud Private Edition" est un candidat

Puis il cherche les claims `ABOUT` cette entite et traverse les `CHAINS_TO`. Le probleme : une entite comme "SAP S/4HANA Cloud Private Edition" est mentionnee dans des centaines de claims couvrant tous les sujets du produit. Les chaines retournees sont celles avec le plus de hops cross-doc, pas celles les plus pertinentes pour la question.

### 4.2 Pas de filtrage de pertinence des chaines

Actuellement :
1. Les chaines sont selectionnees par **topologie** (nombre de docs distincts, cross-doc, hops) via le ORDER BY Cypher
2. Il n'y a **aucun filtrage semantique** entre le contenu des chaines et la question posee
3. Toutes les chaines retournees sont injectees dans le prompt (limite a 3 apres notre correction, mais 3 chaines non pertinentes = 3 x bruit)

### 4.3 Le format d'injection cree un biais cognitif

Le bloc KG est structure en markdown avec des titres ("Cross-document reasoning"), des bold, des fleches. Les chunks RAG sont du texte brut. Le LLM donne naturellement plus de poids au contenu structure.

Papier confirmatif : "Context Length Alone Hurts LLM Performance" (EMNLP 2025) — etendre le contexte degrade le raisonnement meme quand l'evidence pertinente est recuperee.

---

## 5. Benchmark OSMOSIS vs RAG — Resultats finaux

### 5.1 Configuration

- **OSMOSIS** : Haiku 3.5 + KG complet (claims, traversal CHAINS_TO, QS cross-doc)
- **RAG** : Haiku 3.5, memes chunks Qdrant, zero KG
- **Evaluateur** : hybrid (keyword pour tension/sources/multi_doc/proactive, LLM-juge GPT-4o-mini pour both_sides_surfaced et chain_coverage)
- **Questions** : 125 T2 (contradictions) + 25 T5 (KG differentiators) = 150

### 5.2 Resultats

| Metrique | OSMOSIS | RAG | Delta | Commentaire |
|---|---|---|---|---|
| both_sides_surfaced | 30.1% | 34.9% | -4.8pp | KG pollue — RAG fait mieux |
| tension_mentioned | **100%** | 94.4% | **+5.6pp** | OSMOSIS detecte mieux les tensions |
| both_sources_cited | **83.2%** | 53.2% | **+30.0pp** | KG identifie les bons documents |
| chain_coverage | 45.0% | 58.0% | -13.0pp | KG dilue la couverture des aspects |
| multi_doc_cited | **81.5%** | 67.7% | **+13.8pp** | KG cite plus de documents |
| proactive_detection | **100%** | 80.0% | **+20.0pp** | KG detecte les contradictions cachees |
| **Score global** | **73.3%** | **64.7%** | **+8.6pp** | OSMOSIS gagne globalement |

### 5.3 Analyse

**OSMOSIS gagne sur 4/6 metriques** : tension detection, citation sources, multi-doc, proactive detection. Ce sont les metriques de "decouverte" — le KG trouve les bons documents et les bonnes tensions.

**OSMOSIS perd sur 2 metriques** : both_sides_surfaced et chain_coverage. Ce sont les metriques de "qualite de la reponse" — le LLM ne presente pas bien l'information malgre des chunks pertinents.

**Paradoxe** : le KG ameliore le retrieval (trouve les bons docs) mais degrade la synthese (le LLM se perd dans le contexte KG).

---

## 6. Etat de l'art — Comment les systemes GraphRAG adressent ce probleme

### 6.1 Microsoft GraphRAG / DRIFT

- 3 modes (Local, Global, DRIFT hybride) avec **routage par type de question**
- DRIFT ne met jamais toutes les community summaries dans un seul prompt
- Selectionne les top-K les plus pertinentes, genere des follow-ups specifiques
- **Pattern cle** : chaque etape a un scope limite

### 6.2 RAGate (arXiv 2407.21712)

- **Gate binaire** qui predit si le RAG/KG est necessaire pour un tour de conversation
- Correle la confiance de generation avec la pertinence du contexte
- Si le modele est deja confiant → pas d'injection KG

### 6.3 KG2RAG (NAACL 2025)

- Convertit le sous-graphe en graphe non-dirige pondere (poids = similarite query-chunk)
- Genere le **Maximum Spanning Tree** pour eliminer les aretes redondantes
- Reranque avec un cross-encoder
- **Pattern cle** : filtrage structurel avant injection

### 6.4 AttentionRAG (2025)

- Utilise les patterns d'attention du LLM pour identifier les tokens importants
- **Compression 6.3x** sans perte de performance
- Garde uniquement les phrases contenant les tokens a haute attention

### 6.5 UnWeaver (2025)

- Resultat contre-intuitif : VectorRAG enrichi par entites (sans graphe explicite) **bat** GraphRAG
- **Pattern** : enrichir les chunks eux-memes avec les metadonnees KG plutot qu'un bloc separe
- Evite le probleme de "deux sources d'autorite en competition"

### 6.6 "When to Use Graphs in RAG" (2025)

- GraphRAG genere jusqu'a 40 000 tokens de community summaries vs ~900 pour du RAG standard
- Sur les taches de fact retrieval simple, le RAG basique egalise ou depasse GraphRAG
- **Conclusion** : le graphe n'apporte de la valeur que sur les questions multi-hop et les syntheses globales

### 6.7 LDAR — Distraction-Aware Retrieval (2025)

- Des passages qui donnent individuellement la bonne reponse peuvent **collectivement induire une reponse fausse** quand injectes ensemble
- Avec 47% des tokens, on obtient de meilleurs scores qu'avec le contexte complet (70.0 vs 58.6)

---

## 7. Options envisagees

### Option A : Routeur de complexite (questions simples → RAG pur)

**Principe** : classifier chaque question avant le pipeline. Les questions fact retrieval (70-80%) → RAG pur sans KG.

- **Avantage** : quick win, protege les questions simples
- **Limite** : ne resout pas le probleme pour les questions complexes ou le KG est cense apporter de la valeur
- **Effort** : 0.5j (l'IntentResolver 2-passes existe deja)

### Option B : Filtrage semantique des chaines KG

**Principe** : avant injection, scorer chaque chaine KG par cosine similarity avec la question. N'injecter que les chaines dont le score depasse un seuil.

- **Avantage** : resout le probleme racine (chaines non pertinentes filtrees)
- **Limite** : necessite un embedding supplementaire par chaine. Risque de filtrer des chaines pertinentes mais formulees differemment.
- **Effort** : 1j

### Option C : Enrichissement inline (pattern UnWeaver)

**Principe** : au lieu d'un bloc KG separe, enrichir les chunks eux-memes avec les metadonnees KG (entite canonique, relations cles). Le LLM ne voit qu'un seul flux de contenu.

- **Avantage** : elimine le probleme de "deux sources d'autorite en competition"
- **Limite** : refactoring plus lourd, les relations multi-hop sont difficiles a representer inline
- **Effort** : 2-3j

### Option D : Two-pass synthesis (generation puis verification)

**Principe** : 
1. Pass 1 : generer la reponse avec les chunks RAG uniquement
2. Pass 2 : un second appel LLM verifie/enrichit avec le contexte KG ("cette reponse est-elle coherente avec les signaux KG ? si le KG revele des tensions pertinentes, ajoute-les")

- **Avantage** : la reponse de base est toujours pertinente (RAG pur), le KG ne peut qu'enrichir
- **Limite** : double le cout LLM, ajoute de la latence
- **Effort** : 1.5j

### Option E : KG comme post-processing (Insight Cards)

**Principe** : ne pas injecter le KG dans le prompt de synthese du tout. Le LLM genere une reponse RAG pure. Les signaux KG (tensions, evolutions) sont affiches dans des **Insight Cards** separees dans l'UI, pas dans la reponse textuelle.

- **Avantage** : zero risque de pollution. La reponse est toujours pertinente. Les insights KG sont visibles mais ne contaminent pas la synthese.
- **Limite** : perd la capacite de "reponse enrichie" — le KG informe l'utilisateur mais ne modifie pas la reponse. Les tensions ne sont pas integrees dans le texte.
- **Effort** : 1j (les Insight Cards sont deja designees dans le chantier refonte chat)
- **Note** : c'est le design deja prevu dans `doc/ongoing/CHANTIER_REFONTE_CHAT.md` section 10

### Option F : Hybride (B + D) — Filtrage + Two-pass conditionnel

**Principe** :
1. Toujours generer la reponse RAG pure (pass 1)
2. Si le KG a des signaux **et** que les chaines passent le filtre de pertinence → enrichir en pass 2
3. Si aucun signal pertinent → reponse RAG seule

- **Avantage** : combine securite (RAG pur comme base) et valeur (KG quand pertinent)
- **Limite** : complexite d'implementation, cout LLM conditionnel
- **Effort** : 2j

---

## 8. Questions ouvertes

1. **Le filtrage semantique (Option B) suffit-il ?** Si les chaines KG passent le filtre mais sont quand meme "trop presentes" dans le prompt, le LLM peut encore etre biaise.

2. **Le two-pass (Option D) est-il viable en latence ?** Si la reponse passe de 8s a 16s, c'est problematique pour l'UX.

3. **L'enrichissement inline (Option C) est-il compatible avec notre architecture ?** Les chaines CHAINS_TO sont des relations multi-hop — difficile a representer dans un chunk individuel.

4. **L'Option E (KG post-processing) est-elle suffisante commercialement ?** Si le KG n'enrichit pas la reponse textuelle, la valeur ajoutee n'est visible que via les Insight Cards. Est-ce assez pour differencier OSMOSIS d'un RAG classique ?

5. **Peut-on combiner les options ?** Par exemple : routeur (A) + filtrage (B) + Insight Cards (E) pour les signaux qui ne passent pas le filtre.

---

## 9. Code concerne

| Fichier | Role | Lignes cles |
|---|---|---|
| `src/knowbase/api/services/search.py` | Pipeline principal | L889-950 (KG injection), L1869-2112 (traversal CHAINS_TO) |
| `src/knowbase/api/services/synthesis.py` | Prompt de synthese | L67-120 (rules 0-12), L278-330 (synthesize_response) |
| `src/knowbase/api/services/kg_signal_detector.py` | Detection des signaux | L58-150 (detect_signals) |
| `src/knowbase/api/services/signal_policy.py` | Politique d'injection | L20-90 (build_policy) |
| `config/synthesis_prompts.yaml` | Prompts par provider | rule_7_override per provider |
| `benchmark/evaluators/t2t5_diagnostic.py` | Evaluateur benchmark | evaluate_t2, evaluate_t5, LLM-juge |

---

## 10. Modifications deja realisees (cette session)

1. **Prompt synthesis.py** : Rule 2 "THE MAIN answer" → "supplementary, ignore if off-topic". Rule 9 : idem.
2. **search.py** : Header KG "IMPORTANT, Tu DOIS" → "supplementary notes, ignore if off-topic"
3. **search.py** : Limite 3 chaines cross-doc injectees (au lieu de 15)
4. **search.py** : Limite 3 entites canoniques
5. **t2t5_diagnostic.py** : LLM-juge integre nativement, aligne OSMOSIS et RAG
6. **t2t5_diagnostic.py** : Fix chemin `/data` pour persistance des rapports
7. **query_decomposer.py** : Nouveau module de decomposition multi-facettes (pas encore valide)

**Resultat de ces modifications** : insuffisant. Le test avec "supplementary, ignore if off-topic" montre que GPT-4o et Haiku suivent quand meme les chaines KG non pertinentes.
