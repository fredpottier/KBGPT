# Chantier Chunking & Qualite Retrieval

**Statut** : Phase 1 TERMINEE. Hybrid BM25+dense deploye et mesure (+15pp context_relevance).
**Derniere mise a jour** : 31 mars 2026
**Sources archivees** : `doc/archive/pre-rationalization-2026-03/ongoing/SPRINT2_DIAGNOSTIC_CHUNKING.md`, `SPRINT2_PISTES_CHUNKING_ARCHITECTURE.md`, `SPRINT2_SYNTHESE_CONSENSUS_CHUNKING.md`, `ADR_UNITE_PREUVE_VS_UNITE_LECTURE.md`, `RESEARCH_CHUNKING_STRATEGIES_RAG_2024_2025.md`

---

## 1. Diagnostic

### Le probleme

70% des chunks Qdrant font moins de 100 caracteres. La mediane est a 68 chars. Les chunks sont des fragments atomiques (titres de slides, bullet points isoles, lignes de tableau) et non des passages exploitables par le LLM.

### Distribution mesuree (5000 chunks scannes)

| Taille | Count | Pourcentage |
|--------|-------|-------------|
| < 50 chars | 2317 | **46%** |
| 50-100 chars | 1176 | **24%** |
| 100-200 chars | 730 | 15% |
| 200-500 chars | 575 | 12% |
| 500-1000 chars | 130 | 3% |
| > 1000 chars | 72 | **1%** |

### Par type de document

| Type | Median text | % < 100 chars |
|------|-------------|---------------|
| PPTX | 31-82 chars | **80%** |
| PDF | 55-74 chars | **60%** |

### Cause racine dans le code

**Fichier** : `src/knowbase/claimfirst/orchestrator.py`, lignes 688-795

Le pipeline ClaimFirst convertit chaque **Passage** (DocItem atomique) directement en chunk Qdrant **sans re-chunking** :

```python
MIN_CHARS = 20  # seuil minimum = 20 caracteres seulement

for p in valid_passages:
    sc = SubChunk(chunk_id=p.passage_id, text=p.text, ...)  # conversion 1:1
```

Un DocItem PPTX = une ligne de bullet point (30-40 chars).
Un DocItem PDF = un element de texte extrait (50-100 chars).

### Correlation chunks courts / echec benchmark

| Categorie | Avg % chunks courts (<100 chars) |
|-----------|----------------------------------|
| **Correct** | **59%** |
| False IDK | **78%** |
| False Answer | **75%** |
| Irrelevant | **76%** |

Les questions reussies ont 59% de chunks courts. Les questions ratees en ont 75-78%.

---

## 2. Separation unite de preuve vs unite de lecture

### ADR accepte (25 mars 2026)

**Decision** : separer formellement les deux unites.

| Concept | Definition | Usage | Invariant |
|---------|-----------|-------|-----------|
| **Unite de preuve** | DocItem/Claim : atomique, verbatim, ancrable | KG (Neo4j) | Pas d'assertion sans preuve localisable |
| **Unite de lecture** | Chunk Qdrant : contextuel, autonome, lisible | Retrieval (Qdrant) | Un expert humain peut repondre a une question avec ce chunk seul |

### Invariant reformule

> "OSMOSIS ne produit pas d'affirmation sans source documentaire tracable. Les metadonnees structurelles du document (titre, section, position, notes orateur) sont des faits documentaires — pas des inferences. L'unite de preuve (Claim, KG) reste atomique et verbatim. L'unite de lecture (chunk Qdrant) peut etre enrichie par reconstruction contextuelle a partir de metadonnees structurelles sans appel LLM."

### Architecture cible

```
Document brut
    |
[Extraction] Docling + Speaker Notes
    |
    +--- DocItems atomiques → ClaimFirst → Claims → KG  (INCHANGE)
    |    (unite de preuve, verbatim)
    |
    +--- TypeAwareChunks → Prefixe contextuel → Rechunker → Qdrant
         (unite de lecture, enrichie)                       (retrieval)
```

Les deux coexistent. Le lien est preserve via `item_ids` dans les chunks et `chunk_ids` dans les claims.

### Ce qui est autorise

