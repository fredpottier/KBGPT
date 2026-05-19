# ADR — Architecture KG V3 : RAG Baseline + KG Control Plane

**Date** : 3 avril 2026
**Statut** : PROPOSITION FINALE — synthese Claude + ChatGPT + Fred
**Priorite** : CRITIQUE — prerequis pour la qualite produit OSMOSIS
**Remplace** : ADR_KG_INJECTION_ARCHITECTURE_V2.md (rejete — demote le KG en decoration)

---

## 1. Decision

**Adopter l'architecture "RAG as Baseline, KG as Selective Control Plane"** :

- Le **RAG** reste le moteur de reponse par defaut (retrieval invariant, performant sur le simple)
- Le **KG** ne fournit jamais de texte au LLM. Il agit comme **plan de controle** :
  - **Routeur** : determine le mode de reponse (Direct, Augmented, Tension, Structured Fact)
  - **Guide de retrieval** : elargit ou reordonne les chunks
  - **Emetteur de contraintes** : impose des regles structurelles au LLM
- Le **LLM** verbalise sous contraintes. Un **prompt specialise par mode**, pas un prompt universel.

### Principe fondamental

> **Le KG ne parle pas au LLM. Il contraint ce que le LLM a le droit de dire.**

---

## 2. Pourquoi V2 a ete rejetee

L'ADR V2 proposait un "Two-Pass" ou :
- Pass 1 = RAG pur (zero KG dans le prompt)
- Pass 2 = cartes UI avec signaux KG

**Critique** : cela transforme le KG en module decoratif. Une "insight card" est optionnelle et ignorable. Le differenciateur OSMOSIS (arbitrage documentaire) devient un accessoire.

> "Si le KG ne fait que commenter la reponse RAG, OSMOSIS est un RAG++ avec de jolis insights." — ChatGPT

**Le vrai probleme** n'est pas "KG vs prompt" mais "comment le KG influence le systeme sans polluer le LLM". La V2 resout le symptome (pollution) en supprimant la cause (le KG dans la reponse) — fausse solution.

---

## 3. Les 4 modes de reponse

### Mode 1 — DIRECT (60-75% des questions)

**Quand** : chunks RAG pertinents, 1-2 docs, pas de tension, pas de besoin comparatif.

**Comportement** :
- Synthese RAG standard, chunks seuls
- KG completement silencieux dans le prompt
- Badge UI optionnel : "1 source principale, pas de divergence"

**Prompt** : simple, direct, zero mention du KG.

**Mapping code actuel** : `signal_policy` mode `is_silent` (existe deja).

---

### Mode 2 — AUGMENTED (15-20% des questions)

**Quand** : reponse RAG bonne mais signaux KG additionnels — docs manquants, nuance cross-doc, evolution legere, couverture incomplete.

**Comportement** :
- Le KG **elargit le retrieval** : ajoute des chunks de documents identifies par le KG
- Le KG **reordonne les chunks** : rapproche deux passages qui ne seraient jamais voisins en RAG pur
- Le LLM repond a partir des **chunks enrichis** (pas de texte KG narratif)
- Eventuellement une carte UI complete ensuite

**Impact KG** : le KG influence la reponse **par le contexte documentaire**, pas par un texte narratif injecte. Le LLM ne sait pas que le KG a modifie le set de chunks — il voit juste des extraits de documents.

**Prompt** : meme structure que DIRECT, mais les chunks fournis ont ete selectionnes/reordonnes par le KG.

**Mapping code actuel** :
- `_retrieve_chunks()` avec `doc_filter` alimente par le KG (existe)
- Reorder par tensions (existe dans `signal_policy.reorder_by_tensions`)
- KG document scoping (existe, lignes 794-884 de search.py)

---

### Mode 3 — TENSION (5-10% des questions)

**Quand** : contradiction / refine / qualify detecte. Question touchant a un sujet ou plusieurs documents divergent.

**Comportement** :
- Le systeme force un **template de reponse structuree** :

```
Reponse courte (synthese)

Position A (Document X, 2023)
[contenu de la position A avec citation]

Position B (Document Y, 2022)
[contenu de la position B avec citation]

Ce qui a change / ce qui depend du contexte
[analyse comparative]

Conclusion prudente
[pas de verdict definitif si les deux positions sont valides]
```

