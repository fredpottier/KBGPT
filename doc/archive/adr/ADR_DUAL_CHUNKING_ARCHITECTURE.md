> ⚠️ ARCHIVED - Superseded par ADR_COVERAGE_PROPERTY_NOT_NODE + ADR_STRUCTURAL_GRAPH_FROM_DOCLING

# ADR: Dual Chunking Architecture (Coverage vs Retrieval)

**Date**: 2026-01-09
**Statut**: ARCHIVED
**Auteurs**: Claude + ChatGPT + Fred
**Contexte**: Résolution du problème ANCHORED_IN manquants
**Revue**: Évaluation ChatGPT 2026-01-09 - Approuvé avec micro-ajustements

---

## 1. Contexte et Problème

### 1.1 Symptôme observé

Après import d'un document :
- **50 concepts avec anchor_status=SPAN** (extraction réussie, quote trouvée)
- **Seulement 18 relations ANCHORED_IN créées** (36%)
- **32 concepts SPAN orphelins** (64%) - sans lien vers les chunks

### 1.2 Diagnostic

Investigation des chunks dans Neo4j :
- 40 chunks créés pour le document
- Couverture déclarée : [212 - 151921] caractères
- **35 gaps significatifs** détectés entre les chunks
- **Couverture réelle : 27.7%** du document seulement

```
Chunks couvrent : 41,942 caractères
Gaps totaux : 109,701 caractères
Ratio couverture : 27.7%
```

Exemples de gaps :
```
[1917 - 4523] = 2,606 chars de gap
[19845 - 25487] = 5,642 chars de gap
[31054 - 38202] = 7,148 chars de gap
```

### 1.3 Cause racine

Le `HybridAnchorChunker` utilise un mode **layout-aware** qui :
1. Détecte les régions structurelles (tables, paragraphes, titres)
2. Crée des chunks pour chaque région
3. **Ignore les régions avec moins de 50 tokens** (~35-40 mots)

Code responsable (`hybrid_anchor_chunker.py`, ligne 381-391) :
```python
if token_count <= self.chunk_size:
    if token_count >= self.min_chunk_tokens:  # min_chunk_tokens = 50
        chunks.append({...})
    # SINON : région ignorée → crée un gap
```

### 1.4 Conflit architectural identifié

**"Chunk" sert actuellement à deux choses incompatibles :**

| Usage | Objectif | Besoin |
|-------|----------|--------|
| **Retrieval** (Qdrant) | Qualité sémantique, pertinence | Filtrage OK, densité |
| **Ancrage** (Neo4j ANCHORED_IN) | Preuve localisable | Couverture 100% |

La règle des 50 tokens est **légitime pour le retrieval** (éviter bruit, embeddings pauvres) mais **destructrice pour l'ancrage** (crée des zones mortes).

---

## 2. Options Considérées

### Option 1: Supprimer le filtre min_tokens
- **Simple** mais introduit du bruit dans le retrieval
- **Non pérenne** : on devra le remettre plus tard

### Option 2: Merge small regions
- Fusionner les petites régions avec les adjacentes
- **Complexité moyenne** mais reste un compromis
- Continue de mélanger deux responsabilités

### Option 3: Mapping au chunk le plus proche
- **Dangereux** : crée des "preuves fantômes"
- Détruit l'invariant "anchor = preuve localisable"
- **Rejeté**

### Option 4: Dual Chunking (Coverage vs Retrieval)
- Séparation claire des responsabilités (SRP)
- Chaque type optimisé pour son usage
- **Pérenne et production-grade**
- Aligné avec la philosophie OSMOSE (couches séparées)

---

## 3. Décision

**Adopter le Dual Chunking (Option 4)**

Créer deux types de chunks avec des responsabilités distinctes :

### 3.1 CoverageChunks

