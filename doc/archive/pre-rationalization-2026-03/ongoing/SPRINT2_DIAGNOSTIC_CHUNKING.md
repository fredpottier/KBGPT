# Sprint 2 — Diagnostic Cause Racine : Qualite des Chunks Qdrant

**Date** : 25 mars 2026
**Contexte** : Sprint 2 signal-driven implemente, benchmark full-pipeline operationnel
**Objectif** : Documenter la decouverte de la cause racine des mauvais scores et fournir les donnees pour un consensus multi-IA

---

## 1. La decouverte

En analysant les reponses du benchmark full-pipeline (premiere mesure reelle du systeme en production), nous avons constate que les chunks retournes par Qdrant au LLM sont **trop courts pour contenir les faits recherches**. Les chunks sont des fragments atomiques (titres de slides, bullet points isoles, lignes de tableau) et non des passages de texte exploitables.

### Exemple concret

Question : "Quel patch SPAM/SAINT est requis avant la conversion vers S/4HANA 2023 ?"
Reponse attendue : "Le patch SPAM/SAINT 71 ou superieur est requis"

Les 5 premiers chunks retournes par Qdrant (score 0.862, bon retrieval) :
```
Chunk 1 (37 chars): "Conversion Guide for SAP S/4HANA 2023"
Chunk 2 (37 chars): "Conversion Guide for SAP S/4HANA 2023"
Chunk 3 (37 chars): "Conversion Guide for SAP S/4HANA 2023"
Chunk 4 (37 chars): "Conversion Guide for SAP S/4HANA 2023"
Chunk 5 (37 chars): "Conversion Guide for SAP S/4HANA 2023"
```

Le retrieval trouve le bon document mais le chunk ne contient que le titre — pas le contenu.

---

## 2. Donnees quantitatives

### Distribution globale des chunks (5000 scannes)

| Taille | Count | Pourcentage |
|--------|-------|-------------|
| < 50 chars | 2317 | **46%** |
| 50-100 chars | 1176 | **24%** |
| 100-200 chars | 730 | 15% |
| 200-500 chars | 575 | 12% |
| 500-1000 chars | 130 | 3% |
| > 1000 chars | 72 | **1%** |

**70% des chunks font moins de 100 caracteres.** La mediane est a 68 chars.

### Par type de document

| Type | Docs | Chunks | Median text | % < 100 chars |
|------|------|--------|-------------|---------------|
| **PPTX** (Business/Feature Scope) | 5 | 2229 | **31-82 chars** | **80%** |
| **PDF** (Security/Ops/Conversion) | 12 | 2298 | **55-74 chars** | **60%** |
| Autres | 5 | 473 | 28-90 chars | 64-94% |

Les PPTX sont les pires mais les PDF sont aussi affectes — 60% de chunks < 100 chars.

### Taux de reussite par type de document source

(Benchmark Claude Sonnet, 100 questions T1 human, juge calibre factual >= 0.8)

| Type doc | Questions | Correct | Taux |
|----------|-----------|---------|------|
| PDF | 72 | 31 | **43%** |
| PPTX | 13 | 2 | **15%** |
| Autre | 15 | 0 | **0%** |

Les PDF sont significativement meilleurs (43%) que les PPTX (15%) — mais 43% reste bas.

### Correlation chunks courts / echec

| Categorie | Avg % chunks courts (<100 chars) |
|-----------|----------------------------------|
| **Correct** | **59%** |
| False IDK | **78%** |
| False Answer | **75%** |
| Irrelevant | **76%** |

Les questions reussies ont en moyenne 59% de chunks courts. Les questions ratees en ont 75-78%. La correlation est nette.

---

## 3. Cause racine dans le code

### Pipeline d'ingestion : Passage → Qdrant 1:1

Fichier : `src/knowbase/claimfirst/orchestrator.py`, lignes 688-795

Le pipeline ClaimFirst convertit chaque **Passage** (DocItem atomique) directement en chunk Qdrant **sans re-chunking** :

```python
# Ligne 718 : seuil minimum = 20 caracteres seulement
MIN_CHARS = 20

# Lignes 742-758 : conversion 1:1 Passage → SubChunk
for p in valid_passages:
    sc = SubChunk(
        chunk_id=p.passage_id,
        text=p.text,            # texte atomique du DocItem
        ...
    )
```

Un DocItem pour un PPTX = une ligne de bullet point (30-40 chars).
Un DocItem pour un PDF = un element de texte extrait (50-100 chars).

### Le TextChunker existe mais n'est pas utilise

Le fichier `src/knowbase/ingestion/text_chunker.py` implemente un chunking intelligent (512 tokens, overlap 128, respect phrase boundaries). Mais le pipeline ClaimFirst ne l'utilise pas — il envoie directement les Passages atomiques a Qdrant.

### Notes orateur PPTX : non extraites

Aucune reference a `notes_slide`, `speaker_notes` ou equivalent dans le code d'extraction. Les notes orateur des PPTX (qui contiennent souvent le contenu explicatif detaille) sont ignorees.

---

## 4. Impact sur les benchmarks precedents

### Tous les benchmarks Sprint 0/1/2 sont affectes