- Le LLM ne recoit PAS un bloc KG explicatif
- Il recoit des **chunks contradictoires adjacents** + une **obligation de structure** + des **regles de non-conclusion**

**Contraintes KG emises** (courtes, actionnables) :
```
- Il existe 2 positions contradictoires sur ce sujet
- Tu DOIS presenter les deux avec leurs sources
- Tu NE DOIS PAS conclure en faveur de l'une sans justification explicite
- Prefere le document le plus recent si les deux sont valides
```

**Prompt** : prompt specialise "tension" avec template obligatoire.

**Mapping code actuel** :
- `contradiction_envelope` (existe)
- `tension_mentioned` detection (existe dans `kg_signal_detector`)
- Les chunks des deux docs en tension sont deja identifies

---

### Mode 4 — STRUCTURED FACT (3-5% des questions)

**Quand** : question explicitement comparative, de validation, basee sur valeur/version/seuil/release, ou `/verify`.

**Comportement** :
- Pas de synthese libre d'emblee
- Le systeme construit d'abord un **paquet de faits structures** (claims matchees, valeurs, versions)
- Le LLM **verbalise** ce paquet

```
Etape 1 : KG identifie les claims/valeurs/versions pertinentes
Etape 2 : Chunks RAG associes comme preuves
Etape 3 : Sortie intermediaire JSON (claims + preuves)
Etape 4 : LLM reformule en langage naturel
```

**Ici le KG est reellement moteur** — mais seulement sur son terrain naturel (comparaison, verification, evolution).

**Prompt** : prompt specialise "structured fact" avec JSON intermediaire.

**Mapping code actuel** :
- ClaimKey / QuestionDimension (existe)
- EvidenceBundle (existe partiellement)
- `/verify` endpoint (existe, docx_processor.py)

---

## 4. Le role exact du KG

Le KG conserve **3 pouvoirs forts** mais perd le role de "source textuelle parallele" :

### Pouvoir 1 — Declencher un changement de mode

Le KG ne dit pas "voici la reponse". Il dit :
- "cette question n'est pas purement locale" → mode AUGMENTED
- "il existe une divergence" → mode TENSION
- "la couverture RAG est incomplete" → mode AUGMENTED
- "question de comparaison/verification" → mode STRUCTURED_FACT

### Pouvoir 2 — Selectionner et reordonner les preuves

Le KG peut :
- **Ajouter** les docs en tension absents du retrieval RAG
- **Rapprocher** dans le prompt deux chunks de docs differents qui ne seraient jamais voisins en RAG pur
- **Remonter** une ancienne et une nouvelle version cote a cote
- **Assembler** plusieurs preuves autour d'une meme entite

C'est du vrai impact sur la reponse, mais par le **choix des preuves**, pas par du texte narratif.

### Pouvoir 3 — Imposer des contraintes de formulation

Exemples :
- "presente les deux positions" (mode TENSION)
- "ne conclus pas sans distinguer version/date/perimetre"
- "si docs contradictoires, dis-le explicitement"
- "si preuve partielle, reponds partiellement"

Le KG agit comme **policy engine** sur le LLM, pas comme source concurrente.

---

## 5. Pipeline concret

### Etape 1 — Baseline retrieval (invariant)

```
Question → embedding → Qdrant hybrid search → rerank → top 8-12 chunks
```

Identique au RAG pur. Invariant Type A preserve.

### Etape 2 — Readiness scoring (diagnostique)

Calculer 4 scores a partir des signaux deja disponibles :

| Score | Source | Ce qu'il mesure |
|---|---|---|
| `direct_answer_score` | Top chunk scores, nombre docs | Le RAG suffit-il seul ? |
| `tension_score` | Relations CONTRADICTS/REFINES/QUALIFIES | Y a-t-il des tensions detectees ? |
| `cross_doc_score` | Nombre docs dans claims, chains | Information distribuee sur plusieurs docs ? |
| `structured_fact_score` | Match ClaimKey/QD, presence valeurs/versions | Question de verification/comparaison ? |

