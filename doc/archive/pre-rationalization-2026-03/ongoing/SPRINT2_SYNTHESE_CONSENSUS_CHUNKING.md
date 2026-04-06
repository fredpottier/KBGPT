# Sprint 2 — Synthese et Reponses aux Questions de Claude Web et ChatGPT

**Date** : 25 mars 2026
**Prerequis** : Lire d'abord `SPRINT2_PISTES_CHUNKING_ARCHITECTURE.md`

---

## 1. Reponses factuelles aux questions de Claude Web

### Q1: "Inspecter un TypeAwareChunk complet — qualite reelle ?"

**Fait.** Sur le PPTX Business-Scope (476 slides) :

| Metrique | DocItems | TypeAwareChunks |
|----------|----------|-----------------|
| Count | 43060 | **2613** |
| Median text | **11 chars** | **102 chars** |
| < 50 chars | 93% | 43% |
| 100-300 chars | ~2% | 14% |
| 300-1000 chars | ~1% | 17% |
| > 1000 chars | ~0% | **20%** |

Les TypeAwareChunks sont **significativement meilleurs** (10x la mediane, 20% > 1000 chars) mais pas parfaits (43% restent < 50 chars). Ce sont des headings isoles, des figures vides, des bullets courts. Les chunks de 300-1000+ chars sont des sections coherentes avec titre + contenu.

**Conclusion** : les TypeAwareChunks sont une amelioration majeure mais pas suffisante seuls. Ils doivent etre combines avec un filtrage/fusion des petits chunks.

### Q2: "Pourquoi merge_vision=False ? L'ADR-20260126 s'applique-t-il aux TypeAwareChunks ?"

**Repondu.** L'ADR-20260126 "Vision Out of the Knowledge Path" a ete decide parce que la Vision produisait des assertions avec un **taux d'ancrage catastrophique** :
- Vision ON : 12-17% d'ancrage
- TEXT-ONLY : **56.6%** d'ancrage

La decision est claire : **la Vision est exclue du chemin critique de connaissance** (claims, KG, assertions). Les VisionObservations existent comme metadata de navigation, pas comme source de verite.

**MAIS** — et c'est crucial — cette decision concerne le **KG**, pas le **retrieval**. L'ADR ne dit pas "ne jamais utiliser la Vision dans Qdrant". Il dit "ne pas creer de claims a partir de la Vision". Ce sont deux choses differentes :
- KG : besoin de faits ancrables verbatim → Vision exclue (decision correcte)
- Retrieval : besoin de contexte lisible → la Vision pourrait enrichir les chunks sans violer l'ADR

Les TypeAwareChunks **ne sont pas lies a la decision Vision**. Ils sont construits par le structural graph builder a partir des DocItems et des sections — pas a partir de la Vision. Le fait qu'ils ne soient pas utilises par ClaimFirst est une **dette technique d'integration**, pas une consequence de l'ADR.

### Q3: "Les VisionResults contiennent-ils des descriptions textuelles exploitables ?"

**Verifie.** Non — les VisionResults contiennent des **elements/labels** (noms extraits des diagrammes : "SAP Business Data Cloud", "Our AI-First Strategy") mais **pas de descriptions narratives**. Ce sont des listes d'elements, pas des explications.

Les relations entre elements sont quasi-absentes (0.1 relation/diagramme en moyenne). La Vision detecte les noms sur les boites mais pas les fleches ni la logique du schema.

### Q4: "Les speaker notes existent-elles dans les PPTX du corpus ?"

**Verifie.** Oui, et c'est massif :

| PPTX | Slides | Slides avec notes | % | Moyenne chars/note |
|------|--------|-------------------|---|-------------------|
| Access to Customer Systems | 49 | 22 | **45%** | **551** |
| Business Scope FPS03 | 476 | 155 | **33%** | **893** |

Exemple de note orateur (Access to Customer Systems, slide 1) :
> "As per SAP DPA — SAP will always obtain consent before accessing customer systems/data. CAS — consent is obtained as part of the contract (i.e. the ser..."

C'est exactement le type de contenu explicatif qui manque dans les chunks actuels. Les notes sont du **contenu auteur verbatim** — elles respectent parfaitement l'invariant de tracabilite.

---

## 2. Analyse des retours Claude Web et ChatGPT

### Points de convergence (les deux IA sont d'accord)

1. **Le probleme est confirme et fondamental** — les deux reconnaissent que c'est la cause racine dominante qui explique la majorite des symptomes.

2. **Les TypeAwareChunks + rechunker sont la premiere action** — pas de debat. Ce qui existe doit etre branche avant d'explorer de nouvelles approches.

3. **Le Contextual Retrieval (piste C) vient APRES** — les deux disent qu'enrichir des chunks de 35 chars n'a pas de sens. D'abord la fondation, ensuite l'enrichissement.

4. **Les speaker notes sont une priorite haute** — contenu auteur, verbatim, respecte l'invariant, impact potentiellement massif.

5. **Le KG devra probablement etre re-extrait** — les claims issus de DocItems atomiques sont appauvris. ChatGPT et Claude Web convergent sur ce point.

### Points de divergence ou de nuance

**Claude Web** insiste sur la **question du "pourquoi"** — pourquoi les TypeAwareChunks n'ont-ils pas ete branches ? La reponse est maintenant claire : c'est une dette technique. Le ClaimFirst pipeline a ete concu pour l'extraction de claims (ou l'atomicite est un avantage) et l'integration avec Qdrant a ete faite en dernier (Phase 8 de l'orchestrateur) de maniere minimaliste (Passage → Qdrant 1:1).

