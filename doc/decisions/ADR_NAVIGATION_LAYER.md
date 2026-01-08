# ADR_NAVIGATION_LAYER — Contextual Navigation Graph (Non-Semantic Layer)

**Date:** 2026-01-01
**Révision:** 2026-01-06 (validation implémentation complète)
**Auteurs:** ChatGPT (spec + review), Claude Code (documentation + implémentation)
**Status:** ✅ IMPLÉMENTÉ (100%) - Janvier 2026

**Changelog:**
- v1.0 : Spec initiale (ChatGPT)
- v1.1 : Ajout WindowContext constraints, Normative Semantics of Weights, Misuse Scenarios, Non-Promotion Clause (review ChatGPT)
- v1.2 : Implémentation complète (Claude Code)

---

## Implementation Status (Janvier 2026)

| Composant | Fichier | Status |
|-----------|---------|--------|
| **Phase 1: Infrastructure** | | ✅ **COMPLET** |
| ContextNode model | `navigation/types.py` | ✅ |
| NavigationLayerBuilder | `navigation/navigation_layer_builder.py` | ✅ |
| NavigationLayerConfig | `navigation/types.py` | ✅ |
| **Phase 2: DocumentContext** | | ✅ **COMPLET** |
| DocumentContext nodes | `navigation/types.py` | ✅ |
| MENTIONED_IN relations | `navigation_layer_builder.py` | ✅ |
| IN_DOCUMENT relations | `navigation_layer_builder.py` | ✅ |
| **Phase 3: SectionContext** | | ✅ **COMPLET** |
| SectionContext nodes | `navigation/types.py` | ✅ |
| Section path extraction | `navigation_layer_builder.py` | ✅ |
| **Phase 4: WindowContext** | | ✅ **COMPLET** |
| WindowContext nodes (désactivé par défaut) | `navigation/types.py` | ✅ |
| CENTERED_ON relations | `navigation_layer_builder.py` | ✅ |
| Caps & guards (ADR) | `NavigationLayerConfig` | ✅ |
| **Phase 5: Validation** | | ✅ **COMPLET** |
| Graph lint commands (NAV-001 à NAV-004) | `navigation/graph_lint.py` | ✅ |
| RAG whitelist enforcement | `navigation/types.py` | ✅ |
| **Phase 6: API** | | ✅ **COMPLET** |
| GET /navigation/stats | `api/routers/navigation.py` | ✅ |
| GET /navigation/validate | `api/routers/navigation.py` | ✅ |
| GET /navigation/document/{id} | `api/routers/navigation.py` | ✅ |
| GET /navigation/concept/{id}/mentions | `api/routers/navigation.py` | ✅ |
| **Intégration Pipeline** | | ✅ **COMPLET** |
| build_for_document() dans osmose_agentique | `ingestion/osmose_agentique.py:1173` | ✅ |

**Architecture implémentée:**
```
navigation/
├── __init__.py                  # Exports publics
├── types.py                     # ContextNode, DocumentContext, SectionContext, WindowContext
├── navigation_layer_builder.py  # Builder Neo4j (create, link, compute weights)
└── graph_lint.py                # 4 règles lint (NAV-001 à NAV-004)

api/routers/navigation.py        # 4 endpoints REST
```

---

## Context

Le KG OSMOSE est conçu pour extraire des **relations sémantiques fortes** (REQUIRES, ENABLES, …) avec **evidence**.
Après Pass 2 + consolidation + ER, une proportion élevée de concepts reste isolée (~66%). Cette isolation est **attendue** : de nombreux concepts ne participent pas à des relations causales explicitement exprimées dans le texte.

Le besoin produit "cortex documentaire" exige aussi :

* navigation corpus-level,
* exploration de contexte,
* émergence de hubs,
* sans introduire de causalité/hallucination.

---

## Decision

Nous introduisons une **couche de navigation** indépendante de la couche de raisonnement :

* **Aucun edge de navigation ne relie directement Concept→Concept**.
* Les liens de navigation passent **exclusivement** par des nœuds intermédiaires appelés **ContextNode**.
* Les ContextNodes représentent des "unités de contexte" déterministes (document, section, window, topic…).
* Cette couche est **strictement non sémantique** : elle décrit le corpus, pas le monde.

---

## Epistemic Separation (Non-negotiable)

### Semantic Relations Layer (Reasoning)

* Edges typés entre CanonicalConcepts (REQUIRES, ENABLES, …)
* Evidence obligatoire et traçable
* Utilisée par RAG/reasoning

