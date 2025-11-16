# Implémentation Cross-Référence Neo4j ↔ Qdrant

**Phase:** OSMOSE Phase 1.5 - Complémentarité KG + Vector Store
**Date:** 2025-10-17
**Statut:** 🟡 EN COURS

---

## 📋 Contexte

### Problème Identifié

L'architecture agentique OSMOSE actuelle crée uniquement :
- ✅ **Neo4j** : Proto-KG + Published-KG (concepts + relations)
- ✅ **Qdrant `concepts_proto`** : Embeddings des concepts (171 points)
- ❌ **Qdrant `knowbase`** : Vide (0 points) - devrait contenir chunks de texte

### Besoins Business

1. **Recherche hybride** : Neo4j (concepts/relations) + Qdrant (similarité vectorielle)
2. **Enrichissement contextuel** : Concept → Chunks textuels complets
3. **Navigation bidirectionnelle** : Chunk → Concepts → Relations graphe
4. **Fallback intelligent** : Si Neo4j = 0 résultats → Qdrant full-text

---

## 🎯 Architecture Cible

### 1. Neo4j → Qdrant (Concept vers Chunks)

**Schéma ProtoConcept/CanonicalConcept enrichi** :
```cypher
CREATE (proto:ProtoConcept {
  concept_id: "proto-uuid-123",
  concept_name: "SAP S/4HANA",
  concept_type: "PRODUCT",
  segment_id: "segment-1",
  chunk_ids: ["chunk-456", "chunk-789"],  // ← NOUVEAU: IDs chunks Qdrant
  confidence: 0.92,
  tenant_id: "default"
})

CREATE (canonical:CanonicalConcept {
  canonical_id: "canon-uuid-001",
  canonical_name: "SAP S/4HANA Cloud",
  chunk_ids: ["chunk-456", "chunk-789", "chunk-890"],  // ← NOUVEAU
  tenant_id: "default"
})
```

### 2. Qdrant → Neo4j (Chunk vers Concepts)

**Schéma Chunk Qdrant enrichi** :
```python
{
  "id": "chunk-456",
  "vector": [0.123, 0.456, ...],  # 1024 dimensions
  "payload": {
    "text": "SAP S/4HANA est une suite ERP cloud...",
    "document_id": "doc-123",
    "document_name": "SAP S/4HANA Overview.pdf",
    "segment_id": "segment-1",
    "chunk_index": 0,
    "proto_concept_ids": ["proto-123", "proto-124"],      // ← NOUVEAU
    "canonical_concept_ids": ["canon-001", "canon-002"],  // ← NOUVEAU
    "tenant_id": "default",
    "created_at": "2025-10-17T00:00:00Z"
  }
}
```

---

## 🔄 Flux d'Ingestion Modifié

### Avant (Phase 1.5 actuel)
```
Document → Segments → OSMOSE Agentique (FSM)
  → Extractor → Concepts
  → Miner → Relations
  → Gatekeeper → Neo4j (Proto + Published)
  → Qdrant (concepts_proto uniquement)
```

### Après (Phase 1.5 + Cross-Ref)
```
Document → Segments → OSMOSE Agentique (FSM)
  → Extractor → Concepts
  → Miner → Relations
  → Chunker → Chunks texte (NOUVEAU)
     ↓
  → Qdrant (knowbase):
     - Créer chunks avec proto_concept_ids
     - Retourner chunk_ids
     ↓
  → Gatekeeper → Neo4j (Proto + Published):
     - Créer ProtoConcept avec chunk_ids (NOUVEAU)
     - Promotion → CanonicalConcept avec chunk_ids agrégés (NOUVEAU)
     - Mise à jour chunks Qdrant avec canonical_concept_ids (NOUVEAU)
```

---

## 🛠️ Modifications Code

### 1. Module Chunking (NOUVEAU)

**Fichier** : `src/knowbase/ingestion/text_chunker.py` (NOUVEAU)

