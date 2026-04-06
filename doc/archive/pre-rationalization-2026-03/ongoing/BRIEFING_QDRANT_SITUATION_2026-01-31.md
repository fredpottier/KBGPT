# Briefing Technique — Situation Qdrant dans OSMOSE

**Date :** 2026-01-31
**Objectif :** Permettre une réflexion architecturale sur le rôle de Qdrant dans le pipeline V2 stratifié.
**Contexte :** Ce document est destiné à être partagé avec un interlocuteur qui n'a pas accès au code.

---

## 1. Situation actuelle : Qdrant est vide

Les deux collections Qdrant existantes (`knowbase` et `concepts_proto`) contiennent **0 points**. Plus aucune donnée n'est persistée dans Qdrant depuis que le pipeline stratifié V2 est devenu le chemin d'import principal.

---

## 2. Les deux pipelines qui coexistent dans le code

### Pipeline V1 — "OSMOSE Agentique" (ancien, partiellement actif)

**Chemin :** Document → Docling → Chunking sémantique (512 tokens) → Embeddings 1024D → **Qdrant** + Neo4j

Ce pipeline :
- Découpe le document en **chunks sémantiques** (~512 tokens) avec un modèle de chunking classique
- Calcule un **embedding 1024D** (multilingual-e5-large, distance cosine) pour chaque chunk
- **Upsert chaque chunk dans Qdrant** avec un payload riche :
  - `text` : le contenu textuel du chunk
  - `document_id`, `document_name` : traçabilité vers le document source
  - `proto_concept_ids[]` : liste des concepts (ProtoConcept) détectés dans ce chunk
  - `canonical_concept_ids[]` : concepts promus après consolidation (Gatekeeper)
  - `anchored_concepts[]` : modèle d'ancrage hybride avec label, rôle et span
  - `context_id` : référence vers une SectionContext (schéma V1) pour filtrage structurel
  - `section_path` : chemin textuel de la section (ex: "1. Introduction / 1.1 Overview")
  - `char_start`, `char_end`, `token_count` : position dans le document
  - `tenant_id` : isolation multi-tenant
- Persiste des **ProtoConcepts** dans Neo4j avec cross-référence vers les chunk_ids Qdrant
- Les chunks Qdrant et les concepts Neo4j sont **bidirectionnellement liés** : le chunk connaît ses concepts, le concept connaît ses chunks

### Pipeline V2 — "Stratifié" (actif, celui qu'on utilise)

**Chemin :** Document → Docling → Pass 0 (structural) → Cache → Pass 1 (sémantique LLM) → Pass 2 (relations) → **Neo4j seulement**

Ce pipeline :
- **Pass 0** : Docling extrait des **DocItems** (paragraphes, headings, tables, figures — éléments atomiques du document) et des **TypeAwareChunks** (chunks layout-aware, ~3000 chars max, typés NARRATIVE/TABLE/FIGURE/CODE). Tout est sauvegardé dans un fichier cache `.knowcache.json`.
- **Pass 1** : Un LLM (Qwen 14B) lit les chunks et extrait des **assertions** (faits, définitions, prescriptions...). Chaque assertion est ancrée sur un **DocItem** (pas un chunk Qdrant). Les assertions sont ensuite liées à des **Concepts** via un LLM de linking. Un reranker ajuste les scores de confiance.
- **Pass 2** : Un LLM extrait les **relations** entre concepts (REQUIRES, ENABLES, etc.)
- **Persistence** : Tout va dans **Neo4j uniquement** :
  - `Document`, `Section`, `DocItem` (lazy, seulement ceux référencés par une Information)
  - `Subject`, `Theme`, `Concept`, `Information`, `AssertionLog`
  - `CONCEPT_RELATION` entre concepts
  - `VisionObservation` pour les figures/diagrammes
- **Qdrant n'est jamais appelé** : pas d'embedding, pas d'upsert, pas de cross-référence

---

## 3. Ce que le pipeline V2 a gagné vs perdu

### Gagné
- **Ancrage atomique** : l'Information est liée à un DocItem précis (un paragraphe, un heading) plutôt qu'à un chunk de 512 tokens qui peut mélanger plusieurs sujets
- **Extraction sémantique riche** : le LLM extrait des assertions typées (FACTUAL, PRESCRIPTIVE, DEFINITIONAL, CAUSAL, CONDITIONAL, PERMISSIVE, PROCEDURAL) avec confiance, au lieu de juste stocker du texte brut
- **Ontologie structurée** : Subject → Theme → Concept → Information avec types et relations, au lieu de ProtoConcepts plats liés à des chunks
- **Qualité de linking** : un LLM fait le choix du concept, avec un filtre d'admissibilité structurel et un reranker multi-signal, au lieu d'un simple matching textuel

