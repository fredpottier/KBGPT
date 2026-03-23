# OSMOSIS — Analyse structurante du KG-Driven Retrieval

**Date** : 23 mars 2026
**Auteur** : Analyse Claude Opus + données benchmark
**Statut** : Document de travail — en attente review ChatGPT

---

## 1. La problématique

OSMOSIS se positionne comme un système de Q&A documentaire dont le Knowledge Graph (KG) apporte une valeur différenciante par rapport à un RAG vectoriel classique. La promesse : le KG identifie les bons concepts, traverse les relations sémantiques, et retourne des réponses tracées, sourcées et contextualisées — là où un RAG cherche "à l'aveugle" dans un espace vectoriel.

**Le benchmark réalisé révèle que cette promesse n'est que partiellement tenue.** Sur certains axes (détection des contradictions), OSMOSIS surpasse significativement le RAG. Mais sur d'autres (exactitude factuelle sur questions humaines, traçabilité), le RAG fait **mieux** qu'OSMOSIS. Ce n'est pas un problème de paramétrage — c'est un problème structurel.

---

## 2. Les constatations du benchmark

### 2.1 Méthodologie

- **500 questions** réparties en 3 tâches (T1 Provenance, T2 Contradictions, T4 Audit) × 2 types (KG-derived et humaines)
- **Même LLM** (Qwen 2.5 14B AWQ via vLLM) pour les deux systèmes
- **Même prompt** de synthèse
- **RAG baseline** : même embeddings (multilingual-e5-large via TEI), même collection Qdrant, mais SANS KG
- **OSMOSIS** : KG activé avec Claim→Chunk retrieval (claims vectorisés Neo4j → chunk_ids → Qdrant)
- **Évaluation** : LLM-as-judge (GPT-4o-mini) sur chaque réponse

### 2.2 Résultats globaux

| Tâche | Questions | OSMOSIS victoires | RAG victoires |
|-------|-----------|-------------------|---------------|
| T1 KG | 100 | **5** | 0 |
| T1 Human | 100 | 1 | **5** |
| T2 KG | 100 | **4** | 1 |
| T2 Human | 50 | **5** | 0 |
| T4 KG | 100 | **5** | 0 |
| T4 Human | 50 | 1 | **4** |
| **Total** | **500** | **21** | **10** |

### 2.3 Les forces confirmées d'OSMOSIS

**T2 Human (contradictions) — OSMOSIS domine à 100% :**
- Deux positions exposées : 100% vs 26%
- Tension mentionnée : 100% vs 0%
- Arbitrage silencieux : 0% vs 44%

Le KG détecte et expose les tensions entre documents (REFINES, QUALIFIES) que le RAG ignore complètement. C'est le différenciateur le plus net.

**T1/T4 KG — OSMOSIS systématiquement meilleur :**
- Citations : 95% vs 61% (T1 KG)
- Traçabilité : 90% vs 86% (T4 KG)
- False IDK : 25% vs 54% (T1 KG) — le KG aide à ne pas refuser de répondre

### 2.4 La faiblesse critique : OSMOSIS perd sur les questions humaines

**T1 Human — RAG gagne 5-1 :**
- Exactitude factuelle : OSMOSIS 17.6% vs RAG 37%
- Correct source : OSMOSIS 23% vs RAG 39%
- False IDK : OSMOSIS 58% vs RAG 40%

**T4 Human — RAG gagne 4-1 :**
- Sources mentionnées : OSMOSIS 8% vs RAG 88%
- Traçabilité : OSMOSIS 8% vs RAG 78%
- Complétude : OSMOSIS 27.9% vs RAG 60.3%

---

## 3. Analyse des causes racines

### 3.1 Le problème fondamental : le KG-guided retrieval retourne les MAUVAIS chunks

L'analyse question par question montre un pattern récurrent :

**Exemple — "Quel est le prérequis Unicode pour la conversion S/4HANA ?"**

| | OSMOSIS (Claim→Chunk) | RAG (Qdrant pur) |
|---|---|---|
| **Chunk top 1** | "We recommend that you consume the simplification items via SAP Readiness Check" | **"As a prerequisite for the conversion, your system needs to be a Unicode system"** |
| **Chunk top 2** | "In order to generate the stack.xml, you need to have an SAP S/4HANA license" | "As a prerequisite for the conversion, your system needs to be a Unicode system" |
| **Résultat** | "Information not available" | Réponse correcte avec citation |

