# ADR: Normalisation des Noms de Propriétés Python - Neo4j

**Date:** 2026-01-19
**Statut:** APPROUVÉ - En cours d'implémentation
**Auteur:** OSMOSE Team

## Contexte et Problème

Le codebase OSMOSE souffre d'incohérences systémiques entre les noms de propriétés des modèles Pydantic (Python) et les propriétés des nodes Neo4j. Ces incohérences causent des bugs récurrents difficiles à diagnostiquer.

**Exemple de bug récent:** `getattr(proto, 'concept_name', None)` retourne `None` car le champ Pydantic s'appelle `label`, pas `concept_name`.

## Décision

**Uniformiser sur les noms Neo4j** car ils sont plus descriptifs et cohérents.

Les noms Neo4j suivent une convention claire:
- Préfixes explicites: `concept_id`, `canonical_id`, `doc_id`
- Noms complets: `concept_name`, `canonical_name`, `unified_definition`
- Positions: `span_start`, `span_end` (relatif au conteneur)

---

## Mappings de Renommage

### 1. ProtoConcept

| Python Actuel | Neo4j | Python Cible | Impact |
|---------------|-------|--------------|--------|
| `id` | `concept_id` | `concept_id` | 70+ locations |
| `label` | `concept_name` | `concept_name` | 70+ locations |
| `document_id` | `doc_id` | `doc_id` | 50+ locations |

### 2. CanonicalConcept

| Python Actuel | Neo4j | Python Cible | Impact |
|---------------|-------|--------------|--------|
| `id` | `canonical_id` | `canonical_id` | 30+ locations |
| `label` | `canonical_name` | `canonical_name` | 30+ locations |
| `definition_consolidated` | `unified_definition` | `unified_definition` | 20+ locations |

### 3. Anchor

| Python Actuel | Neo4j | Python Cible | Impact |
|---------------|-------|--------------|--------|
| `char_start` | `span_start` | `span_start` | 100+ locations |
| `char_end` | `span_end` | `span_end` | 100+ locations |
| `quote` | `surface_form` | `surface_form` | 50+ locations |

### 4. Document

| Python Actuel | Neo4j | Python Cible | Impact |
|---------------|-------|--------------|--------|
| `document_id` | `doc_id` | `doc_id` | 150+ locations |
| `title` | `name` | `name` | 50+ locations |

---

## Fichiers à Modifier par Entité

### ProtoConcept (70+ fichiers)

#### Définition du Modèle
- `src/knowbase/api/schemas/concepts.py` (lignes 273-329)
  - `id: str` -> `concept_id: str`
  - `label: str` -> `concept_name: str`
  - `document_id: str` -> `doc_id: str`

#### Persistence Layer (CRITIQUE)
- `src/knowbase/ingestion/osmose_persistence.py`
  - Lignes 244, 246, 271-276: Mapping dict pour Neo4j
  - Lignes 1323, 1360-1366: getattr patterns

#### Service Layer
- `src/knowbase/agents/gatekeeper/anchor_based_scorer.py` (102, 136, 137, 175, 176, 336, 363)
- `src/knowbase/api/services/concept_diff_service.py` (306-709)
- `src/knowbase/consolidation/corpus_promotion.py` (426-482, 818)
- `src/knowbase/ingestion/osmose_agentique.py` (1051, 1089)
- `src/knowbase/relations/segment_window_relation_extractor.py` (897)
- `src/knowbase/linguistic/coref_persist.py` (516)
- `src/knowbase/ingestion/pipelines/pass05_coref.py` (987)
- `src/knowbase/api/routers/admin.py` (525)
- `src/knowbase/ingestion/pass2_orchestrator.py` (1314)

#### Scripts
- `app/scripts/fix_anchored_in_textual.py` (50, 54, 83, 88, 103, 135, 142, 163, 166, 205, 209, 238, 243)
- `app/scripts/migrate_lex_key.py` (139)
- `app/scripts/migrate_coverage_to_option_c.py` (208, 238, 312)
- `scripts/backfill_mentioned_in.py` (41)
- `scripts/migrate_lex_key.py`

---

### CanonicalConcept (30+ fichiers)

#### Définition du Modèle
- `src/knowbase/api/schemas/concepts.py` (lignes 417-456)
  - `id: str` -> `canonical_id: str`
  - `label: str` -> `canonical_name: str`
  - `definition_consolidated: Optional[str]` -> `unified_definition: Optional[str]`

#### Persistence Layer
- `src/knowbase/ingestion/osmose_persistence.py`
  - Lignes 302-313: Neo4j MERGE mapping
  - Lignes 323-325: Dict construction
  - Lignes 969-970: Extraction pour relations

#### Service Layer
- `src/knowbase/agents/gatekeeper/anchor_based_scorer.py` (355-365)
- `src/knowbase/consolidation/corpus_promotion.py` (818-819)
- `src/knowbase/api/routers/markers.py` (506, 523)
- `src/knowbase/consolidation/normalization/normalization_engine.py` (669)

---

### Anchor (100+ fichiers)

#### Définition du Modèle
- `src/knowbase/api/schemas/concepts.py` (lignes 149-210)
  - `char_start: int` -> `span_start: int`
  - `char_end: int` -> `span_end: int`
  - `quote: str` -> `surface_form: str`

#### Core Extraction
- `src/knowbase/semantic/extraction/hybrid_anchor_extractor.py` (384-385)
- `src/knowbase/semantic/anchor_resolver.py` (151-152, 379, 523)
- `src/knowbase/ingestion/hybrid_anchor_chunker.py` (560-561, 625-626, 211-212, 303-328, 372-398, 460-484, 552-566, 700-701, 770)