Les scores mesures (factual 35-43%, false_idk 16-38%, false_answer 17-31%) ne refletent pas la qualite de l'architecture OSMOSIS — ils refletent la qualite du chunking. Les conclusions qualitatives restent valides (le KG aide sur les contradictions, pas sur les questions simples) mais les chiffres absolus sont sans valeur.

### Impact sur le KG

Les claims Neo4j sont extraits de ces memes passages courts. Un passage "System replacing 70 systems" genere un claim tout aussi pauvre. Les 15861 claims, 7059 entites, 252 tensions cross-doc sont construits sur cette fondation fragile. La re-ingestion devrait affecter le KG aussi.

### Le benchmark avec Claude Sonnet vs Qwen isole un phenomene secondaire

Le test Claude vs Qwen montre que Claude est plus prudent (48% false_idk) mais plus precis (10% false_answer, 9% irrelevant). Qwen est plus permissif (16.5% false_idk) mais plus bruyant (17% false_answer, 27% irrelevant). Cette difference est reelle mais secondaire : **les deux echouent sur les memes questions** ou les chunks ne contiennent pas l'info.

---

## 5. Analyse des questions ratees : PDF vs PPTX

### Les PDF aussi sont affectes

Sur les 48 false_idk avec Claude Sonnet :
- 29 (60%) ciblent des **PDF** — les PDF ne sont pas epargnes
- 9 (19%) ciblent des **PPTX**
- 10 (21%) ciblent d'**autres** types

Les questions PDF echouent parce que les chunks PDF sont aussi des fragments atomiques (titres de section, lignes isolees, elements de tableau). Le probleme n'est pas specifique aux PPTX — c'est le pipeline ClaimFirst qui envoie des DocItems atomiques a Qdrant pour tous les types de documents.

### Exemple PDF : le bon document est trouve mais le chunk est vide

Question : "Quelle est la convention de nommage pour la destination RFC vers SAP Solution Manager ?"
Chunks retournes :
```
Chunk 1 (30 chars): "RFC Destination for SAP System"
Chunk 2 (45 chars): "RFC Destination to connect to SAP Commissions"
Chunk 3 (45 chars): "RFC Destination to connect to SAP Commissions"
```

Le retrieval trouve les bons documents mais les chunks ne contiennent que des titres — pas le texte avec `SM_<SID>CLNT<CLNT>_READ`.

---

## 6. Ce que ca ne remet PAS en question

1. **L'architecture signal-driven** — les signaux KG (tension, evolution, couverture) sont une bonne approche. Mais ils n'ont pas d'impact tant que les chunks ne contiennent pas assez d'info pour repondre.

2. **Le prompt fix** — le passage a un prompt EN domain-agnostic permissif est correct. Mais un LLM ne peut pas extraire un fait qui n'est pas dans le contexte.

3. **Le benchmark full-pipeline** — c'est la bonne approche. Sans lui, on n'aurait pas decouvert le probleme.

4. **La valeur du KG pour les contradictions** — T2 both_sides_surfaced = 100%. Le KG fonctionne pour les tensions cross-doc. Mais cette valeur est limitee si les chunks ne permettent pas de repondre aux questions factuelles de base.

---

## 7. Questions ouvertes pour consensus

1. **Faut-il re-chunker les Passages existants** (fusionner les DocItems en chunks plus larges par section/slide) **ou re-ingerer completement** (refaire l'extraction avec une strategie de chunking differente) ?

2. **La strategie de re-chunking doit-elle etre uniforme** (tous les types de documents) **ou differenciee** (PPTX = par slide, PDF = par paragraphe/section) ?

3. **Le KG doit-il etre re-extrait** apres le re-chunking (les claims actuels sont issus de passages pauvres) **ou peut-on conserver les claims existants** et juste re-chunker Qdrant ?

4. **Le seuil `MIN_CHARS = 20` est-il le seul probleme** ou le pipeline d'extraction (DocItem atomique) est-il fondamentalement mal adapte pour le retrieval ? Le pipeline ClaimFirst est concu pour l'extraction de claims (ou l'atomicite est un avantage), pas pour le retrieval (ou le contexte est essentiel).

5. **L'invariant d'autonomie** (un chunk doit etre repondable seul par un expert humain) est-il la bonne metrique pour definir la taille minimale d'un chunk ? Si oui, quel est le seuil pratique ?

6. **Les notes orateur des PPTX** doivent-elles etre extraites ? Elles contiennent souvent le contenu explicatif mais risquent d'introduire du bruit (notes partielles, commentaires internes).

---

## 8. Donnees brutes pour reference

### Collection Qdrant
- Collection : `knowbase_chunks_v2`
- ~15000 chunks (5000 scannes pour cette analyse)
- Embedding : multilingual-e5-large 1024d
- Median text : 68 chars

### Pipeline
- Extracteur : ClaimFirst pipeline (`orchestrator.py`)
- Chunking : Passage → Qdrant 1:1 (pas de re-chunking)
- MIN_CHARS : 20
- TextChunker (512 tokens, overlap 128) existe mais non utilise

### Benchmark
- 100 questions T1 human
- Juge : Qwen 14B via vLLM (calibre : factual >= 0.8 = correct)
- Resultats full-pipeline (API OSMOSIS) et Claude Sonnet (memes chunks, LLM different)
- Fichiers : `benchmark/results/20260325_sprint2/`