- Prefixe contextuel deterministe (doc_title + section_title + page)
- Fusion des notes orateur avec le contenu visible des slides (verbatim auteur)
- Relations structurelles Docling comme verbatim
- Filtrage des chunks non-autonomes (< 100 chars narratif, < 50 chars table)
- Utilisation des TypeAwareChunks du cache au lieu des DocItems

### Ce qui reste interdit

- Descriptions interpretatives Vision dans le chemin de connaissance (ADR-20260126 maintenu)
- Prefixe contextuel genere par LLM (inference, non-deterministe)
- Inference de flux directionnels dans les schemas
- Tout contenu ajoute au chunk qui ne provient pas du document source ou de ses metadonnees

---

## 3. Strategie adoptee

### Phase 1 — TypeAwareChunks + rechunker + prefixe (code pret, re-ingestion requise)

**3.1 — Utiliser les TypeAwareChunks du cache au lieu des DocItems**

Le pipeline d'extraction V2 produit deja des TypeAwareChunks structures (329 pour un PPTX vs 861 DocItems). **`orchestrator.py` Phase 8 a ete modifie** pour les utiliser (lignes 638-865). Le code est branche. Il reste a re-ingerer le corpus existant pour activer cette amelioration.

| Metrique | DocItems | TypeAwareChunks |
|----------|----------|-----------------|
| Count (PPTX 476 slides) | 43 060 | **2 613** |
| Median text | 11 chars | **102 chars** |
| < 50 chars | 93% | 43% |
| 100-300 chars | ~2% | 14% |
| 300-1000 chars | ~1% | 17% |
| > 1000 chars | ~0% | **20%** |

**3.2 — Appliquer le rechunker existant** (`rechunker.py`)

- Target : 1500 chars par chunk resultant
- Overlap : 200 chars entre chunks consecutifs
- Regles de rattachement :
  - Heading → se rattache au contenu qui suit
  - Note/Warning → se rattache au paragraphe qui precede
  - Ligne de table → se rattache a sa table
  - Item de liste → se rattache a sa liste + heading
- Filtrage post-fusion : supprimer les chunks restants < 80 chars
- **Force-merge** : tout SubChunk < 100 chars est force-fusionne avec son voisin
- **Cross-type merge par section** : fusionner adjacents meme section quel que soit le type (NARRATIVE + TABLE)
- **Section title lisible** : remplacer le hash section_id par le vrai titre de section

**3.3 — Prefixe contextuel deterministe** (zero LLM)

```
[Document: SAP S/4HANA 2023 Conversion Guide | Section: 3.4 Preparatory Steps]
```

Le doc_title vient du DocumentContext, le section_title du structural graph. Ce n'est pas de l'inference — c'est de la lecture de metadonnees documentaires.

**3.4 — Extraire et fusionner les speaker notes PPTX**

Verification empirique sur le corpus :

| PPTX | Slides avec notes | % | Moyenne chars/note |
|------|-------------------|---|-------------------|
| Access to Customer Systems | 22/49 | **45%** | **551** |
| Business Scope FPS03 | 155/476 | **33%** | **893** |

Les notes sont du **contenu auteur verbatim** — zero tension avec l'invariant de tracabilite. Extraction via `slide.notes_slide.notes_text_frame.text` (python-pptx standard).

### Phase 2 — Re-ingestion et validation

- Re-ingerer un sous-corpus (5 documents cles du benchmark T1)
- Benchmark T1 human (100 questions) en full-pipeline
- Seuil de validation : factual > 60% (vs 43% actuel)
- Decision sur re-extraction claims si amelioration significative

### Phase 3 — Enrichissement optionnel (Sprint 3+)

- Contextual Retrieval avec LLM (si Phase 2 insuffisante)
- Fix rendering Vision PPTX (si validation sur 10 diagrammes montre un gain)
- RSE (Relevant Segment Extraction) dynamique au retrieval

---

## 4. Les 6 pistes evaluees (A → F)

