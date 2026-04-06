# Sprint 2 — Pistes Architecturales pour la Qualite des Chunks

**Date** : 25 mars 2026
**Contexte** : Cause racine identifiee — les chunks Qdrant sont des fragments atomiques (median 68 chars) inutilisables par le LLM. Ce document presente les pistes d'amelioration identifiees apres analyse approfondie du pipeline, de l'etat de l'art, et du contenu reel des caches d'extraction.
**Objectif** : Obtenir un consensus multi-IA avant implementation.

---

## 1. Anatomie exacte du probleme

### Le pipeline actuel en 4 etapes

```
Document brut (.pptx / .pdf)
    |
[Etape 1] ExtractionPipelineV2 (Docling + Vision GPT-4o gating)
    |  → .v5cache.json (full_text + DocItems + TypeAwareChunks + VisionResults)
    |
[Etape 2] CacheLoader → Pass0Result
    |  → DocItems + TypeAwareChunks + VisionObservations (separees)
    |  PERTE : merge_vision = False (par design ADR-20260126)
    |  PERTE : sections non serialisees dans le cache
    |
[Etape 3] ClaimFirst → Passages (DocItem → Passage 1:1)
    |  PERTE : aucune aggregation
    |  PERTE : section_title non propage
    |  PERTE : parent_item_id perdu
    |
[Etape 4] Passages → Qdrant (MIN_CHARS=20, pas de re-chunking)
    |  PERTE : pas de contexte document dans le texte du chunk
    |  PERTE : pas de doc_title / section_title dans le payload
    |  PERTE : le rechunker.py (1500 chars, overlap 200) et text_chunker.py (512 tokens) EXISTENT mais ne sont PAS utilises
    |
[Qdrant] knowbase_chunks_v2 : ~15000 chunks, median 68 chars
```

### Ce qui EXISTE dans le cache mais n'est PAS exploite

L'analyse du cache `.v5cache.json` d'un PPTX Business-Scope (476 slides) revele :

| Element | Present dans le cache | Utilise par ClaimFirst | Utilise par Qdrant |
|---------|:---:|:---:|:---:|
| Texte complet linearise (1M+ chars) | Oui | Oui (via DocItems) | Non |
| Structure hierarchique (headings, sections) | Oui | Partiellement | Non |
| Vision GPT-4o (266 diagrammes analyses) | Oui (2011 elements detectes) | **Non** (merge_vision=False) | **Non** |
| Types de diagrammes (process_workflow, architecture) | Oui | Non | Non |
| Relations entre elements visuels | Faible (21 relations sur 266 diagrammes) | Non | Non |
| TypeAwareChunks (329 chunks structures) | Oui | **Non** (contourne par Passage 1:1) | Non |
| Speaker notes PPTX | **Non — jamais extraites** | — | — |
| Section titles | Partiellement (hash, pas le titre) | Non | Non |
| Document context (subject, version, scope) | Oui | Oui (pour claims) | Partiellement (axis_values) |

**Decouverte critique** : le pipeline d'extraction V2 produit des **TypeAwareChunks** (329 pour le PPTX exemple) qui sont des unites structurellement coherentes. Mais le ClaimFirst pipeline les **ignore** et travaille directement avec les DocItems atomiques (861 items pour le meme document). Le rechunker (`rechunker.py`, target 1500 chars) et le text_chunker (`text_chunker.py`, 512 tokens) existent tous les deux mais ne sont pas branches.

**Decouverte Vision PPTX** : sur les 266 diagrammes analyses par GPT-4o, les elements sont bien detectes (2011 elements, 7.6/diagramme en moyenne) mais les **relations sont quasi-absentes** (21 relations sur 266 diagrammes, 0.1/diagramme). La Vision extrait les noms/labels mais pas la structure logique (fleches, hierarchie, flux). De plus, pour les PPTX, le rendering des slides en images utilise un **placeholder gris** au lieu du vrai rendu — la Vision recoit donc une image vide et ne peut pas analyser le contenu visuel reel.

---

## 2. Les 6 pistes identifiees

### Piste A — Brancher le rechunker existant (Quick Win)

**Principe** : Utiliser le `rechunker.py` deja present dans le code (target 1500 chars, overlap 200, coupe aux limites de phrases) entre l'etape 3 (Passages) et l'etape 4 (Qdrant).

**Ce que ca fait** :
- Les passages courts (headings, bullets) sont fusionnes avec leurs voisins jusqu'a ~1500 chars
- Les passages longs (>2000 chars) sont decoupes proprement
- Les titres courts sont fusionnes avec le chunk suivant (logique existante dans rechunker.py)

