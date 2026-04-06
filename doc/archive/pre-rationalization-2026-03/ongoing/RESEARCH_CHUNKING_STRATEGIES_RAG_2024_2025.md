# Etat de l'Art : Strategies de Chunking pour RAG (2024-2025)

*Recherche synthetique -- Mars 2026*
*Pertinence pour OSMOSE : ingestion PPTX/PDF, enrichissement contextuel, tracabilite*

---

## Table des matieres

1. [Chunking PPTX / Documents Slides](#1-chunking-pptx--documents-slides)
2. [Chunking PDF Structure-Aware](#2-chunking-pdf-structure-aware)
3. [Enrichissement Contextuel des Chunks](#3-enrichissement-contextuel-des-chunks)
4. [Outils et Projets GitHub](#4-outils-et-projets-github)
5. [Papiers Cles et Benchmarks](#5-papiers-cles-et-benchmarks)
6. [Matrice Comparative](#6-matrice-comparative)
7. [Recommandations pour OSMOSE](#7-recommandations-pour-osmose)

---

## 1. Chunking PPTX / Documents Slides

### 1.1 Consensus Actuel : 1 Slide = 1 Chunk

Le consensus dominant en 2024-2025 est la **segmentation au niveau slide** : chaque slide devient un chunk. Cette approche s'aligne avec la structure naturelle de creation des presentations.

**Contenu a extraire par slide :**
- Titre de la slide
- Corps du texte (bullets, paragraphes)
- Notes du presentateur (speaker notes)
- Contenu des tableaux
- Alt-text des images
- Metadonnees (numero de slide, layout)

**Implementation typique** (python-pptx) :
```
Pour chaque slide :
  chunk = {
    "text": titre + "\n" + bullets + "\n" + notes,
    "metadata": {slide_number, slide_title, has_images, has_tables, source_file}
  }
```

### 1.2 Au-dela du Texte : Extraction Visuelle

Les slides posent un probleme unique : l'information est souvent **visuelle** (diagrammes, flowcharts, tableaux complexes). Approches emergentes :

| Approche | Description | Maturite | Cout LLM |
|----------|-------------|----------|----------|
| **OCR selectif** | pytesseract sur slides sans texte extractible | Mature | Non |
| **Mistral OCR** | OCR multimodal pour slides complexes | Production (2025) | Oui (API) |
| **Docling + Granite-Docling-258M** | VLM single-pass pour charts, tables, formules | Production (2025-2026) | Non (local) |
| **Slide2Text** | python-pptx + pytesseract + LLM narration | Recherche (2025) | Oui |
| **SlideCoder** | Layout-aware + RAG hierarchique (H-RAG) | Recherche (2025) | Oui |
| **GPT-4V / Claude Vision** | Screenshot slide -> description textuelle | Production | Oui (eleve) |

### 1.3 Reconstruction Narrative

Les bullet points sont par nature **telegraphiques**. Deux approches pour reconstruire le sens :

**A. Enrichissement au moment de l'ingestion (LLM call):**
- Generer une description en prose de chaque slide via LLM
- Avantage : chunk auto-suffisant, meilleure recherche semantique
- Inconvenient : cout LLM x nombre de slides, risque d'hallucination

**B. Enrichissement par contexte de voisinage (sans LLM):**
- Prependre le titre du document + titre de section + slide precedente
- Avantage : zero cout LLM, fidele au contenu original
- Inconvenient : chunk plus long, contexte partiellement pertinent

### 1.4 Notes du Presentateur

Les notes contiennent souvent le **veritable contenu** d'une presentation. Strategies :
- **Fusion** : concatener notes au texte de la slide (approche recommandee)
- **Dual-chunk** : un chunk "slide visible" + un chunk "notes", lies par metadata
- **Priorite notes** : si notes presentes et substantielles, privilegier les notes

### 1.5 Limites de l'approche "1 slide = 1 chunk"

- Slides tres denses (>500 tokens) : trop longues pour un embedding efficace
- Slides quasi-vides (titre seul, image plein ecran) : chunk sans valeur semantique
- Presentations narratives (type TED) : le sens traverse les slides

**Solution emergente** : chunking adaptatif qui fusionne les slides trop courtes et segmente les slides trop longues, tout en preservant les frontieres naturelles.

---

## 2. Chunking PDF Structure-Aware

### 2.1 Taxonomie des Approches

```
Naive (Fixed-size)
  |-- Character-based (ex: 500 chars avec overlap)
  |-- Token-based (ex: 256 tokens avec overlap)
  |
Structure-Aware
  |-- Recursive Character Splitting (LangChain default)
  |-- Document Element-based (Unstructured.io)
  |-- Page-level
  |
Semantic
  |-- Embedding similarity breakpoints (LlamaIndex, LangChain)
  |-- LLM-guided (LumberChunker)
  |-- Cluster-based (ClusterSemanticChunker)
  |
Hierarchical
  |-- Parent-Child (LlamaIndex HierarchicalNodeParser)
  |-- RAPTOR (arbre de resumes)
  |-- HiChunk (multi-level + Auto-Merge)
  |
Proposition-based
  |-- Dense X Retrieval (atomic facts)
  |-- Proposition Chunking (LLM decomposition)
```

### 2.2 Recursive Character Splitting

**Principe :** Diviser recursivement par separateurs naturels ("\n\n" -> "\n" -> " " -> "") jusqu'a atteindre la taille cible.

- **Performance** : 85.4-89.5% de recall (optimal a ~400 tokens)
- **Avantage** : Rapide, deterministe, respecte les paragraphes
- **Limite** : Ne comprend pas le contenu, peut couper a des frontieres arbitraires
- **Cout LLM** : Zero
- **Verdict** : Bon baseline, suffisant pour beaucoup de cas

### 2.3 Chunking par Elements de Document (Unstructured.io)

**Principe :** Parser le PDF en elements typees (Title, NarrativeText, Table, ListItem, Image, etc.) puis regrouper les elements en chunks respectant les frontieres semantiques.

- **Strategies disponibles** : `basic`, `by_title`, `by_page`, `by_similarity`
- `by_title` : Nouvelle section a chaque titre detecte, avec max_characters
- **Avantage** : Respecte la structure du document (pas de coupe mid-table)
- **Limite** : Qualite depend de la detection de structure (variable selon PDF)
- **Cout LLM** : Zero (sauf contextual chunking optionnel)
- **Nouveaute 2025** : Support token-based chunking (tiktoken), contextual chunking integre

### 2.4 Semantic Chunking

**Principe :** Calculer la similarite cosinus entre phrases consecutives, couper la ou la similarite chute (changement de sujet).

| Variante | Recall | Cout | Notes |
|----------|--------|------|-------|
| LLMSemanticChunker | 0.919 | Eleve (LLM calls) | Meilleur recall absolu |
| ClusterSemanticChunker | 0.913 | Moyen (embeddings) | Bon rapport cout/qualite |
| Percentile breakpoint | ~0.85 | Faible (embeddings) | Standard LlamaIndex |
| Max-Min semantic (2025) | Bon | Moyen | Springer Nature paper |

**Avantage** : Chunks coherents thematiquement
**Limite** : Plus lent, qualite depend du modele d'embedding, non-deterministe
**Cout LLM** : Zero pour embedding-based, eleve pour LLM-based

### 2.5 Hierarchical Chunking

#### A. Parent-Child (LlamaIndex)

```python
HierarchicalNodeParser.from_defaults(chunk_sizes=[2048, 512, 128])
# Cree 3 niveaux : parent (2048) -> child (512) -> grandchild (128)
# AutoMergingRetriever : si assez d'enfants retrieved, remonte au parent
```

- **Avantage** : Recherche fine + contexte large au moment de la generation
- **Limite** : Complexite du storage (3x chunks), logique de retrieval complexe
- **Cout LLM** : Zero a l'ingestion

#### B. RAPTOR (Recursive Abstractive Processing for Tree-Organized Retrieval)

```
Feuilles (chunks originaux)
  -> Clustering (embeddings)
    -> Resumes de clusters (LLM)
      -> Re-clustering
        -> Resumes de niveau superieur
          -> ... jusqu'a un noeud racine
```

- **Performance** : +20% sur QuALITY benchmark avec GPT-4
- **Avantage** : Questions multi-hop, comprehension globale du document
- **Limite** : Cout LLM significatif a l'ingestion, temps de traitement
- **Cout LLM** : **Eleve** (resume recursif de tous les clusters)
- **Paper** : [arXiv:2401.18059](https://arxiv.org/abs/2401.18059), ICLR 2024

#### C. HiChunk (Tencent, 2025)

- Multi-level document structuring via LLMs fine-tunes
- Benchmark HiCBench avec QA evidence-dense
- Algorithme Auto-Merge pour retrieval hierarchique
- **Paper** : [arXiv:2509.11552](https://arxiv.org/abs/2509.11552)

### 2.6 Proposition Chunking / Dense X Retrieval

**Principe :** Decomposer le texte en **propositions atomiques** -- chaque proposition est un fait unique, auto-suffisant, exprime en langage naturel simple.

Exemple :
```
Texte original : "Founded in 1998, Google, a subsidiary of Alphabet,
is headquartered in Mountain View."

Propositions :
1. "Google was founded in 1998."
2. "Google is a subsidiary of Alphabet."
3. "Google is headquartered in Mountain View."
```

- **Performance** : +7.37% DCG@20 vs baselines (LumberChunker)
- **Avantage** : Precision maximale, zero bruit dans les chunks
- **Limite** : Necessite LLM pour decomposition, multiplie le nombre de chunks
- **Cout LLM** : **Eleve** (decomposition de chaque passage)
- **Paper** : Dense X Retrieval (EMNLP 2024), [arXiv:2312.06648](https://arxiv.org/abs/2312.06648)

### 2.7 LumberChunker (EMNLP 2024)

**Principe :** Prompter iterativement un LLM pour identifier le point de shift semantique dans un groupe de passages consecutifs.

- **Performance** : +7.37% DCG@20 sur GutenQA benchmark
- **Avantage** : Taille variable, respecte l'independance semantique
- **Limite** : Cout LLM proportionnel au volume, lent
- **Cout LLM** : **Eleve**
- **Paper** : [arXiv:2406.17526](https://arxiv.org/abs/2406.17526)

---

## 3. Enrichissement Contextuel des Chunks

### 3.1 Contextual Retrieval (Anthropic, Septembre 2024)

**Le probleme :** Un chunk isole perd son contexte. Ex: "Its more than 3.85 million inhabitants make it the EU's most populous city" -- quelle ville ?

**La solution :** Pour chaque chunk, generer un **prefixe contextuel** via LLM qui situe le chunk dans le document.

```
Prompt : "Voici le document <doc>...</doc>.
Voici le chunk : <chunk>...</chunk>
Donnez un contexte court et specifique pour situer ce chunk
dans le document global. Repondez uniquement par le contexte."

Resultat : "Ce chunk parle de Berlin, dans la section sur la demographie
des capitales europeennes du rapport 2023."
```

**Resultats :**
| Configuration | Reduction erreurs retrieval |
|---------------|----------------------------|
| Contextual Embeddings seul | -35% |
| Contextual Embeddings + Contextual BM25 | -49% |
| + Reranking | **-67%** |

**Cout :** ~1 LLM call par chunk a l'ingestion. Anthropic recommande le **prompt caching** pour reduire les couts (le document complet est envoye avec chaque chunk, mais le prefixe du prompt est cache).

**Implementation :** Disponible dans LlamaIndex, Unstructured Platform, et en standalone.

**Pertinence OSMOSE :** **Tres haute.** Domain-agnostique, ameliore significativement le retrieval, compatible avec n'importe quel chunking en amont. Le cout LLM peut etre controle via prompt caching ou un modele local (Qwen 14B).

### 3.2 Late Chunking (Jina AI, Aout 2024)

**Principe :** Inverser l'ordre habituel. Au lieu de chunker puis embedder, on :
1. Passe le document entier dans le modele d'embedding (transformer)
2. Obtient les token embeddings contextuels pour tout le document
3. Segmente la sequence de token embeddings en chunks
4. Mean-pool chaque segment pour obtenir le chunk embedding

**Avantage :** Chaque chunk embedding "connait" le contexte global du document sans surcharge textuelle.

**Contrainte :** Necessite un modele d'embedding long-context (ex: jina-embeddings-v2, 8192 tokens). Ne fonctionne pas avec des modeles standard 512 tokens.

**Comparaison avec Contextual Retrieval :**
| Critere | Contextual Retrieval | Late Chunking |
|---------|---------------------|---------------|
| Cout LLM | 1 call/chunk | Zero |
| Embedding model | N'importe lequel | Long-context requis |
| Texte du chunk modifie | Oui (prefixe ajoute) | Non |
| Tracabilite | Haute (texte visible) | Moyenne (dans l'embedding) |
| Performance | -67% erreurs (avec reranking) | Amelioration moderee |
| Flexibilite | Agnostique au modele d'embedding | Lie a Jina ou modele compatible |

**Pertinence OSMOSE :** Moyenne. Interessant pour zero-cost, mais impose le modele d'embedding Jina et la tracabilite est reduite (le contexte est dans l'embedding, pas dans le texte).

### 3.3 Sentence Window Retrieval / Parent Document Retriever

**Principe :**
1. Indexer de petits chunks (phrases ou courts paragraphes) pour precision du retrieval
2. Au moment du retrieval, retourner au LLM le **parent** (chunk plus large) ou une **fenetre** autour du chunk trouve

**Variantes :**
- **Parent Document Retriever** (LangChain) : stocke child chunks dans le vector store, parent chunks dans un docstore. Retrieval sur children, retour du parent.
- **Sentence Window** : stocke phrases individuelles, retourne N phrases avant/apres au contexte.
- **AutoMerging** (LlamaIndex) : si K enfants d'un meme parent sont retrieved, remplace par le parent.

**Avantage :** Precision du retrieval (petits chunks) + richesse du contexte (grands chunks)
**Cout LLM :** Zero
**Pertinence OSMOSE :** Haute. Peut etre implemente avec le systeme actuel Qdrant + metadata parent_id.

### 3.4 ChunkRAG (Octobre 2024)

**Principe :** Filtrage post-retrieval des chunks par un LLM qui evalue la pertinence semantique de chaque chunk par rapport a la query, reduisant le bruit avant generation.

- Semantic chunking + LLM relevance scoring
- Reduit les hallucinations en eliminant les chunks non pertinents
- **Paper** : [arXiv:2410.19572](https://arxiv.org/abs/2410.19572)

---

## 4. Outils et Projets GitHub

### 4.1 Docling (IBM, open-source, Linux Foundation)

**URL :** [github.com/docling-project/docling](https://github.com/docling-project/docling)

- **Formats** : PDF, DOCX, **PPTX**, XLSX, HTML, images, LaTeX, etc.
- **Capacites** : Layout detection, reading order, table structure, code, formules, image classification
- **Modele** : Granite-Docling-258M (VLM, Apache 2.0, local)
- **Export** : Markdown, HTML, JSON (DoclingDocument)
- **Performance** : 97.9% accuracy sur extraction tables complexes
- **Chunking integre** : Hierarchical chunking respectant la structure du document
- **Pertinence OSMOSE** : **Tres haute.** Remplace python-pptx + pdfplumber/PyMuPDF avec un pipeline unifie. Modele local = zero cout API. Support PPTX natif.

### 4.2 Unstructured.io

**URL :** [github.com/Unstructured-IO/unstructured](https://github.com/Unstructured-IO/unstructured)

- **Partitioning** : Detecte Title, NarrativeText, Table, ListItem, Image, etc.
- **Chunking** : `basic`, `by_title`, `by_page`, `by_similarity`
- **Contextual Chunking** : Integre (implementation de l'approche Anthropic)
- **Token-based** : Support tiktoken
- **Formats** : PDF, DOCX, PPTX, HTML, Email, etc.
- **Pertinence OSMOSE** : Haute. Plus mature que Docling sur le chunking, mais moins performant sur l'extraction de structure PDF.

### 4.3 LlamaIndex

**URL :** [docs.llamaindex.ai](https://docs.llamaindex.ai)

Node Parsers disponibles :
- `SentenceSplitter` : Standard, respecte les phrases
- `SemanticSplitterNodeParser` : Breakpoints par similarite embedding
- `HierarchicalNodeParser` : Parent-child multi-niveaux
- `MarkdownNodeParser` : Parse markdown en sections
- Cookbook Contextual Retrieval : implementation de l'approche Anthropic

### 4.4 LangChain

**URL :** [langchain.com](https://www.langchain.com)

Splitters disponibles :
- `RecursiveCharacterTextSplitter` : Default, bon baseline
- `MarkdownHeaderTextSplitter` : Respecte les headers
- `HTMLHeaderTextSplitter` : Structure HTML
- `SemanticChunker` : Breakpoints semantiques
- `ParentDocumentRetriever` : Stockage dual child/parent

### 4.5 DocETL (UC Berkeley)

**URL :** [github.com/ucbepic/docetl](https://github.com/ucbepic/docetl)

- Pipeline YAML declaratif pour traitement de documents complexes
- Operateur `gather` pour maintenir le contexte lors du chunking
- Operateur `resolve` pour entity resolution cross-chunks
- Rewriting agentique des queries
- **Performance** : 25-80% plus precis que les baselines
- **Pertinence OSMOSE** : Moyenne pour le chunking direct, mais concept `gather` interessant.

### 4.6 LumberChunker

**URL :** [github.com/joaodsmarques/LumberChunker](https://github.com/joaodsmarques/LumberChunker)

- LLM-guided semantic shift detection
- Taille de chunks variable, respecte l'independance semantique
- EMNLP 2024 Findings

### 4.7 RAPTOR (Stanford)

**URL :** [github.com/parthsarthi03/raptor](https://github.com/parthsarthi03/raptor)

- Clustering recursif + resumes hierarchiques
- ICLR 2024
- Integre dans RAGFlow

### 4.8 Outils Specialises PPTX

| Outil | Description | URL |
|-------|-------------|-----|
| RAGAlchamy | Extraction texte + charts + OCR de PPTX | [github](https://github.com/connectaman/RAGAlchamy) |
| Preprocess.co | SaaS pour preprocessing PPTX pour RAG | [preprocess.co](https://preprocess.co/preprocessing-pptx) |
| Mistral OCR | OCR multimodal pour slides complexes | [mistral.ai](https://mistral.ai/news/mistral-ocr) |

---

## 5. Papiers Cles et Benchmarks

### 5.1 Papiers Fondamentaux

| Paper | Venue | Contribution Cle | ArXiv |
|-------|-------|-------------------|-------|
| **RAPTOR** | ICLR 2024 | Arbre de resumes recursifs pour retrieval multi-hop | [2401.18059](https://arxiv.org/abs/2401.18059) |
| **Dense X Retrieval** | EMNLP 2024 | Propositions atomiques comme unite de retrieval | [2312.06648](https://arxiv.org/abs/2312.06648) |
| **LumberChunker** | EMNLP 2024 Findings | LLM-guided semantic segmentation | [2406.17526](https://arxiv.org/abs/2406.17526) |
| **Late Chunking** | Jina AI, 2024 | Chunking post-embedding pour context preservation | [2409.04701](https://arxiv.org/abs/2409.04701) |
| **ChunkRAG** | 2024 | LLM-based chunk filtering post-retrieval | [2410.19572](https://arxiv.org/abs/2410.19572) |
| **Contextual Retrieval** | Anthropic Blog, Sept 2024 | Prefixes contextuels par chunk | [Blog](https://www.anthropic.com/news/contextual-retrieval) |
| **HiChunk** | 2025 | Hierarchical chunking + benchmark | [2509.11552](https://arxiv.org/abs/2509.11552) |
| **Reconstructing Context** | 2025 | Evaluation comparative des strategies | [2504.19754](https://arxiv.org/abs/2504.19754) |
| **Chunking Paradigm** | ICNLSP 2025 | Recursive semantic chunking | [ACL Anthology](https://aclanthology.org/2025.icnlsp-1.15.pdf) |
| **Document Segmentation Matters** | ACL Findings 2025 | Impact segmentation sur RAG | [ACL](https://aclanthology.org/2025.findings-acl.422.pdf) |

### 5.2 Benchmarks et Resultats

**NVIDIA (2024) - 7 strategies x 5 datasets :**
- Page-level : 0.648 accuracy (meilleur overall)
- Factoid queries : optimal 256-512 tokens
- Analytical queries : optimal 1024+ tokens

**Chroma Research (2025) :**
- LLMSemanticChunker : 0.919 recall
- ClusterSemanticChunker : 0.913 recall
- RecursiveCharacterTextSplitter (400 tokens) : 0.854-0.895 recall

**Clinical Decision Support (2024) :**
- Adaptive chunking : 87% accuracy
- Baseline fixed : 50% accuracy
- Adaptive relevance : 93%

### 5.3 Concept de "Chunk Autonomy"

Un theme transversal en 2024-2025 : un bon chunk doit etre **auto-suffisant** ("self-contained"). Criteres :
1. **Comprehensible seul** : pas de pronoms non resolus, pas de references implicites
2. **Atomique** : contient un sujet/theme coherent
3. **Attribuable** : tracable a sa source (page, section, slide)
4. **Taille appropriee** : assez long pour etre significatif, assez court pour etre precis

---

## 6. Matrice Comparative

### 6.1 Strategies de Chunking

| Strategie | Domain-Agnostic | Tracabilite | Cout LLM Ingestion | Qualite Retrieval | Complexite Implementation |
|-----------|:---:|:---:|:---:|:---:|:---:|
| Fixed-size (overlap) | Oui | Haute | Zero | Baseline | Triviale |
| Recursive Character | Oui | Haute | Zero | Bonne | Faible |
| By Document Elements | Oui | Haute | Zero | Bonne+ | Moyenne |
| Semantic (embedding) | Oui | Haute | Zero* | Bonne+ | Moyenne |
| Semantic (LLM) | Oui | Haute | **Eleve** | Tres bonne | Moyenne |
| Parent-Child | Oui | Haute | Zero | Bonne+ | Elevee |
| RAPTOR | Oui | Moyenne** | **Eleve** | Excellente | Elevee |
| Proposition-based | Oui | Moyenne*** | **Eleve** | Excellente | Elevee |
| Contextual Retrieval | Oui | Tres haute | **Moyen** | Excellente | Faible |
| Late Chunking | Oui | Moyenne | Zero | Bonne+ | Faible |

\* Cout d'embedding seulement
\** Les resumes synthetiques s'eloignent du texte original
\*** Les propositions reformulees modifient le texte original

### 6.2 Outils d'Extraction

| Outil | PDF | PPTX | Tables | OCR | Modele Local | Open-Source |
|-------|:---:|:---:|:---:|:---:|:---:|:---:|
| Docling | Excellent | Bon | Excellent | Oui | Oui (258M) | Oui |
| Unstructured | Bon | Bon | Bon | Oui | Partiel | Oui |
| python-pptx | N/A | Bon (texte) | Basique | Non | N/A | Oui |
| PyMuPDF/pdfplumber | Bon | N/A | Moyen | Non | N/A | Oui |
| Mistral OCR | Bon | Bon | Bon | Excellent | Non (API) | Non |
| LlamaParse | Bon | Bon | Bon | Oui | Non (API) | Non |

---

## 7. Recommandations pour OSMOSE

### 7.1 Quick Wins (Impact eleve, effort faible)

**A. Contextual Retrieval a l'ingestion**
- Implementer l'approche Anthropic : pour chaque chunk, generer un prefixe contextuel via Qwen 14B (vLLM burst mode)
- Cout : 1 LLM call/chunk pendant le burst, zero en retrieval
- Impact attendu : -35 a -49% erreurs retrieval
- Compatible avec le chunking actuel sans le modifier

**B. Parent-Child avec metadata**
- Stocker dans Qdrant un champ `parent_chunk_id` et `parent_text` dans le payload
- Retriever sur les petits chunks, inclure le parent dans le contexte LLM
- Cout LLM : Zero
- Impact : Meilleur contexte pour la synthese

### 7.2 Medium Term (Impact eleve, effort moyen)

**C. Migration vers Docling pour l'extraction**
- Remplacer python-pptx + pdfplumber par Docling
- Pipeline unifie PDF + PPTX + DOCX
- Modele Granite-Docling-258M local (zero cout API)
- Meilleure detection de structure (tables, layout, reading order)

**D. Chunking par elements de document**
- Post-Docling : chunking respectant les frontieres detectees (titres, paragraphes, tables)
- Equivalent a Unstructured `by_title` mais sur la sortie Docling
- Zero cout LLM

### 7.3 Long Term (Impact variable, effort eleve)

**E. RAPTOR pour documents longs**
- Resumes hierarchiques pour questions multi-hop
- Pertinent pour les CRR multi-chapitres
- Cout LLM significatif -- a reserver au burst mode

**F. Proposition Chunking pour precision maximale**
- Decomposition en faits atomiques
- Pertinent si false_answer_rate reste eleve apres les quick wins
- Cout LLM tres eleve -- envisager seulement sur corpus critique

### 7.4 A eviter

- **Late Chunking** : impose Jina embeddings, incompatible avec TEI actuel
- **LumberChunker** : cout LLM prohibitif pour un gain marginal vs semantic chunking
- **LLMSemanticChunker** : meilleur recall mais rapport cout/gain defavorable vs ClusterSemantic

---

## Sources

### Papiers Academiques
- [RAPTOR: Recursive Abstractive Processing for Tree-Organized Retrieval](https://arxiv.org/abs/2401.18059) - ICLR 2024
- [Dense X Retrieval: Propositions as Retrieval Unit](https://arxiv.org/abs/2312.06648) - EMNLP 2024
- [LumberChunker: Long-Form Narrative Document Segmentation](https://arxiv.org/abs/2406.17526) - EMNLP 2024 Findings
- [Late Chunking: Contextual Chunk Embeddings](https://arxiv.org/abs/2409.04701) - Jina AI 2024
- [ChunkRAG: Novel LLM-Chunk Filtering Method](https://arxiv.org/abs/2410.19572) - 2024
- [HiChunk: Hierarchical Chunking for RAG](https://arxiv.org/abs/2509.11552) - 2025
- [Reconstructing Context: Evaluating Advanced Chunking Strategies](https://arxiv.org/abs/2504.19754) - 2025
- [Document Segmentation Matters for RAG](https://aclanthology.org/2025.findings-acl.422.pdf) - ACL 2025
- [DocETL: Agentic Query Rewriting for Document Processing](https://arxiv.org/abs/2410.12189) - VLDB 2025

### Blog Posts et Documentation
- [Anthropic - Contextual Retrieval](https://www.anthropic.com/news/contextual-retrieval) - Septembre 2024
- [Jina AI - Late Chunking in Long-Context Embedding Models](https://jina.ai/news/late-chunking-in-long-context-embedding-models/)
- [Unstructured - Chunking Best Practices](https://unstructured.io/blog/chunking-for-rag-best-practices)
- [Unstructured - Contextual Chunking](https://unstructured.io/blog/contextual-chunking-in-unstructured-platform-boost-your-rag-retrieval-accuracy)
- [Firecrawl - Best Chunking Strategies for RAG 2025](https://www.firecrawl.dev/blog/best-chunking-strategies-rag)
- [Stack Overflow - Breaking up is hard to do: Chunking in RAG](https://stackoverflow.blog/2024/12/27/breaking-up-is-hard-to-do-chunking-in-rag-applications/)

### Outils et Repositories
- [Docling (IBM)](https://github.com/docling-project/docling)
- [Unstructured](https://github.com/Unstructured-IO/unstructured)
- [RAPTOR](https://github.com/parthsarthi03/raptor)
- [LumberChunker](https://github.com/joaodsmarques/LumberChunker)
- [HiChunk (Tencent)](https://github.com/TencentCloudADP/hichunk)
- [DocETL (UC Berkeley)](https://github.com/ucbepic/docetl)
- [RAGAlchamy (PPTX)](https://github.com/connectaman/RAGAlchamy)
- [LlamaIndex - Contextual Retrieval Cookbook](https://docs.llamaindex.ai/en/stable/examples/cookbooks/contextual_retrieval/)
