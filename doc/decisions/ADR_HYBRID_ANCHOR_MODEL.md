# ADR: Hybrid Anchor Model Architecture

**Date**: 2024-12-29
**Statut**: Accepté
**Auteurs**: Architecture Review (Claude + ChatGPT consensus)
**Impact**: Majeur - Refonte du pipeline d'ingestion OSMOSE

---

## Invariants d'Architecture (Non-Négociables)

Ces règles sont **verrouillées** et ne doivent jamais être remises en question :

### 1. Aucun concept sans anchor
> Un concept qui n'est pas ancré dans le texte source n'existe pas dans le système.

**Garanties** : Élimination du bruit, traçabilité native, KG sain, auditabilité B2B.

### 2. Aucun texte indexé généré par LLM
> Le LLM sélectionne, qualifie et consolide. Il ne matérialise JAMAIS de texte indexé.

**Garanties** : Pas de reformulations hallucinées dans Qdrant, vérifiabilité des citations.

### 3. Chunking indépendant des concepts
> Les chunks sont découpés selon des règles fixes (taille, overlap). Jamais selon les concepts.

**Garanties** : Volumétrie prévisible, pas d'explosion combinatoire.

### 4. Neo4j = Vérité, Qdrant = Projection
> En cas de divergence, Neo4j fait foi. Qdrant est une vue optimisée pour le retrieval.

**Garanties** : Source unique de vérité, cohérence garantie.

### 5. Pass 1 toujours exploitable
> Même si Pass 2 ne tourne jamais, le système doit être 100% fonctionnel après Pass 1.

**Garanties** : Pas de dépendance cachée, livraison incrémentale possible.

### 6. Payload Qdrant minimal
> Le payload Qdrant ne contient que : `concept_id`, `label`, `role`, `span`, `chunk_id`.

**Interdits** : Pas de définitions, pas de textes synthétiques, pas de contextes étendus.

**Garanties** : Évite la dérive de duplication, maintient la séparation des responsabilités.

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

> **Note architecturale** : Bien que traitée comme une phase unique, EXTRACT comprend deux sous-phases conceptuellement distinctes pour faciliter le debug, les logs et la reprise sur erreur.

#### Entrée
- Document segmenté (47 segments pour 40 pages)

#### Sous-phase A : EXTRACT_CONCEPTS

Responsabilité : Extraction sémantique pure

1. **Extraction LLM** : Pour chaque segment, le LLM extrait :
   - Concepts (label, type heuristique, définition courte)
   - Quote textuelle exacte justifiant le concept
   - Rôle de l'anchor (definition, procedure, requirement, example, etc.)

**Logs attendus** : `[OSMOSE:EXTRACT_CONCEPTS] Segment 12/47 → 8 concepts extraits`

#### Sous-phase B : ANCHOR_RESOLUTION

Responsabilité : Localisation et validation des anchors