### Perdu
- **Recherche vectorielle sur le corpus** : il n'est plus possible de faire une recherche par similarité sémantique sur les textes du document. Si un utilisateur pose une question et que le KG n'a pas la réponse, il n'y a plus de fallback.
- **Cross-référence chunk↔concept** : les concepts V2 ne savent pas quels passages textuels les supportent en tant que vecteurs. Le seul lien est `Information → DocItem`, qui donne le texte source mais pas un embedding permettant la recherche par similarité.
- **Filtrage structurel côté recherche** : le search service utilisait `context_id` dans les filtres Qdrant pour restreindre la recherche aux sections pertinentes (identifiées par le graph). Sans données dans Qdrant, ce mécanisme ne fonctionne plus.

---

## 4. Comment la recherche est censée fonctionner

Le service de recherche (`search.py`) implémente une architecture **Graph-First** en 3 modes :

### Mode REASONED (le meilleur)
1. Extraire les concepts de la question utilisateur (matching Neo4j full-text + Qdrant sémantique)
2. Trouver des chemins sémantiques entre ces concepts dans le graphe Neo4j
3. Collecter les `context_id` le long de ces chemins
4. **Filtrer Qdrant** avec ces `context_id` → récupérer les chunks pertinents
5. Synthétiser une réponse avec LLM

### Mode ANCHORED (fallback structural)
1. Pas de chemin sémantique trouvé, mais routage structurel possible
2. Identifier les Topics/Documents concernés
3. **Filtrer Qdrant** par `document_id`
4. Synthétiser

### Mode TEXT_ONLY (fallback pur RAG)
1. Aucun graphe exploitable
2. **Recherche Qdrant brute** par similarité vectorielle
3. Synthétiser

**Problème : les 3 modes dépendent de Qdrant pour la récupération des passages textuels.** Sans données dans Qdrant, aucun mode de recherche ne peut retourner du contenu textuel.

---

## 5. Les données V2 qui existent et qui pourraient alimenter Qdrant

### TypeAwareChunks (dans le cache Pass 0)
Ce sont des chunks layout-aware produits par Docling + StructuralGraphBuilder :
- `chunk_id` : identifiant unique
- `text` : contenu textuel
- `kind` : NARRATIVE_TEXT, TABLE_TEXT, FIGURE_TEXT, CODE_TEXT
- `section_id` : section du document
- `page_no`, `page_span_min`, `page_span_max` : localisation
- `item_ids[]` : liens vers les DocItems sources (référence Docling)
- `text_origin` : docling, vision_semantic, ocr, placeholder
- Taille max : ~3000 caractères (plus gros que les chunks V1 de ~512 tokens)

### Informations (dans Neo4j, produites par Pass 1)
Les assertions extraites et promues :
- `text` : le texte de l'assertion
- `type` : FACTUAL, PRESCRIPTIVE, DEFINITIONAL, etc.
- `confidence` : score de confiance
- `concept_id` : le concept lié
- `anchor` : le DocItem source avec `span_start` et `span_end`

### Concepts (dans Neo4j, produits par Pass 1)
- `concept_id`, `name`
- Liés à des Themes et un Subject
- Liés à des Informations via `HAS_INFORMATION`
- Liés à d'autres Concepts via `CONCEPT_RELATION`

---

## 6. Les questions architecturales à trancher

### Q1 : Que met-on dans Qdrant ?

**Option A — Les TypeAwareChunks (comme V1 mais mieux typés)**
- Avantage : couverture complète du document, fallback RAG possible
- Inconvénient : les chunks sont gros (3000 chars), mélangent potentiellement des sujets
- Payload : `chunk_id`, `text`, `kind`, `section_id`, `page_no`, `doc_id`, `tenant_id`, éventuellement `concept_ids[]` post-linking

**Option B — Les Informations (assertions extraites)**
- Avantage : chaque point Qdrant est une unité sémantique validée, liée à un concept
- Inconvénient : couverture partielle (seules les assertions promues, ~65% du contenu utile), pas de fallback sur le texte brut
- Payload : `info_id`, `text`, `type`, `confidence`, `concept_id`, `concept_name`, `theme`, `doc_id`, `section_id`

**Option C — Les deux (dual-layer)**
- Layer 1 : TypeAwareChunks pour le fallback RAG et la couverture complète
- Layer 2 : Informations pour la recherche précise, concept-aware
- Plus complexe mais offre le meilleur des deux mondes

### Q2 : Quand calcule-t-on les embeddings ?