### Navigation Layer (Contextual)

* Concept → ContextNode (MENTIONED_IN / APPEARS_IN)
* ContextNode → Document (PART_OF / IN_DOCUMENT)
* Jamais consommée par le moteur de raisonnement
* Jamais consolidée en CanonicalRelation

---

## Why ContextNodes (and not Concept→Concept co-occurrence)

Le lien Concept→Concept "CO_OCCURS" est dangereux car :

* Il ressemble à une relation sémantique
* Il peut être involontairement consommé par des requêtes ou le RAG
* Il pollue la topologie du graphe conceptuel

Le modèle **Concept→Context→Concept** impose une séparation structurelle :
**impossible** de confondre navigation et sémantique sans acte explicite.

---

## Types of ContextNodes (initial scope)

| Type | Description | context_id | Cardinalité |
|------|-------------|------------|-------------|
| **DocumentContext** | Document entier | `doc:{document_id}` | 1 par document |
| **SectionContext** | Section (header path) | `sec:{document_id}:{section_path_hash}` | ~5-20 par document |
| **WindowContext** | Fenêtre glissante (chunk i-1/i/i+1) | `win:{chunk_id}` | 1 par chunk ⚠️ |

*Le système reste agnostique ; ces ContextNodes sont génériques.*

### ⚠️ WindowContext Constraints (CRITICAL)

WindowContext a une cardinalité **linéaire avec le corpus** contrairement à DocumentContext/SectionContext.
Sans garde-fous, cela peut créer une explosion de nœuds et des requêtes coûteuses.

**Règles obligatoires :**

```
WindowContext MUST:
- Be DISABLED by default (feature flag: ENABLE_WINDOW_CONTEXT=false)
- Be capped: max 50 windows per document
- Have traversal depth ≤ 1 hop in navigation queries
- NEVER be used comme source de ranking global
```

**Quand activer WindowContext :**
- Uniquement si SectionContext est insuffisant pour la granularité souhaitée
- Après validation de performance sur corpus représentatif

---

## Data & Computation

* Génération **déterministe**, sans LLM.
* Attributs de poids (counts, PMI, doc_count) stockés sur les relations Concept→Context.
* Budgets top-N appliqués **au moment de la génération** (évite explosion).

### Normative Semantics of Weights

Les attributs `weight`, `count`, `doc_count` sur les relations `MENTIONED_IN` ont une sémantique stricte.

**Ce que `weight` signifie :**
- Une mesure de **fréquence normalisée** dans le contexte donné
- Monotone : plus de mentions → weight plus élevé
- Déterministe : même corpus → même weight

**Ce que `weight` NE signifie PAS :**
- ❌ Importance conceptuelle
- ❌ Centralité sémantique
- ❌ Probabilité ou confiance
- ❌ Relation causale

**Règles de comparabilité :**

```
weight IS comparable:
- Within the same ContextNode type (DocumentContext vs DocumentContext)
- Within the same document

weight is NOT comparable:
- Across different ContextNode types (DocumentContext vs SectionContext)
- Across different tenants
- As proxy for semantic importance
```

**Terminologie UI :**
> Toute métrique dérivée de `weight` doit être labellée **"corpus prominence"** ou **"mention frequency"**,
> jamais **"importance"** ou **"relevance"**.

---

## RAG / Reasoning Contract

> **CRITICAL**: Le RAG assembler **n'a pas le droit** de traverser la navigation layer pour inférer des relations.

La navigation layer peut être utilisée **uniquement** pour :

* Proposer des concepts voisins "à explorer"
* Router des recherches (choisir docs/sections/chunks à récupérer)
* UI graph exploration

---

## Consequences

### Pros

* Forte connectivité sans hallucination
* Navigation corpus-level
* Séparation robuste des couches
* Agnostique métier

### Cons

* Complexité de modèle + UI (deux couches)
* Nécessite des contraintes/guardrails dans requêtes & code

---

## Guardrails

* Contraintes Neo4j (voir section Schema)
* Endpoints séparés API (semantic vs navigation)
* Tests unitaires : "RAG never uses navigation edges"

---

## Misuse Scenarios & Anti-patterns

Cette section documente les **mauvais usages** prévisibles pour les prévenir.

### ❌ Anti-pattern 1 : Interpréter la co-occurrence comme relation

```cypher
// MAUVAIS - Ne jamais interpréter ceci comme une "relation"
MATCH (c)-[:MENTIONED_IN]->(:ContextNode)<-[:MENTIONED_IN]-(other)
RETURN c, other  // Ce n'est PAS une relation sémantique !
```

