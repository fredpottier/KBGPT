# ADR — Architecture d'injection KG V2 : Two-Pass Conditional Synthesis

**Date** : 3 avril 2026
**Statut** : PROPOSITION — en attente de validation
**Auteurs** : Claude (analyse code + architecture), ChatGPT (litterature + plan strategique), Fred (direction produit)
**Priorite** : CRITIQUE — prerequis pour la qualite produit OSMOSIS

---

## 1. Decision

**Adopter une architecture "Two-Pass Conditional Synthesis"** ou :
- **Pass 1** : synthese RAG pure (chunks uniquement, zero KG) — streame au client
- **Pass 2** : enrichissement KG conditionnel — produit des **Insight Cards** (cartes UI separees) ajoutees apres la reponse
- **Gate** : heuristique + scoring semantique decidant si Pass 2 s'execute
- **Scoring** : filtrage cosine + cross-encoder pour eliminer les chaines KG non pertinentes

Le KG n'est **jamais injecte dans le prompt de synthese**. Il est traite dans un pipeline parallele et restitue via l'UI.

---

## 2. Contexte et probleme

### 2.1 Constat quantitatif

Sur 125 questions T2 evaluees (benchmark FINAL_ALIGNED_JUDGE) :
- **66% de reponses problematiques** (48% "no information", 18% hors-sujet)
- **9 cas** ou le RAG repond correctement mais OSMOSIS echoue → le KG degrade la reponse
- **22 cas** hors-sujet ou le LLM suit les chaines KG au lieu de repondre a la question

### 2.2 Preuve experimentale

| Test | Resultat |
|---|---|
| Question "nom officiel du produit" — sans KG (Haiku) | Reponse parfaite, 2033 chars, en francais |
| Meme question — avec KG (Haiku) | Hors-sujet "Central Procurement", 5641 chars |
| Meme question — avec KG (GPT-4o) | Meme hors-sujet "Central Procurement" |

**Le probleme est independant du modele.** La cause est le contenu injecte.

### 2.3 Cause racine identifiee

1. **Matching trop large** : l'entite "SAP S/4HANA Cloud Private Edition" matche des centaines de claims sur tous les sujets
2. **Selection topologique** : les chaines sont triees par cross-doc/hops, pas par pertinence question-reponse
3. **Biais de format** : le markdown structure (titres, bold, fleches) domine les chunks RAG bruts dans l'attention du LLM
4. **Budget non applique** : `MAX_KG_INJECTION_TOKENS = 150` est defini mais jamais enforce — le KG injecte 1000-1550 tokens
5. **Instructions contradictoires** : Rule 0 dit "sources are PRIMARY" mais Rule 2 disait "chains are THE MAIN answer"

### 2.4 Litterature confirmative

| Source | Conclusion cle |
|---|---|
| "Context Length Alone Hurts" (EMNLP 2025) | La longueur du contexte degrade la performance meme avec retrieval parfait |
| "When to Use Graphs in RAG" (2025) | Sur le fact retrieval simple, RAG egalise ou depasse GraphRAG |
| LDAR (2025) | Avec 47% des tokens, meilleurs scores qu'avec le contexte complet |
| UnWeaver (2025) | VectorRAG enrichi par entites bat GraphRAG sur 3 benchmarks |
| KG2RAG (NAACL 2025) | Organisation KG-guidee en paragraphes plutot que dump de chaines |
| RAGate (2024) | Gate binaire predisant si l'augmentation RAG/KG est necessaire |

---

## 3. Architecture cible

### 3.1 Vue d'ensemble