2. **Fuzzy Matching** : Algorithme (rapidfuzz) localise la quote dans le segment source
   - Produit `char_start`, `char_end` exacts
   - Si similarité < 85% → anchor marqué `approximate`
   - Si quote introuvable → concept rejeté (pas d'anchor = pas de concept)

3. **Création ProtoConcept** : Chaque concept validé est créé avec :
   - Son embedding (label + quote principale)
   - Son anchor vers le segment source

**Logs attendus** : `[OSMOSE:ANCHOR_RESOLUTION] 8 concepts → 7 anchors valides, 1 rejeté`

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

#### Règle de Promotion : 3 Statuts de Concepts

> **Problématique** : Le garde-fou `min=2` protège contre le bruit, mais risque de perdre des concepts rares mais critiques (obligation légale citée une fois, exception spécifique, terme technique rare mais clé).

**Solution** : 3 niveaux de statut au lieu d'un simple "promu / rejeté"

| Statut | Critère | Usage | Stabilité |
|--------|---------|-------|-----------|
| **ProtoConcept** | Anchor valide | Toujours conservé, exploitable via chunks | doc-level |
| **CanonicalConcept "stable"** | ≥2 ProtoConcepts OU ≥2 sections | Graphe navigable, recherche directe | corpus-level |
| **CanonicalConcept "singleton"** | 1 seul, mais high-signal | Marqué `needs_confirmation=true` | corpus-level (prudent) |

#### Règle de promotion

```python
PROMOTION_CONFIG = {
    "min_proto_concepts_for_stable": 2,      # ProtoConcepts distincts
    "min_anchor_sections_for_stable": 2,      # Anchors sur sections différentes
    "allow_singleton_if_high_signal": True,   # Voie d'exception
}

def should_promote(proto_concepts: List[ProtoConcept]) -> Tuple[bool, str]:
    """Détermine si un groupe de ProtoConcepts doit être promu en Canonical."""

    count = len(proto_concepts)
    sections = len(set(pc.section_id for pc in proto_concepts))

    # Règle standard : robustesse par fréquence
    if count >= 2 or sections >= 2:
        return True, "stable"

    # Voie d'exception : singleton high-signal
    if count == 1 and is_high_signal(proto_concepts[0]):
        return True, "singleton"  # Marqué needs_confirmation

    return False, None  # Reste ProtoConcept uniquement

def is_high_signal(pc: ProtoConcept) -> bool:
    """Détecte si un concept singleton est critique malgré sa rareté."""

    # Rôle anchor normatif
    if pc.anchor_role in {"requirement", "prohibition", "definition", "constraint"}:
        return True

    # Modaux normatifs dans la quote
    if any(modal in pc.quote.lower() for modal in ["shall", "must", "required", "prohibited"]):
        return True

    # Section type critique
    if pc.section_type in {"requirements", "security", "compliance", "sla", "constraints"}:
        return True

    # Domaine high-value (GDPR, security, DR, etc.)
    if pc.domain in {"gdpr", "security", "disaster_recovery", "sla", "compliance"}:
        return True

    return False
```

#### Traitement
1. **Scoring simplifié** :
   - TF-IDF sur le label/définition
   - Fréquence d'apparition (nombre d'anchors)
   - Centralité basique si graphe existant

2. **Déduplication** :
   - Regroupement des ProtoConcepts similaires
   - Création CanonicalConcept avec embedding consolidé
   - Attribution du statut : "stable" ou "singleton"

3. **Persistance Neo4j** :
   - ProtoConcepts (toujours conservés)
   - CanonicalConcepts avec propriété `stability: "stable"|"singleton"`
   - Singletons marqués `needs_confirmation: true`
   - Relations ANCHORED_IN

#### Sortie
- CanonicalConcepts avec 1 embedding chacun
- Distinction stable/singleton pour la qualité du graphe
- Graphe Neo4j propre

#### Garantie importante
> Même si un concept n'est pas promu en CanonicalConcept, il reste **exploitable** via les chunks (Qdrant) + anchors. La recherche reste complète.

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
- **CanonicalConcept** (corpus-level) : embedding en 2 temps

**Moment exact de l'embedding CanonicalConcept** :

| Phase | Type d'embedding | Méthode | Commentaire |
|-------|------------------|---------|-------------|
| **Pass 1** | Provisoire | Centroïde des embeddings ProtoConcept | 100% fonctionnel, pas de dépendance LLM |
| **Pass 2** | Canonique | Synthèse LLM du concept | Amélioration optionnelle |

```python
def compute_canonical_embedding(proto_concepts: List[ProtoConcept], pass_number: int):
    """Calcule l'embedding d'un CanonicalConcept selon la pass."""

    if pass_number == 1:
        # Centroïde = moyenne des embeddings ProtoConcept
        embeddings = [pc.embedding for pc in proto_concepts]
        return np.mean(embeddings, axis=0)  # Déterministe, rapide

    else:  # Pass 2
        # Synthèse LLM = embedding de la définition consolidée
        consolidated_def = llm_consolidate_definitions(proto_concepts)
        return embed(consolidated_def)  # Plus riche sémantiquement
```