**Sources de donnees** (toutes existent deja) :
- `kg_claim_results` (claims vector search)
- `signal_report` (7 signaux detectes)
- `chain_signals` (CHAINS_TO metrics)
- `qs_crossdoc_data` (QuestionSignature comparisons)
- `retrieval_result.top_score`, `retrieval_result.docs_involved`

### Etape 3 — Mode selection (policy)

```python
def select_response_mode(scores: ReadinessScores) -> ResponseMode:
    if scores.tension_score >= TENSION_THRESHOLD:
        return ResponseMode.TENSION
    if scores.structured_fact_score >= STRUCTURED_THRESHOLD:
        return ResponseMode.STRUCTURED_FACT
    if scores.cross_doc_score >= CROSS_DOC_THRESHOLD:
        return ResponseMode.AUGMENTED
    if scores.direct_answer_score >= DIRECT_THRESHOLD:
        return ResponseMode.DIRECT
    return ResponseMode.DIRECT  # fallback safe
```

Ordre de priorite :
1. TENSION (le plus critique — differenciateur produit)
2. STRUCTURED_FACT (valeur ajoutee forte)
3. AUGMENTED (enrichissement utile)
4. DIRECT (defaut safe)

### Etape 4 — Context builder par mode

| Mode | Chunks | KG action | Contraintes LLM |
|---|---|---|---|
| DIRECT | RAG top-k seuls | Aucune | Prompt simple |
| AUGMENTED | RAG top-k + chunks KG-guided + reorder | Elargit retrieval, reordonne | Prompt standard, pas de mention KG |
| TENSION | Chunks des 2+ docs en tension, adjacents | Force paires contradictoires | Template obligatoire, non-conclusion |
| STRUCTURED_FACT | Claims + chunks preuve | Construit paquet de faits | JSON intermediaire + verbalisation |

### Etape 5 — Synthese specialisee (1 prompt par mode)

**DIRECT** :
```
Tu es un expert. Reponds a la question a partir des extraits fournis.
Cite tes sources. Reponds dans la langue de la question.
```

**AUGMENTED** :
```
Tu es un expert. Reponds a la question a partir des extraits fournis.
Note : les extraits proviennent de plusieurs documents — utilise-les tous.
Cite tes sources. Reponds dans la langue de la question.
```

**TENSION** :
```
Tu es un expert en analyse documentaire.
Les extraits fournis contiennent des positions DIVERGENTES sur le sujet.

Ta reponse DOIT suivre cette structure :
1. Synthese courte (2-3 phrases)
2. Position A : [contenu + source]
3. Position B : [contenu + source]
4. Analyse : ce qui a change / ce qui differe
5. Conclusion prudente (pas de verdict si les deux sont valides)

Regle absolue : ne conclus PAS en faveur d'une position sans preuve explicite.
```

**STRUCTURED_FACT** :
```
Tu es un expert en verification documentaire.
On te fournit un ensemble de faits structures avec leurs preuves documentaires.
Reformule ces faits en langage naturel clair, en citant chaque source.
Ne rajoute rien qui n'est pas dans les faits fournis.
```

---

## 6. Ce qui change par rapport a aujourd'hui

| Aspect | Avant (V1) | Apres (V3) |
|---|---|---|
| KG dans le prompt | Bloc narratif 1000-1500 tokens | **Zero texte KG** — uniquement contraintes courtes |
| Mode de reponse | 1 prompt universel | **4 prompts specialises** |
| Role du KG | Source textuelle parallele au RAG | **Control plane** (route, guide, contraint) |
| Impact KG sur le retrieval | Ajout de chunks apres coup | **Selection/reorder des chunks avant synthese** |
| Contradictions | Injectees en narratif | **Template force + chunks adjacents** |
| Questions simples | KG injecte quand meme | **KG silencieux** |

---

## 7. Ce qui ne change PAS