#### Persistence
- `src/knowbase/ingestion/osmose_persistence.py` (707-708, 717-718, 727, 1335-1336, 1392-1394, 1402)
- `src/knowbase/ingestion/osmose_agentique.py` (279, 1093-1094)
- `src/knowbase/ingestion/osmose_enrichment.py` (84)
- `src/knowbase/structural/graph_builder.py` (724)

#### Relations/Evidence
- `src/knowbase/relations/evidence_bundle_models.py` (89, 93, 274-304)
- `src/knowbase/relations/confidence_calculator.py` (91-92, 295-327)
- `src/knowbase/relations/predicate_extractor.py` (77-78, 460-464)
- `src/knowbase/relations/bundle_validator.py` (192-214)
- `src/knowbase/relations/candidate_detector.py` (291)
- `src/knowbase/relations/segment_window_relation_extractor.py` (456-457)
- `src/knowbase/relations/bundle_persistence.py` (444-445)
- `src/knowbase/relations/structural_topic_extractor.py` (44-45, 538-539)

#### Layout/Extraction
- `src/knowbase/extraction_v2/layout/layout_detector.py` (55-63, 89-90, 499-500)
- `src/knowbase/extraction_v2/context/candidate_mining.py` (907-917)

#### Chunking
- `src/knowbase/ingestion/text_chunker.py` (118-119, 159-160, 235-236, 267-268, 414-415, 453-454)
- `src/knowbase/common/clients/qdrant_client.py` (241-242, 280-281)

#### Services
- `src/knowbase/api/services/search.py` (249)
- `src/knowbase/api/services/hybrid_anchor_search.py` (109)
- `src/knowbase/semantic/classification/fine_classifier.py` (299)
- `src/knowbase/semantic/classification/heuristic_classifier.py` (333)

---

### Document (150+ fichiers)

#### Définition du Modèle
- `src/knowbase/api/schemas/documents.py`
  - Ligne 33: `title: str` -> `name: str`
  - Ligne 47: `title: Optional[str]` -> `name: Optional[str]`
  - Ligne 55: `document_id: str` -> `doc_id: str`
  - Lignes 80, 120, 163, 171, 205: `document_id` -> `doc_id`

#### Service Layer
- `src/knowbase/api/services/document_registry_service.py` (85, 93, 109, 127-128, 158, 166, 180-181, 234-235, 328-329, 361, 363, 389, 396, 415)
- `src/knowbase/common/clients/neo4j_client.py` (232, 279, 298, 323, 350-352, 367, 386)

#### Routers
- `src/knowbase/api/routers/documents.py` (84, 731)

#### Ingestion
- `src/knowbase/ingestion/burst/artifact_importer.py` (41, 119, 124, 196, 214, 301, 321, 339, 350, 465)
- `src/knowbase/ingestion/text_chunker.py` (78, 94, 352, 371)
- `src/knowbase/structural/archiver.py` (38, 61, 126, 228-531)

**Note:** `DocItem` et modèles structurels utilisent déjà `doc_id` - bon exemple à suivre.

---

## Ordre de Migration Recommandé

### Phase 1: Modèles Pydantic (Breaking Changes)
1. **ProtoConcept** - `src/knowbase/api/schemas/concepts.py`
2. **CanonicalConcept** - `src/knowbase/api/schemas/concepts.py`
3. **Anchor** - `src/knowbase/api/schemas/concepts.py`
4. **Document schemas** - `src/knowbase/api/schemas/documents.py`

### Phase 2: Persistence Layer
1. `src/knowbase/ingestion/osmose_persistence.py`
2. `src/knowbase/consolidation/corpus_promotion.py`
3. `src/knowbase/common/clients/neo4j_client.py`

### Phase 3: Service Layer
1. Services concept (diff, explainer, etc.)
2. Services document (registry, etc.)
3. Services search (hybrid, etc.)

### Phase 4: Extraction/Ingestion
1. `hybrid_anchor_extractor.py`, `anchor_resolver.py`
2. `hybrid_anchor_chunker.py`, `text_chunker.py`
3. `osmose_agentique.py`, `osmose_enrichment.py`

### Phase 5: Relations
1. `evidence_bundle_models.py`
2. `confidence_calculator.py`, `predicate_extractor.py`
3. Autres fichiers relations

### Phase 6: Scripts et Tests
1. Tous les scripts de migration
2. Tous les tests unitaires

### Phase 7: Frontend
1. `frontend/src/types/api.ts`
2. `frontend/src/types/graph.ts`
3. Composants utilisant ces types

---

## Vérification Post-Migration

```bash
# Vérifier qu'aucun ancien nom n'est utilisé (après migration)
grep -r "\.label" src/knowbase --include="*.py" | grep -v "canonical_name\|concept_name"
grep -r "char_start\|char_end" src/knowbase --include="*.py"
grep -r "\.quote" src/knowbase --include="*.py" | grep -v "surface_form"
grep -r "document_id" src/knowbase --include="*.py" | grep -v "doc_id"
```

---

## Risques et Mitigations

| Risque | Probabilité | Impact | Mitigation |
|--------|-------------|--------|------------|
| Oubli d'un fichier | Haute | Moyen | Grep exhaustif + tests |
| API Breaking Change | Certaine | Haut | Communiquer aux clients |
| Données Neo4j invalides | Faible | Haut | Purge + réingestion |
| Tests cassés | Certaine | Moyen | MAJ tests en même temps |

---

## Références

- Bug original: `getattr(proto, 'concept_name', None)` retournait `None`
- Fichiers affectés: 200+ locations dans 70+ fichiers
- Temps estimé: 4-8 heures de refactoring
