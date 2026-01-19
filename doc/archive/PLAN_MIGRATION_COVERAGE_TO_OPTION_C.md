# Plan de Migration : CoverageChunk → Option C

**Date**: 2026-01-16
**Status**: DRAFT
**Impact**: Simplification architecture chunking, alignement section_id

---

## 1. Contexte

### Situation actuelle

Deux systèmes de chunking coexistent :

| Système | Fichiers | Usage |
|---------|----------|-------|
| **Legacy** | `coverage_chunk_generator.py`, `hybrid_anchor_chunker.py` | CoverageChunk → DocumentChunk (Neo4j) |
| **Option C** | `structural/type_aware_chunker.py`, `structural/graph_builder.py` | DocItem → SectionContext → TypeAwareChunk |

### Problème identifié

1. **CoverageChunks** n'ont pas de `context_id` rempli
2. **ProtoConcepts** ont un `section_id` textuel (`"5. Custom Code Migration / cluster_0"`)
3. **SectionContext** ont un `section_id` UUID (`"sec_root_013b1f"`)
4. **Mismatch** → MENTIONED_IN vers SectionContext = 0 → COVERS = 0

### Objectif

Retirer les CoverageChunks et utiliser uniquement le système Option C pour :
- Simplifier l'architecture (1 seul système de chunking)
- Aligner les `section_id` entre extraction et structure
- Restaurer la chaîne MENTIONED_IN → COVERS

---

## 2. Analyse des dépendances

### Ce que font les CoverageChunks

```
Extraction Pass 1
    └→ CoverageChunkGenerator.generate()
        └→ CoverageChunk (char_start, char_end, context_id=None)
            └→ Persisté comme DocumentChunk dans Neo4j
                └→ ANCHORED_IN (ProtoConcept → DocumentChunk)
                    └→ Preuve de position du concept
```

### Ce que fait Option C

```
Docling Parse
    └→ DocItemBuilder.build()
        └→ DocItem (charspan_start, charspan_end, section_id)
            └→ SectionProfiler.assign_sections()
                └→ SectionContext (section_id UUID, section_path)
                    └→ TypeAwareChunker.create_chunks()
                        └→ TypeAwareChunk (section_id, item_ids, kind)
```

### Relations impactées

| Relation | Source | Cible | Usage |
|----------|--------|-------|-------|
| `ANCHORED_IN` | ProtoConcept | DocumentChunk | Preuve position |
| `MENTIONED_IN` | CanonicalConcept | SectionContext | Scope section |
| `COVERS` | Topic | CanonicalConcept | Couverture thématique |

---

## 3. Plan de migration

### Phase 1 : Alignement section_id (PRIORITAIRE)

**Objectif** : Le `section_id` sur ProtoConcept doit matcher celui des SectionContext.

**Modification** : `src/knowbase/extraction_v2/pipeline.py`

```python
# AVANT (extraction génère un chemin texte)
proto.section_id = f"{section_path} / cluster_{i}"

# APRÈS (extraction récupère le section_id de Option C)
# Option A: Passer le section_id depuis TypeAwareChunk
proto.section_id = chunk.section_id  # UUID format

# Option B: Lookup SectionContext par position
section = find_section_by_position(doc_id, anchor.char_start)
proto.section_id = section.section_id if section else None
```

**Fichiers à modifier** :
- `src/knowbase/extraction_v2/pipeline.py` : Récupérer section_id depuis StructuralGraphBuildResult
- `src/knowbase/ingestion/osmose_persistence.py` : Utiliser section_id au lieu de context_id

### Phase 2 : Migration ANCHORED_IN

**Objectif** : Remplacer `ANCHORED_IN → DocumentChunk` par `ANCHORED_IN → DocItem` ou `TypeAwareChunk`.

**Option recommandée** : ANCHORED_IN → DocItem (plus précis)

```cypher
-- AVANT
(ProtoConcept)-[:ANCHORED_IN {span_start, span_end}]->(DocumentChunk)

-- APRÈS
(ProtoConcept)-[:ANCHORED_IN {span_start, span_end}]->(DocItem)
```

**Avantages DocItem** :
- Positions exactes (`charspan_start`, `charspan_end`)
- Lié à SectionContext via `section_id`
- Granularité plus fine (paragraphe vs chunk 800 tokens)

**Fichiers à modifier** :
- `src/knowbase/ingestion/osmose_persistence.py` :
  - Fonction `anchor_proto_concepts_to_chunks` → `anchor_proto_concepts_to_docitems`
  - Matcher par position (`anchor.char_start` dans `[DocItem.charspan_start, charspan_end]`)

### Phase 3 : Suppression CoverageChunks

**Fichiers à supprimer** :
- `src/knowbase/ingestion/coverage_chunk_generator.py`
- Références dans `src/knowbase/ingestion/chunk_alignment.py`

**Fichiers à modifier** :
- `src/knowbase/extraction_v2/pipeline.py` : Retirer génération CoverageChunks
- `src/knowbase/ingestion/osmose_persistence.py` : Retirer code DocumentChunk

### Phase 4 : Migration MENTIONED_IN

**Modification** : `src/knowbase/consolidation/corpus_promotion.py`

```python
# AVANT (utilise context_id)
MATCH (s:SectionContext {context_id: ctx_id, tenant_id: $tenant_id})

# APRÈS (utilise section_id directement)
MATCH (s:SectionContext {section_id: $section_id, tenant_id: $tenant_id})
```

### Phase 5 : Validation COVERS

Après phases 1-4, vérifier :
```cypher
-- MENTIONED_IN vers SectionContext
MATCH ()-[r:MENTIONED_IN]->(s:SectionContext) RETURN count(r)
-- Devrait être > 0

-- COVERS créées par Pass 2a
MATCH ()-[r:COVERS]->() RETURN count(r)
-- Devrait être > 0 après exécution Pass 2a
```

---

## 4. Ordre d'implémentation

1. **Phase 1** : Alignement section_id (bloquant pour tout le reste)
2. **Phase 4** : Migration MENTIONED_IN (dépend de Phase 1)
3. **Phase 2** : Migration ANCHORED_IN (peut être fait en parallèle)
4. **Phase 3** : Suppression CoverageChunks (après validation Phases 1-2)
5. **Phase 5** : Validation end-to-end

---

## 5. Risques et mitigations

| Risque | Mitigation |
|--------|------------|
| Documents existants sans DocItem | Script de migration pour réimporter |
| Performance lookup par position | Index Neo4j sur `charspan_start` |
| Perte de données ANCHORED_IN | Conserver DocumentChunk en lecture seule pendant transition |

---

## 6. Métriques de succès

- [ ] 100% ProtoConcepts avec `section_id` format UUID
- [ ] MENTIONED_IN vers SectionContext > 0
- [ ] COVERS > 0 après Pass 2a
- [ ] 0 dépendance sur CoverageChunk/DocumentChunk

---

## 7. Estimation effort

| Phase | Complexité | Fichiers |
|-------|------------|----------|
| Phase 1 | Moyenne | 2 fichiers |
| Phase 2 | Moyenne | 1 fichier |
| Phase 3 | Faible | 2 fichiers |
| Phase 4 | Faible | 1 fichier |
| Phase 5 | Faible | Tests |

**Total estimé** : 6 fichiers à modifier, 1 à supprimer
