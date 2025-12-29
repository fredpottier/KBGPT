# ADR: Hybrid Anchor Model Architecture

**Date**: 2024-12-29
**Statut**: Accepté
**Auteurs**: Architecture Review (Claude + ChatGPT consensus)
**Impact**: Majeur - Refonte du pipeline d'ingestion OSMOSE

---

## Contexte et Problème

### Situation actuelle

Le pipeline OSMOSE Agentique actuel souffre d'un problème de performance critique qui rend le système non viable pour un usage production :

| Métrique | Valeur actuelle | Problème |
|----------|-----------------|----------|
| Temps par document | 35+ minutes | Inacceptable |
| Corpus 70 documents | 40+ heures | Non viable |
| Concept-focused chunks | 11,713 / doc | Explosion combinatoire |
| Chunks génériques | 84 / doc | Ratio 140:1 |

### Cause racine identifiée

Le modèle actuel repose sur les **concept-focused chunks** :
- Pour chaque concept extrait, le LLM génère des reformulations contextuelles
- Ces reformulations sont vectorisées et stockées comme unités indépendantes
- Résultat : **duplication sémantique massive** et **explosion combinatoire**

Ce n'est pas un problème de tuning ou de parallélisation. C'est un **défaut architectural fondamental**.

### Décomposition du temps (document test : 172K chars, ~40 pages)

| Phase | Durée | % | Cause |
|-------|-------|---|-------|
| EXTRACT | 5.7 min | 17% | 47 segments × appels LLM |
| CLASSIFY | 15 min | 45% | 527 concepts × 17 batches séquentiels |
| GATE_CHECK | 10 min | 30% | 2,297 contexts × scoring embeddings |
| CHUNKING | 10+ min | - | 11,713 chunks à vectoriser |
| **TOTAL** | **35+ min** | | |

---

## Décision : Hybrid Anchor Model

### Principe fondamental

> **Un concept ne produit pas de contenu. Un concept référence du contenu existant.**

Dans l'architecture cible :
- Le **texte source reste la seule source primaire**
- Les concepts sont des **clés sémantiques structurantes**
- La relation concept ↔ texte est **explicite, traçable et justifiée** via des **Anchors**

### Définition d'un Anchor

Un **Anchor** est un lien explicite entre :
- Un concept (ProtoConcept ou CanonicalConcept)
- Un passage précis du texte source (chunk)
- Un rôle sémantique identifié (definition, procedure, requirement, example, etc.)

```json
{
  "concept_id": "cc_dpia_001",
  "chunk_id": "doc_chunk_42",
  "quote": "A DPIA shall be carried out where processing is likely to result in a high risk...",
  "role": "definition",
  "confidence": 0.92,
  "char_start": 1234,
  "char_end": 1456
}
```

### Conséquence majeure

**Les concept-focused chunks sont définitivement supprimés.**

Ils sont remplacés par :
- Des **chunks document-centric** (texte réel, non reformulé)
- Des **concepts reliés par anchors** (références, pas duplications)

---

## Architecture à 2 Passes

### Vue d'ensemble