**Garantie Pass 1** :
- L'embedding centroïde est **immédiatement disponible**
- La recherche vectorielle fonctionne sans attendre Pass 2
- Pas de dépendance cachée vers le LLM

**Justification** :
- Un CanonicalConcept représente le concept *dans le corpus*, pas dans un doc
- Évite la dérive vers un document spécifique
- Cohérence cross-document
- Pass 2 améliore sans invalider

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

### 6. Payload Qdrant : Règle de Minimalité

**Décision** : Le payload Qdrant pour `anchored_concepts` est strictement limité.

**Champs autorisés** :

```python
ALLOWED_ANCHOR_PAYLOAD_FIELDS = {
    "concept_id",   # Référence vers Neo4j
    "label",        # Nom du concept (pour affichage rapide)
    "role",         # Rôle de l'anchor (definition, requirement, etc.)
    "span",         # [char_start, char_end] dans le chunk
    "chunk_id",     # Référence vers le chunk parent
}
```

**Champs INTERDITS** (ne jamais ajouter) :

```python
FORBIDDEN_ANCHOR_PAYLOAD_FIELDS = {
    "definition",       # ❌ Duplication de Neo4j
    "synthetic_text",   # ❌ Texte généré par LLM
    "full_context",     # ❌ Contexte étendu
    "embedding",        # ❌ Jamais dans payload
    "relations",        # ❌ Appartient à Neo4j
    "metadata",         # ❌ Trop générique, risque de dérive
}
```

**Justification** :
- Évite la dérive de duplication avec Neo4j
- Maintient Qdrant comme **projection légère**
- Force les enrichissements à passer par Neo4j
- Dans 6 mois, quelqu'un sera tenté d'ajouter "par confort" → cette règle l'en empêche

**Validation automatique** :

```python
def validate_anchor_payload(anchor_payload: dict) -> bool:
    """Rejette tout payload non-conforme."""
    for key in anchor_payload.keys():
        if key not in ALLOWED_ANCHOR_PAYLOAD_FIELDS:
            raise ValueError(f"Champ interdit dans anchor payload: {key}")
    return True
```

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

---

## Addendum 2024-12-30 : Architecture Relations Pass 2

### Contexte

L'Option A' (extraction relations chunk-by-chunk) corrigeait le dépassement de contexte LLM mais introduisait un problème de coût : **166 appels LLM** au lieu de ~47, causant des temps de 20-25 min au lieu de ~1 min prévu.

**Décision** : Les relations explicites sont déplacées en **Pass 2** (non-bloquant), avec extraction au niveau **segment** (pas chunk).

### Invariants Pass 1 / Pass 2 (Non-Négociables)

#### 1. Pass 1 MUST be usable without explicit relations
RAG + concepts + anchors + corrélations (similarité embeddings).
Aucune relation typée en Pass 1.

#### 2. No relation is persisted without text evidence
Quote trouvable + ancrage (chunk_id, span).
Si quote introuvable → relation rejetée.

#### 3. Relations extraction is segment-level only
Chunk-level extraction interdit (sauf mode debug).
Unité d'extraction = segment sémantique (~47 par document).

#### 4. Hard budgets (non-dépassables)
```python
PASS2_RELATION_BUDGET = {
    "max_relations_per_segment": 8,
    "max_total_relations_per_doc": 150,
    "max_quote_words": 30,
    "max_output_tokens": 800,
    "predicate_set": [
        "defines", "requires", "enables", "prevents", "causes",
        "applies_to", "part_of", "depends_on", "mitigates",
        "conflicts_with", "example_of", "governed_by"
    ]
}
```

#### 5. Every relation must include an anchorable quote
Format obligatoire : `subject_id`, `predicate`, `object_id`, `confidence`, `quote`.

#### 6. Observability required
- Par segment : relations proposées / validées / rejetées
- Par document : taux fuzzy-match, tokens consommés, état enrichissement