| Aspect | Spécification |
|--------|---------------|
| **Objectif** | Couverture 100% du texte, unité de preuve |
| **Stockage** | Neo4j uniquement |
| **Vectorisation** | Non (pas dans Qdrant) |
| **Stratégie** | Chunking linéaire simple, pas layout-aware |
| **Filtrage** | Aucun (pas de min_tokens) |
| **Overlap** | Faible ou nul |
| **Taille** | 600-1200 tokens (à définir) |

### 3.2 RetrievalChunks

| Aspect | Spécification |
|--------|---------------|
| **Objectif** | Retrieval sémantique efficace |
| **Stockage** | Neo4j + Qdrant |
| **Vectorisation** | Oui (embeddings 1024 dims) |
| **Stratégie** | Layout-aware (préserve tables) |
| **Filtrage** | min_tokens = 50 (garde la règle) |
| **Overlap** | 64 tokens |
| **Taille** | 256 tokens |

### 3.3 Relations

```
(ProtoConcept)-[:ANCHORED_IN]->(CoverageChunk)
     └── Preuve localisable, couverture garantie

(CoverageChunk)-[:ALIGNS_WITH {overlap_chars, overlap_ratio}]->(RetrievalChunk)
     └── Lien par intersection de positions

RetrievalChunk.payload.anchored_concepts
     └── Alimenté via les intersections spans
```

---

## 4. Schéma Neo4j

### 4.1 Node: DocumentChunk (étendu)

```cypher
(:DocumentChunk {
    // Identité
    chunk_id: String,           // UUID unique
    document_id: String,
    tenant_id: String,

    // Type (NOUVEAU)
    chunk_type: "coverage" | "retrieval",

    // Positions (commun)
    char_start: Integer,
    char_end: Integer,

    // Contexte
    context_id: String,         // Hash(document_id + section_path)
    section_path: String,
    segment_id: String,

    // Spécifique Coverage
    coverage_seq: Integer,      // Ordre séquentiel (si coverage)

    // Spécifique Retrieval
    token_count: Integer,       // (si retrieval)
    is_atomic: Boolean,         // Table non coupée (si retrieval)
    region_type: String,        // Type région layout (si retrieval)

    // Métadonnées
    created_at: DateTime
})
```

### 4.2 Relation: ANCHORED_IN (modifiée)

```cypher
(ProtoConcept)-[:ANCHORED_IN {
    role: String,               // "definition", "context", etc.
    span_start: Integer,        // Position RELATIVE au début du chunk (pas absolue dans le document)
    span_end: Integer,          // Position RELATIVE au début du chunk
    created_at: DateTime
}]->(DocumentChunk {chunk_type: "coverage"})
```

**Invariants**:
- ANCHORED_IN pointe TOUJOURS vers un CoverageChunk (jamais RetrievalChunk)
- `span_start` et `span_end` sont des positions **relatives au chunk**, calculées comme :
  - `span_start = anchor.char_start - chunk.char_start`
  - `span_end = anchor.char_end - chunk.char_start`

### 4.3 Relation: ALIGNS_WITH (nouvelle)

```cypher
(DocumentChunk {chunk_type: "coverage"})-[:ALIGNS_WITH {
    overlap_chars: Integer,     // Nombre de chars en commun
    overlap_ratio: Float,       // Ratio d'overlap (0.0 - 1.0)
    created_at: DateTime
}]->(DocumentChunk {chunk_type: "retrieval"})
```

Construction : pour chaque RetrievalChunk, trouver les CoverageChunks dont `[char_start, char_end]` intersecte.

### 4.4 Note sur context_id

Le champ `context_id` (hash de document_id + section_path) **reste inchangé et orthogonal** au dual chunking :
- Il sert de pivot vers la Navigation Layer (SectionContext)
- Il est présent sur les deux types de chunks
- Il n'est PAS utilisé pour le mapping Coverage ↔ Retrieval (qui se fait par positions)

---

## 5. Qdrant (inchangé conceptuellement)

Collection `knowbase` contient uniquement les **RetrievalChunks**.