```
┌─────────────────────────────────────────────────────────────────┐
│                         PASS 1 - SOCLE                          │
│              (Bloquant, ~10 min/doc, système exploitable)       │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  EXTRACT ────► GATE_CHECK ────► RELATIONS ────► CHUNK ────► ✓  │
│                                                                 │
│  Résultat : Graphe sain, recherche fonctionnelle, 0 bruit      │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼ (configurable: inline/background/scheduled)
┌─────────────────────────────────────────────────────────────────┐
│                     PASS 2 - ENRICHISSEMENT                     │
│                    (Non bloquant, optionnel SLA)                │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  CLASSIFY_FINE ────► ENRICH_RELATIONS ────► CROSS_DOC          │
│                                                                 │
│  Résultat : Classification fine, relations enrichies, corpus   │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

---

## Pass 1 : Socle de Vérité Exploitable

### Objectif

À l'issue de Pass 1 :
- Le système est **utilisable**
- Le graphe est **sain** (aucun concept sans anchor)
- La recherche est **fiable** (hybride chunks + concepts)

### Phase EXTRACT (~5-6 min)

#### Entrée
- Document segmenté (47 segments pour 40 pages)

#### Traitement
1. **Extraction LLM** : Pour chaque segment, le LLM extrait :
   - Concepts (label, type heuristique, définition courte)
   - Quote textuelle exacte justifiant le concept

2. **Fuzzy Matching** : Algorithme (rapidfuzz) localise la quote dans le segment source
   - Produit `char_start`, `char_end` exacts
   - Si similarité < 85% → anchor marqué `approximate`

3. **Création ProtoConcept** : Chaque concept est créé avec :
   - Son embedding (label + quote principale)
   - Son anchor vers le segment source

#### Sortie
- ProtoConcepts avec anchors validés
- Aucun concept sans preuve textuelle

#### Règle critique
> **Un concept sans anchor n'est pas créé.** Il est soit du bruit, soit une hypothèse non validée.

### Phase GATE_CHECK simplifiée (~2 min)

#### Changements vs actuel

| Aspect | Avant | Après |
|--------|-------|-------|
| Scoring contextuel | 2,297 contexts, 575 batches embeddings | Supprimé |
| Scoring | TF-IDF + centralité + embeddings contextuels | TF-IDF + fréquence anchors |
| Déduplication | LLM + embeddings | LLM simplifié |
| Embedding concept | Multiples par contexte | **1 seul par CanonicalConcept** |

#### Traitement
1. **Scoring simplifié** :
   - TF-IDF sur le label/définition
   - Fréquence d'apparition (nombre d'anchors)
   - Centralité basique si graphe existant

2. **Déduplication** :
   - Regroupement des ProtoConcepts similaires
   - Création CanonicalConcept avec embedding consolidé

3. **Persistance Neo4j** :
   - ProtoConcepts
   - CanonicalConcepts
   - Relations ANCHORED_IN

#### Sortie
- CanonicalConcepts avec 1 embedding chacun
- Graphe Neo4j propre

### Phase RELATIONS (~1 min)

#### Traitement
- Extraction LLM des relations entre concepts du segment
- Création RawAssertions dans Neo4j

#### Pas de changement majeur
Cette phase était déjà efficace.

### Phase CHUNK (~1 min)

#### Changements majeurs

| Aspect | Avant | Après |
|--------|-------|-------|
| Chunks génériques | 84 (512 tokens) | **170-200 (256 tokens)** |
| Concept-focused chunks | 11,713 | **0 (supprimés)** |
| Total chunks | 11,797 | **~180** |
| Batches embeddings | 2,950 | **~45** |

#### Configuration cible

```python
CHUNKING_CONFIG = {
    "chunk_size_tokens": 256,      # Réduit de 512
    "chunk_overlap_tokens": 64,    # Réduit de 128
    "embedding_model": "intfloat/multilingual-e5-large",
}
```

#### Traitement
1. **Chunking document-centric** :
   - Découpage par taille fixe (256 tokens)
   - Overlap 64 tokens
   - ~170-200 chunks pour 40 pages

2. **Embedding chunks** :
   - Vectorisation des chunks réels (pas de reformulation)

3. **Liaison anchors → chunks** :
   - Chaque anchor référence le chunk contenant sa quote
   - Mise à jour relation Neo4j : `(Concept)-[:ANCHORED_IN]->(Chunk)`
   - Enrichissement payload Qdrant : `anchored_concepts[]`

4. **Persistance Qdrant** :
   - Chunks avec embeddings
   - Payload enrichi incluant les concepts ancrés

#### Sortie
- Collection Qdrant avec chunks document-centric
- Liens bidirectionnels concept ↔ chunk

---

## Pass 2 : Enrichissement Sémantique

### Objectif

Enrichir le graphe **sans invalider Pass 1**.

### Timing configurable

```python
PASS2_MODE = "inline"      # Burst mode (GPU disponible)
           | "background"  # Job asynchrone (mode normal)
           | "scheduled"   # Batch nocturne (corpus stable)