#### 7. UI/API must distinguish correlations from relations
- **Corrélations Pass 1** : "Similar concepts" (embedding_similarity, same_section)
- **Relations Pass 2** : "Relations" (predicates typés avec evidence)

### Scoring Segments Pass 2

Objectif : Ne lancer des appels LLM que sur les segments à fort potentiel relationnel.

```python
def compute_segment_score(segment) -> int:
    """Score 0-100 pour décider si on extrait les relations."""

    # 1. Densité d'anchors (signal principal)
    anchor_score = min(segment.anchors_count * 15, 45)

    # 2. Diversité conceptuelle
    diversity_score = min(segment.unique_concepts_count * 10, 30)

    # 3. Type de section
    section_scores = {
        "requirements": 25, "process": 25, "architecture": 25, "rules": 25,
        "scope": 15, "obligations": 15, "controls": 15,
        "definition": 5,
        "introduction": -20, "summary": -20, "annex": -20, "foreword": -20
    }
    section_type_score = section_scores.get(segment.section_type, 0)

    # 4. Pénalité narratif pur
    narrative_penalty = -20 if (segment.anchors_count <= 1 and segment.unique_concepts_count <= 1) else 0

    return anchor_score + diversity_score + section_type_score + narrative_penalty

# Seuils de décision
SEGMENT_SCORE_THRESHOLDS = {
    "run_always": 50,      # Score >= 50 → extraction systématique
    "run_if_budget": 35,   # Score 35-49 → si budget disponible
    "skip": 0              # Score < 35 → skip
}
```

**Résultat attendu** : ~15-25 appels LLM au lieu de 47, sans perte significative.

### État d'enrichissement par document

```python
DOCUMENT_ENRICHMENT_STATUS = {
    "pass1_done": "Socle exploitable (RAG + concepts)",
    "pass2_pending": "En attente d'enrichissement relations",
    "pass2_running": "Enrichissement en cours",
    "pass2_done": "Graphe complet avec relations",
    "pass2_failed": "Échec enrichissement (voir logs)",
    "pass2_skipped": "Enrichissement ignoré (config)"
}
```

### Gestion quotes introuvables

```python
FUZZY_MATCH_CONFIG = {
    "min_score": 85,
    "on_match_failure": "reject",  # Options: "reject" | "needs_review"
    "log_failures": True,
    "max_failures_before_alert": 10
}
```

**Règle absolue** : Pass 2 n'écrit jamais une relation sans preuve ancrée.

### Mode d'exécution Pass 2

```python
PASS2_EXECUTION_MODE = {
    "burst_active": "inline",      # GPU disponible → immédiat
    "burst_inactive": "scheduled", # Batch (nocturne ou job)
    "force_skip": False            # Désactiver Pass 2
}
```

### Validation

- [x] Analyse validée par ChatGPT (2024-12-30)
- [x] Architecture cohérente avec Pass 1 socle / Pass 2 enrichissement
- [ ] Implémentation
- [ ] Tests
- [ ] Métriques observabilité

---

## Addendum 2026-01-09 : ADR_UNIFIED_CORPUS_PROMOTION

### Changement majeur : Promotion déplacée de Pass 1 vers Pass 2.0

**Contexte** : L'analyse du corpus a révélé que 46 concepts apparaissant dans ≥2 documents n'étaient jamais promus car la promotion était faite document par document en Pass 1, sans vue corpus.

**Décision** : La promotion des ProtoConcepts en CanonicalConcepts est maintenant effectuée en **Pass 2.0** (nouvelle phase CORPUS_PROMOTION), AVANT toutes les autres phases Pass 2.

### Impact sur ce document

**Sections obsolètes** (conservées pour historique, remplacées par Pass 2.0) :

1. **Section "Phase GATE_CHECK simplifiée" (lignes 202-295)** :
   - ❌ La promotion N'EST PLUS effectuée en Pass 1
   - ✅ Pass 1 crée uniquement des ProtoConcepts
   - ✅ Le scoring est conservé mais la promotion est déférée

