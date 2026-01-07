# ADR: Architecture Graph-First pour OSMOSE

**Statut**: DRAFT - En discussion
**Date**: 2026-01-06
**Auteurs**: Claude Code + ChatGPT (collaboration)
**Contexte**: Résolution du "Semantic Anchoring Bug" et pivot architectural

---

## 1. Contexte et Problème

### 1.1 Le Bug qui a tout déclenché

Question posée : *"Quel est le processus de transformation d'une proposition commerciale en contrat exécutable ?"*

**Attendu** : Concepts `Solution Quotation Management` ↔ `Service Contract Execution`
**Obtenu** : Concepts `Digital Transformation`, `AI-assisted Cloud Transformation`

**Cause racine** : Le mot "transformation" dans la question a biaisé la recherche vectorielle vers des concepts sémantiquement proches du mot, pas du sens.

### 1.2 Architecture Actuelle (Retrieval-First)

```
Question → Embedding → Qdrant (chunks) → Top-K → Reranking
                                              ↓
                                    PUIS: Graph Context (enrichissement)
                                              ↓
                                    → Synthèse LLM
```

**Problèmes identifiés** :
- Le KG est appelé APRÈS la recherche vectorielle
- 1-hop neighbors only (pas de pathfinding)
- Relations sémantiques = 1036 pour 4285 concepts (ratio 0.24 = trop faible)
- Pas de propagation du contexte document vers les chunks

### 1.3 Objectif du Pivot

Passer de **"retrieval-first enriched by KG"** à **"graph-first validated by evidence"**.

---

## 2. Décision Architecturale

### 2.1 Principe Non-Négociable

> **Le KG devient le routeur, Qdrant devient la source de preuves.**

```
Question → Concept Seeds → Graph Paths → Evidence Plan → Qdrant (filtrée) → Synthèse
```

### 2.2 Trois Modes de Réponse (Dégradation Gracieuse)

| Mode | Condition | Audit |
|------|-----------|-------|
| **Reasoned** | Chemin sémantique trouvé dans KG | Chemin + preuves par arête |
| **Anchored** | Pas de chemin, mais ancrage structurel (Topics/COVERS) | Scope + citations |
| **Text-only** | Rien dans le KG | Citations + mention "pas de support KG" |

Même en Text-only, le graphe est interrogé en premier.

---

## 3. Modèle de Données Cible

### 3.1 Ce Qui Existe Déjà

| Composant | État | Usage Actuel |
|-----------|------|--------------|
| `CanonicalConcept` | ✅ Existe | Nœud principal |
| `ContextNode` (Document/Section) | ✅ Existe | Navigation layer |
| `MENTIONED_IN` | ✅ Existe (~10,723 relations) | **Non utilisé dans RAG** |
| `chunk_ids[]` sur concepts | ✅ Existe | Propriété, pas relation |
| Relations sémantiques | ✅ Existe (~1,036) | Whitelist dans RAG |
| `evidence_ids[]` sur relations | ❌ N'existe pas | - |
| `Topic` node | ❌ N'existe pas | - |
| `COVERS` relation | ❌ N'existe pas | - |

### 3.2 Couche Evidence Graph (À Compléter)

On garde le modèle actuel mais on l'enrichit :

```cypher
// Déjà existant (UTILISER dans RAG!)
(CanonicalConcept)-[:MENTIONED_IN {salience, positions}]->(ContextNode)
(ContextNode:SectionContext)-[:IN_DOC]->(ContextNode:DocumentContext)

// À ajouter: évidence sur les relations
(Concept)-[r:REQUIRES|ENABLES|...]->(Concept)
// r.evidence_ids = ["ctx:sec:xxx:yyy", "ctx:sec:xxx:zzz"]  // Pointe vers SectionContext
```

**Décision** : On ne crée PAS de node `Chunk` dans Neo4j. On utilise :
- `SectionContext` comme granularité de preuve
- `chunk_ids[]` comme propriété pour le pont vers Qdrant

### 3.3 Couche Structural Scope (À Créer)

Option A - Topic comme node séparé :
```cypher
(:Topic {topic_id, name, tenant_id})
(Document)-[:HAS_TOPIC {salience}]->(Topic)
(Topic)-[:COVERS {confidence}]->(Concept)
```