```

### Phase CLASSIFY_FINE

#### Avant (Pass 1)
Classification heuristique basée sur :
- Patterns textuels
- Structure du document
- Verbes normatifs (must, shall, should)

#### Pass 2
Classification LLM fine-grained :
- Types précis (abstract, structural, procedural, regulatory, etc.)
- Sous-types
- Confiance affinée

### Phase ENRICH_RELATIONS

- Relations cross-segment
- Inférences (si A→B et B→C alors A→C)
- Types de relations enrichis

### Phase CROSS_DOC

- Consolidation corpus-level des CanonicalConcepts
- Centralité graphe globale
- Définitions multilingues (synthèse LLM)
- Détection de contradictions

---

## Modèle de Données

### Neo4j (Source de vérité)

```cypher
// ProtoConcept (doc-level)
(:ProtoConcept {
  id: "pc_xxx",
  label: "Data Protection Impact Assessment",
  definition: "Process required by GDPR...",
  type_heuristic: "procedural",
  embedding: [1024 floats],
  document_id: "doc_123",
  tenant_id: "default",
  created_at: datetime()
})

// CanonicalConcept (corpus-level)
(:CanonicalConcept {
  id: "cc_xxx",
  label: "Data Protection Impact Assessment",
  definition_consolidated: "...",
  type_fine: "regulatory_procedure",  // Ajouté en Pass 2
  embedding: [1024 floats],
  tenant_id: "default"
})

// DocumentChunk
(:DocumentChunk {
  id: "chunk_xxx",
  document_id: "doc_123",
  text: "A DPIA shall be carried out...",
  char_start: 1234,
  char_end: 1756,
  token_count: 256,
  tenant_id: "default"
})

// Relation ANCHORED_IN
(:ProtoConcept)-[:ANCHORED_IN {
  quote: "A DPIA shall be carried out...",
  role: "definition",
  confidence: 0.92,
  char_start: 45,
  char_end: 120,
  approximate: false
}]->(:DocumentChunk)

// Relation INSTANCE_OF
(:ProtoConcept)-[:INSTANCE_OF]->(:CanonicalConcept)
```

### Qdrant (Projection optimisée)

```json
{
  "id": "chunk_xxx",
  "vector": [1024 floats],
  "payload": {
    "document_id": "doc_123",
    "document_name": "aepd_gdpr_ai_guide.pdf",
    "text": "A DPIA shall be carried out...",
    "char_start": 1234,
    "char_end": 1756,
    "tenant_id": "default",
    "anchored_concepts": [
      {
        "concept_id": "cc_dpia_001",
        "label": "Data Protection Impact Assessment",
        "role": "definition",
        "span": [45, 120]
      }
    ]
  }
}
```

### Règle de cohérence

> **Neo4j = source de vérité**
> **Qdrant = projection optimisée pour le retrieval**

En cas de divergence, Neo4j fait foi.

---

## Recherche Hybride

### Pipeline de recherche cible

```
Query utilisateur
       │
       ├──────────────────────────────────────┐
       │                                      │
       ▼                                      ▼
┌─────────────────┐                 ┌─────────────────┐
│ Qdrant Search   │                 │ Concept Search  │
│ (chunks)        │                 │ (embeddings)    │
└────────┬────────┘                 └────────┬────────┘
         │                                   │
         │ top_k chunks                      │ top_k concepts
         │                                   │
         ▼                                   ▼
┌─────────────────────────────────────────────────────┐
│                    FUSION                           │
│  - Chunks directs                                   │
│  - Chunks via anchors des concepts pertinents       │
│  - Reranking unifié                                 │
└─────────────────────────────────────────────────────┘
         │
         ▼