2. **Section "Règle de Promotion : 3 Statuts de Concepts"** :
   - ❌ Le code `should_promote()` ne s'exécute plus en Pass 1
   - ✅ Cette logique est maintenant dans `CorpusPromotionEngine` (Pass 2.0)

### Nouvelle architecture pipeline

```
┌─────────────────────────────────────────────────────────────────┐
│                         PASS 1 - SOCLE                          │
│              (Bloquant, ~10 min/doc, système exploitable)       │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  EXTRACT ────► ANCHOR_RESOLUTION ────► CHUNK ────► ✓           │
│                                                                 │
│  Résultat : ProtoConcepts + Chunks, AUCUN CanonicalConcept     │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                     PASS 2.0 - CORPUS PROMOTION                 │
│                    (NOUVEAU - ADR_UNIFIED_CORPUS_PROMOTION)     │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  LOAD_PROTOS ────► GROUP_BY_LABEL ────► APPLY_RULES ────►      │
│  CREATE_CANONICALS                                              │
│                                                                 │
│  Résultat : CanonicalConcepts avec vue corpus complète         │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                     PASS 2a/2b/3 - ENRICHISSEMENT               │
│                    (Non bloquant, optionnel SLA)                │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  STRUCTURAL_TOPICS ────► CLASSIFY_FINE ────► ENRICH_RELATIONS  │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

### Règles de promotion Pass 2.0 (remplacent celles de Pass 1)

```python
# ADR_UNIFIED_CORPUS_PROMOTION - Règles unifiées
PROMOTION_RULES = {
    # Règle 1: Multi-occurrence même document
    "stable_if_multi_occurrence": "proto_count >= 2",

    # Règle 2: Multi-section même document
    "stable_if_multi_section": "section_count >= 2",

    # Règle 3: Cross-document avec signal minimal
    "stable_if_crossdoc": "document_count >= 2 AND has_minimal_signal",

    # Règle 4: Singleton high-signal V2
    "singleton_if_high_signal": "proto_count == 1 AND check_high_signal_v2()",
}

# High-Signal V2 = NORMATIF + NON-TEMPLATE + SIGNAL-CONTENU
def check_high_signal_v2(proto):
    # 1. NORMATIF: rôle ou modal
    is_normative = (
        proto.anchor_role in {"definition", "requirement", "constraint"} or
        has_normative_modal(proto.quote)  # shall, must, required
    )

    # 2. NON-TEMPLATE: pas boilerplate
    is_not_template = (
        proto.template_likelihood < 0.5 and
        proto.positional_stability < 0.8 and
        not proto.is_repeated_bottom
    )

    # 3. SIGNAL-CONTENU: zone main ou section
    has_content_signal = (
        proto.dominant_zone == "main" or
        proto.section_path not in [None, ""]
    )

    return is_normative and is_not_template and has_content_signal
```

### Signal minimal pour cross-document

```python
def has_minimal_signal(protos: List[Proto]) -> bool:
    """Au moins un proto avec signal exploitable."""
    return any(
        p.anchor_status == "SPAN" or
        p.anchor_role in {"definition", "constraint"} or
        p.confidence >= 0.7
        for p in protos
    )
```

### Invariants préservés

1. ✅ **Invariant #5 "Pass 1 toujours exploitable"** : Reste vrai car les chunks + ProtoConcepts permettent la recherche
2. ✅ **Invariant #1 "Aucun concept sans anchor"** : Appliqué en Pass 1, préservé en Pass 2.0
3. ✅ **Invariant #4 "Neo4j = Vérité"** : Les CanonicalConcepts sont créés dans Neo4j par Pass 2.0

### Référence

- **Spec complète** : `doc/ongoing/ADR_UNIFIED_CORPUS_PROMOTION.md`
- **Implémentation** : `src/knowbase/consolidation/corpus_promotion.py`
- **Phase Pass 2** : `src/knowbase/ingestion/pass2_orchestrator.py` (phase CORPUS_PROMOTION)