Option B - Topic comme CanonicalConcept type TOPIC :
```cypher
(:CanonicalConcept {concept_type: "TOPIC"})
(Document)-[:HAS_TOPIC]->(CanonicalConcept:TOPIC)
```

**Recommandation** : Option B (réutilise l'existant, moins de refacto)

---

## 4. Pipeline d'Ingestion Cible (4 Passes)

> **Clarification 2026-01-06** : La distinction scope vs preuve est FONDAMENTALE.
> Topic/COVERS = périmètre documentaire (scope), JAMAIS lien conceptuel.
> Seul Pass 3 crée des relations sémantiques prouvées.

### Pass 1 - Extraction Concepts (Existant, modifié)

- Extraction des ProtoConcepts par segment
- Consolidation en CanonicalConcepts
- Création `MENTIONED_IN` avec salience par section
- **CHANGEMENT** : Pas de relations sémantiques à ce stade

### Pass 2a - Structural Topics / COVERS (NOUVEAU)

> **Principe clé** : Topic/COVERS répond à "De quoi parle ce document/section ?"
> Ce n'est JAMAIS un lien causal, une relation conceptuelle, ou un chemin de raisonnement.
> C'est un **filtre de périmètre**, pas une preuve.

**Identification des Topics** (ordre de priorité) :
1. **Structure documentaire** (H1/H2, TOC, headers) - source primaire
2. **LLM léger** sur structure (titres + intro) → 5-15 Topics max
3. **Match/Create CanonicalConcept** avec `concept_type: "TOPIC"`

**Création des relations** :
- `(Document)-[:HAS_TOPIC {salience}]->(Topic)`
- `(Topic)-[:COVERS {confidence}]->(Concept)`

**Règles COVERS** (déterministes, PAS de LLM) :
- Concept `MENTIONED_IN` une section rattachée au Topic
- ET salience suffisante (TF-IDF doc-level, spread)
- ET pas un concept générique (stop-concept)

> ⚠️ **PIÈGE À ÉVITER** : "Si A et B sont couverts par le même Topic, ils sont liés" = FAUX
> Ils sont dans le même **périmètre documentaire**, aucun lien sémantique n'est affirmé.

### Pass 2b - Classification Fine (Existant)

- `CLASSIFY_FINE` : Affinage types concepts via LLM
- Enrichissements non causaux
- **Rien ici n'est utilisé comme preuve ou pour justifier une réponse**

### Pass 3 - Consolidation Sémantique (NOUVEAU)

> **Principe clé** : C'est le SEUL endroit où la vérité sémantique est construite.
> Le LLM peut proposer/reformuler, mais la relation DOIT être ancrée dans une preuve.

**Candidate Generation** :
- Paires de concepts dans même Topic/Section
- Co-présence récurrente (≥2 sections différentes)

**Verification LLM (extractive-only)** :
```python
{
    "relation_type": "REQUIRES",
    "direction": "A→B",
    "evidence_span": "quote exacte courte",  # OBLIGATOIRE
    "evidence_locator": "ctx:sec:doc123:hash456",
    "confidence": 0.85
}
# OU: ABSTAIN si pas de preuve textuelle
```

**Multi-evidence policy** :
- 1 preuve suffit si source forte (glossaire, norme, "shall")
- Sinon ≥2 preuves indépendantes

> ⚠️ **INVARIANT** : Pass 3 ne dépend JAMAIS du LLM seul.
> Sans ancrage preuve, la relation reste décoration, pas connaissance.

### 4.0 Nuances Importantes (Garde-fous Cognitifs)

| Nuance | Description |
|--------|-------------|
| **Topic = précondition** | Un concept hors topic est non défendable. MAIS être dans le bon topic n'autorise rien. |
| **Anchored ≠ Reasoned** | Mode Anchored = réduction espace de recherche, pas moteur logique. Il empêche les sauts hors sujet. |
| **LLM = assistant** | Le LLM nomme/normalise les Topics, il n'invente pas. Pour COVERS, le LLM n'a rien à faire. |

### 4.1 Ce Qu'on Garde de l'Existant

- `osmose_agentique.py` : Orchestration générale
- `DocContextExtractor` : Extraction markers/scope
- `CanonicalConcept` merging logic
- `MENTIONED_IN` création

### 4.2 Ce Qu'on Modifie

- Déplacer création relations sémantiques de Pass 1 vers Pass 3
- Ajouter `evidence_ids[]` sur les relations
- Créer Pass 2 pour Topics/COVERS

---

## 5. Runtime Cible (Graph-First)

### 5.1 Clarification GDS (2026-01-06)

> **GDS Community Edition EST disponible** avec Neo4j Community

**Limites GDS Community** :
- Concurrency : max 4 CPU cores
- Model catalog : limité à 3 modèles
- Catalog operations : certaines limitations de gestion

**Impact sur notre cible** : **AUCUN** pour le graph-first runtime :
- 4 cores suffisent pour pathfinding sur ~4K concepts
- Pas besoin de ML/embeddings graph (on a Qdrant)
- Pas besoin de 50 projections simultanées

**Décision** : Utiliser GDS pour pathfinding/scoring sur SemanticGraph VALIDATED.

**Stratégie pathfinding** :
1. **GDS Yen's k-shortest paths** : Pour Top-K chemins auditables (k=5 ou k=10)
   - Note : Dijkstra = 1 seul chemin, Yen = k meilleurs chemins
   - Pour k=1, Yen se comporte comme Dijkstra
2. **Cypher natif** : Jointures, evidence plan, MENTIONED_IN (pas pathfinding)
3. **NetworkX** : Réservé au batch/offline (InferenceEngine)

### 5.2 Pipeline Runtime

```
┌─────────────────────────────────────────────────────────────────┐
│                    GRAPH-FIRST RUNTIME                          │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  Question                                                       │
│      │                                                          │
│      ▼                                                          │
│  [Étape 1] extract_concepts_from_query_v2()                    │
│            → seed_concepts[] (Top 10-20)                       │
│                                                                 │
│      │                                                          │
│      ▼                                                          │
│  [Étape 2] GRAPH PATH SEARCH (GDS Yen k-shortest)              │
│            - Entre paires de seeds (top pairs)                 │
│            - Vers targets implicites (si question "processus") │
│            - Scoring : confidence × evidence_coverage          │
│            → candidate_paths[] (Top 5-10)                      │
│                                                                 │
│      │                                                          │
│      ├── Si paths trouvés → MODE REASONED                      │
│      │       │                                                  │
│      │       ▼                                                  │
│      │   [Étape 3a] EVIDENCE COLLECTION                        │
│      │              - Récupérer evidence_ids des arêtes        │
│      │              - Compléter via MENTIONED_IN               │
│      │              → evidence_plan                            │
│      │                                                          │
│      ├── Si pas de paths → MODE ANCHORED                       │
│      │       │                                                  │
│      │       ▼                                                  │
│      │   [Étape 3b] STRUCTURAL ROUTING                         │
│      │              - Router via HAS_TOPIC/COVERS              │
│      │              - Récupérer docs via MENTIONED_IN          │
│      │              → structural_context                       │
│      │                                                          │
│      └── Si rien → MODE TEXT-ONLY                              │
│              │                                                  │
│              ▼                                                  │
│          [Étape 3c] Qdrant classique (fallback)               │
│                                                                 │
│      │                                                          │
│      ▼                                                          │
│  [Étape 4] QDRANT SEARCH (Filtrée)                             │
│            - Filtrer par doc_ids/section_ids du plan           │
│            - Ou concept_ids du chemin                          │
│            → evidence_chunks[]                                  │
│                                                                 │
│      │                                                          │
│      ▼                                                          │
│  [Étape 5] SYNTHÈSE LLM                                        │
│            - Chemin (raisonnement)                             │
│            - Preuves (passages)                                │
│            → Réponse + Audit Trail                             │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

### 5.3 Requêtes Cypher Clés

**Path Search (2-3 hops max)** :
```cypher
MATCH (start:CanonicalConcept {canonical_name: $seed1, tenant_id: $tenant})
MATCH (end:CanonicalConcept {canonical_name: $seed2, tenant_id: $tenant})
MATCH path = shortestPath((start)-[r:REQUIRES|ENABLES|PART_OF|GOVERNED_BY*1..3]-(end))
WHERE ALL(rel IN relationships(path) WHERE rel.confidence >= $min_confidence)
RETURN path,
       reduce(conf = 1.0, rel IN relationships(path) | conf * rel.confidence) AS path_confidence
ORDER BY path_confidence DESC
LIMIT 5
```

**Evidence Collection** :
```cypher
UNWIND $path_nodes AS concept_name
MATCH (c:CanonicalConcept {canonical_name: concept_name, tenant_id: $tenant})
MATCH (c)-[m:MENTIONED_IN]->(ctx:SectionContext)
RETURN concept_name, ctx.context_id, ctx.section_path, m.salience
ORDER BY m.salience DESC
```

---

## 6. Tests de Validation (North Star)

| Test | Description | Critère de Succès |
|------|-------------|-------------------|
| **Ambiguous Word** | Question "transformation" → bons concepts | Trouve "Quotation→Contract", pas "Digital Transformation" |
| **Path Recovery** | Question sur relation connue → retrouve le chemin | Chemin identique à celui dans Neo4j |
| **Evidence Alignment** | Chaque arête a une preuve | 100% des arêtes REASONED ont evidence_ids |
| **No Spurious Edge** | Arêtes sans preuve = 0 en mode REASONED | Ratio < 1% |

---

## 7. Plan d'Implémentation (Phases)

> **Approche Clean Slate** : Les données actuelles sont jetables (tests).
> Pas de migration, on corrige le code puis purge + réimport.

### Phase 0 - Pont SectionContext → Qdrant (Prioritaire)

1. Modifier `hybrid_anchor_chunker.py` : ajouter `context_id` + `section_path`
2. Vérifier cohérence hash avec `navigation_layer_builder.py`
3. Créer payload index Qdrant sur `context_id`
4. Purger données de test + réimporter quelques docs pour validation

**Livrable** : Chunks Qdrant filtrable par `context_id` Neo4j

### Phase A - Foundation

1. Activer MENTIONED_IN dans le RAG (supprimer de l'exclusion whitelist)
2. Ajouter `evidence_ids[]` au schéma des relations Neo4j
3. Installer GDS Community si pas déjà fait
4. Créer projection GDS "SemanticGraph" pour pathfinding

**Livrable** : Infrastructure prête pour graph-first

### Phase B - Pass 2a/2b/3 (Clarification 2026-01-06)

> **Rappel** : Topic/COVERS = scope (filtre), PAS lien conceptuel.
> Pass 3 = seule source de relations sémantiques prouvées.

**B.1 - Pass 2a : Structural Topics / COVERS** ✅ IMPLÉMENTÉ (2026-01-06)

> **Module** : `src/knowbase/relations/structural_topic_extractor.py`
> **Intégration** : `pass2_orchestrator.py` → phase `STRUCTURAL_TOPICS`

1. ✅ Extraire Topics depuis structure doc (H1/H2, numérotation)
   - `StructuralTopicExtractor._extract_headers()` parse Markdown H1/H2 et numérotation
   - Normalisation titres pour matching cross-document
2. ✅ Créer `CanonicalConcept` avec `concept_type: "TOPIC"`
   - `TopicNeo4jWriter._upsert_topic_concept()` via MERGE
3. ✅ Créer `HAS_TOPIC` (Document → Topic)
   - `TopicNeo4jWriter._create_has_topic_relation()`
4. ✅ Créer `COVERS` (Topic → Concept) via règles déterministes :
   - `CoversBuilder.build_covers_for_document()`
   - Critères : `MENTIONED_IN` + salience ≥ 0.3
   - Exclusion stop-concepts (document, section, introduction, etc.)

**B.2 - Pass 2b : Classification Fine** (existant, réorganisé)
- `CLASSIFY_FINE` reste tel quel
- Aucune création de relation sémantique

**B.3 - Pass 3 : Consolidation Sémantique** ✅ IMPLÉMENTÉ (2026-01-06)

> **Module** : `src/knowbase/relations/semantic_consolidation_pass3.py`
> **Intégration** : `pass2_orchestrator.py` → phase `SEMANTIC_CONSOLIDATION`

SEULE source de relations sémantiques prouvées.

1. ✅ Candidate generation : co-présence Topic/Section, récurrence ≥2 sections
   - `CandidateGenerator.generate_candidates()` via requête MENTIONED_IN
   - Critères : MIN_CO_OCCURRENCES=2, MIN_CANDIDATE_SCORE=0.3
2. ✅ Verification LLM extractive : quote obligatoire ou ABSTAIN
   - `ExtractiveVerifier.verify_candidate()` avec prompt strict
   - La quote doit être vérifiable dans le texte source (matching normalisé)
   - ABSTAIN si aucune preuve explicite trouvée
3. ✅ Règle : `evidence_context_ids[]` non vide pour TOUTE relation
   - `Pass3SemanticWriter.write_verified_relation()` refuse écriture sans evidence
   - Chaque relation a `evidence_quote` + `evidence_context_ids`
4. ✅ Multi-evidence policy : relations marquées `multi_evidence=true` si mise à jour

**Livrable** : Relations prouvées avec traçabilité complète

### Phase C - Runtime Graph-First ✅ IMPLÉMENTÉ (2026-01-07)

> **Module** : `src/knowbase/api/services/graph_first_search.py`
> **Intégration** : `search.py` → paramètre `use_graph_first=True`

1. ✅ Créé `GraphFirstSearchService` avec 3 modes (REASONED/ANCHORED/TEXT_ONLY)
   - `build_search_plan()` détermine le mode selon les paths trouvés
   - `SearchMode.REASONED` : Paths sémantiques trouvés avec evidence
   - `SearchMode.ANCHORED` : Routing structural via HAS_TOPIC/COVERS
   - `SearchMode.TEXT_ONLY` : Fallback Qdrant classique
2. ✅ Pathfinding GDS Yen k-shortest paths
   - `_gds_yen_paths()` utilise `gds.shortestPath.yens.stream`
   - `_ensure_gds_projection()` crée la projection SemanticGraph
   - Fallback sur `allShortestPaths` Cypher si GDS indisponible
3. ✅ Intégration dans `search.py`
   - Nouveau paramètre `use_graph_first: bool = False`
   - Réponse inclut `graph_first_plan` avec mode et metadata
4. ✅ Filtrage Qdrant par `context_id`
   - `search_qdrant_filtered()` filtre par context_ids du plan
   - Utilise le pont Phase 0 (`make_context_id` dans hybrid_anchor_chunker)

**Livrable** : Runtime graph-first opérationnel

### Phase D - Validation ✅ IMPLÉMENTÉ (2026-01-07)

> **Module tests** : `tests/graph_first/`

1. ✅ Tests North Star (`test_north_star.py`)
   - `TestNorthStarAmbiguousWord` : Question ambiguë → bons concepts
   - `TestNorthStarPathRecovery` : Chemin identique au KG
   - `TestSearchModeSelection` : Sélection REASONED/ANCHORED/TEXT_ONLY

2. ✅ Tests Evidence Alignment (`test_evidence_alignment.py`)
   - `TestEvidenceAlignment` : 100% des paths ont evidence_context_ids
   - `TestNoSpuriousEdge` : Ratio arêtes sans preuve < 1%
   - `TestEvidenceCollectionIntegrity` : Via MENTIONED_IN

3. ✅ Tests Performance (`test_performance.py`)
   - Target: < 500ms total (sans synthèse LLM)
   - `TestPerformanceBenchmarks` : Seuils par composant
   - `TestScalabilityBenchmarks` : Jusqu'à 10 concepts
   - `TestPerformanceIntegration` : End-to-end réel

4. ⏳ Import corpus complet + validation qualité
   - À faire après purge des bases par l'utilisateur
   - Réimporter avec Pass 2a + Pass 3 complets

**Seuils de performance configurés** :
```python
PERFORMANCE_THRESHOLDS = {
    "build_search_plan_ms": 300,
    "total_graph_first_ms": 500,
}
```

**Exécution tests** :
```bash
# Tests unitaires (rapides)
pytest tests/graph_first/ -v -m "not integration"

# Tests intégration (nécessite Neo4j)
pytest tests/graph_first/ -v -m integration
```

---

## 8. Chantier Prioritaire : Pont SectionContext → Qdrant

### 8.1 Diagnostic (2026-01-06)

**État actuel du code** : Le champ `context_id` n'est pas injecté dans le payload Qdrant.

| Composant | Code Actuel | Code Cible |
|-----------|-------------|------------|
| `document_id` | ✅ Présent | ✅ Garder |
| `segment_id` | ⚠️ Format incompatible | Supprimer ou aligner |
| `context_id` | ❌ Absent | ✅ Ajouter |
| `section_path` | ❌ Absent | ✅ Ajouter |

### 8.2 Solution : Corriger le Code (Clean Slate)

> **Note** : Les données actuelles (Neo4j + Qdrant) sont des données de test jetables.
> Pas de migration nécessaire. On corrige le code, on purge, on réimporte.

**Modification dans `HybridAnchorChunker.chunk_document()`** :

```python
# Payload chunk cible
{
    "document_id": document_id,
    "context_id": f"sec:{document_id}:{section_hash}",  # Pointe vers SectionContext Neo4j
    "section_path": section_path,                        # Ex: "1.2 Security Architecture"
    "char_start": char_start,
    "char_end": char_end,
    "tenant_id": tenant_id,
    # ... autres champs existants
}
```

**Points d'injection** :

| Fichier | Modification |
|---------|--------------|
| `hybrid_anchor_chunker.py` | Ajouter `context_id` + `section_path` au payload |
| `navigation_layer_builder.py` | S'assurer que le hash est identique |
| Script setup Qdrant | Créer payload index sur `context_id` |

**Workflow ingestion corrigé** :

```
Document → Segmentation → SectionContext créés dans Neo4j (context_id = sec:doc:hash)
                       ↘ Chunks créés dans Qdrant (même context_id)
```

### 8.3 Spécification `context_id` (Format Unique)

**Format canonique** : `sec:{document_id}:{section_hash}`

Exemples :
- `sec:Joule_L0_f8e565db:5a7b6bd7e075`
- `sec:SAP_BTP_Security:a1b2c3d4e5f6`

**Helper unique** (à utiliser partout) :

```python
import hashlib

def make_context_id(document_id: str, section_path: str) -> str:
    """
    Génère un context_id unique et cohérent.

    IMPORTANT: Cette fonction DOIT être appelée des deux côtés :
    - NavigationLayerBuilder (Neo4j)
    - HybridAnchorChunker (Qdrant)

    Args:
        document_id: ID du document (ex: "Joule_L0_f8e565db")
        section_path: Chemin de section normalisé (ex: "1.2 Security")

    Returns:
        context_id au format "sec:{doc_id}:{hash6}"
    """
    # Normalisation : lowercase, strip, espaces → underscores
    normalized_path = section_path.lower().strip().replace(" ", "_")

    # Hash court (6 chars) pour unicité
    hash_input = f"{document_id}:{normalized_path}"
    section_hash = hashlib.sha256(hash_input.encode()).hexdigest()[:12]

    return f"sec:{document_id}:{section_hash}"
```

**Règle** : Ne JAMAIS construire un `context_id` autrement qu'avec ce helper.

### 8.4 Déploiement

1. Créer le helper `make_context_id()` dans un module partagé
2. Modifier `navigation_layer_builder.py` pour utiliser ce helper
3. Modifier `hybrid_anchor_chunker.py` pour utiliser ce helper
4. Créer payload index Qdrant sur `context_id`
5. Purger données de test : `./kw.ps1 clean`
6. Réimporter les documents avec le code corrigé
7. Valider : vérifier que `context_id` Qdrant = `context_id` Neo4j

### 8.5 Impact sur le Runtime Graph-First

Avec le pont câblé :
- Filtrage direct Qdrant : `filter: {"must": [{"key": "context_id", "match": {"any": $evidence_context_ids}}]}`
- Performance : ~10ms (vs post-filtrage inefficace)

---

## 8bis. Scoring de Chemin (Audit-First)

Le meilleur chemin n'est pas forcément le plus court ni le plus confiant :
c'est celui qui a les **preuves les plus propres**.

### Formule de Score

```python
def score_path(path: Path) -> float:
    """
    Score un chemin pour l'audit.

    Critères (par ordre de priorité) :
    1. Evidence coverage : chaque edge a-t-elle des preuves ?
    2. Confidence agrégée des edges
    3. Pénalité longueur (moins de hops = mieux)
    4. Pénalité "generic hub" (nœuds qui relient tout)
    """
    edges = path.relationships

    # 1. Evidence coverage (0-1) : % d'edges avec evidence_ids non vides
    evidence_coverage = sum(1 for e in edges if e.evidence_ids) / len(edges)

    # 2. Confidence agrégée (produit des confidences)
    confidence_product = reduce(lambda a, b: a * b, [e.confidence for e in edges], 1.0)

    # 3. Pénalité longueur : -0.1 par hop au-delà de 2
    length_penalty = max(0, len(edges) - 2) * 0.1

    # 4. Pénalité hub : -0.05 par nœud avec degree > 20
    hub_penalty = sum(0.05 for n in path.nodes if n.degree > 20)

    # Score final (pondéré)
    score = (
        0.4 * evidence_coverage +
        0.3 * confidence_product +
        0.2 * (1 - length_penalty) +
        0.1 * (1 - hub_penalty)
    )

    return max(0, min(1, score))
```

### Règle de Sélection

- **Mode Reasoned** : Ne retenir que les chemins avec `evidence_coverage >= 0.8`
- **Mode Anchored** : Chemins avec `evidence_coverage < 0.8` mais ancrage structurel
- **Top-K** : Retourner les k meilleurs chemins par score (k=5 par défaut)

### Invariant Non-Négociable (Reasoned)

> **Un chemin purement structurel ou composé uniquement de relations non prouvées
> ne peut JAMAIS déclencher le Mode Reasoned.**

Cet invariant garantit que :
- Le Mode Reasoned = toujours au moins une arête sémantique avec `evidence_ids[]`
- Pas de "court-circuit" possible lors de futurs refactors
- L'audit est toujours ancré dans des preuves textuelles

---

## 9. Invariants Fondamentaux (Garde-fous)

Ces 3 invariants doivent être respectés dans tout le code pour éviter toute régression :

| # | Invariant | Conséquence si violé |
|---|-----------|----------------------|
| **I1** | Le graphe est TOUJOURS interrogé AVANT Qdrant | Retour au biais retrieval-first |
| **I2** | Mode Reasoned = relations avec preuves (`evidence_ids[]` non vide) | Liens artificiels, audit impossible |
| **I3** | SectionContext est la seule granularité de vérité sémantique | Perte de contexte, chunk-level thinking |

---

## 10. Décisions Prises

### D1: Représentation des Passages

**Décision** : `SectionContext` comme granularité de preuve + `context_id` dans payload Qdrant

- Pas de node `Chunk` dans Neo4j (évite duplication)
- `SectionContext` = granularité pour `evidence_ids[]`
- `context_id` dans Qdrant = pont vers Neo4j

### D2: Relations Existantes

**Décision** : Approche Clean Slate

- Les données actuelles sont des tests jetables
- Purge complète puis réimport avec le code corrigé
- Pas de migration, pas de marquage "unverified"
- Nouvelles relations créées uniquement via Pass 3 (avec preuves)

### D3: Pathfinding

**Décision** : GDS Community (Yen k-shortest paths)

- GDS Community suffisant (limites OK pour notre échelle)
- `gds.shortestPath.yens` pour Top-K chemins auditables (k=5)
- Dijkstra uniquement si k=1 (mode cheap)
- Cypher natif pour jointures/evidence plan (pas pathfinding)
- NetworkX réservé au batch/offline

---

## 11. Annexes

### A. Whitelist Relations Sémantiques Actuelle

```python
SEMANTIC_RELATION_TYPES = frozenset({
    "REQUIRES", "ENABLES", "PREVENTS", "CAUSES",
    "APPLIES_TO", "DEPENDS_ON", "PART_OF", "MITIGATES",
    "CONFLICTS_WITH", "DEFINES", "EXAMPLE_OF", "GOVERNED_BY",
})
```

### B. Métriques KG Actuelles

- CanonicalConcepts: ~4,285
- Relations sémantiques: ~1,036 (ratio 0.24)
- MENTIONED_IN: ~10,723
- Documents: ~150

### C. Références

- `src/knowbase/api/services/search.py` - Runtime actuel
- `src/knowbase/api/services/graph_guided_search.py` - Service KG actuel
- `src/knowbase/navigation/types.py` - Modèle ContextNode
- `doc/ongoing/ADR_NAVIGATION_LAYER.md` - ADR Navigation Layer existant