┌─────────────────────────────────────────────────────┐
│                  RÉPONSE                            │
│  - Contexte : chunks pertinents                     │
│  - Justification : concepts + anchors (citations)   │
│  - Navigation : liens Knowledge Graph               │
└─────────────────────────────────────────────────────┘
```

### Avantages

1. **Précision** : Recherche sur texte réel, pas sur reformulations
2. **Explicabilité** : Chaque concept est justifié par des anchors
3. **Navigation** : Les concepts permettent d'explorer le graphe
4. **Audit** : Citations vérifiables directement

---

## Décisions Techniques Détaillées

### 1. Construction des Anchors : LLM + Fuzzy Matching

**Décision** : Le LLM fournit la quote, le code fournit les positions.

**Justification** :
- Les LLMs ne sont pas fiables pour produire des offsets exacts
- Le fuzzy matching est déterministe et auditable
- Permet de détecter les hallucinations (quote non trouvée)

**Implémentation** :
```python
def create_anchor(concept, segment_text, llm_quote):
    # Fuzzy match pour trouver la position exacte
    match = rapidfuzz.fuzz.partial_ratio(llm_quote, segment_text)

    if match.score >= 85:
        return Anchor(
            quote=segment_text[match.start:match.end],
            char_start=match.start,
            char_end=match.end,
            approximate=False
        )
    else:
        # Fallback : marquer comme approximate
        return Anchor(
            quote=llm_quote,
            approximate=True,
            warning="Quote not found with high confidence"
        )
```

### 2. Granularité du Chunking : 256 tokens

**Décision** : 256 tokens avec overlap 64 (valeur cible produit).

**Justification** :

| Granularité | Tokens | Chunks (40 pages) | Trade-off |
|-------------|--------|-------------------|-----------|
| Actuelle | 512 | 84 | Trop gros, perte précision |
| **Cible** | **256** | **~180** | **Bon équilibre** |
| Fine | 128 | ~340 | Risque fragmentation |

### 3. Classification : Hybride Pass 1 / Pass 2

**Décision** : Heuristique en Pass 1, LLM en Pass 2.

**Pass 1 - Heuristique** :
```python
def classify_heuristic(concept, context):
    # Patterns structurels
    if re.match(r'^Article \d+', concept.label):
        return "structural"

    # Verbes normatifs
    if any(v in context for v in ['shall', 'must', 'required']):
        return "regulatory"

    # Patterns procéduraux
    if any(p in concept.label.lower() for p in ['process', 'procedure', 'method']):
        return "procedural"

    return "abstract"  # Défaut