Payload enrichi via intersections :
```json
{
    "chunk_id": "uuid",
    "document_id": "...",
    "char_start": 1000,
    "char_end": 2500,
    "anchored_concepts": [
        {
            "concept_id": "pc_xxx",
            "label": "SAP S/4HANA",
            "role": "definition",
            "span": [120, 180]
        }
    ],
    // ... autres champs existants
}
```

`anchored_concepts` est alimenté en :
1. Trouvant les CoverageChunks qui intersectent ce RetrievalChunk
2. Récupérant les ProtoConcepts liés via ANCHORED_IN
3. Calculant les spans relatifs au RetrievalChunk

---

## 6. Algorithme de Génération

### 6.1 Pipeline modifié

```
Document text_content
    │
    ├──► CoverageChunkGenerator (linéaire)
    │        └──► CoverageChunks[] ──► Neo4j
    │
    ├──► RetrievalChunkGenerator (layout-aware)
    │        └──► RetrievalChunks[] ──► Neo4j + Qdrant
    │
    ├──► AlignmentBuilder
    │        └──► ALIGNS_WITH relations ──► Neo4j
    │
    └──► AnchorMapper
             └──► ANCHORED_IN (vers CoverageChunks) ──► Neo4j
             └──► anchored_concepts payload ──► Qdrant
```

### 6.2 Génération CoverageChunks

```python
def generate_coverage_chunks(text_content: str, document_id: str) -> List[CoverageChunk]:
    """
    Chunking linéaire simple pour couverture 100%.

    - Pas de layout-aware
    - Pas de filtrage min_tokens
    - Overlap minimal (éviter doublons de preuve)
    """
    COVERAGE_CHUNK_SIZE = 800  # tokens (à calibrer)
    COVERAGE_OVERLAP = 50      # tokens (minimal)

    chunks = []
    # Tokenize et découper linéairement
    # ...
    return chunks
```

### 6.3 Mapping ANCHORED_IN

```python
def map_anchors_to_coverage_chunks(
    proto_concepts: List[ProtoConcept],
    coverage_chunks: List[CoverageChunk]
) -> List[AnchoredInRelation]:
    """
    Chaque anchor SPAN doit trouver son CoverageChunk.

    Invariant: Si anchor.char_start/end est dans le document,
    il DOIT y avoir un CoverageChunk qui le contient.
    """
    for proto in proto_concepts:
        if proto.anchor_status != "SPAN":
            continue

        for anchor in proto.anchors:
            # Trouver le CoverageChunk contenant cette position
            matching_chunk = find_coverage_chunk(
                coverage_chunks,
                anchor.char_start,
                anchor.char_end
            )

            if matching_chunk is None:
                # ERREUR: couverture incomplète!
                raise CoverageError(f"No coverage chunk for anchor at {anchor.char_start}")

            yield AnchoredInRelation(proto.id, matching_chunk.id, anchor)
```

---

## 7. Métriques de Validation

Après implémentation, vérifier :

| Métrique | Avant | Cible | Description |
|----------|-------|-------|-------------|
| Coverage chars (%) | 27.7% | **>95%** | Couverture du document par CoverageChunks |
| ANCHORED_IN / SPAN (%) | 36% | **>95%** | Concepts SPAN avec relation ANCHORED_IN |
| Gaps significatifs | 35 | **0** | Nombre de trous >100 chars entre CoverageChunks |
| RAG end-to-end (%) | N/A | **>90%** | % ProtoConcept SPAN présents dans ≥1 RetrievalChunk payload |

**Note sur RAG end-to-end** : Cette métrique vérifie que les concepts ancrés sont bien "consommables" par le RAG via les RetrievalChunks. CoverageChunks garantissent la preuve, mais le produit final dépend des RetrievalChunks.

Si ces métriques ne sont pas atteintes, il reste un bug.

---

## 8. Impact sur le Code Existant

### Fichiers à modifier