```
Question utilisateur
    |
    v
┌──────────────────┐
│   Intent Gate    │  < 1ms, heuristique
│   (signal check) │
└──┬───────────┬───┘
   │           │
   │ toujours  │ si gate=true
   │           │
┌──▼──────┐  ┌─▼──────────────┐
│ Pass 1  │  │ KG Relevance   │   PARALLELE
│ RAG-only│  │ Scoring        │
│ (Haiku) │  │ (cosine+xenc)  │
│ STREAM  │  │ 20-80ms        │
└──┬──────┘  └──┬─────────────┘
   │             │
   │    signals_pertinents > 0 ?
   │        │ non         │ oui
   │        │             │
   │   [FIN]         ┌────▼──────────┐
   │                 │   Pass 2      │
   │                 │   Enrichment  │
   │                 │   (Haiku)     │
   │                 │   → JSON cards│
   │                 └────┬──────────┘
   │                      │
   v                      v
┌─────────────────────────────────────┐
│         Response Assembly           │
│  answer: Pass 1 (texte streame)     │
│  enrichments: [] | [Insight Cards]  │
└─────────────────────────────────────┘
```

### 3.2 Principe fondamental

> **Le KG n'entre jamais dans le prompt de synthese.**
> Pass 1 = RAG pur. Pass 2 = cartes UI separees.
> Le LLM ne peut pas "deriver" sur le KG car il ne le voit jamais.

### 3.3 Latence

```
t=0      ┬─ Pass 1 streaming (Haiku) ─────────────► tokens au client
         ├─ KG Scoring (cosine+cross-encoder) ─┐
         │                                      │
t=~80ms  │                       Scoring done ──┘
         │                                │
t=~8s    │  Pass 1 terminee               │ (resultats prets depuis longtemps)
         │                     pertinents > 0 ?
         │                      │ oui
         │                 ┌────▼─────┐
         │                 │  Pass 2  │ ~3s
         │                 │  (Haiku) │
         │                 └────┬─────┘
         │                      │
t=~11s   │◄────────────────────┘
         │  Append Insight Cards via SSE
         ▼
```