**Avantages** :
- Zero cout LLM
- Code deja ecrit et teste
- Pas de re-ingestion necessaire (on peut re-chunker les Passages existants)
- Preserve la tracabilite (item_ids dans les SubChunks)

**Limites** :
- Fusion mecanique par proximite de position, pas par coherence semantique
- Ne resout pas le probleme des PPTX ou chaque bullet est un DocItem isole
- N'ajoute pas de contexte (le titre du document ou de la section)
- Ne resout pas le probleme Vision

**Effort** : 0.5-1 jour

### Piste B — Utiliser les TypeAwareChunks au lieu des DocItems

**Principe** : Le pipeline d'extraction V2 produit deja des `TypeAwareChunks` (329 pour le PPTX vs 861 DocItems). Ces chunks sont construits en respectant la structure du document (un chunk = une section coherente). Les envoyer a Qdrant au lieu des DocItems.

**Ce que ca fait** :
- Les chunks suivent la structure du document (heading + ses paragraphes = 1 chunk)
- Les tables sont gardees entieres
- Les figures avec leur legende

**Avantages** :
- Zero cout LLM
- Deja calcule dans le cache (pas de re-extraction)
- Structurellement coherent (respecte les frontieres de section)
- Moins de chunks (329 vs 861 = meilleur ratio signal/bruit)

**Limites** :
- Les TypeAwareChunks n'ont pas ete valides pour la qualite (ils ont ete construits mais jamais utilises)
- Il faut verifier si le mapping chunk → claims est preservable
- N'ajoute pas de contexte document/section explicite

**Effort** : 1-2 jours

### Piste C — Contextual Retrieval (Anthropic, 2024)

**Principe** : Ajouter un prefixe de contexte a chaque chunk avant l'embedding. Pour chaque chunk, generer un court texte (50-100 tokens) qui situe le chunk dans son document :
```
"Ce passage provient du Conversion Guide SAP S/4HANA 2023, section 'Preparation de la conversion',
sous-section 'Prerequis techniques'. Le document decrit les etapes de conversion d'un systeme SAP ERP
vers S/4HANA 2023."

[texte original du chunk]
```

**Ce que ca fait** :
- Le chunk devient auto-porteur (un expert humain peut comprendre de quoi il parle sans contexte externe)
- L'embedding capture le contexte documentaire en plus du contenu
- Le retrieval est plus precis (le cosine similarity capture "prerequis conversion S/4HANA" au lieu de juste "SPAM/SAINT")

**Resultats publies** (Anthropic, 2024) :
- -35% d'erreurs de retrieval (top-20) en combinaison avec BM25
- -67% quand combine avec BM25 + reranking

**Avantages** :
- Domain-agnostic (le contexte est genere automatiquement)
- Compatible avec n'importe quelle strategie de chunking (A ou B)
- Ameliore a la fois le retrieval ET la synthese (le LLM recoit le contexte)
- Preserve la tracabilite (le prefixe est une metadata, le texte original est intact)

**Limites** :
- **Necessite un appel LLM par chunk** (~15000 appels pour le corpus actuel)
- Cout : avec Qwen 14B en burst (~50 tokens out / chunk), ~15000 * 0.3s = ~1.25h en burst
- Alternative : utiliser un prompt template sans LLM (section_title + doc_title + doc_subject), moins bon mais zero cout
- **Casse potentiellement un invariant** : le prefixe est une "interpretation" du contexte, pas un verbatim. Si le LLM se trompe sur le contexte, le chunk porte une fausse information. Risque pour la tracabilite/auditabilite.

**Effort** : 2-3 jours (avec burst Qwen)

### Piste D — Extraction des Speaker Notes PPTX

**Principe** : python-pptx supporte nativement l'extraction des notes orateur (`slide.notes_slide.text_frame.text`). Les fusionner avec le contenu visible de la slide.

**Ce que ca fait** :
- Les notes orateur (qui contiennent souvent les explications detaillees, les chiffres precis, les SAP Notes referencees) deviennent partie du chunk
- Un chunk PPTX passe de "Maintain Bill Of Material" (30 chars) a "Maintain Bill Of Material — Cette fonctionnalite permet de creer et modifier des listes de materiaux dans SAP S/4HANA. La configuration se fait via la transaction CS01..." (300+ chars)