Le RAG retourne directement le chunk qui contient la réponse. OSMOSIS retourne des chunks liés au sujet général (conversion) mais pas au fait précis (Unicode). Le LLM dit alors "information not available" car la réponse n'est pas dans les chunks qu'on lui a donnés.

### 3.2 Pourquoi les chunks KG sont non pertinents

Le Claim→Chunk retrieval suit ce chemin :

```
Question utilisateur
  → Embedding de la question
  → Neo4j vector search sur claim_embedding (index 7936 claims sur 15861)
  → Top 10 claims les plus proches sémantiquement
  → chunk_ids de ces claims → Qdrant scroll
  → Chunks retournés au LLM
```

**Trois problèmes dans ce chemin :**

**Problème A — Couverture partielle des embeddings claim.**
Seuls 7936 claims sur 15861 (50%) ont des embeddings dans Neo4j. Les 7925 autres sont invisibles pour le vector search Neo4j. Si le fait cherché est dans un claim sans embedding, il ne sera jamais trouvé par le Niveau 2.

**Problème B — Le claim vector search ne cherche pas le bon grain.**
Le vector search sur les claims cherche des claims sémantiquement proches de la question. Mais un claim est un fait atomique extrait ("SAP S/4HANA uses Azure Subscription for each customer"), pas un passage documentaire. La question "Quel prérequis Unicode ?" est sémantiquement proche de claims sur la conversion en général, pas du claim spécifique sur Unicode — si ce claim existe.

**Problème C — Le mapping claim→chunk est 1:1, pas contextuel.**
Chaque claim pointe vers UN chunk Qdrant (via chunk_ids). Mais ce chunk peut ne contenir que le verbatim du claim (une phrase) sans le contexte documentaire nécessaire pour répondre à la question. Le RAG retourne des chunks de ~500-800 chars qui contiennent le contexte complet.

### 3.3 La fusion KG/Qdrant est déséquilibrée

Même avec un minimum de 3 chunks Qdrant garanti dans la fusion, les 7 chunks KG (souvent non pertinents pour les questions humaines) diluent le contexte. Le LLM reçoit un contexte majoritairement hors-sujet et refuse de répondre.

---

## 4. État actuel de l'organisation Neo4j

### 4.1 Nœuds et volumes

| Label | Count | Rôle |
|-------|-------|------|
| Claim | 15 861 | Fait atomique extrait d'un document |
| Entity | 7 059 | Entité nommée mentionnée dans les claims |
| ClaimCluster | 2 381 | Groupes de claims similaires |
| QuestionSignature | 755 | Réponse factuelle extraite (valeur + question) |
| QuestionDimension | 382 | Question factuelle canonique (pivot de comparaison) |
| CanonicalEntity | 267 | Entité dédupliquée (pivot de résolution) |
| WikiArticle | 69 | Articles de synthèse générés |
| Facet | 9 | Domaines thématiques |

### 4.2 Relations clés

| Relation | Count | Rôle |
|----------|-------|------|
| ABOUT | 25 634 | Claim → Entity (ancrage sémantique) |
| IN_CLUSTER | 7 728 | Claim → ClaimCluster (regroupement) |
| SIMILAR_TO | 4 208 | Claim ↔ Claim (similarité) |
| BELONGS_TO_FACET | 2 659 | Claim → Facet (thème) |
| CHAINS_TO | 1 547 | Claim → Claim (chaîne narrative) |
| ANSWERS | 770 | QS → QD (réponse à une question factuelle) |
| SAME_CANON_AS | 379 | Entity → CanonicalEntity (synonymie) |
| REFINES | 280 | Claim → Claim (raffinement) |
| QUALIFIES | 249 | Claim → Claim (qualification/nuance) |
| CONTRADICTS | 2 | Claim → Claim (contradiction directe) |

### 4.3 Propriétés critiques sur Claim

- `claim_id`, `text`, `verbatim_quote`, `doc_id`, `page_no`
- `chunk_ids` : **100% rempli** — pont direct vers Qdrant
- `embedding` : **50% rempli** (7936/15861) — bottleneck pour le vector search Neo4j
- `structured_form_json` : triple SPO (sujet, prédicat, objet)
- `claim_type` : FACTUAL (95%), PRESCRIPTIVE (3.6%), DEFINITIONAL (1.4%)