| Piste | Description | Verdict | Invariant | Effort |
|-------|-------------|---------|-----------|--------|
| **A** | Brancher le rechunker existant (1500 chars, overlap 200) | **ADOPTE** — zero cout LLM, code deja ecrit | Conforme | 0.5-1j |
| **B** | Utiliser les TypeAwareChunks au lieu des DocItems | **ADOPTE** — 10x la mediane, structures | Conforme | 1-2j |
| **C** | Contextual Retrieval (Anthropic 2024) — prefixe LLM par chunk | **REPORTE** Sprint 3 — enrichir des chunks de 35 chars n'a pas de sens, fondation d'abord | **Tension** : le prefixe est une inference | 2-3j |
| **D** | Extraction des speaker notes PPTX | **ADOPTE** — contenu auteur, impact massif | Conforme (verbatim) | 0.5-1j |
| **E** | Fix rendering Vision PPTX (placeholder gris → vrai rendu) | **REPORTE** — relations detectees tres faibles (0.1/diagramme), rendering complexe | **Tension** : description Vision = interpretation | 3-5j |
| **F** | Chunking structure-aware (1 slide = 1 chunk PPTX, 1 section = 1 chunk PDF) | **INTEGRE** dans la strategie B+rechunker | Conforme | 2-3j |

### Consensus multi-IA (Claude Web + ChatGPT + Claude Code)

Points de convergence unanimes :
1. Le probleme est fondamental et cause racine dominante de tous les symptomes
2. TypeAwareChunks + rechunker = premiere action, pas de debat
3. Le Contextual Retrieval vient APRES — enrichir des chunks de 35 chars n'a pas de sens
4. Les speaker notes sont une priorite haute — contenu auteur, verbatim, impact massif
5. Le KG devra probablement etre re-extrait — les claims issus de DocItems atomiques sont appauvris

---

## 5. Etat de l'art RAG chunking 2024-2025

### Resultats publies cles

| Approche | Performance | Cout LLM |
|----------|-----------|----------|
| **Contextual Retrieval** (Anthropic, sept 2024) | -35% a -67% erreurs retrieval | Moyen (1 call/chunk) |
| **RAPTOR** (ICLR 2024) | +20% sur QuALITY benchmark | Eleve (resumes recursifs) |
| **Dense X Retrieval** (EMNLP 2024) | +7.37% DCG@20 | Eleve (decomposition) |
| **Page-level** (NVIDIA 2024) | 0.648 accuracy (meilleur overall) | Zero |
| **RecursiveCharSplitter** (400 tokens) | 0.854-0.895 recall | Zero |
| **LLMSemanticChunker** (Chroma 2025) | 0.919 recall | Eleve |

### Concept de "Chunk Autonomy" (theme transversal 2024-2025)

Un bon chunk doit etre **auto-suffisant** :
1. Comprehensible seul (pas de pronoms non resolus)
2. Atomique (un sujet/theme coherent)
3. Attribuable (tracable a sa source)
4. Taille appropriee (assez long pour etre significatif, assez court pour etre precis)

### Consensus PPTX : 1 slide = 1 chunk

Le consensus dominant en 2024-2025 est la segmentation au niveau slide. Contenu a extraire par slide : titre + corps + notes orateur + tableaux + alt-text images + metadonnees. Les slides trop courtes sont fusionnees, les trop denses sont segmentees.

### Outils pertinents pour OSMOSIS

| Outil | Pertinence | Statut |
|-------|-----------|--------|
| **Docling** (IBM) | Tres haute — deja utilise par ExtractionPipelineV2 | En place |
| **Unstructured.io** | Haute — bon chunking `by_title` | Alternative |
| **Jina Late Chunking** | Moyenne — necessite modele Jina specifique | **Ecarte** |
| **LumberChunker** | Basse — cout LLM prohibitif | **Ecarte** |

### Pistes a eviter

- **Proposition chunking** (Dense X Retrieval) : hallucination + perte tracabilite
- **Late chunking** (Jina) : necessite changement modele embedding
- **Docling HybridChunker** : input incompatible, pas d'overlap

---

## 6. Constats empiriques

### Donnees mesurees sur le corpus