| Scenario | Latence percue |
|---|---|
| Sans Pass 2 (70-80% des requetes) | ~8s (identique a aujourd'hui) |
| Avec Pass 2 | 8s streaming + 3s cards en background = **11s total** |

---

## 4. Composants detailles

### 4.1 Intent Gate (heuristique, zero LLM)

Decide si Pass 2 doit s'executer. Conditions :

| Condition | Decision | Raison |
|---|---|---|
| 0 signaux KG detectes | SKIP | Rien a enrichir |
| Signaux tous < 0.6 confiance | SKIP | Trop bruites |
| >= 1 contradiction/tension (confiance >= 0.6) | **RUN** | Proposition de valeur OSMOSIS |
| >= 1 signal cross-doc dont >= 1 doc dans RAG | **RUN** | Enrichissement probable |
| Question factuelle simple + 0 contradiction | SKIP | RAG suffit |

**Les contradictions passent toujours** : c'est LE differenciateur. L'utilisateur ne sait pas qu'un doc contredit un autre — c'est exactement ce que le KG apporte.

### 4.2 KG Relevance Scoring (pipeline 2 etapes, 20-80ms)

**Etape 1 — Filtre cosine (elimine 60-70% des chaines)**

```python
def cosine_filter(question, chains, entity_name, threshold=0.38):
    # CRITIQUE : retirer le nom d'entite pour eviter le biais
    q_clean = question.replace(entity_name, "").strip()
    q_emb = embed(q_clean)
    survivors = []
    for chain in chains:
        chain_text = " -> ".join(c.text for c in chain.claims)
        chain_clean = chain_text.replace(entity_name, "").strip()
        sim = cosine(q_emb, embed(chain_clean))
        if sim > threshold:
            survivors.append(chain)
    return survivors
```

**Mitigation du biais d'entite** : le nom de l'entite ("SAP S/4HANA Cloud Private Edition") gonfle artificiellement le cosine car il apparait dans la question ET dans toutes les chaines. En le retirant des deux cotes, on force la comparaison sur la semantique reelle.

**Etape 2 — Cross-encoder reranking (sur survivants)**

- Modele recommande : `cross-encoder/ms-marco-MiniLM-L-6-v2` (22M params, ~15ms/paire CPU)
- Alternative multilingue : `BAAI/bge-reranker-v2-m3`
- Seuil : score > 0.5 (sigmoid)
- **Exception contradictions** : seuil abaisse a 0.3 (on veut du recall)

**Pourquoi pas un LLM pour le scoring** : 200-400ms par appel x 10 chaines = 2-4s. Inacceptable en temps reel. Le cross-encoder fait le meme travail en 50-150ms total.

### 4.3 Pass 1 — Synthese RAG pure

Prompt simplifie, zero mention du KG :

```
Tu es un expert qui repond aux questions en t'appuyant UNIQUEMENT
sur les extraits de documents fournis.

Regles :
- Reponds directement a la question posee
- Cite les documents sources
- Si les extraits ne contiennent pas assez d'information, dis-le
- Reponds dans la meme langue que la question
```

**Ce qui change par rapport a aujourd'hui** : suppression des Rules 2 (cross-doc chains), 9 (cross-doc comparisons), et toute mention de "Reading instructions", "Knowledge Graph", "tensions". Le LLM ne sait meme pas que le KG existe.

### 4.4 Pass 2 — Enrichissement en cartes structurees

Pass 2 ne reecrit PAS la reponse. Il produit des **cartes JSON** :

```json
[
  {
    "type": "contradiction",
    "title": "Divergence sur le protocole TLS",
    "body": "Le Security Guide 2022 accepte TLS 1.2, le Security Guide 2023 exige TLS 1.3.",
    "sources": ["Security Guide 2022 (p.45)", "Security Guide 2023 (p.52)"],
    "severity": "high"
  },
  {
    "type": "evolution",
    "title": "Changement de nom produit",
    "body": "SAP S/4HANA Cloud Private Edition renomme en SAP Cloud ERP Private Edition en 2025.",
    "sources": ["Feature Scope 2023", "Business Scope 2025"],
    "severity": "medium"
  }
]
```

**Prompt Pass 2** :

```
Tu es un analyste documentaire. On te donne :
1. Une question utilisateur
2. Une reponse deja produite a partir d'extraits RAG
3. Des signaux pertinents issus d'un graphe de connaissances

Ta tache : pour chaque signal, produis une carte d'enrichissement concise.
Tu ne modifies PAS la reponse existante. Tu produis des complements.

Regles :
- severity=high : contradiction directe affectant la reponse
- severity=medium : evolution ou nuance importante
- severity=low : complement contextuel
- Si un signal n'apporte RIEN de nouveau, EXCLUS-le
- Maximum 3 cartes, priorise par severity
- Reponds en JSON array uniquement
```

**Pourquoi des cartes et pas une reecriture** :
1. La reponse Pass 1 est deja streamee → pas de reecriture possible
2. Les cartes sont visuellement distinctes → l'utilisateur comprend le complement KG
3. **Zero risque de pollution** : le LLM ne peut pas "deriver" car il reformule des signaux pre-valides, il ne raisonne pas

### 4.5 Response Assembly (SSE/WebSocket)

```python
@dataclass
class SynthesisResponse:
    answer: str                          # Pass 1
    enrichments: list[EnrichmentCard]    # Pass 2 (peut etre vide)
    metadata: SynthesisMetadata

@dataclass
class EnrichmentCard:
    type: str        # "contradiction" | "evolution" | "complement"
    title: str
    body: str
    sources: list[str]
    severity: str    # "high" | "medium" | "low"
```

Cote frontend : la reponse streame normalement. Quand les cartes arrivent (evenement SSE `enrichments`), elles apparaissent sous la reponse avec une animation slide-in.

---

## 5. Points d'insertion dans le code actuel

L'analyse du code revele 5 "seams" architecturales exploitables :

| Seam | Localisation | Modification |
|---|---|---|
| **Policy Gate** | signal_policy.py:58-196 | Ajouter seuils de strength + pertinence |
| **Chain Materialization** | search.py:945-1005 | Remplacer injection directe par scoring + cartes |
| **QS Selection** | search.py:1050-1057 | Seuil confiance + pertinence |
| **Token Budget** | signal_policy.py:20 | **ENFORCER** le budget (actuellement defini mais non applique) |
| **Prompt Integration** | synthesis.py:322-328 | Supprimer `{graph_context}` du prompt Pass 1 |

### 5.1 Decouverte critique : budget non enforce

`MAX_KG_INJECTION_TOKENS = 150` est defini a la ligne 20 de signal_policy.py mais **aucune troncature ou comptage de tokens** n'a lieu avant l'injection. En pratique, le KG injecte **1000-1550 tokens** — un depassement de 6-10x.

### 5.2 Infrastructure existante exploitable

| Brique | Etat | Extension |
|---|---|---|
| Signal strengths (0.0-1.0) | Existe | Utiliser comme seuils de gate |
| Chain quality metrics | Existe | Utiliser comme pre-filtres |
| Contradiction envelope + fallback | Existe | Patron a generaliser |
| Token tracking | Existe (par modele) | Ajouter tracking par composant (chunks vs KG) |
| IntentResolver 2-passes | Existe | Utiliser pour classifier questions simples/complexes |

---

## 6. Cout LLM

| Composant | Input tokens | Output tokens | Cout estime |
|---|---|---|---|
| Pass 1 (RAG synthesis) | ~3000 | ~500 | ~$0.004 |
| Scoring (cosine + cross-encoder) | 0 | 0 | ~$0.000 (pas de LLM) |
| Pass 2 (enrichment cards) | ~1500 | ~300 | ~$0.002 |
| **Total sans Pass 2** | | | **~$0.004** |
| **Total avec Pass 2** | | | **~$0.006** |
| **Cout actuel (single-pass)** | | | **~$0.005** |

L'overhead est marginal (+20% quand Pass 2 s'execute, 0% sinon).