**ChatGPT** apporte le concept de **Contextual Retrieval Bundle (CRB)** — l'idee que l'unite de retrieval doit etre une "reconstruction contextuelle" du DocItem, pas le DocItem lui-meme. C'est plus ambitieux que les TypeAwareChunks (qui sont des regroupements structurels) mais pourrait etre la cible a long terme.

**Claude Web** propose la reformulation de l'invariant : "Les metadonnees structurelles du document (titre, section, position) ne sont pas des inferences — elles sont des faits documentaires." Cette reformulation autorise l'ajout de prefixes contextuels deterministes (doc_title + section_title) sans violer l'invariant.

### Points d'attention souleves

**ChatGPT** : "ce n'est pas juste chunks trop petits, c'est une erreur de design — utiliser une unite concue pour l'extraction comme unite de retrieval". Il a raison. La separation DocItem (preuve KG) vs Chunk (lecture LLM) est le pivot architectural a formaliser.

**Claude Web** : "avant toute implementation, Phase 1 = diagnostic et validation rapide". Il a raison aussi. Il faut inspecter la qualite des TypeAwareChunks, valider les notes, comprendre l'ADR — ce qui est fait dans ce document.

---

## 3. Plan d'action propose (synthese des deux analyses)

### Phase 1 — Correction immediate avec l'existant (2-3 jours)

**1.1 — Brancher les TypeAwareChunks vers Qdrant au lieu des DocItems**

Le cache contient deja 2613 TypeAwareChunks pour le Business-Scope (vs 43060 DocItems). Modifier `orchestrator.py` pour utiliser les chunks du cache au lieu de convertir les DocItems 1:1.

Ajouter dans le payload Qdrant :
- `doc_title` (depuis DocumentContext)
- `section_title` (depuis le structural graph)

Filtrer les chunks trop courts (< 50 chars pour NARRATIVE_TEXT, < 20 chars pour TABLE/FIGURE).

**1.2 — Extraire et fusionner les speaker notes PPTX**

Ajouter dans l'extracteur PPTX : `slide.notes_slide.notes_text_frame.text` fusionne avec le texte visible de la slide. Le note est du contenu auteur verbatim — zero tension avec l'invariant.

**1.3 — Prefixe contextuel deterministe (pas d'appel LLM)**

Pour chaque chunk, prefixer le texte avec un contexte structurel :
```
[Document: Business Scope SAP S/4HANA Cloud Private Edition 2025]
[Section: Preparation de la conversion > Prerequis techniques]
[Slide 45]

SPAM/SAINT patch level 71 or higher must be applied...
```

Ce n'est pas de l'inference — c'est de la lecture de metadonnees documentaires. Conforme a la reformulation de l'invariant proposee par Claude Web.

### Phase 2 — Re-ingestion et validation (3-5 jours)

**2.1 — Re-ingerer un sous-corpus (5 documents cles)**

Choisir les 5 documents les plus cibles par le benchmark T1 human. Re-ingerer avec les TypeAwareChunks + notes + prefixe. Comparer la taille et la qualite des chunks avant/apres.

**2.2 — Benchmark de validation**

Relancer le benchmark T1 human (100 questions) en full-pipeline. Si le factual passe de 43% a 60%+, la these est validee. Comme le dit Claude Web : "si l'amelioration est marginale (<10pp), le probleme est ailleurs".

**2.3 — Decision sur le KG**

Selon les resultats du benchmark :
- Si les scores s'ameliorent significativement → re-extraire les claims depuis les nouveaux chunks sur le sous-corpus, comparer la richesse des claims
- Si marginal → le probleme est plus profond (embeddings, retrieval, questions du benchmark)

### Phase 3 — Enrichissement si necessaire (Sprint 3+)

- Contextual Retrieval avec LLM (piste C) — seulement si Phase 2 ne suffit pas
- Fix rendering Vision PPTX (piste E) — seulement si validation sur 10 diagrammes montre un gain
- Rechunker sur les TypeAwareChunks longs (> 2000 chars) — utiliser le rechunker existant (1500 chars target)

---

## 4. L'invariant reformule

Proposition de reformulation (inspiree Claude Web) :

**Ancien invariant** :
> "OSMOSIS ne deduit pas de verite des documents — il n'exploite que ce qui est clairement indique."

**Nouveau invariant propose** :
> "OSMOSIS ne produit pas d'affirmation sans source documentaire tracable. Les metadonnees structurelles du document (titre, section, position, notes orateur) sont des faits documentaires — pas des inferences. L'unite de preuve (Claim, KG) reste atomique et verbatim. L'unite de lecture (chunk Qdrant) peut etre enrichie par reconstruction contextuelle a partir de metadonnees structurelles sans appel LLM."

Cette reformulation :
- Preserve l'interdiction d'inferer du contenu
- Autorise l'ajout de contexte structurel (titre, section, page) sans violation
- Autorise les notes orateur (contenu auteur)
- Distingue explicitement unite de preuve (KG) et unite de lecture (Qdrant)
- Interdit toujours la description Vision interpretative dans le chemin de connaissance

---

## 5. Architecture cible (vision long terme)

```
Document brut
    |
[Extraction] Docling + Vision (gating) + Speaker Notes
    |
    +--- DocItems atomiques → ClaimFirst → Claims → KG (INCHANGE)
    |                         (unite de preuve, verbatim)
    |
    +--- TypeAwareChunks → Prefixe contextuel → Rechunker → Qdrant
                           (unite de lecture, enrichie)      (retrieval)
```

**Separation formelle** :
- **Unite de preuve** = DocItem/Claim : atomique, verbatim, ancrable. Pour le KG.
- **Unite de lecture** = TypeAwareChunk enrichi : contextuel, autonome, lisible. Pour le retrieval.

Les deux coexistent. Le lien est preserve via `item_ids` dans les chunks et `chunk_ids` dans les claims.