**Fonctionnalités** :
- Découpage texte en chunks (512 tokens, overlap 128)
- Génération embeddings par chunk (multilingual-e5-large, 1024D)
- Attribution chunks aux concepts (mention du concept dans chunk)
- Format output compatible Qdrant

**Méthodes principales** :
```python
class TextChunker:
    def chunk_document(
        self,
        text: str,
        document_id: str,
        segment_id: str,
        concepts: List[Dict],
        chunk_size: int = 512,
        overlap: int = 128
    ) -> List[Dict]:
        """
        Découpe texte en chunks et associe concepts.

        Returns:
            List of chunks: [
                {
                    "text": "...",
                    "chunk_index": 0,
                    "proto_concept_ids": ["proto-123"],
                    "embedding": [0.123, ...]
                }
            ]
        """
```

---

### 2. Neo4j Client (MODIFICATION)

**Fichier** : `src/knowbase/common/clients/neo4j_client.py`

**Modifications** :

#### a) Méthode `create_proto_concept()` (ligne ~170)
```python
def create_proto_concept(
    self,
    tenant_id: str,
    concept_id: str,
    concept_name: str,
    concept_type: str,
    confidence: float,
    metadata: Optional[Dict[str, Any]] = None,
    segment_id: Optional[str] = None,
    chunk_ids: Optional[List[str]] = None  # ← NOUVEAU paramètre
) -> bool:
    """
    Créer ProtoConcept dans Neo4j avec références chunks Qdrant.
    """
    query = """
    CREATE (proto:ProtoConcept {
        concept_id: $concept_id,
        concept_name: $concept_name,
        concept_type: $concept_type,
        confidence: $confidence,
        tenant_id: $tenant_id,
        segment_id: $segment_id,
        chunk_ids: $chunk_ids,  // ← NOUVEAU champ
        created_at: datetime(),
        metadata: $metadata_json
    })
    RETURN proto.concept_id AS concept_id
    """
```

#### b) Méthode `promote_to_published()` (ligne ~311)
```python
def promote_to_published(
    self,
    tenant_id: str,
    proto_concept_id: str,
    canonical_name: str,
    unified_definition: str,
    quality_score: float = 0.0,
    metadata: Optional[Dict[str, Any]] = None,
    decision_trace_json: Optional[str] = None,
    surface_form: Optional[str] = None,
    deduplicate: bool = True,
    chunk_ids: Optional[List[str]] = None  # ← NOUVEAU paramètre
) -> str:
    """
    Promouvoir ProtoConcept vers Published avec agrégation chunk_ids.
    """
    # Si déduplication, agréger chunk_ids de tous les ProtoConcepts
    if deduplicate and existing_canonical_id:
        # Récupérer chunk_ids existants + nouveaux
        aggregated_chunk_ids = self._aggregate_chunk_ids(
            existing_canonical_id,
            proto_concept_id
        )
        # Mettre à jour CanonicalConcept.chunk_ids
```

#### c) Nouvelle méthode `_aggregate_chunk_ids()` (NOUVEAU)
```python
def _aggregate_chunk_ids(
    self,
    canonical_id: str,
    proto_concept_id: str
) -> List[str]:
    """
    Agréger chunk_ids depuis CanonicalConcept existant + ProtoConcept.

    Returns:
        Liste unique chunk_ids (dédupliqués)
    """
    query = """
    MATCH (canonical:CanonicalConcept {canonical_id: $canonical_id})
    MATCH (proto:ProtoConcept {concept_id: $proto_concept_id})
    RETURN canonical.chunk_ids AS existing_chunks, proto.chunk_ids AS new_chunks
    """
```

---

### 3. Qdrant Client (MODIFICATION)

**Fichier** : `src/knowbase/common/clients/qdrant_client.py`

**Modifications** :