- **Median DocItems** : 11 chars (PPTX Business-Scope, 476 slides)
- **Median TypeAwareChunks** : 102 chars (meme document)
- **Median chunks Qdrant actuels** : 68 chars (5000 chunks scannes)
- **Speaker notes PPTX** : 33-45% des slides en ont, 551-893 chars/note en moyenne
- **Vision PPTX** : 266 diagrammes analyses, 2011 elements detectes, mais **0.1 relation/diagramme** — quasi inutile
- **TypeAwareChunks PDF** (Security Guide) : median 319 chars (vs 68 chars Qdrant)

### Test borne superieure

Chunks reconstruits (~1500 chars) depuis le full_text du cache :
- Claude Sonnet : 15% → **54%** (+39pp)
- Claude Haiku : **80%** sur 5 questions
- Qwen 14B : 15% → 15% (zero amelioration — trop petit pour exploiter du contexte riche)

### Repartition du benchmark par type de document

- **97/100 questions T1 human** ciblent des PDF → la strategie PDF est la priorite absolue
- Seulement 2 vrais PPTX dans le corpus (007 + 022), 3 questions benchmark PPTX
- Certaines questions benchmark PPTX ciblent des faits absents du corpus (schemas visuels non extraits)

---

## 7. Etat actuel et travaux restants

### Mesure Qdrant du 30 mars 2026

> **Phase 1 TERMINEE.** 22 documents re-ingeres avec le nouveau pipeline (TypeAwareChunks + rechunker + prefixe contextuel). Les resultats sont spectaculaires :

| Metrique | Avant (diagnostic Sprint 2) | **Apres (Qdrant 30 mars 2026)** | Delta |
|----------|---------------------------|-------------------------------|-------|
| Points total | ~5000 | **7629** | +53% |
| Documents | ? | **22** | — |
| Median chars | 68 | **957** | **x14** |
| < 100 chars | **70%** | **0%** | -70pp |
| < 200 chars | ~85% | **1%** | -84pp |
| >= 1000 chars | 1% | **47%** | +46pp |
| >= 1500 chars | 0% | **15%** | +15pp |
| Prefix contextuel | 0% | **92%** | +92pp |
| Min chunk | ~20 chars | **153 chars** | x7.6 |
| Types : NARRATIVE | ? | **77%** | — |
| Types : FIGURE | ? | **18%** | — |
| Types : TABLE | ? | **3%** | — |

Distribution P10=321, P25=542, P75=1407, P90=1544 chars. Max=3977 chars.

### Ce qui est FAIT

- ✅ TypeAwareChunks comme source (Phase 8 orchestrator.py)
- ✅ Rechunker 1500 chars / 200 overlap (rechunker.py)
- ✅ Force-merge chunks < 100 chars
- ✅ Prefixe contextuel deterministe `[Document: ... | Section: ... | Page N]`
- ✅ Speaker notes PPTX extraites et fusionnees (pptx_extractor.py + slide_reconstructor.py)
- ✅ Section title lisible (resolution depuis section_id)
- ✅ Collection `knowbase_chunks_v2` avec 1024D cosine
- ✅ 22/28 documents re-ingeres

### Ce qui RESTE a faire

| # | Tache | Effort | Priorite |
|---|-------|--------|----------|
| ~~2~~ | ~~Benchmark complet 320 questions post-re-ingestion~~ | — | ✅ **FAIT** — Baseline V5 (29 mars) : T1 Human factual 0.689 (+2.3pp vs RAG), answers 47% (+5pp), false_idk 9%. OSMOSIS >= RAG sur toutes metriques. |
| 1 | **Ingerer les 6 docs manquants** (comparer la liste des 28 vs les 22 presents dans Qdrant) | 0.5j | P0 |
| 3 | **Integrer RAGAS diagnostic** (faithfulness, context_precision) pour distinguer echec retrieval vs generation | 2j | P1 — voir `CHANTIER_BENCHMARK.md` |
| 4 | **Hybrid BM25+dense via Qdrant RRF** — termes exacts (versions, codes TLS) fragiles en dense-only | 1-3j | P1 — voir `ARCH_RETRIEVAL.md` §11.8 |
| 5 | **Decision re-extraction claims** si les scores T1 KG restent faibles malgre retrieval ameliore | Decision | P2 |
| 6 | **Contextual Retrieval** (Anthropic-style, prefixe LLM par chunk) — report sauf si context_precision RAGAS < 0.6 | 2-3j | P3 — optionnel |