### 4.4 Lien Qdrant

Collection `knowbase_chunks_v2` : ~15 000 chunks avec embeddings 1024d (multilingual-e5-large). Le champ payload `chunk_id` matche exactement le format de `Claim.chunk_ids` : `"default:DOC_ID:#/texts/N"`.

### 4.5 QuestionDimension (Phase B — récemment activée)

382 QuestionDimensions avec :
- `canonical_question` : question factuelle en anglais
- `embedding` : vecteur 1024d (backfillé le 23 mars 2026)
- Index vectoriel `qd_embedding` : ONLINE
- Couverture : 755 claims sur 15861 (4.8%) ont une QuestionSignature liée

---

## 5. Le fossé structurel : Claims vs Chunks

C'est le cœur du problème. OSMOSIS a **deux univers de retrieval** qui ne sont pas alignés :

### Univers 1 : Les Claims (Neo4j)
- Faits **atomiques** extraits par LLM
- Grain fin : une phrase, un fait
- Structurés : SPO, type, entités, relations
- **Mais** : 50% sans embedding, texte court, contexte perdu

### Univers 2 : Les Chunks (Qdrant)
- **Passages** documentaires bruts
- Grain moyen : 500-800 chars, contexte préservé
- Non structurés : texte pur + métadonnées (doc_id, page)
- **Mais** : pas de relations, pas de détection de contradictions

### Le mapping `chunk_ids` ne résout pas le fossé

Le `chunk_ids` sur chaque Claim pointe vers le chunk dont le claim a été extrait. Mais :
- Un chunk contient souvent **plusieurs claims** (ou parties de claims)
- Le claim ne capture qu'un fait du chunk, pas tout le contexte
- Si la question porte sur un aspect NON extrait comme claim (ex: "prérequis Unicode"), le claim vector search ne le trouve pas, même si le chunk Qdrant le contient

**Le RAG cherche dans les chunks (complets, contextuels). OSMOSIS cherche dans les claims (atomiques, partiels) puis va récupérer les chunks associés. Si le fait n'est pas un claim, OSMOSIS le rate.**

---

## 6. Propositions architecturales

### Proposition A — "KG-Enriched Qdrant" (évolution incrémentale)

**Principe** : Ne pas remplacer les chunks Qdrant par les chunks KG. Au lieu de ça, TOUJOURS faire le search Qdrant vectoriel (comme le RAG), puis ENRICHIR les résultats avec les métadonnées KG.

```
Question → Qdrant vector search → top 10 chunks (comme le RAG)
        → Pour chaque chunk : Neo4j lookup par chunk_id
          → Trouver le/les Claims liés à ce chunk
          → Extraire entity_names, contradiction_texts, QD/QS
        → Injecter ces métadonnées dans le contexte LLM
        → Synthèse enrichie
```

**Avantages** :
- Le retrieval est AUSSI BON que le RAG (mêmes chunks)
- Les enrichissements KG AJOUTENT de la valeur sans RETIRER de la qualité
- Pas de risque de rater un fait non-claim
- Simple à implémenter

**Inconvénients** :
- Le KG ne PILOTE pas la recherche, il ne fait qu'enrichir
- Pas de routing par QuestionDimension
- Ne différencie pas structurellement OSMOSIS d'un "RAG + post-processing"

### Proposition B — "Dual-Pool Score-Based" (évolution intermédiaire)

**Principe** : Faire les deux searches en parallèle (Qdrant + Neo4j claims), puis fusionner par pertinence estimée pour la question spécifique, pas par source.

```
Question → [Parallèle]
  → Qdrant vector search → 10 chunks avec scores
  → Neo4j claim vector search → 10 claims → chunk_ids → Qdrant fetch
  → Fusion : re-scorer TOUS les chunks par pertinence pour la question
    (via cross-encoder ou cosine avec l'embedding de la question)
  → Top 10 par pertinence, quelle que soit la source
  → Enrichir avec métadonnées KG
```

**Avantages** :
- Les chunks les plus pertinents gagnent, indépendamment de la source
- Les chunks KG qui sont pertinents montent naturellement
- Les chunks KG non pertinents sont éliminés par le re-scoring
- Compatible avec le QD routing comme "boost" (pas comme remplacement)

**Inconvénients** :
- Le re-scoring ajoute de la latence
- Nécessite un cross-encoder ou un calcul de similarité supplémentaire
- Plus complexe à implémenter