#### a) Nouvelle méthode `upsert_chunks()` (NOUVEAU)
```python
def upsert_chunks(
    self,
    chunks: List[Dict[str, Any]],
    collection_name: str = "knowbase",
    tenant_id: str = "default"
) -> List[str]:
    """
    Insérer chunks dans Qdrant avec proto_concept_ids.

    Args:
        chunks: [
            {
                "text": "...",
                "embedding": [...],
                "document_id": "doc-123",
                "segment_id": "segment-1",
                "proto_concept_ids": ["proto-123"],
                "chunk_index": 0
            }
        ]

    Returns:
        List of chunk_ids (UUIDs générés)
    """
```

#### b) Nouvelle méthode `update_chunks_with_canonical_ids()` (NOUVEAU)
```python
def update_chunks_with_canonical_ids(
    self,
    chunk_ids: List[str],
    canonical_concept_id: str,
    collection_name: str = "knowbase"
) -> bool:
    """
    Mettre à jour chunks avec canonical_concept_id après promotion.

    Args:
        chunk_ids: IDs des chunks à mettre à jour
        canonical_concept_id: ID du CanonicalConcept promu
    """
```

---

### 4. OSMOSE Agentique (MODIFICATION)

**Fichier** : `src/knowbase/ingestion/osmose_agentique.py`

**Modifications** :

#### a) Ajout import chunker (ligne ~30)
```python
from knowbase.ingestion.text_chunker import TextChunker
```

#### b) Init chunker dans `__init__()` (ligne ~100)
```python
def __init__(
    self,
    config: Optional[OsmoseIntegrationConfig] = None,
    qdrant_client: Optional[QdrantClient] = None,
    neo4j_client: Optional[Neo4jClient] = None
):
    # ... existing code ...

    # NOUVEAU: Init text chunker
    self.text_chunker = TextChunker(
        model_name="intfloat/multilingual-e5-large",
        chunk_size=512,
        overlap=128
    )
    logger.info("[OSMOSE] TextChunker initialized (512 tokens, overlap 128)")
```

#### c) Nouvelle méthode `_create_chunks_in_qdrant()` (NOUVEAU, ligne ~450)
```python
def _create_chunks_in_qdrant(
    self,
    text_content: str,
    document_id: str,
    state: AgentState,
    result_metrics: Dict[str, Any]
) -> Dict[str, List[str]]:
    """
    Créer chunks texte dans Qdrant avec références concepts.

    Returns:
        concept_to_chunk_ids: {
            "proto-123": ["chunk-456", "chunk-789"],
            "proto-124": ["chunk-456"]
        }
    """
    try:
        # 1. Découper texte en chunks + embeddings
        chunks = self.text_chunker.chunk_document(
            text=text_content,
            document_id=document_id,
            segment_id=state.segments[0].segment_id if state.segments else "segment-0",
            concepts=state.candidates  # Concepts extraits par Extractor
        )

        # 2. Insérer chunks dans Qdrant
        chunk_ids = self.qdrant_client.upsert_chunks(
            chunks=chunks,
            collection_name="knowbase",
            tenant_id=state.tenant_id
        )

        # 3. Construire mapping concept → chunk_ids
        concept_to_chunk_ids = {}
        for chunk, chunk_id in zip(chunks, chunk_ids):
            for proto_id in chunk.get("proto_concept_ids", []):
                if proto_id not in concept_to_chunk_ids:
                    concept_to_chunk_ids[proto_id] = []
                concept_to_chunk_ids[proto_id].append(chunk_id)

        logger.info(
            f"[OSMOSE:Chunks] Created {len(chunk_ids)} chunks in Qdrant "
            f"({len(concept_to_chunk_ids)} concepts referenced)"
        )

        return concept_to_chunk_ids

    except Exception as e:
        logger.error(f"[OSMOSE:Chunks] Error creating chunks: {e}")
        return {}
```