**Pourquoi c'est dangereux :** Deux concepts mentionnés dans le même contexte ne partagent pas nécessairement de lien causal ou sémantique. Ils sont juste co-localisés dans le texte.

### ❌ Anti-pattern 2 : Confondre centralité et importance

```
// MAUVAIS
"Ce concept a 500 MENTIONED_IN → il est important"
```

**Pourquoi c'est dangereux :** Un concept très mentionné peut être :
- Un terme générique (ex: "système", "données")
- Un artefact de vocabulaire du corpus
- Non-central pour le raisonnement

**Correction :** Utiliser "corpus prominence", pas "importance".

### ❌ Anti-pattern 3 : Utiliser navigation pour le ranking sémantique

```python
# MAUVAIS
def rank_concepts(query):
    # Utilise MENTIONED_IN count pour scorer
    return sorted(concepts, key=lambda c: c.mention_count)
```

**Pourquoi c'est dangereux :** Le ranking sémantique doit utiliser uniquement les relations sémantiques et les embeddings, pas la fréquence de mention.

### ✅ Usages corrects de la navigation layer

| Usage | Autorisé | Exemple |
|-------|----------|---------|
| Explorer voisins contextuels | ✅ | "Quels concepts apparaissent dans ce document ?" |
| Router une recherche | ✅ | "Chercher dans les documents où X est mentionné" |
| Afficher en UI | ✅ | Liens pointillés pour exploration |
| Inférer des relations | ❌ | - |
| Calculer importance | ❌ | - |
| Alimenter RAG reasoning | ❌ | - |

---

## Non-Promotion Clause (Layer Integrity)

**Principe fondamental :** Aucun edge de la Navigation Layer ne peut être "promu" vers la Semantic Layer.

```
FORBIDDEN:
Navigation edge → Semantic relation (automatic promotion)

REQUIRED for any promotion:
1. Explicit extraction step (LLM-based with evidence)
2. Evidence requirement (source_text, confidence)
3. Pass through Pass 2 pipeline (classification, validation)
4. Human review for edge cases
```

**Pourquoi cette règle :**
Sans cette contrainte, quelqu'un pourrait :
- Prendre des co-occurrences fréquentes
- Les "promouvoir" en relations
- Recréer le problème initial (KG halluciné)

**Exception unique :**
Si une analyse statistique **suggère** une relation potentielle, elle doit :
1. Être soumise à extraction LLM avec le texte source
2. Passer par le pipeline standard (Pass 1 + Pass 2)
3. Avoir une evidence traçable

> La co-occurrence peut **suggérer** où chercher, jamais **affirmer** une relation.

---

# Schema Neo4j

## Labels

```
:CanonicalConcept
:Document
:DocumentChunk
:ContextNode (label parent)
  ├── :DocumentContext
  ├── :SectionContext
  └── :WindowContext
```

## Relations (Navigation Layer)

| Relation | Source | Target | Properties |
|----------|--------|--------|------------|
| `MENTIONED_IN` | CanonicalConcept | ContextNode | count, weight, first_seen |
| `IN_DOCUMENT` | ContextNode | Document | - |
| `CENTERED_ON` | WindowContext | DocumentChunk | - |

---

# Cypher Templates

## A) DocumentContext

Un par document :

```cypher
// Créer le DocumentContext
MERGE (d:Document {document_id:$doc_id})
MERGE (ctx:DocumentContext:ContextNode {context_id: 'doc:' + $doc_id})
SET ctx.kind = "document", ctx.tenant_id = $tenant_id
MERGE (ctx)-[:IN_DOCUMENT]->(d);
```

Lier un concept :

```cypher
// Lier concept au DocumentContext
MATCH (c:CanonicalConcept {canonical_id:$cc_id})
MATCH (ctx:DocumentContext:ContextNode {context_id: 'doc:' + $doc_id})
MERGE (c)-[r:MENTIONED_IN]->(ctx)
ON CREATE SET r.count = $count, r.first_seen = datetime()
ON MATCH  SET r.count = r.count + $count;
```

## B) SectionContext

Un par (document_id + section_path_normalized) :

```cypher
// Créer le SectionContext
MERGE (ctx:SectionContext:ContextNode {context_id: 'sec:' + $doc_id + ':' + $section_hash})
SET ctx.kind = "section",
    ctx.section_path = $section_path,
    ctx.doc_id = $doc_id,
    ctx.tenant_id = $tenant_id
WITH ctx
MATCH (d:Document {document_id:$doc_id})
MERGE (ctx)-[:IN_DOCUMENT]->(d);
```