### Proposition C — "KG-Driven Scope + Qdrant Proof" (architecture cible)

**Principe** : Le KG ne retourne pas des chunks — il définit le PÉRIMÈTRE de recherche. Qdrant cherche ensuite les preuves textuelles dans ce périmètre.

```
Question → KG Resolution
  → Identifier les Entities pertinentes (via Entity embedding ou QD match)
  → Identifier les Documents pertinents (via claims ABOUT ces entities)
  → Identifier les Tensions (REFINES, QUALIFIES entre ces claims)

Question → Qdrant search FILTRÉ par les documents identifiés par le KG
  → Vector search DANS les documents du périmètre KG
  → Les chunks retournés sont pertinents ET dans le bon contexte
  → Enrichir avec les métadonnées KG (tensions, entités)
```

**Avantages** :
- Le KG PILOTE vraiment la recherche (définit le périmètre)
- Qdrant cherche les PREUVES dans le périmètre identifié
- Combine la précision du KG (bons documents) avec la robustesse du vector search (bons passages)
- Exploite les relations ABOUT, SAME_CANON_AS, BELONGS_TO_FACET pour le scoping
- Cohérent avec l'ADR North Star : "Le KG est le routeur, Qdrant est la source de preuves"

**Inconvénients** :
- Plus complexe à implémenter
- Dépend de la qualité du entity resolution (si les entités ne sont pas trouvées, le scoping rate)
- Nécessite un fallback Qdrant non-filtré si le scoping est trop restrictif

### Proposition D — Hybride progressive (recommandée)

**Principe** : Combiner A (court terme), B (moyen terme) et C (long terme) avec des points de mesure intermédiaires.

**Phase 1 (immédiat)** — Proposition A : KG-Enriched Qdrant
- Le search Qdrant reste le même que le RAG
- On enrichit les chunks retournés avec les métadonnées KG
- **Résultat attendu** : aussi bon que le RAG sur T1/T4 Human, meilleur sur T2
- **Métrique de validation** : OSMOSIS ≥ RAG sur toutes les tâches

**Phase 2 (court terme)** — Proposition C light : KG-Driven Document Scoping
- Le KG identifie les documents pertinents (via Entity resolution)
- Qdrant cherche dans ces documents (filtre par doc_id)
- Si le scoping retourne < 3 documents, fallback sur Qdrant non-filtré
- **Résultat attendu** : meilleure précision car le search est focalisé
- **Métrique de validation** : factual_correctness +10-15% vs Phase 1

**Phase 3 (moyen terme)** — Proposition C complète : KG Scope + QD Precision
- Le QD routing s'ajoute pour les questions factuelles comparables
- Le KG scope s'enrichit avec les SAME_CANON_AS et les Facets
- Les tensions cross-doc sont systématiquement surfacées
- **Résultat attendu** : OSMOSIS significativement supérieur sur tous les axes

---

## 7. Recommandation immédiate

**Implémenter la Proposition A maintenant** et relancer le benchmark pour valider que OSMOSIS ≥ RAG sur toutes les tâches.

Le changement est minimal : au lieu de remplacer les chunks Qdrant par les chunks KG, on fait le search Qdrant normal puis on enrichit les résultats. Le code existe déjà (`_enrich_chunks_with_kg`) — il suffit de changer l'ordre d'exécution dans `search_documents()`.

Le gain sera immédiat : les scores T1/T4 Human remonteront au niveau du RAG (mêmes chunks) + les enrichissements KG ajouteront les entités et tensions que le RAG n'a pas.

C'est la base minimale pour ensuite construire les phases 2 et 3 qui apporteront le vrai différenciateur.

---

## 8. Questions ouvertes pour ChatGPT

1. La Proposition C (KG-Driven Scope) est-elle compatible avec l'ADR North Star et le modèle ClaimKey/Information/Context ?
2. Le fossé Claims vs Chunks est-il résolvable sans refondre l'extraction (augmenter la couverture des claims à 100%) ?
3. La Proposition D (hybride progressive) est-elle la bonne stratégie de transition, ou faut-il viser directement la Proposition C ?
4. Le re-scoring de la Proposition B est-il nécessaire si la Proposition C (scoping) fonctionne ?
5. Comment mesurer objectivement que le KG "pilote" la recherche vs "enrichit" un RAG ?