| Fichier | Modification |
|---------|--------------|
| `hybrid_anchor_chunker.py` | Séparer en 2 générateurs (Coverage + Retrieval) |
| `osmose_agentique.py` | Appeler les 2 générateurs, créer alignements |
| `osmose_persistence.py` | Créer ALIGNS_WITH, modifier ANCHORED_IN |
| `api/schemas/concepts.py` | Ajouter `chunk_type` enum si nécessaire |

### Fichiers inchangés

- `hybrid_anchor_extractor.py` - Extraction des concepts (indépendant)
- `anchor_resolver.py` - Résolution fuzzy (indépendant)
- `layout_detector.py` - Utilisé seulement par RetrievalChunks

---

## 9. Réponses aux Questions (spec ChatGPT 2026-01-09)

| Question | Réponse |
|----------|---------|
| Taille CoverageChunks | **800 tokens** |
| Overlap CoverageChunks | **0** (pas d'overlap) |
| Naming chunk_id | `{document_id}::coverage::{seq}` et `{document_id}::retrieval::{seq}` |
| ALIGNS_WITH | Tous les overlaps > 0 (pas de limite top-N) |

---

## 10. Invariants NON NÉGOCIABLES

### Invariant 1 – Proof completeness
```
COUNT(ProtoConcept WHERE anchor_status=SPAN) ≈ COUNT(ANCHORED_IN)
```
Tout concept SPAN doit avoir un lien ANCHORED_IN.

### Invariant 2 – Coverage
```
Σ coverage_chunks.covered_chars ≥ 95% du document
```
Les CoverageChunks doivent couvrir quasi-tout le texte.

### Invariant 3 – Retrieval quality
- Aucun chunk < 50 tokens vectorisé
- Nombre de RetrievalChunks stable vs avant

---

## 11. Spécification Implémentation (ChatGPT 2026-01-09)

### 11.1 Paramètres CoverageChunks

```python
COVERAGE_CHUNK_SIZE_TOKENS = 800
COVERAGE_OVERLAP_TOKENS = 0
```

### 11.2 Génération CoverageChunks

```python
def generate_coverage_chunks(text_content: str, document_id: str) -> List[Dict]:
    """
    Chunking linéaire simple pour couverture 100%.
    - Pas de layout-aware
    - Pas de filtrage min_tokens
    - Overlap nul
    """
    chunks = []
    seq = 0

    # Approximation: 1 token ≈ 4 chars
    chunk_size_chars = COVERAGE_CHUNK_SIZE_TOKENS * 4  # ~3200 chars

    for start in range(0, len(text_content), chunk_size_chars):
        end = min(start + chunk_size_chars, len(text_content))
        chunk = {
            "chunk_id": f"{document_id}::coverage::{seq}",
            "chunk_type": "coverage",
            "document_id": document_id,
            "char_start": start,
            "char_end": end,
            "coverage_seq": seq,
            "source": "linear_text"
        }
        chunks.append(chunk)
        seq += 1

    return chunks
```

### 11.3 Création ALIGNS_WITH

```python
def create_alignments(
    coverage_chunks: List[Dict],
    retrieval_chunks: List[Dict]
) -> List[Dict]:
    """
    Crée les relations ALIGNS_WITH entre Coverage et Retrieval chunks.
    """
    alignments = []

    for coverage in coverage_chunks:
        for retrieval in retrieval_chunks:
            overlap_chars = calculate_overlap(
                coverage["char_start"], coverage["char_end"],
                retrieval["char_start"], retrieval["char_end"]
            )

            if overlap_chars > 0:
                coverage_length = coverage["char_end"] - coverage["char_start"]
                alignments.append({
                    "coverage_chunk_id": coverage["chunk_id"],
                    "retrieval_chunk_id": retrieval["chunk_id"],
                    "overlap_chars": overlap_chars,
                    "overlap_ratio": overlap_chars / coverage_length
                })

    return alignments

def calculate_overlap(a_start: int, a_end: int, b_start: int, b_end: int) -> int:
    return max(0, min(a_end, b_end) - max(a_start, b_start))
```

### 11.4 Mapping ANCHORED_IN

```python
def map_anchors_to_coverage(
    proto_concepts: List[ProtoConcept],
    coverage_chunks: List[Dict]
) -> List[Dict]:
    """
    Mappe chaque anchor SPAN vers son CoverageChunk.

    Règle déterministe:
        coverage_chunk = first where chunk.char_start <= anchor.char_start < chunk.char_end
    """
    relations = []

    for proto in proto_concepts:
        if proto.anchor_status != "SPAN":
            continue

        for anchor in proto.anchors:
            # Trouver le CoverageChunk contenant cette position
            matching_chunk = None
            for chunk in coverage_chunks:
                if chunk["char_start"] <= anchor.char_start < chunk["char_end"]:
                    matching_chunk = chunk
                    break

            if matching_chunk is None:
                raise CoverageError(
                    f"No coverage chunk for anchor at position {anchor.char_start}"
                )

            relations.append({
                "proto_id": proto.id,
                "chunk_id": matching_chunk["chunk_id"],
                "role": anchor.role,
                "span_start": anchor.char_start - matching_chunk["char_start"],
                "span_end": anchor.char_end - matching_chunk["char_start"]
            })

    return relations
```

### 11.5 Alimentation payload Qdrant

```python
def build_retrieval_payload_anchored_concepts(
    retrieval_chunk: Dict,
    alignments: List[Dict],
    anchored_in_relations: List[Dict],
    proto_concepts: Dict[str, ProtoConcept]
) -> List[Dict]:
    """
    Alimente anchored_concepts pour un RetrievalChunk via les alignments.
    """
    anchored_concepts = []

    # Trouver les CoverageChunks alignés avec ce RetrievalChunk
    aligned_coverage_ids = [
        a["coverage_chunk_id"]
        for a in alignments
        if a["retrieval_chunk_id"] == retrieval_chunk["chunk_id"]
    ]

    # Trouver les ProtoConcepts ancrés dans ces CoverageChunks
    for relation in anchored_in_relations:
        if relation["chunk_id"] not in aligned_coverage_ids:
            continue

        proto = proto_concepts[relation["proto_id"]]

        # Recalculer le span relatif au RetrievalChunk
        # (si le concept est dans la zone du retrieval chunk)
        anchor_start = relation["span_start"]  # relatif au coverage
        # ... logique de recalcul ...

        anchored_concepts.append({
            "concept_id": proto.id,
            "label": proto.label,
            "role": relation["role"],
            "span": [span_start_relative, span_end_relative]
        })

    return anchored_concepts
```

---

## 12. Références

- Analyse ChatGPT du 2026-01-09 (dual chunking recommendation)
- ADR_HYBRID_ANCHOR_MODEL.md (architecture anchor existante)
- ADR_NAVIGATION_LAYER.md (séparation des couches)

---

## Annexe: Conversation de diagnostic

### Données brutes (document test)

```
Total chunks: 40
Couverture: [212 - 151921]

Gaps significatifs (>100 chars): 35
  Gap: [1917 - 4523] = 2606 chars
  Gap: [6054 - 7034] = 980 chars
  Gap: [8281 - 8536] = 255 chars
  ...

Couverture chunks: 41942 chars
Total gaps: 109701 chars
Ratio couverture: 27.7%
```

### Requêtes Neo4j utilisées

```cypher
// Compter SPAN vs ANCHORED_IN
MATCH (p:ProtoConcept {tenant_id: 'default', anchor_status: 'SPAN'})
WHERE NOT exists((p)-[:ANCHORED_IN]->(:DocumentChunk))
RETURN count(p) AS orphans

// Analyser gaps
MATCH (dc:DocumentChunk {tenant_id: 'default'})
RETURN dc.char_start, dc.char_end ORDER BY dc.char_start
```