## C) WindowContext

Un par chunk_id :

```cypher
// Créer le WindowContext
MERGE (ctx:WindowContext:ContextNode {context_id: 'win:' + $chunk_id})
SET ctx.kind = "window",
    ctx.doc_id = $doc_id,
    ctx.center_chunk_id = $chunk_id,
    ctx.tenant_id = $tenant_id
WITH ctx
MATCH (ch:DocumentChunk {chunk_id:$chunk_id})
MERGE (ctx)-[:CENTERED_ON]->(ch);
```

---

# Règles Anti-Mélange

## A) Conventions de type (non ambiguës)

* **Aucun edge navigation** ne doit avoir un nom sémantique
* **Aucun edge sémantique** ne doit pointer vers ContextNode

## B) Graph Lint (validation)

Commande `knowbase validate-graph` qui exécute ces requêtes et **FAIL** si résultat non vide.

### 1) Interdire edges navigation Concept→Concept

```cypher
// DOIT retourner 0 résultats
MATCH (a:CanonicalConcept)-[r:CO_OCCURS|CO_OCCURS_IN_CORPUS|CO_OCCURS_IN_DOCUMENT]->(b:CanonicalConcept)
RETURN a.canonical_id, type(r), b.canonical_id
LIMIT 10;
```

### 2) Interdire prédicats sémantiques vers ContextNode

```cypher
// DOIT retourner 0 résultats
MATCH (:CanonicalConcept)-[r:REQUIRES|ENABLES|PREVENTS|CAUSES|APPLIES_TO|DEPENDS_ON|PART_OF|MITIGATES|CONFLICTS_WITH|DEFINES|EXAMPLE_OF|GOVERNED_BY]->(ctx:ContextNode)
RETURN type(r), ctx.context_id
LIMIT 10;
```

### 3) Whitelist RAG (code)

```python
# Dans le code RAG - JAMAIS ajouter MENTIONED_IN / IN_DOCUMENT
SEMANTIC_RELATION_TYPES = {
    "REQUIRES", "ENABLES", "PREVENTS", "CAUSES",
    "APPLIES_TO", "DEPENDS_ON", "PART_OF", "MITIGATES",
    "CONFLICTS_WITH", "DEFINES", "EXAMPLE_OF", "GOVERNED_BY"
}
```

## C) Séparation API

Deux endpoints distincts :

* `/graph/semantic/...` : n'utilise que relations sémantiques
* `/graph/navigation/...` : n'utilise que navigation layer

---

# Plan d'Implémentation

| Phase | Tâche | Priorité | Status |
|-------|-------|----------|--------|
| 1 | Créer `ContextNode` model + writer `navigation_layer_builder.py` | P0 | ✅ |
| 2 | Implémenter `DocumentContext` | P0 | ✅ |
| 3 | Implémenter `SectionContext` | P1 | ✅ |
| 4 | Implémenter `WindowContext` (optionnel, désactivé par défaut) | P2 | ✅ |
| 5 | Mettre budgets top-N par concept au build time | P1 | ✅ |
| 6 | Ajouter le "graph lint" (4 règles) + endpoint `/navigation/validate` | P0 | ✅ |
| 7 | API endpoints `/navigation/*` | P1 | ✅ |
| 8 | Vérifier RAG : whitelist stricte relations sémantiques | P0 | ✅ |
| 9 | Intégration pipeline OSMOSE (`build_for_document()`) | P0 | ✅ |

**Note (Janvier 2026):** ADR entièrement implémenté. La Navigation Layer est opérationnelle et intégrée au pipeline d'ingestion. WindowContext désactivé par défaut (feature flag) conformément aux contraintes de cardinalité.

---

# Rappel Philosophique

> La navigation layer **n'est pas là pour "raisonner"**.
> Elle est là pour :
> * éviter les silos,
> * permettre exploration,
> * router la recherche,
> * donner de la mémoire corpus.
>
> C'est la différence entre **un cerveau** et **une base de faits**.

---

# Extensions Futures (non implémentées)

* Formule PMI normalisée pour `weight`
* Budgets top-K dynamiques
* Version "WindowContext-first" pour améliorer pertinence
* Couche émergente (Layer C) pour relations statistiques

---

*Spécification: ChatGPT*
*Documentation: Claude Code*
*Date: 2026-01-01*