**Avantages** :
- Impact potentiellement massif sur les PPTX (80% des chunks < 100 chars)
- Pas d'interpretation — les notes sont du contenu auteur, pas de l'inference
- Respecte l'invariant de tracabilite (verbatim du document)
- Facile a implementer (python-pptx standard)

**Limites** :
- Necessite une re-ingestion des PPTX
- Les notes ne sont pas toujours presentes (certains PPTX n'ont pas de notes)
- Les notes peuvent contenir des commentaires internes non pertinents
- Ne resout pas le probleme des PDF

**Point d'attention** : il faut d'abord verifier si les PPTX du corpus ont des notes. Un scan rapide des fichiers sources repondra a cette question.

**Effort** : 0.5-1 jour (extraction) + re-ingestion

### Piste E — Fix du rendering Vision PPTX

**Principe** : Actuellement, le Vision Semantic Reader recoit un **placeholder gris** pour les slides PPTX au lieu du vrai rendu. Le code (`vision/analyzer.py:463`) genere un placeholder car le rendering PPTX → image est techniquement difficile. Fixer ce rendering permettrait a GPT-4o d'analyser les vrais slides.

**Ce que ca fait** :
- Les 111 chunks FIGURE_TEXT vides (sur 207) deviendraient des descriptions riches de diagrammes
- Les relations visuelles (fleches, hierarchie, flux) pourraient etre extraites

**Avantages** :
- Deja 266 diagrammes analyses — mais avec des images vides
- Le pipeline Vision est en place (gating, semantic reader)

**Limites** :
- Le rendering PPTX → image est complexe (LibreOffice headless, Aspose, ou service cloud)
- Cout GPT-4o Vision pour ~200 slides
- **Casse potentiellement un invariant** : la description Vision d'un diagramme est une **interpretation**, pas un verbatim. "3 boites reliees par des fleches" peut etre interprete comme un flux de processus ou une hierarchie — le systeme deduit une semantique
- Les relations detectees par Vision sont deja faibles (0.1/diagramme) meme sur les images disponibles

**Effort** : 3-5 jours (rendering + integration)

### Piste F — Chunking structure-aware par slide (PPTX) / par section (PDF)

**Principe** : Au lieu de chunker par DocItem atomique, chunker par **unite structurelle** :
- PPTX : 1 slide = 1 chunk (titre + tous les bullets + notes + description Vision)
- PDF : 1 section = 1 chunk (heading + tous les paragraphes jusqu'au prochain heading)

**Ce que ca fait** :
- Un chunk PPTX contient tout le contenu d'une slide = unite semantique coherente
- Un chunk PDF contient tout le contenu d'une section = contexte complet

**Avantages** :
- Respecte la structure documentaire (la slide/section est l'unite de sens voulue par l'auteur)
- Pas d'interpretation (on regroupe, on n'infere pas)
- Preserve la tracabilite (chaque chunk pointe vers sa page/section source)

**Limites** :
- Certaines slides/sections peuvent etre tres longues (3000+ chars) → depasse la fenetre d'embedding optimale
- Il faut gerer les cas limites (slide sans titre, section vide)
- Les tables multi-slides sont coupees
- Necessite de reconstruire la logique de regroupement depuis les DocItems (en utilisant section_id + reading_order)

**Effort** : 2-3 jours

---

## 3. Etat de l'art 2024-2025

### Outils et librairies identifies

| Outil | Type | Forces | Pertinence OSMOSIS |
|-------|------|--------|-------------------|
| **Docling** (IBM) | Extracteur unifie | PDF + PPTX, modele Granite local 258M, zero API | **Deja utilise** par ExtractionPipelineV2 |
| **Unstructured.io** | Extracteur | Bon partitioning par elements, tables | Alternative a Docling |
| **LlamaIndex SemanticChunker** | Chunking | Split par changement de topic (embedding-based) | Complementaire a la piste F |
| **Anthropic Contextual Retrieval** | Enrichissement | -35% erreurs retrieval | Piste C |
| **Jina Late Chunking** | Embedding | Chunks contextuels sans modification | Necessite modele Jina specifique |
| **RAPTOR** (2024) | Hierarchique | Resumes hierarchiques | Utile pour questions audit (T4) |

### Papers cles

- **Contextual Retrieval** (Anthropic, 2024) : -35 a -67% erreurs retrieval avec prefixe contextuel
- **Dense X Retrieval** (Proposition-based, 2024) : chunker par propositions independantes — precision maximale mais cout LLM eleve
- **RAPTOR** (2024) : resumes hierarchiques clusters — excellent pour multi-hop mais cout LLM
- **Parent Document Retrieval** (LangChain) : indexer petit, retourner grand — zero cout LLM

---

## 4. Combinaisons recommandees (par priorite)

### Niveau 1 — Quick wins sans re-ingestion (1-2 jours)

| Action | Piste | Impact attendu | Cout LLM |
|--------|-------|----------------|----------|
| Brancher le rechunker existant | A | +30-50% taille mediane chunks | Zero |
| Ajouter doc_title + section_title dans le payload Qdrant | — | Contexte pour le LLM | Zero |

### Niveau 2 — Re-ingestion ciblee (3-5 jours)

| Action | Piste | Impact attendu | Cout LLM |
|--------|-------|----------------|----------|
| Extraire speaker notes PPTX | D | Impact massif si notes presentes | Zero |
| Utiliser TypeAwareChunks au lieu de DocItems | B | Chunks 3x plus coherents | Zero |
| Chunking par slide (PPTX) / par section (PDF) | F | Chunks auto-porteurs | Zero |

### Niveau 3 — Enrichissement (5-10 jours)

| Action | Piste | Impact attendu | Cout LLM |
|--------|-------|----------------|----------|
| Contextual Retrieval (prefixe par chunk) | C | -35% erreurs retrieval | Moyen (burst) |
| Fix rendering Vision PPTX | E | 111 chunks vides → riches | Eleve (GPT-4o) |

---

## 5. Invariants impactes

| Invariant | Pistes qui le respectent | Pistes qui le challengent |
|-----------|--------------------------|--------------------------|
| Agnosticite domaine | Toutes | Aucune |
| Pas d'interpretation du contenu | A, B, D, F | **C** (prefixe LLM = interpretation du contexte), **E** (description Vision = interpretation des diagrammes) |
| Tracabilite verbatim | A, B, D, F | **C** (le prefixe n'est pas du verbatim) |
| Auditabilite | Toutes | **C** (si le prefixe est faux, le chunk porte une fausse metadata) |

### Sur l'invariant "pas d'interpretation"

Les pistes C et E introduisent une tension avec cet invariant. Deux perspectives :

**Position conservatrice** : le prefixe contextuel (C) et la description Vision (E) sont des inferences. Si le LLM dit "ce passage parle de prerequis de conversion" et que c'est faux, le chunk est contamine. Si la Vision dit "ce diagramme montre un flux de migration" et que c'est un organigramme, le claim extrait sera faux. L'invariant existe pour une raison.

**Position pragmatique** : un PPTX est par construction un support visuel qui necessite une interpretation pour etre exploitable. "3 boites reliees par des fleches" n'est pas une information — c'est la conclusion "flux de processus en 3 etapes : A → B → C" qui est l'information. Si on refuse toute interpretation des slides, on se condamne a des chunks de 30 chars qui ne servent a rien. Le compromis pourrait etre de **marquer explicitement les contenus inferes** (prefixe = "[CONTEXT INFERRED]", description Vision = "[VISUAL INTERPRETATION]") pour preserver la tracabilite.

---

## 6. Questions pour le consensus

1. **Faut-il d'abord verifier si les speaker notes existent dans nos PPTX** avant de lancer une strategie de re-ingestion ? (scan rapide ~30 min)

2. **Le Contextual Retrieval (piste C) est-il acceptable** malgre la tension avec l'invariant "pas d'interpretation" ? Le marquage explicite `[CONTEXT INFERRED]` est-il un compromis suffisant ?

3. **Doit-on re-extraire les claims** apres le re-chunking (tout le pipeline ClaimFirst) ou peut-on garder les claims existants et juste ameliorer les chunks Qdrant ? Les claims sont issus des memes DocItems atomiques — la re-extraction produirait-elle des claims meilleurs ?

4. **La combinaison B + D + F** (TypeAwareChunks + speaker notes + chunking structurel) est-elle suffisante sans recourir au Contextual Retrieval (C) ? Elle est 100% conforme aux invariants.

5. **Quel est le bon ordre** : quick win d'abord (piste A) pour mesurer l'impact, puis re-ingestion si necessaire ? Ou tout d'un coup ?

6. **Le rendering Vision PPTX (piste E) vaut-il l'investissement** etant donne que les relations detectees sont deja faibles (0.1/diagramme) meme quand la Vision recoit une vraie image ?

7. **Le rechunker (1500 chars target) est-il le bon seuil** ou faut-il un seuil different pour PPTX (une slide complete) vs PDF (une section) ?