- Retrieval Qdrant invariant (Type A)
- Modele de synthese (Haiku)
- Neo4j KG et ses relations
- Signal detector et ses 7 signaux
- Contradiction envelope
- Frontend (sauf ajout eventuel d'Insight Cards en complement)

---

## 8. Alignement avec l'existant

| Brique existante | Reutilisation |
|---|---|
| `signal_policy.py` (gate mechanism) | Evolue en **mode selector** (4 modes au lieu de on/off) |
| `kg_signal_detector.py` (7 signaux) | Les scores alimentent le readiness scoring |
| `_retrieve_chunks()` + `doc_filter` | Mode AUGMENTED utilise le KG pour filtrer/elargir |
| `contradiction_envelope` | Mode TENSION l'utilise pour identifier les paires |
| `reorder_by_tensions` | Mode TENSION place les chunks contradictoires adjacents |
| `IntentResolver 2-passes` | Peut alimenter le `structured_fact_score` |
| Insight Cards (design chat refonte) | Complement UI pour signaux KG non integres dans la reponse |

---

## 9. Plan d'implementation en 3 sprints

### Sprint 1 — Safe Hybrid (3-4 jours)

**Objectif** : ne plus laisser le KG degrader les reponses simples.

1. Implementer le **readiness scoring** (4 scores a partir des signaux existants)
2. Implementer le **mode selector** (remplace le signal_policy binaire)
3. Mode DIRECT : supprimer tout texte KG du prompt
4. Mode AUGMENTED : KG elargit le retrieval + reordonne, zero texte narratif
5. Feature flag `OSMOSIS_RESPONSE_MODES=true/false`

**Validation** :
- Benchmark T2 : taux "no info faux" et "hors-sujet" → < 5%
- Benchmark T1 : non-regression sur questions simples

### Sprint 2 — Mode TENSION solide (3-4 jours)

**Objectif** : exploiter le differenciateur — le KG detecte et structure les contradictions.

1. Prompt specialise TENSION avec template obligatoire
2. Assemblage des chunks contradictoires adjacents
3. Regles de non-conclusion
4. UI dediee aux divergences (Split Truth View du chantier refonte chat)

**Validation** :
- `both_sides_surfaced` > 60% (vs 30% actuellement)
- `tension_mentioned` >= 95%
- Pas de regression sur autres modes

### Sprint 3 — Mode STRUCTURED FACT (3-4 jours)

**Objectif** : le KG comme moteur de reponse sur son terrain naturel.

1. Pipeline claims → faits structures → verbalisation
2. Integration avec `/verify`
3. Cas d'usage : comparaison versions, validation seuils, evolution temporelle

**Validation** :
- `chain_coverage` > 70% (vs 45% actuellement)
- Questions de verification : precision > 80%

---

## 10. Metriques de succes globales

| Metrique | Baseline | Cible Sprint 1 | Cible Sprint 3 |
|---|---|---|---|
| Taux "no info faux" | 7.2% | < 2% | < 1% |
| Taux hors-sujet | 17.6% | < 5% | < 3% |
| both_sides_surfaced | 30.1% | > 45% | > 65% |
| tension_mentioned | 100% | >= 95% | >= 98% |
| both_sources_cited | 83.2% | >= 80% | >= 85% |
| chain_coverage | 45% | >= 50% | >= 70% |
| proactive_detection | 100% | >= 90% | >= 95% |
| Score global OSMOSIS | 73.3% | >= 75% | >= 85% |
| Delta OSMOSIS vs RAG | +8.6pp | >= +10pp | >= +20pp |

---

## 11. Risques et mitigations

| Risque | Mitigation |
|---|---|
| Mode selector mal calibre (trop de DIRECT) | Seuils conservateurs + monitoring du ratio par mode |
| Mode TENSION template trop rigide | Template comme guide, pas comme contrainte absolue |
| Sprint 3 trop ambitieux (structured fact) | Peut etre reporte — Sprint 1+2 suffisent pour le differenciateur |
| Regression sur questions simples | Feature flag + benchmark non-regression systematique |
| Le KG manque des tensions (faux negatifs) | Seuil tension bas + fallback AUGMENTED (pas DIRECT) |

---

## 12. La formule

> **RAG pour trouver vite. KG pour savoir quand il ne faut pas repondre trop simplement.**

> **Le RAG fournit la matiere locale. Le KG decide si cette matiere est suffisante, contradictoire, incomplete ou comparable.**

> **Le KG ne parle pas au LLM. Il contraint ce que le LLM a le droit de dire.**