#### d) Modification `process_document()` (ligne ~140)
```python
async def process_document(
    self,
    text_content: str,
    document_id: str,
    filename: Optional[str] = None,
    tenant: str = "default"
) -> OsmoseIntegrationResult:
    """
    Process document via SupervisorAgent FSM + create chunks in Qdrant.
    """
    # ... existing FSM execution ...

    # NOUVEAU: Créer chunks APRÈS extraction concepts, AVANT promotion
    concept_to_chunk_ids = self._create_chunks_in_qdrant(
        text_content=text_content,
        document_id=document_id,
        state=final_state,
        result_metrics=result_metrics
    )

    # Ajouter chunk_ids au state pour utilisation par Gatekeeper
    final_state.concept_to_chunk_ids = concept_to_chunk_ids

    # Continue avec promotion (Gatekeeper utilisera chunk_ids)
    # ...
```

---

### 5. Gatekeeper Delegate (MODIFICATION)

**Fichier** : `src/knowbase/agents/gatekeeper/gatekeeper.py`

**Modifications** :

#### a) Ajout champ `concept_to_chunk_ids` dans `AgentState` (base.py ligne ~50)
```python
class AgentState(BaseModel):
    # ... existing fields ...
    concept_to_chunk_ids: Dict[str, List[str]] = Field(default_factory=dict)  # ← NOUVEAU
```

#### b) Modification `_promote_concepts_tool()` (ligne ~580)
```python
def _promote_concepts_tool(self, tool_input: PromoteConceptsInput) -> ToolOutput:
    """
    Promouvoir concepts vers Published-KG avec chunk_ids.
    """
    # ... existing promotion logic ...

    for candidate in passed_candidates:
        proto_concept_id = candidate["id"]
        concept_name = candidate["name"]

        # NOUVEAU: Récupérer chunk_ids pour ce concept
        chunk_ids = state.concept_to_chunk_ids.get(proto_concept_id, [])

        # Promotion avec chunk_ids
        canonical_id = self.neo4j_client.promote_to_published(
            tenant_id=state.tenant_id,
            proto_concept_id=proto_concept_id,
            canonical_name=canonical_name,
            unified_definition=unified_definition,
            quality_score=quality_score,
            metadata=metadata,
            decision_trace_json=decision_trace_json,
            surface_form=concept_name,
            deduplicate=True,
            chunk_ids=chunk_ids  # ← NOUVEAU paramètre
        )

        # NOUVEAU: Mettre à jour chunks Qdrant avec canonical_id
        if chunk_ids:
            self.qdrant_client.update_chunks_with_canonical_ids(
                chunk_ids=chunk_ids,
                canonical_concept_id=canonical_id
            )
```

---

## 📊 Impact & Métriques

### Métriques Attendues

| Métrique | Avant | Après (Attendu) |
|----------|-------|-----------------|
| **Chunks Qdrant `knowbase`** | 0 | ~50-100 par document |
| **Concepts avec chunk_ids** | 0% | 100% |
| **Chunks avec concept_ids** | 0% | 100% |
| **Cross-référence bidirectionnelle** | ❌ | ✅ |

### Cas d'Usage Activés

1. ✅ **Recherche Concept → Texte** : `GET /api/concepts/{id}/chunks`
2. ✅ **Recherche Vectorielle → Graphe** : `POST /api/search/hybrid`
3. ✅ **Enrichissement contextuel** : Concept + Relations + Chunks textuels
4. ✅ **Fallback intelligent** : Neo4j → Qdrant si 0 résultats

---

## 🧪 Tests Validation

### Test 1 : Création Chunks

**Input** : Document PDF 3 pages (~1500 mots)

**Assertions** :
```python
# Vérifier Qdrant
chunks = qdrant_client.search("knowbase", limit=100, filter={"document_id": "doc-123"})
assert len(chunks) >= 5  # Au moins 5 chunks

# Vérifier payload
assert chunks[0].payload["proto_concept_ids"] != []
assert chunks[0].payload["tenant_id"] == "default"
```