```

**Pass 2 - LLM** :
Classification fine avec sous-types, confiance, justification.

### 4. Embeddings Concepts : Distinction doc-level / corpus-level

**Décision** :
- **ProtoConcept** (doc-level) : embedding = label + quote principale du doc
- **CanonicalConcept** (corpus-level) : embedding = synthèse consolidée

**Justification** :
- Un CanonicalConcept représente le concept *dans le corpus*, pas dans un doc
- Évite la dérive vers un document spécifique
- Cohérence cross-document

### 5. Stockage Anchors : Double écriture intentionnelle

**Décision** : Anchors stockés dans Neo4j ET dans Qdrant payload.

**Neo4j** (source de vérité) :
- Navigation graphe : concept → ses chunks
- Requêtes Cypher complexes
- Audit et traçabilité

**Qdrant** (projection) :
- Retrieval enrichi : chunk → ses concepts
- Reranking intelligent
- Réponse expliquée

---

## Estimation des Gains

### Temps de traitement

| Phase | Avant | Après (Pass 1) | Réduction |
|-------|-------|----------------|-----------|
| EXTRACT | 5.7 min | 5-6 min | ~0% |
| CLASSIFY | 15 min | 0 (Pass 2) | **-100%** |
| GATE_CHECK | 10 min | 2 min | **-80%** |
| RELATIONS | 1 min | 1 min | 0% |
| CHUNKING | 10+ min | 1 min | **-90%** |
| **TOTAL Pass 1** | **35+ min** | **~10 min** | **-70%** |

### Volumétrie

| Métrique | Avant | Après | Réduction |
|----------|-------|-------|-----------|
| Chunks / doc | 11,797 | ~180 | **98%** |
| Batches embeddings | 2,950 | ~45 | **98%** |
| Concepts avec anchors | Variable | 100% | - |

### Projection corpus

| Scénario | Avant | Après |
|----------|-------|-------|
| 70 docs (Pass 1 only) | 40+ heures | **~12 heures** |
| 70 docs (Pass 1 + Pass 2 inline) | - | **~16 heures** |
| Burst overnight | Non viable | **Viable** |

---

## Plan d'Implémentation

### Phase 1 : Préparation

1. [ ] Corriger les fichiers utilisant `LLMRouter()` direct :
   - `src/knowbase/relations/llm_relation_extractor.py:480`
   - `src/knowbase/relations/relation_enricher.py:121`

2. [ ] Ajouter `rapidfuzz` aux dépendances

3. [ ] Créer la configuration `PASS2_MODE`

### Phase 2 : Refactoring EXTRACT

4. [ ] Modifier le prompt d'extraction pour demander des quotes exactes

5. [ ] Implémenter `create_anchor_with_fuzzy_match()`

6. [ ] Créer le modèle `Anchor` dans les schemas

### Phase 3 : Simplification GATE_CHECK

7. [ ] Supprimer `EmbeddingsContextualScorer`

8. [ ] Implémenter scoring simplifié (TF-IDF + fréquence anchors)

9. [ ] Modifier la déduplication pour 1 embedding / CanonicalConcept

### Phase 4 : Refactoring CHUNKING

10. [ ] Modifier `TextChunker` : config 256 tokens

11. [ ] Supprimer la génération de concept-focused chunks

12. [ ] Implémenter la liaison anchors → chunks

13. [ ] Enrichir le payload Qdrant avec `anchored_concepts`

### Phase 5 : Classification hybride

14. [ ] Implémenter `classify_heuristic()` dans Pass 1

15. [ ] Déplacer classification LLM en Pass 2

### Phase 6 : Pass 2 configurable

16. [ ] Créer `Pass2Orchestrator` avec modes inline/background/scheduled

17. [ ] Implémenter les phases CLASSIFY_FINE, ENRICH_RELATIONS, CROSS_DOC

### Phase 7 : Recherche hybride

18. [ ] Modifier le service de recherche pour fusion chunks + concepts

19. [ ] Implémenter le reranking unifié

20. [ ] Ajouter les anchors dans la réponse (citations)

---

## Critères d'Acceptation

### Pass 1

- [ ] Temps < 12 min pour un document de 40 pages
- [ ] 0 concept-focused chunks générés
- [ ] 100% des concepts ont au moins 1 anchor
- [ ] Chunks génériques : 150-250 pour 40 pages
- [ ] Recherche fonctionnelle sur chunks

### Pass 2

- [ ] Ne bloque pas Pass 1
- [ ] Classification fine disponible
- [ ] Mode configurable fonctionne (inline/background/scheduled)

### Qualité

- [ ] Anchors avec positions exactes (< 5% approximate)
- [ ] Recherche hybride retourne concepts + chunks
- [ ] Réponses incluent citations vérifiables

---

## Risques et Mitigations

| Risque | Impact | Mitigation |
|--------|--------|------------|
| Fuzzy match rate bas | Anchors approximate | Améliorer prompts extraction |
| Perte qualité RAG | UX dégradée | A/B test avant/après |
| Pass 2 jamais exécuté | Graphe pauvre | Alerting + dashboard |
| Régression scoring | Concepts non pertinents promus | Golden set de test |

---

## Conclusion

Le **Hybrid Anchor Model** n'est pas une optimisation. C'est une **correction architecturale** qui :

1. **Élimine** la duplication sémantique (concept-focused chunks)
2. **Préserve** toute la richesse informationnelle (anchors traçables)
3. **Réduit** le temps de traitement de 70%
4. **Rend** le système viable pour un usage production

L'architecture à 2 passes permet de livrer un système exploitable rapidement (Pass 1) tout en conservant la capacité d'enrichissement sémantique (Pass 2).

---

## Références

- Discussion architecture : 2024-12-29 (Claude + ChatGPT consensus)
- Document test : `aepd_gdpr_ai_guide.pdf` (172K chars, ~40 pages)
- Mesures initiales : 35+ min / 11,713 chunks / 527 concepts