---

## 7. Comparaison avec les alternatives rejetees

| Option | Avantage | Raison du rejet |
|---|---|---|
| **Patch prompt** ("ignore if off-topic") | Zero effort | Prouve insuffisant — GPT-4o suit quand meme les chaines |
| **Filtrage seul** (scoring sans two-pass) | Simple | Ne resout pas le biais de format — le KG structure dans le prompt domine toujours |
| **Reecriture Pass 2** (rewrite answer) | Reponse enrichie "native" | Reintroduit le risque de pollution — le LLM re-pondere le KG vs la reponse |
| **KG sidecar pur** (zero Pass 2 LLM) | Zero cout LLM additionnel | Perd la capacite de reformuler les signaux KG en langage utilisateur |
| **Enrichissement inline** (pattern UnWeaver) | Elimine le double canal | Refactoring lourd, les relations multi-hop sont difficiles a representer inline |

**L'architecture two-pass + cartes** est le seul design qui :
1. Garantit une reponse RAG toujours pertinente (Pass 1)
2. Preserve la valeur KG (contradictions, evolutions) via les cartes
3. Elimine physiquement le risque de pollution (le KG ne touche jamais le prompt)
4. Reste compatible avec le streaming existant
5. A un cout marginal

---

## 8. Strategie de validation

### 8.1 Metriques de succes

| Metrique | Baseline actuel | Cible | Methode |
|---|---|---|---|
| Taux "no info faux" (RAG OK mais OSMOSIS KO) | 7.2% (9/125) | < 1% | Benchmark T2 avec juge |
| Taux hors-sujet | 17.6% (22/125) | < 3% | Benchmark T2 avec juge |
| both_sides_surfaced | 30.1% | > 60% | LLM-juge aligne |
| tension_mentioned | 100% | >= 95% | Keyword (stable) |
| proactive_detection | 100% | >= 90% | Keyword (stable) |
| Latence p95 | ~12s | < 15s | Monitoring |

### 8.2 Tests de validation