### Test 2 : Cross-Référence Neo4j → Qdrant

**Input** : Concept "SAP S/4HANA"

**Assertions** :
```cypher
MATCH (c:CanonicalConcept {canonical_name: "SAP S/4HANA"})
RETURN c.chunk_ids AS chunk_ids

-- Vérifier que chunk_ids non vide
assert len(chunk_ids) >= 1

-- Fetch chunks depuis Qdrant
chunks = qdrant_client.retrieve(chunk_ids)
assert all(c.payload["canonical_concept_ids"] == ["canon-001"] for c in chunks)
```

### Test 3 : Cross-Référence Qdrant → Neo4j

**Input** : Recherche vectorielle "cloud migration"

**Assertions** :
```python
# Recherche Qdrant
chunks = qdrant_client.search("knowbase", query_vector=embed("cloud migration"), limit=5)

# Extraire concept_ids
concept_ids = []
for chunk in chunks:
    concept_ids.extend(chunk.payload["canonical_concept_ids"])

# Fetch concepts Neo4j
query = """
MATCH (c:CanonicalConcept)
WHERE c.canonical_id IN $concept_ids
RETURN c.canonical_name, c.chunk_ids
"""
concepts = neo4j_client.run(query, concept_ids=concept_ids)

assert len(concepts) >= 1
```

---

## 📅 Planning Implémentation

| Tâche | Durée | Status |
|-------|-------|--------|
| 1. Créer `text_chunker.py` | 2h | ⏳ EN COURS |
| 2. Modifier `neo4j_client.py` (chunk_ids) | 1h | ⏳ PENDING |
| 3. Modifier `qdrant_client.py` (upsert/update chunks) | 1h | ⏳ PENDING |
| 4. Modifier `osmose_agentique.py` (intégration chunker) | 2h | ⏳ PENDING |
| 5. Modifier `gatekeeper.py` (liaison chunks) | 1h | ⏳ PENDING |
| 6. Modifier `base.py` (AgentState.concept_to_chunk_ids) | 15min | ⏳ PENDING |
| 7. Tests unitaires | 2h | ⏳ PENDING |
| 8. Tests E2E | 1h | ⏳ PENDING |
| **TOTAL** | **10-11h** | **~1.5 jours** |

---

## 🔧 Fichiers Modifiés

### Nouveaux Fichiers
1. **`src/knowbase/ingestion/text_chunker.py`** (NOUVEAU, ~250 lignes)
2. **`tests/ingestion/test_text_chunker.py`** (NOUVEAU, ~150 lignes)
3. **`tests/integration/test_cross_reference_neo4j_qdrant.py`** (NOUVEAU, ~200 lignes)

### Fichiers Modifiés
4. **`src/knowbase/common/clients/neo4j_client.py`** (+80 lignes)
5. **`src/knowbase/common/clients/qdrant_client.py`** (+120 lignes)
6. **`src/knowbase/ingestion/osmose_agentique.py`** (+150 lignes)
7. **`src/knowbase/agents/gatekeeper/gatekeeper.py`** (+40 lignes)
8. **`src/knowbase/agents/base.py`** (+1 ligne)

---

## 🚀 Prochaines Étapes

1. ✅ Corriger erreur Neo4j (`!=` → `<>`) - **FAIT**
2. ⏳ Implémenter `TextChunker` - **EN COURS**
3. ⏳ Modifier Neo4j Client (chunk_ids)
4. ⏳ Modifier Qdrant Client (chunks)
5. ⏳ Intégrer chunker dans OSMOSE Agentique
6. ⏳ Modifier Gatekeeper (liaison)
7. ⏳ Tests E2E
8. ⏳ Commit + Documentation

---

**Auteur** : Claude Code
**Date** : 2025-10-17
**Version** : 1.0
**Statut** : 🟡 EN COURS (Étape 2/8)