**Option 1 — À l'import (dans le reprocess, après Pass 1)**
- Avantage : immédiat, tout est prêt pour la recherche
- Inconvénient : ajoute du temps d'import (embedding 1024D pour chaque chunk/information)

**Option 2 — En différé (job asynchrone post-import)**
- Avantage : l'import reste rapide, l'embedding est fait en background
- Inconvénient : les données ne sont pas immédiatement cherchables

### Q3 : Quel modèle d'embedding ?

Actuellement le code V1 utilise `multilingual-e5-large` (1024D, cosine). Options :
- Garder le même pour compatibilité
- Passer à un modèle plus récent (e5-mistral, etc.) si les performances justifient le changement

### Q4 : Comment relier les points Qdrant au graphe V2 ?

Le search service Graph-First filtre Qdrant par `context_id` (= SectionContext V1). En V2, l'équivalent serait :
- `section_id` : la Section V2 du chunk/information
- `concept_id` : le concept lié (pour les Informations)
- `doc_id` : le document source

Il faut adapter le search service pour utiliser ces nouveaux champs au lieu de `context_id`.

### Q5 : Que fait-on du search service existant ?

Le search service actuel mélange :
- Du code V1 (ProtoConcepts, context_id, canonical_concept_ids)
- Du code Graph-First (chemins sémantiques, modes REASONED/ANCHORED/TEXT_ONLY)
- Du code Graph-Guided (enrichissement par voisinage graphe)

Il faudra adapter ce service pour :
1. Comprendre les nouveaux nœuds V2 (Concept, Information, Theme, Subject)
2. Utiliser les bons champs de filtrage Qdrant
3. Maintenir les 3 modes de recherche

---

## 7. Schéma comparatif des deux modèles

### Modèle V1 (ancien)
```
Document
  └─ Chunk (Qdrant, 512 tokens, embedding 1024D)
       ├─ proto_concept_ids[] → ProtoConcept (Neo4j)
       ├─ canonical_concept_ids[] → CanonicalConcept (Neo4j)
       └─ context_id → SectionContext (Neo4j V1)

Recherche : Query → Embedding → Qdrant search → Chunks → Enrichissement KG → Synthèse
```

### Modèle V2 (actuel, sans Qdrant)
```
Document (Neo4j)
  └─ Section (Neo4j)
       └─ DocItem (Neo4j, lazy)
            └─ Information (Neo4j, assertion extraite)
                 └─ Concept (Neo4j) → Theme → Subject

Chunks (cache seulement, pas dans Qdrant)
  └─ TypeAwareChunk (3000 chars, typé NARRATIVE/TABLE/FIGURE/CODE)
       └─ item_ids[] → DocItem (pour anchor resolution)

Recherche : ??? (pas de vecteurs, pas de fallback RAG)
```

### Modèle V2 cible (à définir)
```
Document (Neo4j)
  └─ Section (Neo4j)
       └─ DocItem (Neo4j)
            └─ Information (Neo4j + Qdrant?)
                 └─ Concept (Neo4j + Qdrant?)

TypeAwareChunk (Qdrant, embedding 1024D)
  └─ Payload: section_id, doc_id, kind, concept_ids[]?

Recherche : Query → Graph-First → Qdrant filtré → Synthèse enrichie KG
```

---

## 8. Contraintes et points d'attention

1. **Le cache contient tout le nécessaire** : les TypeAwareChunks avec texte, section_id, page_no et item_ids sont dans le `.knowcache.json`. On peut les vectoriser sans re-extraire.

2. **Les Informations sont déjà dans Neo4j** : elles ont un texte, un concept lié, un DocItem source. On peut les vectoriser à partir de Neo4j.

3. **Le modèle d'embedding est déjà configuré** : `multilingual-e5-large` (1024D) est prêt, le client Qdrant a toutes les méthodes nécessaires (`upsert_chunks`, `search_with_tenant_filter`, etc.).

4. **Le search service existe mais est cassé** : il attend des données dans Qdrant qui n'existent plus. Il faudra l'adapter quelle que soit l'option choisie.

5. **Performance** : l'embedding de ~400 chunks (doc de 150 pages) prend quelques secondes. Ce n'est pas un bottleneck.

6. **Multi-tenancy** : le système est déjà conçu pour l'isolation par `tenant_id` dans Qdrant. Pas de risque de mélange.

7. **L'import burst crée le cache** : le burst (Docling + Vision) produit le cache qui contient les chunks. Le reprocess (Pass 1+2) produit les Informations et Concepts. La vectorisation Qdrant pourrait se faire à l'un ou l'autre moment, ou aux deux.