| Test | Ce qu'il valide | Methode |
|---|---|---|
| **Ablation KG** | Pass 1 = RAG pur fonctionne | Comparer Pass 1 seul vs ancien single-pass |
| **Gate precision** | Le gate laisse passer les contradictions | 25 questions T2 contradiction → gate=true sur >= 90% |
| **Scoring recall** | Le scoring garde les chaines pertinentes | 10 chaines manuellement annotees → recall >= 80% |
| **Cards quality** | Les cartes sont pertinentes et concises | LLM-juge sur 50 cartes generees |
| **Non-regression** | Pas de perte sur questions simples | 100 questions T1 factual → score stable |
| **Distractor injection** | Robustesse aux chaines KG hors-sujet | 20 chaines volontairement off-topic → 0 pollution |

### 8.3 Rollout

1. **Feature flags** : `KG_TWO_PASS=true/false`, `KG_SCORING_THRESHOLD=0.5`, `KG_PASS2_ENABLED=true/false`
2. **Canary** : activer sur le benchmark d'abord, puis sur le chat
3. **Rollback** : retour a `KG_TWO_PASS=false` = comportement actuel

---

## 9. Plan d'implementation

### Phase 1 : Safety Net (3-4 jours)

**Objectif** : eliminer la pollution, meme si le KG est desactive temporairement.

1. **Supprimer `{graph_context}` du prompt Pass 1** — le LLM ne voit plus le KG
2. **Creer `kg_relevance_scorer.py`** — cosine filter + cross-encoder
3. **Modifier `search_documents()`** — séparer le flow RAG (Pass 1) du flow KG (pre-scoring)
4. **Feature flag** `KG_TWO_PASS` pour basculer

**Validation** : benchmark T2 — le taux "no info faux" et "hors-sujet" tombe a 0%.

### Phase 2 : Enrichissement (3-4 jours)

**Objectif** : restituer la valeur KG via les cartes.

1. **Creer `kg_enrichment_pass2.py`** — prompt Pass 2, generation des cartes JSON
2. **Modifier l'API `/search`** — retourner `enrichments: [...]` dans la reponse
3. **Frontend : Insight Cards** — composant React pour afficher les cartes sous la reponse
4. **SSE/streaming** — evenement `enrichments` envoye apres Pass 1

**Validation** : 
- Les cartes sont pertinentes (LLM-juge sur 50 cartes)
- Les contradictions sont surfacees (proactive_detection >= 90%)
- La latence reste acceptable (< 15s p95)

### Phase 3 : Optimisation (2-3 jours)

**Objectif** : affiner les seuils et le gate.

1. **Calibrer les seuils** — cosine, cross-encoder, gate confidence
2. **Benchmark complet** — T2/T5 avec juge aligne, OSMOSIS vs RAG
3. **Documenter les resultats** — ADR valide ou ajuste

---

## 10. Alignement avec les travaux precedents

| Travail existant | Relation avec cet ADR |
|---|---|
| CHANTIER_REFONTE_CHAT.md (section 10) | Les **Insight Cards** y sont deja designees — cet ADR fournit le backend |
| IntentResolver 2-passes | Reutilise pour le gate "question simple → skip Pass 2" |
| signal_policy.py | Le gate etend la policy existante avec des seuils de pertinence |
| contradiction_envelope | Le pattern "validate + fallback" est generalise aux cartes |
| Benchmark T2/T5 | Le harness d'evaluation existe — ajouter les metriques "no info faux" et "hors-sujet" |

---

## 11. Risques et mitigations

| Risque | Probabilite | Impact | Mitigation |
|---|---|---|---|
| Pass 2 latence trop elevee | Moyen | UX degrade | Timeout 5s + fallback "pas de cartes" |
| Cross-encoder pas assez precis en multilingue | Moyen | Faux negatifs (chaines pertinentes filtrees) | Utiliser `bge-reranker-v2-m3` (multilingue) |
| Cartes trop frequentes (fatigue utilisateur) | Faible | UX pollue | Max 3 cartes, severity gate |
| Perte de la metrique proactive_detection | Faible | Regression benchmark | Contradictions always-pass dans le gate |
| Complexite de maintenance (2 prompts au lieu de 1) | Faible | Dette technique | Les prompts sont simples et independants |
